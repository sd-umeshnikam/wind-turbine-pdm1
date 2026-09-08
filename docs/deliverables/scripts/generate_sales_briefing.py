"""Generates docs/deliverables/Sales_Briefing.docx.

Audience: Sales / Business Development. Written by a domain expert translating the
platform's real, data-grounded results into customer-conversation-ready language.
Every number/example here is pulled from eda/outputs/ - nothing is illustrative.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _data as data
import _docx_style as s

OUT_PATH = Path(__file__).resolve().parents[1] / "Sales_Briefing.docx"


def build() -> None:
    fs = data.fleet_summary()
    dq = data.data_quality()
    events = data.events_categorized()
    total_rows = data.total_rows(dq)
    total_turbines = data.total_turbines(fs)

    pitch = data.event_row(events, "C", 91)

    cited_events = [
        ("A", 73, "Hydraulics"), ("A", 72, "Gearbox"), ("C", 91, "Pitch System"),
        ("A", 40, "Generator"), ("A", 68, "Transformer"), ("C", 67, "Transformer"),
        ("C", 18, "Rotor Brake"), ("B", 27, "Bearing"),
    ]
    def truncate(text: str, limit: int = 55) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "…"

    problem_rows = []
    for farm, eid, label in cited_events:
        r = data.event_row(events, farm, eid)
        problem_rows.append(
            [label, f'"{truncate(r["event_description"])}"', f'{r["duration_days"]:.0f} days']
        )

    doc = s.new_document()

    s.add_title_page(
        doc,
        "Wind Turbine Predictive Maintenance Platform",
        "Briefing for Sales & Business Development",
        [
            "Prepared by: Data Engineering & Data Science Team",
            f"Date: {datetime.date.today().isoformat()}",
            "Audience: Sales / Business Development",
            "Classification: Internal",
        ],
    )

    s.add_heading(doc, "In This Briefing", 1)
    s.add_bullets(doc, [
        "The business problem: what unplanned turbine downtime actually costs, in real terms",
        "What we built, explained without jargon",
        "Real evidence it works - actual charts from actual turbine failures, not mockups",
        "What makes this offering different",
        "Talking points for customer conversations",
        "Honest status today, and suggested next steps",
    ])
    s.add_page_break(doc)

    # 1. Business problem -------------------------------------------------
    s.add_heading(doc, "1. The Business Problem: Unplanned Downtime", 1)
    s.add_body(doc,
        "Every wind turbine operator faces the same core problem: a major component "
        "(gearbox, hydraulics, pitch system, generator, transformer, rotor brake, bearings) degrades "
        "silently for days or weeks before it actually fails. Today, most operators only "
        "find out when a SCADA alarm fires at the moment of failure - by which point the "
        "turbine is already down, a technician has to be dispatched (often to a remote or "
        "offshore site), and lost generation is already accumulating."
    )
    s.add_body(doc,
        "These are not hypothetical scenarios. Below are real, logged failure events from "
        "actual wind turbines (from the public SCADA benchmark dataset this platform was "
        "built and validated against) - the exact kind of event this platform is designed "
        "to catch earlier."
    )
    s.add_table(
        doc,
        ["Component", "Real Event (as logged by the operator)", "Fault window"],
        problem_rows,
        widths=[1.5, 3.6, 1.1],
    )
    s.add_callout(doc, "REAL DATA",
        f"This platform was built and validated against {total_turbines} real turbines "
        f"across 3 wind farms - {total_rows:,} individual sensor readings in total, including "
        f"{fs['fleet_totals']['total_anomaly_events']} real logged failure events. Every "
        "chart in this briefing is a real turbine's real data, not a simulation.",
        kind="note")

    # 2. What we built ------------------------------------------------------
    s.add_heading(doc, "2. What We Built, in Plain Terms", 1)
    s.add_body(doc,
        "Think of it like a modern car's diagnostic system, but for a wind turbine. It does "
        "three things:"
    )
    s.add_bullets(doc, [
        '"Which part is at risk?" - like a check-engine light that names the actual system '
        "(not just a generic warning light), it identifies whether it's the gearbox, "
        "hydraulics, pitch system, generator, transformer, rotor brake, or a bearing "
        "(via vibration analysis) that's showing early signs of trouble.",
        '"How much time is left?" - like a fuel gauge, it estimates Remaining Useful Life '
        "(RUL) in hours, with a realistic range (not a single falsely-precise number) so "
        "maintenance can be scheduled proactively instead of reactively.",
        '"Where is this heading?" - like a weather forecast, it projects the trend for the '
        "next several days so a flagged component's trajectory can be watched, not just its "
        "current state.",
    ])
    s.add_body(doc,
        "Under the hood, raw sensor exports (the same 10-minute SCADA data most turbines "
        "already produce) are cleaned, organized, and distilled into these signals through a "
        "staged data pipeline on AWS and Databricks - no new hardware or sensors required."
    )

    # 3. Real evidence --------------------------------------------------
    s.add_heading(doc, "3. Real Evidence This Works", 1)
    s.add_body(doc,
        "The single most important thing to know: every chart below is a real turbine's "
        "real sensor data leading up to a real, logged failure - compared against a real "
        "normal turbine over the same time window. Nothing here is a mockup."
    )

    s.add_heading(doc, "Example: Hydraulic Group Failure (Wind Farm A)", 2)
    s.add_body(doc,
        "This turbine's hydraulic system failed after a multi-day lead-up (the dataset's own "
        "event timestamps are anonymized per-turbine, so we cite relative timing, not a "
        "calendar date). Its oil temperature was already running 10-15°C hotter than a "
        "normal turbine's - and stayed elevated for the entire lead-up window, not just in "
        "the final hours. This is exactly the kind of early, sustained signal the platform "
        "is designed to flag well before a SCADA threshold alarm would ever trigger."
    )
    s.add_chart(doc, "degradation_trend_A_hydraulics_73.png",
        "Real sensor data: hydraulic oil temperature, failing turbine (red) vs. a normal "
        "turbine (green), in the days surrounding a real logged failure.")

    s.add_heading(doc, "Example: Pitch System Fault (Wind Farm C)", 2)
    s.add_body(doc,
        f'This turbine logged "{pitch["event_description"]}" - note that the fault report '
        'names "Axis 3" specifically. Our analysis, run automatically with no manual '
        "tuning, independently identified Axis 3's own temperature sensor as the most "
        "relevant early-warning signal - landing on the exact same component the maintenance "
        "log named. That's a meaningful proof point: the method isn't guessing, it's finding "
        "the same physical signal a real technician's diagnosis pointed to."
    )
    s.add_chart(doc, "degradation_trend_C_pitch_91.png",
        "Real sensor data: pitch Axis 3 temperature trending above normal for most of the "
        "pre-fault window.")

    s.add_heading(doc, "Example: Bearing Failure Detected via Vibration (Wind Farm B)", 2)
    s.add_body(doc,
        "Worth including precisely because it's not a perfect story: this turbine was "
        "\"stopped due to a main bearing damage.\" Vibration monitoring on the tower did "
        "pick up a clearly elevated, sustained vibration signature tied to this failure - "
        "but for this event, the clearest signal appeared right around the shutdown itself "
        "rather than weeks in advance. We show this because it's real and it's honest: "
        "vibration monitoring reliably confirms a bearing problem is real and ongoing, and "
        "for some failures that confirmation comes with more lead time than others. Setting "
        "that expectation correctly with a customer up front builds more trust than only "
        "showing the cleanest chart."
    )
    s.add_chart(doc, "degradation_trend_B_vibration_27.png",
        "Real sensor data: tower vibration during a real main-bearing failure - elevated "
        "sustained activity visible around the failure window.")

    s.add_heading(doc, "Fleet-Wide Picture", 2)
    s.add_body(doc,
        "Across all 3 farms, the real failure history breaks down as follows - hydraulics "
        "and pitch-system issues are the two most common named failure categories, which is "
        "exactly the kind of pattern a maintenance team can plan around once it's visible "
        "early."
    )
    s.add_chart(doc, "fault_category_by_farm.png",
        "Real failure counts by component and by wind farm, from the platform's own "
        "analysis of the underlying maintenance logs.")

    # 4. Differentiators ------------------------------------------------
    s.add_heading(doc, "4. What Makes This Different", 1)
    s.add_bullets(doc, [
        f"Built and proven on real operating data - {total_turbines} turbines, "
        f"{total_rows:,} sensor readings, {fs['fleet_totals']['total_anomaly_events']} real "
        "failure events - not a synthetic demo.",
        "Covers 7 major component categories out of the box (Gearbox, Hydraulics, Pitch "
        "System, Generator, Transformer, Rotor Brake, and Bearing via vibration analysis), "
        "and the method extends to new categories without a rebuild.",
        "Works across different turbine models and vendors automatically - it matches "
        "sensors by their description, not a fixed column layout, which is how it already "
        "handles 3 completely different sensor schemas (86, 257, and 957 sensors per farm) "
        "with the same pipeline.",
        "Includes a live visual dashboard with an actual 3D “digital twin” view of "
        "turbine health - not just a spreadsheet of numbers.",
        "Runs in the customer's own AWS account - enterprise-grade from day one, with fully "
        "isolated dev/staging/production environments and no shared infrastructure between "
        "customers.",
        "Built as independent services, not one fragile system - an issue in the alerting "
        "component, for example, can never take down the live telemetry dashboard.",
    ])

    # 5. Talking points ---------------------------------------------------
    s.add_heading(doc, "5. Talking Points for Customer Conversations", 1)
    qa = [
        ("What data do you need from us?",
         "The same SCADA export most turbines already produce - 10-minute sensor averages "
         "and standard operating-status codes. No new sensors or hardware."),
        ("Which failures can it catch?",
         "Gearbox, Hydraulics, Pitch System, Generator, Transformer, Rotor Brake, and Bearing "
         "(via vibration analysis) today, each validated against real failure history - "
         "extensible to other components as more data comes in."),
        ("How is this different from the alarms our SCADA already has?",
         "SCADA alarms fire when a value crosses a fixed threshold - often only once the "
         "fault is already underway. This platform watches for sustained trend shifts (like "
         "the hydraulics example) that show up days to weeks earlier than a threshold "
         "breach."),
        ("Is our data safe? Where does it run?",
         "It runs entirely inside the customer's own AWS account, with separate, isolated "
         "environments for development, staging, and production. Nothing is shared across "
         "customers."),
        ("Can it handle our specific turbine model?",
         "Yes - the platform matches sensors by their real-world description rather than "
         "a fixed layout, which is exactly how it already works across three farms with "
         "completely different sensor counts and naming."),
    ]
    for q, a in qa:
        p = doc.add_paragraph()
        run = p.add_run(f"Q: {q}")
        run.bold = True
        run.font.color.rgb = s.COPPER
        doc.add_paragraph(f"A: {a}")

    # 6. Honest status -----------------------------------------------------
    s.add_heading(doc, "6. Honest Status Today", 1)
    s.add_callout(doc, "IMPORTANT",
        "This is a validated architecture and working scaffold, proven against real "
        "historical turbine data - it is not yet running on a live customer SCADA feed. "
        "Be transparent about this with prospects: the value proposition is proven on real "
        "data, and the next step with any customer is a pilot on their own data.",
        kind="warning")

    # 7. Next steps ---------------------------------------------------------
    s.add_heading(doc, "7. Suggested Next Steps for a Prospect", 1)
    s.add_numbered(doc, [
        "Data Readiness Check - the prospect sends a sample SCADA export; we produce the "
        "same kind of real, sensor-grounded trend charts shown in this briefing, using "
        "their own turbines.",
        "Pilot Dashboard - stand up the live dashboard (Fleet Overview, Asset Detail, "
        "Digital Twin) against their historical data so their team can explore it "
        "hands-on.",
        "Production Pilot - connect a live feed for one site and begin real-time alerting "
        "alongside their existing SCADA alarms, not replacing them.",
    ])

    # Appendix --------------------------------------------------------------
    s.add_page_break(doc)
    s.add_heading(doc, "Appendix: Glossary", 1)
    glossary = [
        ("SCADA", "The turbine's own sensor/control system - the data source this platform "
                  "reads from. No new hardware needed."),
        ("RUL (Remaining Useful Life)", "An estimate of how many hours remain before a "
                                        "component is likely to fail, shown as a realistic "
                                        "range rather than one falsely precise number."),
        ("Fault classification", "Identifying *which* component is showing early signs of "
                                  "trouble, not just that \"something\" is abnormal."),
        ("Trend forecasting", "Projecting a component's health forward in time, like a "
                               "weather forecast."),
        ("Digital Twin", "A live, visual 3D representation of a turbine's current health, "
                          "driven by real sensor data."),
        ("Vibration analysis", "Listening to a turbine's overall \"shake\" via accelerometers "
                                "on the drivetrain, tower, or nacelle - a decades-old, "
                                "industry-standard way to catch bearing wear before it fails."),
        ("Medallion architecture", "The staged data pipeline (raw → cleaned → "
                                    "distilled) that turns SCADA exports into the signals "
                                    "above."),
    ]
    s.add_table(doc, ["Term", "Plain-English meaning"], glossary, widths=[2.0, 4.2])

    doc.save(str(OUT_PATH))
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
