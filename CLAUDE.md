# Pager Intelligence — project context for Claude Code

## What this project is
Hackathon project for 1by0Grit, AI Ops track, problem AIO0001 "The Pager That Cried Wolf".
Ops teams get hundreds of alerts a day; most are duplicates, small blips, or symptoms of one fault.
Engineers learn to ignore them and miss the one that matters. Small on-call teams suffer most.

Our system turns a flood of alerts/logs into a few scored incidents, each with a root cause and fix:

1. Ingest: Prometheus Alertmanager webhook (metric alerts) + Loki (logs), both JSON
2. Normalize: everything into one `Event` schema
3. Dedup + group: fingerprint identical messages, correlate same fault across sources into one `Incident`
4. Score: base severity + context factors (geo risk, burst, recurring, critical asset, many hosts, self-resolved blip). Scores go UP for real threats and DOWN for noise. Every point has a recorded reason.
5. RAG: look up similar past incidents (runbooks) in ChromaDB. Similarity >= 0.8 → known fix.
6. LLM fallback: no match → local LLM via Ollama generates root cause, impact, fix as strict JSON.
7. Learning loop: engineer approves an AI fix → it is saved into ChromaDB → next time it is a known fix.
8. Dashboard: noise counter ("356 raw alerts → 6 incidents → 2 pages"), live incident feed, incident report.

## Stack
- Backend: Python 3.11+, FastAPI, LangGraph, SQLite (SQLModel), ChromaDB, sentence-transformers
- LLM: Ollama, model `qwen2.5:7b` (fits an 8 GB RTX 5050 GPU). Never require a cloud API key.
- Frontend: React + Vite + TypeScript + Tailwind
- Monitoring: Prometheus, Alertmanager, Loki, Promtail, node-exporter in Docker Compose
- Dev machine: Windows laptop, 16 GB RAM, RTX 5050 8 GB. Commands must work on Windows (PowerShell) too.

## Existing code (step 1, already working — do not break it)
- `core/generator.py` fake Alertmanager + Loki JSON, 6 scenarios
- `core/normalizer.py`, `core/fingerprint.py`, `core/geo.py`, `core/pipeline.py`, `core/scoring.py`
- `core/config.py` holds every tunable number. Put new thresholds here, not in logic.
- `demo.py` runs everything; expected output: 356 raw → 6 incidents → 2 pages
- `output/3_incidents.json` is the contract the later steps consume

## Rules for working in this repo
- The developer does not write code himself; he wants to UNDERSTAND the system. After every step,
  explain in plain, simple English: what each new file does, how data flows through it, and how
  it connects to the previous step. Use short analogies. No jargon without a one-line explanation.
- After building, actually run it and show the output. Fix errors before saying a step is done.
- Keep the demo working offline (venue Wi-Fi is unreliable). Fake data must always be a fallback.
- Keep each step runnable on its own with one command, documented in README.md.
- Prefer simple, readable code over clever code. Small files with one job each.
- Do not invent features outside the current step's prompt; ask if something is unclear.
- Update README.md at the end of every step (how to run, what's new).
