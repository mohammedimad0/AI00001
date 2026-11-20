"""The FastAPI app: every URL the outside world (Alertmanager, Loki, the dashboard) can call.

Start:   .\\.venv\\Scripts\\python.exe -m backend
Docs:    http://localhost:8000/docs  (Swagger: try every endpoint in the browser)
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlmodel import Session, select

from core import config as C
from llm import client as llm
from rag import store

from . import llm_worker, loki_poller, replay, sse
from .db import WRITE_LOCK, FeedbackRow, IncidentRow, clear_all, engine, init_db, utcnow
from .incidents import compute_stats, compute_timeline, incident_dict, to_api
from .ingest import process
from .schemas import AlertmanagerWebhook, Feedback, LokiResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    sse.bind_loop(asyncio.get_running_loop())
    # Warm up the LLM in the background (loads the model into the GPU) so the first demo call is fast
    threading.Thread(target=llm.warm_up, name="llm-warmup", daemon=True).start()
    # Load the embedding model + runbooks NOW (~20 s once), so the first webhook is fast.
    await asyncio.to_thread(store.load_runbooks)
    if C.DATA_SOURCE in ("live", "both"):
        loki_poller.start()                       # real logs: poll Loki every 10 s
    yield
    replay.stop()
    loki_poller.stop()


app = FastAPI(title="Pager Intelligence API", version="0.4",
              description="Alerts and logs in, a few scored incidents with fixes out.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=C.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


# ---- ingest ------------------------------------------------------------------
@app.post("/webhook/alertmanager", tags=["ingest"])
def webhook_alertmanager(payload: AlertmanagerWebhook):
    """Prometheus Alertmanager calls this when alerts fire or resolve."""
    return process(alertmanager=payload.model_dump())


@app.post("/ingest/loki", tags=["ingest"])
def ingest_loki(payload: LokiResponse):
    """Log lines in Loki's query_range response format."""
    return process(loki=payload.model_dump())


# ---- demo --------------------------------------------------------------------
@app.post("/demo/replay", tags=["demo"])
def demo_replay():
    """Stream the fake scenario in over ~30 s so the dashboard fills live."""
    if C.DATA_SOURCE == "live":
        raise HTTPException(409, "Fake data is switched off (DATA_SOURCE = 'live')")
    if not replay.start():
        raise HTTPException(409, "A replay is already running")
    return {"started": True, "seconds": C.REPLAY_SECONDS, "batches": C.REPLAY_BATCHES}


@app.post("/demo/inject/tls", tags=["demo"])
def demo_inject_tls():
    """Demo story: the expired-certificate logs arrive again 2 hours later (new incident)."""
    return replay.tls_again()


@app.post("/demo/reset", tags=["demo"])
def demo_reset():
    """Empty the database and forget approved AI runbooks. Seed runbooks stay."""
    replay.stop()
    llm_worker.reset()
    loki_poller.reset()
    with WRITE_LOCK:
        clear_all()
        forgotten = store.forget_learned()
        with Session(engine) as s:
            stats = compute_stats(s)
    sse.publish("reset", {})
    sse.publish("stats", stats)
    return {"reset": True, "forgot_learned_runbooks": forgotten, "runbooks": store.count()}


# ---- incidents -----------------------------------------------------------------
@app.get("/incidents", tags=["incidents"])
def list_incidents(band: str | None = Query(None, description="critical / high / medium / low"),
                   status: str | None = Query(None, description="open / acknowledged / resolved")):
    with Session(engine) as s:
        q = select(IncidentRow)
        if band:
            q = q.where(IncidentRow.band == band)
        if status:
            q = q.where(IncidentRow.status == status)
        rows = s.exec(q.order_by(IncidentRow.score.desc(), IncidentRow.id)).all()
        return [to_api(r) for r in rows]


def _get(s: Session, incident_id: str) -> IncidentRow:
    row = s.get(IncidentRow, incident_id)
    if row is None:
        raise HTTPException(404, f"No incident {incident_id}")
    return row


@app.get("/incidents/{incident_id}", tags=["incidents"])
def get_incident(incident_id: str):
    with Session(engine) as s:
        return to_api(_get(s, incident_id), s, detail=True)


