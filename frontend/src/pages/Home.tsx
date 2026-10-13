import { Link } from "react-router-dom";
import { useApi } from "../api";
import { Badge, Card, Page, StateBadge, Table } from "../components/ui";

type DataCheck = { groups: { purpose: string; label: string; ready: boolean }[] };
type Cohort = { name: string; patients: number | null; cases: number | null };
type Run = { name: string; experiment: string; state: string; done: number; total: number };

export default function Home() {
  const data = useApi<DataCheck>("/data").data;
  const cohorts = useApi<Cohort[]>("/cohorts").data ?? [];
  const models = useApi<{ reachable: boolean; models: { name: string }[] }>("/models").data;
  const runs = useApi<Run[]>("/runs", 5000).data ?? [];
  const steps = [
    { to: "/data", title: "Place the MIMIC files", done: data?.groups.slice(0, 2).every((g) => g.ready),
      detail: data ? data.groups.map((g) => `${g.label}: ${g.ready ? "ready" : "missing files"}`).join(" · ") : "…" },
    { to: "/cohorts", title: "Build a cohort and its cases", done: cohorts.some((c) => c.cases),
      detail: `${cohorts.length} cohort(s), ${cohorts.filter((c) => c.cases).length} with case files` },
    { to: "/models", title: "Get the models", done: (models?.models.length ?? 0) > 0,
      detail: models?.reachable ? `${models.models.length} model(s) installed in Ollama` : "Ollama is not running" },
    { to: "/experiments/new", title: "Configure an experiment", done: runs.length > 0, detail: "Agents, models, prompts, cases" },
    { to: "/runs", title: "Watch it run and read the results", done: runs.some((r) => r.state === "completed"),
      detail: `${runs.length} run(s)` },
  ];
  return (
    <Page title="TriageSim" subtitle="Evaluate how language models triage emergency department patients, on MIMIC-IV. Everything runs on this computer.">
      <Card title="Getting started">
        <ol className="space-y-3">
          {steps.map((s, i) => (
            <li key={s.to}>
              <Link to={s.to} className="flex items-center gap-4 rounded-lg p-2 hover:bg-slate-50">
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                  s.done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{s.done ? "✓" : i + 1}</span>
                <span className="flex-1">
                  <span className="block text-sm font-medium text-slate-900">{s.title}</span>
                  <span className="block text-xs text-slate-500">{s.detail}</span>
                </span>
                <span className="text-slate-400">→</span>
              </Link>
            </li>
          ))}
        </ol>
      </Card>
      <Card title="Recent runs">
        <Table head={["Run", "Experiment", "Progress", "State"]}
          rows={runs.slice(0, 5).map((r) => [
            <Link className="text-brand-600 hover:underline" to={`/runs/${r.name}`}>{r.name}</Link>,
            r.experiment, `${r.done}/${r.total}`, <StateBadge state={r.state} />])}
          empty="No runs yet." />
      </Card>
      <p className="text-xs text-slate-400"><Badge>Privacy</Badge> MIMIC data stays in the data folder on this computer. The app listens on this computer only.</p>
    </Page>
  );
}
