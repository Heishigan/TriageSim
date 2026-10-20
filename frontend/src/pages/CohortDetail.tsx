import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { type FlowStep, type Job, api, post, useApi } from "../api";
import { Alert, Badge, Button, Card, Field, Page, Progress, Spinner, Table, inputClass } from "../components/ui";

type Detail = {
  name: string; filters: string[];
  report: { flow: FlowStep[]; esi_distribution: Record<string, number>; sex_distribution: Record<string, number> };
  cases_report: null | { cases: number; flow: { step: string; cases: number }[]; hpi_redacted: number;
    ed_course_cut: number; removed_sentences_by_rule: Record<string, number>; with_medications: number;
    with_vitals: number; head_injury_icd_positive: number | null };
  case_job: Job | null;
};
type Case = {
  case_id: string; stay_id: number;
  nurse_view: Record<string, unknown> & { vitals: Record<string, unknown> };
  patient_view: Record<string, unknown> & { medications: string[] };
  reference: Record<string, unknown>;
  audit: { hpi_redacted: boolean; ed_course_cut: boolean; removed_sentences: Record<string, number> };
};

export default function CohortDetail() {
  const { name = "" } = useParams();
  const [tab, setTab] = useState<"overview" | "cases" | "review">("overview");
  const detail = useApi<Detail>(`/cohorts/${name}`);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = job?.state === "running" || detail.data?.case_job?.state === "running";

  const buildCases = async () => {
    setError(null);
    try {
      let j = await post<Job>(`/cohorts/${name}/cases`);
      setJob(j);
      while (j.state === "running") {
        await new Promise((r) => setTimeout(r, 1000));
        j = await api<Job>(`/jobs/${j.id}`);
        setJob(j);
      }
      if (j.state === "failed") setError(j.error);
      detail.reload();
    } catch (e) { setError((e as Error).message); }
  };

  const d = detail.data;
  return (
    <Page title={name} subtitle={<Link to="/cohorts" className="text-brand-600 hover:underline">← All cohorts</Link>}
      actions={d && <Button variant="primary" disabled={running} onClick={buildCases}>
        {running ? <span className="flex items-center gap-2"><Spinner /> Building cases…</span> : d.cases_report ? "Rebuild case files" : "Build case files"}</Button>}>
      {detail.error && <Alert kind="error">{detail.error}</Alert>}
      {error && <Alert kind="error">{error}</Alert>}
      {job?.state === "running" && (
        <Card>
          <p className="mb-2 text-sm">{job.progress.status}{job.progress.notes_read ? ` · ${job.progress.notes_read.toLocaleString()} notes read` : ""}</p>
          <Progress value={job.progress.notes_read ?? 0} total={331_793} label="Reading discharge notes (MIMIC-IV-Note has about 330,000)" />
        </Card>
      )}
      {d && (
        <>
          <div className="flex gap-1 border-b border-slate-200">
            {(["overview", "cases", "review"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
                tab === t ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                {{ overview: "Overview", cases: "Case files", review: "Case review" }[t]}</button>))}
          </div>
          {tab === "overview" && <Overview d={d} />}
          {tab === "cases" && (d.cases_report ? <CasePreview name={name} /> : <Alert>Build the case files first (button at the top right).</Alert>)}
          {tab === "review" && <Review name={name} />}
        </>
      )}
    </Page>
  );
}

function Overview({ d }: { d: Detail }) {
  const cr = d.cases_report;
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Filters applied">
        <ol className="list-decimal space-y-1 pl-5 text-sm">{d.filters.map((f) => <li key={f}>{f}</li>)}</ol>
      </Card>
      <Card title="Cohort flow">
        <Table head={["Step", "ED stays", "Patients"]}
          rows={d.report.flow.map((s) => [s.step, s.ed_stays.toLocaleString(), s.patients.toLocaleString()])} />
      </Card>
      <Card title="ESI and sex">
        <div className="flex gap-10 text-sm">
          <Table head={["ESI", "Stays"]} rows={Object.entries(d.report.esi_distribution).map(([k, v]) => [k, v.toLocaleString()])} />
          <Table head={["Sex", "Stays"]} rows={Object.entries(d.report.sex_distribution).map(([k, v]) => [k, v.toLocaleString()])} />
        </div>
      </Card>
      <Card title="Case files">
        {!cr ? <p className="text-sm text-slate-500">Not built yet. Case files add the history the patient agent knows (from the discharge note, redacted), home medications, vitals and labels.</p> : (
          <div className="space-y-3 text-sm">
            <Table head={["Step", "Cases"]} rows={cr.flow.map((s) => [s.step, s.cases.toLocaleString()])} />
            <ul className="space-y-1 text-slate-600">
              <li>HPIs changed by redaction: <b>{cr.hpi_redacted.toLocaleString()}</b> (ED course cut in {cr.ed_course_cut.toLocaleString()})</li>
              <li>Sentences removed: {Object.entries(cr.removed_sentences_by_rule).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(" · ") || "none"}</li>
              <li>With home medications: {cr.with_medications.toLocaleString()} · with vitals: {cr.with_vitals.toLocaleString()}</li>
              <li>Head injury (ICD) positive: {cr.head_injury_icd_positive === null ? "no label file" : cr.head_injury_icd_positive.toLocaleString()}</li>
            </ul>
          </div>)}
      </Card>
    </div>
  );
}

