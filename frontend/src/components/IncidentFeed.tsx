// Left side: filters + the incident cards, highest score first.
// <motion.li layout> makes a card glide to its new place when the order changes,
// and slide in when it is new.

import { AnimatePresence, motion } from "motion/react";
import type { Band, Incident, Status } from "../api";
import { BAND_STYLE, BANDS, when, useNow } from "../lib";

export type Filters = { band: Band | "all"; status: Status | "all" };

export function IncidentFeed({ incidents, filters, setFilters, selectedId, onSelect, offline }: {
  incidents: Incident[];
  offline: boolean;
  filters: Filters;
  setFilters: (f: Filters) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const now = useNow();
  const shown = incidents
    .filter((i) => filters.band === "all" || i.band === filters.band)
    .filter((i) => filters.status === "all" || i.status === filters.status)
    .sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));

  return (
    <section className="flex min-h-0 flex-col" aria-label="Incident feed">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5">
        <Chips
          value={filters.band}
          options={["all", ...BANDS] as const}
          onChange={(band) => setFilters({ ...filters, band })}
        />
        <select
          value={filters.status}
          onChange={(e) => setFilters({ ...filters, status: e.target.value as Filters["status"] })}
          className="ml-auto rounded-md border border-line bg-page px-2 py-1 text-xs text-ink-2"
          aria-label="Filter by status"
        >
          <option value="all">All statuses</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
        </select>
      </div>

      <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        <AnimatePresence initial={false}>
          {shown.map((inc) => (
            <motion.li
              key={inc.id}
              layout
              initial={{ opacity: 0, x: -24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 420, damping: 36 }}
            >
              <Card inc={inc} now={now} selected={inc.id === selectedId} onClick={() => onSelect(inc.id)} />
            </motion.li>
          ))}
        </AnimatePresence>
        {shown.length === 0 && (
          <li className="px-2 py-10 text-center text-sm text-muted">
            {offline && incidents.length === 0
              ? "Waiting for the backend…"
              : incidents.length === 0 ? "No incidents yet. Press “Replay demo” to stream the scenario in." : "No incidents match these filters."}
          </li>
        )}
      </ul>
    </section>
  );
}

function Card({ inc, now, selected, onClick }: { inc: Incident; now: number; selected: boolean; onClick: () => void }) {
  const style = BAND_STYLE[inc.band];
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={`group relative flex w-full gap-3 overflow-hidden rounded-lg border p-3 pl-4 text-left transition
        ${selected ? "border-ink-2/40 bg-raised" : "border-line bg-surface hover:bg-raised"}`}
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${style.bar}`} aria-hidden />
      <div className="flex w-12 shrink-0 flex-col items-center">
        <span className={`w-full rounded-md py-1 text-center text-lg font-semibold ${style.chip}`}>{inc.score}</span>
        <span className={`mt-1 text-[11px] font-medium uppercase tracking-wide ${style.text}`}>{inc.band}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="truncate text-sm font-medium text-ink">{inc.title}</h3>
          <FixBadge inc={inc} />
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-2">
          <span title={`${inc.event_count} events, ${inc.unique_messages} unique message(s)`}>×{inc.event_count.toLocaleString()}</span>
          <span className="truncate" title={inc.hosts.join(", ")}>
            {inc.hosts.slice(0, 3).join(", ")}{inc.hosts.length > 3 ? ` +${inc.hosts.length - 3}` : ""}
          </span>
          <span className="text-muted" title="time of the last event">{when(inc.last_seen, now)}</span>
          {inc.status !== "open" && <span className="text-muted">· {inc.status}</span>}
        </div>
      </div>
    </button>
  );
}

export function FixBadge({ inc }: { inc: Incident }) {
  const r = { ...inc.resolution, source: inc.resolution?.source ?? "none" };
  const base = "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium";
  if (r.source === "rag") return <span className={`${base} bg-good/15 text-good`}>✓ Known fix</span>;
  if (r.source === "llm")
    return r.approved
      ? <span className={`${base} bg-good/15 text-good`}>✓ Approved AI fix</span>
      : <span className={`${base} bg-ai/15 text-ai`}>✦ AI-generated{r.cached ? " (cached)" : ""}</span>;
  if (r.source === "llm_pending" || r.source === "none")
    return <span className={`${base} flex items-center gap-1 bg-ink/10 text-ink-2`}><span className="pulse-dot size-1.5 rounded-full bg-ai" />Thinking…</span>;
  return <span className={`${base} bg-critical/15 text-up`} title={r.reason}>⚠ LLM unavailable</span>;
}

function Chips<T extends string>({ value, options, onChange }: { value: T; options: readonly T[]; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-1" role="group" aria-label="Filter by band">
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          aria-pressed={value === o}
          className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs capitalize transition
            ${value === o ? "bg-raised text-ink ring-1 ring-ink-2/30" : "text-ink-2 hover:bg-raised"}`}
        >
          {o !== "all" && <span className={`size-2 rounded-full ${BAND_STYLE[o as Band].bar}`} />}
          {o}
        </button>
      ))}
    </div>
  );
}
