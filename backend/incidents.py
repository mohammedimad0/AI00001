"""Small helpers between the database rows and the rest of the system.

- event_from_row / row_from_event: database row <-> core Event (so core/ code is reused as-is)
- load_incident: rebuild a core Incident from all its stored events (to rescore it)
- incident_dict: the 3_incidents.json shape that rag/ and llm/ expect
- to_api: what the API sends to the dashboard
- set_resolution: store a new fix suggestion (and keep the history)
- compute_stats: the noise counter numbers
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlmodel import Session, func, select

from core.models import Event, Incident
from core.scoring import action_for

from .db import EventRow, FeedbackRow, IncidentRow, ResolutionRow, as_utc, to_utc, utcnow

BANDS = ("critical", "high", "medium", "low")


def event_from_row(r: EventRow) -> Event:
    return Event(
        timestamp=as_utc(r.timestamp), source=r.source, host=r.host, service=r.service,
        error_type=r.error_type, message=r.message, level=r.level, src_ip=r.src_ip,
        country=r.country, resolved_at=as_utc(r.resolved_at), labels=r.labels or {},
        template=r.template, fingerprint=r.fingerprint,
    )


def row_from_event(ev: Event, incident_id: str, dedup_key: str) -> EventRow:
    return EventRow(
        dedup_key=dedup_key, incident_id=incident_id, timestamp=to_utc(ev.timestamp),
        source=ev.source, host=ev.host, service=ev.service, error_type=ev.error_type,
        level=ev.level, message=ev.message, src_ip=ev.src_ip, country=ev.country,
        resolved_at=to_utc(ev.resolved_at), template=ev.template,
        fingerprint=ev.fingerprint, labels=ev.labels,
    )


def load_incident(s: Session, row: IncidentRow) -> Incident:
    rows = s.exec(select(EventRow).where(EventRow.incident_id == row.id).order_by(EventRow.timestamp)).all()
    inc = Incident(id=row.id, error_type=row.error_type, service=row.service, country=row.country)
    for r in rows:
        inc.add(event_from_row(r))
    inc.score, inc.band, inc.factors = row.score, row.band, row.factors
    return inc


def incident_dict(s: Session, row: IncidentRow) -> dict:
    return load_incident(s, row).to_dict()


def set_resolution(s: Session, row: IncidentRow, resolution: dict) -> None:
    row.resolution = resolution
    row.updated_at = utcnow()
    s.add(row)
    s.add(ResolutionRow(incident_id=row.id, source=resolution.get("source", "none"), data=resolution))


def _iso(dt):
    dt = as_utc(dt)
    return dt.isoformat() if dt else None


def to_api(row: IncidentRow, s: Session | None = None, detail: bool = False) -> dict:
    d = {
        "id": row.id, "title": row.title, "error_type": row.error_type, "service": row.service,
        "country": row.country, "score": row.score, "band": row.band,
        "action": action_for(row.band), "factors": row.factors, "status": row.status,
        "event_count": row.event_count, "unique_messages": row.unique_messages,
        "fingerprints": row.fingerprints, "hosts": row.hosts, "sources": row.sources,
        "first_seen": _iso(row.first_seen), "last_seen": _iso(row.last_seen),
        "resolution": row.resolution, "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at),
    }
    if detail and s is not None:
        events = s.exec(select(EventRow).where(EventRow.incident_id == row.id)
                        .order_by(EventRow.timestamp)).all()
        d["sample_events"] = [event_from_row(e).to_dict() for e in events[:10]]
        per_minute = Counter(as_utc(e.timestamp).strftime("%Y-%m-%dT%H:%M") for e in events)
        d["timeline"] = [{"minute": m, "count": c} for m, c in sorted(per_minute.items())]
        d["feedback"] = [f.model_dump(exclude={"id", "incident_id"}) for f in s.exec(
            select(FeedbackRow).where(FeedbackRow.incident_id == row.id).order_by(FeedbackRow.created_at)).all()]
        d["resolution_history"] = [{"source": r.source, "created_at": _iso(r.created_at)} for r in s.exec(
            select(ResolutionRow).where(ResolutionRow.incident_id == row.id).order_by(ResolutionRow.id)).all()]
    return d


def compute_timeline(s: Session) -> list[dict]:
    """[{minute: "2026-11-20T10:05", raw: 42, incidents: 1}, ...] with empty minutes filled in."""
    raw = Counter(as_utc(t).replace(second=0, microsecond=0) for t in s.exec(select(EventRow.timestamp)).all())
    created = Counter(as_utc(t).replace(second=0, microsecond=0)
                      for t in s.exec(select(IncidentRow.first_seen)).all() if t)
    if not raw:
        return []
    minute, last = min(raw), max(raw)
    out = []
    while minute <= last:
        out.append({"minute": minute.strftime("%Y-%m-%dT%H:%M"), "raw": raw.get(minute, 0),
                    "incidents": created.get(minute, 0)})
        minute += timedelta(minutes=1)
    return out


def compute_stats(s: Session) -> dict:
    raw = s.exec(select(func.count()).select_from(EventRow)).one()
    rows = s.exec(select(IncidentRow)).all()
    by_band = {b: 0 for b in BANDS}
    by_status = {"open": 0, "acknowledged": 0, "resolved": 0}
    fixes = Counter()
    for r in rows:
        by_band[r.band] = by_band.get(r.band, 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1
        fixes[(r.resolution or {}).get("source", "none")] += 1
    return {
        "raw_events": raw,
        "incidents": len(rows),
        "pages": by_band["critical"],
        "noise_reduction_pct": round(100 * (1 - len(rows) / raw), 1) if raw else 0.0,
        "by_band": by_band,
        "by_status": by_status,
        "fixes": dict(fixes),
    }
