import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { type CohortSettings, api, post, useApi } from "../api";
import { Alert, Button, Card, ConfirmDialog, DeleteLink, Field, Page, Spinner, Table, inputClass } from "../components/ui";

type Preset = { name: string; settings: CohortSettings };
type Cohort = { name: string; created: string; patients: number | null; cases: number | null };

const EMPTY: CohortSettings = { name: "cohort", min_age: null, max_age: null, sexes: ["F", "M"], admission: "any",
  icd10_codes: [], icd9_codes: [], require_acuity: false, esi_levels: [1, 2, 3, 4, 5], one_visit_per_patient: false };

function describe(s: CohortSettings): string[] {
  const out: string[] = [];
  if (s.min_age !== null || s.max_age !== null)
    out.push(s.max_age === null ? `Age ${s.min_age} or older at the ED visit` : `Age ${s.min_age ?? 0} to ${s.max_age}`);
  if (s.sexes.length === 1) out.push(`Sex: ${s.sexes[0]}`);
  if (s.admission !== "any") out.push(s.admission === "admitted" ? "Admitted to hospital" : "Not admitted to hospital");
  if (s.icd10_codes.length || s.icd9_codes.length)
    out.push("ED diagnosis includes " + [s.icd10_codes.length ? `ICD-10 ${s.icd10_codes.join(", ")}` : "",
      s.icd9_codes.length ? `ICD-9 ${s.icd9_codes.join(", ")}` : ""].filter(Boolean).join(" or "));
  if (s.require_acuity) out.push("Triage acuity (ESI) recorded");
  if (s.esi_levels.length < 5) out.push(`ESI level ${s.esi_levels.join(", ")}`);
  if (s.one_visit_per_patient) out.push("First qualifying visit per patient");
  return out;
}

const codes = (text: string) => text.split(/[,;\s]+/).map((c) => c.trim().toUpperCase().replace(/\./g, "")).filter(Boolean);

export default function Cohorts() {
  const cohorts = useApi<Cohort[]>("/cohorts");
  const presets = useApi<Preset[]>("/cohort-presets").data ?? [];
  const [building, setBuilding] = useState(false);
  const [deleting, setDeleting] = useState<Cohort | null>(null);
  return (
    <Page title="2. Cohorts & cases" subtitle="Choose which ED visits to study, then turn them into case files for the agents."
      actions={!building && <Button variant="primary" onClick={() => setBuilding(true)}>New cohort</Button>}>
      {building && <Builder presets={presets} onCancel={() => setBuilding(false)} />}
      <Card title="Saved cohorts">
        <Table head={["Cohort", "Created", "Patients", "Case files", ""]}
          rows={(cohorts.data ?? []).map((c) => [
            <Link className="font-medium text-brand-600 hover:underline" to={`/cohorts/${c.name}`}>{c.name}</Link>,
            c.created?.replace("T", " "), c.patients?.toLocaleString(),
            c.cases ? `${c.cases.toLocaleString()} cases` : <span className="text-slate-400">not built yet</span>,
            <DeleteLink onClick={() => setDeleting(c)} />])}
          empty="No cohorts yet. Click New cohort." />
      </Card>
      {deleting && <DeleteCohort cohort={deleting} onClose={() => setDeleting(null)}
        onDeleted={() => { setDeleting(null); cohorts.reload(); }} />}
    </Page>
  );
}

function DeleteCohort({ cohort, onClose, onDeleted }: { cohort: Cohort; onClose: () => void; onDeleted: () => void }) {
  const runs = useApi<{ name: string; active: boolean }[]>(`/cohorts/${encodeURIComponent(cohort.name)}/runs`);
  const used = runs.data ?? [];
  return (
    <ConfirmDialog title={`Delete cohort ${cohort.name}?`} confirmLabel="Delete cohort" onClose={onClose}
      onConfirm={async () => { await api(`/cohorts/${encodeURIComponent(cohort.name)}`, { method: "DELETE" }); onDeleted(); }}>
      <p>{cohort.patients?.toLocaleString() ?? "?"} patients{cohort.cases ? `, ${cohort.cases.toLocaleString()} case files` : ""}.
        This permanently deletes the cohort and its case files from this computer. It cannot be undone.</p>
      <p>The MIMIC data files are not affected; you can build the cohort again.</p>
      {runs.error ? <Alert kind="warning">Could not check which runs use this cohort: {runs.error}</Alert>
        : runs.data === null ? <p className="text-slate-400">Checking which runs use it…</p>
        : used.length > 0 && (
          <Alert kind="warning">
            <p className="font-medium">{used.length} run{used.length > 1 ? "s use" : " uses"} this cohort.</p>
            <p className="mt-1">Their results stay, but they can no longer be resumed or show case details:</p>
            <ul className="mt-1 list-disc pl-5 text-xs">{used.map((r) => <li key={r.name}><code>{r.name}</code>{r.active ? " (running)" : ""}</li>)}</ul>
          </Alert>)}
    </ConfirmDialog>
  );
}

