import { useState, type FormEvent } from "react";
import { ApiError } from "../api/client";
import { useAuth } from "./AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Incorrect username or password."
          : `Sign-in failed: ${err instanceof Error ? err.message : "unknown error"}`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="card login-card stack" onSubmit={submit} aria-labelledby="login-title">
        <div className="row" style={{ gap: 12 }}>
          <svg width="40" height="40" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#256abf" />
            <g fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
              <path d="M16 15V28M16 15L16 4M16 15L6.5 20.5M16 15L25.5 20.5" />
            </g>
            <circle cx="16" cy="15" r="2.4" fill="#fff" />
          </svg>
          <div>
            <h1 id="login-title">Wind PdM Console</h1>
            <div className="subtle">Predictive maintenance for wind fleets</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="username">Username</label>
          <input
            id="username"
            className="input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && (
          <div className="banner error" role="alert" style={{ margin: 0 }}>
            {error}
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy} style={{ justifyContent: "center", height: 36 }}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="subtle" style={{ margin: 0 }}>
          Accounts are issued by your platform administrator. Every sign-in is recorded in the audit log.
        </p>
      </form>
    </div>
  );
}
