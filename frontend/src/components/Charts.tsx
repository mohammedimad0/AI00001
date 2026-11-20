// The two bottom charts.
// 1. Raw events per minute vs incidents created per minute: two panels stacked on ONE shared
//    time axis (raw events reach ~80/min, incidents are 0-1/min, so one shared y-scale
//    would flatten incidents to nothing, and two y-scales on one chart would mislead).
// 2. Incidents by band: one horizontal bar per band, value at the tip.

import { useState } from "react";
import type { Band, Stats, TimelinePoint } from "../api";
import { BAND_STYLE, BANDS, Swatch, Tooltip, useWidth } from "../lib";


function niceMax(v: number) {
  if (v <= 1) return 1;
  const step = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / step) * step;
}

export function NoiseChart({ points }: { points: TimelinePoint[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const totalRaw = points.reduce((s, p) => s + p.raw, 0);
  const totalInc = points.reduce((s, p) => s + p.incidents, 0);

  const GUTTER = 34, PAD = 16, TOP_H = 96, GAP = 22, BOT_H = 34, AXIS_H = 18;
  const H = PAD + TOP_H + GAP + BOT_H + AXIS_H;
  const plotW = Math.max(0, width - GUTTER);
  const n = Math.max(points.length, 1);
  const slot = plotW / n;
  const barW = Math.max(1, Math.min(24, slot * 0.62));
  const rawMax = niceMax(Math.max(1, ...points.map((p) => p.raw)));
  const incMax = Math.max(1, ...points.map((p) => p.incidents));
  const peak = points.reduce((best, p, i) => (p.raw > (points[best]?.raw ?? -1) ? i : best), 0);
  const x = (i: number) => GUTTER + i * slot + (slot - barW) / 2;
  const tickEvery = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 70))));

  return (
    <figure className="flex min-w-0 flex-col">
      <figcaption className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-ink">Noise squashed: raw events vs incidents, per minute</span>
        <span className="flex gap-4 text-xs text-ink-2">
          <span className="flex items-center gap-1.5"><Swatch color="var(--color-series-1)" />Raw events ({totalRaw.toLocaleString()})</span>
          <span className="flex items-center gap-1.5"><Swatch color="var(--color-series-2)" />Incidents created ({totalInc})</span>
        </span>
      </figcaption>
      <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
        {points.length === 0 ? (
          <div className="grid h-[186px] place-items-center text-xs text-muted">Waiting for events…</div>
        ) : (
          <svg width={width} height={H} role="img" overflow="visible"
               aria-label={`${totalRaw} raw events over ${points.length} minutes became ${totalInc} incidents`}>
            <g transform={`translate(0 ${PAD})`}>
            {/* top panel: raw events */}
            {[0, rawMax / 2, rawMax].map((t) => {
              const y = TOP_H - (t / rawMax) * TOP_H;
              return (
                <g key={`r${t}`}>
                  <line x1={GUTTER} x2={width} y1={y + 0.5} y2={y + 0.5} stroke={t === 0 ? "var(--color-axis)" : "var(--color-line)"} />
                  <text x={GUTTER - 6} y={y + 3.5} textAnchor="end" className="fill-muted text-[10px] tabular-nums">{t}</text>
                </g>
              );
            })}
            {points.map((p, i) => {
              const h = (p.raw / rawMax) * TOP_H;
              return p.raw > 0 ? (
                <path key={`rb${i}`} d={topRounded(x(i), TOP_H - h, barW, h, 2)}
                      fill="var(--color-series-1)" opacity={hover === null || hover === i ? 1 : 0.4} />
              ) : null;
            })}
            {points[peak]?.raw > 0 && (
              <text x={Math.min(x(peak) + barW / 2, width - 40)} y={TOP_H - (points[peak].raw / rawMax) * TOP_H - 5}
                    textAnchor="middle" className="fill-ink-2 text-[10px]">peak {points[peak].raw}/min</text>
            )}

            </g>

            {/* bottom panel: incidents created */}
            <g transform={`translate(0 ${PAD + TOP_H + GAP})`}>
              <line x1={GUTTER} x2={width} y1={BOT_H + 0.5} y2={BOT_H + 0.5} stroke="var(--color-axis)" />
              <text x={GUTTER - 6} y={BOT_H + 3.5} textAnchor="end" className="fill-muted text-[10px]">0</text>
              <text x={GUTTER - 6} y={3.5} textAnchor="end" className="fill-muted text-[10px]">{incMax}</text>
              <line x1={GUTTER} x2={width} y1={0.5} y2={0.5} stroke="var(--color-line)" />
              {points.map((p, i) => {
                const h = (p.incidents / incMax) * BOT_H;
                return p.incidents > 0 ? (
                  <path key={`ib${i}`} d={topRounded(x(i), BOT_H - h, barW, h, 2)}
                        fill="var(--color-series-2)" opacity={hover === null || hover === i ? 1 : 0.4} />
                ) : null;
              })}
            </g>

            {/* time axis */}
            {points.map((p, i) => i % tickEvery === 0 ? (
              <text key={`t${i}`} x={GUTTER + i * slot + slot / 2} y={H - 4} textAnchor="middle"
                    className="fill-muted text-[10px] tabular-nums">{p.minute.slice(11)}</text>
            ) : null)}

            {/* hover targets: a full-height column per minute (bigger than the thin bars) */}
            {points.map((_, i) => (
              <rect key={`h${i}`} x={GUTTER + i * slot} y={PAD} width={slot} height={TOP_H + GAP + BOT_H}
                    fill={hover === i ? "rgba(255,255,255,0.04)" : "transparent"} onMouseEnter={() => setHover(i)} />
            ))}
          </svg>
        )}
        {hover !== null && points[hover] && (
          <Tooltip x={Math.min(Math.max(GUTTER + hover * slot + slot / 2, 80), width - 80)} y={8}>
            <div className="font-medium">{points[hover].minute.slice(11)} UTC</div>
            <div className="flex items-center gap-1.5"><Swatch color="var(--color-series-1)" /> {points[hover].raw} raw events</div>
            <div className="flex items-center gap-1.5"><Swatch color="var(--color-series-2)" /> {points[hover].incidents} incident{points[hover].incidents === 1 ? "" : "s"} created</div>
          </Tooltip>
        )}
      </div>
    </figure>
  );
}

