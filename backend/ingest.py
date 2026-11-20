"""One delivery of alerts/logs in -> database updated -> dashboards told -> LLM jobs queued."""
from __future__ import annotations

from sqlmodel import Session

from . import llm_worker, sse
from .db import WRITE_LOCK, IncidentRow, engine
from .flow import GRAPH
from .incidents import compute_stats, to_api


def process(alertmanager: dict | None = None, loki: dict | None = None) -> dict:
    with WRITE_LOCK, Session(engine) as s:
        out = GRAPH.invoke({"db": s, "alertmanager": alertmanager, "loki": loki})
        new_ids = out.get("new_ids", [])
        updated_ids = [i for i in out.get("touched", []) if i not in new_ids]
        messages = [("new_incident", to_api(s.get(IncidentRow, i))) for i in new_ids]
        messages += [("incident_updated", to_api(s.get(IncidentRow, i))) for i in updated_ids]
        stats = compute_stats(s)

    # Tell the dashboards (outside the lock: no need to hold others up)
    for event, data in messages:
        sse.publish(event, data)
    sse.publish("stats", stats)

    llm_jobs = out.get("llm_jobs", [])
    for inc_id in llm_jobs:
        llm_worker.submit(inc_id)

    received = len(out.get("events", []))
    return {
        "received": received,
        "stored": received - out.get("duplicates", 0),
        "duplicates": out.get("duplicates", 0),
        "new_incidents": new_ids,
        "updated_incidents": updated_ids,
        "looked_up": out.get("lookup", []),
        "llm_queued": llm_jobs,
    }
