"""Fake Prometheus Alertmanager + Loki data for the demo.

Produces data in the SAME JSON shapes the real tools send, so swapping in
real Prometheus/Loki later changes nothing downstream.

Scenarios (all on 2026-11-20, starting 10:00 UTC):
  1. Brute force: 120 failed logins in 3 min from a North Korean IP range
  2. Normal: 3 failed logins from Indian IPs, spread over 24 min
  3. Disk on logs-01 keeps filling up and clearing every 10 min (flapping)
  4. CPU spike on web-03 that resolves itself after 60 seconds
  5. Real outage: db-primary goes down, 4 web servers spam connection errors
  6. Background noise: slow-request warnings on web-02
  7. Expired TLS certificate on api-gateway: 3 client hosts fail the SSL
     handshake every ~30 s for 5 minutes. No runbook covers this one,
     so it is the demo case for the LLM fallback (step 3).
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ns(t: datetime) -> str:
    return str(int(t.timestamp() * 1_000_000_000))


class FakeOps:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.alerts: list[dict] = []
        self.streams: dict[tuple[str, str], list[list[str]]] = {}

    def log(self, t: datetime, job: str, host: str, level: str, text: str) -> None:
        self.streams.setdefault((job, host), []).append(
            [_ns(t), f"{_iso(t)} {level} {text}"]
        )

    def alert(self, name, instance, severity, summary, start, end=None, job="node"):
        self.alerts.append({
            "status": "resolved" if end else "firing",
            "labels": {"alertname": name, "instance": instance,
                       "severity": severity, "job": job},
            "annotations": {"summary": summary},
            "startsAt": _iso(start),
            "endsAt": _iso(end) if end else "0001-01-01T00:00:00Z",
        })

    # ---- output in the real tools' formats -----------------------------
    def alertmanager_payload(self) -> dict:
        """What Alertmanager POSTs to a webhook receiver."""
        return {
            "version": "4",
            "receiver": "pager-intelligence",
            "status": "firing",
            "alerts": self.alerts,
        }

    def loki_response(self) -> dict:
        """What Loki's /loki/api/v1/query_range returns."""
        result = [
            {"stream": {"job": job, "host": host}, "values": values}
            for (job, host), values in self.streams.items()
        ]
        return {"status": "success",
                "data": {"resultType": "streams", "result": result}}


def build_scenario(seed: int = 42) -> tuple[dict, dict]:
    f = FakeOps(seed)
    r = f.rng
    users = ["admin", "root", "deploy", "ops", "test"]

    # 1. Brute force from North Korea (175.45.176.0/22)
    for i in range(120):
        t = T0 + timedelta(minutes=5, seconds=i * 1.5)
        ip = f"175.45.176.{r.randint(2, 250)}"
        f.log(t, "auth", "auth-01", "WARN",
              f"Login failed for user {r.choice(users)} from {ip} port {r.randint(30000, 65000)}")

    # 2. Ordinary failed logins (Indian ISP range 49.36.0.0/14)
    for minute in (20, 32, 44):
        t = T0 + timedelta(minutes=minute)
        ip = f"49.36.{r.randint(0, 255)}.{r.randint(2, 250)}"
        f.log(t, "auth", "auth-01", "WARN",
              f"Login failed for user {r.choice(users)} from {ip} port {r.randint(30000, 65000)}")

    # 3. Disk flapping on logs-01: fires every 10 min, clears after 4 min
    for k in range(6):
        start = T0 + timedelta(minutes=10 * k)
        pct = r.randint(91, 97)
        f.alert("DiskAlmostFull", "logs-01:9100", "warning",
                f"Disk /var/log on logs-01 is {pct}% full",
                start, start + timedelta(minutes=4))

    # 4. CPU blip on web-03, resolves after 60 s
    start = T0 + timedelta(minutes=30)
    f.alert("HighCPU", "web-03:9100", "warning",
            "CPU usage above 90% on web-03", start, start + timedelta(seconds=60))

    # 5. Real outage: db-primary down
    outage = T0 + timedelta(minutes=40)
    f.alert("PostgresDown", "db-primary:9187", "critical",
            "PostgreSQL on db-primary is not responding", outage, job="postgres")
    for host in ("web-01", "web-02", "web-03", "web-04"):
        for i in range(50):
            t = outage + timedelta(seconds=5 + i * 5 + r.random())
            f.log(t, "payments-api", host, "ERROR",
                  f"Connection refused to db-primary:5432 (attempt {r.randint(1, 5)}) "
                  f"request_id={r.getrandbits(64):016x}")

    # 6. Background noise: slow requests on web-02
    for _ in range(25):
        t = T0 + timedelta(seconds=r.randint(0, 3600))
        f.log(t, "shop-api", "web-02", "WARN",
              f"Slow request GET /api/products/{r.randint(1, 9999)} took {r.randint(1200, 3000)}ms")

    # 7. Expired TLS certificate on api-gateway (no runbook -> LLM demo case)
    tls_start = T0 + timedelta(minutes=50)
    for host in ("web-01", "web-04", "batch-01"):
        for i in range(10):
            t = tls_start + timedelta(seconds=i * 30 + r.randint(0, 9))
            f.log(t, "orders-api", host, "ERROR",
                  "SSL handshake failed to api-gateway:443: certificate has expired "
                  "(notAfter=2026-11-20T09:59:59Z)")

    return f.alertmanager_payload(), f.loki_response()
