"""Train, evaluate, compare and (gated) promote the health model of a farm.

    python -m wtpdm.ml.train --farm C [--trigger manual|schedule|drift] [--no-promote]

MLflow layout (experiment "wtpdm-health"):
  parent run  farm-<F>                 data version, selected detector, headline metrics,
                                       comparison tables, model card, the registered bundle
    child     nbm/<subcomponent>       candidate comparison per monitored sensor
    child     detector/<name>          event-level evaluation of each detector
    child     component/<code>         per-component detection + diagnosis
    child     rul/<candidate>          experimental remaining-useful-life comparison
Registry: wtpdm-health-<F> (aliases: challenger -> champion when the gate passes),
          wtpdm-rul-<F> (experimental, only if it beats the constant baseline).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from wtpdm import catalog
from wtpdm.logging import configure_logging, get_logger
from wtpdm.ml import detectors, rul
from wtpdm.ml.bundle import HealthBundle, HealthPyfunc
from wtpdm.ml.dataset import farm_schema, load_farm_frame
from wtpdm.ml.evaluate import Metrics, event_results, summarize
from wtpdm.ml.health import component_scores, subpart_scores
from wtpdm.ml.nbm import CANDIDATES, TargetModel, fit_target, residual_z, time_holdout
from wtpdm.settings import get_settings

log = get_logger("train")
EXPERIMENT = "wtpdm-health"
SUPERVISED_TRAIN_SAMPLE = 0.2
# Promotion gate vs the threshold baseline: no meaningful increase in false alarms.
MAX_FALSE_ALARM_INCREASE_DAYS = 2.0
# A challenger replaces the champion only if it is better by at least this much (care score);
# retraining on unchanged data must not churn model versions.
MIN_IMPROVEMENT = 0.005


def model_name(farm: str) -> str:
    return f"wtpdm-health-{farm}"


# ------------------------------------------------------------------ stages


def fit_nbms(schema, frame: pd.DataFrame, fit_df, val_df, candidates):
    """Fit every target's NBM; returns models, per-target table, and sub-part scores for all rows."""
    models: dict[str, TargetModel] = {}
    rows: list[dict] = []
    sub_cols: dict[str, pd.Series] = {}
    series = frame["event_id"]
    for sub, cols in schema.targets.items():
        sub_models: dict[str, TargetModel] = {}
        with mlflow.start_run(run_name=f"nbm/{sub}", nested=True):
            mlflow.set_tags({"stage": "nbm", "subcomponent": sub})
            for col in cols:
                try:
                    tm = fit_target(col, sub, schema.condition_columns, fit_df, val_df, candidates)
                except ValueError as exc:
                    rows.append({"subcomponent": sub, "sensor": col, "status": "skipped", "reason": str(exc)})
                    continue
                sub_models[col] = tm
                rows.append(
                    {
                        "subcomponent": sub,
                        "sensor": col,
                        "description": schema.descriptions.get(col, col),
                        "status": "ok",
                        "selected": tm.candidate,
                        **{f"nrmse_{r.name}": r.nrmse for r in tm.results},
                        **{f"r2_{r.name}": r.r2 for r in tm.results},
                    }
                )
            if not sub_models:
                continue
            table = pd.DataFrame([r for r in rows if r["subcomponent"] == sub and r["status"] == "ok"])
            for c in candidates:
                mlflow.log_metric(f"median_nrmse_{c}", float(table[f"nrmse_{c}"].median()))
            mlflow.log_metric("sensors", len(sub_models))
            mlflow.log_dict(table.to_dict(orient="records"), "nbm_targets.json")
        models.update(sub_models)
        z = pd.DataFrame(
            {
                c: residual_z(m, frame, schema.condition_columns).astype(np.float32)
                for c, m in sub_models.items()
            },
            index=frame.index,
        )
        sub_cols[sub] = subpart_scores(z, {sub: list(sub_models)}, series)[sub]
        del z
        log.info("nbm fitted", farm=schema.farm, subcomponent=sub, sensors=len(sub_models))
    return models, pd.DataFrame(rows), pd.DataFrame(sub_cols, index=frame.index)


def evaluate_detector(out: detectors.DetectorOutput, frame, pred_mask, worst_comp) -> tuple[Metrics, list]:
    pred = frame[pred_mask]
    alarm = detectors.persistent_alarm(out.score[pred_mask], out.threshold, pred["event_id"].to_numpy())
    results = event_results(pred, alarm, worst_comp[pred_mask])
    return summarize(results), results


