// Response shapes of the Platform API (wtpdm/api/schemas.py and the routers).

export type Role = "viewer" | "engineer" | "admin";
export type Severity = "low" | "medium" | "high" | "critical";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type FarmId = "A" | "B" | "C";

export interface User {
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface DirectoryEntry {
  username: string;
  display_name: string;
  role: Role;
}

// ---------------------------------------------------------------- fleet & turbines

export interface Replay {
  cursor_ts: string | null;
  cycle: number;
  position: number;
  total_rows: number;
  progress: number;
  source_event_id: number | null;
  operating_status: number | null;
  operating_status_label: string | null;
  updated_at: string | null;
}

export interface AlertBrief {
  id: string;
  severity: Severity;
  status: AlertStatus;
  title: string;
  component_code: string;
  subcomponent_code: string | null;
  condition_active: boolean;
  opened_at: string;
}

export interface TurbineSummary {
  id: string;
  farm_id: FarmId;
  name: string;
  health: number | null;
  alarm: boolean | null;
  worst_subcomponent: string | null;
  components: Record<string, number>;
  model_version: string | null;
  replay: Replay | null;
  active_alert: AlertBrief | null;
}

export interface FleetKpis {
  turbines: number;
  reporting: number;
  in_alarm: number;
  mean_health: number | null;
  active_alerts: Record<Severity, number>;
  unacknowledged: number;
}

export interface Fleet {
  kpis: FleetKpis;
  turbines: TurbineSummary[];
  replay_speed: number;
}

export interface Farm {
  id: FarmId;
  name: string;
  description: string | null;
  turbines: number;
  sensors: number;
  events: Record<string, number>;
  champion: string | null;
  active_alerts: number;
}

export interface Sensor {
  code: string;
  description: string;
  unit: string | null;
  role: "monitored" | "condition" | "other";
  subcomponent_code: string | null;
  condition_kind: string | null;
}

export interface SubpartHealth {
  code: string;
  name: string;
  health: number | null;
  residual_z: number | null;
  ts: string | null;
  sensors: Sensor[];
}

export interface ComponentHealth {
  code: string;
  name: string;
  health: number | null;
  subparts: SubpartHealth[];
}

export interface TurbineDetail extends TurbineSummary {
  asset_id: number;
  anomaly_score: number | null;
  components_tree: ComponentHealth[];
}

export interface SeriesPoint {
  ts: string;
  avg: number | null;
  min: number | null;
  max: number | null;
}

export interface Window {
  start: string;
  end: string;
  bucket_seconds: number;
}

export interface HealthSeries {
  subcomponent: string;
  name: string;
  points: SeriesPoint[];
  alarm_ts: string[];
}

export interface HealthSeriesResponse {
  turbine_id: string;
  window: Window;
  series: HealthSeries[];
}

export interface SensorSeries {
  code: string;
  description: string;
  unit: string | null;
  points: SeriesPoint[];
}

export interface TelemetryResponse {
  turbine_id: string;
  window: Window;
  series: SensorSeries[];
}

export interface ExpectedPoint {
  ts: string;
  actual: number | null;
  expected: number | null;
  residual_z: number | null;
}

export interface ExpectedResponse {
  turbine_id: string;
  sensor: Sensor;
  model_version: string;
  nbm_candidate: string;
  window: Window;
  points: ExpectedPoint[];
}

export interface ConditionReading {
  code: string;
  description: string;
  unit: string | null;
  kind: string;
  value: number | null;
  ts: string | null;
}

export interface Snapshot {
  turbine_id: string;
  cursor_ts: string | null;
  operating_status: number | null;
  operating_status_label: string | null;
  readings: ConditionReading[];
}

export interface CareEvent {
  id: number;
  farm_id: FarmId;
  source_event_id: number;
  turbine_id: string;
  label: "anomaly" | "normal";
  description: string | null;
  category: string | null;
  component_code: string | null;
  window_start: string;
  prediction_start: string;
  event_start: string;
  event_end: string;
  n_rows: number;
}

// ---------------------------------------------------------------- alerts

export interface Driver {
  z: number;
  sensor: string;
  description: string;
}

export interface Note {
  id: number;
  author: string;
  body: string;
  created_at: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  details: Record<string, unknown> | null;
}

export interface Alert {
  id: string;
  turbine_id: string;
  farm_id: FarmId | null;
  component_code: string;
  subcomponent_code: string | null;
  severity: Severity;
  status: AlertStatus;
  title: string;
  message: string;
  drivers: Driver[] | null;
  model_version: string | null;
  opened_at: string;
  updated_at: string;
  data_ts: string | null;
  last_data_ts: string | null;
  condition_active: boolean;
  cleared_at: string | null;
  assignee: string | null;
  acknowledged_by: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
}

export interface AlertDetail extends Alert {
  notes: Note[];
  audit: AuditEntry[];
}

export interface AlertPage {
  total: number;
  items: Alert[];
}

export interface AlertSummary {
  by_status: Record<AlertStatus, number>;
  by_severity: Record<Severity, number>;
  by_farm: Record<string, number>;
  unassigned: number;
}

// ---------------------------------------------------------------- MLOps

export type Metrics = Record<string, number>;

export interface ModelVersion {
  model: string;
  farm: FarmId;
  version: string;
  aliases: string[];
  gate: string | null;
  created_at: string;
  run_id: string;
  run_url: string;
  trigger: string | null;
  actor: string | null;
  data_version: string | null;
  selected_detector: string | null;
  metrics: Metrics;
}

export interface FarmModels {
  farm: FarmId;
  versions: ModelVersion[];
}

export type Row = Record<string, string | number | boolean | null>;

export interface Comparison {
  model: string;
  version: string;
  selected_detector: string | null;
  detectors: Row[];
  components: Row[];
  nbm: Row[];
  rul: Row[];
}

export interface CompareRow {
  metric: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  better: string | null;
}

export interface VersionCompare {
  model: string;
  a: ModelVersion;
  b: ModelVersion;
  metrics: CompareRow[];
}

export interface Deployment {
  id: number;
  model_name: string;
  version: string;
  alias: string;
  farm_id: FarmId;
  validation: string;
  metrics: Metrics | null;
  promoted_at: string;
  promoted_by: string;
}

export interface DriftRow {
  metric: string;
  feature: string | null;
  feature_description: string | null;
  value: number;
  threshold: number;
  breached: boolean;
  triggers_retrain: boolean;
}

export type DriftStatus = "ok" | "warning" | "drift" | "no_data";

export interface DriftSnapshot {
  farm_id: FarmId;
  checked_at: string | null;
  status: DriftStatus;
  rows: DriftRow[];
}

export interface DriftHistoryPoint {
  ts: string;
  value: number;
  threshold: number;
  breached: boolean;
}

export interface DriftHistory {
  farm: FarmId;
  metric: string;
  triggers_retrain: boolean;
  series: Record<string, DriftHistoryPoint[]>;
}

export interface DriftPolicy {
  interval_minutes: number;
  window_days: number;
  min_rows: number;
  metrics: Record<string, { threshold: number | string; triggers_retrain: boolean }>;
}

export interface RetrainJob {
  id: number;
  trigger: string;
  status: "queued" | "running" | "succeeded" | "failed";
  requested_by: string;
  scope: { farm?: string; reason?: string } | null;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: {
    run_id?: string;
    metrics?: Metrics;
    selected?: string;
    error?: string;
    registry?: {
      model: string;
      version: string;
      promoted: boolean;
      gate_reasons: string[];
      previous_champion_score: number | null;
    };
  } | null;
}

export interface RetrainSchedule {
  cron: string;
  timezone: string;
  next_run: string;
  drift_cooldown_hours: number;
  auto_promote: boolean;
  promotion_gate: { min_care_score_improvement: number; false_alarms: string };
}

// ---------------------------------------------------------------- data

export interface Coverage {
  farms: FarmId[];
  subparts: { code: string; name: string; component: string }[];
  matrix: Record<string, Record<string, Record<string, number>>>;
}

export interface QualityRow {
  sensor: string;
  description: string | null;
  unit: string | null;
  rows: number;
  missing_pct: number;
  stuck_pct: number;
  out_of_range_pct: number;
}

export interface Quality {
  farm: FarmId;
  data_version: string;
  sensors: QualityRow[];
}

export interface ReplayTurbine extends Replay {
  turbine_id: string;
  farm_id: FarmId;
}

export interface ReplayStatus {
  mode: string;
  speed: number;
  tick_seconds: number;
  last_update: string | null;
  turbines: ReplayTurbine[];
}

export interface AuditPage {
  total: number;
  items: AuditEntry[];
}

// ---------------------------------------------------------------- assistant

export interface Citation {
  kind: string;
  label: string;
  ref: string;
  link: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: number | null;
  answer: string;
  blocked: boolean;
  reason: string | null;
  flags: string[];
  tools: { name: string; args: Record<string, unknown>; ok: boolean }[];
  citations: Citation[];
  suggestions: string[];
  suggestion_source: string;
  model: string | null;
  latency_ms: number;
}

export interface ChatContext {
  page?: string;
  turbine_id?: string;
  alert_id?: string;
}

export interface Insight {
  kind: string;
  tone: "critical" | "warning" | "good" | "info";
  title: string;
  detail: string;
  link: string | null;
}

export interface Insights {
  since: string;
  first_visit: boolean;
  generated_at: string;
  items: Insight[];
}

export interface FailureMode {
  id: string;
  mode: string;
  signals: string[];
  checks: string[];
  actions: string[];
}

export interface RecommendationItem {
  subcomponent: string;
  name: string;
  safety_relevant: boolean;
  evidence: { sensor?: string; description?: string; z?: number; health?: number; residual_z?: number | null }[];
  failure_modes: FailureMode[];
}

export interface Recommendation {
  scope: "alert" | "turbine";
  alert_id: string | null;
  turbine_id: string;
  severity: Severity | null;
  response: { window: string; posture: string } | null;
  items: RecommendationItem[];
  notes: string[];
  disclaimer: string;
  citations: string[];
}
