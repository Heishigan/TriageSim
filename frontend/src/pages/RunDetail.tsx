import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { type Metrics, type RunEvent, type RunStatus, api, post, useApi } from "../api";
import { Alert, Badge, Button, Card, Field, Page, Progress, Spinner, Stat, StateBadge, Table, ci, inputClass, pct } from "../components/ui";

type Detail = { name: string; status: RunStatus; config: { name: string; description: string; nurse: { mode: string; model: { name: string } };
  patient?: { model: { name: string }; persona: string; mode: string }; evaluator?: { enabled: boolean } } };
type Row = { case_id: string; persona: string | null; reference_esi: number; esi: number | null;
  head_injury: boolean | null; decided: boolean; forced: boolean; questions: number; seconds: number;
  scores: Record<string, number> | null };
type Results = { metrics: Metrics; cases: Row[] };
type Message = { speaker: string; text: string; turn: number; decision?: number; kind?: string; retrieved?: string[] };

export default function RunDetail() {
  const { name = "" } = useParams();
  const [tab, setTab] = useState<"live" | "cases" | "results">("live");
  const detail = useApi<Detail>(`/runs/${name}`, 2000);
  const st = detail.data?.status;
  const active = st?.state === "running" || st?.state === "created" || st?.state === "stopping";
  useEffect(() => { if (st && !active && st.state === "completed" && tab === "live") setTab("results"); }, [st?.state]); // eslint-disable-line

  const stop = () => post(`/runs/${name}/stop`).then(detail.reload);
  const resume = () => post(`/runs/${name}/resume`).then(() => { setTab("live"); detail.reload(); });
  const cfg = detail.data?.config;
  return (
    <Page title={name} subtitle={<Link className="text-brand-600 hover:underline" to="/runs">← All runs</Link>}
      actions={st && <>
        {active && <Button variant="danger" onClick={stop}>Stop</Button>}
        {(st.state === "stopped" || st.state === "interrupted" || st.state === "failed") && <Button variant="primary" onClick={resume}>Resume</Button>}
      </>}>
      {detail.error && <Alert kind="error">Could not load this run: {detail.error}</Alert>}
      {st && (
        <Card>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <StateBadge state={st.state} />
            <span><b>{cfg?.nurse.mode.replace("_", " ")}</b> · nurse {cfg?.nurse.model.name}
              {cfg?.patient && cfg.nurse.mode === "interview" && <> · patient {cfg.patient.model.name} ({cfg.patient.mode === "retrieval" ? "retrieval" : cfg.patient.persona})</>}</span>
            {st.current_case && <span className="text-slate-500">now: {st.current_case}</span>}
          </div>
          <div className="mt-4"><Progress value={st.done} total={st.total} label={`${st.done} of ${st.total} cases`} /></div>
          {st.state === "failed" && <div className="mt-4"><Alert kind="error"><pre className="whitespace-pre-wrap text-xs">{st.error}</pre></Alert></div>}
          {st.state === "interrupted" && <div className="mt-4"><Alert kind="warning">The app was closed while this run was going. Resume continues where it stopped.</Alert></div>}
        </Card>)}
      <div className="flex gap-1 border-b border-slate-200">
        {(["live", "cases", "results"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${
            tab === t ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {{ live: "Live", cases: "Cases", results: "Results" }[t]}</button>))}
      </div>
      {tab === "live" && <Live name={name} />}
      {tab === "cases" && <Cases name={name} />}
      {tab === "results" && <ResultsView name={name} />}
    </Page>
  );
}

/* ---- live view: server-sent events ------------------------------------------------- */
function Live({ name }: { name: string }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [ended, setEnded] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const source = new EventSource(`/api/runs/${name}/events`);
    source.onmessage = (e) => {
      try { const event = JSON.parse(e.data); setEvents((prev) => [...prev, event]); }
      catch { /* ignore a malformed line rather than break the page */ }
    };
    source.addEventListener("end", () => { setEnded(true); source.close(); });
    return () => source.close();
  }, [name]);
  useEffect(() => {
    // Braces matter: an effect may only return a clean-up function. Newer Chrome returns a
    // Promise from scrollIntoView, which React would then try to call.
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length]);

  const caseIds = useMemo(() => [...new Set(events.filter((e) => e.case_id).map((e) => e.case_id!))], [events]);
  const [pick, setPick] = useState<string | null>(null);
  const current = pick ?? caseIds[caseIds.length - 1];
  const messages = events.filter((e) => e.type === "message" && e.case_id === current) as Message[];
  const start = events.find((e) => e.type === "case_start" && e.case_id === current);
  const done = events.filter((e) => e.type === "case_done");
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
      <Card title={current ? `Conversation · ${current}` : "Conversation"} actions={<>
        {start?.persona && <Badge color="gray">persona: {start.persona}</Badge>}
        {pick && <Button variant="ghost" onClick={() => setPick(null)}>Follow live</Button>}</>}>
        {!messages.length && <p className="text-sm text-slate-500">{ended ? "No messages." : <span className="flex items-center gap-2"><Spinner /> Waiting for the first message…</span>}</p>}
        <Conversation messages={messages} />
        <div ref={bottom} />
      </Card>
      <Card title={`Finished cases (${done.length})`}>
        <ul className="max-h-[520px] space-y-1 overflow-y-auto text-sm">
          {[...done].reverse().map((e) => (
            <li key={e.case_id}><button onClick={() => setPick(e.case_id!)} className="flex w-full items-center justify-between rounded px-2 py-1 hover:bg-slate-50">
              <span className="font-mono text-xs">{e.case_id}</span>
              <EsiPair got={e.esi ?? e.esi_final} reference={e.reference_esi} /></button></li>))}
        </ul>
        {events.some((e) => e.type === "run_failed") && <Alert kind="error">{events.find((e) => e.type === "run_failed")?.error}</Alert>}
      </Card>
    </div>
  );
}

