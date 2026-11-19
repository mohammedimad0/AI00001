"""Turns Alertmanager JSON and Loki JSON into one list of Event objects."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .fingerprint import fingerprint
from .geo import country_of
from .models import Event

# Alertmanager alertname -> error_type
ALERT_TYPES = {
    "PostgresDown": "db_down",
    "DiskAlmostFull": "disk_full",
    "HighCPU": "high_cpu",
}

# Log text patterns -> error_type (first match wins)
LOG_RULES = [
    (re.compile(r"login failed|authentication failed|invalid password", re.I), "auth_failure"),
    (re.compile(r"connection refused to ([\w.-]+)", re.I), "db_down"),
    (re.compile(r"no space left|disk .* full", re.I), "disk_full"),
    (re.compile(r"slow request", re.I), "slow_request"),
    (re.compile(r"ssl handshake failed (?:to|with) ([\w.-]+).*certificate has expired", re.I), "tls_expired"),
]

IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
LOG_LINE_RE = re.compile(r"^(\S+)\s+(\w+)\s+(.*)$")


def _parse_time(s: str) -> datetime | None:
    if not s or s.startswith("0001-"):
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def from_alertmanager(payload: dict) -> list[Event]:
    events = []
    for a in payload.get("alerts", []):
        labels = a.get("labels", {})
        host = labels.get("instance", "unknown").split(":")[0]
        name = labels.get("alertname", "")
        error_type = ALERT_TYPES.get(name, "unknown")
        message = a.get("annotations", {}).get("summary", name)
        ev = Event(
            timestamp=_parse_time(a["startsAt"]),
            source="prometheus",
            host=host,
            service=host,                     # for infra alerts the host IS the affected thing
            error_type=error_type,
            message=message,
            level=labels.get("severity", "warning").upper(),
            resolved_at=_parse_time(a.get("endsAt", "")),
            labels=labels,
        )
        ev.template, ev.fingerprint = fingerprint(ev.error_type, ev.service, message)
        events.append(ev)
    return events


def from_loki(response: dict) -> list[Event]:
    events = []
    for stream in response.get("data", {}).get("result", []):
        meta = stream.get("stream", {})
        host = meta.get("host", "unknown")
        job = meta.get("job", "unknown")
        for ns, line in stream.get("values", []):
            m = LOG_LINE_RE.match(line)
            level, text = (m.group(2), m.group(3)) if m else ("INFO", line)
            ts = datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc)

            error_type, service = "unknown", job
            for pattern, etype in LOG_RULES:
                hit = pattern.search(text)
                if hit:
                    error_type = etype
                    # If the rule captured a target, that target is the affected service:
                    # "connection refused to db-primary:5432"     -> db-primary
                    # "SSL handshake failed to api-gateway:443"   -> api-gateway
                    if hit.groups():
                        service = hit.group(1).split(":")[0]
                    break

            ip_hit = IP_RE.search(text)
            src_ip = ip_hit.group(1) if ip_hit and error_type == "auth_failure" else None

            ev = Event(
                timestamp=ts, source="loki", host=host, service=service,
                error_type=error_type, message=text, level=level,
                src_ip=src_ip, country=country_of(src_ip), labels=meta,
            )
            ev.template, ev.fingerprint = fingerprint(ev.error_type, ev.service, text)
            events.append(ev)
    return events


def normalize(alertmanager_payload: dict, loki_response: dict) -> list[Event]:
    events = from_alertmanager(alertmanager_payload) + from_loki(loki_response)
    return sorted(events, key=lambda e: e.timestamp)
