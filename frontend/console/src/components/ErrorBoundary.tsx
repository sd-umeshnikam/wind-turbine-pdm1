// Crash containment: a rendering error shows a recoverable error state in place of the part
// of the console that failed (never a blank page), and every crash is reported to the API
// so it appears in the api logs.

import { Component, type ErrorInfo, type ReactNode } from "react";
import { api } from "../api/client";

const clip = (s: string | undefined, n: number) => (s ?? "").slice(0, n);

export function reportError(error: unknown, componentStack = "") {
  const e = error instanceof Error ? error : new Error(String(error));
  void api
    .post("/client-errors", {
      message: clip(`${e.name}: ${e.message}`, 500),
      stack: clip(`${e.stack ?? ""}\n${componentStack}`, 4000),
      path: clip(window.location.pathname, 300),
      user_agent: clip(navigator.userAgent, 300),
    })
    .catch(() => undefined); // signed out or API down: nothing more to do
}

/** Errors outside React rendering (event handlers, promises). */
export function reportUncaughtErrors() {
  window.addEventListener("error", (e) => reportError(e.error ?? e.message));
  window.addEventListener("unhandledrejection", (e) => reportError(e.reason));
}

interface Props {
  children: ReactNode;
  /** What failed, in the error title: "this page", "the assistant". */
  area?: string;
}

export class ErrorBoundary extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportError(error, info.componentStack ?? "");
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="state error" role="alert">
        <div className="state-title">Something went wrong in {this.props.area ?? "this page"}</div>
        <div>{error.message}</div>
        <div className="row" style={{ gap: 8, justifyContent: "center" }}>
          <button className="btn sm" onClick={() => this.setState({ error: null })}>
            Try again
          </button>
          <button className="btn sm" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    );
  }
}
