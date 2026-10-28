// TanStack Query hooks over the Platform API. Query keys start with the area name so the
// live stream can invalidate a whole area (see stream.ts).

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Query } from "./client";
import type {
  AlertDetail,
  ChatContext,
  ChatResponse,
  Insights,
  Recommendation,
  AlertPage,
  AlertSummary,
  AuditPage,
  CareEvent,
  Comparison,
  Coverage,
  Deployment,
  DirectoryEntry,
  DriftHistory,
  DriftPolicy,
  DriftSnapshot,
  ExpectedResponse,
  Farm,
  FarmModels,
  Fleet,
  HealthSeriesResponse,
  Quality,
  ReplayStatus,
  RetrainJob,
  RetrainSchedule,
  Role,
  Sensor,
  Snapshot,
  TelemetryResponse,
  TurbineDetail,
  User,
  VersionCompare,
} from "./types";

const LIVE = 15_000; // fallback polling when the stream is down; the stream refreshes sooner

// ---------------------------------------------------------------- fleet & turbines

export const useFleet = (farm?: string) =>
  useQuery({
    queryKey: ["fleet", farm ?? "all"],
    queryFn: () => api.get<Fleet>("/fleet", { farm }),
    refetchInterval: LIVE,
  });

export const useFarms = () => useQuery({ queryKey: ["farms"], queryFn: () => api.get<Farm[]>("/farms") });

export const useTurbine = (id: string) =>
  useQuery({
    queryKey: ["turbine", id],
    queryFn: () => api.get<TurbineDetail>(`/turbines/${id}`),
    refetchInterval: LIVE,
  });

export interface Range {
  from?: string;
  to?: string;
  points?: number;
}

export const useHealthTrend = (id: string, subcomponents: string[], range: Range) =>
  useQuery({
    queryKey: ["turbine", id, "health", subcomponents.join(","), range],
    queryFn: () =>
      api.get<HealthSeriesResponse>(`/turbines/${id}/health`, {
        subcomponents: subcomponents.join(","),
        ...range,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });

export const useTelemetry = (id: string, sensors: string[], range: Range) =>
  useQuery({
    queryKey: ["turbine", id, "telemetry", sensors.join(","), range],
    queryFn: () =>
      api.get<TelemetryResponse>(`/turbines/${id}/telemetry`, { sensors: sensors.join(","), ...range }),
    enabled: sensors.length > 0,
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });

export const useExpected = (id: string, sensor: string | null, range: Range) =>
  useQuery({
    queryKey: ["turbine", id, "expected", sensor, range],
    queryFn: () => api.get<ExpectedResponse>(`/turbines/${id}/expected`, { sensor, ...range }),
    enabled: !!sensor,
    placeholderData: keepPreviousData,
    retry: false,
  });

export const useSnapshot = (id: string) =>
  useQuery({
    queryKey: ["turbine", id, "snapshot"],
    queryFn: () => api.get<Snapshot>(`/turbines/${id}/snapshot`),
    refetchInterval: 10_000,
  });

export const useTurbineEvents = (id: string) =>
  useQuery({
    queryKey: ["turbine", id, "events"],
    queryFn: () => api.get<CareEvent[]>(`/turbines/${id}/events`),
  });

// ---------------------------------------------------------------- alerts

export const useAlerts = (filters: Query) =>
  useQuery({
    queryKey: ["alerts", "list", filters],
    queryFn: () => api.get<AlertPage>("/alerts", filters),
    placeholderData: keepPreviousData,
    refetchInterval: LIVE,
  });

export const useAlertSummary = () =>
  useQuery({
    queryKey: ["alerts", "summary"],
    queryFn: () => api.get<AlertSummary>("/alerts/summary"),
    refetchInterval: LIVE,
  });

export const useAlert = (id: string | null) =>
  useQuery({
    queryKey: ["alerts", "detail", id],
    queryFn: () => api.get<AlertDetail>(`/alerts/${id}`),
    enabled: !!id,
  });

export const useDirectory = (enabled: boolean) =>
  useQuery({
    queryKey: ["users", "directory"],
    queryFn: () => api.get<DirectoryEntry[]>("/users/directory"),
    enabled,
    staleTime: 60_000,
  });

export type AlertAction =
  | { kind: "acknowledge"; note?: string }
  | { kind: "assign"; assignee: string | null }
  | { kind: "resolve"; resolution: string }
  | { kind: "note"; body: string };

export function useAlertAction(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: AlertAction) => {
      switch (action.kind) {
        case "acknowledge":
          return api.post<AlertDetail>(`/alerts/${id}/acknowledge`, { note: action.note || null });
        case "assign":
          return api.post<AlertDetail>(`/alerts/${id}/assign`, { assignee: action.assignee });
        case "resolve":
          return api.post<AlertDetail>(`/alerts/${id}/resolve`, { resolution: action.resolution });
        case "note":
          return api.post<AlertDetail>(`/alerts/${id}/notes`, { body: action.body });
      }
    },
    onSuccess: (detail) => {
      qc.setQueryData(["alerts", "detail", id], detail);
      void qc.invalidateQueries({ queryKey: ["alerts"] });
      void qc.invalidateQueries({ queryKey: ["fleet"] });
    },
  });
}

// ---------------------------------------------------------------- models, drift, retraining

export const useModels = () =>
  useQuery({ queryKey: ["models", "list"], queryFn: () => api.get<FarmModels[]>("/models") });

