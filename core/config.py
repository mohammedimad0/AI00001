"""All tunable numbers live here, so the team can tweak scoring without touching logic."""
from datetime import timedelta

# Starting score for each kind of error
BASE_SEVERITY = {
    "db_down": 80,
    "disk_full": 60,
    "auth_failure": 40,
    "high_cpu": 30,
    "slow_request": 10,
    "tls_expired": 60,
    "unknown": 20,
}

ERROR_LABELS = {
    "db_down": "Database unreachable",
    "disk_full": "Disk almost full",
    "auth_failure": "Login failures",
    "high_cpu": "High CPU",
    "slow_request": "Slow requests",
    "tls_expired": "TLS certificate expired",
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
CHROMA_PATH = "chroma_db"             # folder (relative to project root) for the vector DB
CHROMA_COLLECTION = "runbooks"
# similarity >= this (and same error_type) = known fix.
# Started at 0.80, measured on the demo data: correct matches score 0.73-0.87,
# the TLS incident (no runbook) scores 0.42. 0.70 accepts every real match with margin.
RAG_THRESHOLD = 0.70
RAG_TOP_K = 3                         # how many closest runbooks to look at
