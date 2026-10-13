import { useState } from "react";
import { type Job, post, put, useApi } from "../api";
import { Alert, Badge, Button, Card, Field, Page, Progress, Spinner, Table, inputClass } from "../components/ui";

type ModelList = { reachable: boolean; error?: string; models: { name: string; size: number; modified: string }[]; downloads: Job[] };
type Health = { settings: { ollama_url: string; hf_token_set: boolean; hf_token_hint: string } };

const gb = (b: number) => `${(b / 1e9).toFixed(1)} GB`;
const SUGGESTED = ["qwen2.5:32b", "llama3.1:8b", "nomic-embed-text"];

export default function Models() {
  const models = useApi<ModelList>("/models", 2000);
  const health = useApi<Health>("/health");
  return (
    <Page title="3. Models" subtitle="Models run locally in Ollama. Download them from the Ollama library or from Hugging Face (GGUF files, with your token for gated models).">
      <Settings health={health.data} onSaved={() => { health.reload(); models.reload(); }} />
      {models.data && !models.data.reachable && (
        <Alert kind="error">Ollama is not reachable: {models.data.error} Install it from ollama.com and start it, or change its address above.</Alert>)}
      <Download installed={models.data?.models.map((m) => m.name) ?? []} />
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
      <Card title="Installed in Ollama">
        <Table head={["Model", "Size", "", ""]} rows={(models.data?.models ?? []).map((m) => [
          <code>{m.name}</code>, gb(m.size), m.modified?.slice(0, 10), <TestButton name={m.name} />])}
          empty="No models installed yet." />
      </Card>
    </Page>
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
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <Field label="Ollama address"><input className={inputClass} value={url ?? health.settings.ollama_url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Field label="Hugging Face token" hint={health.settings.hf_token_set ? `Saved (${health.settings.hf_token_hint}). Stored only on this computer.` : "Only needed for gated or private models. Stored only on this computer."}>
          <input type="password" className={inputClass} placeholder="hf_..." value={token} onChange={(e) => setToken(e.target.value)} />
        </Field>
        <Button variant="primary" onClick={save}>{saved ? "Saved" : "Save"}</Button>
      </div>
    </Card>
  );
}

function Download({ installed }: { installed: string[] }) {
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
    <Card title="Download a model">
      <div className="mb-4 flex gap-2">
        {(["ollama", "huggingface"] as const).map((s) => (
          <Button key={s} variant={source === s ? "primary" : "secondary"} onClick={() => setSource(s)}>{s === "ollama" ? "Ollama library" : "Hugging Face (GGUF)"}</Button>))}
      </div>
      {source === "ollama" ? (
        <div className="space-y-3">
          <div className="flex gap-3"><input className={inputClass} placeholder="e.g. qwen2.5:32b" value={name} onChange={(e) => setName(e.target.value)} />
            <Button variant="primary" disabled={!name} onClick={() => start()}>Download</Button></div>
          <p className="text-xs text-slate-500">Used by the presets: {SUGGESTED.map((m) => (
            <button key={m} className="mr-2 text-brand-600 hover:underline disabled:text-slate-400" disabled={installed.includes(m) || installed.includes(`${m}:latest`)}
              onClick={() => start(m)}>{m}{installed.includes(m) || installed.includes(`${m}:latest`) ? " ✓" : ""}</button>))}</p>
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
