import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { post, useApi } from "../api";
import { Alert, Badge, Button, Card, ConfirmDialog, Field, Page, Spinner, inputClass } from "../components/ui";

/* The experiment is edited as plain JSON mirroring the YAML; the server validates it. */
type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Preset = { name: string; config: Json };
type Fields = Record<string, { source: string; description: string }>;
type Cohort = { name: string; cases: number | null };

const ESI_HELP: Record<string, string> = {
  interview: "The nurse interviews the patient agent, one question at a time, then decides.",
  chart_review: "The nurse reads the chart (including the history) and decides. No conversation.",
  multiple_choice: "The same information as a board-style multiple-choice question.",
};

export default function NewExperiment() {
  const navigate = useNavigate();
  const presets = useApi<Preset[]>("/experiment-presets").data ?? [];
  const fields = useApi<Fields>("/fields").data ?? {};
  const cohorts = (useApi<Cohort[]>("/cohorts").data ?? []).filter((c) => c.cases);
  const models = useApi<{ models: { name: string }[] }>("/models").data?.models.map((m) => m.name) ?? [];
  const demoMode = useApi<{ demo: boolean }>("/health").data?.demo ?? false;
  const [config, setConfig] = useState<Json | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [sample, setSample] = useState<Sample | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  const choose = (p: Preset) => {
    const c = structuredClone(p.config);
    if (cohorts.length) c.cohort = cohorts[0].name;
    setConfig(c);
  };

  useEffect(() => {
    if (!config) return;
    const id = setTimeout(async () => {
      const r = await post<{ valid: boolean; errors: string[] }>("/experiments/validate", config);
      setErrors(r.errors);
    }, 300);
    return () => clearTimeout(id);
  }, [config]);

  // The sample check: which cases the run will get, recomputed when cohort or sampling change.
  const sampleKey = config && errors.length === 0 ? JSON.stringify([config.cohort, config.sampling]) : null;
  useEffect(() => {
    if (!sampleKey) { setSample(null); return; }
    setSample(null); setSampleError(null);
    const id = setTimeout(async () => {
      try { setSample(await post<Sample>("/experiments/preview", config)); }
      catch (e) { setSampleError((e as Error).message); }
    }, 400);
    return () => clearTimeout(id);
  }, [sampleKey]); // eslint-disable-line

  const set = (path: string, value: unknown) => setConfig((c) => {
    const next = structuredClone(c!);
    const keys = path.split(".");
    let t = next;
    for (const k of keys.slice(0, -1)) t = t[k];
    t[keys[keys.length - 1]] = value;
    return next;
  });

  const start = async () => {
    setStarting(true); setStartError(null);
    try {
      const r = await post<{ name: string }>("/runs", config);
      navigate(`/runs/${r.name}`);
    } catch (e) { setStarting(false); throw e; }
  };

  const downloadYaml = async () => {
    const r = await fetch("/api/experiments/yaml", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) });
    const url = URL.createObjectURL(await r.blob());
    Object.assign(document.createElement("a"), { href: url, download: `${config!.name}.yaml` }).click();
  };

  if (!config) {
    return (
      <Page title="4. New experiment" subtitle="Start from a preset, then adjust agents, models, prompts and cases.">
        {!cohorts.length && <Alert kind="warning">No cohort has case files yet. Build them under Cohorts & cases first.</Alert>}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {presets.map((p) => (
            <button key={p.name} onClick={() => choose(p)} className="rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-brand-500 hover:shadow">
              <div className="flex items-center justify-between"><span className="font-semibold text-slate-900">{p.name.replace(/_/g, " ")}</span>
                <Badge color="blue">{p.config.nurse.mode.replace("_", " ")}</Badge></div>
              <p className="mt-2 text-sm text-slate-500">{p.config.description}</p>
            </button>))}
        </div>
      </Page>
    );
  }

  const interview = config.nurse.mode === "interview";
  return (
    <Page title={`4. New experiment: ${config.name}`} subtitle={config.description}
      actions={<>
        <Button onClick={() => setConfig(null)}>Change preset</Button>
        <Button onClick={downloadYaml} disabled={errors.length > 0}>Download YAML</Button>
        <Button variant="primary" disabled={errors.length > 0 || starting || !config.cohort || !sample?.ok}
          title={!sample ? "Waiting for the sample check" : !sample.ok ? "Fix the sample check first" : undefined}
          onClick={() => setConfirming(true)}>
          {starting ? <span className="flex items-center gap-2"><Spinner /> Starting…</span> : "Start run"}</Button>
      </>}>
      {errors.length > 0 && <Alert kind="error"><b>Fix before running:</b><ul className="mt-1 list-disc pl-5">{errors.map((e) => <li key={e}>{e}</li>)}</ul></Alert>}
      {startError && <Alert kind="error">{startError}</Alert>}

      <Card title="Experiment">
        <div className="grid gap-4 md:grid-cols-4">
          <Field label="Name"><input className={inputClass} value={config.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Cohort (with case files)">
            <select className={inputClass} value={config.cohort} onChange={(e) => set("cohort", e.target.value)}>
              {!cohorts.some((c) => c.name === config.cohort) && <option value={config.cohort}>{config.cohort} (newest matching)</option>}
              {cohorts.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.cases} cases)</option>)}
            </select></Field>
          <Field label="Number of cases" hint="Empty = all cases">
            <input type="number" min={1} className={inputClass} value={config.sampling.cases ?? ""}
              onChange={(e) => set("sampling.cases", e.target.value === "" ? null : Number(e.target.value))} /></Field>
          <Field label="Which cases" hint={config.sampling.order === "stratified"
            ? "Same ESI mix as the cohort; seeded, so every run with this seed gets the same cases"
            : "Random is seeded, so it is reproducible"}>
            <div className="flex gap-2">
              <select className={inputClass} value={config.sampling.order} onChange={(e) => set("sampling.order", e.target.value)}>
                <option value="stratified">Stratified by ESI</option><option value="random">Random sample</option><option value="first">First cases</option></select>
              <input type="number" title="Seed" className={`${inputClass} w-24`} value={config.sampling.seed} onChange={(e) => set("sampling.seed", Number(e.target.value))} />
            </div></Field>
        </div>
        {config.sampling.order === "stratified" && (
          <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={!!config.sampling.stratify_head_injury}
              onChange={(e) => set("sampling.stratify_head_injury", e.target.checked)} />
            Also keep the share of head-injury cases (ICD label) within each ESI level
          </label>)}
      </Card>

      <SampleCheck sample={sample} error={sampleError} waiting={!!sampleKey && !sample && !sampleError} />

      {confirming && sample && (
        <ConfirmDialog title={`Start ${config.name}?`} confirmLabel="Start run" busyLabel="Starting…" variant="primary"
          onClose={() => setConfirming(false)} onConfirm={start}>
          <p>{sample.flow.sample.toLocaleString()} cases from <code>{config.cohort}</code>, {config.sampling.order}
            {config.sampling.stratify_head_injury ? " by ESI and head injury" : config.sampling.order === "stratified" ? " by ESI" : ""}, seed {config.sampling.seed}.</p>
          <p>ESI {sample.esi.map((r) => `${r.level}: ${r.sample}`).join(" · ")}
            {sample.head_injury ? ` · head injury ${sample.head_injury.sample} (${sample.head_injury.sample_pct}%)` : ""}</p>
          <p>Nurse <code>{config.nurse.model.name}</code>
            {config.nurse.mode === "interview" && config.patient ? <> · patient <code>{config.patient.model.name}</code></> : null}
            {config.evaluator?.enabled ? <> · evaluator <code>{config.evaluator.model.name}</code></> : null}</p>
          <p>Sample ID <code>{sample.sample_id}</code>: runs with the same ID use exactly the same patients.</p>
          {sample.checks.some((c) => c.level === "warning") && <Alert kind="warning">The sample check has warnings; see above.</Alert>}
        </ConfirmDialog>)}

      {!models.length && !demoMode && <Alert kind="warning">No models are downloaded yet. Download at least one under <a className="font-medium underline" href="/models">Models</a>, then come back.</Alert>}
      <AgentCard title="Nurse agent" path="nurse" agent={config.nurse} set={set} fields={fields} models={models} demoMode={demoMode} exclude={["persona", "esi", "disposition", "head_injury", "transcript", "decision"]}>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Mode" hint={ESI_HELP[config.nurse.mode]}>
            <select className={inputClass} value={config.nurse.mode} onChange={(e) => {
              set("nurse.mode", e.target.value);
              if (e.target.value === "interview" && !config.patient) set("patient", presets.find((p) => p.name === "interview")?.config.patient);
            }}>
              <option value="interview">Interview</option><option value="chart_review">Chart review</option><option value="multiple_choice">Multiple choice</option>
            </select></Field>
          {interview && <Field label="Question limit" hint="After this many questions the nurse must decide.">
            <input type="number" min={1} max={50} className={inputClass} value={config.nurse.max_turns} onChange={(e) => set("nurse.max_turns", Number(e.target.value))} /></Field>}
          {interview && <Field label="Opening question"><input className={inputClass} value={config.nurse.opening_message} onChange={(e) => set("nurse.opening_message", e.target.value)} /></Field>}
        </div>
      </AgentCard>

      {interview && config.patient && (
        <AgentCard title="Patient agent" path="patient" agent={config.patient} set={set} fields={fields} models={models} demoMode={demoMode} exclude={["esi", "disposition", "head_injury", "transcript", "decision", "vitals", "arrival_transport"]}>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="How the patient answers" hint={config.patient.mode === "retrieval" ? "Only from passages of the record retrieved for each question (embedding model below)." : "In character, from what the patient knows."}>
              <select className={inputClass} value={config.patient.mode} onChange={(e) => set("patient.mode", e.target.value)}>
                <option value="llm">Language model in character</option><option value="retrieval">Retrieval only (grounded)</option></select></Field>
            {config.patient.mode === "retrieval" ? (
              <Field label="Embedding model"><input className={inputClass} value={config.patient.retrieval_embedding_model} onChange={(e) => set("patient.retrieval_embedding_model", e.target.value)} /></Field>
            ) : (
              <Field label="Persona" hint="'random' draws one per case (reproducibly).">
                <select className={inputClass} value={config.patient.persona} onChange={(e) => set("patient.persona", e.target.value)}>
                  <option value="random">random (not neutral)</option>
                  {Object.keys(config.patient.personas).map((p) => <option key={p}>{p}</option>)}</select></Field>
            )}
          </div>
          {config.patient.mode === "llm" && (
            <details className="mt-4"><summary className="cursor-pointer text-sm font-medium text-brand-600">Edit personas</summary>
              <div className="mt-3 space-y-3">{Object.entries(config.patient.personas as Record<string, string>).map(([k, v]) => (
                <Field key={k} label={k}><textarea rows={2} className={`${inputClass} text-xs`} value={v} onChange={(e) => set(`patient.personas.${k}`, e.target.value)} /></Field>))}</div>
            </details>)}
        </AgentCard>)}

      {config.evaluator && (
        <AgentCard title="Evaluator agent" path="evaluator" agent={config.evaluator} set={set} fields={fields} models={models} demoMode={demoMode} exclude={["persona"]}
          toggle={<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={config.evaluator.enabled} onChange={(e) => set("evaluator.enabled", e.target.checked)} />enabled</label>}>
          <p className="text-sm text-slate-500">Reads the transcript and the reference answers after each case and scores the nurse (0–10) on history taking, risk identification and decision.</p>
        </AgentCard>)}
    </Page>
  );
}