@app.post("/incidents/{incident_id}/approve", tags=["incidents"])
def approve(incident_id: str, body: Feedback = Body(default_factory=Feedback)):
    """Engineer approves the AI fix -> saved as a runbook -> next time it is a known fix."""
    with WRITE_LOCK, Session(engine) as s:
        row = _get(s, incident_id)
        res = row.resolution or {}
        if res.get("source") != "llm":
            raise HTTPException(409, f"Only AI-generated fixes can be approved (this one is {res.get('source')!r})")
        rb = store.approve_fix(incident_dict(s, row), res)
        row.resolution = {**res, "approved": True, "approved_runbook_id": rb["id"]}
        row.updated_at = utcnow()
        s.add(row)
        s.add(FeedbackRow(incident_id=row.id, action="approve", comment=body.comment, runbook_id=rb["id"]))
        s.commit()
        data = to_api(row)
    sse.publish("incident_updated", data)
    return {"message": "Saved to knowledge base", "runbook_id": rb["id"], "incident": data}


@app.post("/incidents/{incident_id}/reject", tags=["incidents"])
def reject(incident_id: str, body: Feedback = Body(default_factory=Feedback)):
    """Engineer rejects the suggested fix. Nothing is learned; the rejection is recorded."""
    with WRITE_LOCK, Session(engine) as s:
        row = _get(s, incident_id)
        res = row.resolution or {}
        if res.get("source") not in ("llm", "rag"):
            raise HTTPException(409, f"Nothing to reject (resolution is {res.get('source')!r})")
        store.reject_fix(incident_dict(s, row), res, body.comment)
        row.resolution = {**res, "rejected": True}
        row.updated_at = utcnow()
        s.add(row)
        s.add(FeedbackRow(incident_id=row.id, action="reject", comment=body.comment))
        s.commit()
        data = to_api(row)
    sse.publish("incident_updated", data)
    return {"message": "Rejection recorded", "incident": data}


@app.post("/incidents/{incident_id}/ack", tags=["incidents"])
def ack(incident_id: str, body: Feedback = Body(default_factory=Feedback)):
    """Engineer says "I'm on it": status open -> acknowledged."""
    with WRITE_LOCK, Session(engine) as s:
        row = _get(s, incident_id)
        row.status = "acknowledged"
        row.updated_at = utcnow()
        s.add(row)
        s.add(FeedbackRow(incident_id=row.id, action="ack", comment=body.comment))
        s.commit()
        data, stats = to_api(row), compute_stats(s)
    sse.publish("incident_updated", data)
    sse.publish("stats", stats)
    return data


# ---- dashboard -----------------------------------------------------------------
@app.get("/stats", tags=["dashboard"])
def stats():
    with Session(engine) as s:
        return compute_stats(s)


@app.get("/timeline", tags=["dashboard"])
def timeline():
    """Per minute: raw events received vs incidents created (the "noise squashed" chart)."""
    with Session(engine) as s:
        return compute_timeline(s)


@app.get("/stream", tags=["dashboard"])
async def stream():
    """Server-Sent Events: new_incident, incident_updated, stats (and reset)."""
    async def events():
        q = sse.subscribe()
        try:
            with Session(engine) as s:
                yield sse.format_event("stats", compute_stats(s))     # current numbers right away
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=C.SSE_KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"                              # comment line, keeps proxies happy
        finally:
            sse.unsubscribe(q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/health", tags=["dashboard"])
def health():
    ollama = llm.status()
    try:
        chroma = {"ok": True, "runbooks": store.count()}
    except Exception as e:
        chroma = {"ok": False, "error": str(e)}
    return {
        "status": "ok" if ollama["ok"] and chroma["ok"] else "degraded",
        "ollama": {**ollama, "warmup": llm.warmup},
        "chromadb": chroma,
        "llm_jobs_pending": llm_worker.pending(),
        "replay_running": replay.is_running(),
        "data_source": C.DATA_SOURCE,
        "loki": {k: loki_poller.status[k] for k in ("enabled", "reachable", "last_poll", "last_error", "lines_ingested")},
    }
