"""Test setup: every test run uses a throwaway database, vector store and approved-runbook folder,
and a fake LLM, so tests are fast, offline, and never touch your real demo data."""
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Must happen BEFORE core.config is imported anywhere
_TMP = Path(tempfile.mkdtemp(prefix="pager-test-"))
os.environ["PAGER_DB_PATH"] = str(_TMP / "test.db")
os.environ["PAGER_CHROMA_PATH"] = str(_TMP / "chroma")
os.environ["PAGER_APPROVED_DIR"] = str(_TMP / "approved")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Never reach the real Ollama from tests: a background LLM job that outlives its test would otherwise
# make a real ~10 s call and block the single LLM worker for the next test.
os.environ["PAGER_OLLAMA_URL"] = "http://127.0.0.1:9"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAKE_FIX = {
    "source": "llm", "model": "fake-llm", "root_cause": "The TLS certificate on api-gateway expired.",
    "impact": "Clients cannot connect to api-gateway.", "severity_comment": "Score looks right.",
    "fix_steps": ["Renew the certificate", "Reload api-gateway"], "prevention": "Auto-renew certificates.",
    "confidence": 0.9, "hint_runbooks": [], "attempts": 1, "llm_seconds": 0.0,
}


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from backend.main import app
    with TestClient(app) as c:
        yield c


REAL_GENERATE_FIX = None


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    global REAL_GENERATE_FIX
    from llm import client as llm_client
    REAL_GENERATE_FIX = REAL_GENERATE_FIX or llm_client.generate_fix   # kept for tests of the real fallback
    monkeypatch.setattr(llm_client, "generate_fix", lambda inc, hints: dict(FAKE_FIX))


@pytest.fixture
def clean(client):
    client.post("/demo/reset")
    yield client


def wait_for(predicate, timeout=10.0):
    """Background work (LLM worker, replay) finishes a moment later: poll until it is done."""
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("condition not met in time")
