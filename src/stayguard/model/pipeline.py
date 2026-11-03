"""Train, evaluate, choose and score: the full Phase 4 pipeline.

1. Build as-of features (one row per booking alive at its as-of point).
2. Fit the baseline and both candidate models on the train intakes; evaluate on validation.
3. Choose the candidate with the best validation PR-AUC.
4. Extra evidence: a backtest on the latest January intake, calibration, lift, permutation
   importance, planted-effect recovery and a deliberate leakage demonstration.
5. Refit the chosen model on all closed intakes and score the open bookings.
6. Write scored_bookings and the evaluation tables to DuckDB for the app.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from sklearn.base import clone

from stayguard.config import DB_PATH, load_assumptions
from stayguard.db import connect
from stayguard.model.baseline import SegmentRateBaseline
from stayguard.model.evaluate import (
    business_value,
    calibration_table,
    classification_metrics,
    importance_table,
    lift_table,
)
from stayguard.model.features import FEATURES, assert_no_leakage, build_feature_frame
from stayguard.model.recovery import recovery_table
from stayguard.model.train import MODEL_VERSIONS, make_candidates
from stayguard.sql_runner import run_query

BASELINE = "baseline_segment_rate"


@dataclass
class ModelRun:
    """Everything the pipeline produced; tests and the CLI read from this."""

    chosen: str
    model_version: str
    selection_model: Any  # chosen model fitted on train intakes only (used for validation checks)
    final_model: Any  # chosen model refitted on all closed intakes (used for scoring)
    frame: pd.DataFrame
    evaluation: pd.DataFrame
    calibration: pd.DataFrame
    lift: pd.DataFrame
    importance: pd.DataFrame
    recovery: pd.DataFrame
    scored: pd.DataFrame
    days_left: int
    seconds: float


def days_to_open_intake(assumptions: dict[str, Any]) -> int:
    """Days from the snapshot to the open intake's move-in (the as-of horizon)."""
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    starts = [pd.Timestamp(d) for d in assumptions["intakes"].values()]
    return int((min(s for s in starts if s > snapshot) - snapshot).days)


def _metrics_rows(model: str, dataset: str, metrics: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {"model": model, "dataset": dataset, "metric": k, "value": v} for k, v in metrics.items()
    ]


def _evaluate(
    name: str,
    model: Any,
    train: pd.DataFrame,
    test: pd.DataFrame,
    dataset: str,
    ops: dict[str, Any],
) -> tuple[Any, np.ndarray, list[dict[str, Any]]]:
    """Fit on `train`, predict `test`, and return the model, predictions and metric rows."""
    model.fit(train[FEATURES], train["target"])
    p = model.predict_proba(test[FEATURES])[:, 1]
    metrics = classification_metrics(test["target"].to_numpy(), p)
    metrics |= business_value(test, p, ops["queue_top_share"], ops["intervention_save_rate"])
    return model, p, _metrics_rows(name, dataset, metrics)


