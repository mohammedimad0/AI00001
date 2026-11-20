// The page layout: top bar, [incident feed | incident report], charts at the bottom.
// App owns the shared state (via useLiveData) and hands pieces of it to each component.

import { useCallback, useState } from "react";
import { API_URL, api } from "./api";
import { BandChart, NoiseChart } from "./components/Charts";
import { IncidentFeed, type Filters } from "./components/IncidentFeed";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { IncidentReport } from "./components/IncidentReport";
import { StoryBar } from "./components/StoryBar";
import { TopBar } from "./components/TopBar";
import { useDemoStory } from "./useDemoStory";
import { useLiveData } from "./useLiveData";

export default function App() {
  const live = useLiveData();
  const [filters, setFilters] = useState<Filters>({ band: "all", status: "all" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const incidents = Object.values(live.incidents);
  const selected = selectedId ? live.incidents[selectedId] : undefined;
  const select = useCallback((id: string | null) => setSelectedId(id), []);
  const demo = useDemoStory({ incidents: live.incidents, stats: live.stats, health: live.health, resets: live.resets }, select);
  const resetAll = async () => {
    demo.stop();
    setSelectedId(null);
    try { await api.reset(); } catch { /* the backend-down banner already explains */ }
  };

  return (
    <div className="flex h-full flex-col">
      {live.connection === "down" && <BackendDownBanner onRetry={live.reload} />}
      <TopBar stats={live.stats} health={live.health} offline={live.connection === "down"}
              storyRunning={demo.story.running} onStory={demo.start}
              onReplayStarted={() => { setSelectedId(null); live.loadHealth(); }} />
      <StoryBar story={demo.story} onNext={demo.next} onStop={demo.stop} onReset={resetAll} onDismiss={demo.dismiss} />

      <main className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(340px,5fr)_7fr]">
        <div className="flex min-h-0 flex-col border-line lg:border-r">
          <ErrorBoundary name="incident feed">
            <IncidentFeed incidents={incidents} filters={filters} setFilters={setFilters} offline={live.connection === "down"}
                          selectedId={selectedId} onSelect={setSelectedId} />
          </ErrorBoundary>
        </div>
        <div className="flex min-h-0 flex-col bg-surface/40">
          {selected ? (
            <ErrorBoundary name="incident report" key={selected.id}>
              <IncidentReport incident={selected} onChanged={live.upsert} onClose={() => setSelectedId(null)} />
            </ErrorBoundary>
          ) : (
            <div className="grid flex-1 place-items-center p-8 text-center text-sm text-muted">
              <div>
                <div className="mb-1 text-ink-2">Select an incident</div>
                to see why it scored what it did, the fix, and the raw evidence.
              </div>
            </div>
          )}
        </div>
      </main>

      <footer className="grid grid-cols-1 gap-6 border-t border-line bg-surface px-5 py-4 md:grid-cols-[3fr_1fr]">
        <ErrorBoundary name="noise chart"><NoiseChart points={live.timeline} /></ErrorBoundary>
        <ErrorBoundary name="band chart"><BandChart stats={live.stats} /></ErrorBoundary>
      </footer>
    </div>
  );
}

function BackendDownBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-critical/50 bg-critical/15 px-5 py-2.5 text-sm">
      <span className="font-semibold text-up">⚠ Backend not reachable</span>
      <span className="text-ink-2">
        Can't reach <code className="font-mono text-ink">{API_URL}</code>. Start it with{" "}
        <code className="rounded bg-page px-1.5 py-0.5 font-mono text-ink">.\.venv\Scripts\python.exe -m backend</code>
        {" "}— the dashboard reconnects by itself.
      </span>
      <button onClick={onRetry} className="ml-auto rounded-md border border-line px-2.5 py-1 text-xs hover:bg-raised">Retry now</button>
    </div>
  );
}
