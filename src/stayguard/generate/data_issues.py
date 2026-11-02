"""Plant the data-quality issues the validation layer must catch (CLAUDE.md §4).

Each function returns how many rows it touched, so tests can check the quality report finds
exactly what was planted.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from stayguard.generate._util import days, days_between


def plant_null_first_response(rng: np.random.Generator, leads: pd.DataFrame, share: float) -> int:
    """Blank out first_response_minutes on some contacted leads (contacted_at is kept)."""
    candidates = leads.index[leads["first_response_minutes"].notna()]
    k = int(round(share * len(candidates)))
    chosen = rng.choice(candidates.to_numpy(), size=k, replace=False)
    leads.loc[chosen, "first_response_minutes"] = pd.NA
    return k


def plant_duplicate_bookings(
    rng: np.random.Generator,
    bookings: pd.DataFrame,
    cancellations: pd.DataFrame,
    share: float,
    snapshot: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, set[int]]:
    """Re-enter some bookings a second time 1–47 hours later (same student and property).

    Returns the new frames and the ids of both the originals and their copies.
    """
    days_to_cancel = (
        bookings["booking_id"]
        .map(cancellations.set_index("booking_id")["days_after_booking"])
        .fillna(np.inf)
    )
    eligible = (
        (bookings["booked_at"] <= snapshot - pd.Timedelta(days=2))
        & (bookings["days_booked_before_intake"] >= 3)
        & (days_to_cancel >= 3)  # the copy must still be booked before it is cancelled
    )
    k = int(round(share * len(bookings)))
    originals = np.sort(rng.choice(bookings.index[eligible].to_numpy(), size=k, replace=False))

    dupes = bookings.loc[originals].copy()
    original_ids = dupes["booking_id"].to_numpy()
    dupes["booking_id"] = bookings["booking_id"].max() + np.arange(1, k + 1)
    dupes["booked_at"] = dupes["booked_at"] + pd.to_timedelta(
        rng.integers(3600, 47 * 3600, size=k), unit="s"
    )
    dupes["days_booked_before_intake"] = np.floor(
        days_between(dupes["_intake_start"], dupes["booked_at"])
    ).astype(int)

    copy_of = dupes.set_index(original_ids)
    dup_cancels = cancellations.loc[cancellations["booking_id"].isin(original_ids)].copy()
    dup_cancels["booked_at"] = dup_cancels["booking_id"].map(copy_of["booked_at"])
    dup_cancels["booking_id"] = dup_cancels["booking_id"].map(copy_of["booking_id"])
    dup_cancels["days_after_booking"] = np.floor(
        days_between(dup_cancels["cancelled_at"], dup_cancels["booked_at"])
    ).astype(int)

    bookings = pd.concat([bookings, dupes], ignore_index=True)
    cancellations = pd.concat([cancellations, dup_cancels], ignore_index=True)
    touched = {int(i) for i in original_ids} | {int(i) for i in dupes["booking_id"]}
    return bookings, cancellations, touched


def plant_cancel_before_booking(
    rng: np.random.Generator, cancellations: pd.DataFrame, n_rows: int, exclude_ids: set[int]
) -> int:
    """Move a handful of cancellation timestamps to before the booking timestamp."""
    candidates = cancellations.index[~cancellations["booking_id"].isin(exclude_ids)]
    chosen = rng.choice(candidates.to_numpy(), size=n_rows, replace=False)
    booked_at = cancellations.loc[chosen, "booked_at"]
    moved = booked_at - days(rng.uniform(1, 10, size=n_rows))
    cancellations.loc[chosen, "cancelled_at"] = moved.to_numpy()
    cancellations.loc[chosen, "days_after_booking"] = np.floor(
        days_between(moved, booked_at)
    ).astype(int)
    return n_rows


def plant_all(
    rng: np.random.Generator,
    assumptions: dict[str, Any],
    leads: pd.DataFrame,
    bookings: pd.DataFrame,
    cancellations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Apply every planted issue; `leads` is edited in place.

    Returns (bookings, cancellations, counts of planted rows).
    """
    dq = assumptions["generator"]["data_quality"]
    snapshot = pd.Timestamp(assumptions["project"]["snapshot_date"])
    n_null = plant_null_first_response(rng, leads, dq["null_first_response_share"])
    bookings, cancellations, duplicate_ids = plant_duplicate_bookings(
        rng, bookings, cancellations, dq["duplicate_booking_share"], snapshot
    )
    n_before = plant_cancel_before_booking(
        rng, cancellations, dq["cancel_before_booking_rows"], duplicate_ids
    )
    counts = {
        "duplicate_booking_rows": len(duplicate_ids) // 2,
        "null_first_response_minutes": n_null,
        "cancelled_before_booked": n_before,
        "non_gbp_bookings": int((bookings["currency"] != "GBP").sum()),
    }
    return bookings, cancellations, counts