def leakage_demonstration(
    con: duckdb.DuckDBPyConnection,
    chosen_model: Any,
    train: pd.DataFrame,
    valid: pd.DataFrame,
    dataset: str,
    ops: dict[str, Any],
) -> list[dict[str, Any]]:
    """Refit the chosen model with interaction features that ignore the as-of cut-off.

    The two interaction columns keep their names but get all-time values, so any model pipeline
    accepts them. The validation score jumps: that is what leakage looks like. Never scored.
    """
    leaky = run_query(con, "model/leakage_demo_interactions").set_index("booking_id")

    def with_leak(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        ids = out["booking_id"]
        out["touches_before_as_of"] = ids.map(leaky["touches_all_time"]).fillna(0).astype(float)
        out["positive_touch_rate_before_as_of"] = ids.map(
            leaky["positive_touch_rate_all_time"]
        ).astype(float)
        return out

    _, _, rows = _evaluate(
        "leaky_demo", clone(chosen_model), with_leak(train), with_leak(valid), dataset, ops
    )
    return rows


def _write_table(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("staging", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM staging")
    con.unregister("staging")


def run_model_pipeline(db_path: Path = DB_PATH) -> ModelRun:
    """Train, evaluate, score and write results. Needs a writable database."""
    started = time.perf_counter()
    assumptions = load_assumptions()
    seed = int(assumptions["project"]["seed"])
    ops = assumptions["operations"]
    assert_no_leakage(FEATURES)

    con = connect(db_path, read_only=False)
    try:
        frame = build_feature_frame(con, assumptions)
        train = frame.loc[frame["split"] == "train"]
        valid = frame.loc[frame["split"] == "validation"]
        score = frame.loc[frame["split"] == "score"]
        validation_name = "validation " + "+".join(assumptions["model_split"]["validation_intakes"])

        # Fit everything on train, compare on validation.
        rows: list[dict[str, Any]] = []
        fitted: dict[str, Any] = {}
        predictions: dict[str, np.ndarray] = {}
        candidates = {BASELINE: SegmentRateBaseline(), **make_candidates(seed)}
        for name, model in candidates.items():
            fitted[name], predictions[name], metric_rows = _evaluate(
                name, model, train, valid, validation_name, ops
            )
            rows += metric_rows
        evaluation = pd.DataFrame(rows)
        pr_auc = evaluation.query("metric == 'pr_auc'").set_index("model")["value"]
        chosen = str(pr_auc.drop(BASELINE).idxmax())

        # Backtest on the most recent January intake (the open intake is a January one).
        train_intakes = assumptions["model_split"]["train_intakes"]
        jan_test = [i for i in train_intakes if i.startswith("Jan")][-1]
        earlier = train_intakes[: train_intakes.index(jan_test)]
        backtest_rows: list[dict[str, Any]] = []
        for name in (BASELINE, chosen):
            model = SegmentRateBaseline() if name == BASELINE else clone(candidates[chosen])
            _, _, metric_rows = _evaluate(
                name,
                model,
                frame.loc[frame["intake"].isin(earlier)],
                frame.loc[frame["intake"] == jan_test],
                f"backtest {jan_test}",
                ops,
            )
            backtest_rows += metric_rows
        leak_rows = leakage_demonstration(
            con, candidates[chosen], train, valid, validation_name, ops
        )
        evaluation = pd.DataFrame(rows + backtest_rows + leak_rows)

        y_valid = valid["target"].to_numpy()
        calibration = pd.concat(
            [
                calibration_table(y_valid, predictions[m]).assign(model=m)
                for m in (BASELINE, chosen)
            ],
            ignore_index=True,
        )
        lift = pd.concat(
            [lift_table(y_valid, predictions[m]).assign(model=m) for m in (BASELINE, chosen)],
            ignore_index=True,
        )
        importance = importance_table(fitted[chosen], valid, y_valid, seed)
        days_left = days_to_open_intake(assumptions)
        recovery = recovery_table(fitted[chosen], valid)

        # Refit on every closed intake, then score the open bookings.
        closed = frame.loc[frame["split"].isin(["train", "validation"])]
        final_model = clone(candidates[chosen]).fit(closed[FEATURES], closed["target"])
        model_version = MODEL_VERSIONS[chosen]
        scored = pd.DataFrame(
            {
                "booking_id": score["booking_id"].astype("int64").to_numpy(),
                "p_cancel": final_model.predict_proba(score[FEATURES])[:, 1],
                "model_version": model_version,
                "scored_as_of": pd.Timestamp(assumptions["project"]["snapshot_date"]).date(),
            }
        )

        _write_table(con, "scored_bookings", scored)
        _write_table(con, "model_evaluation", evaluation)
        _write_table(con, "model_calibration", calibration)
        _write_table(con, "model_lift", lift)
        _write_table(con, "model_importance", importance)
        _write_table(con, "model_effect_recovery", recovery)
        con.execute("CHECKPOINT")
    finally:
        con.close()

    return ModelRun(
        chosen=chosen,
        model_version=model_version,
        selection_model=fitted[chosen],
        final_model=final_model,
        frame=frame,
        evaluation=evaluation,
        calibration=calibration,
        lift=lift,
        importance=importance,
        recovery=recovery,
        scored=scored,
        days_left=days_left,
        seconds=round(time.perf_counter() - started, 1),
    )
