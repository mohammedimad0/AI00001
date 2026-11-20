"""The database: 4 tables in one SQLite file (pager.db).

Think of it as 4 filing cabinets:
  events       every alert / log line we received (after normalizing)
  incidents    the grouped problems: score, band, factors, status, current resolution
  resolutions  history of every fix suggestion (runbook match or LLM answer) per incident
  feedback     what engineers did: approve, reject, acknowledge
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine, delete

from core import config as C

ROOT = Path(__file__).resolve().parent.parent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """All times are UTC. If a value comes back from SQLite without its zone, put it back."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


to_utc = as_utc   # same rule for writing: always store UTC with the zone attached


class EventRow(SQLModel, table=True):
    __tablename__ = "events"
    id: int | None = Field(default=None, primary_key=True)
    dedup_key: str = Field(index=True, unique=True)   # same alert re-sent -> same key, stored once
    incident_id: str = Field(index=True, foreign_key="incidents.id")
    timestamp: datetime = Field(index=True)
    source: str
    host: str
    service: str
    error_type: str
    level: str
    message: str
    src_ip: str | None = None
    country: str | None = None
    resolved_at: datetime | None = None
    template: str = ""
    fingerprint: str = Field(default="", index=True)
    labels: dict = Field(default_factory=dict, sa_column=Column(JSON))
    received_at: datetime = Field(default_factory=utcnow)


class IncidentRow(SQLModel, table=True):
    __tablename__ = "incidents"
    id: str = Field(primary_key=True)                 # INC-0001
    error_type: str = Field(index=True)
    service: str = Field(index=True)
    country: str | None = None
    title: str = ""
    score: int = 0
    band: str = Field(default="low", index=True)
    factors: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="open", index=True)   # open / acknowledged / resolved
    event_count: int = 0
    unique_messages: int = 0
    fingerprints: dict = Field(default_factory=dict, sa_column=Column(JSON))
    hosts: list = Field(default_factory=list, sa_column=Column(JSON))
    sources: list = Field(default_factory=list, sa_column=Column(JSON))
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    resolution: dict = Field(default_factory=dict, sa_column=Column(JSON))
    looked_up_band: str | None = None                 # band at the last RAG/LLM lookup
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ResolutionRow(SQLModel, table=True):
    __tablename__ = "resolutions"
    id: int | None = Field(default=None, primary_key=True)
    incident_id: str = Field(index=True, foreign_key="incidents.id")
    source: str                                       # rag / llm_pending / llm / llm_unavailable
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class FeedbackRow(SQLModel, table=True):
    __tablename__ = "feedback"
    id: int | None = Field(default=None, primary_key=True)
    incident_id: str = Field(index=True, foreign_key="incidents.id")
    action: str                                       # approve / reject / ack
    comment: str = ""
    runbook_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


_db_file = Path(C.DB_PATH) if Path(C.DB_PATH).is_absolute() else ROOT / C.DB_PATH
engine = create_engine(f"sqlite:///{_db_file}", connect_args={"check_same_thread": False})

# Webhooks, the replay and the LLM worker can all write at the same moment.
# One "talking stick": only the holder may change incidents, so two batches never
# create the same incident twice.
WRITE_LOCK = threading.RLock()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def clear_all() -> None:
    """Empty every table (for /demo/reset). Children first, because of foreign keys."""
    with Session(engine) as s:
        for table in (FeedbackRow, ResolutionRow, EventRow, IncidentRow):
            s.exec(delete(table))
        s.commit()
