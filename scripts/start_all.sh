#!/usr/bin/env bash
# One command to start everything (macOS / Linux / Git Bash):  bash scripts/start_all.sh   (FAKE=1 to skip Docker)
# Logs go to logs/backend.log and logs/dashboard.log.  Stop: kill the PIDs printed at the end, then
#   docker compose -f infra/docker-compose.yml down
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
up() { curl -s -o /dev/null --max-time 2 "$1"; }
PY=.venv/bin/python; [ -x "$PY" ] || PY=.venv/Scripts/python.exe

mode=fake
if [ -n "${FAKE:-}" ]; then echo "1/4 FAKE mode requested: skipping Docker."
elif ! command -v docker >/dev/null; then echo "1/4 Docker not installed -> FAKE mode (demo replay + story work offline)."
elif ! docker info >/dev/null 2>&1; then echo "1/4 Docker not running -> FAKE mode. Start Docker and re-run for LIVE data."
else
  echo "1/4 Starting the Docker stack..."
  if docker compose -f infra/docker-compose.yml up -d --build >logs/docker.log 2>&1; then mode=both; echo "    LIVE + FAKE mode"
  else echo "    Docker stack failed (see logs/docker.log) -> FAKE mode"; fi
fi

if up http://localhost:8000/health; then echo "2/4 Backend already running."
else echo "2/4 Starting the backend (logs/backend.log)..."; PAGER_DATA_SOURCE=$mode nohup "$PY" -m backend >logs/backend.log 2>&1 & echo "    pid $!"; fi

if up http://localhost:5173; then echo "3/4 Dashboard already running."
else
  echo "3/4 Starting the dashboard (logs/dashboard.log)..."
  ( cd frontend && { [ -d node_modules ] || npm install; } && nohup npm run dev >../logs/dashboard.log 2>&1 & echo "    pid $!" )
fi

echo "4/4 Waiting for backend + dashboard..."
for _ in $(seq 1 90); do up http://localhost:8000/health && up http://localhost:5173 && break; sleep 2; done
if ! (up http://localhost:8000/health && up http://localhost:5173); then echo "Not up after 3 minutes, see logs/."; exit 1; fi
echo "Ready: data source $(echo $mode | tr a-z A-Z). Dashboard: http://localhost:5173 -> press 'Demo story'"
for open in xdg-open open start; do command -v $open >/dev/null && { $open http://localhost:5173 >/dev/null 2>&1; break; }; done
