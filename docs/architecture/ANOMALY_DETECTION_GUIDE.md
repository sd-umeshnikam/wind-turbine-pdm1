# Anomaly Detection Guide — What Gets Flagged, and Why

This doc answers the question a maintenance engineer or reviewer asks first: **"why did the
platform say this component is failing?"** It covers the general detection mechanism once
(§1), then the physical reasoning and real evidence behind each of the seven target components
(§2), grounded in the actual charts and numbers in [`eda/EDA_REPORT.md`](../../eda/EDA_REPORT.md)
— nothing here is a generic textbook failure-mode list; every claim below cites a real chart or
event from that report.

## 1. How detection actually works (the general mechanism)

The platform never flags an anomaly from a single reading. Three layers work together:

1. **Rolling features, not raw values.** `gold.<component>_features` (see
   [BLUEPRINT.md §3](BLUEPRINT.md#3-medallion-data-architecture)) computes 1h/6h/24h rolling
   mean *and* rolling standard deviation per sensor, per component. A single hot reading is
   noise; a sustained shift in the rolling mean, or a collapse/spike in rolling variability
   (a component running unusually smoothly *or* unusually erratically), is the actual signal —
   see §2 below for concrete examples of both directions.
2. **Fault classification gives a category, not just "abnormal."** `<component>_fault_classifier`
   (§4 of BLUEPRINT.md) is trained to distinguish *which* component's feature pattern the current
   rolling window resembles, against `gold.fault_events`' real labeled history. The model doesn't
   invent failure signatures — it learns them from the same real events cited in §2.
3. **RUL and forecast add the "how long," alerting adds the "who gets told."**
   `alerting-service` (see [BLUEPRINT.md §5](BLUEPRINT.md#5-backend--independently-deployable-services-no-monolith))
   only raises an alert when *either* fault probability crosses a threshold *or* the RUL P50
   estimate drops below a configurable hours threshold — an OR, not an AND, because either signal
   alone is independently actionable for scheduling maintenance (see
   `services/alerting-service/src/handler.ts`'s `severityFor`).

**What "why" actually means in the UI**: the Asset Detail and Forecasts/RUL dashboard modules
always show the underlying sensor trend alongside the prediction (never a bare probability
number) — see BLUEPRINT.md §6 — so a flagged component can always be visually cross-checked
against the same kind of chart shown below, not taken on faith.

## 2. Per-component reasoning, grounded in real data

### Gearbox
**Sensors used**: oil temperature, oil pressure, high-speed-shaft bearing temperature (per-farm
resolved via keyword match against each farm's `feature_description.csv` — see BLUEPRINT.md §3).
**Why these indicate failure**: a gearbox converts low-speed, high-torque rotor motion to
high-speed generator input through meshing gears under constant load; wear, misalignment, or oil
breakdown all show up first as *friction* (heat) and *lubrication irregularity* (pressure), well
before a gear tooth actually breaks.
**Real evidence**: Farm A event 72 ("Gearbox failure") shows both oil and bearing temperature
running hotter *and* noisier than the normal baseline through most of the pre-fault window, with a
sharp shared dip ~day 9-11 consistent with a protective derate/shutdown. Farm C event 12 ("Oil
level error, two-pump mode + Oil Leakage Gear Oil Supply") shows oil *pressure* running higher and
far more erratic (frequent drop-outs to near 0) than the baseline's low-noise ~4 bar — the
erratic-pressure signature is the giveaway here, not just an average shift, which is why rolling
*standard deviation* is tracked alongside rolling mean.

### Hydraulics
**Sensors used**: hydraulic oil tank temperature, oil level, pump pressure.
**Why**: the hydraulic system actuates pitch and braking; a leak, failing pump, or degrading
accumulator makes the pump work harder and/or lose pressure, which shows up as sustained elevated
oil temperature (from extra pump duty cycling) or abnormal pressure, well before the system fails
to actuate.
**Real evidence**: Farm A event 73 ("Hydraulic group") is the cleanest signal in the entire EDA —
hydraulic oil temperature sits persistently ~10-15°C above baseline for the *entire* pre-fault
window (not just near the fault), i.e. a stable, early, sustained offset rather than a last-minute
spike. Farm C event 28 ("Accumulators hydraulic system") shows recurring multi-day temperature
spikes (up to ~45-48°C vs a ~20-30°C baseline band) rather than one single event — consistent with
an accumulator fault that recurs under load.

### Pitch System
**Sensors used**: per-axis pitch motor temperature, axis cooling-element temperature, pitch angle.
**Why**: each blade's pitch axis has its own motor, encoder, and (in Farm C's 3-axis independent
design) its own cooling and control electronics; a failing axis motor or its Beckhoff control card
draws abnormal current and runs hot well before the axis actually stops responding
("not-ready-to-operate").
**Real evidence**: Farm C event 91 ("Axis 3 not ready-to-operate") shows Axis 3's own
cooling-element temperature — the exact axis named in the real fault text — running ~5-10°C above
baseline for most of the pre-fault window, with Axis 1 motor temperature showing a similar
sustained elevation. The rule-based sensor pick landing on the literally-named axis, using no
hand-curation, is itself evidence the feature-to-fault mapping is physically sound, not
coincidental.

### Generator
**Sensors used**: Drive-End / Non-Drive-End bearing temperature, stator winding temperature,
cooling-air-inlet temperature.
**Why**: generator bearings and windings are the two things that actually wear/degrade under
continuous rotation and electrical load; bearing wear raises friction (temperature), winding
insulation breakdown raises electrical resistance (also temperature, plus eventually current
anomalies the platform doesn't yet ingest).
**Real evidence — and an important caveat**: Farm A event 40 ("Generator bearing failure") is the
one case in this whole report where the anomaly runs *cooler and less variable* than baseline for
most of the window, not hotter — read together with the fault, this looks like the turbine was
already throttled back (derated) in response to an early symptom, rather than running hot
unchecked. The same chart also shows a sensor pinned at a flat ~204 for extended stretches late in
the window — almost certainly a sensor fault/dropout code, not a real reading. **This is exactly
why the platform's feature pipeline needs an implausible-value filter, not just a missing-value
check** (see EDA_REPORT.md §5) — a generator bearing model trained on this data without that
filter would learn a nonsense "204 = imminent failure" rule from a data artifact, not physics.

### Transformer
**Sensors used**: per-phase or per-unit oil/winding temperature (granularity differs by farm —
see EDA_REPORT.md §3).
**Why**: a transformer's oil (or air, depending on cooling design) is both the coolant and the
electrical insulator; insulation degradation and internal electrical faults both manifest as
abnormal, sustained temperature rise or abnormal thermal *cycling* patterns, since oil temperature
directly tracks internal heat generation.
**Real evidence**: Farm C event 67 ("overpressure on the main transformer") shows one of its two
oil sensors — "Oil temperature 1 main transformer" — running a clean, sustained ~10-15°C above
baseline for essentially the *entire* ~58-day window, one of the longest clean early-warning
offsets in the whole dataset; its sibling sensor ("Oil temperature EB transformer", a different
transformer bank) shows no useful signal at all for this event, a real finding reported honestly
rather than cherry-picked. Farm A event 68 ("Transformer failure") shows the opposite kind of
precursor: *reduced* day/night thermal cycling versus the baseline's wide swings during the
officially-logged window, then a clear thermal-runaway climb (to well above baseline peaks) in the
week immediately after the logged window ends — evidence that a real early-warning system should
watch cycling *pattern*, not just absolute temperature, and should not stop looking the moment an
official event window closes.

### Rotor Brake
**Sensors used**: hydraulic brake-caliper pressure (per-caliper, e.g. "A"/"B" in Farm C).
**Why**: the rotor brake is a hydraulically-actuated mechanical brake; anything that disrupts its
hydraulic supply or control power causes pressure to run low or erratic rather than holding its
normal regulated band, well before the brake fails to engage/disengage on command.
**Real evidence**: Farm C event 18 ("24VAC supply fault to rotor brake, then extended standstill")
shows both brake calipers' pressure running persistently *lower* than baseline across the ~10 days
of available pre-fault data, with sharp transient dips layered on top — consistent with a
power/control fault causing degraded pressure regulation rather than a single instantaneous
mechanical break. **Coverage caveat**: this sensor only exists in Farm C's instrumentation (see
EDA_REPORT.md §3) — Farm A and B have no rotor-brake-specific sensor at all, so this model is
necessarily Farm-C-only until other farms add the instrumentation.

### Bearing (Vibration Analysis)
**Sensors used**: broadband vibration amplitude — Farm B's drive-train (axis Z) and tower (axis
X/Y) accelerometers in mG; Farm C's nacelle accelerometers (longitudinal/transverse) in m/s².
**Why**: this is the one component detected by a fundamentally different physical signal than
every other component in this guide — motion/acceleration, not temperature or pressure. Bearing
wear, imbalance, and looseness in rotating machinery increase the overall mechanical vibration
energy transmitted through the structure; monitoring broadband vibration amplitude against a
normal baseline is a decades-old, industry-standard condition-monitoring technique for rotating
machinery (the same principle behind ISO 10816/20816 vibration severity zones), independent of
knowing the exact fault mechanism.

**Real evidence — and why it's reported as a mixed result, not a clean win**: Farm B event 27
("Turbine is stopped due to a main bearing damage") is the only anomaly event in this dataset with
both a real bearing-related fault description *and* real vibration instrumentation. Drive-train
vibration (axis Z) shows no usable separation from the normal baseline through the pre-fault
window — both sit near zero with occasional transient spikes in both series; this sensor was not
informative for this event. Tower vibration (axis X) is more useful but tells an honestly
different story than the cleanest charts elsewhere in this guide (e.g. Farm A Hydraulics' days-early
sustained offset): during the ~61-day labeled event window itself, the anomaly turbine's tower
vibration overlaps the normal baseline's noisy range closely — no early separation. The clear
signal instead appears in the roughly one-week span immediately *after* the labeled event window
closes, where the anomaly turbine shows a sustained, densely-elevated vibration band while the
baseline in the same relative period stays low. Read plainly: for this specific event, vibration
tracked the failure/shutdown episode itself (plausibly abnormal coast-down or restart dynamics from
a damaged bearing), not a multi-week advance warning the way the hydraulics and transformer
examples did. This is a genuine, useful finding about this signal's behavior — it should not be
oversold as an early-warning success story it wasn't.

**Scope caveat — the most important one in this document**: this dataset's vibration sensors are
10-minute statistical aggregates (average/max/min/standard-deviation of overall vibration
amplitude), not raw high-frequency waveform data. A production condition-monitoring system for
bearings/gearboxes typically samples accelerometers in the kHz range and applies FFT spectral
analysis to isolate characteristic fault frequencies (ball-pass frequencies outer/inner race, cage
and rolling-element frequencies, gear-mesh frequency and its sidebands) — that lets a real system
tell *which* bearing defect mode is present, not just that overall vibration changed. This
platform's `vibration` component supports broadband severity trending (an ISO 10816/20816-style
"is this getting worse" check) with the same classification/RUL/forecasting pipeline as every other
component (see BLUEPRINT.md §4) — it does not do spectral fault-mode diagnosis, and should not be
represented as doing so. Raw-waveform capture and spectral feature engineering is a documented v2
extension, not something achievable with this dataset as it exists today.

## 3. What this means for trusting (or not trusting) a flagged anomaly

- A component flagged by *sustained offset over many days* (Farm A hydraulics, Farm C transformer)
  is a stronger, earlier signal than one flagged by a late spike — the platform's rolling-window
  features are specifically designed to catch the former, not just threshold the latter.
- A component whose telemetry looks *calmer* than normal (Farm A generator) can be just as
  meaningful a precursor as one running hot — don't assume "anomaly = higher values."
- Always sanity-check a flagged value against physical plausibility before trusting it (Farm A
  generator's pegged-204 artifact) — the dashboard's Asset Detail view exists specifically so a
  human can make that check before acting on an alert.
- Coverage is real-data-limited, not just a modeling choice: rotor brake is Farm-C-only, vibration
  instrumentation only exists on Farm B and C, and 3 of Farm B's 6 real anomalies (generic "high
  temperature" reports) still fall outside all seven target categories — a "no alert" for those
  reflects the model's honest scope, not a gap in detection.
- Not every signal gives early warning, and the platform reports that honestly rather than forcing
  a narrative: Bearing/vibration's one real evidence case (Farm B event 27) showed its clearest
  separation *after* the labeled fault window rather than days in advance, unlike the hydraulics
  and transformer examples above — a genuinely different, and equally useful, kind of finding.
- Vibration (Bearing) supports "is this trending worse" broadband monitoring only, not "which
  specific bearing defect mode" spectral diagnosis — see the scope caveat above before promising a
  capability this dataset can't back up.
