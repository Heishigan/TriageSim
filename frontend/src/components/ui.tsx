import { type ReactNode, useEffect, useRef, useState } from "react";
import type { Wilson } from "../api";

export function Page({ title, subtitle, actions, children }:
  { title: string; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
      </div>
      <div className="space-y-6">{children}</div>
    </div>
  );
}

export function Card({ title, actions, children, className = "" }:
  { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          <div className="flex gap-2">{actions}</div>
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost";
  ref?: React.Ref<HTMLButtonElement> };
export function Button({ variant = "secondary", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-slate-300",
    secondary: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-slate-300",
    ghost: "text-brand-600 hover:bg-brand-50 disabled:text-slate-400",
  }[variant];
  return <button className={`rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${styles} ${className}`} {...props} />;
}

const BADGE: Record<string, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  blue: "bg-brand-50 text-brand-700 ring-brand-100",
  gray: "bg-slate-100 text-slate-600 ring-slate-200",
};
export function Badge({ color = "gray", children }: { color?: keyof typeof BADGE; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${BADGE[color]}`}>{children}</span>;
}

export function StateBadge({ state }: { state?: string }) {
  const color = ({ completed: "green", done: "green", running: "blue", created: "gray", stopped: "amber",
    interrupted: "amber", stopping: "amber", failed: "red" } as const)[state ?? ""] ?? "gray";
  return <Badge color={color}>{state ?? "unknown"}</Badge>;
}

export function Progress({ value, total, label }: { value: number; total: number; label?: ReactNode }) {
  const pct = total > 0 ? Math.min(100, (100 * value) / total) : 0;
  return (
    <div>
      {label && <div className="mb-1 flex justify-between text-xs text-slate-500"><span>{label}</span><span>{pct.toFixed(0)}%</span></div>}
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-brand-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "error" | "success" | "warning"; children: ReactNode }) {
  const style = { info: "border-brand-100 bg-brand-50 text-brand-700", error: "border-rose-200 bg-rose-50 text-rose-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700", warning: "border-amber-200 bg-amber-50 text-amber-800" }[kind];
  return <div className={`rounded-lg border px-4 py-3 text-sm ${style}`}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:ring-2 focus:ring-brand-100 focus:outline-none disabled:bg-slate-50";

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone === "bad" ? "text-rose-600" : tone === "good" ? "text-emerald-600" : "text-slate-900"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function pct(w: Wilson | null | undefined) {
  return w && w.pct !== null ? `${w.pct}%` : "–";
}
export function ci(w: Wilson | null | undefined) {
  return w && w.pct !== null ? `95% CI ${w.low}–${w.high} · ${w.k}/${w.n}` : "no cases";
}

export function Table({ head, rows, empty = "Nothing yet." }: { head: ReactNode[]; rows: ReactNode[][]; empty?: string }) {
  if (!rows.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead><tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
          {head.map((h, i) => <th key={i} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-slate-100 last:border-0">
          {r.map((c, j) => <td key={j} className="px-3 py-2 align-top">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />;
}

/** A confirmation dialog for destructive actions. `onConfirm` may throw; its message is shown
 * in the dialog and the dialog stays open. Escape or Cancel closes it; Cancel has the focus. */
export function ConfirmDialog({ title, children, confirmLabel = "Delete", busyLabel = "Deleting…", variant = "danger", onConfirm, onClose }:
  { title: string; children: ReactNode; confirmLabel?: string; busyLabel?: string; variant?: "danger" | "primary";
    onConfirm: () => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  close.current = busy ? () => {} : onClose;          // never close while deleting
  useEffect(() => { cancel.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const confirm = async () => {
    setBusy(true); setError(null);
    try { await onConfirm(); } catch (e) { setError((e as Error).message); setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) close.current(); }}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <h2 id="confirm-title" className="text-base font-semibold text-slate-900">{title}</h2>
        <div className="mt-3 space-y-2 text-sm text-slate-600">{children}</div>
        {error && <div className="mt-4"><Alert kind="error">{error}</Alert></div>}
        <div className="mt-6 flex justify-end gap-2">
          <Button ref={cancel} disabled={busy} onClick={onClose}>Cancel</Button>
          <Button variant={variant} disabled={busy} onClick={confirm}>{busy ? busyLabel : confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

/** A small red text button for table rows. */
export function DeleteLink({ disabled, title, onClick }: { disabled?: boolean; title?: string; onClick: () => void }) {
  return <button className="text-sm font-medium text-rose-600 hover:underline disabled:cursor-not-allowed disabled:text-slate-400 disabled:no-underline"
    disabled={disabled} title={title} onClick={onClick}>Delete</button>;
}
