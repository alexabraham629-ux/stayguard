"""Candidate models: an interpretable logistic regression and gradient-boosted trees."""

from __future__ import annotations

from typing import Any

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from stayguard.model.features import CATEGORICAL, NUMERIC

MODEL_VERSIONS = {"logistic_regression": "logreg_v1", "gradient_boosting": "hgb_v1"}


def make_logistic_regression() -> Pipeline:
    """Baseline ML model: one-hot categories, imputed + scaled numerics, L2 logistic regression."""
    preprocess = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                        ("scale", StandardScaler()),
                    ]
                ),
                NUMERIC,
            ),
        ]
    )
    return Pipeline([("prep", preprocess), ("model", LogisticRegression(C=1.0, max_iter=2000))])


def make_gradient_boosting(seed: int) -> HistGradientBoostingClassifier:
    """Trees with native categorical and missing-value support; fixed settings, no early stopping
    (so results are deterministic)."""
    return HistGradientBoostingClassifier(
        categorical_features="from_dtype",
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=15,
        min_samples_leaf=40,
        l2_regularization=1.0,
        early_stopping=False,
        random_state=seed,
    )


def make_candidates(seed: int) -> dict[str, Any]:
    return {
        "logistic_regression": make_logistic_regression(),
        "gradient_boosting": make_gradient_boosting(seed),
    }
