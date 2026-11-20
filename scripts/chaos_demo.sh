#!/usr/bin/env bash
# Fires every chaos scenario at the victim app, in order, with pauses (~6 minutes).
#   bash scripts/chaos_demo.sh              (PAUSE=10 bash ... for shorter waits, NO_DOCKER=1 to keep Postgres running)
set -euo pipefail
VICTIM="${VICTIM:-http://localhost:8080}"
PAUSE="${PAUSE:-20}"
COMPOSE="$(dirname "$0")/../infra/docker-compose.yml"

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
note() { printf '   %s\n' "$1"; }
wait_for() { note "waiting $1 s ($2)"; sleep "$1"; }
chaos() { note "victim: $(curl -sS -X POST "$VICTIM$1" ${2:+-H "X-Forwarded-For: $2"})"; }

curl -sSf "$VICTIM/healthz" >/dev/null || { echo "Victim app not reachable at $VICTIM. Run: docker compose -f infra/docker-compose.yml up -d --build"; exit 1; }

step "1/5 Brute-force login attack from North Korea (175.45.176.0/22): 2 IPs x 100 attempts"
chaos /chaos/bruteforce 175.45.176.23
chaos /chaos/bruteforce 175.45.177.104
step "    + 3 ordinary failed logins from India (49.36.0.0/14), spread out"
for ip in 49.36.12.7 49.37.200.15 49.38.4.90; do
  curl -s -o /dev/null -X POST "$VICTIM/login" -H "X-Forwarded-For: $ip" -H "Content-Type: application/json" \
       -d '{"user":"priya","password":"wrong"}' && note "login from $ip rejected (401)"
  sleep 5
done
wait_for "$PAUSE" "logs reach Loki -> poller (every 10 s) -> incidents"

step "2/5 CPU spike on the victim for 60 s (HighCPU fires, then resolves by itself)"
chaos "/chaos/cpu?seconds=60"
wait_for $((PAUSE + 70)) "alert fires after ~20 s, resolves ~30 s after the burn ends"

step "3/5 Fill the victim's /data disk to 95% for 45 s (DiskAlmostFull)"
chaos "/chaos/disk?seconds=45"
wait_for $((PAUSE + 40)) "alert fires, Alertmanager waits 10 s, webhook"

step "4/5 Database outage: victim cannot reach db-primary for 90 s"
chaos "/chaos/db-down?seconds=90"
if [ -z "${NO_DOCKER:-}" ]; then
  note "also stopping the real Postgres container, so TargetDown fires in Prometheus"
  docker compose -f "$COMPOSE" stop db-primary >/dev/null
  wait_for 60 "Connection refused logs + TargetDown + HighErrorRate"
  docker compose -f "$COMPOSE" start db-primary >/dev/null
  wait_for $((PAUSE + 10)) "recovery"
else
  wait_for 90 "Connection refused logs + HighErrorRate"
fi

step "5/5 Expired TLS certificate: 3 client hosts fail the handshake with api-gateway for 60 s"
chaos "/chaos/tls?seconds=60"
wait_for $((PAUSE + 50)) "no runbook for TLS -> the local LLM writes the fix"

chaos /chaos/stop
step "Done. Look at the dashboard: http://localhost:5173"