def component_evaluation(comps: pd.DataFrame, frame, pred_mask, val_mask) -> list[dict]:
    """Per component: can its own score detect the faults labelled with that component,
    without alarming on normal events?"""
    rows = []
    pred = frame[pred_mask]
    for comp in comps.columns:
        score = comps[comp].to_numpy()
        thr = float(np.nanquantile(score[val_mask], detectors.THRESHOLD_QUANTILE))
        alarm = detectors.persistent_alarm(score[pred_mask], thr, pred["event_id"].to_numpy())
        keep = (pred["label"] == "normal") | (pred["event_component"] == comp)
        results = event_results(pred[keep.to_numpy()], alarm[keep.to_numpy()])
        m = summarize(results)
        rows.append({"component": comp, "threshold": thr, **m.as_dict()})
    return rows


# ------------------------------------------------------------------ plots and card


def _plot_nbm(table: pd.DataFrame, candidates, path: Path) -> None:
    ok = table[table["status"] == "ok"]
    med = ok.groupby("subcomponent")[[f"nrmse_{c}" for c in candidates]].median()
    ax = med.plot.barh(figsize=(9, max(3, 0.45 * len(med))), width=0.8)
    ax.set_xlabel("median normalised RMSE on held-out normal data (lower is better)")
    ax.legend([c for c in candidates], loc="lower right")
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def _plot_leads(results_by_det: dict[str, list], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    for name, results in results_by_det.items():
        leads = [r.warning_hours for r in results if r.label == "anomaly" and r.warning_hours is not None]
        if leads:
            ax.hist(np.clip(leads, 0, 720), bins=24, alpha=0.5, label=f"{name} (n={len(leads)})")
    ax.set_xlabel("warning before failure (hours from first alarm to event end)")
    ax.set_ylabel("detected faults")
    ax.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def model_card(farm, version, schema, selected, det_table, comp_rows, rul_rows, nbm_table) -> str:
    ok = nbm_table[nbm_table["status"] == "ok"]
    lines = [
        f"# Health model card - Wind Farm {farm}",
        "",
        f"- Data version: `{version}`",
        f"- Monitored sensors modelled: {len(ok)} across {ok['subcomponent'].nunique()} sub-parts "
        f"({len(schema.excluded)} excluded by data quality: {sorted(set(schema.excluded.values()))})",
        f"- Operating-condition inputs: {', '.join(schema.conditions)}",
        f"- Selected detector: **{selected}**",
        "",
        "## Evaluation protocol",
        "CARE-style, event level. Normal-behaviour models learn from the `train` history of every",
        "event file",
        "(excluding any row inside an anomaly window of the same turbine) and are scored on the `prediction`",
        "windows: anomaly windows end in a real fault, normal windows in nothing. Thresholds come from",
        "normal",
        "validation data only; the supervised detector is evaluated out-of-fold with folds grouped by event.",
        "",
        "## Detector comparison",
        det_table.to_markdown(index=False),
        "",
        "## Per-component detection",
        pd.DataFrame(comp_rows)[
            [
                "component",
                "anomaly_events",
                "detected",
                "false_alarm_events",
                "median_warning_hours",
                "care_style_score",
            ]
        ].to_markdown(index=False),
        "",
        "## Remaining useful life (experimental)",
        pd.DataFrame(rul_rows).to_markdown(index=False) if rul_rows else "Too few faults to evaluate.",
        "",
        "## Limitations",
        "- Few labelled faults per component: per-component figures carry wide uncertainty.",
        "- Timestamps are anonymised per turbine; seasonality is not modelled.",
        "- Health scores are relative to each turbine's own normal behaviour, not absolute physical limits.",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ registry


def _champion_score(client: MlflowClient, name: str) -> float | None:
    try:
        mv = client.get_model_version_by_alias(name, "champion")
    except MlflowException:
        return None
    return client.get_run(mv.run_id).data.metrics.get("selected_care_style_score")


def register_and_gate(run_id: str, farm: str, selected: Metrics, baseline: Metrics, promote: bool) -> dict:
    client = MlflowClient()
    name = model_name(farm)
    with contextlib.suppress(MlflowException):  # already registered
        client.create_registered_model(name, description=f"Sub-part health model for Wind Farm {farm}")
    mv = client.create_model_version(name, f"runs:/{run_id}/model", run_id=run_id)
    client.set_registered_model_alias(name, "challenger", mv.version)

    reasons = []
    if selected.false_alarm_days_per_turbine_year > (
        baseline.false_alarm_days_per_turbine_year + MAX_FALSE_ALARM_INCREASE_DAYS
    ):
        reasons.append("more false alarms than the baseline detector")
    champion = _champion_score(client, name)
    if champion is not None and selected.care_style_score < champion + MIN_IMPROVEMENT:
        reasons.append(
            f"care_style_score {selected.care_style_score} does not improve on champion {champion}"
            f" by >= {MIN_IMPROVEMENT}"
        )
    promoted = promote and not reasons
    if promoted:
        client.set_registered_model_alias(name, "champion", mv.version)
    client.set_model_version_tag(name, mv.version, "gate", "passed" if not reasons else "; ".join(reasons))
    return {
        "model": name,
        "version": mv.version,
        "promoted": promoted,
        "gate_reasons": reasons,
        "previous_champion_score": champion,
    }


def record_deployment(farm: str, registry: dict, metrics: Metrics, actor: str, trigger: str) -> None:
    """Mirror the registry decision into the platform DB (deployment history + audit)."""
    from wtpdm.db.models import AuditLog, ModelDeployment
    from wtpdm.db.session import session_scope

    with session_scope() as s:
        # The registry alias moves, so the rows it moved away from are retired.
        moved = ["champion", "challenger"] if registry["promoted"] else ["challenger"]
        s.query(ModelDeployment).filter(
            ModelDeployment.farm_id == farm, ModelDeployment.alias.in_(moved)
        ).update({"alias": "retired"})
        s.add(
            ModelDeployment(
                model_name=registry["model"],
                version=str(registry["version"]),
                alias="champion" if registry["promoted"] else "challenger",
                farm_id=farm,
                validation="validated" if not registry["gate_reasons"] else "failed_gate",
                metrics=metrics.as_dict(),
                promoted_by=actor,
            )
        )
        s.add(
            AuditLog(
                actor=actor,
                action="model.promote" if registry["promoted"] else "model.register",
                entity="model",
                entity_id=f"{registry['model']}/{registry['version']}",
                details={
                    **registry,
                    "trigger": trigger,
                    "awaiting_approval": not registry["promoted"] and not registry["gate_reasons"],
                },
            )
        )


# ------------------------------------------------------------------ main flow


def train_farm(farm: str, trigger: str = "manual", actor: str = "system:train", promote: bool = True) -> dict:
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(EXPERIMENT)
    candidates = tuple(CANDIDATES)

    schema = farm_schema(settings.lake_root, farm)
    frame = (
        load_farm_frame(settings.lake_root, schema)
        .sort(["event_id", "ts"])
        .to_pandas(use_pyarrow_extension_array=False)
    )
    version = catalog.data_version(settings.lake_root, farm)
    train_rows = frame[frame["train_ok"]]
    fit_df, val_df = time_holdout(train_rows)
    val_mask = frame.index.isin(val_df.index)
    pred_mask = (frame["split"] == "prediction").to_numpy()
    log.info(
        "frame loaded",
        farm=farm,
        rows=len(frame),
        fit=len(fit_df),
        val=len(val_df),
        pred=int(pred_mask.sum()),
    )

    with mlflow.start_run(run_name=f"farm-{farm}") as parent:
        mlflow.set_tags({"farm": farm, "trigger": trigger, "data_version": version, "actor": actor})
        mlflow.log_params(
            {
                "conditions": ",".join(schema.conditions),
                "candidates": ",".join(candidates),
                "persistence_rows": detectors.PERSISTENCE_ROWS,
                "threshold_quantile": detectors.THRESHOLD_QUANTILE,
                "excluded_sensors": len(schema.excluded),
            }
        )

        target_models, nbm_table, subs = fit_nbms(schema, frame, fit_df, val_df, candidates)
        comps = component_scores(subs)
        turbine = subs.max(axis=1).to_numpy()
        worst_comp = comps.idxmax(axis=1, skipna=True)

        # ---- detectors
        outputs = [
            detectors.threshold_baseline(turbine[val_mask], turbine),
            detectors.isolation_forest(subs[val_mask], subs),
        ]
        feats = detectors.supervised_features(subs, frame["event_id"])
        rng = np.random.default_rng(42)
        sup_mask = pred_mask | (
            frame["train_ok"].to_numpy() & (rng.random(len(frame)) < SUPERVISED_TRAIN_SAMPLE)
        )
        sup = detectors.supervised_lgbm(
            feats[sup_mask],
            detectors.supervised_labels(frame[sup_mask]),
            frame["event_id"].to_numpy()[sup_mask],
        )
        sup_score = np.full(len(frame), np.nan)
        sup_score[sup_mask] = sup.score
        # Same alarm policy as the unsupervised detectors: threshold at the high quantile of
        # its own (out-of-fold) scores on normal training data - a fixed 0.5 alarmed on
        # every normal window because class weighting inflates probabilities.
        normal_oof = sup_score[sup_mask & frame["train_ok"].to_numpy()]
        sup_threshold = float(np.nanquantile(normal_oof, detectors.THRESHOLD_QUANTILE))
        outputs.append(detectors.DetectorOutput(sup.name, sup_score, sup_threshold, sup.model))

        det_metrics: dict[str, Metrics] = {}
        det_results: dict[str, list] = {}
        for out in outputs:
            m, results = evaluate_detector(out, frame, pred_mask, worst_comp)
            det_metrics[out.name], det_results[out.name] = m, results
            with mlflow.start_run(run_name=f"detector/{out.name}", nested=True):
                mlflow.set_tags({"stage": "detector", "detector": out.name})
                mlflow.log_param("threshold", round(out.threshold, 5))
                mlflow.log_metrics({k: v for k, v in m.as_dict().items() if isinstance(v, int | float)})
                mlflow.log_dict(
                    {"events": [{**asdict(r), "first_alarm": str(r.first_alarm)} for r in results]},
                    "event_results.json",
                )

        baseline = det_metrics["threshold_baseline"]
        eligible = {
            n: m
            for n, m in det_metrics.items()
            if m.false_alarm_days_per_turbine_year
            <= baseline.false_alarm_days_per_turbine_year + MAX_FALSE_ALARM_INCREASE_DAYS
        }
        selected_name = max(eligible, key=lambda n: eligible[n].care_style_score)
        selected = det_metrics[selected_name]
        sel_out = next(o for o in outputs if o.name == selected_name)

        # ---- per component
        comp_rows = component_evaluation(comps, frame, pred_mask, val_mask)
        for row in comp_rows:
            with mlflow.start_run(run_name=f"component/{row['component']}", nested=True):
                mlflow.set_tags({"stage": "component", "component": row["component"]})
                mlflow.log_metrics({k: v for k, v in row.items() if isinstance(v, int | float)})

        # ---- RUL (experimental)
        rx, ry, rg = rul.rul_frame(feats, frame)
        rul_results = rul.evaluate_rul(rx, ry, rg)
        for r in rul_results:
            with mlflow.start_run(run_name=f"rul/{r.candidate}", nested=True):
                mlflow.set_tags({"stage": "rul", "candidate": r.candidate, "experimental": "true"})
                mlflow.log_metrics({k: v for k, v in asdict(r).items() if isinstance(v, int | float)})

        # ---- headline metrics, comparison tables, card, bundle
        mlflow.set_tag("selected_detector", selected_name)
        mlflow.log_metrics(
            {f"selected_{k}": v for k, v in selected.as_dict().items() if isinstance(v, int | float)}
        )
        det_table = pd.DataFrame(
            [{"detector": n, "selected": n == selected_name, **m.as_dict()} for n, m in det_metrics.items()]
        )
        bundle = HealthBundle(
            farm=farm,
            conditions=schema.condition_columns,
            targets={s: [c for c in cols if c in target_models] for s, cols in schema.targets.items()},
            descriptions=schema.descriptions,
            units=schema.units,
            target_models=target_models,
            detector_name=selected_name,
            detector_model=sel_out.model,
            threshold=sel_out.threshold,
            metrics=selected.as_dict(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            det_table.to_csv(t / "detector_comparison.csv", index=False)
            (t / "detector_comparison.html").write_text(det_table.to_html(index=False))
            pd.DataFrame(comp_rows).to_csv(t / "component_evaluation.csv", index=False)
            nbm_table.to_csv(t / "nbm_comparison.csv", index=False)
            _plot_nbm(nbm_table, candidates, t / "nbm_comparison.png")
            _plot_leads(det_results, t / "lead_times.png")
            (t / "model_card.md").write_text(
                model_card(
                    farm,
                    version,
                    schema,
                    selected_name,
                    det_table,
                    comp_rows,
                    [asdict(r) for r in rul_results],
                    nbm_table,
                )
            )
            (t / "excluded_sensors.json").write_text(json.dumps(schema.excluded, indent=2))
            mlflow.log_artifacts(str(t), "evaluation")
            joblib.dump(bundle, t / "bundle.joblib", compress=3)
            mlflow.pyfunc.log_model(
                "model", python_model=HealthPyfunc(), artifacts={"bundle": str(t / "bundle.joblib")}
            )
        registry = register_and_gate(parent.info.run_id, farm, selected, baseline, promote)
        mlflow.set_tags({"registered_version": registry["version"], "promoted": registry["promoted"]})
    record_deployment(farm, registry, selected, actor, trigger)

    log.info("farm trained", farm=farm, selected=selected_name, metrics=selected.as_dict(), registry=registry)
    return {
        "farm": farm,
        "run_id": parent.info.run_id,
        "selected": selected_name,
        "metrics": selected.as_dict(),
        "registry": registry,
        "data_version": version,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--farm", action="append", choices=["A", "B", "C"])
    parser.add_argument("--trigger", default="manual", choices=["manual", "schedule", "drift"])
    parser.add_argument("--no-promote", action="store_true")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    for farm in args.farm or ["A", "B", "C"]:
        train_farm(farm, trigger=args.trigger, promote=not args.no_promote)


if __name__ == "__main__":
    main()