function AgentCard({ title, path, agent, set, fields, models, demoMode, exclude, toggle, children }: {
  title: string; path: string; agent: Json; set: (p: string, v: unknown) => void; fields: Fields; models: string[]; demoMode: boolean;
  exclude: string[]; toggle?: React.ReactNode; children?: React.ReactNode;
}) {
  const options = useMemo(() => Object.entries(fields).filter(([k]) => !exclude.includes(k)), [fields, exclude]);
  const sees: string[] = agent.sees;
  const m = agent.model;
  const installed = models.includes(m.name) || models.includes(`${m.name}:latest`);
  const choice = m.source === "demo" ? "__demo" : installed ? m.name : "";
  return (
    <Card title={title} actions={toggle}>
      <div className="space-y-5">
        {children}
        <div className="grid gap-4 md:grid-cols-4">
          <Field label="Model" hint={!choice ? <span className="text-rose-600">Choose a downloaded model{m.name ? ` (the preset's ${m.name} is not downloaded)` : ""}.</span>
            : "Only downloaded models are listed. Get more under Models."}>
            <select className={inputClass} value={choice} onChange={(e) => {
              const v = e.target.value;
              if (v === "__demo") set(`${path}.model.source`, "demo");
              else { set(`${path}.model.source`, "ollama"); set(`${path}.model.name`, v); }
            }}>
              {!choice && <option value="" disabled>Choose a model…</option>}
              {models.map((x) => <option key={x} value={x}>{x}</option>)}
              {demoMode && <option value="__demo">Demo model (fake answers, demo mode only)</option>}
            </select></Field>
          <Field label="Temperature" hint="0 = most deterministic"><input type="number" step={0.1} min={0} max={2} className={inputClass} value={m.temperature ?? ""}
            onChange={(e) => set(`${path}.model.temperature`, e.target.value === "" ? null : Number(e.target.value))} /></Field>
          <Field label="Seed"><input type="number" className={inputClass} value={m.seed ?? ""} onChange={(e) => set(`${path}.model.seed`, e.target.value === "" ? null : Number(e.target.value))} /></Field>
          <Field label="Max reply length" hint="Tokens, reasoning included; stops a runaway reply. Empty = no limit">
            <input type="number" min={64} step={512} className={inputClass} value={m.max_tokens ?? ""}
              onChange={(e) => set(`${path}.model.max_tokens`, e.target.value === "" ? null : Number(e.target.value))} /></Field>
          {m.source === "huggingface" && <>
            <Field label="HF repository"><input className={inputClass} value={m.hf_repo ?? ""} onChange={(e) => set(`${path}.model.hf_repo`, e.target.value)} /></Field>
            <Field label="GGUF file"><input className={inputClass} value={m.hf_file ?? ""} onChange={(e) => set(`${path}.model.hf_file`, e.target.value)} /></Field>
          </>}
          {m.source === "demo" && <div className="md:col-span-4"><Alert kind="warning">Demo model: canned answers to try the app. Results mean nothing.</Alert></div>}
        </div>
        <Field group label="What this agent may read" hint="Ticking a field allows it; the agent only receives it where the prompt uses {field}. Reference answers are never available to the nurse or patient.">
          <div className="flex flex-wrap gap-2 pt-1">{options.map(([k, f]) => (
            <label key={k} title={f.description} className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
              sees.includes(k) ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 text-slate-600"}`}>
              <input type="checkbox" className="hidden" checked={sees.includes(k)}
                onChange={() => set(`${path}.sees`, sees.includes(k) ? sees.filter((x) => x !== k) : [...sees, k])} />
              {`{${k}}`}</label>))}</div>
        </Field>
        <Field label="Prompt" hint="Use {field} to insert case information.">
          <textarea rows={10} className={`${inputClass} font-mono text-xs leading-5`} value={agent.system_prompt}
            onChange={(e) => set(`${path}.system_prompt`, e.target.value)} /></Field>
      </div>
    </Card>
  );
}

