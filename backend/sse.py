"""Live updates for the dashboard (Server-Sent Events).

Like a radio station: every open dashboard tab "tunes in" to /stream and gets its own
mailbox (queue). publish() drops a copy of each message into every mailbox.
publish() may be called from background threads (replay, LLM worker), so it hands the
message to the web server's event loop safely with call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
import json
import threading

_loop: asyncio.AbstractEventLoop | None = None
_subscribers: set[asyncio.Queue] = set()
_lock = threading.Lock()


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subscribers.discard(q)


def _deliver(q: asyncio.Queue, message: str) -> None:
    try:
        q.put_nowait(message)
    except asyncio.QueueFull:          # a stuck client must not block everyone else
        pass


def format_event(event: str, data: dict) -> str:
    """The SSE wire format: 'event: <name>' + 'data: <json>' + blank line."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def publish(event: str, data: dict) -> None:
    if _loop is None:
        return
    message = format_event(event, data)
    with _lock:
        targets = list(_subscribers)
    for q in targets:
        _loop.call_soon_threadsafe(_deliver, q, message)
