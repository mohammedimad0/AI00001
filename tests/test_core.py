"""Steps 1 logic: fingerprinting, scoring, grouping (no server, no database)."""
from core.fingerprint import fingerprint, make_template
from core.generator import build_scenario
from core.pipeline import run


def _by_title(result, text):
    return [i for i in result["incidents"] if text in i.title]


def test_fingerprint_ignores_ips_ports_and_users():
    a = "Login failed for user root from 175.45.176.9 port 40211"
    b = "Login failed for user admin from 175.45.176.88 port 51990"
    assert make_template(a) == "login failed for user <user> from <ip> port <num>"
    assert fingerprint("auth_failure", "auth", a) == fingerprint("auth_failure", "auth", b)


def test_fingerprint_differs_per_service():
    msg = "Login failed for user root from 175.45.176.9 port 40211"
    assert fingerprint("auth_failure", "auth", msg)[1] != fingerprint("auth_failure", "vpn", msg)[1]


def test_scenario_totals():
    r = run(*build_scenario())
    assert (r["raw_event_count"], r["incident_count"], r["paged_count"]) == (386, 7, 2)


def test_kp_brute_force_scores_110_critical():
    (inc,) = _by_title(run(*build_scenario()), "from KP")
    assert (inc.score, inc.band) == (110, "critical")
    assert {f["factor"] for f in inc.factors} == {"base", "geo_risk", "burst"}


def test_cpu_blip_scores_0_low():
    (inc,) = _by_title(run(*build_scenario()), "High CPU")
    assert (inc.score, inc.band) == (0, "low")
    assert any(f["factor"] == "self_resolved_blip" for f in inc.factors)


def test_db_outage_merges_alert_and_logs_into_one_incident():
    db = [i for i in run(*build_scenario())["incidents"] if i.error_type == "db_down"]
    assert len(db) == 1                                   # ONE incident, not 201
    (inc,) = db
    assert inc.service == "db-primary"
    assert inc.sources == {"prometheus", "loki"}          # the alert AND the logs
    assert inc.count == 201                               # 1 alert + 4 hosts x 50 log lines
