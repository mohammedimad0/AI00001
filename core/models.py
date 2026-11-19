"""Data shapes used across the pipeline.

Event    = one normalized alert or log line (the "one JSON schema").
Incident = many events that describe the same underlying problem.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    timestamp: datetime
    source: str                 # "prometheus" or "loki"
    host: str                   # machine that reported it
    service: str                # the thing that is actually affected
    error_type: str             # e.g. auth_failure, disk_full, db_down
    message: str                # original text
    level: str = "ERROR"
    src_ip: str | None = None   # attacker / client IP, if any
    country: str | None = None  # filled in by geo lookup
    resolved_at: datetime | None = None
    labels: dict = field(default_factory=dict)
    template: str = ""          # message with variable parts stripped
    fingerprint: str = ""       # short hash of the template

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "host": self.host,
            "service": self.service,
            "error_type": self.error_type,
            "level": self.level,
            "message": self.message,
            "src_ip": self.src_ip,
            "country": self.country,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "fingerprint": self.fingerprint,
            "template": self.template,
        }


@dataclass
class Incident:
    id: str
    error_type: str
    service: str
    country: str | None
    events: list[Event] = field(default_factory=list)
    fingerprints: dict[str, dict] = field(default_factory=dict)  # fp -> {template, count}
    score: int = 0
    band: str = ""
    factors: list[dict] = field(default_factory=list)

    # ---- derived properties -------------------------------------------
    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def first_seen(self) -> datetime:
        return min(e.timestamp for e in self.events)

    @property
    def last_seen(self) -> datetime:
        return max(e.timestamp for e in self.events)

    @property
    def hosts(self) -> set[str]:
        return {e.host for e in self.events}

    @property
    def sources(self) -> set[str]:
        return {e.source for e in self.events}

    @property
    def title(self) -> str:
        from .config import ERROR_LABELS
        label = ERROR_LABELS.get(self.error_type, self.error_type)
        where = f" on {self.service}"
        origin = f" from {self.country}" if self.country else ""
        return f"{label}{where}{origin}"

    def add(self, event: Event) -> None:
        self.events.append(event)
        fp = self.fingerprints.setdefault(
            event.fingerprint, {"template": event.template, "count": 0}
        )
        fp["count"] += 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "error_type": self.error_type,
            "service": self.service,
            "country": self.country,
            "score": self.score,
            "band": self.band,
            "factors": self.factors,
            "event_count": self.count,
            "unique_messages": len(self.fingerprints),
            "fingerprints": self.fingerprints,
            "hosts": sorted(self.hosts),
            "sources": sorted(self.sources),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "sample_events": [e.to_dict() for e in self.events[:5]],
        }
