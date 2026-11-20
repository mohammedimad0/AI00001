// Small shared helpers: band colors, time formatting, the count-up number, the tooltip.

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Band } from "./api";

export const BANDS: Band[] = ["critical", "high", "medium", "low"];

// Literal class names (Tailwind only generates classes it can see written out in full)
export const BAND_STYLE: Record<Band, { bar: string; chip: string; text: string; fill: string }> = {
  critical: { bar: "bg-critical", chip: "bg-critical text-white", text: "text-critical", fill: "var(--color-critical)" },
  high: { bar: "bg-high", chip: "bg-high text-white", text: "text-high", fill: "var(--color-high)" },
  medium: { bar: "bg-medium", chip: "bg-medium text-black", text: "text-medium", fill: "var(--color-medium)" },
  low: { bar: "bg-low", chip: "bg-low text-white", text: "text-muted", fill: "var(--color-low)" },
};

export function timeAgo(iso: string, now = Date.now()): string {
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** "10:54 UTC · 3m ago", or just "10:54 UTC" when the time is ahead of this machine's clock (demo data). */
export function when(iso: string, now = Date.now()): string {
  return new Date(iso).getTime() > now ? clock(iso) : `${clock(iso)} · ${timeAgo(iso, now)}`;
}

export function clock(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16) + " UTC";
}

/** A number that glides from its old value to the new one instead of jumping. */
export function CountUp({ value, duration = 600, format = (n: number) => n.toLocaleString() }:
  { value: number; duration?: number; format?: (n: number) => string }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = performance.now();
    const begin = from.current;
    let frame = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / duration);
      const eased = 1 - (1 - p) ** 3;
      const v = begin + (value - begin) * eased;
      setShown(v);
      from.current = v;
      if (p < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <>{format(Math.round(shown))}</>;
}

/** Re-render every `ms` so "time ago" labels stay fresh. */
export function useNow(ms = 10_000): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

/** Floating tooltip box used by the charts. Position is in px relative to the chart wrapper. */
export function Tooltip({ x, y, children }: { x: number | string; y: number; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-line bg-raised px-2.5 py-1.5 text-xs text-ink shadow-lg"
      style={{ left: x, top: y - 8 }}
    >
      {children}
    </div>
  );
}

export function Swatch({ color, line = false }: { color: string; line?: boolean }) {
  return line
    ? <span className="inline-block h-0.5 w-3 rounded-full align-middle" style={{ background: color }} />
    : <span className="inline-block size-2.5 rounded-sm align-middle" style={{ background: color }} />;
}

/** Measure an element's width in px (charts draw in real pixels so bars keep their size). */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}
