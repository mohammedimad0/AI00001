"""/demo/replay: feed the fake scenario in small deliveries over ~30 s.

The scenario covers one hour (10:00-11:00). We cut that hour into 30 slices of ~2 minutes
and send one slice per second, as a real Alertmanager webhook + Loki response would arrive.
So the dashboard fills up live, like a time-lapse video of the hour.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from core import config as C
from core.generator import build_scenario

from .ingest import process

log = logging.getLogger("pager.replay")

_thread: threading.Thread | None = None
_stop = threading.Event()


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start() -> bool:
    global _thread
    if is_running():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_run, name="replay", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=10)


def _alert_time(a: dict) -> datetime:
    return datetime.fromisoformat(a["startsAt"].replace("Z", "+00:00"))


def _log_time(ns: str) -> datetime:
    return datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc)


def slices(n: int) -> list[tuple[dict, dict]]:
    """The scenario cut into n time slices, each as (alertmanager_payload, loki_response)."""
    am, loki = build_scenario()
    items = [(_alert_time(a), "alert", a) for a in am["alerts"]]
    for stream in loki["data"]["result"]:
        items += [(_log_time(v[0]), "log", (stream["stream"], v)) for v in stream["values"]]
    items.sort(key=lambda x: x[0])
    t0, t1 = items[0][0], items[-1][0]
    width = (t1 - t0) / n

    out = []
    for b in range(n):
        lo = t0 + width * b
        hi = t0 + width * (b + 1) if b < n - 1 else t1 + timedelta(seconds=1)   # last slice: take the rest
        part = [it for it in items if lo <= it[0] < hi]
        alerts = [it[2] for it in part if it[1] == "alert"]
        streams: dict[tuple, dict] = {}
        for _t, kind, payload in part:
            if kind == "log":
                labels, value = payload
                key = tuple(sorted(labels.items()))
                streams.setdefault(key, {"stream": labels, "values": []})["values"].append(value)
        out.append((
            {**am, "alerts": alerts},
            {"status": "success", "data": {"resultType": "streams", "result": list(streams.values())}},
        ))
    return out


def _run() -> None:
    pause = C.REPLAY_SECONDS / C.REPLAY_BATCHES
    try:
        for am, loki in slices(C.REPLAY_BATCHES):
            if _stop.is_set():
                break
            if am["alerts"] or loki["data"]["result"]:
                process(alertmanager=am, loki=loki)
            if _stop.wait(pause):
                break
    except Exception:
        log.exception("replay failed")


def tls_again(hours_later: int = 2) -> dict:
    """Demo story, last stage: the same expired-certificate logs arrive again, 2 hours later.
    The gap is > 15 min, so it becomes a NEW incident; if the AI fix was approved, it is now a known fix."""
    _am, loki = build_scenario()
    shift = hours_later * 3600 * 1_000_000_000
    streams = [
        {"stream": s["stream"], "values": [[str(int(ns) + shift), line] for ns, line in s["values"]]}
        for s in loki["data"]["result"] if s["stream"].get("job") == "orders-api"
    ]
    return process(loki={"status": "success", "data": {"resultType": "streams", "result": streams}})
