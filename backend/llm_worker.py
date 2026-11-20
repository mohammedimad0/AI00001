"""Background LLM worker: one helper in the back room who answers LLM jobs one at a time.

The webhook only drops a job in the tray (submit) and answers immediately.
The helper picks it up, asks Ollama (~5-7 s), saves the answer and tells the dashboards.
One at a time, because the 4 GB GPU holds one model and would only queue parallel calls anyway.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import Session

from core import config as C
from llm import client as llm
from rag import matcher

from . import sse
from .db import WRITE_LOCK, IncidentRow, engine
from .incidents import compute_stats, incident_dict, set_resolution, to_api

log = logging.getLogger("pager.llm_worker")

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llm")
_lock = threading.Lock()
_pending: set[str] = set()     # incidents already waiting (don't queue the same one twice)
_generation = 0                # bumped by reset(): answers for wiped incidents are thrown away


def submit(incident_id: str) -> None:
    with _lock:
        if incident_id in _pending:
            return
        _pending.add(incident_id)
        generation = _generation
    _executor.submit(_run, incident_id, generation)


def reset() -> None:
    global _generation
    with _lock:
        _generation += 1
        _pending.clear()


def pending() -> int:
    with _lock:
        return len(_pending)


def _run(incident_id: str, generation: int) -> None:
    try:
        with WRITE_LOCK, Session(engine) as s:
            row = s.get(IncidentRow, incident_id)
            inc = incident_dict(s, row) if row else None
        with _lock:
            _pending.discard(incident_id)    # from now on, a band change may queue a fresh job
        if inc is None or generation != _generation:
            return

        try:
            hints = matcher.closest(inc, k=C.LLM_HINT_RUNBOOKS)
        except Exception:
            hints = []
        result = llm.generate_fix(inc, hints)          # slow part, done WITHOUT holding the lock

        with WRITE_LOCK, Session(engine) as s:
            row = s.get(IncidentRow, incident_id)
            if row is None or generation != _generation:
                return                                 # incident was wiped by /demo/reset
            set_resolution(s, row, result)
            s.commit()
            data, stats = to_api(row), compute_stats(s)
        sse.publish("incident_updated", data)
        sse.publish("stats", stats)
    except Exception:
        log.exception("LLM job for %s failed", incident_id)
        with _lock:
            _pending.discard(incident_id)
