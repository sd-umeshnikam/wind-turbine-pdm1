# How the platform works

## Data and the live replay
The platform runs on the CARE wind-farm dataset: three farms (A onshore in Portugal, B and C offshore in Germany) with 10-minute SCADA averages. Each of the 95 CARE events is one turbine's year of normal history followed by a prediction window that leads into a known outcome: an anomaly (a real fault) or normal operation. "Live" data is a replay of this recorded history: every turbine streams its own rows into the platform at a configurable speed (for example 60x), and scoring, alerts and drift checks run on that stream. Timestamps are anonymised and shifted per turbine, so each turbine has its own data clock; only the order and durations within one turbine are meaningful, and dates of different turbines cannot be compared.

## Components and sub-parts
Every turbine is broken down into components (gearbox, generator, rotor and main bearing, pitch system, rotor brake, hydraulic system, yaw system, transformer, power converter, electrical cabinets, structural vibration) and their sub-parts (for example gearbox high-speed-shaft bearings, lubrication oil, planetary bearings). A taxonomy maps each farm's sensors to sub-parts by their description. A farm only monitors the sub-parts it has sensors for: the console shows the others as "not monitored", never with an estimated value.

## Normal-behaviour models and expected values
For each monitored sensor, a normal-behaviour model (NBM) predicts what a healthy turbine would read under the current operating conditions (active power, wind speed, ambient and nacelle temperature, rotor speed, pitch angle). Candidates are a polynomial ridge regression (baseline), LightGBM and an MLP; the best per sensor on held-out normal data is selected. The residual (measured minus expected), divided by that turbine's normal residual spread, is the standardised residual z. A large positive z means the part runs hotter (or higher) than it should for the conditions.

## Health scores
Residuals are smoothed (6-hour EWMA) and rolled up from sensor to sub-part, component (worst sub-part) and turbine. Health is a calibrated 0-100 score: 100 while behaviour is within normal noise, decaying as the deviation grows. Health is calibrated per model version so that 50 is the alarm level of the deployed detector. In the console, 80 and above shows as healthy, 65-80 as watch, 50-65 as degraded and below 50 as alarm.

## Anomaly detectors
Three detectors run on the health scores: a health-score threshold (baseline), an Isolation Forest, and a supervised LightGBM early-warning classifier. Each farm deploys the detector that scored best in evaluation. A detector alarms when its score stays above its threshold (the 99.5th percentile of its scores on normal data) for 2 hours.

## Alerts
One active alert per turbine. An alert is raised when the turbine's detector alarm persists. Severity comes from turbine health: health 50 or more is low (an unusual combination with no single sub-part far beyond normal), 25-50 medium, 10-25 high, below 10 critical, and one level higher once the condition has persisted 48 hours. Severity never drops while the alert is active. The condition counts as cleared after 6 hours below 90% of the threshold, but clearing does not close the alert: an engineer resolves it with a resolution note. After a resolution, the same turbine raises a new alert within 24 hours only if it is more severe. Alert drivers are the sensors with the largest standardised residuals; sub-part attribution is a contributing signal, not a confirmed diagnosis.

## Alert workflow and roles
Open alerts are acknowledged by an engineer (who becomes the owner unless reassigned), assigned to an engineer or admin, annotated with notes, and resolved with a description of what was found and done. Every action is recorded in the audit log. Viewers can read everything; engineers also work alerts; admins also manage users, request retrains and approve challenger models.

## Evaluation
Models are evaluated per event with leave-turbine-out grouping. Detection counts only alarms inside an anomaly event's abnormal period; alarms on normal events, or before the abnormal period begins, are false alarms. The CARE-style score is the mean of event F1, accuracy on normal events, and earliness (the share of the abnormal period still ahead at the first alarm). It is not the official CARE score. False alarms are also reported as alarm days per turbine-year of normal operation. Remaining-useful-life models (Weibull AFT, LightGBM quantile) are experimental and not used for alerts, because each farm has few labelled failures.

## Model registry, champion and challenger
Each farm has one registered health model (wtpdm-health-A, -B, -C) in MLflow. The champion alias serves scoring; a new version becomes the challenger. The promotion gate requires the CARE-style score to improve on the champion by at least 0.005 without more false-alarm days per turbine-year than the baseline detector. With auto-promotion on, a challenger that passes the gate becomes champion; otherwise an admin approves it. A version that failed the gate cannot be approved.

## Drift monitoring
Every 15 minutes, the last 30 data-days of each farm are compared with the champion's training reference. Metrics: input distribution shift (PSI, informational, threshold 0.25), share of inputs outside the training range (out-of-support, threshold 0.05, triggers retrain), shift of the residual / turbine score distribution (residual shift, threshold 1.5, triggers retrain), and the alert rate compared with the reference (informational). "Drift" means a retrain-triggering metric breached; "warning" means only an informational metric breached.

## Retraining
Retraining is triggered by drift (with a 24-hour cool-down per farm), by a weekly schedule (Sunday 02:00 UTC by default), or manually by an admin. Every retrain runs the full training and evaluation protocol and goes through the same promotion gate. Jobs and their outcome (promoted, or held with the gate reasons) are listed under Drift & retraining.

## Digital twin
The digital twin shows a turbine's replayed operating conditions (power, wind speed, rotor speed, pitch angle, temperatures) and the health of each component. A quantity the farm does not measure is shown as not measured. The rotor only spins when a replayed rotor-speed reading exists.

## Limitations
Few labelled failures exist per farm and sub-part, so detection is uncertain and false alarms occur. Farm C's sensors are poorly explained by its operating conditions (many are cabinet or auxiliary signals), so its expected values are less precise. The platform supports maintenance decisions; it does not replace inspection, the OEM manual or site safety procedures.