type Check = { level: "ok" | "info" | "warning" | "error"; text: string };
type Sample = {
  flow: { cohort_stays: number; cases: number; usable: number; requested: number | null; sample: number };
  esi: { level: number; cohort: number; cohort_pct: number | null; sample: number; sample_pct: number | null }[];
  head_injury: { pool: number; pool_pct: number | null; sample: number; sample_pct: number | null } | null;
  sex: { F: number; M: number }; age_median: number | null;
  with_hpi: number; with_medications: number; with_all_vitals: number; hpi_redacted: number;
  sample_id: string; checks: Check[]; ok: boolean;
};

const CHECK_STYLE: Record<Check["level"], [string, string]> = {
  ok: ["✓", "text-emerald-700"], info: ["i", "text-slate-500"], warning: ["!", "text-amber-700"], error: ["✕", "text-rose-700"],
};

function SampleCheck({ sample, error, waiting }: { sample: Sample | null; error: string | null; waiting: boolean }) {
  if (error) return <Alert kind="error">Sample check: {error}</Alert>;
  if (!sample) return waiting ? <Card title="Sample check"><p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Drawing the sample…</p></Card> : null;
  const n = sample.flow.sample;
  const pct = (k: number) => (n ? `${((100 * k) / n).toFixed(1)}%` : "–");
  return (
    <Card title="Sample check" actions={<span className="text-xs text-slate-500">Sample ID <code>{sample.sample_id}</code></span>}>
      <p className="text-sm text-slate-700">
        Cohort {sample.flow.cohort_stays.toLocaleString()} stays → case files {sample.flow.cases.toLocaleString()} → with ESI {sample.flow.usable.toLocaleString()} → <b>this run {n.toLocaleString()} cases</b>
      </p>
      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <table className="text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-slate-500"><th className="py-1">ESI</th><th>Cohort</th><th>This run</th></tr></thead>
          <tbody>
            {sample.esi.map((r) => (
              <tr key={r.level} className="border-t border-slate-100">
                <td className="py-1">{r.level}</td>
                <td>{r.cohort.toLocaleString()} <span className="text-slate-400">({r.cohort_pct ?? "–"}%)</span></td>
                <td>{r.sample.toLocaleString()} <span className="text-slate-400">({r.sample_pct ?? "–"}%)</span></td>
              </tr>))}
            {sample.head_injury && (
              <tr className="border-t border-slate-200">
                <td className="py-1">Head injury</td>
                <td>{sample.head_injury.pool.toLocaleString()} <span className="text-slate-400">({sample.head_injury.pool_pct}% of cases)</span></td>
                <td>{sample.head_injury.sample.toLocaleString()} <span className="text-slate-400">({sample.head_injury.sample_pct}%)</span></td>
              </tr>)}
          </tbody>
        </table>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-slate-500">Female / male</dt><dd>{sample.sex.F} / {sample.sex.M}</dd>
          <dt className="text-slate-500">Median age</dt><dd>{sample.age_median ?? "–"}</dd>
          <dt className="text-slate-500">With history (HPI)</dt><dd>{sample.with_hpi} ({pct(sample.with_hpi)})</dd>
          <dt className="text-slate-500">History redacted</dt><dd>{sample.hpi_redacted} ({pct(sample.hpi_redacted)})</dd>
          <dt className="text-slate-500">With home medications</dt><dd>{sample.with_medications} ({pct(sample.with_medications)})</dd>
          <dt className="text-slate-500">With all vital signs</dt><dd>{sample.with_all_vitals} ({pct(sample.with_all_vitals)})</dd>
        </dl>
      </div>
      <ul className="mt-4 space-y-1 text-sm">
        {sample.checks.map((c, i) => (
          <li key={i} className={`flex gap-2 ${CHECK_STYLE[c.level][1]}`}><span className="w-4 text-center font-semibold">{CHECK_STYLE[c.level][0]}</span>{c.text}</li>))}
      </ul>
    </Card>
  );
}
