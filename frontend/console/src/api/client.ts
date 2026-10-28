// Thin fetch wrapper for the Platform API (same origin, under /api). The bearer token is
// kept in sessionStorage: it ends with the browser tab and is never written to disk.

const TOKEN_KEY = "wtpdm.token";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let onUnauthorized: (() => void) | null = null;

export const session = {
  token(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null) {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // storage blocked: the session lasts until reload
    }
  },
  onUnauthorized(handler: (() => void) | null) {
    onUnauthorized = handler;
  },
};

export type Query = Record<string, string | number | boolean | null | undefined | string[]>;

export function queryString(params: Query = {}): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => qs.append(key, v));
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

/** FastAPI errors carry `detail` as a string, or as a list of validation errors. */
export function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail))
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
        .filter(Boolean)
        .join("; ");
  }
  return fallback;
}

async function request<T>(method: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = session.token();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`/api${path}`, { ...init, method, headers });
  if (res.status === 401 && token) onUnauthorized?.();
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // not JSON (e.g. a proxy error page)
    }
    throw new ApiError(res.status, errorMessage(body, `${res.status} ${res.statusText}`));
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: Query) => request<T>("GET", path + queryString(params)),
  post: <T>(path: string, body?: unknown) =>
    request<T>("POST", path, {
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>("PATCH", path, {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  form: <T>(path: string, fields: Record<string, string>) =>
    request<T>("POST", path, { body: new URLSearchParams(fields) }),
};