function Builder({ presets, onCancel }: { presets: Preset[]; onCancel: () => void }) {
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2>(1);
  const [s, setS] = useState<CohortSettings>(EMPTY);
  const [icd10, setIcd10] = useState("");
  const [icd9, setIcd9] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const usePreset = (name: string) => {
    const p = presets.find((x) => x.name === name);
    const next = p ? p.settings : EMPTY;
    setS(next); setIcd10(next.icd10_codes.join(", ")); setIcd9(next.icd9_codes.join(", "));
  };
  useEffect(() => { if (presets.length && s === EMPTY) usePreset(presets[0].name); }, [presets]); // eslint-disable-line

  const settings: CohortSettings = { ...s, icd10_codes: codes(icd10), icd9_codes: codes(icd9) };
  const problem = !/^[A-Za-z0-9_-]+$/.test(s.name) ? "Name: letters, digits, - and _ only."
    : !s.sexes.length ? "Choose at least one sex." : !s.esi_levels.length ? "Choose at least one ESI level."
    : s.min_age !== null && s.max_age !== null && s.min_age > s.max_age ? "Minimum age is above maximum age." : null;

  const build = async () => {
    setBusy(true); setError(null);
    try {
      const r = await post<{ name: string }>("/cohorts", settings);
      navigate(`/cohorts/${r.name}`);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <Card title={`New cohort · step ${step} of 2: ${step === 1 ? "filters" : "review and build"}`}
      actions={<Button variant="ghost" onClick={onCancel}>Cancel</Button>}>
      {step === 1 ? (
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Start from a preset">
            <select className={inputClass} onChange={(e) => usePreset(e.target.value)} defaultValue={presets[0]?.name}>
              {presets.map((p) => <option key={p.name}>{p.name}</option>)}
              <option value="">(none: every ED stay)</option>
            </select>
          </Field>
          <Field label="Cohort name" hint="Used for the folder name.">
            <input className={inputClass} value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} />
          </Field>
          <Field label="Minimum age" hint="Age at the ED visit. Empty = no minimum.">
            <input type="number" min={0} max={120} className={inputClass} value={s.min_age ?? ""}
              onChange={(e) => setS({ ...s, min_age: e.target.value === "" ? null : Number(e.target.value) })} />
          </Field>
          <Field label="Maximum age" hint="Empty = no maximum. MIMIC reports ages above 89 as 91.">
            <input type="number" min={0} max={120} className={inputClass} value={s.max_age ?? ""}
              onChange={(e) => setS({ ...s, max_age: e.target.value === "" ? null : Number(e.target.value) })} />
          </Field>
          <Field label="Sex">
            <div className="flex gap-4 pt-1 text-sm">{["F", "M"].map((x) => (
              <label key={x} className="flex items-center gap-2"><input type="checkbox" checked={s.sexes.includes(x)}
                onChange={() => setS({ ...s, sexes: toggle(s.sexes, x) })} />{x === "F" ? "Female" : "Male"}</label>))}</div>
          </Field>
          <Field label="Hospital admission">
            <select className={inputClass} value={s.admission} onChange={(e) => setS({ ...s, admission: e.target.value })}>
              <option value="any">Any</option><option value="admitted">Admitted only</option><option value="not_admitted">Not admitted only</option>
            </select>
          </Field>
          <Field label="ICD-10 codes in the ED diagnoses" hint="Prefixes (S06) or ranges (W00-W19), comma separated. Empty = no code filter.">
            <input className={inputClass} value={icd10} onChange={(e) => setIcd10(e.target.value)} />
          </Field>
          <Field label="ICD-9 codes in the ED diagnoses" hint="ICD-9 codes start with a digit, E or V, e.g. E880-E888.">
            <input className={inputClass} value={icd9} onChange={(e) => setIcd9(e.target.value)} />
          </Field>
          <Field label="ESI levels">
            <div className="flex gap-3 pt-1 text-sm">{[1, 2, 3, 4, 5].map((x) => (
              <label key={x} className="flex items-center gap-1.5"><input type="checkbox" checked={s.esi_levels.includes(x)}
                onChange={() => setS({ ...s, esi_levels: toggle(s.esi_levels, x).sort() })} />{x}</label>))}</div>
          </Field>
          <div className="space-y-2 pt-6 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.require_acuity}
              onChange={(e) => setS({ ...s, require_acuity: e.target.checked })} />Require a triage acuity (ESI)</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.one_visit_per_patient}
              onChange={(e) => setS({ ...s, one_visit_per_patient: e.target.checked })} />One visit per patient (first qualifying visit)</label>
          </div>
          <div className="md:col-span-2 flex items-center justify-end gap-3">
            {problem && <span className="text-sm text-rose-600">{problem}</span>}
            <Button variant="primary" disabled={!!problem} onClick={() => setStep(2)}>Next: review</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm"><span className="font-medium">Cohort:</span> {settings.name}</p>
          <div>
            <p className="text-sm font-medium">Filters that will be applied, in this order:</p>
            <ol className="mt-2 list-decimal space-y-1 pl-6 text-sm">
              {describe(settings).map((d) => <li key={d}>{d}</li>)}
              {!describe(settings).length && <li className="list-none text-amber-700">No filters: every ED stay.</li>}
            </ol>
          </div>
          {error && <Alert kind="error">{error}</Alert>}
          <div className="flex justify-between">
            <Button onClick={() => setStep(1)}>Back</Button>
            <Button variant="primary" disabled={busy} onClick={build}>
              {busy ? <span className="flex items-center gap-2"><Spinner /> Building (first time ~1 min)…</span> : "Build cohort"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
