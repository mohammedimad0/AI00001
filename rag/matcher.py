"""Decides, for each incident, whether a runbook already explains it.

Input:  one incident dict, exactly as in output/3_incidents.json
Output: a "resolution" dict
  known fix -> {source: "rag", runbook_id, similarity, root_cause, impact, fix_steps}
  no match  -> {source: "none", best_similarity, best_runbook_id}   (step 3 sends these to the LLM)
"""
from __future__ import annotations

from core import config as C

from . import store


def build_query(inc: dict) -> str:
    """Describe the incident in words: title, type, service, its message templates,
    and the scoring reasons (HOW it behaved: "120 events within 5 minutes", "high-risk country").

    The reasons matter: a brute-force attack and a user mistyping a password produce the
    SAME log message. Only the behaviour tells them apart.
    """
    templates = sorted(inc["fingerprints"].values(), key=lambda f: f["count"], reverse=True)
    parts = [inc["title"], inc["error_type"], inc["service"]]
    parts += [t["template"] for t in templates[:5]]       # the 5 most common messages
    parts += [f["reason"] for f in inc["factors"] if f["factor"] != "base"]
    return ". ".join(parts)


def resolve(inc: dict) -> dict:
    matches = store.search(build_query(inc))
    best = matches[0] if matches else None

    # The closest runbook of the SAME error type (a CPU runbook must never "fix" a DB outage)
    same_type = [m for m in matches if m["runbook"]["error_type"] == inc["error_type"]]
    if same_type and same_type[0]["similarity"] >= C.RAG_THRESHOLD:
        m, rb = same_type[0], same_type[0]["runbook"]
        return {
            "source": "rag",
            "runbook_id": rb["id"],
            "runbook_title": rb["title"],
            "similarity": m["similarity"],
            "root_cause": rb["root_cause"],
            "impact": rb["impact"],
            "fix_steps": rb["fix_steps"],
        }
    return {
        "source": "none",
        "best_similarity": best["similarity"] if best else 0.0,
        "best_runbook_id": best["runbook"]["id"] if best else None,
    }
