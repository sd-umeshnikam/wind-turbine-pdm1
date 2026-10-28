// Live updates over server-sent events (/api/stream). Each event invalidates the query
// area it affects, so open pages refetch real data; audit events also feed the activity
// list. EventSource cannot send headers, so the token goes in the query string (the API
// never logs query strings).

import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";
import { session } from "./client";
import type { AuditEntry } from "./types";

export type StreamState = "connecting" | "live" | "offline";

const MAX_ACTIVITY = 60;
const INVALIDATES: Record<string, string[][]> = {
  fleet: [["fleet"], ["turbine"], ["replay"]],
  alert: [["alerts"], ["fleet"], ["turbine"]],
  model: [["models"], ["farms"]],
  retrain: [["retrain"], ["models"]],
  drift: [["drift"]],
  user: [["users"]],
};
const AUDIT_EVENTS = ["alert", "model", "retrain", "user", "auth"];

let state: StreamState = "offline";
let activity: AuditEntry[] = [];
let lastFleetAt: number | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export const useStreamState = () => useSyncExternalStore(subscribe, () => state);
export const useActivity = () => useSyncExternalStore(subscribe, () => activity);
export const useLastFleetAt = () => useSyncExternalStore(subscribe, () => lastFleetAt);

/** Keep one stream open while signed in; reconnects with backoff. */
export function useLiveStream(qc: QueryClient, enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      const token = session.token();
      if (!token || closed) return;
      state = "connecting";
      emit();
      source = new EventSource(`/api/stream?access_token=${encodeURIComponent(token)}`);
      source.addEventListener("hello", () => {
        attempt = 0;
        state = "live";
        emit();
      });
      for (const [event, keys] of Object.entries(INVALIDATES)) {
        source.addEventListener(event, (e) => {
          keys.forEach((queryKey) => void qc.invalidateQueries({ queryKey }));
          if (event === "fleet") lastFleetAt = Date.now();
          if (AUDIT_EVENTS.includes(event)) {
            try {
              const entry = JSON.parse((e as MessageEvent<string>).data) as AuditEntry;
              activity = [entry, ...activity.filter((a) => a.id !== entry.id)].slice(0, MAX_ACTIVITY);
            } catch {
              // malformed event: ignore
            }
          }
          emit();
        });
      }
      source.onerror = () => {
        source?.close();
        state = "offline";
        emit();
        if (closed) return;
        attempt += 1;
        retry = setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempt));
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      source?.close();
      state = "offline";
      emit();
    };
  }, [qc, enabled]);
}
