# Health models — evaluation results (platform v2)

Generated from the MLflow experiment `wtpdm-health` (one parent run per farm, child runs per
sub-part NBM, detector, component and RUL candidate). Re-running `python -m wtpdm.ml.train`
regenerates every number here; each farm's run also stores `evaluation/model_card.md`.

## Method in one paragraph

Per farm, a normal-behaviour model (NBM) predicts every monitored sensor from the operating
conditions (power, wind speed, ambient/nacelle temperature, rotor speed, pitch). Candidates —
polynomial ridge (baseline), LightGBM, MLP — are compared per sensor on a time-ordered holdout of
normal data; the best is kept. Standardised residuals roll up into sub-part → component → turbine
health scores. Three detectors run on those scores (threshold baseline, Isolation Forest,
supervised LightGBM evaluated out-of-fold with folds grouped by event), each with its alarm
threshold at the 99.5th percentile of its scores on normal data and a 2-hour persistence rule.

Evaluation is event-level on the CARE `prediction` windows. An anomaly event's window
`[event_start, event_end]` is the **abnormal period** (onset of abnormal behaviour → failure);
detection counts only alarms inside it, warning time is measured to the failure, and alarms on
normal events or before the onset are false alarms. Training never sees a row inside any anomaly
window of the same turbine.

## Selected (champion) model per farm

| Farm | Detector | Faults caught | False-alarm normal windows | Median warning before failure | Alarm days / turbine-year | Score* |
|---|---|---|---|---|---|---|
| A | threshold baseline | 7 / 11 | 3 / 11 | 85 h | 1.5 | 0.57 |
| B | isolation forest | 4 / 6 | 2 / 9 | 1,030 h | 0.4 | 0.66 |
| C | threshold baseline | 18 / 27 | 7 / 31 | 192 h | 2.6 | 0.65 |

\* care-style score = mean of event F1, normal-event accuracy and earliness (share of the
abnormal period still ahead at the first alarm). Not the official CARE score.

## Detector comparison

| Farm | Detector | Score | Caught | False-alarm windows | Median warning | Alarm days / yr |
|---|---|---|---|---|---|---|
| A | threshold baseline | **0.57** | 7/11 | 3/11 | 85 h | 1.48 |
| A | supervised LightGBM | 0.53 | 4/11 | 1/11 | 83 h | 0.91 |
| A | isolation forest | 0.40 | 5/11 | 5/11 | 77 h | 0.62 |
| B | isolation forest | **0.66** | 4/6 | 2/9 | 1,030 h | 0.36 |
| B | threshold baseline | 0.49 | 3/6 | 4/9 | 1,348 h | 0.97 |
| B | supervised LightGBM | 0.10 | 1/6 | 8/9 | 276 h | 9.16 |
| C | threshold baseline | **0.65** | 18/27 | 7/31 | 192 h | 2.62 |
| C | isolation forest | 0.65 | 16/27 | 4/31 | 212 h | 3.03 |
| C | supervised LightGBM | 0.57 | 13/27 | 5/31 | 126 h | 0.46 |

No detector wins everywhere, which is why selection is per farm. The supervised detector is
weakest where faults are fewest (Farm B: 6 faults), as expected.

## Normal-behaviour model comparison (median normalised RMSE on held-out normal data)

| Farm | Ridge (baseline) | LightGBM | MLP | Sub-parts |
|---|---|---|---|---|
| A | 0.38 | **0.33** | 0.35 | 11 |
| B | 0.61 | **0.59** | 0.62 | 10 |
| C | 0.91 | **0.87** | 0.91 | 18 |

LightGBM is selected for almost every sensor. Farm C's sensors are poorly explained by its
operating conditions (many are cabinet/auxiliary signals) — see *Next improvements*.

## Remaining useful life (experimental — not deployed)

MAE in hours (grouped cross-validation): no candidate beats the constant-median baseline
(A: 180 vs 180, B: 180 vs 182, C: 180 vs 184). With 6–27 faults per farm the data does not
support a deployable RUL model; the platform reports health and warning instead.

## Known limitations

- **Sub-part diagnosis is weak**: the worst sub-part at the first alarm belongs to the labelled
  faulty component in only 14–28% of detected faults. Alarms are reliable at turbine level;
  sub-part attribution is shown as "contributing signals", not a diagnosis.
- Few faults per component → wide uncertainty on per-component figures.
- Timestamps are anonymised per turbine; no seasonality modelling.

## Next improvements (tracked)

1. Farm C NBM inputs: add nacelle temperature, lagged conditions and turbine identity.
2. Per-component thresholds tuned on normal data to improve diagnosis.
3. Calibrated alert severity from detector score margin + persistence.
