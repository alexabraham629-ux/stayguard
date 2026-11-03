"""Intake calendar helpers: which intake is open, how far away it is, what to compare it with."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _snapshot(assumptions: dict[str, Any]) -> pd.Timestamp:
    return pd.Timestamp(assumptions["project"]["snapshot_date"])


def _starts(assumptions: dict[str, Any]) -> dict[str, pd.Timestamp]:
    return {name: pd.Timestamp(d) for name, d in assumptions["intakes"].items()}


def open_intake(assumptions: dict[str, Any]) -> str:
    """The first intake whose move-in is after the snapshot (Jan-2027)."""
    snapshot = _snapshot(assumptions)
    future = {k: v for k, v in _starts(assumptions).items() if v > snapshot}
    return min(future, key=future.__getitem__)


def latest_closed_intake(assumptions: dict[str, Any]) -> str:
    """The most recent intake that has already moved in (Sep-2026)."""
    snapshot = _snapshot(assumptions)
    past = {k: v for k, v in _starts(assumptions).items() if v <= snapshot}
    return max(past, key=past.__getitem__)


def days_to_open_intake(assumptions: dict[str, Any]) -> int:
    """Days from the snapshot to the open intake's move-in: the as-of horizon (ADR-005)."""
    return int((_starts(assumptions)[open_intake(assumptions)] - _snapshot(assumptions)).days)


def comparable_intake(intake: str) -> str:
    """Same intake month one year earlier: 'Jan-2027' -> 'Jan-2026'."""
    month, year = intake.split("-")
    return f"{month}-{int(year) - 1}"
