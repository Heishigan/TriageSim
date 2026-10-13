import { useState } from "react";
import { type Job, api, post, put, useApi } from "../api";
import { Alert, Badge, Button, Card, Field, Page, Progress, Spinner, Table, inputClass } from "../components/ui";
import { OllamaAction, type OllamaStatus } from "../components/ollama";

type ModelList = { reachable: boolean; error?: string; models: { name: string; size: number; modified: string }[]; downloads: Job[] };
type Health = { ollama: OllamaStatus;
  settings: { ollama_url: string; hf_token_set: boolean; hf_token_hint: string } };

const gb = (b: number) => `${(b / 1e9).toFixed(1)} GB`;
type CatalogModel = { name: string; family: string; tier: string; size_gb: number; memory_gb: number;
  tags: string[]; note: string; installed: boolean; fits_gpu: boolean };
type Catalog = { tiers: Record<string, string>; models: CatalogModel[]; gpus: { name: string; memory_gb: number }[]; gpu_memory_gb: number };

export default function Models() {
  const models = useApi<ModelList>("/models", 2000);
  const health = useApi<Health>("/health", 4000);
  return (
    <Page title="3. Models" subtitle="Models run locally in Ollama. Download them from the Ollama library or from Hugging Face (GGUF files, with your token for gated models).">
      <Settings health={health.data} onSaved={() => { health.reload(); models.reload(); }} />
      {models.data && !models.data.reachable && health.data && (
        <OllamaMissing status={health.data.ollama} onChange={() => { health.reload(); models.reload(); }} />)}
      <Card title="Installed in Ollama">
        <Table head={["Model", "Size", "Downloaded", "", ""]} rows={(models.data?.models ?? []).map((m) => [
          <code>{m.name}</code>, gb(m.size), m.modified?.slice(0, 10), <TestButton name={m.name} />,
          <DeleteButton name={m.name} size={m.size} onDeleted={models.reload} />])}
          empty="No models installed yet." />
      </Card>
      <CatalogCard />
      <Download />
      {!!models.data?.downloads.length && (
        <Card title="Downloads">
          <div className="space-y-4">{models.data.downloads.map((j) => (
            <div key={j.id}>
              <div className="mb-1 flex items-center justify-between text-sm"><b>{j.label}</b>
                <Badge color={j.state === "done" ? "green" : j.state === "failed" ? "red" : "blue"}>{j.state}</Badge></div>
              {j.state === "running" && <Progress value={j.progress.completed ?? 0} total={j.progress.total || 1} label={j.progress.status} />}
              {j.state === "done" && <p className="text-xs text-slate-500">{String(j.result?.result ?? "")}</p>}
              {j.error && <p className="text-xs text-rose-600">{j.error}</p>}
            </div>))}</div>
        </Card>)}
    </Page>
  );
}

function OllamaMissing({ status, onChange }: { status: OllamaStatus; onChange: () => void }) {
  return (
    <Card title={status.installed ? "Ollama is installed but not running" : "Ollama is not installed"}>
      <div className="space-y-3 text-sm">
        <p>TriageSim runs models through <a className="font-medium text-brand-600 hover:underline" href="https://ollama.com/download"
          target="_blank" rel="noreferrer">Ollama</a>, a free program that keeps everything on this computer.
          {!status.installed && status.platform === "windows" && " One click downloads the official installer from ollama.com and runs it (no administrator rights needed)."}</p>
        <OllamaAction status={status} onChange={onChange} />
        <p className="text-slate-500">Without Ollama you can still try the whole app in demo mode (<code>start-demo-windows.bat</code>), which offers a Demo model with invented answers.</p>
      </div>
    </Card>
  );
}

