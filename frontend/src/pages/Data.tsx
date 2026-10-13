import { useState } from "react";
import { post, useApi } from "../api";
import { Alert, Badge, Button, Card, Page } from "../components/ui";

type Check = {
  data_dir: string; tree: string;
  groups: { purpose: string; label: string; ready: boolean;
    files: { path: string; ok: boolean; message: string; source: string; url: string }[] }[];
};

export default function Data() {
  const { data, error, reload, loading } = useApi<Check>("/data");
  const [opened, setOpened] = useState<string | null>(null);
  const openFolder = async () => {
    try { setOpened(`Opened in your file manager: ${(await post<{ opened: string }>("/data/open-folder")).opened}`); }
    catch (e) { setOpened((e as Error).message); }
  };
  return (
    <Page title="1. Data" subtitle="Place the MIMIC files in the data folder of TriageSim, exactly as shown. The files never leave this computer."
      actions={<>
        <Button onClick={openFolder}>Open the data folder</Button>
        <Button variant="primary" onClick={reload} disabled={loading}>Check again</Button>
      </>}>
      {error && <Alert kind="error">{error}</Alert>}
      {opened && <Alert>{opened}</Alert>}
      {data && (
        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          <div className="space-y-6">
            {data.groups.map((g) => (
              <Card key={g.purpose} title={g.label} actions={<Badge color={g.ready ? "green" : g.purpose === "labels" ? "amber" : "red"}>{g.ready ? "ready" : g.purpose === "labels" ? "optional" : "missing files"}</Badge>}>
                <ul className="space-y-2">
                  {g.files.map((f) => (
                    <li key={f.path + g.purpose} className="flex items-start gap-3 text-sm">
                      <span className={f.ok ? "text-emerald-600" : "text-rose-500"}>{f.ok ? "✓" : "✗"}</span>
                      <span className="flex-1">
                        <code className="font-mono text-slate-800">{f.path}</code>
                        {!f.ok && <span className="block text-xs text-slate-500">{f.message} <a className="text-brand-600 hover:underline" href={f.url} target="_blank" rel="noreferrer">{f.source}</a></span>}
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>
          <Card title="Expected layout">
            <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 font-mono text-xs leading-5 text-slate-100">{data.tree}</pre>
            <p className="mt-3 text-xs text-slate-500">On this computer: <code className="break-all">{data.data_dir}</code></p>
            <p className="mt-2 text-xs text-slate-500">Keep the files compressed (.csv.gz) and do not rename them. MIMIC requires credentialed PhysioNet access.</p>
          </Card>
        </div>
      )}
    </Page>
  );
}
