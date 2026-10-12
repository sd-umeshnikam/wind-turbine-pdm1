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
  fault_to_downtime_hours: WarningTimeStats & {
    n_events_computable: number;
    n_anomaly_events_total: number;
  };
}

// Hours from a fault's logged start to the turbine's first downtime; null when no event qualified.
export interface WarningTimeStats {
  median_hours: number | null;
  p25_hours: number | null;
  p75_hours: number | null;
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
    fault_to_downtime_hours: WarningTimeStats;
    fault_to_downtime_coverage: string;
  };
  data_quality_note: string;
}
