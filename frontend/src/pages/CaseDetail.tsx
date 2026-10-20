import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, useApi } from "../api";
import { Alert, Badge, Button, Card, Page, Spinner, Table, inputClass } from "../components/ui";
import { View } from "./CohortDetail";
import { Conversation, EsiPair, type Message } from "./RunDetail";

type Row = Record<string, unknown>;
type GroundTruth = {
  case: { case_id: string; stay_id: number; hadm_id: number | null; nurse_view: Row; patient_view: Row; reference: Row;
    audit: { hpi_redacted: boolean; ed_course_cut: boolean; removed_sentences: Record<string, number> } };
  mimic: { ed_stay: Row[]; triage: Row[]; ed_diagnoses: Row[] };
};
type RunCase = { run: string; experiment: string; type: string; mode: string; persona: string | null;
  reference_esi: number; esi: number | null; forced: boolean; questions: number; format_failures: number;
  scores: Record<string, number> | null; transcript: Message[]; feedback: string | null };
type Note = { found: boolean; reason?: string; hpi_original?: string; hpi_given_to_patient?: string; sections?: Record<string, string> };

function Text({ title, text }: { title: string; text?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      <p className="whitespace-pre-wrap text-sm text-slate-800">{text || "–"}</p>
    </div>
  );
}

/** Rows of a MIMIC table as small key-value blocks (fits a narrow column). */
function Records({ title, rows, keys }: { title: string; rows: Row[]; keys?: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      {!rows.length ? <p className="text-sm text-slate-500">None.</p> : rows.map((r, i) => (
        <dl key={i} className="mb-2 grid grid-cols-[auto_1fr] gap-x-3 text-sm last:mb-0">
          {(keys ?? Object.keys(r)).filter((k) => k in r).map((k) => <Fragment key={k}><dt className="text-xs text-slate-500">{k}</dt>
            <dd className="text-slate-800">{String(r[k] ?? "–")}</dd></Fragment>)}
        </dl>))}
    </div>
  );
}

function GroundTruthPanel({ name, caseId, data }: { name: string; caseId: string; data: GroundTruth }) {
  const [note, setNote] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const c = data.case;
  const load = async () => {
    setBusy(true); setErr(null);
    try { setNote(await api<Note>(`/cohorts/${name}/cases/${caseId}/note`)); } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
        stay {c.stay_id} · admission {c.hadm_id ?? "none"}
        {c.audit.hpi_redacted && <Badge color="amber">HPI redacted: {Object.entries(c.audit.removed_sentences).map(([k, v]) => `${k} ${v}`).join(", ")}{c.audit.ed_course_cut ? " · ED course cut" : ""}</Badge>}
      </div>
      <View title="Reference (evaluation only)" data={c.reference} />
      <View title="Nurse sees at arrival" data={c.nurse_view} />
      <View title="Patient agent knows" data={c.patient_view} />
      <Records title="MIMIC-IV triage (nurse's ESI = acuity)" rows={data.mimic.triage} />
      <Records title="MIMIC-IV ED stay" rows={data.mimic.ed_stay} />
      <Records title="MIMIC-IV ED diagnoses" rows={data.mimic.ed_diagnoses} keys={["seq_num", "icd_code", "icd_version", "icd_title"]} />
      <div className="rounded-lg border border-slate-200 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Original discharge note</span>
          <Button onClick={load} disabled={busy}>{busy ? <Spinner /> : note ? "Reload" : "Load"}</Button>
        </div>
        {err && <Alert kind="error">{err}</Alert>}
        {!note && !err && <p className="text-sm text-slate-500">The HPI before redaction and the other sections. The first load reads the note file (a minute or two).</p>}
        {note && !note.found && <Alert>{note.reason}</Alert>}
        {note?.found && <div className="space-y-3">
          <Text title="HPI in the original note" text={note.hpi_original} />
          <Text title="HPI given to the patient agent" text={note.hpi_given_to_patient} />
          {Object.entries(note.sections ?? {}).map(([k, v]) => <Text key={k} title={k.replace(/_/g, " ")} text={v} />)}
        </div>}
      </div>
    </div>
  );
}

