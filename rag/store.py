"""The runbook library, stored in ChromaDB as vectors (embeddings).

Think of it as a library where books are shelved by MEANING, not by title:
- load_runbooks()  puts every runbooks/*.json on the shelf (safe to run again and again)
- search(text)     finds the runbooks whose meaning is closest to the text
- add_runbook(rb)  adds or updates one runbook (step 3 uses this to learn approved AI fixes)

Everything runs locally. The embedding model (~90 MB) is downloaded once,
then loaded from the local cache, so it works with no internet.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from core import config as C
from core.fingerprint import make_template

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")   # harmless Windows cache warning

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_DIR = ROOT / "runbooks"
APPROVED_DIR = ROOT / C.APPROVED_RUNBOOK_DIR   # AI fixes an engineer approved (the learning loop)

log = logging.getLogger("pager.learning")


# ---- the embedding model: text -> list of 384 numbers -------------------
@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    try:
        return SentenceTransformer(C.EMBED_MODEL, local_files_only=True)   # offline, from cache
    except Exception:
        return SentenceTransformer(C.EMBED_MODEL)                          # first run: download


def embed(texts: list[str]) -> list[list[float]]:
    return _model().encode(texts, normalize_embeddings=True).tolist()


# ---- the vector database -----------------------------------------------
@lru_cache(maxsize=1)
def _collection():
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(
        path=str(ROOT / C.CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False),     # no network calls
    )
    # "cosine" = compare the DIRECTION of vectors (their meaning), not their length
    return client.get_or_create_collection(C.CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"})


def runbook_text(rb: dict) -> str:
    """The text we turn into a vector: what the problem LOOKS like.

    Symptoms go through the same cleaner as incident messages (IPs -> <ip>, numbers -> <num>),
    so both sides of the comparison are written the same way.
    """
    return f"{rb['title']}. {rb['error_type']}. {rb['service']}. {make_template(rb['symptoms'])}"


def _upsert(runbooks: list[dict]) -> None:
    if not runbooks:
        return
    texts = [runbook_text(rb) for rb in runbooks]
    _collection().upsert(          # upsert = insert, or overwrite if the id already exists
        ids=[rb["id"] for rb in runbooks],
        embeddings=embed(texts),
        documents=texts,
        metadatas=[{"error_type": rb["error_type"], "service": rb["service"],
                    "title": rb["title"], "source": rb.get("source", "seed"),
                    "json": json.dumps(rb)} for rb in runbooks],
    )


def load_runbooks() -> int:
    """Put every runbook into ChromaDB: the seed ones (runbooks/*.json) and the ones
    engineers approved (runbooks/approved/*.json). Idempotent: running twice changes nothing."""
    files = sorted(RUNBOOK_DIR.glob("*.json")) + sorted(APPROVED_DIR.glob("*.json"))
    _upsert([json.loads(p.read_text(encoding="utf-8")) for p in files])
    return _collection().count()


def count() -> int:
    return _collection().count()


def add_runbook(rb: dict) -> None:
    _upsert([rb])


# ---- learning loop -------------------------------------------------------
def approve_fix(incident: dict, resolution: dict) -> dict:
    """An engineer approved an AI-generated fix: save it as a new runbook.

    It goes into ChromaDB (so the next search finds it) AND into
    runbooks/approved/<id>.json (so it survives even if chroma_db/ is deleted).
    The same kind of incident approved again overwrites the same runbook, not a duplicate.
    """
    if resolution.get("source") != "llm":
        raise ValueError(f"Only LLM-generated fixes can be approved, got source={resolution.get('source')!r}")
    from .matcher import build_query        # imported here to avoid a circular import

    slug = re.sub(r"[^a-z0-9]+", "-", f"{incident['error_type']}-{incident['service']}".lower()).strip("-")
    rb = {
        "id": f"AI-{slug}",
        "title": incident["title"],
        "error_type": incident["error_type"],
        "service": incident["service"],
        "symptoms": build_query(incident),  # describe it exactly the way future incidents are searched
        "root_cause": resolution["root_cause"],
        "impact": resolution["impact"],
        "fix_steps": resolution["fix_steps"],
        "prevention": resolution["prevention"],
        "source": "approved_ai",
        "learned_from": incident["id"],
        "model": resolution.get("model"),
        "confidence": resolution.get("confidence"),
    }
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    (APPROVED_DIR / f"{rb['id']}.json").write_text(json.dumps(rb, indent=2), encoding="utf-8")
    add_runbook(rb)
    log.info("approved AI fix for %s -> runbook %s", incident["id"], rb["id"])
    return rb


def reject_fix(incident: dict, resolution: dict, reason: str = "") -> None:
    """An engineer rejected an AI fix. Nothing is learned; we only record it."""
    log.warning("rejected AI fix for %s (%s): %s", incident["id"], resolution.get("source"), reason or "no reason")


def forget_learned() -> int:
    """Remove all approved AI runbooks (used by `demo.py --learn` so the demo can be repeated)."""
    col = _collection()
    learned = col.get(where={"source": "approved_ai"})["ids"]
    if learned:
        col.delete(ids=learned)
    for p in APPROVED_DIR.glob("*.json"):
        p.unlink()
    return len(learned)


def search(query: str, k: int = C.RAG_TOP_K) -> list[dict]:
    """Closest runbooks to the query text, best first: [{runbook, similarity}, ...].

    Exact search: we compare the query with EVERY stored runbook vector ourselves.
    Chroma's approximate index (HNSW) sometimes did not yet see a runbook that was just
    approved, so the learning loop could miss it. The stored vectors are always right, and
    with a few hundred runbooks comparing all of them takes well under a millisecond.
    Similarity = cosine similarity = 1 - Chroma's cosine distance (vectors are normalized).
    """
    data = _collection().get(include=["embeddings", "metadatas"])
    if not data["ids"]:
        return []
    vectors = np.asarray(data["embeddings"], dtype=np.float32)
    sims = vectors @ np.asarray(embed([query])[0], dtype=np.float32)
    best = np.argsort(-sims)[:k]
    return [{"runbook": json.loads(data["metadatas"][i]["json"]), "similarity": round(float(sims[i]), 3)}
            for i in best]
