"""The INCREMENTAL LangGraph flow, used by the backend for every delivery of alerts/logs.

Step 3's graph/flow.py processes one big batch from scratch. A live system instead gets
small deliveries all day long, so this flow works against the database:

  normalize -> merge -> score -> rag_lookup --(all matched)------------> finalize
                                            \\--(some unmatched)-> queue_llm -/

  normalize   raw JSON -> Event objects (core/normalizer.py, unchanged)
  merge       drop exact re-sends, put each new event into an OPEN incident with the
              same (error type, service, country) if its last event was < 15 min ago,
              otherwise open a new incident
  score       rescore every incident that got new events (core/scoring.py, unchanged)
  rag_lookup  only for incidents that are NEW or whose BAND CHANGED: look for a runbook
  queue_llm   no runbook -> mark "llm_pending"; the LLM runs later in a background thread,
              so the webhook answers in milliseconds instead of waiting ~7 s
  finalize    save everything in one go (commit)
"""
from __future__ import annotations

import hashlib
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlmodel import Session, select

from core import config as C
from core.models import Event
from core.normalizer import from_alertmanager, from_loki
from core.scoring import score_incident
from rag import matcher

from .db import EventRow, IncidentRow, as_utc, to_utc, utcnow
from .incidents import incident_dict, load_incident, row_from_event, set_resolution


class State(TypedDict, total=False):
    db: Session                 # the open database session for this delivery
    alertmanager: dict | None   # raw input (either or both)
    loki: dict | None
    events: list[Event]         # after normalize
    duplicates: int             # re-sent events we already had
    new_ids: list[str]          # incidents created by this delivery
    touched: list[str]          # incidents that got new events (or a "resolved" update)
    lookup: list[str]           # incidents that need a runbook lookup (new or band changed)
    unmatched: dict[str, dict]  # incident id -> the "no match" result
    llm_jobs: list[str]         # incidents handed to the background LLM worker


def dedup_key(ev: Event) -> str:
    """Same alert re-sent by Alertmanager, or the same log line read twice -> same key."""
    if ev.source == "prometheus":
        basis = f"prom|{ev.labels.get('alertname')}|{ev.labels.get('instance')}|{ev.timestamp.isoformat()}"
    else:
        basis = f"loki|{ev.labels.get('job')}|{ev.host}|{ev.timestamp.isoformat()}|{ev.message}"
    return hashlib.sha1(basis.encode()).hexdigest()


def _next_id(s: Session) -> str:
    ids = s.exec(select(IncidentRow.id)).all()
    n = max((int(i.split("-")[1]) for i in ids), default=0) + 1
    return f"INC-{n:04d}"


def _open_incident_for(s: Session, ev: Event) -> IncidentRow | None:
    """The most recent not-resolved incident with the same grouping key, if within the gap."""
    candidates = s.exec(select(IncidentRow).where(
        IncidentRow.error_type == ev.error_type,
        IncidentRow.service == ev.service,
        IncidentRow.status != "resolved",
    ).order_by(IncidentRow.last_seen.desc())).all()
    for inc in candidates:
        if inc.country == ev.country:
            if ev.timestamp - as_utc(inc.last_seen) > C.INCIDENT_GAP:
                return None            # too long since its last event: start a fresh incident
            return inc
    return None


# ---- nodes -----------------------------------------------------------------
def normalize(state: State) -> State:
    events = []
    if state.get("alertmanager"):
        events += from_alertmanager(state["alertmanager"])
    if state.get("loki"):
        events += from_loki(state["loki"])
    return {"events": sorted(events, key=lambda e: e.timestamp)}


def merge(state: State) -> State:
    s = state["db"]
    new_ids, touched, duplicates = [], [], 0
    for ev in state["events"]:
        key = dedup_key(ev)
        existing = s.exec(select(EventRow).where(EventRow.dedup_key == key)).first()
        if existing:
            duplicates += 1
            # Alertmanager re-sends an alert with status "resolved" once it clears
            if ev.resolved_at and existing.resolved_at is None:
                existing.resolved_at = to_utc(ev.resolved_at)
                s.add(existing)
                if existing.incident_id not in touched:
                    touched.append(existing.incident_id)
            continue

        inc = _open_incident_for(s, ev)
        if inc is None:
            inc = IncidentRow(id=_next_id(s), error_type=ev.error_type, service=ev.service,
                              country=ev.country, first_seen=to_utc(ev.timestamp),
                              last_seen=to_utc(ev.timestamp))
            new_ids.append(inc.id)
        inc.first_seen = min(inc.first_seen, to_utc(ev.timestamp))
        inc.last_seen = max(inc.last_seen, to_utc(ev.timestamp))
        s.add(inc)
        s.add(row_from_event(ev, inc.id, key))
        s.flush()                      # so the next event in this delivery can see it
        if inc.id not in touched:
            touched.append(inc.id)
    return {"new_ids": new_ids, "touched": touched, "duplicates": duplicates}


def score(state: State) -> State:
    s = state["db"]
    lookup = []
    for inc_id in state["touched"]:
        row = s.get(IncidentRow, inc_id)
        inc = score_incident(load_incident(s, row))
        row.title, row.score, row.band, row.factors = inc.title, inc.score, inc.band, inc.factors
        row.event_count, row.unique_messages = inc.count, len(inc.fingerprints)
        row.fingerprints, row.hosts, row.sources = inc.fingerprints, sorted(inc.hosts), sorted(inc.sources)
        row.first_seen, row.last_seen = to_utc(inc.first_seen), to_utc(inc.last_seen)
        row.updated_at = utcnow()
        s.add(row)
        if row.looked_up_band != row.band:   # new incident (None) or band changed
            lookup.append(inc_id)
    return {"lookup": lookup}


def rag_lookup(state: State) -> State:
    s = state["db"]
    unmatched = {}
    for inc_id in state["lookup"]:
        row = s.get(IncidentRow, inc_id)
        try:
            result = matcher.resolve(incident_dict(s, row))
        except Exception as e:               # one bad incident must not stop the rest
            result = {"source": "none", "best_similarity": 0.0, "best_runbook_id": None,
                      "error": f"RAG failed: {e}"}
        row.looked_up_band = row.band
        if result["source"] == "rag":
            set_resolution(s, row, result)
        else:
            unmatched[inc_id] = result
    return {"unmatched": unmatched}


def queue_llm(state: State) -> State:
    s = state["db"]
    for inc_id, result in state["unmatched"].items():
        set_resolution(s, s.get(IncidentRow, inc_id), {**result, "source": "llm_pending"})
    return {"llm_jobs": list(state["unmatched"])}


def finalize(state: State) -> State:
    state["db"].commit()
    return {}


def needs_llm(state: State) -> str:
    return "queue_llm" if state.get("unmatched") else "finalize"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("normalize", normalize), ("merge", merge), ("score", score),
                     ("rag_lookup", rag_lookup), ("queue_llm", queue_llm), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "normalize")
    g.add_edge("normalize", "merge")
    g.add_edge("merge", "score")
    g.add_edge("score", "rag_lookup")
    g.add_conditional_edges("rag_lookup", needs_llm, {"queue_llm": "queue_llm", "finalize": "finalize"})
    g.add_edge("queue_llm", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build_graph()
