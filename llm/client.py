"""Talks to the local LLM (Ollama) and makes sure the answer is valid JSON.

Like a strict form: the LLM must fill in exactly these boxes (FixSuggestion),
or we ask it once more. If Ollama is not running, we return a clear
"llm_unavailable" result instead of crashing, so the demo always keeps going.
For incident types we have a saved real answer for (llm/cached/<error_type>.json),
we show that one instead, clearly marked "cached".
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from core import config as C

from .prompts import SYSTEM_PROMPT, build_user_prompt


class FixSuggestion(BaseModel):
    """The exact JSON shape the LLM must return."""
    root_cause: str
    impact: str
    severity_comment: str
    fix_steps: list[str]
    prevention: str
    confidence: float = Field(ge=0, le=1)


CACHE_DIR = Path(__file__).resolve().parent / "cached"
KEEP_ALIVE = "30m"          # keep the model loaded in GPU memory between demo calls
warmup = {"state": "not started", "seconds": None, "error": None}


def _unavailable(reason: str) -> dict:
    return {
        "source": "llm_unavailable",
        "model": C.LLM_MODEL,
        "reason": reason,
        "root_cause": "unknown",
        "impact": "unknown",
        "severity_comment": "unknown",
        "fix_steps": [],
        "prevention": "unknown",
        "confidence": 0.0,
    }


def is_available() -> bool:
    try:
        return httpx.get(f"{C.OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


def status() -> dict:
    """For /health: is Ollama running, and is our model downloaded?"""
    try:
        r = httpx.get(f"{C.OLLAMA_URL}/api/tags", timeout=3)
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return {"ok": C.LLM_MODEL in names, "reachable": True, "model": C.LLM_MODEL,
                "model_pulled": C.LLM_MODEL in names}
    except (httpx.HTTPError, ValueError):
        return {"ok": False, "reachable": False, "model": C.LLM_MODEL, "model_pulled": False,
                "hint": "start Ollama (ollama serve)"}


def warm_up() -> None:
    """Load the model into GPU memory with a 1-token prompt, so the first real call is fast.
    (The very first call after a restart can take 5-80 s; this pays that cost at startup.)"""
    warmup.update(state="running", error=None)
    started = time.perf_counter()
    try:
        r = httpx.post(f"{C.OLLAMA_URL}/api/generate", timeout=180, json={
            "model": C.LLM_MODEL, "prompt": "ok", "stream": False, "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": 1}})
        r.raise_for_status()
        warmup.update(state="ok", seconds=round(time.perf_counter() - started, 1))
    except (httpx.HTTPError, ValueError) as e:
        warmup.update(state="failed", error=str(e)[:200] or type(e).__name__)


def cached_answer(error_type: str) -> dict | None:
    path = CACHE_DIR / f"{error_type}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def generate_fix(inc: dict, hints: list[dict]) -> dict:
    """Ask the LLM; if it cannot answer, fall back to a saved real answer (marked cached)."""
    result = _ask_llm(inc, hints)
    if result["source"] == "llm_unavailable":
        cached = cached_answer(inc["error_type"])
        if cached:
            return {**cached, "source": "llm", "cached": True, "llm_seconds": 0.0,
                    "hint_runbooks": [h["runbook"]["id"] for h in hints],
                    "reason": f"Live LLM unavailable ({result['reason']}); showing a saved answer"}
    return result


def _ask_llm(inc: dict, hints: list[dict]) -> dict:
    """Ask the LLM for root cause + fix. Always returns a dict, never raises."""
    request = {
        "model": C.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(inc, hints)},
        ],
        "format": FixSuggestion.model_json_schema(),   # Ollama structured output: forces this JSON shape
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": C.LLM_TEMPERATURE},
    }
    started = time.perf_counter()
    problem = ""
    for attempt in (1, 2):                              # retry once on invalid JSON
        try:
            r = httpx.post(f"{C.OLLAMA_URL}/api/chat", json=request, timeout=C.LLM_TIMEOUT_S)
        except httpx.ConnectError:
            return _unavailable(f"Ollama is not running at {C.OLLAMA_URL} (start it with: ollama serve)")
        except httpx.TimeoutException:
            return _unavailable(f"LLM did not answer within {C.LLM_TIMEOUT_S} s")
        except httpx.HTTPError as e:
            return _unavailable(f"Could not reach Ollama: {e}")

        if r.status_code == 404:
            return _unavailable(f"Model {C.LLM_MODEL} is not pulled (run: ollama pull {C.LLM_MODEL})")
        if r.status_code != 200:
            return _unavailable(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")

        try:
            fix = FixSuggestion.model_validate_json(r.json()["message"]["content"])
        except (ValidationError, ValueError, KeyError) as e:
            problem = f"invalid JSON from LLM: {str(e)[:200]}"
            continue                                    # ask again

        return {
            "source": "llm",
            "model": C.LLM_MODEL,
            **fix.model_dump(),
            "hint_runbooks": [h["runbook"]["id"] for h in hints],
            "attempts": attempt,
            "llm_seconds": round(time.perf_counter() - started, 1),
        }
    return _unavailable(f"Gave up after 2 attempts, {problem}")
