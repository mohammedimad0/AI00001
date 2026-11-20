"""Step 6: live-source parsing and the Loki poller (no Docker needed: Loki is faked)."""
import time

import httpx

from backend import loki_poller
from core import config as C
from core.normalizer import from_alertmanager, from_loki


def _alert(name, instance, job, summary):
    return {"alerts": [{"status": "firing", "labels": {"alertname": name, "instance": instance, "job": job},
                        "annotations": {"summary": summary}, "startsAt": "2026-11-20T10:00:00Z"}]}


def test_targetdown_on_a_database_is_db_down_on_db_primary():
    (ev,) = from_alertmanager(_alert("TargetDown", "db-primary:9187", "postgres", "PostgreSQL on db-primary is not responding"))
    assert (ev.error_type, ev.service) == ("db_down", "db-primary")


def test_targetdown_on_other_targets_and_high_error_rate():
    (ev,) = from_alertmanager(_alert("TargetDown", "web-05:9100", "node", "Target web-05 is down"))
    assert ev.error_type == "node_down"
    (ev,) = from_alertmanager(_alert("HighErrorRate", "victim:8080", "victim", "HTTP 5xx error rate above 20% on victim"))
    assert (ev.error_type, ev.service) == ("high_error_rate", "victim")


def test_real_openssh_lines_are_auth_failures_with_attacker_ip():
    lines = [
        "Failed password for invalid user webmaster from 173.234.31.186 port 38926 ssh2",
        "Invalid user test9 from 52.80.34.196",
        "pam_unix(sshd:auth): authentication failure; logname= uid=0 euid=0 tty=ssh ruser= rhost=183.62.140.253  user=root",
        "reverse mapping checking getaddrinfo for ns.marryaldkfaczcz.com [173.234.31.186] failed - POSSIBLE BREAK-IN ATTEMPT!",
    ]
    resp = {"data": {"result": [{"stream": {"job": "sshd", "host": "LabSZ"},
                                 "values": [[str(1795171800000000000 + i), f"2026-11-20T10:50:00Z WARN {l}"]
                                            for i, l in enumerate(lines)]}]}}
    events = from_loki(resp)
    assert [e.error_type for e in events] == ["auth_failure"] * 4
    assert [e.src_ip for e in events] == ["173.234.31.186", "52.80.34.196", "183.62.140.253", "173.234.31.186"]


def test_poller_reads_only_new_lines(clean, monkeypatch):
    """Fake Loki: first poll returns 2 lines, second poll must ask for lines AFTER the newest one."""
    t0 = time.time_ns() - 60_000_000_000
    line = "2026-11-20T10:50:00Z ERROR SSL handshake failed to api-gateway:443: certificate has expired"
    asked = []

    def fake_loki(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        asked.append(start)
        values = [[str(t0 + i * 1000), line] for i in range(2) if t0 + i * 1000 >= start]   # 1 µs apart
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "streams", "result":
            [{"stream": {"job": "orders-api", "host": "web-01"}, "values": values}] if values else []}})

    loki_poller.status["last_ns"] = None
    monkeypatch.setattr(C, "LOKI_START_LOOKBACK_S", 300)
    with httpx.Client(transport=httpx.MockTransport(fake_loki)) as client:
        assert loki_poller.poll_once(client) == 2
        assert loki_poller.poll_once(client) == 0          # nothing new: nothing read twice
    assert asked[1] == t0 + 1000 + 1                         # second request starts after the newest line
    incidents = clean.get("/incidents").json()
    assert [(i["error_type"], i["event_count"]) for i in incidents] == [("tls_expired", 2)]


def test_live_only_mode_disables_fake_replay(clean, monkeypatch):
    monkeypatch.setattr(C, "DATA_SOURCE", "live")
    assert clean.post("/demo/replay").status_code == 409
    assert clean.get("/health").json()["data_source"] == "live"


def test_llm_down_uses_cached_tls_answer(monkeypatch):
    """Ollama unreachable: the TLS incident still gets a real (saved) answer, clearly marked cached."""
    from llm import client
    monkeypatch.setattr(C, "OLLAMA_URL", "http://127.0.0.1:9")          # nothing listens there
    from tests import conftest
    monkeypatch.setattr(client, "generate_fix", conftest.REAL_GENERATE_FIX)   # undo the test-wide fake LLM
    from core.generator import build_scenario
    from core.pipeline import run
    tls = next(i.to_dict() for i in run(*build_scenario())["incidents"] if i.error_type == "tls_expired")
    res = client.generate_fix(tls, [])
    assert res["source"] == "llm" and res["cached"] is True
    assert "expired" in res["root_cause"] and res["fix_steps"]
    db = next(i.to_dict() for i in run(*build_scenario())["incidents"] if i.error_type == "db_down")
    assert client.generate_fix(db, [])["source"] == "llm_unavailable"   # no cached answer: honest failure


def test_story_tls_again_becomes_known_fix_after_approval(clean):
    import time as _t
    from tests.conftest import wait_for
    from core import config as C2
    C2_old = C2.REPLAY_SECONDS
    C2.REPLAY_SECONDS = 0.3
    try:
        clean.post("/demo/replay")
        tls = wait_for(lambda: next((i for i in clean.get("/incidents").json()
                                     if i["error_type"] == "tls_expired" and i["resolution"].get("source") == "llm"), None), 60)
        assert clean.post(f"/incidents/{tls['id']}/approve").status_code == 200
        wait_for(lambda: not clean.get("/health").json()["replay_running"], 60)
        out = clean.post("/demo/inject/tls").json()
        assert len(out["new_incidents"]) == 1 and out["llm_queued"] == []
        res = clean.get(f"/incidents/{out['new_incidents'][0]}").json()["resolution"]
        assert (res["source"], res["runbook_id"]) == ("rag", "AI-tls-expired-api-gateway")
    finally:
        C2.REPLAY_SECONDS = C2_old