export const useComparison = (farm: string, version: string | null) =>
  useQuery({
    queryKey: ["models", "comparison", farm, version],
    queryFn: () => api.get<Comparison>(`/models/${farm}/versions/${version}/comparison`),
    enabled: !!version,
    staleTime: Infinity, // a finished training run never changes
  });

export const useModelCard = (farm: string, version: string | null) =>
  useQuery({
    queryKey: ["models", "card", farm, version],
    queryFn: () => api.get<string>(`/models/${farm}/versions/${version}/card`),
    enabled: !!version,
    staleTime: Infinity,
  });

export const useVersionCompare = (farm: string, a: string | null, b: string | null) =>
  useQuery({
    queryKey: ["models", "compare", farm, a, b],
    queryFn: () => api.get<VersionCompare>(`/models/${farm}/compare`, { a, b }),
    enabled: !!a && !!b && a !== b,
  });

export const useDeployments = (farm?: string) =>
  useQuery({
    queryKey: ["models", "deployments", farm ?? "all"],
    queryFn: () => api.get<Deployment[]>("/models/deployments", { farm }),
  });

export function useApprove(farm: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (version: string) => api.post(`/models/${farm}/versions/${version}/approve`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export const useDrift = () =>
  useQuery({ queryKey: ["drift", "status"], queryFn: () => api.get<DriftSnapshot[]>("/drift"), refetchInterval: 60_000 });

export const useDriftHistory = (farm: string, metric: string, feature?: string) =>
  useQuery({
    queryKey: ["drift", "history", farm, metric, feature ?? ""],
    queryFn: () => api.get<DriftHistory>("/drift/history", { farm, metric, feature }),
  });

export const useDriftPolicy = () =>
  useQuery({ queryKey: ["drift", "policy"], queryFn: () => api.get<DriftPolicy>("/drift/policy"), staleTime: Infinity });

export const useRetrainJobs = (farm?: string) =>
  useQuery({
    queryKey: ["retrain", "jobs", farm ?? "all"],
    queryFn: () => api.get<RetrainJob[]>("/retrain/jobs", { farm }),
    refetchInterval: 30_000,
  });

export const useRetrainSchedule = () =>
  useQuery({ queryKey: ["retrain", "schedule"], queryFn: () => api.get<RetrainSchedule>("/retrain/schedule") });

export function useRequestRetrain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { farm: string; reason: string }) => api.post<RetrainJob>("/retrain/jobs", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["retrain"] }),
  });
}

// ---------------------------------------------------------------- data & admin

export const useSensors = (farm: string, role?: string) =>
  useQuery({
    queryKey: ["data", "sensors", farm, role ?? ""],
    queryFn: () => api.get<Sensor[]>("/data/sensors", { farm, role }),
    staleTime: Infinity,
  });

export const useCoverage = () =>
  useQuery({ queryKey: ["data", "coverage"], queryFn: () => api.get<Coverage>("/data/coverage"), staleTime: Infinity });

export const useQuality = (farm: string) =>
  useQuery({
    queryKey: ["data", "quality", farm],
    queryFn: () => api.get<Quality>("/data/quality", { farm }),
    staleTime: Infinity,
  });

export const useEvents = (farm?: string) =>
  useQuery({
    queryKey: ["data", "events", farm ?? "all"],
    queryFn: () => api.get<CareEvent[]>("/data/events", { farm }),
    staleTime: Infinity,
  });

export const useReplay = () =>
  useQuery({ queryKey: ["replay"], queryFn: () => api.get<ReplayStatus>("/replay"), refetchInterval: 10_000 });

export const useAudit = (filters: Query, enabled: boolean) =>
  useQuery({
    queryKey: ["audit", filters],
    queryFn: () => api.get<AuditPage>("/audit", filters),
    enabled,
    placeholderData: keepPreviousData,
  });

export const useUsers = (enabled: boolean) =>
  useQuery({ queryKey: ["users", "list"], queryFn: () => api.get<User[]>("/users"), enabled });

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; display_name: string; password: string; role: Role }) =>
      api.post<User>("/users", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ username, ...body }: { username: string } & Partial<Omit<User, "username">> & { password?: string }) =>
      api.patch<User>(`/users/${username}`, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

// ---------------------------------------------------------------- assistant

export const useAssistantStatus = () =>
  useQuery({
    queryKey: ["assistant", "status"],
    queryFn: () => api.get<{ available: boolean; model: string | null }>("/assistant/status"),
    staleTime: 60_000,
  });

export const useStarters = (context: ChatContext) =>
  useQuery({
    queryKey: ["assistant", "starters", context],
    queryFn: () => api.get<{ suggestions: string[] }>("/assistant/suggestions", { ...context }),
    staleTime: 60_000,
  });

export const useInsights = (since: string | null) =>
  useQuery({
    queryKey: ["assistant", "insights", since],
    queryFn: () => api.get<Insights>("/assistant/insights", { since }),
    refetchInterval: 60_000,
  });

export const useRecommendation = (params: { alert_id?: string; turbine_id?: string }, enabled = true) =>
  useQuery({
    queryKey: ["assistant", "recommendation", params],
    queryFn: () => api.get<Recommendation>("/assistant/recommendations", params),
    enabled,
  });

export const useChat = () =>
  useMutation({
    mutationFn: (body: { message: string; conversation_id?: string | null; context?: ChatContext }) =>
      api.post<ChatResponse>("/assistant/chat", body),
  });

export const useFeedback = () =>
  useMutation({
    mutationFn: ({ id, rating }: { id: number; rating: 1 | -1 }) => api.post(`/assistant/messages/${id}/feedback`, { rating }),
  });
