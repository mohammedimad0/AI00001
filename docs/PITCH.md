# Pager Intelligence — pitch

## Before you go on stage (5 minutes earlier)

1. `powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1` → everything green (Docker may be yellow: fine).
2. `powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1` → the dashboard opens in the browser.
3. Press **Reset** once if the dashboard shows old data. Make the browser full screen (F11).
4. Only one screen should run the story: close other dashboard tabs (they would reset each other).
5. Backup plan: if the backend does not start, run
   `.\.venv\Scripts\python.exe demo.py --learn` in a terminal: same story, as text.

---

## The 3-minute pitch (follows the ★ Demo story)

Press **★ Demo story** right after the first sentence. The captions run on their own; **Next ▸** skips ahead
if you are faster than the story, so you are never waiting.

| Time | On screen (story stage) | Say |
| --- | --- | --- |
| 0:00 | Empty dashboard | "On-call engineers get hundreds of alerts a day. Most are duplicates, blips that fix themselves, or echoes of one fault. So people stop trusting the pager — and miss the one that matters. That's the pager that cried wolf." **Click ★ Demo story.** |
| 0:15 | **a · Noise flood** — counter climbs to 386 | "This is one hour of a small company: Prometheus alerts and Loki log lines, in the exact formats those tools send. 386 of them. Without help, that's 386 interruptions." |
| 0:40 | **b · Grouping** — 386 → 7 → 2 | "We normalize everything into one shape, strip out the IPs and IDs, and merge what belongs together. 386 raw alerts become 7 incidents — and only **2** pages. 98 % less noise." |
| 0:55 | **c · Brute force** — KP report, waterfall | "Here's why this one pages: 120 failed logins in three minutes from North Korea. Base 40, plus 40 for a high-risk country, plus 30 for the burst: 110, critical. Every point has a written reason — no black box." |
| 1:20 | **d · DB outage** | "One Prometheus alert that Postgres is down, plus 200 'connection refused' logs from four web servers. A normal tool shows 201 alerts. We show **one** incident on the database — with the known fix from our runbook library." |
| 1:45 | **e · CPU blip** | "And the opposite: a CPU spike that fixed itself in 60 seconds. 30 minus 30: zero. It's logged, but nobody gets woken up at 3 am." |
| 2:05 | **f · AI writes a fix** — TLS report | "An expired TLS certificate. No runbook covers it. So a language model running **on this laptop** — no cloud, logs never leave the machine — writes the root cause and fix steps as strict JSON. An engineer reviews it and approves." |
| 2:30 | **g · Learned** — second TLS card, "Known fix 99 %" | "Two hours later the same problem comes back. Now it's a known fix, straight from the knowledge base — no AI call needed. **Every approval makes the system smarter.**" |
| 2:50 | End caption | "Pager Intelligence: hundreds of alerts in, the two that matter out, each with a reason and a fix. It runs on one laptop, with the tools ops teams already use. Thank you." |

If there is time left or a judge asks for "real": the badge says **LIVE** — the same pipeline reads a real
Prometheus/Loki stack. `scripts\chaos_demo.ps1` breaks a real app (DB outage: real alert + real logs merge
into one incident); `scripts\replay_loghub.py` replays 2,000 lines of a real SSH attack log → 1 incident.

---

## 30-second version

"On-call teams drown in alerts — hundreds a day, mostly duplicates and blips — so they start ignoring the
pager and miss the real outage. Pager Intelligence takes the raw flood from Prometheus and Loki, merges it
into a few incidents, and scores each one with a reason for every point: in our demo, 386 alerts become 7
incidents and only 2 pages. Each incident comes with a fix — from a runbook library, or written by a local
LLM that never sends your logs to the cloud. When an engineer approves an AI fix, the system learns it, so
next time it's instant."

---

## 10 likely judge questions — short, honest answers

**1. Why not fine-tune a model instead of RAG + prompting?**
We have no training data yet: a team's history of good fixes is exactly what this system collects.
Retrieval works from day one with 25 runbooks, updates instantly when an engineer approves a fix (no
retraining), and shows *which* runbook it used, so it is checkable. Fine-tuning is on the roadmap, using the
approved fixes as training data once there are hundreds of them.

**2. How does scoring avoid missing real incidents (false negatives)?**
Nothing is ever dropped: every event is stored and every incident stays visible on the dashboard, even "low".
Points only go *down* in one narrow case — a blip that resolved itself within 2 minutes with at most 2 events.
Dangerous types start high (a database down alone scores 80 + 20 for a critical asset = page). Honest gap:
a slow, quiet problem on a non-critical service can stay below the paging line; the fix is per-service
weights in `config.py`, and the roadmap is to learn weights from acknowledge/ignore feedback.

**3. How were the thresholds chosen?**
By measuring on our demo data, and we say so. Example: we started the runbook match at 0.80 similarity,
measured that correct matches scored 0.73–0.87 and the "no runbook" case 0.42, and set 0.70. On live data
we checked it again: for CPU, disk and real SSH alerts the closest runbooks were near-ties or the wrong
cause, and 0.70 correctly refused to guess. All numbers live in one file and are easy to retune per team.

**4. How does it scale to thousands of alerts?**
The per-event work is cheap (a regex, a hash, a dictionary lookup). The expensive steps run per *incident*,
not per event: runbook search only when an incident is new or its band changes (~0.02 s), and the LLM only
for incidents without a runbook, in a background queue. On a laptop it ingested 2,000 real SSH log lines in
one go. We have not load-tested beyond that; the next step for scale is Postgres instead of SQLite, a queue
in front of ingest, and more workers.

**5. What about privacy?**
Everything runs locally: the LLM (Ollama), the embeddings, the vector database, the app. No API key, no
cloud call; logs never leave the machine. After the first install it runs with Wi-Fi off.

**6. What happens when the LLM is wrong?**
Its answer is clearly labelled "AI-generated, needs review" with a confidence, and it only uses facts from
the incident (the prompt tells it to say "unknown" otherwise; the output is forced into a strict schema).
Nothing is learned until a human clicks Approve; Reject records the rejection. If the LLM is down or too
slow, the incident still appears, scored, with "LLM unavailable" — it never blocks the pipeline.

**7. How is this different from Alertmanager grouping or PagerDuty?**
Alertmanager groups alerts with identical labels, from one source. We also merge *across* sources — a metric
alert and 200 log lines become one incident — and we dedup log messages by fingerprint. PagerDuty routes and
escalates; it doesn't tell you *why* something matters or *how* to fix it. We add an explainable score, a
fix, and learning. We are complementary: the roadmap sends only our critical incidents on to PagerDuty/Slack.

**8. What does it cost to run?**
Zero licence cost: all open source. It runs on one laptop with a 4 GB GPU (the LLM uses ~2 GB). No
per-call fees, and the LLM is only called for incidents without a known fix (1 of 7 in the demo), so a
small CPU-only box would also work, just with slower AI answers.

**9. Geo scoring — what about attackers behind a VPN, or from a "normal" country?**
Geo is one factor of several. A brute force from anywhere still gets the burst points (+30) and shows up;
the high-risk list is just a configurable extra. Real attacker IPs need the free MaxMind database for real
countries; without it they show "unknown" and the other factors still apply.

**10. What if something breaks during a real incident — Docker, the LLM, the backend?**
Each part degrades on its own: no LLM → incidents still scored, with a "cached" or "unavailable" fix;
no Loki → the poller retries every 10 s; no Docker → it runs on the alert webhook and demo data. The
dashboard shows a banner instead of a blank page when the backend is down, and reconnects by itself.
