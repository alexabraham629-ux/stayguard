"""Model evaluation: discrimination, calibration, lift, importance and business value."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from stayguard.model.features import FEATURES


def _top_share_mask(scores: np.ndarray, share: float) -> np.ndarray:
    """Boolean mask of the top `share` of rows by score (stable tie-break by position)."""
    n_top = int(round(share * len(scores)))
    order = np.argsort(-scores, kind="mergesort")
    mask = np.zeros(len(scores), dtype=bool)
    mask[order[:n_top]] = True
    return mask


def classification_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """ROC-AUC, PR-AUC, Brier, and lift / gains in the top decile."""
    y = np.asarray(y)
    base_rate = float(y.mean())
    top = _top_share_mask(p, 0.10)
    return {
        "n": float(len(y)),
        "base_rate": base_rate,
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        # Brier of always predicting the base rate: a model must beat this to be useful.
        "brier_constant": base_rate * (1 - base_rate),
        "lift_top_decile": float(y[top].mean() / base_rate),
        "gains_top_decile": float(y[top].sum() / y.sum()),
    }


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Predicted vs observed rate in equal-size bins of predicted probability."""
    df = pd.DataFrame({"y": np.asarray(y), "p": p})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False) + 1
    return (
        df.groupby("bin")
        .agg(n=("y", "size"), mean_predicted=("p", "mean"), observed_rate=("y", "mean"))
        .reset_index()
    )


def lift_table(y: np.ndarray, p: np.ndarray) -> pd.DataFrame:
    """Decile 1 = highest risk. Lift = decile cancellation rate / overall rate."""
    df = pd.DataFrame({"y": np.asarray(y), "p": p})
    df["decile"] = 10 - pd.qcut(df["p"].rank(method="first"), 10, labels=False)
    table = (
        df.groupby("decile")
        .agg(n=("y", "size"), cancellations=("y", "sum"), mean_predicted=("p", "mean"))
        .reset_index()
    )
    table["cancellation_rate"] = table["cancellations"] / table["n"]
    table["lift"] = table["cancellation_rate"] / df["y"].mean()
    table["cumulative_gains"] = table["cancellations"].cumsum() / df["y"].sum()
    return table


def importance_table(
    model: Any, X: pd.DataFrame, y: np.ndarray, seed: int, n_repeats: int = 5
) -> pd.DataFrame:
    """Permutation importance on held-out data: the drop in PR-AUC when a feature is shuffled."""
    result = permutation_importance(
        model,
        X[FEATURES],
        y,
        scoring="average_precision",
        n_repeats=n_repeats,
        random_state=seed,
    )
    table = pd.DataFrame(
        {
            "feature": FEATURES,
            "importance_mean": result.importances_mean,
            "importance_std": result.importances_std,
        }
    ).sort_values("importance_mean", ascending=False, ignore_index=True)
    table["rank"] = np.arange(1, len(table) + 1)
    return table


def business_value(
    frame: pd.DataFrame, p: np.ndarray, top_share: float, save_rate: float
) -> dict[str, float]:
    """Commission saved if the team works the top `top_share` of the queue, ranked by
    commission x p_cancel, and saves `save_rate` of the commission that would have cancelled."""
    commission = frame["commission_gbp"].to_numpy()
    lost = commission * frame["target"].to_numpy()
    worked = _top_share_mask(commission * p, top_share)
    return {
        "saved_gbp": float(lost[worked].sum() * save_rate),
        "random_saved_gbp": float(lost.sum() * top_share * save_rate),  # expected, random calls
        "perfect_saved_gbp": float(
            lost[_top_share_mask(lost + 1e-9 * commission, top_share)].sum() * save_rate
        ),
        "total_lost_gbp": float(lost.sum()),
    }