function baseLabel(r: RunCase) {
  return r.persona && r.mode === "interview" ? `${r.type} (${r.persona})` : r.type;
}

/** The pipeline name; with the experiment name added when two runs would look the same
 *  (e.g. chart review and the arrival-only ablation, which is also a chart review). */
function label(r: RunCase, all: RunCase[]) {
  const base = baseLabel(r);
  return all.filter((o) => baseLabel(o) === base).length > 1 ? `${base} · ${r.experiment}` : base;
}

/** One case across every run of its cohort, next to the ground truth: for manual review. */
export default function CaseDetail() {
  const { name = "", caseId = "" } = useParams();
  const navigate = useNavigate();
  const truth = useApi<GroundTruth>(`/cohorts/${name}/cases/${caseId}`);
  const runs = useApi<RunCase[]>(`/cohorts/${name}/cases/${caseId}/runs`);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [goto, setGoto] = useState("");
  const shown = (runs.data ?? []).filter((r) => !hidden.has(r.run));
  const toggle = (run: string) => setHidden((h) => { const n = new Set(h); if (n.has(run)) n.delete(run); else n.add(run); return n; });
  const go = () => {
    const v = goto.trim();
    if (!v) return;
    navigate(`/cohorts/${name}/cases/${/^\d+$/.test(v) ? `case-${v.padStart(5, "0")}` : v}`);
    setGoto("");
  };
  return (
    <Page title={`Case review · ${caseId}`}
      subtitle={<Link className="text-brand-600 hover:underline" to="/runs">← Runs</Link>}
      actions={<form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); go(); }}>
        <input className={`${inputClass} !w-60`} placeholder="Another case, e.g. 01276" value={goto} onChange={(e) => setGoto(e.target.value)} />
        <Button type="submit">Open</Button></form>}>
      <div className="space-y-6">
        <Alert kind="warning">Patient-level data from MIMIC-IV. Review it on this computer only; do not copy or share it.</Alert>
        <Card title="Decisions in every run">
          {runs.error && <Alert kind="error">{runs.error}</Alert>}
          {!runs.data && !runs.error && <Spinner />}
          {runs.data && <Table head={["Show", "Pipeline", "Agent / nurse ESI", "Questions", "Scores (history / risk / decision)", "Run"]}
            rows={runs.data.map((r) => [
              <input type="checkbox" checked={!hidden.has(r.run)} onChange={() => toggle(r.run)} aria-label={`Show ${r.run}`} />,
              <span className="font-medium">{label(r, runs.data ?? [])}</span>,
              <span><EsiPair got={r.esi} reference={r.reference_esi} />{r.forced && <Badge color="amber">forced</Badge>}</span>,
              r.mode === "interview" ? r.questions : "–",
              r.scores ? Object.values(r.scores).join(" / ") : "–",
              <Link className="font-mono text-xs text-brand-600 hover:underline" to={`/runs/${r.run}`}>{r.run}</Link>])}
            empty="No run of this cohort has a result for this case." />}
        </Card>
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(320px,2fr)_5fr]">
          <Card title="Ground truth" className="xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto">
            {truth.error && <Alert kind="error">Could not load the case: {truth.error}</Alert>}
            {!truth.data && !truth.error && <Spinner />}
            {truth.data && <GroundTruthPanel name={name} caseId={caseId} data={truth.data} />}
          </Card>
          <div className="grid items-start gap-6 lg:grid-cols-2">
            {shown.map((r) => (
              <Card key={r.run} title={label(r, runs.data ?? [])} actions={<EsiPair got={r.esi} reference={r.reference_esi} />}>
                <Conversation messages={r.transcript} />
                {r.feedback && <div className="mt-4"><Alert>Evaluator: {r.feedback}</Alert></div>}
              </Card>))}
          </div>
        </div>
      </div>
    </Page>
  );
}
