"""The shapes of request bodies. FastAPI checks them and shows them in Swagger (/docs).

extra="allow": real Alertmanager / Loki send more fields than we need; we accept and ignore them.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str = "firing"                     # firing / resolved
    labels: dict[str, str]                     # alertname, instance, severity, job, ...
    annotations: dict[str, str] = {}           # summary, description
    startsAt: str
    endsAt: str = "0001-01-01T00:00:00Z"       # Alertmanager's "not resolved yet"


class AlertmanagerWebhook(BaseModel):
    """What Alertmanager POSTs to a webhook receiver (version 4 format)."""
    model_config = ConfigDict(extra="allow")
    version: str = "4"
    receiver: str = ""
    status: str = "firing"
    alerts: list[AlertmanagerAlert]


NanoTimestamp = Annotated[str, StringConstraints(pattern=r"^\d+$")]   # e.g. "1795171800000000000"


class LokiStream(BaseModel):
    model_config = ConfigDict(extra="allow")
    stream: dict[str, str]                     # labels: job, host, ...
    values: list[tuple[NanoTimestamp, str]]    # [nanosecond timestamp, log line]


class LokiData(BaseModel):
    model_config = ConfigDict(extra="allow")
    resultType: str = "streams"
    result: list[LokiStream]


class LokiResponse(BaseModel):
    """What Loki's /loki/api/v1/query_range returns."""
    model_config = ConfigDict(extra="allow")
    status: str = "success"
    data: LokiData


class Feedback(BaseModel):
    comment: str = ""                          # optional note from the engineer
