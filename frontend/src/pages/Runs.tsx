import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useApi } from "../api";
import { Button, Card, ConfirmDialog, DeleteLink, Page, Progress, StateBadge, Table } from "../components/ui";

type Models = { nurse: string | null; patient: string | null; evaluator: string | null };
type Run = { name: string; experiment: string; type: string; models: Models; cohort: string | null;
  state: string; done: number; total: number; created: string };

const ACTIVE = ["running", "stopping"];

function ModelList({ models }: { models: Models }) {
  const rows = ([["Nurse", models.nurse], ["Patient", models.patient], ["Evaluator", models.evaluator]] as const)
    .filter(([, m]) => m);
  return (
    <div className="space-y-0.5 text-xs">
      {rows.map(([role, m]) => (
        <div key={role}><span className="inline-block w-16 text-slate-500">{role}</span><code className="text-slate-800">{m}</code></div>))}
    </div>
  );
}

export default function Runs() {
  const runs = useApi<Run[]>("/runs", 3000);
  const [deleting, setDeleting] = useState<Run | null>(null);
  return (
    <Page title="5. Runs & results" subtitle="Every run, live or finished. Open one to watch it or read its results."
      actions={<Link to="/experiments/new"><Button variant="primary">New experiment</Button></Link>}>
      <Card>
        <Table head={["Run", "Type", "Models", "Progress", "State", ""]}
          rows={(runs.data ?? []).map((r) => [
            <Link className="font-medium text-brand-600 hover:underline" to={`/runs/${r.name}`}>{r.name}</Link>,
            r.type,
            <ModelList models={r.models} />,
            <div className="w-40"><Progress value={r.done} total={r.total} /><span className="text-xs text-slate-500">{r.done}/{r.total}</span></div>,
            <StateBadge state={r.state} />,
            <DeleteLink disabled={ACTIVE.includes(r.state)} title={ACTIVE.includes(r.state) ? "Stop the run first" : undefined}
              onClick={() => setDeleting(r)} />])}
          empty="No runs yet." />
      </Card>
      {deleting && (
        <ConfirmDialog title={`Delete run ${deleting.name}?`} confirmLabel="Delete run" onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await api(`/runs/${encodeURIComponent(deleting.name)}`, { method: "DELETE" });
            setDeleting(null);
            runs.reload();
          }}>
          <p>{deleting.type} · {deleting.done} of {deleting.total} cases done.</p>
          <p>This permanently deletes its results, transcripts and evaluator scores from this computer. It cannot be undone.</p>
          <p>The cohort and the models are not affected.</p>
        </ConfirmDialog>)}
    </Page>
  );
}
