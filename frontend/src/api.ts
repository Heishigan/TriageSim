// Small typed helpers for the local TriageSim API.
import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) {
    let message = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* not JSON */
    }
    throw new ApiError(message);
  }
  return r.json() as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });

/** Load data, optionally re-loading every `pollMs`. */
export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError((e as Error).message);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    reload();
    if (!pollMs) return () => void (alive.current = false);
    const id = setInterval(reload, pollMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [reload, pollMs]);

  return { data, error, loading, reload, setData };
}

// ---- types (mirror the Python API) ----------------------------------------------------
export type Wilson = { n: number; k: number; pct: number | null; low: number | null; high: number | null };
export type FlowStep = { step: string; ed_stays: number; patients: number };
export type Job = {
  id: string; kind: string; label: string; state: string; seconds: number; error: string | null;
  progress: { status?: string; completed?: number; total?: number; notes_read?: number };
  result: Record<string, unknown> | null;
};
export type CohortSettings = {
  name: string; min_age: number | null; max_age: number | null; sexes: string[]; admission: string;
  icd10_codes: string[]; icd9_codes: string[]; require_acuity: boolean; esi_levels: number[];
  one_visit_per_patient: boolean;
};
export type RunStatus = {
  state: string; done: number; total: number; current_case?: string | null; error?: string | null;
  created?: string; updated?: string; started?: string; finished?: string;
  external?: boolean; host?: string; slurm_job?: string | null;
};
export type RunEvent = {
  type: string; case_id?: string; speaker?: string; text?: string; turn?: number; decision?: number;
  kind?: string; esi?: number; reference_esi?: number; persona?: string;
  esi_final?: number; // runs saved before self-review was removed
  questions?: number; error?: string; time?: number; retrieved?: string[];
};
export type Metrics = {
  cases: number; decided: number; undecided: number; forced_decisions: number; format_failures: number;
  agreement: Wilson; within_one_level: Wilson; under_triage: Wilson; over_triage: Wilson;
  weighted_kappa: number | null; confusion: Record<string, Record<string, number>>;
  head_injury: null | { cases: number; under_triage_vs_nurse: Wilson; esi_3_or_lower_urgency: Wilson };
  questions: null | { mean: number; median: number; min: number; max: number };
  evaluator_scores: Record<string, null | { mean: number; sd: number; n: number }>;
  by_persona: Record<string, { cases: number; agreement: Wilson; under_triage: Wilson }>;
  seconds_per_case: number | null;
};