export function BandChart({ stats }: { stats: Stats }) {
  const [hover, setHover] = useState<Band | null>(null);
  const max = Math.max(1, ...BANDS.map((b) => stats.by_band[b] ?? 0));
  return (
    <figure className="flex min-w-0 flex-col">
      <figcaption className="mb-3 text-sm font-medium text-ink">Incidents by band</figcaption>
      <div className="space-y-2.5" role="table" aria-label="Incidents by band">
        {BANDS.map((b) => {
          const v = stats.by_band[b] ?? 0;
          return (
            <div key={b} role="row" className="relative grid grid-cols-[72px_1fr] items-center gap-3"
                 onMouseEnter={() => setHover(b)} onMouseLeave={() => setHover(null)}>
              <span role="cell" className="flex items-center gap-1.5 text-xs capitalize text-ink-2">
                <span className={`size-2 rounded-full ${BAND_STYLE[b].bar}`} />{b}
              </span>
              <div role="cell" className="flex h-6 items-center gap-2 border-l border-axis">
                <div className="h-4 rounded-r-[4px] transition-all duration-500"
                     style={{ width: `calc(${(v / max) * 100}% - 28px)`, minWidth: v ? 3 : 0,
                              background: BAND_STYLE[b].fill, opacity: hover === null || hover === b ? 1 : 0.5 }} />
                <span className="text-xs font-semibold tabular-nums text-ink">{v}</span>
              </div>
              {hover === b && (
                <Tooltip x={160} y={0}>
                  <span className="capitalize">{b}</span>: <b>{v}</b> incident{v === 1 ? "" : "s"}
                  {b === "critical" ? " (each one pages on-call)" : ""}
                </Tooltip>
              )}
            </div>
          );
        })}
      </div>
    </figure>
  );
}

/** A column path with rounded top corners and a square base. */
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`;
}
