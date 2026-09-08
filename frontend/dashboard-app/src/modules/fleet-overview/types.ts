// Mirrors eda/outputs/fleet_summary.json exactly - see that file's
// data_quality_note: turbine counts are distinct asset_id values per farm,
// not dataset file counts.
export interface FarmSummary {
  label: string;
  n_turbines: number;
  n_event_files: number;
  n_anomaly_events: number;
  n_normal_events: number;
  anomaly_count_by_category: Record<string, number>;
  lead_time_hours: {
    n_events_computable: number;
    n_anomaly_events_total: number;
    avg_hours: number | null;
  };
}

export interface FleetSummary {
  farms: Record<string, FarmSummary>;
  fleet_totals: {
    total_turbines: number;
    total_event_files: number;
    total_anomaly_events: number;
    total_normal_events: number;
    anomaly_count_by_category: Record<string, number>;
  };
  headline_kpis: {
    total_anomaly_events: number;
    most_common_fault_category_including_other: string;
    most_common_named_fault_category: string;
    avg_derated_or_idle_to_downtime_lead_time_hours: number;
    lead_time_sample_coverage: string;
  };
  data_quality_note: string;
}
