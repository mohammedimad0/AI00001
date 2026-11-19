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
import os
from functools import lru_cache
from pathlib import Path

from core import config as C
from core.fingerprint import make_template

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")   # harmless Windows cache warning

ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_DIR = ROOT / "runbooks"


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
    """Put every runbooks/*.json into ChromaDB. Idempotent: running twice changes nothing."""
    runbooks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNBOOK_DIR.glob("*.json"))]
    _upsert(runbooks)
    return _collection().count()


def add_runbook(rb: dict) -> None:
    _upsert([rb])


def search(query: str, k: int = C.RAG_TOP_K) -> list[dict]:
    """Closest runbooks to the query text, best first: [{runbook, similarity}, ...]."""
    res = _collection().query(query_embeddings=embed([query]), n_results=k)
    return [
        {"runbook": json.loads(meta["json"]), "similarity": round(1 - dist, 3)}  # distance -> similarity
        for meta, dist in zip(res["metadatas"][0], res["distances"][0])
    ]
