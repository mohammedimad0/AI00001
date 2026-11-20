"""Step 4: the HTTP API (in-process test client, temp database, fake LLM)."""
import json
from pathlib import Path

from core import config as C
from rag import store
from tests.conftest import wait_for

POSTGRES_DOWN = {
    "version": "4", "receiver": "pager-intelligence", "status": "firing",
    "alerts": [{
        "status": "firing",
        "labels": {"alertname": "PostgresDown", "instance": "db-primary:9187",
                   "severity": "critical", "job": "postgres"},
        "annotations": {"summary": "PostgreSQL on db-primary is not responding"},
        "startsAt": "2026-11-20T10:40:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph",    # extra field real Alertmanager sends
        "fingerprint": "a1b2c3",
    }],
}

TLS_LOGS = {
    "status": "success",
    "data": {"resultType": "streams", "result": [
        {"stream": {"job": "orders-api", "host": h},
         "values": [[str(1795171800000000000 + i * 30_000_000_000),
                     "2026-11-20T10:50:00Z ERROR SSL handshake failed to api-gateway:443: "
                     "certificate has expired (notAfter=2026-11-20T09:59:59Z)"] for i in range(5)]}
        for h in ("web-01", "web-04", "batch-01")
    ]},
}


def test_webhook_parses_alertmanager_payload(clean):
    r = clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] == 1 and len(body["new_incidents"]) == 1

    (inc,) = clean.get("/incidents").json()
    assert inc["error_type"] == "db_down"
    assert inc["service"] == "db-primary"                 # host taken from instance "db-primary:9187"
    assert inc["sources"] == ["prometheus"]
    assert (inc["score"], inc["band"]) == (100, "critical")   # 80 base + 20 critical asset
    assert inc["resolution"]["source"] == "rag"           # RB-007 is a known fix


def test_webhook_resend_is_deduplicated_and_resolve_is_applied(clean):
    clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)
    again = clean.post("/webhook/alertmanager", json=POSTGRES_DOWN).json()
    assert again["duplicates"] == 1 and again["stored"] == 0

    resolved = json.loads(json.dumps(POSTGRES_DOWN))
    resolved["alerts"][0].update(status="resolved", endsAt="2026-11-20T10:45:00Z")
    clean.post("/webhook/alertmanager", json=resolved)
    inc_id = clean.get("/incidents").json()[0]["id"]
    detail = clean.get(f"/incidents/{inc_id}").json()
    assert detail["event_count"] == 1
    assert detail["sample_events"][0]["resolved_at"].startswith("2026-11-20T10:45")


def test_webhook_rejects_bad_payload(clean):
    assert clean.post("/webhook/alertmanager", json={"version": "4"}).status_code == 422
    assert clean.post("/webhook/alertmanager", json={"alerts": [{"labels": {}}]}).status_code == 422
    bad_loki = {"status": "success", "data": {"result": [{"stream": {"job": "x"},
                                                          "values": [["1.79E+18", "boom"]]}]}}
    assert clean.post("/ingest/loki", json=bad_loki).status_code == 422


def test_alert_and_logs_merge_across_deliveries(clean):
    """The DB alert arrives by webhook, the 'connection refused' logs later via Loki: one incident."""
    clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)
    logs = {"status": "success", "data": {"resultType": "streams", "result": [
        {"stream": {"job": "payments-api", "host": "web-01"},
         "values": [[str(1795171205000000000 + i * 5_000_000_000),
                     f"2026-11-20T10:40:05Z ERROR Connection refused to db-primary:5432 (attempt 1) "
                     f"request_id={i:016x}"] for i in range(10)]}]}}
    out = clean.post("/ingest/loki", json=logs).json()
    assert out["new_incidents"] == [] and len(out["updated_incidents"]) == 1
    (inc,) = clean.get("/incidents").json()
    assert inc["event_count"] == 11 and inc["sources"] == ["loki", "prometheus"]


