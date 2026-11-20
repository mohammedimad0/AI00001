// Right side: the full report for one incident.
// It fetches GET /incidents/{id} when you click a card, and again whenever a live update
// says this incident changed (its updated_at moves), e.g. when the LLM answer arrives.

import { useEffect, useState } from "react";
import { api, type Incident, type IncidentDetail } from "../api";
import { BAND_STYLE, clock, Tooltip, useWidth } from "../lib";
import { FixBadge } from "./IncidentFeed";
import { Waterfall } from "./Waterfall";

export function IncidentReport({ incident, onChanged, onClose }:
  { incident: Incident; onChanged: (inc: Incident) => void; onClose: () => void }) {
  const [detail, setDetail] = useState<IncidentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.incident(incident.id)
      .then((d) => { if (alive) { setDetail(d); setLoadError(null); } })
      .catch((e) => alive && setLoadError(String(e.message ?? e)));
    return () => { alive = false; };
  }, [incident.id, incident.updated_at]);

  const d = detail && detail.id === incident.id ? { ...detail, ...incident } : null;
  const style = BAND_STYLE[incident.band];

  return (
    <article className="flex min-h-0 flex-col" aria-label={`Incident ${incident.id}`}>
      <header className="flex items-start gap-3 border-b border-line px-5 py-3.5">
        <span className={`rounded-md px-2.5 py-1 text-xl font-semibold ${style.chip}`}>{incident.score}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold">{incident.title}</h2>
            <FixBadge inc={incident} />
          </div>
          <div className="mt-0.5 text-xs text-ink-2">
            {incident.id} · <span className={style.text}>{incident.band}</span> → {incident.action} · status {incident.status}
            {" · "}{clock(incident.first_seen)}–{clock(incident.last_seen)}
          </div>
        </div>
        <AckButton incident={incident} onChanged={onChanged} />
        <button onClick={onClose} className="rounded-md px-2 py-1 text-ink-2 hover:bg-raised" aria-label="Close report">✕</button>
      </header>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-4">
        {loadError && <p className="rounded-md border border-critical/40 bg-critical/10 p-2 text-xs text-up">Could not load details: {loadError}</p>}

        <Section title="Why this score">
          <Waterfall factors={incident.factors} score={incident.score} band={incident.band} />
        </Section>

        <Section title="Fix">
          <FixPanel incident={incident} onChanged={onChanged} />
        </Section>

        <Section title="Raw evidence">
          {d ? <Evidence d={d} /> : <p className="text-xs text-muted">Loading…</p>}
        </Section>
      </div>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function AckButton({ incident, onChanged }: { incident: Incident; onChanged: (inc: Incident) => void }) {
  const [busy, setBusy] = useState(false);
  if (incident.status !== "open") return <span className="rounded-md bg-raised px-2.5 py-1.5 text-xs text-ink-2">✓ Acknowledged</span>;
  return (
    <button
      disabled={busy}
      onClick={async () => { setBusy(true); try { onChanged(await api.ack(incident.id)); } finally { setBusy(false); } }}
      className="rounded-md border border-line px-2.5 py-1.5 text-xs text-ink hover:bg-raised disabled:opacity-50"
    >
      I'm on it (ack)
    </button>
  );
}

function FixPanel({ incident, onChanged }: { incident: Incident; onChanged: (inc: Incident) => void }) {
  const r = incident.resolution ?? { source: "none" };
  const [checked, setChecked] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => { setChecked({}); setMessage(null); }, [incident.id]);

  if (!r.source || r.source === "none" || r.source === "llm_pending") {
    return (
      <div className="flex items-center gap-2 rounded-md border border-ai/30 bg-ai/10 p-3 text-sm text-ink-2">
        <span className="pulse-dot size-2 rounded-full bg-ai" />
        No runbook matched (closest {r.best_runbook_id ?? "–"}, {pct(r.best_similarity)}). The local AI is writing a fix…
      </div>
    );
  }
  if (r.source === "llm_unavailable") {
    return (
      <div className="rounded-md border border-critical/40 bg-critical/10 p-3 text-sm text-ink-2">
        No runbook matched and the local LLM could not answer: <span className="text-ink">{r.reason}</span>
      </div>
    );
  }

  async function act(kind: "approve" | "reject") {
    setBusy(kind);
    setMessage(null);
    try {
      if (kind === "approve") {
        const res = await api.approve(incident.id);
        onChanged(res.incident);
        // the chip below ("Saved to knowledge base") is the confirmation
      } else {
        const res = await api.reject(incident.id, "rejected from dashboard");
        onChanged(res.incident);
        setMessage({ ok: true, text: "Rejection recorded. Nothing was learned from this fix." });
      }
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }

  const steps = r.fix_steps ?? [];
  return (
    <div className="space-y-4">
      {/* where the fix comes from */}
      {r.source === "rag" ? (
        <div className="rounded-md border border-good/30 bg-good/10 px-3 py-2 text-sm">
          <span className="font-medium text-good">Known fix</span>
          <span className="text-ink-2"> from runbook </span>
          <span className="font-mono text-ink">{r.runbook_id}</span>
          <span className="text-ink-2"> “{r.runbook_title}” · similarity </span>
          <span className="font-medium text-ink">{pct(r.similarity)}</span>
        </div>
      ) : (
        <div className="rounded-md border border-ai/30 bg-ai/10 px-3 py-2 text-sm">
          <span className="font-medium text-ai">AI-generated, needs review</span>
          {r.cached && <span className="ml-1.5 rounded bg-medium/20 px-1.5 py-0.5 text-[11px] font-medium text-medium" title={r.reason}>cached sample (live LLM offline)</span>}
          <span className="text-ink-2"> · {r.model} · confidence </span>
          <span className="font-medium text-ink">{pct(r.confidence)}</span>
          {r.llm_seconds !== undefined && <span className="text-ink-2"> · written in {r.llm_seconds} s</span>}
          {r.severity_comment && <p className="mt-1 text-xs text-ink-2">{r.severity_comment}</p>}
        </div>
      )}

      <Field label="Root cause">{r.root_cause}</Field>
      <Field label="Impact">{r.impact}</Field>

      <div>
        <div className="mb-1.5 text-xs text-muted">Fix steps <span className="text-muted">({Object.values(checked).filter(Boolean).length}/{steps.length} done)</span></div>
        <ol className="space-y-1">
          {steps.map((s, i) => (
            <li key={i}>
              <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-1.5 py-1 text-sm hover:bg-raised">
                <input type="checkbox" checked={!!checked[i]} onChange={(e) => setChecked({ ...checked, [i]: e.target.checked })}
                       className="mt-0.5 size-4 shrink-0 accent-good" />
                <span className={checked[i] ? "text-muted line-through" : "text-ink"}>{i + 1}. {s}</span>
              </label>
            </li>
          ))}
        </ol>
      </div>

      {r.prevention && <Field label="Prevention">{r.prevention}</Field>}

      {r.source === "llm" && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {r.approved ? (
            <span className="rounded-md bg-good/15 px-3 py-1.5 text-sm font-medium text-good">
              ✓ Saved to knowledge base as {r.approved_runbook_id}. Next time this is a known fix.
            </span>
          ) : r.rejected ? (
            <span className="rounded-md bg-raised px-3 py-1.5 text-sm text-ink-2">✕ Rejected</span>
          ) : (
            <>
              <button disabled={!!busy} onClick={() => act("approve")}
                      className="rounded-md bg-good px-3.5 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-50">
                {busy === "approve" ? "Saving…" : "Approve fix"}
              </button>
              <button disabled={!!busy} onClick={() => act("reject")}
                      className="rounded-md border border-line px-3.5 py-1.5 text-sm text-ink hover:bg-raised disabled:opacity-50">
                {busy === "reject" ? "…" : "Reject"}
              </button>
              <span className="text-xs text-muted">Approving teaches the system: next time this is a known fix.</span>
            </>
          )}
        </div>
      )}
      {message && <p className={`text-sm ${message.ok ? "text-good" : "text-up"}`}>{message.text}</p>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-xs text-muted">{label}</div>
      <p className="text-sm leading-relaxed text-ink">{children || "unknown"}</p>
    </div>
  );
}

function Evidence({ d }: { d: IncidentDetail }) {
  const templates = Object.values(d.fingerprints).sort((a, b) => b.count - a.count);
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 text-xs text-muted">
          {d.event_count.toLocaleString()} events collapsed into {templates.length} unique message{templates.length === 1 ? "" : "s"}
          {" · "}hosts {d.hosts.join(", ")} · sources {d.sources.join(" + ")}
        </div>
        <ul className="divide-y divide-line rounded-md border border-line">
          {templates.map((t) => (
            <li key={t.template} className="flex items-baseline gap-3 px-3 py-1.5">
              <span className="w-12 shrink-0 text-right text-xs font-semibold tabular-nums text-ink">×{t.count}</span>
              <code className="min-w-0 wrap-break-word font-mono text-xs text-ink-2">{t.template}</code>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="mb-1.5 text-xs text-muted">Events per minute</div>
        <MiniTimeline points={d.timeline} />
      </div>

      <div>
        <div className="mb-1.5 text-xs text-muted">Sample log lines (first {d.sample_events.length})</div>
        <pre className="max-h-48 overflow-auto rounded-md border border-line bg-page p-2.5 font-mono text-[11px] leading-5 text-ink-2">
          {d.sample_events.map((e) => `${e.timestamp.slice(11, 19)}  ${e.host.padEnd(9)} ${e.level.padEnd(5)} ${e.message}`).join("\n")}
        </pre>
      </div>
    </div>
  );
}

/** Tiny column chart of this incident's events per minute (one series: no legend needed). */
function MiniTimeline({ points }: { points: { minute: string; count: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();
  if (points.length === 0) return <p className="text-xs text-muted">No events.</p>;
  const H = 56;
  const max = Math.max(...points.map((p) => p.count));
  const slot = width / points.length;
  const w = Math.max(2, Math.min(24, slot * 0.6));
  return (
    <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
      <svg width={width} height={H} className="block" role="img" aria-label={`Events per minute, peak ${max}`}>
        {points.map((p, i) => {
          const h = Math.max(1, (p.count / max) * (H - 2));
          return (
            <g key={p.minute} onMouseEnter={() => setHover(i)}>
              <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
              <rect x={i * slot + (slot - w) / 2} y={H - h} width={w} height={h} rx={2}
                    fill="var(--color-series-1)" opacity={hover === null || hover === i ? 1 : 0.45} />
            </g>
          );
        })}
        <line x1="0" x2={width} y1={H - 0.5} y2={H - 0.5} stroke="var(--color-axis)" />
      </svg>
      <div className="mt-0.5 flex justify-between text-[10px] text-muted">
        <span>{points[0].minute.slice(11)}</span><span>{points[points.length - 1].minute.slice(11)} UTC</span>
      </div>
      {hover !== null && (
        <Tooltip x={Math.min(Math.max((hover + 0.5) * slot, 70), width - 70)} y={0}>
          <span className="text-ink-2">{points[hover].minute.slice(11)}</span> · <b>{points[hover].count}</b> events
        </Tooltip>
      )}
    </div>
  );
}

function pct(v: number | undefined) {
  return v === undefined ? "–" : `${Math.round(v * 100)}%`;
}
