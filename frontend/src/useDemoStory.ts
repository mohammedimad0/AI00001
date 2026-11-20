// The scripted ~3-minute "Demo story". It drives the real system through the real API
// (reset, replay, approve, inject) and selects the right incident at each stage, while
// a caption explains what the audience is seeing. Works fully offline in FAKE mode.
//
// Each wait can be cut short with "Next", and the whole run can be stopped at any time.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Health, type Incident, type Stats } from "./api";

export const STAGES = [
  { key: "a", title: "Noise flood" },
  { key: "b", title: "Grouping" },
  { key: "c", title: "Brute force → page" },
  { key: "d", title: "DB outage merged" },
  { key: "e", title: "CPU blip ignored" },
  { key: "f", title: "AI writes a fix" },
  { key: "g", title: "Learned" },
] as const;

export interface Story {
  running: boolean;
  stage: number;           // index into STAGES, STAGES.length = finished
  text: string;
  error: string | null;
}

const IDLE: Story = { running: false, stage: -1, text: "", error: null };

class Stopped extends Error {}

export function useDemoStory(data: { incidents: Record<string, Incident>; stats: Stats; health: Health | null; resets: number },
                             select: (id: string | null) => void) {
  const [story, setStory] = useState<Story>(IDLE);
  const live = useRef(data);
  const runId = useRef(0);
  const skip = useRef<(() => void) | null>(null);

  const ownResetAt = useRef(0);
  const running = useRef(false);
  useEffect(() => { live.current = data; }, [data]);
  useEffect(() => { running.current = story.running; }, [story.running]);

  // Everyone shares one backend. If another screen resets the demo while our story runs,
  // stop politely instead of failing later on incidents that no longer exist.
  useEffect(() => {
    if (running.current && Date.now() - ownResetAt.current > 5000) {
      runId.current += 1;
      skip.current?.();
      setStory({ running: false, stage: -1, text: "",
        error: "The demo was reset from another screen, so the story stopped. Press “Demo story” to start again." });
    }
  }, [data.resets]);

  const stop = useCallback(() => {
    runId.current += 1;
    skip.current?.();
    setStory(IDLE);
  }, []);

  const next = useCallback(() => skip.current?.(), []);

  const start = useCallback(async () => {
    const id = ++runId.current;
    const alive = () => { if (runId.current !== id) throw new Stopped(); };
    const say = (stage: number, text: string) => { alive(); setStory({ running: true, stage, text, error: null }); };

    // wait up to `ms`, or until `until()` is true, or until "Next" is pressed
    const wait = (ms: number, until?: () => boolean) => new Promise<void>((resolve) => {
      const started = Date.now();
      const timer = window.setInterval(() => {
        if (runId.current !== id || Date.now() - started >= ms || (until && until())) finish();
      }, 250);
      const finish = () => { window.clearInterval(timer); skip.current = null; resolve(); };
      skip.current = finish;
    }).then(alive);

    const all = () => Object.values(live.current.incidents);
    const find = (pred: (i: Incident) => boolean) => all().find(pred);
    const s = () => live.current.stats;

    try {
      // a) noise flood
      say(0, "Prometheus alerts and Loki log lines start pouring in, hundreds of them. Without help, on-call would be paged for each one.");
      select(null);
      ownResetAt.current = Date.now();
      await api.reset();
      await api.replay();
      await wait(9000, () => s().raw_events > 120);
      say(0, "Every alert and log line is turned into one standard event and fingerprinted: “Login failed for user root from 175.45.176.9” and “…user admin from 175.45.176.88” are the same message.");
      await wait(40000, () => s().raw_events >= 386 && !live.current.health?.replay_running);

      // b) grouping
      const st = s();
      say(1, `${st.raw_events} raw alerts → ${st.incidents} incidents → ${st.pages} pages. Duplicates are counted, not repeated; symptoms of one fault are merged. ${st.noise_reduction_pct}% less noise.`);
      await wait(14000);

      // c) KP brute force
      const kp = find((i) => i.error_type === "auth_failure" && i.country === "KP");
      if (kp) select(kp.id);
      say(2, `${kp?.event_count ?? 120} failed logins in 3 minutes from North Korea. Base 40 + high-risk country 40 + burst 30 = ${kp?.score ?? 110} → critical. This one pages on-call, and every point has a reason.`);
      await wait(24000);

      // d) DB outage
      const db = find((i) => i.error_type === "db_down");
      if (db) select(db.id);
      say(3, `1 Prometheus “PostgresDown” alert + ${(db?.event_count ?? 201) - 1} “connection refused” log lines from ${(db?.hosts.length ?? 5) - 1} web servers → merged into ONE incident on db-primary. Known fix ${db?.resolution.runbook_id ?? "RB-007"} found in the runbook library.`);
      await wait(24000);

      // e) CPU blip
      const cpu = find((i) => i.error_type === "high_cpu");
      if (cpu) select(cpu.id);
      say(4, "A CPU spike on web-03 that fixed itself in 60 seconds. 30 − 30 = 0 → low. It is logged, but nobody is woken up at 3 am.");
      await wait(18000);

      // f) TLS -> LLM -> approve
      let tls = find((i) => i.error_type === "tls_expired");
      if (tls) select(tls.id);
      say(5, "Expired TLS certificate: no runbook matches. The local LLM (on this laptop, no cloud) writes the root cause and fix as strict JSON…");
      await wait(75000, () => {
        const src = find((i) => i.error_type === "tls_expired")?.resolution.source;
        return src === "llm" || src === "llm_unavailable";
      });
      tls = find((i) => i.error_type === "tls_expired");
      const r = tls?.resolution;
      if (tls && r?.source === "llm") {
        say(5, `AI fix ready${r.cached ? " (saved sample, live LLM offline)" : ""}: “${r.root_cause}”, confidence ${Math.round((r.confidence ?? 0) * 100)}%. An engineer reviews it and clicks Approve → saved to the knowledge base.`);
        await wait(14000);
        if (!r.approved) await api.approve(tls.id);
        await wait(5000);

        // g) learning loop
        say(6, "Two hours later, the same certificate problem comes back…");
        const out = await api.injectTls();
        const againId = out.new_incidents[0];
        await wait(5000, () => !!live.current.incidents[againId]);
        if (againId) select(againId);
        const again = live.current.incidents[againId]?.resolution;
        say(6, again?.source === "rag"
          ? `…and now it is a Known fix from the knowledge base (${again.runbook_id}, similarity ${Math.round((again.similarity ?? 0) * 100)}%). No LLM call needed: the system learned from one approval.`
          : "…the new incident is being matched against the knowledge base.");
        await wait(20000);
      } else {
        say(5, "The LLM could not answer right now, so there is nothing to approve. The rest of the system keeps working.");
        await wait(8000);
      }

      const end = s();
      setStory({ running: false, stage: STAGES.length, error: null,
        text: `That's the story: ${end.raw_events} raw alerts → ${end.incidents} incidents → ${end.pages} pages, each with a reason and a fix.` });
    } catch (e) {
      if (e instanceof Stopped) return;
      setStory({ running: false, stage: -1, text: "", error: e instanceof Error ? e.message : String(e) });
    }
  }, [select]);

  return { story, start, next, stop, dismiss: () => setStory(IDLE) };
}
