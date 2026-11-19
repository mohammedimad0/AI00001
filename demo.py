"""Steps 1-2 demo: generate fake data, run the pipeline, look up known fixes, print the result.

Run:  python demo.py
Writes every JSON stage to output/ so you can see what each step produced.
"""
import json
import sys
import time
from pathlib import Path

from core.generator import build_scenario
from core.pipeline import run
from core.scoring import action_for
from rag import matcher, store

OUT = Path(__file__).parent / "output"
OUT.mkdir(exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8")   # so the arrow prints on any Windows console


def main():
    alertmanager_payload, loki_response = build_scenario()
    result = run(alertmanager_payload, loki_response)
    incidents = [i.to_dict() for i in result["incidents"]]

    # Step 2: RAG - look up a known fix for every incident
    t = time.perf_counter()
    n_runbooks = store.load_runbooks()
    for inc in incidents:
        inc["resolution"] = matcher.resolve(inc)
    rag_secs = time.perf_counter() - t

    # Save each stage so you can open and inspect the JSON
    (OUT / "1_raw_alertmanager.json").write_text(json.dumps(alertmanager_payload, indent=2))
    (OUT / "1_raw_loki.json").write_text(json.dumps(loki_response, indent=2))
    (OUT / "2_normalized_events.json").write_text(
        json.dumps([e.to_dict() for e in result["events"]], indent=2))
    (OUT / "3_incidents.json").write_text(
        json.dumps([i.to_dict() for i in result["incidents"]], indent=2))
    (OUT / "4_resolved_incidents.json").write_text(json.dumps(incidents, indent=2))

    print()
    print(f"  {result['raw_event_count']} raw alerts/logs  ->  "
          f"{result['incident_count']} incidents  ->  {result['paged_count']} pages")
    print(f"  RAG: {n_runbooks} runbooks in ChromaDB, lookup took {rag_secs:.1f} s")
    print()
    print(f"  {'ID':<9}{'SCORE':>6}  {'BAND':<9}{'EVENTS':>7}  {'ACTION':<18}TITLE")
    print("  " + "-" * 92)
    for inc in incidents:
        print(f"  {inc['id']:<9}{inc['score']:>6}  {inc['band']:<9}{inc['event_count']:>7}  "
              f"{action_for(inc['band']):<18}{inc['title']}")
        for f in inc["factors"]:
            sign = "+" if f["points"] >= 0 else ""
            print(f"  {'':<9}{sign + str(f['points']):>6}  {f['reason']}")
        r = inc["resolution"]
        if r["source"] == "rag":
            print(f"  {'':<9}  ✔ KNOWN FIX ({r['runbook_id']}, similarity {r['similarity']:.2f}) "
                  f"{r['runbook_title']}")
        else:
            print(f"  {'':<9}  ✘ NO MATCH → needs LLM "
                  f"(closest {r['best_runbook_id']}, similarity {r['best_similarity']:.2f})")
        print()
    print(f"  JSON for every stage written to {OUT}/")


if __name__ == "__main__":
    main()
