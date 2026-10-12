# Glossary and how to read the dashboard

## Anomaly
An anomaly is when a turbine starts behaving differently from its normal pattern, usually an early sign that something is going wrong days or weeks before the breakdown. In the dataset every data file is labelled either an anomaly event (it leads up to a real failure) or a normal event. There are 44 anomaly events and 51 normal events across 36 turbines.

## RUL (Remaining Useful Life)
RUL is the estimated time a component has left before it fails. The models predict it in hours and the dashboard shows it in days, months or years.

## P10, P50 and P90
The RUL prediction is a range, not a single number. P10 is the pessimistic estimate: only a 10% chance the part fails sooner. P50 is the most likely estimate: half the time it fails before, half after. P90 is the optimistic estimate: 90% chance it fails before this. Plan maintenance before P10. A narrow gap between P10 and P90 means a confident prediction; a wide gap means more uncertainty.

## Reading the RUL forecast chart
The dark blue line is P50, the most likely remaining life over the next days. The light blue shaded band is the P10 to P90 range. The band gets wider further into the future because predictions further ahead are less certain. When the bottom of the band gets close to zero, plan maintenance.

## Fault probability
The chance that a component is currently in a fault state rather than healthy, from the fault classifier. The Forecasts page colours it red above 25%.

## Health status: Healthy, Watch, Fault
Healthy means readings are normal with no predicted problem. Watch means something is drifting or remaining life is getting short. Fault means a high chance of failure or very little life left. On the Digital Twin page these statuses are currently simulated demo data, not live model output.

## Warning time before shutdown
Typical time from a fault's logged start to the turbine first going into downtime. Measured for 33 of 44 failures: median about 30 hours, with half of cases between 13 and 88 hours. Farm C median is about 28 hours, Farm B about 357 hours, and Farm A can rarely be measured because it barely records a downtime status.

## Turbine status codes (status_type_id)
0 normal operation, 1 derated operation (running at reduced power), 2 idling, 3 service, 4 downtime, 5 other. Only Farm B records derated (1); Farms A and C never record derated or idling.

## Derate and idle
Derate means the turbine still runs but produces less power than normal, usually to protect itself. Idle means it is up but not generating. Downtime means it has stopped because of a fault.

## Medallion architecture (bronze, silver, gold)
Raw SCADA CSVs land in the bronze layer, are cleaned in the silver layer, and turned into features, fault events and RUL labels in the gold layer. Models are trained on the gold layer.

## Models used
Fault classifier: multi-class LightGBM (Light Gradient Boosting Machine). RUL: LightGBM quantile regression trained three times for P10, P50 and P90. Trend forecaster: per-turbine Exponential Smoothing (ETS, damped trend) on a health index, forecasting 14 days ahead. Models are tracked in MLflow on port 5000.

## Digital twin
A live 3D (or 2D fallback) view of a turbine where each part is coloured by health. It is a data-bound visualisation, not a physics simulation.
