import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, session } from "../api/client";
import type { Role, TokenResponse, User } from "../api/types";

const RANK: Record<Role, number> = { viewer: 0, engineer: 1, admin: 2 };

export const hasRole = (user: User | null, role: Role) => !!user && RANK[user.role] >= RANK[role];

interface AuthValue {
  user: User | null;
  /** The user's previous visit, captured at sign-in (before this visit updates it). */
  previousVisit: string | null;
  loading: boolean;
  login(username: string, password: string): Promise<void>;
  logout(): void;
  can(role: Role): boolean;
}

const AuthContext = createContext<AuthValue | null>(null);
const PREVIOUS_VISIT_KEY = "wtpdm.previousVisit";

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => !!session.token());
  const [previousVisit, setPreviousVisit] = useState<string | null>(() => {
    try {
      return sessionStorage.getItem(PREVIOUS_VISIT_KEY);
    } catch {
      return null;
    }
  });

  const clear = useCallback(() => {
    session.set(null);
    setUser(null);
    qc.clear();
  }, [qc]);

  useEffect(() => {
    session.onUnauthorized(clear);
    if (session.token()) {
      api
        .get<User>("/auth/me")
        .then(setUser)
        .catch(clear)
        .finally(() => setLoading(false));
    }
    return () => session.onUnauthorized(null);
  }, [clear]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.form<TokenResponse>("/auth/token", { username, password });
    session.set(res.access_token);
    const previous = res.user.last_seen_at;
    try {
      if (previous) sessionStorage.setItem(PREVIOUS_VISIT_KEY, previous);
      else sessionStorage.removeItem(PREVIOUS_VISIT_KEY);
    } catch {
      // storage blocked
    }
    setPreviousVisit(previous);
    setUser(res.user);
    // This visit becomes the reference for the next one's "since your last visit".
    void api.post("/auth/seen").catch(() => undefined);
  }, []);

  const logout = useCallback(() => {
    void api
      .post("/auth/seen")
      .catch(() => undefined)
      .finally(clear);
  }, [clear]);

  const value = useMemo<AuthValue>(
    () => ({ user, previousVisit, loading, login, logout, can: (role) => hasRole(user, role) }),
    [user, previousVisit, loading, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
