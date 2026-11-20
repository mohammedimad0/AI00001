"""Steps 1-3 demo: fake data -> LangGraph flow (score, known-fix lookup, LLM fallback) -> report.

Run:
  python demo.py            one run of the whole flow
  python demo.py --learn    the learning-loop demo: run once (TLS goes to the LLM), auto-approve
                            the AI fix, run again -> TLS is now a KNOWN FIX
Writes every JSON stage to output/ so you can see what each step produced.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from core import config as C
from core.generator import build_scenario
from core.scoring import action_for
from graph.flow import run_flow
from llm import client as llm
from rag import store

OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8")   # so arrows and ticks print on any Windows console


def run_once(label: str) -> dict:
    alertmanager_payload, loki_response = build_scenario()
    t = time.perf_counter()
    state = run_flow(alertmanager_payload, loki_response)
    secs = time.perf_counter() - t

    # Save each stage so you can open and inspect the JSON
    (OUT / "1_raw_alertmanager.json").write_text(json.dumps(alertmanager_payload, indent=2))
    (OUT / "1_raw_loki.json").write_text(json.dumps(loki_response, indent=2))
    (OUT / "2_normalized_events.json").write_text(
        json.dumps([e.to_dict() for e in state["events"]], indent=2))
    (OUT / "3_incidents.json").write_text(
        json.dumps([{k: v for k, v in i.items() if k != "resolution"} for i in state["incidents"]], indent=2))
    (OUT / "4_resolved_incidents.json").write_text(json.dumps(state["incidents"], indent=2))

    print_report(label, state, secs)
    return state


def print_report(label: str, state: dict, secs: float) -> None:
    s = state["stats"]
    print()
    print(f"  ===== {label} =====")
    print(f"  {s['raw_events']} raw alerts/logs  ->  {s['incidents']} incidents  ->  {s['pages']} pages")
    print(f"  fixes: {s['known_fix']} known (runbook), {s['ai_generated']} AI-generated, "
          f"{s['llm_unavailable']} LLM unavailable   (flow took {secs:.1f} s)")
    print()
    print(f"  {'ID':<9}{'SCORE':>6}  {'BAND':<9}{'EVENTS':>7}  {'ACTION':<18}TITLE")
    print("  " + "-" * 92)
    pad = " " * 11
    for inc in state["incidents"]:
        print(f"  {inc['id']:<9}{inc['score']:>6}  {inc['band']:<9}{inc['event_count']:>7}  "
              f"{action_for(inc['band']):<18}{inc['title']}")
        for f in inc["factors"]:
            sign = "+" if f["points"] >= 0 else ""
            print(f"  {'':<9}{sign + str(f['points']):>6}  {f['reason']}")
        r = inc["resolution"]
        if r["source"] == "rag":
            print(f"{pad}✔ KNOWN FIX ({r['runbook_id']}, similarity {r['similarity']:.2f}) {r['runbook_title']}")
        elif r["source"] == "llm":
            print(f"{pad}🤖 AI-GENERATED ({r['model']}, confidence {r['confidence']:.2f}, "
                  f"{r['llm_seconds']} s) - needs review")
            print(f"{pad}   root cause: {r['root_cause']}")
            print(f"{pad}   impact:     {r['impact']}")
            for i, step in enumerate(r["fix_steps"], 1):
                print(f"{pad}   {i}. {step}")
        else:
            print(f"{pad}⚠ NO KNOWN FIX, LLM UNAVAILABLE: {r.get('reason', '')}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--learn", action="store_true",
                        help="run, auto-approve the AI fix, run again to show it is now a known fix")
    args = parser.parse_args()

    if not llm.is_available():
        print(f"\n  NOTE: Ollama is not reachable at {C.OLLAMA_URL}. Incidents without a runbook "
              f"will show 'LLM unavailable'. Start it with: ollama serve")

    if not args.learn:
        run_once("RUN")
        print(f"  JSON for every stage written to {OUT}/")
        return

    removed = store.forget_learned()             # start clean so this demo can be repeated
    if removed:
        print(f"\n  (reset: forgot {removed} previously approved AI runbook(s))")

    first = run_once("RUN 1: before learning")
    ai = [i for i in first["incidents"] if i["resolution"]["source"] == "llm"]
    if not ai:
        print("  No AI-generated fix to approve (is Ollama running and the model pulled?). Stopping.")
        return

    for inc in ai:
        rb = store.approve_fix(inc, inc["resolution"])
        print(f"  ENGINEER APPROVES the AI fix for {inc['id']} ({inc['title']})")
        print(f"  -> saved as runbook {rb['id']} in ChromaDB and runbooks/approved/{rb['id']}.json")

    run_once("RUN 2: after learning")
    print(f"  JSON for every stage written to {OUT}/")


if __name__ == "__main__":
    main()