function Settings({ health, onSaved }: { health: Health | null; onSaved: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);
  if (!health) return null;
  const save = async () => {
    await put("/settings", { ollama_url: url ?? health.settings.ollama_url, hf_token: token || null });
    setToken(""); setSaved(true); onSaved();
  };
  return (
    <Card title="Connection">
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-start">
        <Field label="Ollama address" hint="Where Ollama runs. The default is right for most computers.">
          <input className={inputClass} value={url ?? health.settings.ollama_url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Hugging Face token" hint={health.settings.hf_token_set ? `Saved (${health.settings.hf_token_hint}). Stored only on this computer.` : "Only needed for gated or private models. Stored only on this computer."}>
          <input type="password" className={inputClass} placeholder="hf_..." value={token} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <div className="md:pt-6"><Button variant="primary" onClick={save}>{saved ? "Saved" : "Save"}</Button></div>
      </div>
    </Card>
  );
}

function CatalogCard() {
  const catalog = useApi<Catalog>("/model-catalog", 5000).data;
  const [onlyFits, setOnlyFits] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!catalog) return null;
  const pull = async (name: string) => {
    setBusy(name); setError(null);
    try { await post("/models/pull", { name }); } catch (e) { setError((e as Error).message); }
    setBusy(null);
  };
  const gpu = catalog.gpus[0];
  return (
    <Card title="Model catalog" actions={gpu && (
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyFits} onChange={(e) => setOnlyFits(e.target.checked)} />Only what fits my GPU</label>)}>
      <p className="mb-4 text-sm text-slate-600">
        {gpu ? <>Detected GPU: <b>{gpu.name}</b> ({gpu.memory_gb} GB). Models marked <Badge color="green">fits</Badge> should run fast on it.</>
          : "No NVIDIA GPU detected: models run on the CPU, slowly. Start with the laptop models."}
        {" "}Sizes are approximate. All models run on this computer; cloud models are not offered because MIMIC data must stay local.
      </p>
      {error && <div className="mb-3"><Alert kind="error">{error}</Alert></div>}
      <div className="space-y-3">
        {Object.entries(catalog.tiers).map(([tier, label], i) => {
          const rows = catalog.models.filter((m) => m.tier === tier && (!onlyFits || m.fits_gpu || tier === "embedding"));
          if (!rows.length) return null;
          const have = rows.filter((m) => m.installed).length;
          return (
            <details key={tier} open={i === 0} className="group rounded-lg border border-slate-200">
              <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 hover:bg-slate-50">
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  <span className="text-slate-400 transition group-open:rotate-90">▶</span>{label}</span>
                <span className="text-xs text-slate-500">{rows.length} models{have ? ` · ${have} installed` : ""}</span>
              </summary>
              <div className="border-t border-slate-100 px-4 py-2">
              <Table head={["Model", "Family", "Download", "GPU memory", "", ""]} rows={rows.map((m) => [
                <code className="text-sm">{m.name}</code>,
                <span>{m.family} {m.tags.map((t) => <Badge key={t} color={t === "medical" ? "red" : t === "recent" ? "blue" : "gray"}>{t}</Badge>)}
                  {m.note && <span className="block text-xs text-slate-500">{m.note}</span>}</span>,
                `~${m.size_gb} GB`, <span>~{m.memory_gb} GB {m.fits_gpu && <Badge color="green">fits</Badge>}</span>, "",
                m.installed ? <Badge color="green">installed</Badge>
                  : <Button variant="ghost" disabled={busy === m.name} onClick={() => pull(m.name)}>{busy === m.name ? <Spinner /> : "Download"}</Button>])} />
              </div>
            </details>);
        })}
      </div>
    </Card>
  );
}

function Download() {
  const [source, setSource] = useState<"ollama" | "huggingface">("ollama");
  const [name, setName] = useState("");
  const [repo, setRepo] = useState("");
  const [file, setFile] = useState("");
  const [error, setError] = useState<string | null>(null);
  const start = async (model = name) => {
    setError(null);
    try {
      await post("/models/pull", source === "ollama" ? { name: model } : { name: model, source, hf_repo: repo, hf_file: file });
      setName("");
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <Card title="Download any other model">
      <div className="mb-4 flex gap-2">
        {(["ollama", "huggingface"] as const).map((s) => (
          <Button key={s} variant={source === s ? "primary" : "secondary"} onClick={() => setSource(s)}>{s === "ollama" ? "Ollama library" : "Hugging Face (GGUF)"}</Button>))}
      </div>
      {source === "ollama" ? (
        <div className="space-y-3">
          <div className="flex gap-3"><input className={inputClass} placeholder="e.g. qwen2.5:32b" value={name} onChange={(e) => setName(e.target.value)} />
            <Button variant="primary" disabled={!name} onClick={() => start()}>Download</Button></div>
          <p className="text-xs text-slate-500">Any model from <a className="text-brand-600 hover:underline" href="https://ollama.com/library" target="_blank" rel="noreferrer">ollama.com/library</a>, as name:size (e.g. qwen3.5:9b). Downloaded models stay on this computer and are reused; nothing is downloaded twice.</p>
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Repository" hint="e.g. bartowski/Qwen2.5-32B-Instruct-GGUF"><input className={inputClass} value={repo} onChange={(e) => setRepo(e.target.value)} /></Field>
          <Field label="GGUF file" hint="e.g. Qwen2.5-32B-Instruct-Q4_K_M.gguf"><input className={inputClass} value={file} onChange={(e) => setFile(e.target.value)} /></Field>
          <Field label="Name in Ollama" hint="What experiments will call it"><input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <div className="md:col-span-3 flex justify-end"><Button variant="primary" disabled={!repo || !file || !name} onClick={() => start()}>Download and register</Button></div>
        </div>
      )}
      {error && <div className="mt-3"><Alert kind="error">{error}</Alert></div>}
    </Card>
  );
}

function DeleteButton({ name, size, onDeleted }: { name: string; size: number; onDeleted: () => void }) {
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    const ok = window.confirm(`Delete ${name} from this computer?\n\nThis frees about ${gb(size)} of disk space. `
      + "Past results are not affected, and you can download the model again later.");
    if (!ok) return;
    setBusy(true);
    try {
      await api(`/models/${encodeURIComponent(name)}`, { method: "DELETE" });
      onDeleted();
    } catch (e) { window.alert((e as Error).message); }
    setBusy(false);
  };
  return <button className="text-sm font-medium text-rose-600 hover:underline disabled:text-slate-400" disabled={busy} onClick={remove}>
    {busy ? "Deleting…" : "Delete"}</button>;
}

function TestButton({ name }: { name: string }) {
  const [reply, setReply] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true);
    try {
      const r = await post<{ reply: string; seconds: number }>("/models/test", { name });
      setReply(`${r.reply} (${r.seconds}s)`);
    } catch (e) { setReply(`Error: ${(e as Error).message}`); }
    setBusy(false);
  };
  return (
    <div className="max-w-md">
      <Button variant="ghost" disabled={busy} onClick={test}>{busy ? <Spinner /> : "Test"}</Button>
      {reply && <p className="mt-1 text-xs text-slate-600">{reply}</p>}
    </div>
  );
}
