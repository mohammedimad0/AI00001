"""Severity scoring: base score + context factors, in both directions.

Every factor that fires is recorded with its points and a reason,
so the dashboard can show WHY an incident got its score.
"""
from __future__ import annotations

from . import config as C
from .models import Incident


def _max_in_window(timestamps, window) -> int:
    """Largest number of events inside any sliding window of the given length."""
    ts = sorted(timestamps)
    best, left = 0, 0
    for right, t in enumerate(ts):
        while t - ts[left] > window:
            left += 1
        best = max(best, right - left + 1)
    return best


def score_incident(inc: Incident) -> Incident:
    factors = []
    base = C.BASE_SEVERITY.get(inc.error_type, C.BASE_SEVERITY["unknown"])
    factors.append({"factor": "base", "points": base,
                    "reason": f"{C.ERROR_LABELS.get(inc.error_type, inc.error_type)} starts at {base}"})

    # Geo risk
    if inc.country in C.HIGH_RISK_COUNTRIES:
        factors.append({"factor": "geo_risk", "points": C.GEO_RISK_POINTS,
                        "reason": f"Source IPs geolocate to high-risk country {inc.country}"})

    # Burst vs recurring
    peak = _max_in_window([e.timestamp for e in inc.events], C.BURST_WINDOW)
    span = inc.last_seen - inc.first_seen
    is_burst = peak >= C.BURST_THRESHOLD
    if is_burst:
        mins = int(C.BURST_WINDOW.total_seconds() // 60)
        factors.append({"factor": "burst", "points": C.BURST_POINTS,
                        "reason": f"{peak} events within {mins} minutes"})
    elif inc.count >= C.RECURRING_MIN_COUNT and span >= C.RECURRING_MIN_SPAN:
        factors.append({"factor": "recurring", "points": C.RECURRING_POINTS,
                        "reason": f"Seen {inc.count} times over {int(span.total_seconds() // 60)} minutes"})

    # Critical asset
    if inc.service in C.CRITICAL_SERVICES:
        factors.append({"factor": "critical_asset", "points": C.CRITICAL_ASSET_POINTS,
                        "reason": f"{inc.service} is a critical service"})

    # Blast radius
    if len(inc.hosts) >= C.MANY_HOSTS_THRESHOLD:
        factors.append({"factor": "many_hosts", "points": C.MANY_HOSTS_POINTS,
                        "reason": f"{len(inc.hosts)} hosts affected: {', '.join(sorted(inc.hosts))}"})

    # Self-resolving blip (pulls the score DOWN)
    all_resolved = all(e.resolved_at for e in inc.events)
    if all_resolved and inc.count <= C.BLIP_MAX_COUNT:
        longest = max(e.resolved_at - e.timestamp for e in inc.events)
        if longest <= C.BLIP_MAX_DURATION:
            factors.append({"factor": "self_resolved_blip", "points": C.BLIP_POINTS,
                            "reason": f"Resolved itself in {int(longest.total_seconds())} seconds"})

    inc.score = max(0, sum(f["points"] for f in factors))
    inc.factors = factors
    for minimum, band, _action in C.BANDS:
        if inc.score >= minimum:
            inc.band = band
            break
    return inc


def action_for(band: str) -> str:
    return next(action for _m, b, action in C.BANDS if b == band)
