"""Cancellation-risk model: leakage guard, time split, quality, effect recovery, scoring."""

import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from stayguard.config import load_assumptions
from stayguard.model.features import (
    FEATURES,
    LEAKY_COLUMNS,
    NON_FEATURE_COLUMNS,
    LeakageError,
    assert_no_leakage,
)
from stayguard.model.pipeline import BASELINE

VALIDATION = "validation Sep-2026"


def metric(model_run, model: str, name: str, dataset: str = VALIDATION) -> float:
    ev = model_run.evaluation
    row = ev[(ev["model"] == model) & (ev["metric"] == name) & (ev["dataset"] == dataset)]
    return float(row["value"].item())


# --- Leakage ------------------------------------------------------------------------------------


def test_feature_list_has_no_leaky_columns():
    assert_no_leakage(FEATURES)
    assert not set(FEATURES) & NON_FEATURE_COLUMNS


@pytest.mark.parametrize("column", sorted(LEAKY_COLUMNS))
def test_leakage_guard_rejects_each_leaky_column(column):
    with pytest.raises(LeakageError):
        assert_no_leakage([*FEATURES, column])


def test_interaction_features_only_use_touches_before_as_of(model_run, con):
    frame = model_run.frame[["booking_id", "as_of_ts", "touches_before_as_of"]]
    touches = con.execute(
        "SELECT booking_id, ts FROM fact_interaction WHERE booking_id IS NOT NULL"
    ).df()
    merged = touches.merge(frame, on="booking_id")
    expected = (
        merged.loc[merged["ts"] < merged["as_of_ts"]]
        .groupby("booking_id")
        .size()
        .reindex(frame["booking_id"], fill_value=0)
    )
    assert (frame["touches_before_as_of"].to_numpy() == expected.to_numpy()).all()


def test_population_is_alive_at_as_of(model_run, con):
    b = con.execute(
        "SELECT booking_id, booked_at, is_cancelled, cancelled_at FROM v_bookings_gbp"
    ).df()
    rows = model_run.frame[["booking_id", "as_of_ts"]].merge(b, on="booking_id")
    assert (rows["booked_at"] < rows["as_of_ts"]).all()
    cancelled_before = rows["is_cancelled"] & (rows["cancelled_at"] < rows["as_of_ts"])
    assert not cancelled_before.any()


def test_leakage_demo_shows_what_leakage_looks_like(model_run):
    """Interactions after the as-of point inflate the score: the planted trap (ADR-016) works."""
    honest = metric(model_run, model_run.chosen, "pr_auc")
    leaky = metric(model_run, "leaky_demo", "pr_auc")
    assert leaky > 1.5 * honest


# --- Split --------------------------------------------------------------------------------------


def test_split_is_time_based(model_run):
    split = load_assumptions()["model_split"]
    frame = model_run.frame
    for name, intakes in (
        ("train", split["train_intakes"]),
        ("validation", split["validation_intakes"]),
        ("score", split["score_intakes"]),
    ):
        assert set(frame.loc[frame["split"] == name, "intake"]) == set(intakes)
    assert frame.loc[frame["split"] == "score", "is_open"].all()
    assert frame.loc[frame["split"] != "score", "target"].notna().all()


# --- Quality ------------------------------------------------------------------------------------


def test_model_beats_baseline_on_validation(model_run):
    chosen = model_run.chosen
    assert metric(model_run, chosen, "pr_auc") > metric(model_run, BASELINE, "pr_auc")
    assert metric(model_run, chosen, "roc_auc") > metric(model_run, BASELINE, "roc_auc")
    assert metric(model_run, chosen, "brier") < metric(model_run, chosen, "brier_constant")


def test_model_beats_baseline_on_january_backtest(model_run):
    dataset = "backtest Jan-2026"
    assert metric(model_run, model_run.chosen, "pr_auc", dataset) > metric(
        model_run, BASELINE, "pr_auc", dataset
    )


def test_chosen_model_has_best_validation_pr_auc(model_run):
    candidates = ["logistic_regression", "gradient_boosting"]
    best = max(candidates, key=lambda m: metric(model_run, m, "pr_auc"))
    assert model_run.chosen == best


def test_validation_calibration_is_reasonable(model_run):
    cal = model_run.calibration.query("model == @model_run.chosen")
    overall_gap = np.average(cal["mean_predicted"] - cal["observed_rate"], weights=cal["n"])
    assert abs(overall_gap) < 0.02
    assert (cal["mean_predicted"] - cal["observed_rate"]).abs().mean() < 0.05


def test_working_the_queue_beats_random_calls(model_run):
    chosen = model_run.chosen
    assert metric(model_run, chosen, "saved_gbp") > 1.5 * metric(
        model_run, chosen, "random_saved_gbp"
    )


# --- Recovery of planted effects ----------------------------------------------------------------


def test_planted_cancellation_effects_recovered(model_run):
    rec = model_run.recovery
    assert rec["recovered"].all(), rec.loc[~rec["recovered"], ["effect", "relative_change"]]


def test_top_features_align_with_planted_effects(model_run):
    top = set(model_run.importance.head(6)["feature"])
    assert {"visa_status_at_booking", "source_country", "deposit_paid"} <= top
    assert "days_booked_before_intake" in top


# --- Scoring ------------------------------------------------------------------------------------


def test_scored_table_written(con, model_run):
    scored = con.execute("SELECT booking_id, p_cancel, model_version FROM scored_bookings").df()
    n_open = con.execute("SELECT COUNT(*) FROM v_bookings_gbp WHERE is_open").fetchone()[0]
    assert len(scored) == n_open
    assert scored["booking_id"].is_unique
    assert (scored["model_version"] == model_run.model_version).all()
    assert scored["p_cancel"].between(0, 1, inclusive="neither").all()
    baseline = con.execute("SELECT COUNT(*) FROM scored_bookings_baseline").fetchone()[0]
    assert baseline == n_open


def test_model_tables_available_for_the_app(con):
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {
        "model_evaluation",
        "model_calibration",
        "model_lift",
        "model_importance",
        "model_effect_recovery",
    } <= tables


def test_scores_match_the_hidden_future(model_run, generated):
    """Oracle check, only possible with synthetic data: compare scores with what really happens."""
    scored = model_run.scored.merge(generated.hidden_truth, on="booking_id")
    assert len(scored) == len(model_run.scored)
    truth = scored["will_cancel"].astype(int)
    assert roc_auc_score(truth, scored["p_cancel"]) > 0.65
    assert scored["p_cancel"].mean() == pytest.approx(truth.mean(), rel=0.25)


def test_hidden_truth_never_reaches_the_database(con):
    columns = con.execute("SELECT DISTINCT column_name FROM information_schema.columns").df()[
        "column_name"
    ]
    assert not columns.str.contains("will_cancel").any()
