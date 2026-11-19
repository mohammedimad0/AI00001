# Pager Intelligence — Steps 1–2: core engine + known-fix lookup (RAG)

Turns a flood of alerts and logs into a few scored incidents, then looks up a known fix
for each one in a local library of runbooks. Everything runs offline after the first install.

## Setup (once)

Windows PowerShell:
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
macOS / Linux: same, but activate with `source .venv/bin/activate`.

The install is ~250 MB (CPU-only PyTorch). The first `python demo.py` also downloads the
embedding model `all-MiniLM-L6-v2` (~90 MB) once; after that no internet is needed.

## Run

```
python demo.py
```

Expected result: **386 raw alerts/logs → 7 incidents → 2 pages**, and

| Incident | Score | Fix lookup |
| --- | --- | --- |
| Database unreachable on db-primary | 145 critical | KNOWN FIX RB-007 (0.87) |
| Login failures on auth from KP (brute force) | 110 critical | KNOWN FIX RB-001 (0.76) |
| Disk almost full on logs-01 (flapping) | 80 high | KNOWN FIX RB-004 (0.80) |
| TLS certificate expired on api-gateway | 75 high | **NO MATCH → needs LLM** (best 0.42) |
| Login failures on auth from IN (normal) | 40 medium | KNOWN FIX RB-002 (0.74) |
| Slow requests on shop-api | 30 low | KNOWN FIX RB-009 (0.87) |
| High CPU on web-03 (blip) | 0 low | KNOWN FIX RB-005 (0.74) |

The run takes ~20 s on Windows: almost all of it is Python loading PyTorch at startup.
A single lookup takes ~0.02 s.

## What each file does

| File | Stage | Job |
| --- | --- | --- |
| `core/generator.py` | Fake data | Produces JSON in the exact shapes Alertmanager (webhook) and Loki (query API) send. Seven scenarios: brute force from KP, normal failed logins, flapping disk, CPU blip, DB outage, slow-request noise, expired TLS certificate. |
| `core/normalizer.py` | Normalize | Converts both formats into one `Event` shape and classifies the error type. |
| `core/fingerprint.py` | Dedup | Strips IPs, numbers, users and IDs from a message and hashes what's left, so identical problems get the same fingerprint. |
| `core/geo.py` | Context | IP → country. Uses MaxMind GeoLite2 if `data/GeoLite2-Country.mmdb` exists, otherwise a small built-in table. |
| `core/pipeline.py` | Group | Merges events into incidents by (error type, affected service, origin country) with a 15-min gap rule. |
| `core/scoring.py` | Score | Base score + context factors (geo, burst, recurring, critical asset, many hosts, self-resolved blip). Records the reason for every point. |
| `core/config.py` | Settings | Every tunable number, including `RAG_THRESHOLD`. Tune here, not in the logic. |
| `core/models.py` | Data shapes | `Event` and `Incident`. |
| `runbooks/*.json` | Knowledge | 25 seed runbooks: symptoms, root cause, impact, fix steps, prevention. No TLS runbook on purpose (LLM demo case). |
| `rag/store.py` | RAG | ChromaDB vector store at `./chroma_db`. `load_runbooks()`, `search(text)`, `add_runbook(rb)`. |
| `rag/matcher.py` | RAG | Builds a search text per incident and decides: known fix (similarity ≥ threshold and same error type) or no match. |
| `demo.py` | Run | Runs it all, prints the table, writes each JSON stage to `output/`. |

## Look at the JSON stages

`output/1_raw_*.json` → `2_normalized_events.json` → `3_incidents.json` → `4_resolved_incidents.json`

`4_resolved_incidents.json` = the incidents plus a `resolution`:
`{source: "rag", runbook_id, similarity, root_cause, impact, fix_steps}` or `{source: "none", best_similarity, best_runbook_id}`.

## How matching was tuned (step 2)

- The search text for an incident includes its **scoring reasons** ("120 events within 5 minutes",
  "high-risk country KP"). Without them a brute-force attack and a mistyped password look identical.
- Runbook symptoms pass through the **same cleaner** as log messages (`<ip>`, `<num>`, `<user>`).
- `RAG_THRESHOLD` lowered from 0.80 to **0.70**: correct matches scored 0.73–0.87, the TLS case 0.42.

## Next steps

3. LLM fallback with Ollama + approve-and-learn loop.
4. FastAPI backend.
5. React dashboard.
6. Real Prometheus/Loki wiring (Docker Compose).
