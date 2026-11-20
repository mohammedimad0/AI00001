"""Loki poller: every 10 s, ask Loki "any new error-ish log lines since last time?"

Like checking a mailbox on a timer. We remember the timestamp of the newest line we have
seen, and next time ask only for lines AFTER it, so no line is read twice. (Even if one
were, the database de-duplicates it.) New lines go through the same ingest flow as the
/ingest/loki endpoint.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from core import config as C

from .ingest import process

log = logging.getLogger("pager.loki_poller")

_thread: threading.Thread | None = None
_stop = threading.Event()
status = {
    "enabled": False,
    "reachable": False,
    "last_poll": None,          # unix time of the last successful poll
    "last_error": None,
    "lines_ingested": 0,
    "last_ns": None,            # newest log timestamp seen (nanoseconds)
}


def start() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    status["enabled"] = True
    _thread = threading.Thread(target=_run, name="loki-poller", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    status["enabled"] = False


def poll_once(client: httpx.Client) -> int:
    """One round: fetch everything newer than last_ns (in batches), ingest it. Returns lines read."""
    now_ns = time.time_ns()
    start_ns = status["last_ns"] + 1 if status["last_ns"] else now_ns - C.LOKI_START_LOOKBACK_S * 1_000_000_000
    total = 0
    while True:
        r = client.get(f"{C.LOKI_URL}/loki/api/v1/query_range", params={
            "query": C.LOKI_QUERY, "start": start_ns, "end": now_ns,
            "limit": C.LOKI_BATCH_LIMIT, "direction": "forward",
        })
        r.raise_for_status()
        body = r.json()
        streams = body.get("data", {}).get("result", [])
        lines = sum(len(s.get("values", [])) for s in streams)
        if lines == 0:
            break
        process(loki=body)
        newest = max(int(v[0]) for s in streams for v in s["values"])
        status["last_ns"] = max(status["last_ns"] or 0, newest)
        total += lines
        if lines < C.LOKI_BATCH_LIMIT:
            break
        start_ns = newest + 1                    # a full batch: there may be more, keep going
    status["lines_ingested"] += total
    return total


def _run() -> None:
    with httpx.Client(timeout=10) as client:
        while not _stop.is_set():
            try:
                n = poll_once(client)
                status.update(reachable=True, last_poll=time.time(), last_error=None)
                if n:
                    log.info("ingested %d log lines from Loki", n)
            except Exception as e:                # Loki down / not started yet: just try again later
                status.update(reachable=False, last_error=str(e)[:200])
            _stop.wait(C.LOKI_POLL_S)


def reset() -> None:
    """After /demo/reset: a clean slate. Only log lines written from now on count."""
    status.update(last_ns=time.time_ns(), lines_ingested=0)
