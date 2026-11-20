// Everything the dashboard knows about the backend lives in this file:
// the shapes of the data (types) and one small function per endpoint.

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Band = "critical" | "high" | "medium" | "low";
export type Status = "open" | "acknowledged" | "resolved";

export interface Factor {
  factor: string;
  points: number;
  reason: string;
}

export interface Resolution {
  source: "rag" | "llm" | "llm_pending" | "llm_unavailable" | "none";
  // known fix (rag)
  runbook_id?: string;
  runbook_title?: string;
  similarity?: number;
  // AI-generated (llm)
  model?: string;
  confidence?: number;
  severity_comment?: string;
  llm_seconds?: number;
  // shared
  root_cause?: string;
  impact?: string;
  fix_steps?: string[];
  prevention?: string;
  reason?: string;
  best_similarity?: number;
  best_runbook_id?: string | null;
  approved?: boolean;
  cached?: boolean;           // saved sample answer, shown when the live LLM is unavailable
  approved_runbook_id?: string;
  rejected?: boolean;
}

export interface Incident {
  id: string;
  title: string;
  error_type: string;
  service: string;
  country: string | null;
  score: number;
  band: Band;
  action: string;
  factors: Factor[];
  status: Status;
  event_count: number;
  unique_messages: number;
  fingerprints: Record<string, { template: string; count: number }>;
  hosts: string[];
  sources: string[];
  first_seen: string;
  last_seen: string;
  resolution: Resolution;
  created_at: string;
  updated_at: string;
}

export interface SampleEvent {
  timestamp: string;
  source: string;
  host: string;
  level: string;
  message: string;
}

export interface IncidentDetail extends Incident {
  sample_events: SampleEvent[];
  timeline: { minute: string; count: number }[];
  feedback: { action: string; comment: string; runbook_id: string | null; created_at: string }[];
}

export interface Stats {
  raw_events: number;
  incidents: number;
  pages: number;
  noise_reduction_pct: number;
  by_band: Record<Band, number>;
  by_status: Record<Status, number>;
  fixes: Record<string, number>;
}

export interface Health {
  status: "ok" | "degraded";
  ollama: { ok: boolean; reachable: boolean; model: string; model_pulled: boolean;
            warmup?: { state: string; seconds: number | null; error: string | null } };
  chromadb: { ok: boolean; runbooks?: number; error?: string };
  llm_jobs_pending: number;
  replay_running: boolean;
  data_source: "fake" | "live" | "both";
  loki: { enabled: boolean; reachable: boolean; last_poll: number | null; last_error: string | null; lines_ingested: number };
}

export interface TimelinePoint {
  minute: string;
  raw: number;
  incidents: number;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  stats: () => call<Stats>("/stats"),
  health: () => call<Health>("/health"),
  timeline: () => call<TimelinePoint[]>("/timeline"),
  incidents: () => call<Incident[]>("/incidents"),
  incident: (id: string) => call<IncidentDetail>(`/incidents/${id}`),
  approve: (id: string) => post<{ message: string; runbook_id: string; incident: Incident }>(`/incidents/${id}/approve`, {}),
  reject: (id: string, comment = "") => post<{ message: string; incident: Incident }>(`/incidents/${id}/reject`, { comment }),
  ack: (id: string) => post<Incident>(`/incidents/${id}/ack`, {}),
  reset: () => post<unknown>("/demo/reset"),
  replay: () => post<{ started: boolean; seconds: number }>("/demo/replay"),
  injectTls: () => post<{ new_incidents: string[]; llm_queued: string[] }>("/demo/inject/tls"),
};
