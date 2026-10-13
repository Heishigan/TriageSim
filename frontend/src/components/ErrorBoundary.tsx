import { Component, type ReactNode } from "react";

/** Send a browser error to the terminal window, so it can be read and reported. */
export function reportError(message: string, stack = "") {
  fetch("/api/client-error", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, stack, where: window.location.pathname }),
  }).catch(() => undefined);
}

window.addEventListener("error", (e) => reportError(e.message, e.error?.stack ?? ""));
window.addEventListener("unhandledrejection", (e) => reportError(String(e.reason), e.reason?.stack ?? ""));

/** Instead of a blank page, show what went wrong (and log it in the terminal). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    reportError(error.message, error.stack ?? "");
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-3xl px-8 py-10">
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-rose-800">
          <h1 className="text-lg font-semibold">This page ran into a problem</h1>
          <p className="mt-2 text-sm">The error is also written in the TriageSim terminal window. Please send it to the developer.</p>
          <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded bg-white p-3 text-xs">{this.state.error.message}{"\n"}{this.state.error.stack}</pre>
          <button className="mt-4 rounded-lg bg-rose-600 px-3.5 py-2 text-sm font-medium text-white" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}
