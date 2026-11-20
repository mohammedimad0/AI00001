"""The "victim": a tiny shop backend we can break on purpose.

- Writes log lines to /var/log/victim/app.log in the form
      <time> <LEVEL> <host> <job> <message>
  Promtail turns <host> and <job> into Loki labels and ships "<time> <LEVEL> <message>".
- Exposes /metrics for Prometheus (request counts by status, its own CPU, disk usage of /data).
- Simulates customer traffic (2 orders per second) that really queries Postgres (db-primary).
- /chaos/* endpoints cause the incidents our system should catch.
"""
from __future__ import annotations

import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from flask import Flask, Response, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

LOG_FILE = Path(os.environ.get("VICTIM_LOG_DIR", "/var/log/victim")) / "app.log"
DATA_DIR = Path(os.environ.get("VICTIM_DATA_DIR", "/data"))
DB_HOST = os.environ.get("DB_HOST", "db-primary")
DB_DSN = f"host={DB_HOST} port=5432 dbname=shop user=shop password=shop connect_timeout=2"
ME = os.environ.get("VICTIM_HOST", "victim")

app = Flask(__name__)
REQUESTS = Counter("victim_http_requests_total", "Requests handled, by endpoint and status", ["endpoint", "status"])
DISK_USED = Gauge("victim_disk_used_ratio", "Used fraction of the /data volume")
DISK_USED.set_function(lambda: _disk_ratio())

_log_lock = threading.Lock()
_chaos = {"db_down": False}
_stop = threading.Event()          # set by /chaos/stop: every running chaos thread checks it


def log(level: str, host: str, job: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with _log_lock, LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {level} {host} {job} {message}\n")


def _disk_ratio() -> float:
    try:
        st = os.statvfs(DATA_DIR)                     # Linux (inside Docker)
        return 1 - st.f_bavail / st.f_blocks
    except (OSError, AttributeError):                  # e.g. running on Windows for a quick test
        return 0.0


def client_ip() -> str:
    """Behind a load balancer the real client IP is the first entry of X-Forwarded-For."""
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() or request.remote_addr or "0.0.0.0"


def in_background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


# ---- simulated customer traffic -------------------------------------------------
def traffic_loop() -> None:
    conn = None
    attempt = 0
    while True:
        time.sleep(0.5)
        request_id = uuid.uuid4().hex[:16]
        try:
            if _chaos["db_down"]:
                raise psycopg.OperationalError("chaos: db-down")
            if conn is None or conn.closed:
                conn = psycopg.connect(DB_DSN, autocommit=True)
            conn.execute("SELECT 1")
            attempt = 0
            REQUESTS.labels("orders", "200").inc()
        except psycopg.Error:
            conn = None
            attempt = attempt % 5 + 1
            REQUESTS.labels("orders", "500").inc()
            log("ERROR", ME, "payments-api",
                f"Connection refused to db-primary:5432 (attempt {attempt}) request_id={request_id}")


# ---- normal endpoints ------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "chaos": {"db_down": _chaos["db_down"]}}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    user = body.get("user", "admin")
    if body.get("password") == "correct-horse":
        REQUESTS.labels("login", "200").inc()
        return {"ok": True}
    REQUESTS.labels("login", "401").inc()
    log("WARN", "auth-01", "auth", f"Login failed for user {user} from {client_ip()} port {random.randint(30000, 65000)}")
    return {"ok": False}, 401


# ---- chaos ---------------------------------------------------------------------
@app.post("/chaos/bruteforce")
def chaos_bruteforce():
    ip, n = client_ip(), int(request.args.get("n", 100))

    def run():
        for _ in range(n):
            if _stop.is_set():
                return
            user = random.choice(["admin", "root", "deploy", "ops", "test", "oracle", "ubuntu"])
            REQUESTS.labels("login", "401").inc()
            log("WARN", "auth-01", "auth", f"Login failed for user {user} from {ip} port {random.randint(30000, 65000)}")
            time.sleep(0.1)                         # 100 attempts in ~10 s
    _stop.clear()
    in_background(run)
    return {"started": "bruteforce", "from_ip": ip, "attempts": n}


@app.post("/chaos/cpu")
def chaos_cpu():
    seconds = int(request.args.get("seconds", 60))

    def burn():
        end = time.time() + seconds
        x = 0
        while time.time() < end and not _stop.is_set():
            x = (x * 31 + 7) % 1_000_003              # pure busy work: 100% of one core
    _stop.clear()
    in_background(burn)
    return {"started": "cpu", "seconds": seconds}


@app.post("/chaos/disk")
def chaos_disk():
    hold = int(request.args.get("seconds", 60))
    target = float(request.args.get("fill", 0.95))
    path = DATA_DIR / "fill.bin"

    def fill():
        chunk = b"\0" * (1024 * 1024)
        with path.open("wb") as f:
            while _disk_ratio() < target and not _stop.is_set():
                try:
                    f.write(chunk)
                    f.flush()
                except OSError:
                    break
        log("WARN", ME, "storage", f"Disk /data on {ME} is {_disk_ratio():.0%} full")
        _stop.wait(hold)
        path.unlink(missing_ok=True)
        log("INFO", ME, "storage", f"Disk /data on {ME} back to {_disk_ratio():.0%}")
    _stop.clear()
    in_background(fill)
    return {"started": "disk", "fill_to": target, "hold_seconds": hold}


@app.post("/chaos/db-down")
def chaos_db_down():
    seconds = int(request.args.get("seconds", 0))      # 0 = until /chaos/stop
    _chaos["db_down"] = True

    def recover():
        if not _stop.wait(seconds):
            _chaos["db_down"] = False
    _stop.clear()
    if seconds:
        in_background(recover)
    return {"started": "db-down", "seconds": seconds or "until /chaos/stop"}


@app.post("/chaos/tls")
def chaos_tls():
    seconds = int(request.args.get("seconds", 60))

    def run():
        end = time.time() + seconds
        while time.time() < end and not _stop.is_set():
            for host in ("web-01", "web-04", "batch-01"):    # client hosts calling the gateway
                log("ERROR", host, "orders-api",
                    "SSL handshake failed to api-gateway:443: certificate has expired (notAfter=2026-11-19T23:59:59Z)")
            _stop.wait(10)
    _stop.clear()
    in_background(run)
    return {"started": "tls", "seconds": seconds}


@app.post("/chaos/stop")
def chaos_stop():
    _stop.set()
    _chaos["db_down"] = False
    (DATA_DIR / "fill.bin").unlink(missing_ok=True)
    return {"stopped": True}


LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
log("INFO", ME, "victim", "victim app started")
in_background(traffic_loop)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
