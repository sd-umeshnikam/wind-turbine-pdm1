"""Generates docs/deliverables/Domain_Expert_Briefing.docx.

Audience: wind turbine domain experts (O&M / reliability engineers) who know turbines
deeply but want to evaluate the platform's data-science approach on its technical
merits. Every figure is pulled from eda/outputs/ - nothing here is illustrative, and
limitations are reported as found, not smoothed over.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _data as data
import _docx_style as s

OUT_PATH = Path(__file__).resolve().parents[1] / "Domain_Expert_Briefing.docx"


def build() -> None:
    fs = data.fleet_summary()
    dq = data.data_quality()
    events = data.events_categorized()
    total_rows = data.total_rows(dq)

    doc = s.new_document()

    s.add_title_page(
        doc,
        "Wind Turbine Predictive Maintenance Platform",
        "Technical Briefing for Domain Experts (O&M / Reliability Engineering)",
        [
            "Prepared by: Data Engineering & Data Science Team",
            f"Date: {datetime.date.today().isoformat()}",
            "Audience: Wind Turbine Domain Experts / O&M Engineers",
            "Classification: Internal",
        ],
    )

    s.add_heading(doc, "In This Briefing", 1)
    s.add_bullets(doc, [
        "Purpose, scope, and the real dataset this platform is built and validated against",
        "The fault taxonomy - derived from real maintenance logs, not assumed",
        "Detection methodology and physical rationale per asset, with real evidence charts",
        "The machine learning approach: classification, RUL, and trend forecasting",
        "Validation, data quality, and honest limitations",
        "How this complements existing SCADA alarms and CMMS workflows",
    ])
    s.add_page_break(doc)

    # 1. Purpose & scope -----------------------------------------------------
    s.add_heading(doc, "1. Purpose, Scope & the Real Dataset", 1)
    s.add_body(doc,
        "This platform turns 10-minute SCADA averages - the same data class most turbines "
        "already produce - into three outputs per component: fault classification (which "
        "component, which failure mode), Remaining Useful Life (RUL) estimation, and health "
        "trend forecasting. Target components today: Gearbox, Hydraulics, Pitch System, "
        "Generator, Transformer, Rotor Brake, and Bearing (via vibration analysis). The "
        "method is designed to extend to further components (Yaw, Converter, "
        "PLC/communications) as more labeled failure history becomes available."
    )
    s.add_body(doc,
        "It was built and validated against the public wind-turbine SCADA benchmark "
        "dataset - three real wind farms, not synthetic data:"
    )
    s.add_table(
        doc,
        ["Farm", "Type", "Turbines", "Sensors/file", "Total rows", "Anomaly / Normal events"],
        [
            ["A", "Onshore, Portugal (EDP)", str(fs["farms"]["A"]["n_turbines"]),
             str(dq["A"]["n_columns"]), f'{dq["A"]["n_rows_total"]:,}',
             f'{fs["farms"]["A"]["n_anomaly_events"]} / {fs["farms"]["A"]["n_normal_events"]}'],
            ["B", "Offshore, Germany (anonymized)", str(fs["farms"]["B"]["n_turbines"]),
             str(dq["B"]["n_columns"]), f'{dq["B"]["n_rows_total"]:,}',
             f'{fs["farms"]["B"]["n_anomaly_events"]} / {fs["farms"]["B"]["n_normal_events"]}'],
            ["C", "Offshore, Germany (anonymized)", str(fs["farms"]["C"]["n_turbines"]),
             str(dq["C"]["n_columns"]), f'{dq["C"]["n_rows_total"]:,}',
             f'{fs["farms"]["C"]["n_anomaly_events"]} / {fs["farms"]["C"]["n_normal_events"]}'],
            ["Total", "-", "36", "-", f"{total_rows:,}",
             f'{fs["fleet_totals"]["total_anomaly_events"]} / {fs["fleet_totals"]["total_normal_events"]}'],
        ],
        widths=[0.6, 2.1, 0.9, 1.0, 1.1, 1.5],
    )
    s.add_callout(doc, "NOTE",
        "Farm C is offshore with 3-axis independent pitch control, full hydraulics, and "
        "water cooling - by far the richest instrumentation of the three, which is why most "
        "of the evidence charts in §3 are drawn from it. Farm B's sensor names are "
        "anonymized (sensor_N) in all three farms, but sensor *descriptions* remain "
        "meaningful - all component matching in this platform is done against the "
        "description text, never the raw column name.", kind="note")

    # 2. Fault taxonomy -------------------------------------------------------
    s.add_heading(doc, "2. Fault Taxonomy Derived From Real Maintenance Logs", 1)
    s.add_body(doc,
        "Rather than assume a generic failure-mode list, all 44 real anomaly events' "
        "free-text maintenance descriptions were keyword-classified into component "
        "categories (English + German, since Farm B/C's operators write in both). Full "
        "category list, fleet-wide:"
    )
    cat = fs["fleet_totals"]["anomaly_count_by_category"]
    s.add_table(doc, ["Category", "Count"], [[k, str(v)] for k, v in cat.items()],
                widths=[3.0, 1.0])
    s.add_callout(doc, "HONEST FINDING",
        "Farm B splits cleanly into two real issue modes: 3 of its 6 anomaly events are "
        "genuine main/rotor bearing failures (\"Rotor Bearing 2 - Damage\", main-bearing "
        "standstill), now captured by the Bearing category specifically because Farm B "
        "carries real vibration sensors (see §3) that let this taxonomy extend to cover "
        "them (see the Bearing subsection of §3 for the evidence). The remaining 3 (\"high "
        "temperature\" x3) stay in \"Other/unclassified\" - generic alarms with no "
        "component-specific keyword to match, a real finding about this farm's "
        "maintenance-log detail level, not a taxonomy gap.", kind="warning")

    # 3. Detection methodology -------------------------------------------------
    s.add_page_break(doc)
    s.add_heading(doc, "3. Detection Methodology & Physical Rationale per Asset", 1)
    s.add_body(doc,
        "Detection never relies on a single reading. Rolling 1h/6h/24h mean AND standard "
        "deviation are computed per sensor group (a component running unusually smoothly, "
        "or unusually erratically, is as meaningful a signal as an absolute value shift). "
        "Sensors are resolved per farm by keyword-matching each farm's own "
        "feature_description.csv, not by fixed column name - the same method that already "
        "reconciles Farm A/B/C's completely incompatible schemas (86 / 257 / 957 columns)."
    )

    def asset_section(title, sensors_used, rationale, chart_file, chart_caption, evidence_text, caveat=None):
        s.add_heading(doc, title, 2)
        s.add_body(doc, f"Sensors used: {sensors_used}", italic=True)
        s.add_body(doc, rationale)
        s.add_chart(doc, chart_file, chart_caption)
        s.add_body(doc, evidence_text)
        if caveat:
            s.add_callout(doc, "CAVEAT", caveat, kind="warning")

    asset_section(
        "Gearbox",
        "oil temperature, oil pressure, high-speed-shaft bearing temperature",
        "A gearbox converts low-speed, high-torque rotor motion to high-speed generator "
        "input through meshing gears under constant load. Wear, misalignment, or oil "
        "breakdown show up first as friction (heat) and lubrication irregularity "
        "(pressure), before a gear tooth actually breaks.",
        "degradation_trend_C_gearbox_12.png",
        'Wind Farm C, event 12 ("Oil level error, two-pump mode + Oil Leakage Gear Oil '
        'Supply...") - gearbox oil pressure.',
        "Oil pressure runs at a visibly higher and far more erratic level (frequent sharp "
        "drop-outs) than the baseline's low-noise band across the entire ~23-day window - "
        "consistent with the \"two-pump mode\"/\"oil leakage\" wording in the real event "
        "description. The erratic-pressure signature, not just an average shift, is why "
        "rolling standard deviation is tracked alongside rolling mean.",
    )

    asset_section(
        "Hydraulics",
        "hydraulic oil tank temperature, oil level, pump pressure",
        "The hydraulic system actuates pitch and braking. A leak, failing pump, or "
        "degrading accumulator makes the pump work harder and/or lose pressure, showing up "
        "as sustained elevated oil temperature or abnormal pressure well before the system "
        "fails to actuate.",
        "degradation_trend_A_hydraulics_73.png",
        'Wind Farm A, event 73 ("Hydraulic group") - hydraulic oil temperature.',
        "The cleanest signal found in the entire EDA: oil temperature sits persistently "
        "~10-15°C above the normal baseline for the entire pre-fault window shown, not just "
        "near event_start - a stable, early, sustained offset rather than a last-minute "
        "spike.",
    )

    asset_section(
        "Pitch System",
        "per-axis pitch motor temperature, axis cooling-element temperature, pitch angle",
        "Each blade's pitch axis has its own motor, encoder, and (in Farm C's 3-axis "
        "independent design) its own cooling and control electronics. A failing axis motor "
        "or control card draws abnormal current and runs hot well before the axis stops "
        "responding (\"not-ready-to-operate\").",
        "degradation_trend_C_pitch_91.png",
        'Wind Farm C, event 91 ("23020 : Axis 3 not ready-to-operate") - Axis 3 cooling '
        "element and Axis 1 motor temperature.",
        "The rule-based sensor pick (no hand-curation) landed on Axis 3's own cooling "
        "temperature - the exact axis named in the real fault text - running ~5-10°C above "
        "baseline for most of the pre-fault window. Axis 1 motor temperature shows a "
        "similar sustained elevation, pointing to a genuine multi-day thermal precursor "
        "rather than an instantaneous trip.",
    )

    asset_section(
        "Generator",
        "Drive-End / Non-Drive-End bearing temperature, stator winding temperature, "
        "cooling-air-inlet temperature",
        "Generator bearings and windings are what actually wear/degrade under continuous "
        "rotation and electrical load; bearing wear raises friction (temperature), winding "
        "insulation breakdown raises electrical resistance (also temperature).",
        "degradation_trend_A_generator_40.png",
        'Wind Farm A, event 40 ("Generator bearing failure") - Drive-End / Non-Drive-End '
        "bearing temperature.",
        "The one case in this whole analysis where the anomaly runs cooler and less "
        "variable than baseline for most of the window - read together with the fault, "
        "more consistent with the turbine already being throttled back (derated) in "
        "response to an early symptom than with unchecked overheating.",
        caveat="The Non-Drive-End sensor is pinned at a flat ~204 for extended stretches "
               "late in the window - almost certainly a sensor fault/dropout code, not a "
               "real physical reading. A production feature pipeline needs an explicit "
               "implausible-value filter (per-sensor plausible range from "
               "feature_description.csv's unit field), not just a missingness check - a "
               "stuck-at-a-constant value is not \"missing\" and will silently corrupt a "
               "rolling mean/std feature if untreated.",
    )

    asset_section(
        "Transformer",
        "per-phase or per-unit oil/winding temperature (granularity differs by farm)",
        "Transformer oil is both the coolant and the electrical insulator; insulation "
        "degradation and internal electrical faults manifest as abnormal, sustained "
        "temperature rise or abnormal thermal cycling, since oil temperature directly "
        "tracks internal heat generation.",
        "degradation_trend_C_transformer_67.png",
        'Wind Farm C, event 67 ("overpressure on the main transformer") - main transformer '
        "oil temperature.",
        "One of the longest, cleanest early-warning offsets in the whole dataset: oil "
        "temperature runs a sustained ~10-15°C above baseline for essentially the entire "
        "~58-day window. Note: of the two oil sensors profiled for this event, only this "
        "one is discriminative - the other (\"EB transformer\", a different bank) tracks "
        "the baseline closely and would be down-weighted in a production feature set. "
        "Separately, Farm A's transformer-failure event (68) shows a different precursor "
        "pattern worth knowing: reduced day/night thermal cycling during the officially "
        "logged window, then a clear thermal-runaway climb in the week immediately after "
        "the logged window ends - evidence that cycling pattern, not just absolute "
        "temperature, carries signal, and that monitoring should not stop the moment an "
        "official event window closes.",
    )

    asset_section(
        "Rotor Brake",
        "hydraulic brake-caliper pressure (per-caliper)",
        "The rotor brake is hydraulically actuated. Anything disrupting its hydraulic "
        "supply or control power causes pressure to run low or erratic rather than holding "
        "its normal regulated band, before the brake fails to engage/disengage on command.",
        "degradation_trend_C_rotor_brake_18.png",
        'Wind Farm C, event 18 ("24VAC supply fault to rotor brake, then extended '
        'standstill") - brake caliper A/B hydraulic pressure.',
        "Both calipers run persistently lower than baseline across the ~10 days of "
        "available pre-fault data, with sharp transient dips layered on top - consistent "
        "with a control/power-supply fault causing degraded pressure regulation rather "
        "than a single instantaneous mechanical break.",
        caveat="Rotor-brake instrumentation exists only in Farm C - Farm A and B have no "
               "rotor-brake-specific sensor at all (confirmed by manual inspection of both "
               "farms' feature_description.csv, not a matching failure). This model is "
               "necessarily Farm-C-only until other farms add the instrumentation.",
    )

    asset_section(
        "Bearing (Vibration Analysis)",
        "broadband vibration amplitude - drive-train/tower accelerometers (Farm B, mG), "
        "nacelle accelerometers (Farm C, m/s²)",
        "This is the one component detected by a fundamentally different physical signal "
        "than every other asset above - motion/acceleration, not temperature or pressure. "
        "Bearing wear, imbalance, and looseness increase overall mechanical vibration "
        "energy transmitted through the structure; broadband vibration monitoring against "
        "a normal baseline is a decades-old, industry-standard condition-monitoring "
        "technique for rotating machinery (the same principle behind ISO 10816/20816 "
        "vibration severity zones), independent of knowing the exact fault mechanism.",
        "degradation_trend_B_vibration_27.png",
        'Wind Farm B, event 27 ("Turbine is stopped due to a main bearing damage") - '
        "drive-train (axis Z) and tower (axis X) vibration.",
        "An honest mixed result, not a clean win. Drive-train vibration shows no usable "
        "separation from baseline through the pre-fault window - both series sit near zero "
        "with matching transient spikes. Tower vibration is more useful but tells a "
        "different story than the cleanest charts above: during the ~61-day labeled event "
        "window itself it overlaps the baseline's noisy range closely - no early "
        "separation. The clear signal instead appears in the week immediately after the "
        "labeled window closes, where the anomaly turbine shows a sustained, "
        "densely-elevated vibration band while the baseline stays low over the same "
        "relative period - plausibly abnormal coast-down/restart dynamics from a damaged "
        "bearing, not a multi-week advance-warning precursor the way hydraulics and "
        "transformer showed above.",
        caveat="This dataset's vibration sensors are 10-minute statistical aggregates "
               "(avg/max/min/std of overall amplitude), not raw high-frequency waveform "
               "data. A production bearing/gearbox CMS typically samples accelerometers in "
               "the kHz range and applies FFT spectral analysis to isolate characteristic "
               "fault frequencies (ball-pass frequencies outer/inner race, cage/roller "
               "frequencies, gear-mesh frequency and sidebands) to identify which specific "
               "defect mode is present. This platform's vibration component supports "
               "broadband severity trending only - spectral fault-mode diagnosis would "
               "require raw-waveform capture this dataset does not contain, a documented v2 "
               "extension.",
    )

    # 4. ML approach -----------------------------------------------------------
    s.add_page_break(doc)
    s.add_heading(doc, "4. Machine Learning Approach", 1)
    s.add_table(
        doc,
        ["Problem", "Approach", "Rationale"],
        [
            ["Fault classification", "Multi-class LightGBM per component, trained on "
             "rolling Gold-layer features, MLflow-tracked (macro-F1)",
             "Gradient-boosted trees handle the mixed numeric feature set well and train "
             "fast enough to retrain per-component as new labeled events accumulate."],
            ["RUL estimation", "LightGBM quantile regression, P10/P50/P90 hours-to-failure",
             "A single point estimate is misleading for maintenance scheduling; the "
             "uncertainty band is shown in the dashboard alongside the P50, always."],
            ["Trend forecasting", "Classical (statsmodels ETS) per-asset health index, "
             "not deep learning",
             "Deliberately classical-first: only ~44 labeled anomaly events exist "
             "fleet-wide - nowhere near enough to trust a deep sequence model's "
             "extrapolation. Noted as a v2 upgrade path once more history accumulates."],
        ],
        widths=[1.4, 2.6, 2.6],
    )
    s.add_body(doc,
        "Feature engineering resolves each component's relevant sensors per farm via "
        "keyword match against that farm's feature_description.csv description column "
        "(not the anonymized sensor_name) - the same mechanism used for the taxonomy in "
        "§2 and the evidence charts in §3. RUL labels are computed as hours from each "
        "pre-event row back to that event's event_start, capped at a 720-hour (30-day) "
        "look-back horizon and deduplicated to the nearest upcoming anomaly event per row."
    )

    # 5. Validation & limitations -----------------------------------------------
    s.add_heading(doc, "5. Validation, Data Quality & Honest Limitations", 1)
    s.add_body(doc, "Data quality is genuinely strong across all three farms:")
    dq_rows = []
    for farm in ("A", "B", "C"):
        m = dq[farm]["missingness_summary"]
        dq_rows.append([
            farm, str(dq[farm]["n_columns"]),
            f'{m["always_populated_count"]}/{dq[farm]["n_columns"]} always populated',
            str(m["sparse_count"]),
        ])
    s.add_table(doc, ["Farm", "Columns", "Always populated", "Sparse (>5% missing) columns"],
                dq_rows, widths=[0.8, 1.0, 2.6, 2.2])
    s.add_body(doc,
        "Farm C's large \"mostly populated\" bucket (836 of 957 columns) is an artifact of "
        "the 5% bucketing threshold catching sub-0.02% gaps, not a real quality problem - "
        "the actual missing rate across every one of those columns tops out at 0.0136%."
    )
    s.add_callout(doc, "LIMITATION",
        "The \"derated/idle-to-downtime lead time\" KPI is only computable for "
        f'{fs["headline_kpis"]["lead_time_sample_coverage"]} fleet-wide - '
        "Farm A and Farm C never emit status_type_id 1 (derated) or 2 (idling) at all; "
        "only Farm B does, and even there never idling. status_type_id usage is not "
        "standardized across farms, and this platform reports that honestly rather than "
        "presenting a fleet-wide lead-time number built on 2 data points.", kind="warning")
    s.add_callout(doc, "LIMITATION",
        "Event timestamps are anonymized/shifted independently per turbine (observed years "
        "span ~2014-2029 across files) - never usable for cross-turbine or calendar-based "
        "seasonality analysis, only within-turbine relative timing and duration.",
        kind="warning")

    # 6. Complementing existing practice ----------------------------------------
    s.add_heading(doc, "6. How This Complements Existing SCADA Alarms & CMMS", 1)
    s.add_body(doc,
        "SCADA threshold alarms are reactive by design - they fire once a fixed setpoint is "
        "crossed, which several of the charts in §3 show happening well after a sustained "
        "trend shift was already visible. This platform is designed to extend the warning "
        "horizon on the same sensor stream, not replace the alarm system - both should run "
        "side by side."
    )
    s.add_body(doc,
        "A flagged component is only useful if it becomes a real maintenance action: the "
        "platform's architecture includes a relational store (assets ↔ work orders ↔ "
        "technicians) specifically so a fault classification or RUL estimate can route "
        "into an existing CMMS workflow rather than living only on a dashboard."
    )

    doc.save(str(OUT_PATH))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
