import { NavLink, Route, Routes } from "react-router-dom";
import { useApi } from "./api";
import Home from "./pages/Home";
import Data from "./pages/Data";
import Cohorts from "./pages/Cohorts";
import CohortDetail from "./pages/CohortDetail";
import Models from "./pages/Models";
import NewExperiment from "./pages/NewExperiment";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";

const STEPS = [
  { to: "/data", label: "Data", n: 1 },
  { to: "/cohorts", label: "Cohorts & cases", n: 2 },
  { to: "/models", label: "Models", n: 3 },
  { to: "/experiments/new", label: "New experiment", n: 4 },
  { to: "/runs", label: "Runs & results", n: 5 },
];

type Health = { version: string; demo: boolean; ollama: { reachable: boolean; installed: boolean; version?: string } };

export default function App() {
  const { data: health } = useApi<Health>("/health", 10000);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col bg-slate-900 text-slate-300">
        <NavLink to="/" className="px-5 pt-6 pb-8">
          <div className="text-lg font-semibold text-white">TriageSim</div>
          <div className="text-xs text-slate-400">LLM triage testbed</div>
          {health?.demo && <div className="mt-3 rounded-md bg-amber-400 px-2 py-1 text-center text-xs font-bold text-amber-950">DEMO · invented data</div>}
        </NavLink>
        <nav className="flex-1 space-y-1 px-3">
          {STEPS.map((s) => (
            <NavLink key={s.to} to={s.to}
              className={({ isActive }) => `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
                isActive ? "bg-slate-800 text-white" : "hover:bg-slate-800/60 hover:text-white"}`}>
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-700 text-xs font-semibold text-slate-200">{s.n}</span>
              {s.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800 px-5 py-4 text-xs">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${health?.ollama.reachable ? "bg-emerald-400" : "bg-rose-400"}`} />
            {health?.ollama.reachable ? `Ollama ${health.ollama.version}`
              : <NavLink to="/models" className="underline">{health?.ollama.installed ? "Ollama not running" : "Ollama not installed"}</NavLink>}
          </div>
          <div className="mt-1 text-slate-500">Version {health?.version ?? "…"} · runs on this computer</div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/data" element={<Data />} />
          <Route path="/cohorts" element={<Cohorts />} />
          <Route path="/cohorts/:name" element={<CohortDetail />} />
          <Route path="/models" element={<Models />} />
          <Route path="/experiments/new" element={<NewExperiment />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:name" element={<RunDetail />} />
        </Routes>
      </main>
    </div>
  );
}
