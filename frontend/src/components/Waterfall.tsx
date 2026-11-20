// Severity breakdown as a horizontal waterfall:
// the base bar starts at 0, every factor starts where the previous one ended
// (+ goes right in red: more dangerous; − goes left in green: less dangerous),
// and the last row is the total, colored by its band. Hairlines mark the band thresholds.

import type { Band, Factor } from "../api";
import { BAND_STYLE } from "../lib";

const THRESHOLDS = [
  { at: 40, label: "medium" },
  { at: 70, label: "high" },
  { at: 90, label: "critical" },
];

export function Waterfall({ factors, score, band }: { factors: Factor[]; score: number; band: Band }) {
  let running = 0;
  const rows = factors.map((f) => {
    const start = running;
    running += f.points;
    return { ...f, start, end: running };
  });
  const max = Math.max(150, ...rows.map((r) => Math.max(r.start, r.end)), score);
  const pct = (v: number) => `${(Math.max(0, v) / max) * 100}%`;

  return (
    <div className="space-y-1.5" role="table" aria-label="Score breakdown">
      {/* threshold scale */}
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-3 text-[10px] text-muted" aria-hidden>
        <span />
        <div className="relative h-3">
          {THRESHOLDS.map((t) => (
            <span key={t.at} className="absolute -translate-x-1/2" style={{ left: pct(t.at) }}>{t.at}</span>
          ))}
        </div>
      </div>

      {rows.map((r, i) => {
        const isBase = r.factor === "base";
        const up = r.points >= 0;
        const left = Math.min(r.start, r.end);
        const color = isBase ? "var(--color-series-1)" : up ? "var(--color-up)" : "var(--color-good)";
        return (
          <div key={i} role="row" className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-3">
            <div role="cell" className="flex items-baseline gap-2 text-xs">
              <span className={`w-9 shrink-0 text-right font-semibold tabular-nums ${isBase ? "text-ink" : up ? "text-up" : "text-good"}`}>
                {isBase ? r.points : `${up ? "+" : "−"}${Math.abs(r.points)}`}
              </span>
              <span className="text-ink-2">{r.reason}</span>
            </div>
            <div role="cell" className="relative h-5">
              <Gridlines pct={pct} />
              <div
                className="absolute top-1 h-3 rounded-[3px]"
                style={{ left: pct(left), width: pct(Math.abs(r.points)), background: color, minWidth: 2 }}
                title={`${r.reason}: ${r.start} → ${Math.max(0, r.end)}`}
              />
            </div>
          </div>
        );
      })}

      {/* total */}
      <div role="row" className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-3 border-t border-line pt-2">
        <div role="cell" className="flex items-baseline gap-2 text-xs">
          <span className="w-9 shrink-0 text-right text-sm font-semibold tabular-nums text-ink">{score}</span>
          <span className="font-medium text-ink">
            Total → <span className={BAND_STYLE[band].text}>{band}</span>
            {score === 0 && running < 0 ? <span className="text-muted"> (floored at 0)</span> : null}
          </span>
        </div>
        <div role="cell" className="relative h-5">
          <Gridlines pct={pct} />
          <div className="absolute top-0.5 h-4 rounded-[3px]"
               style={{ left: 0, width: pct(score), background: BAND_STYLE[band].fill, minWidth: score ? 2 : 0 }} />
        </div>
      </div>
    </div>
  );
}

function Gridlines({ pct }: { pct: (v: number) => string }) {
  return (
    <>
      <span className="absolute inset-y-0 left-0 w-px bg-axis" />
      {THRESHOLDS.map((t) => (
        <span key={t.at} className="absolute inset-y-0 w-px bg-line" style={{ left: pct(t.at) }} />
      ))}
    </>
  );
}
