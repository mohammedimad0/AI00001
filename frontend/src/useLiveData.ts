// The dashboard's "radio receiver".
// 1. On start it asks the backend for everything once (stats, incidents, timeline).
// 2. Then it keeps ONE open line to GET /stream. The backend pushes small messages
//    ("new_incident", "incident_updated", "stats", "reset") and we merge each one into
//    our state, so React redraws only what changed. No page refresh, no polling for incidents.
// 3. If the backend goes away, we say so (connection = "down") and keep retrying.

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, api, type Health, type Incident, type Stats, type TimelinePoint } from "./api";

export type Connection = "connecting" | "live" | "down";

const EMPTY_STATS: Stats = {
  raw_events: 0, incidents: 0, pages: 0, noise_reduction_pct: 0,
  by_band: { critical: 0, high: 0, medium: 0, low: 0 },
  by_status: { open: 0, acknowledged: 0, resolved: 0 },
  fixes: {},
};

export function useLiveData() {
  const [stats, setStats] = useState<Stats>(EMPTY_STATS);
  const [incidents, setIncidents] = useState<Record<string, Incident>>({});
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [resets, setResets] = useState(0);          // counts /demo/reset broadcasts (from any screen)
  const timelineTimer = useRef<number | null>(null);

  const upsert = useCallback((inc: Incident) => {
    setIncidents((prev) => ({ ...prev, [inc.id]: inc }));
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [s, list, t] = await Promise.all([api.stats(), api.incidents(), api.timeline()]);
      setStats(s);
      setIncidents(Object.fromEntries(list.map((i) => [i.id, i])));
      setTimeline(t);
      return true;
    } catch {
      setConnection("down");
      return false;
    }
  }, []);

  // The timeline chart is recomputed by the backend; refetch at most once a second while events stream in.
  const refreshTimelineSoon = useCallback(() => {
    if (timelineTimer.current !== null) return;
    timelineTimer.current = window.setTimeout(async () => {
      timelineTimer.current = null;
      try { setTimeline(await api.timeline()); } catch { /* the banner already covers this */ }
    }, 1000);
  }, []);

  const loadHealth = useCallback(async () => {
    try { setHealth(await api.health()); } catch { setHealth(null); }
  }, []);

  // Live updates over Server-Sent Events
  useEffect(() => {
    const es = new EventSource(`${API_URL}/stream`);
    const parse = (e: MessageEvent) => JSON.parse(e.data);

    es.onopen = () => { setConnection("live"); loadAll(); loadHealth(); };   // (re)connected: resync
    es.onerror = () => setConnection("down");                               // EventSource retries by itself
    es.addEventListener("new_incident", (e) => upsert(parse(e as MessageEvent)));
    es.addEventListener("incident_updated", (e) => upsert(parse(e as MessageEvent)));
    es.addEventListener("stats", (e) => { setStats(parse(e as MessageEvent)); refreshTimelineSoon(); });
    es.addEventListener("reset", () => { setIncidents({}); setTimeline([]); setResets((n) => n + 1); });

    return () => es.close();
  }, [loadAll, loadHealth, upsert, refreshTimelineSoon]);

  // Health dots: Ollama / ChromaDB can go up or down without any incident changing, so poll them.
  useEffect(() => {
    loadHealth();
    const id = window.setInterval(loadHealth, 5000);
    return () => window.clearInterval(id);
  }, [loadHealth]);

  return { stats, incidents, timeline, health, connection, resets, upsert, reload: loadAll, loadHealth };
}
