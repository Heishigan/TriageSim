import { Link } from "react-router-dom";
import { useApi } from "../api";
import { Button, Card, Page, Progress, StateBadge, Table } from "../components/ui";

type Run = { name: string; experiment: string; mode: string; state: string; done: number; total: number; created: string };

export default function Runs() {
  const runs = useApi<Run[]>("/runs", 3000).data ?? [];
  return (
    <Page title="5. Runs & results" subtitle="Every run, live or finished. Open one to watch it or read its results."
      actions={<Link to="/experiments/new"><Button variant="primary">New experiment</Button></Link>}>
      <Card>
        <Table head={["Run", "Experiment", "Mode", "Progress", "State"]}
          rows={runs.map((r) => [
            <Link className="font-medium text-brand-600 hover:underline" to={`/runs/${r.name}`}>{r.name}</Link>,
            r.experiment, r.mode?.replace("_", " "),
            <div className="w-40"><Progress value={r.done} total={r.total} /><span className="text-xs text-slate-500">{r.done}/{r.total}</span></div>,
            <StateBadge state={r.state} />])}
          empty="No runs yet." />
      </Card>
    </Page>
  );
}