export function View({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <dl className="space-y-1.5 text-sm">
        {Object.entries(data).map(([k, v]) => (
          <div key={k}><dt className="text-xs text-slate-500">{k.replace(/_/g, " ")}</dt>
            <dd className="whitespace-pre-wrap text-slate-800">{typeof v === "object" && v !== null
              ? Array.isArray(v) ? v.join(", ") || "–" : Object.entries(v).map(([a, b]) => `${a}: ${b ?? "–"}`).join(" · ")
              : String(v ?? "–") || "–"}</dd></div>))}
      </dl>
    </div>
  );
}

function CasePreview({ name }: { name: string }) {
  const [offset, setOffset] = useState(0);
  const { data } = useApi<{ total: number; cases: Case[] }>(`/cohorts/${name}/cases?limit=1&offset=${offset}`);
  const c = data?.cases[0];
  return (
    <Card title={`Case files (${data?.total.toLocaleString() ?? "…"})`} actions={<>
      <Button disabled={offset === 0} onClick={() => setOffset(offset - 1)}>Previous</Button>
      <Button disabled={!data || offset + 1 >= data.total} onClick={() => setOffset(offset + 1)}>Next</Button></>}>
      <Alert kind="warning">Patient-level data. Review it on this computer only; do not copy or share it.</Alert>
      {c && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center gap-2 text-sm"><b>{c.case_id}</b> · stay {c.stay_id}
            {c.audit.hpi_redacted && <Badge color="amber">HPI redacted: {Object.entries(c.audit.removed_sentences).map(([k, v]) => `${k} ${v}`).join(", ") || ""}{c.audit.ed_course_cut ? " · ED course cut" : ""}</Badge>}</div>
          <div className="grid gap-3 lg:grid-cols-3">
            <View title="Nurse sees at arrival" data={c.nurse_view} />
            <View title="Patient agent knows" data={c.patient_view} />
            <View title="Reference (evaluation only)" data={c.reference} />
          </div>
        </div>)}
    </Card>
  );
}

type ReviewCase = { stay_id: number; facts: Record<string, string>; diagnoses: Record<string, unknown>[];
  visits: Record<string, unknown>[]; verdict: { verdict: string; note: string } | null };

function Review({ name }: { name: string }) {
  const [group, setGroup] = useState("included");
  const [n, setN] = useState(5);
  const [seed, setSeed] = useState(1);
  const { data, error, loading, reload } = useApi<{ reproduced: boolean; groups: string[]; pool: number; cases: ReviewCase[] }>(
    `/cohorts/${name}/review?group=${encodeURIComponent(group)}&n=${n}&seed=${seed}`);
  const save = async (stay_id: number, verdict: string) => {
    await post(`/cohorts/${name}/review`, { stay_id, group, verdict, note: "" });
    reload();
  };
  return (
    <div className="space-y-4">
      <Alert kind="warning">Patient-level data. Review it on this computer only; do not copy or share it.</Alert>
      <Card>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Review"><select className={inputClass} value={group} onChange={(e) => setGroup(e.target.value)}>
            {(data?.groups ?? ["included"]).map((g) => <option key={g} value={g}>{g === "included" ? "Included cases" : `Excluded at: ${g}`}</option>)}</select></Field>
          <Field label="How many"><input type="number" min={1} max={50} className={inputClass} value={n} onChange={(e) => setN(Number(e.target.value))} /></Field>
          <Field label="Sample number" hint="The same number always gives the same cases."><input type="number" min={1} className={inputClass} value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></Field>
        </div>
        {data && <p className="mt-3 text-sm text-slate-600">{data.pool.toLocaleString()} cases in this group.{" "}
          {data.reproduced ? <Badge color="green">Rebuilt from saved settings: identical</Badge> : <Badge color="red">Rebuild differs from saved cohort</Badge>}</p>}
      </Card>
      {loading && <Spinner />}
      {error && <Alert kind="error">{error}</Alert>}
      {data?.cases.map((c) => (
        <Card key={c.stay_id} title={`Stay ${c.stay_id} · ${c.facts.Status}`} actions={["Correct", "Incorrect", "Unsure"].map((v) => (
          <Button key={v} variant={c.verdict?.verdict === v ? "primary" : "secondary"} onClick={() => save(c.stay_id, v)}>{v}</Button>))}>
          <div className="grid gap-4 lg:grid-cols-3">
            <dl className="space-y-1 text-sm">{Object.entries(c.facts).map(([k, v]) => (
              <div key={k} className="flex gap-2"><dt className="w-32 shrink-0 text-slate-500">{k}</dt><dd>{v}</dd></div>))}</dl>
            <div className="lg:col-span-2 space-y-3">
              <Table head={["#", "Code", "Ver.", "Title", "Match"]} rows={c.diagnoses.map((d) => [
                String(d.seq_num), String(d.icd_code), String(d.icd_version), String(d.icd_title), d.matches_filter ? "✓" : ""])} />
              <Table head={["Visit", "Arrival", "Disposition", "Status"]} rows={c.visits.map((v) => [
                <span className={v["this case"] ? "font-semibold" : ""}>{String(v.stay_id)}</span>,
                String(v.intime).replace("T", " ").slice(0, 16), String(v.disposition), String(v.status)])} />
            </div>
          </div>
        </Card>))}
    </div>
  );
}
