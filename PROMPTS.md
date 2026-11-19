# Pager Intelligence — Claude Code prompts, step by step

How to use:
1. Unzip `pager-intelligence-step1.zip`, open the `pager-intelligence` folder in VS Code.
2. Make sure `CLAUDE.md` is in the folder root (Claude Code reads it automatically).
3. Open Claude Code, paste ONE prompt at a time. Wait until it runs and verifies before the next.
4. After each step, commit: `git add . && git commit -m "step N"` so you can roll back.

---

## Step 0 — Check the setup

```
Read CLAUDE.md and every file in core/ plus demo.py. Then:
1. Set up a Python virtual environment (.venv) and a requirements.txt (empty for now is fine).
2. Run `python demo.py` and confirm the output is 356 raw → 6 incidents → 2 pages.
3. Initialise git with a sensible .gitignore (venv, __pycache__, output/, data/*.mmdb, chroma_db/, node_modules/).
4. Explain to me in simple words, like to a beginner, how data flows from generator.py to 3_incidents.json.
Do not change any logic yet.
```

---

## Step 2 — RAG: known fixes from past incidents

```
Build step 2: RAG lookup of known fixes. Read CLAUDE.md first.

1. Add a 7th scenario to core/generator.py that has NO runbook, so we can demo the LLM path later:
   an expired TLS certificate on api-gateway (logs like "SSL handshake failed: certificate has expired"
   from 3 client hosts over ~5 minutes). Add error_type "tls_expired" (base 60) to config and normalizer
   rules. Update the expected demo numbers in README.

2. Create a runbooks/ folder with 25 runbooks as JSON files. Each has: id, title, error_type, service
   (or "*"), symptoms (2-3 sentences written like log messages and alert summaries), root_cause, impact,
   fix_steps (list), prevention, source ("seed"). Cover: brute-force login attacks, normal failed logins,
   disk full / log rotation, flapping disk alerts, CPU spikes, DB down / connection refused, DB connection
   pool exhaustion, slow requests, memory leak / OOM kill, pod crashloop, DNS failure, high latency,
   queue backlog, cache down, etc. Do NOT include TLS certificate expiry (that is the LLM demo case).

3. Create rag/store.py: ChromaDB PersistentClient at ./chroma_db, cosine distance, embeddings from
   sentence-transformers "all-MiniLM-L6-v2" (runs locally, offline after first download).
   Functions: load_runbooks() (idempotent), search(incident) -> best match + similarity (1 - distance),
   add_runbook(dict).

4. Create rag/matcher.py: build the query text from incident title, error_type, service and its
   fingerprint templates. If similarity >= RAG_THRESHOLD (0.80, in config.py) AND error_type matches,
   attach resolution = {source: "rag", runbook_id, similarity, root_cause, impact, fix_steps}.
   Otherwise resolution = {source: "none", best_similarity}.

5. Update demo.py to run RAG after scoring and print "KNOWN FIX (runbook id, similarity)" or
   "NO MATCH → needs LLM" for each incident. Write output/4_resolved_incidents.json.

6. Add requirements, run it, show me the output. Tune the threshold if real matches score below 0.8,
   and tell me what you changed and why.

7. Explain simply: what an embedding is, what a vector DB does, and why similarity 0.8 means "same problem".
```

---

## Step 3 — LLM fallback + LangGraph flow + learning loop

```
Build step 3: local LLM fallback, the LangGraph pipeline, and the approve-and-learn loop. Read CLAUDE.md.

1. llm/client.py: call Ollama at http://localhost:11434 with model from config (LLM_MODEL = "qwen2.5:7b").
   Use Ollama's structured output (format = JSON schema) and validate with Pydantic:
   {root_cause: str, impact: str, severity_comment: str, fix_steps: list[str], prevention: str,
    confidence: float 0-1}. Retry once on invalid JSON. Timeout 60 s.
   If Ollama is not running, return a clear fallback result marked source "llm_unavailable"
   so the demo never crashes.

2. llm/prompts.py: a strict system prompt for an SRE assistant. Input = incident title, score,
   factor breakdown, hosts, first/last seen, up to 5 sample log lines, and the 2 closest runbooks
   (even below threshold) as hints. Tell it to only use facts from the input and say "unknown" otherwise.

3. graph/flow.py: a LangGraph StateGraph with nodes normalize → group → score → rag_lookup, then a
   conditional edge: matched → finalize, not matched → llm_generate → finalize. State holds events,
   incidents, resolutions. Process incidents independently so one failure doesn't stop others.

4. Learning loop in rag/store.py: approve_fix(incident, resolution) saves it as a new runbook with
   source "approved_ai" (to ChromaDB and to runbooks/approved/*.json). reject_fix() just logs it.

5. demo.py: run the graph. Add a --learn flag that: runs once (TLS incident goes to LLM), auto-approves
   the LLM fix, runs again, and shows the TLS incident is now a KNOWN FIX. This is our best demo moment.

6. Tell me exactly which Ollama commands to run on Windows (install, `ollama pull qwen2.5:7b`), run it,
   and show both runs. Also show how long the LLM call took on GPU.

7. Explain simply: what LangGraph adds vs plain function calls, and why we force JSON output.
```

---

## Step 4 — FastAPI backend + database + live updates

