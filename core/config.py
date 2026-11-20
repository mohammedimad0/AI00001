"""All tunable numbers live here, so the team can tweak scoring without touching logic."""
import os
from datetime import timedelta

# Starting score for each kind of error
BASE_SEVERITY = {
    "db_down": 80,
    "disk_full": 60,
    "auth_failure": 40,
    "high_cpu": 30,
    "slow_request": 10,
    "tls_expired": 60,
    "node_down": 70,
    "high_error_rate": 50,
    "unknown": 20,
}

ERROR_LABELS = {
    "db_down": "Database unreachable",
    "disk_full": "Disk almost full",
    "auth_failure": "Login failures",
    "high_cpu": "High CPU",
    "slow_request": "Slow requests",
    "tls_expired": "TLS certificate expired",
    "node_down": "Target down",
    "high_error_rate": "High error rate",
    "unknown": "Unclassified error",
}

# Context factors (points added or removed)
GEO_RISK_POINTS = 40
HIGH_RISK_COUNTRIES = {"KP"}          # edit this list for your demo

BURST_POINTS = 30
BURST_WINDOW = timedelta(minutes=5)
BURST_THRESHOLD = 50                  # events inside BURST_WINDOW

RECURRING_POINTS = 20
RECURRING_MIN_COUNT = 5
RECURRING_MIN_SPAN = timedelta(minutes=10)

CRITICAL_ASSET_POINTS = 20
CRITICAL_SERVICES = {"db-primary", "payments-api"}

MANY_HOSTS_POINTS = 15
MANY_HOSTS_THRESHOLD = 3

BLIP_POINTS = -30
BLIP_MAX_DURATION = timedelta(minutes=2)
BLIP_MAX_COUNT = 2

# Grouping: a new event joins an open incident if it arrives within this gap
INCIDENT_GAP = timedelta(minutes=15)

# Severity bands: (minimum score, band name, action)
BANDS = [
    (90, "critical", "Page on-call"),
    (70, "high", "Notify"),
    (40, "medium", "Show on dashboard"),
    (0, "low", "Log only"),
]

# ---- Step 2: RAG (known fixes from past incidents) ----------------------
EMBED_MODEL = "all-MiniLM-L6-v2"      # small local sentence-transformers model
CHROMA_PATH = os.environ.get("PAGER_CHROMA_PATH", "chroma_db")   # vector DB folder (tests use a temp one)
CHROMA_COLLECTION = "runbooks"
# similarity >= this (and same error_type) = known fix.
# Started at 0.80, measured on the demo data: correct matches score 0.73-0.87,
# the TLS incident (no runbook) scores 0.42. 0.70 accepts every real match with margin.
RAG_THRESHOLD = 0.70
RAG_TOP_K = 3                         # how many closest runbooks to look at

# ---- Step 3: local LLM fallback (Ollama) ---------------------------------
OLLAMA_URL = os.environ.get("PAGER_OLLAMA_URL", "http://127.0.0.1:11434")   # not "localhost": on Windows that tries IPv6 first (~2 s delay)
LLM_MODEL = "qwen2.5:3b"              # fits a 4 GB GPU (RTX 3050). With 8 GB use "qwen2.5:7b".
LLM_TIMEOUT_S = 60                    # give up on one LLM call after this many seconds
LLM_TEMPERATURE = 0.1                 # low = more factual, less creative
LLM_HINT_RUNBOOKS = 2                 # closest runbooks shown to the LLM as hints
LLM_SAMPLE_LINES = 5                  # sample log lines shown to the LLM

# ---- Step 4: backend ------------------------------------------------------
DB_PATH = os.environ.get("PAGER_DB_PATH", "pager.db")            # SQLite file (tests use a temp one)
APPROVED_RUNBOOK_DIR = os.environ.get("PAGER_APPROVED_DIR", "runbooks/approved")
API_PORT = 8000
CORS_ORIGINS = ["http://localhost:5173"]                         # the Vite dev server (step 5)
REPLAY_SECONDS = 30                                              # /demo/replay spreads the scenario over this
REPLAY_BATCHES = 30                                              # ... in this many small deliveries
SSE_KEEPALIVE_S = 15                                             # ping idle /stream clients this often

# ---- Step 6: live data (Prometheus/Alertmanager webhook + Loki poller) ----------
# "fake" = only /demo/replay, "live" = only real sources (replay disabled), "both" = both
DATA_SOURCE = os.environ.get("PAGER_DATA_SOURCE", "both")
LOKI_URL = os.environ.get("PAGER_LOKI_URL", "http://localhost:3100")
LOKI_POLL_S = 10                                   # ask Loki for new lines this often
LOKI_QUERY = '{job=~".+"} |~ "(?i)error|fail|refused|denied|expired"'
LOKI_START_LOOKBACK_S = 300                        # on startup, read the last 5 minutes once
LOKI_BATCH_LIMIT = 5000                            # max lines per request (more = next request)