function EsiPair({ got, reference }: { got?: number | null; reference?: number | null }) {
  const color = got == null ? "gray" : got === reference ? "green" : got > (reference ?? 0) ? "red" : "amber";
  return <Badge color={color}>ESI {got ?? "–"} / ref {reference ?? "–"}</Badge>;
}

function Conversation({ messages }: { messages: Message[] }) {
  return (
    <div className="space-y-3">
      {messages.map((m, i) => m.speaker === "system" ? (
        <div key={i} className="mx-auto max-w-xl rounded-lg bg-slate-100 px-3 py-2 text-center text-xs text-slate-600">{m.text}</div>
      ) : (
        <div key={i} className={`flex ${m.speaker === "patient" ? "justify-end" : "justify-start"}`}>
          <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm shadow-sm ${m.speaker === "patient" ? "bg-brand-600 text-white" : "border border-slate-200 bg-white"}`}>
            <div className={`mb-0.5 text-[11px] font-semibold uppercase tracking-wide ${m.speaker === "patient" ? "text-brand-100" : "text-slate-400"}`}>
              {m.speaker}</div>
            <div className="whitespace-pre-wrap">{m.text}</div>
            {m.decision && <div className="mt-1"><Badge color="blue">Decision: ESI {m.decision}</Badge></div>}
            {m.retrieved && <details className="mt-1 text-xs opacity-80"><summary>retrieved passages</summary>{m.retrieved.map((r, j) => <p key={j}>• {r}</p>)}</details>}
          </div>
        </div>))}
    </div>
  );
}

/* ---- cases ------------------------------------------------------------------------- */
function Cases({ name }: { name: string }) {
  const { data, error } = useApi<Results>(`/runs/${name}/results`, 5000);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ transcript: Message[]; evaluation: { feedback: string } | null } | null>(null);
  useEffect(() => { if (open) api<typeof detail>(`/runs/${name}/cases/${open}`).then(setDetail); }, [open, name]);
  return (
    <div className="space-y-6">
      {error && <Alert kind="error">Could not load the cases: {error}</Alert>}
      <Card>
        <Table head={["Case", "Persona", "Nurse ESI", "Agent ESI", "Head injury", "Questions", "Scores", ""]}
          rows={(data?.cases ?? []).map((r) => [
            <span className="font-mono text-xs">{r.case_id}</span>, r.persona ?? "–", r.reference_esi,
            <span><EsiPair got={r.esi} reference={r.reference_esi} />{r.forced && <Badge color="amber">forced</Badge>}</span>,
            r.head_injury === null ? "–" : r.head_injury ? "yes" : "no", r.questions,
            r.scores ? Object.values(r.scores).join(" / ") : "–",
            <Button variant="ghost" onClick={() => setOpen(r.case_id)}>Transcript</Button>])}
          empty="No finished cases yet." />
      </Card>
      {open && detail && (
        <Card title={`Transcript · ${open}`} actions={<Button variant="ghost" onClick={() => { setOpen(null); setDetail(null); }}>Close</Button>}>
          <Conversation messages={detail.transcript} />
          {detail.evaluation && <div className="mt-4"><Alert>Evaluator: {detail.evaluation.feedback}</Alert></div>}
        </Card>)}
    </div>
  );
}

/* ---- results ----------------------------------------------------------------------- */
function ResultsView({ name }: { name: string }) {
  const { data, error } = useApi<Results>(`/runs/${name}/results`);
  const [summary, setSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (error) return <Alert kind="error">Could not load the results: {error}. The details are in the terminal window.</Alert>;
  if (!data) return <Spinner />;
  const m = data.metrics;
  if (!m.cases) return <Alert>No finished cases yet.</Alert>;
  const summarise = async () => {
    setBusy(true);
    try { setSummary((await post<{ summary: string }>(`/runs/${name}/summary`)).summary); }
    catch (e) { setSummary(`Error: ${(e as Error).message}`); }
    setBusy(false);
  };
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Agreement with nurse" value={pct(m.agreement)} sub={ci(m.agreement)} />
        <Stat label="Under-triage" value={pct(m.under_triage)} sub={ci(m.under_triage)} tone="bad" />
        <Stat label="Over-triage" value={pct(m.over_triage)} sub={ci(m.over_triage)} />
        <Stat label="Weighted kappa" value={m.weighted_kappa ?? "–"} sub={`${m.decided} decided · ${m.undecided} undecided · ${m.forced_decisions} forced`} />
      </div>
      {m.head_injury && (
        <div className="grid gap-4 md:grid-cols-3">
          <Stat label="Head-injury cases" value={m.head_injury.cases} sub="ICD S06 / 850–854 on the admission" />
          <Stat label="Head injury: under-triage vs nurse" value={pct(m.head_injury.under_triage_vs_nurse)} sub={ci(m.head_injury.under_triage_vs_nurse)} tone="bad" />
          <Stat label="Head injury: ESI 3 or less urgent" value={pct(m.head_injury.esi_3_or_lower_urgency)} sub={ci(m.head_injury.esi_3_or_lower_urgency)} tone="bad" />
        </div>)}
      <Card title="Summary" actions={<Button onClick={summarise} disabled={busy}>{busy ? <Spinner /> : summary ? "Write again" : "Write a plain-language summary"}</Button>}>
        {summary ? <p className="whitespace-pre-wrap text-sm leading-6">{summary}</p>
          : <p className="text-sm text-slate-500">A model reads the numbers below and writes a short overview. Always check it against the numbers.</p>}
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Agent ESI vs nurse ESI">
          <table className="text-sm"><thead><tr><th className="px-2 text-left text-xs text-slate-500">nurse ↓ / agent →</th>
            {[1, 2, 3, 4, 5].map((g) => <th key={g} className="w-12 px-2 text-center">{g}</th>)}</tr></thead>
            <tbody>{[1, 2, 3, 4, 5].map((ref) => (
              <tr key={ref}><td className="px-2 font-medium">{ref}</td>{[1, 2, 3, 4, 5].map((got) => {
                const v = m.confusion[ref][got];
                const tone = !v ? "text-slate-300" : got === ref ? "bg-emerald-50 font-semibold text-emerald-700" : got > ref ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-800";
                return <td key={got} className={`px-2 py-1 text-center ${tone}`}>{v}</td>;
              })}</tr>))}</tbody></table>
          <p className="mt-2 text-xs text-slate-500">Red = under-triage (less urgent than the nurse), amber = over-triage.</p>
        </Card>
        <Card title="Run details">
          <ul className="space-y-1 text-sm">
            <li>Within one ESI level of the nurse: {pct(m.within_one_level)} <span className="text-slate-500">({ci(m.within_one_level)})</span></li>
            <li>Decisions forced at the question limit: {m.forced_decisions}</li>
          </ul>
          {m.questions && <p className="mt-3 text-sm">Questions per interview: mean {m.questions.mean}, median {m.questions.median} (range {m.questions.min}–{m.questions.max})</p>}
          <p className="mt-1 text-sm text-slate-500">{m.seconds_per_case}s per case · {m.format_failures} format failures</p>
        </Card>
        <Card title="Evaluator scores (0–10)">
          <Table head={["Criterion", "Mean ± SD", "n"]} rows={Object.entries(m.evaluator_scores).map(([k, v]) => [
            k.replace(/_/g, " "), v ? `${v.mean} ± ${v.sd}` : "–", v?.n ?? 0])} />
        </Card>
        <Card title="By persona">
          <Table head={["Persona", "Cases", "Agreement", "Under-triage"]} rows={Object.entries(m.by_persona).map(([k, v]) => [
            k, v.cases, `${pct(v.agreement)} (${v.agreement.low}–${v.agreement.high})`, `${pct(v.under_triage)} (${v.under_triage.low}–${v.under_triage.high})`])}
            empty="No personas in this run." />
        </Card>
      </div>
      <Compare name={name} />
    </div>
  );
}

function Compare({ name }: { name: string }) {
  const runs = (useApi<{ name: string; state: string }[]>("/runs").data ?? []).filter((r) => r.name !== name);
  const [other, setOther] = useState("");
  const [outcome, setOutcome] = useState("under_triage");
  const [out, setOut] = useState<null | { paired_cases: number; a: { pct: number | null }; b: { pct: number | null }; only_a: number; only_b: number; p_value: number }>(null);
  const run = async () => setOut(await api(`/compare?a=${name}&b=${other}&outcome=${outcome}`));
  return (
    <Card title="Compare with another run (paired, exact McNemar)">
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <Field label="Other run"><select className={inputClass} value={other} onChange={(e) => setOther(e.target.value)}>
          <option value="">choose…</option>{runs.map((r) => <option key={r.name}>{r.name}</option>)}</select></Field>
        <Field label="Outcome"><select className={inputClass} value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="under_triage">Under-triage</option><option value="agreement">Agreement</option><option value="head_injury_under_triage">Head-injury under-triage</option></select></Field>
        <Button variant="primary" disabled={!other} onClick={run}>Compare</Button>
      </div>
      {out && <p className="mt-4 text-sm">On {out.paired_cases} cases decided in both runs: this run {out.a.pct ?? "–"}% vs {out.b.pct ?? "–"}%.
        Only this run: {out.only_a}, only the other: {out.only_b}. <b>p = {out.p_value}</b></p>}
    </Card>
  );
}