def test_unknown_incident_goes_to_llm_then_approve_saves_runbook(clean):
    out = clean.post("/ingest/loki", json=TLS_LOGS).json()
    assert out["llm_queued"] == out["new_incidents"]       # no runbook for TLS -> LLM job
    inc_id = out["new_incidents"][0]

    # the background worker (fake LLM here) fills in the answer a moment later
    inc = wait_for(lambda: (lambda d: d if d["resolution"]["source"] == "llm" else None)(
        clean.get(f"/incidents/{inc_id}").json()))
    assert inc["resolution"]["root_cause"].startswith("The TLS certificate")

    r = clean.post(f"/incidents/{inc_id}/approve", json={"comment": "looks right"})
    assert r.status_code == 200
    rb_id = r.json()["runbook_id"]
    assert rb_id == "AI-tls-expired-api-gateway"
    saved = Path(store.APPROVED_DIR) / f"{rb_id}.json"
    assert saved.exists() and json.loads(saved.read_text())["source"] == "approved_ai"
    # learned right away: the very next search finds it
    found = store.search("TLS certificate expired api-gateway", k=3)
    assert found[0]["runbook"]["id"] == rb_id, [(m["runbook"]["id"], m["similarity"]) for m in found]

    # ... and the same incident arriving again is now a KNOWN FIX, no LLM
    clean.post("/demo/reset")      # (reset forgets learned runbooks, so approve again on a fresh DB)
    out = clean.post("/ingest/loki", json=TLS_LOGS).json()
    wait_for(lambda: clean.get(f"/incidents/{out['new_incidents'][0]}").json()["resolution"]["source"] == "llm")
    clean.post(f"/incidents/{out['new_incidents'][0]}/approve")
    more = json.loads(json.dumps(TLS_LOGS))
    for stream in more["data"]["result"]:          # same problem, 2 hours later -> a new incident
        stream["values"] = [[str(int(ns) + 7_200_000_000_000), line] for ns, line in stream["values"]]
    again = clean.post("/ingest/loki", json=more).json()
    assert again["llm_queued"] == []
    res = clean.get(f"/incidents/{again['new_incidents'][0]}").json()["resolution"]
    assert (res["source"], res["runbook_id"]) == ("rag", rb_id)

    detail = clean.get(f"/incidents/{inc_id}").json()
    assert detail["resolution"]["approved"] is True
    assert [f["action"] for f in detail["feedback"]] == ["approve"]


def test_approve_refuses_known_fix(clean):
    clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)
    inc_id = clean.get("/incidents").json()[0]["id"]
    assert clean.post(f"/incidents/{inc_id}/approve").status_code == 409


def test_ack_reject_and_filters(clean):
    clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)
    inc_id = clean.get("/incidents").json()[0]["id"]
    assert clean.post(f"/incidents/{inc_id}/ack").json()["status"] == "acknowledged"
    assert clean.post(f"/incidents/{inc_id}/reject", json={"comment": "wrong runbook"}).status_code == 200
    assert len(clean.get("/incidents?status=acknowledged&band=critical").json()) == 1
    assert clean.get("/incidents?band=low").json() == []
    assert clean.get("/incidents/INC-9999").status_code == 404


def test_replay_gives_same_result_as_batch(clean, monkeypatch):
    """Streaming the scenario in 30 small deliveries must end with the same numbers as step 1-3."""
    monkeypatch.setattr(C, "REPLAY_SECONDS", 0.3)
    assert clean.post("/demo/replay").status_code == 200
    stats = wait_for(lambda: (lambda s: s if s["raw_events"] == 386 and not
                              clean.get("/health").json()["replay_running"] else None)(
        clean.get("/stats").json()), timeout=60)
    assert (stats["incidents"], stats["pages"]) == (7, 2)
    assert stats["by_band"] == {"critical": 2, "high": 2, "medium": 1, "low": 2}
    assert stats["noise_reduction_pct"] == 98.2


def test_health_reports_components(client):
    h = client.get("/health").json()
    assert h["chromadb"]["ok"] is True and h["chromadb"]["runbooks"] >= 25
    assert "ollama" in h and "reachable" in h["ollama"]


def test_timeline_counts_raw_events_and_new_incidents_per_minute(clean):
    clean.post("/webhook/alertmanager", json=POSTGRES_DOWN)          # 10:40, opens an incident
    clean.post("/ingest/loki", json=TLS_LOGS)                         # 10:50-10:52, opens another
    points = clean.get("/timeline").json()
    assert points[0]["minute"] == "2026-11-20T10:40" and points[-1]["minute"] == "2026-11-20T10:52"
    assert len(points) == 13                                          # empty minutes are filled in
    assert sum(p["raw"] for p in points) == 16 and sum(p["incidents"] for p in points) == 2
