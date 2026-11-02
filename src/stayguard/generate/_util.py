"""Small vectorised helpers shared by the generator modules."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sigmoid(x: np.ndarray) -> np.ndarray:
    """Logistic function, mapping log-odds to probabilities."""
    return 1.0 / (1.0 + np.exp(-x))


def logit(p: float) -> float:
    """Log-odds of a probability."""
    return float(np.log(p / (1.0 - p)))


def sample_categorical(u: np.ndarray, probs: np.ndarray) -> np.ndarray:
    """Pick one category per row from row-wise `probs` (n, k), using uniforms `u` (n,)."""
    cum = np.cumsum(probs, axis=1)
    cum[:, -1] = 1.0  # guard against floating-point round-off
    return (u[:, None] > cum).sum(axis=1)


def days(n: np.ndarray | float) -> pd.TimedeltaIndex:
    """Timedelta of (fractional) days, vectorised."""
    return pd.to_timedelta(np.asarray(n, dtype=float) * 86_400.0, unit="s")


def days_between(later: pd.Series, earlier: pd.Series) -> np.ndarray:
    """Fractional days from `earlier` to `later`."""
    return ((later - earlier).dt.total_seconds() / 86_400.0).to_numpy()
