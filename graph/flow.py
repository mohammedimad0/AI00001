"""The whole pipeline as a LangGraph flowchart.

    normalize -> group -> score -> rag_lookup --(all matched)----------------> finalize
                                              \\--(some not matched)-> llm_generate -/

Each box (node) is a small function that reads the shared State and returns the
parts it changed. LangGraph runs the boxes in order and follows the arrows.
Inside rag_lookup and llm_generate every incident is handled on its own, inside
try/except, so one broken incident never stops the others.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from core import config as C
from core.models import Event, Incident
from core.normalizer import normalize as normalize_events
from core.pipeline import group_events
from core.scoring import score_incident
from llm import client as llm
from rag import matcher, store


class State(TypedDict, total=False):
    alertmanager: dict          # raw input
    loki: dict                  # raw input
    events: list[Event]         # after normalize
    groups: list[Incident]      # after group (Python objects, needed for scoring)
    incidents: list[dict]       # after score: the 3_incidents.json contract
    resolutions: dict[str, dict]  # incident id -> resolution (rag / llm / llm_unavailable)
    stats: dict                 # filled by finalize


# ---- nodes ---------------------------------------------------------------
def normalize(state: State) -> State:
    return {"events": normalize_events(state["alertmanager"], state["loki"])}


def group(state: State) -> State:
    return {"groups": group_events(state["events"])}


def score(state: State) -> State:
    scored = sorted((score_incident(i) for i in state["groups"]), key=lambda i: i.score, reverse=True)
    return {"incidents": [i.to_dict() for i in scored]}


def rag_lookup(state: State) -> State:
    store.load_runbooks()
    resolutions = {}
    for inc in state["incidents"]:
        try:
            resolutions[inc["id"]] = matcher.resolve(inc)
        except Exception as e:                       # one bad incident must not stop the rest
            resolutions[inc["id"]] = {"source": "none", "best_similarity": 0.0,
                                      "best_runbook_id": None, "error": f"RAG failed: {e}"}
    return {"resolutions": resolutions}


def llm_generate(state: State) -> State:
    resolutions = dict(state["resolutions"])
    for inc in state["incidents"]:
        if resolutions[inc["id"]]["source"] != "none":
            continue                                 # already has a known fix
        try:
            hints = matcher.closest(inc, k=C.LLM_HINT_RUNBOOKS)
        except Exception:
            hints = []
        try:
            resolutions[inc["id"]] = llm.generate_fix(inc, hints)
        except Exception as e:
            resolutions[inc["id"]] = {"source": "llm_unavailable", "reason": f"LLM step failed: {e}",
                                      "root_cause": "unknown", "impact": "unknown",
                                      "fix_steps": [], "prevention": "unknown", "confidence": 0.0}
    return {"resolutions": resolutions}


def finalize(state: State) -> State:
    incidents = [{**inc, "resolution": state["resolutions"][inc["id"]]} for inc in state["incidents"]]
    sources = [inc["resolution"]["source"] for inc in incidents]
    return {
        "incidents": incidents,
        "stats": {
            "raw_events": len(state["events"]),
            "incidents": len(incidents),
            "pages": sum(1 for i in incidents if i["band"] == "critical"),
            "known_fix": sources.count("rag"),
            "ai_generated": sources.count("llm"),
            "llm_unavailable": sources.count("llm_unavailable"),
        },
    }


# ---- the arrows ------------------------------------------------------------
def needs_llm(state: State) -> str:
    """Conditional edge: go to the LLM only if some incident has no known fix."""
    if any(r["source"] == "none" for r in state["resolutions"].values()):
        return "llm_generate"
    return "finalize"


def build_graph():
    g = StateGraph(State)
    for name, fn in [("normalize", normalize), ("group", group), ("score", score),
                     ("rag_lookup", rag_lookup), ("llm_generate", llm_generate), ("finalize", finalize)]:
        g.add_node(name, fn)
    g.add_edge(START, "normalize")
    g.add_edge("normalize", "group")
    g.add_edge("group", "score")
    g.add_edge("score", "rag_lookup")
    g.add_conditional_edges("rag_lookup", needs_llm, {"llm_generate": "llm_generate", "finalize": "finalize"})
    g.add_edge("llm_generate", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build_graph()


def run_flow(alertmanager_payload: dict, loki_response: dict) -> State:
    return GRAPH.invoke({"alertmanager": alertmanager_payload, "loki": loki_response})
