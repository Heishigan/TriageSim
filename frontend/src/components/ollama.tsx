import { useState } from "react";
import { post } from "../api";
import { Spinner } from "./ui";

export type OllamaStatus = {
  reachable: boolean; installed: boolean; installing: boolean; version?: string;
  platform: string; install_command: string | null;
};

/** Install (Windows, one click) or start Ollama; shows the command on other systems. */
export function OllamaAction({ status, onChange, compact = false }:
  { status: OllamaStatus; onChange: () => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (status.reachable) return null;
  const run = async (path: string) => {
    setBusy(true); setError(null);
    try { await post(path); } catch (e) { setError((e as Error).message); }
    setBusy(false); onChange();
  };
  const button = compact
    ? "mt-2 w-full rounded-md bg-brand-600 px-2 py-1.5 text-xs font-semibold text-white hover:bg-brand-700 disabled:bg-slate-600"
    : "rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:bg-slate-300";
  let action;
  if (status.installing) {
    action = <span className={`flex items-center gap-2 ${compact ? "mt-2 text-xs text-slate-300" : "text-sm"}`}><Spinner /> Installing Ollama… follow its window</span>;
  } else if (status.installed) {
    action = <button className={button} disabled={busy} onClick={() => run("/ollama/start")}>{busy ? "Starting…" : "Start Ollama"}</button>;
  } else if (status.platform === "windows") {
    action = <button className={button} disabled={busy} onClick={() => run("/ollama/install")}>{busy ? "Starting install…" : "Install Ollama"}</button>;
  } else {
    action = (
      <div className={compact ? "mt-2 text-xs text-slate-300" : "text-sm"}>
        Install it with: <code className={`block whitespace-pre-wrap break-all rounded p-2 ${compact ? "mt-1 bg-slate-800" : "mt-1 bg-slate-100"}`}>{status.install_command ?? "see ollama.com/download"}</code>
      </div>);
  }
  return <div>{action}{error && <p className={`mt-1 ${compact ? "text-xs text-rose-300" : "text-sm text-rose-600"}`}>{error}</p>}</div>;
}
