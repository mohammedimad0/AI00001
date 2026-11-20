"""What we say to the LLM.

SYSTEM_PROMPT = the job description (same for every incident).
build_user_prompt() = the case file for ONE incident: only facts our pipeline measured.
"""
from __future__ import annotations

from core import config as C

SYSTEM_PROMPT = """You are a senior Site Reliability Engineer (SRE) on call.
You receive ONE incident that an alert-correlation system has already grouped and scored.
Your job: explain the most likely root cause, the impact, and concrete fix steps.

Strict rules:
- Use ONLY facts that appear in the incident data below. Do not invent hosts, versions, people, dates or numbers.
- If something cannot be known from the data, write "unknown" for that field.
- The reference runbooks are the closest past incidents. They may NOT match this incident.
  Use them only if they clearly describe the same problem; otherwise ignore them.
- fix_steps: 3 to 6 short, concrete actions an engineer can run now, in order. Include commands where obvious.
- severity_comment: one sentence on whether the score and band look right, based on the factors.
- confidence: a number from 0 to 1 for how sure you are of the root cause (0.9 = clear evidence in the logs).
- Answer with a single JSON object that matches the given schema. No markdown, no extra text."""


def _hint_text(hints: list[dict]) -> str:
    if not hints:
        return "  (none)"
    lines = []
    for h in hints:
        rb = h["runbook"]
        lines.append(f"  - {rb['id']} \"{rb['title']}\" (similarity {h['similarity']:.2f}, "
                     f"type {rb['error_type']}): root cause: {rb['root_cause']}")
    return "\n".join(lines)


def build_user_prompt(inc: dict, hints: list[dict]) -> str:
    factors = "\n".join(f"  {f['points']:+d}  {f['reason']}" for f in inc["factors"])
    templates = "\n".join(f"  {fp['count']}x  {fp['template']}"
                          for fp in sorted(inc["fingerprints"].values(), key=lambda f: -f["count"]))
    samples = "\n".join(f"  {e['timestamp']} {e['host']} {e['level']} {e['message']}"
                        for e in inc["sample_events"][:C.LLM_SAMPLE_LINES])
    return f"""INCIDENT {inc['id']}
Title: {inc['title']}
Error type: {inc['error_type']}
Affected service: {inc['service']}
Score: {inc['score']} (band: {inc['band']})
Score breakdown:
{factors}
Events: {inc['event_count']} from sources {', '.join(inc['sources'])}
Hosts reporting it: {', '.join(inc['hosts'])}
First seen: {inc['first_seen']}
Last seen: {inc['last_seen']}
Unique message templates (count x template):
{templates}
Sample log lines:
{samples}

Reference runbooks (closest past incidents, may not match):
{_hint_text(hints)}
"""