```
Build step 4: the FastAPI backend. Read CLAUDE.md.

1. backend/ with FastAPI app, SQLite via SQLModel (tables: events, incidents, resolutions, feedback).
   Incidents store score, band, factors (JSON), status (open / acknowledged / resolved), resolution.

2. Endpoints:
   - POST /webhook/alertmanager  (real Alertmanager webhook format)
   - POST /ingest/loki           (Loki query_range response format)
   - POST /demo/replay           (runs the fake scenario, streamed in over ~30 s so the dashboard
                                  fills live, not all at once)
   - GET  /incidents?band=&status=   GET /incidents/{id}
   - POST /incidents/{id}/approve    POST /incidents/{id}/reject    POST /incidents/{id}/ack
   - GET  /stats  → raw_events, incidents, pages, noise_reduction_pct, by_band counts
   - GET  /stream → Server-Sent Events: new_incident, incident_updated, stats
   - GET  /health → checks Ollama + ChromaDB status

3. Run the LangGraph flow incrementally: new events join open incidents (15-min gap rule from config),
   rescore, and only call RAG/LLM when an incident is new or its band changes. LLM calls run in a
   background task so the webhook returns fast.

4. CORS for http://localhost:5173. Swagger docs at /docs.

5. Write a few pytest tests: fingerprinting, scoring of the KP brute force (=110 critical), CPU blip
   (=0 low), DB outage merging alert + logs into one incident, webhook parsing.

6. Run the server (uvicorn), hit each endpoint with curl/httpie, show results. Explain simply:
   what a REST API is, what a webhook is, and what SSE does for the dashboard.
```

---

## Step 5 — React dashboard

```
Build step 5: the dashboard. Read CLAUDE.md. Use React + Vite + TypeScript + Tailwind in frontend/.
Clean, dark ops-console look. Data from the step 4 API; live updates via /stream (SSE).

Pages / parts:
1. Top bar: big noise-reduction counter "356 raw alerts → 7 incidents → 2 pages" that counts up live,
   health dots for Ollama and ChromaDB, a "Replay demo" button (POST /demo/replay).
2. Incident feed: cards sorted by score, colored by band (critical red, high orange, medium yellow,
   low gray), showing title, score, ×count, hosts, time, and a badge "Known fix" or "AI-generated".
   Filters by band and status. New incidents slide in.
3. Incident report (click a card): 
   - Severity breakdown as a horizontal waterfall: base bar then each factor +/− with its reason
   - Root cause, impact, fix steps (checklist), prevention
   - Source: runbook id + similarity %, or "AI-generated, needs review" with confidence
   - Approve / Reject buttons (approve calls the API, then shows "Saved to knowledge base")
   - Raw evidence: unique message templates with counts, sample log lines, timeline of events
4. Small charts: events per minute (raw) vs incidents (after grouping), and incidents by band.

Run it, open it, and click through every part. Fix anything broken. Then explain simply how the
frontend talks to the backend, using one real request as the example.
```

---

## Step 6 — Real Prometheus + Loki with Docker Compose

```
Build step 6: real monitoring stack. Read CLAUDE.md. Keep fake-data replay working as a fallback.

1. infra/docker-compose.yml with: prometheus, alertmanager, node-exporter, loki, promtail, and a small
   "victim" app (Python) that exposes /metrics and writes logs. The victim app has endpoints to trigger
   chaos: /chaos/bruteforce, /chaos/cpu, /chaos/disk, /chaos/db-down, /chaos/tls.
2. Prometheus alert rules for HighCPU, DiskAlmostFull, PostgresDown-style "TargetDown", high error rate.
   Alertmanager route → webhook http://host.docker.internal:8000/webhook/alertmanager (works on Windows
   Docker Desktop), group_wait 10s.
3. Promtail ships the victim app's logs to Loki. Backend gets a Loki poller (every 10 s, LogQL
   {job=~".+"} |~ "(?i)error|fail|refused|denied", tracks last timestamp so nothing is read twice).
4. A script scripts/chaos_demo.ps1 (and .sh) that fires all chaos scenarios in sequence for the live demo.
5. Start everything, trigger chaos, show alerts arriving in the dashboard. Explain simply what each
   container does and how an alert travels from Prometheus to our dashboard.
```

---

## Step 7 — Demo polish and pitch

```
Step 7: make it demo-ready. Read CLAUDE.md.
1. One command to start everything (scripts/start_all.ps1 and .sh) and a pre-flight check script that
   verifies Ollama model pulled, embeddings cached, ChromaDB seeded, ports free.
2. Pre-warm the LLM at startup so the first demo call isn't slow.
3. A "Demo mode" toggle in the dashboard that replays the scripted 3-minute story:
   noise flood → KP brute force pages → DB outage merges 200 logs into 1 incident → TLS goes to LLM →
   approve → replay → now a known fix.
4. README: architecture diagram (mermaid), how to run, what each folder does, results table.
5. Write me a 3-minute pitch script that follows the demo, and a list of 8 likely judge questions with
   short honest answers (including: why not fine-tune, how scoring avoids false negatives, how it
   scales, privacy of logs since the LLM is local).
```

---

## If something breaks (paste this)

```
Something is broken. Do not rewrite large parts. First reproduce the error, explain the cause in one
or two simple sentences, then make the smallest fix, re-run, and show me it works.
```
