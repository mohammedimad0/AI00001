// Top bar: the noise counter (the headline number), health dots, and the Replay demo button.

import { useState } from "react";
import { api, type Health, type Stats } from "../api";
import { CountUp } from "../lib";

export function TopBar({ stats, health, offline, storyRunning, onStory, onReplayStarted }: {
  stats: Stats; health: Health | null; offline: boolean; storyRunning: boolean;
  onStory: () => void; onReplayStarted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = busy || !!health?.replay_running || storyRunning;
  const fakeOff = health?.data_source === "live";

  async function replay() {
    setBusy(true);
    setError(null);
    try {
      await api.reset();
      await api.replay();
      onReplayStarted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <header className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-line bg-surface px-5 py-3">
      <div className="flex items-center gap-2.5">
        <span className="grid size-7 place-items-center rounded-md bg-critical/15 text-critical" aria-hidden>
          <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
          </svg>
        </span>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Pager Intelligence</div>
          <div className="text-xs text-muted">alerts in, incidents out</div>
        </div>
        <SourceBadges health={health} />
      </div>

      {/* The headline: raw -> incidents -> pages */}
      <div className="flex flex-1 items-baseline justify-center gap-3 text-ink" aria-live="polite">
        <Figure value={stats.raw_events} label="raw alerts" />
        <Arrow />
        <Figure value={stats.incidents} label="incidents" />
        <Arrow />
        <Figure value={stats.pages} label={stats.pages === 1 ? "page" : "pages"} accent />
        <span className="ml-3 rounded-full border border-good/40 bg-good/10 px-2.5 py-0.5 text-sm font-medium text-good">
          <CountUp value={stats.noise_reduction_pct * 10} format={(n) => (n / 10).toFixed(1)} />% noise cut
        </span>
      </div>

      <div className="flex items-center gap-5">
        <HealthDot label="Ollama" ok={health?.ollama.ok} detail={health ? (health.ollama.reachable ? (health.ollama.model_pulled ? health.ollama.model : `${health.ollama.model} not pulled`) : "not running") : "unknown"} />
        <HealthDot label="ChromaDB" ok={health?.chromadb.ok} detail={health?.chromadb.ok ? `${health.chromadb.runbooks} runbooks` : "unknown"} />
        <button
          onClick={onStory}
          disabled={running || offline || fakeOff}
          className="rounded-md bg-ai px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          title={fakeOff ? "Needs fake data (DATA_SOURCE is 'live')" : "A scripted 3-minute walk through the whole system, with captions"}
        >
          ★ Demo story
        </button>
        <button
          onClick={replay}
          disabled={running || offline || fakeOff}
          className="rounded-md bg-series-1 px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          title="Clears everything, then streams the demo scenario in over ~30 seconds"
        >
          {running && !storyRunning ? "Replaying…" : "▶ Replay demo"}
        </button>
      </div>
      {error && <div className="w-full text-right text-xs text-up">Replay failed: {error}</div>}
    </header>
  );
}

function Figure({ value, label, accent = false }: { value: number; label: string; accent?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={`text-3xl font-semibold ${accent ? "text-critical" : ""}`}><CountUp value={value} /></span>
      <span className="text-sm text-ink-2">{label}</span>
    </span>
  );
}

function Arrow() {
  return <span className="text-xl text-muted" aria-hidden>→</span>;
}

/** Where incidents come from: LIVE (Prometheus webhook + Loki poller) and/or FAKE (demo replay). */
function SourceBadges({ health }: { health: Health | null }) {
  if (!health) return null;
  const mode = health.data_source;
  const live = mode === "live" || mode === "both";
  const fake = mode === "fake" || mode === "both";
  const lokiOk = health.loki?.reachable;
  return (
    <div className="flex gap-1.5">
      {live && (
        <span
          className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider
            ${lokiOk ? "bg-critical/20 text-up" : "bg-raised text-muted"}`}
          title={lokiOk
            ? `Live: Alertmanager webhook + Loki poller (${health.loki.lines_ingested} log lines read)`
            : `Live sources enabled, but Loki is not reachable${health.loki?.last_error ? `: ${health.loki.last_error}` : ""}`}
        >
          <span className={`size-1.5 rounded-full ${lokiOk ? "pulse-dot bg-critical" : "bg-muted"}`} />
          LIVE{lokiOk ? "" : " · Loki off"}
        </span>
      )}
      {fake && (
        <span className="rounded bg-series-1/20 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-series-1"
              title="Fake scenario available via Replay demo">
          FAKE
        </span>
      )}
    </div>
  );
}

function HealthDot({ label, ok, detail }: { label: string; ok: boolean | undefined; detail: string }) {
  const color = ok === undefined ? "bg-muted" : ok ? "bg-good" : "bg-critical";
  return (
    <span className="flex items-center gap-1.5 text-xs" title={`${label}: ${detail}`}>
      <span className={`size-2.5 rounded-full ${color}`} />
      <span className="text-ink-2">{label}</span>
      <span className="text-muted">{ok === undefined ? "?" : ok ? "ok" : "down"}</span>
    </span>
  );
}
