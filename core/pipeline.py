"""Glues the stages together: normalize -> dedup/group -> score."""
from __future__ import annotations

from . import config as C
from .models import Event, Incident
from .normalizer import normalize
from .scoring import score_incident


def group_events(events: list[Event]) -> list[Incident]:
    """Dedup + correlate in one pass.

    Dedup:      identical messages (same fingerprint) are counted, not repeated.
    Correlate:  different messages about the same fault join one incident.
                Key = (error_type, affected service, risky origin country).
                So the PostgresDown alert and 200 'connection refused' logs
                become ONE incident about db-primary.
    """
    open_incidents: dict[tuple, Incident] = {}
    closed: list[Incident] = []
    counter = 0

    for ev in sorted(events, key=lambda e: e.timestamp):
        key = (ev.error_type, ev.service, ev.country)
        inc = open_incidents.get(key)

        if inc and ev.timestamp - inc.last_seen > C.INCIDENT_GAP:
            closed.append(inc)          # too long since last event: start fresh
            inc = None

        if inc is None:
            counter += 1
            inc = Incident(id=f"INC-{counter:04d}", error_type=ev.error_type,
                           service=ev.service, country=ev.country)
            open_incidents[key] = inc
        inc.add(ev)

    return closed + list(open_incidents.values())


def run(alertmanager_payload: dict, loki_response: dict) -> dict:
    events = normalize(alertmanager_payload, loki_response)
    incidents = [score_incident(i) for i in group_events(events)]
    incidents.sort(key=lambda i: i.score, reverse=True)
    return {
        "raw_event_count": len(events),
        "incident_count": len(incidents),
        "paged_count": sum(1 for i in incidents if i.band == "critical"),
        "events": events,
        "incidents": incidents,
    }
