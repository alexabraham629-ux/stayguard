"""What-if simulator: how much Expected Net Commission can the levers add to the open intake?

Three levers, applied in this order so nothing is counted twice:
1. Chase deposits: some no-deposit students pay one; their risk falls to the model's
   "same booking, deposit paid" prediction (p_cancel_if_deposit).
2. Work the call queue: the top share of open bookings by remaining expected loss are called, and
   the save rate of their at-risk commission is kept.
3. Response-time SLA: more of the leads still in the pipeline are answered within the SLA, and
   convert like historically fast-answered leads.

Every lever is an ASSUMPTION-driven projection, not a forecast: levers 1 and 3 read causal effects
off observational data. The simulator page shows each assumption next to the result.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from stayguard.calendar import open_intake
from stayguard.metrics import Filters, MetricData


@dataclass(frozen=True)
class WhatIfInputs:
    share_of_queue_worked: float  # 0..1 of open bookings called
    save_rate: float  # 0..1 of a called booking's at-risk commission kept
    deposit_chase_success: float  # 0..1 of no-deposit open bookings that pay when asked
    sla_target_share: float  # 0..1 of pipeline leads answered within the SLA


@dataclass(frozen=True)
class PipelineStats:
    """Inputs for the SLA lever, measured from the data."""

    open_pipeline_leads: int  # open-intake leads not yet booked or lost
    current_sla_share: float  # historical share of leads answered within the SLA
    conversion_within_sla: float
    conversion_outside_sla: float
    avg_commission_gbp: float  # per open booking
    avg_survival: float  # 1 - mean p_cancel of open bookings


@dataclass(frozen=True)
class WhatIfResult:
    base_enc_gbp: float
    deposit_gain_gbp: float
    calls_gain_gbp: float
    sla_gain_gbp: float
    calls_made: int
    deposits_collected: float

    @property
    def projected_enc_gbp(self) -> float:
        return self.base_enc_gbp + self.deposit_gain_gbp + self.calls_gain_gbp + self.sla_gain_gbp


def open_bookings(d: MetricData, f: Filters) -> pd.DataFrame:
    """Open bookings with the columns the simulator needs."""
    b = f.apply(d.bookings)
    b = b.loc[b["is_open"]].copy()
    if "p_cancel_if_deposit" not in b:
        b["p_cancel_if_deposit"] = b["p_cancel"]  # baseline scores: deposit lever has no effect
    return b[["booking_id", "commission_gbp", "p_cancel", "p_cancel_if_deposit", "deposit_paid"]]


def pipeline_stats(d: MetricData, f: Filters) -> PipelineStats:
    sla = d.assumptions["operations"]["late_first_response_minutes"]
    leads = f.apply(d.leads)
    history = leads.loc[leads["is_closed_intake"] & leads["first_response_minutes"].notna()]
    within = history["first_response_minutes"] <= sla
    booked = history["status"] == "booked"
    pipeline = leads.loc[
        (leads["intake"] == open_intake(d.assumptions))
        & leads["status"].isin(["new", "contacted", "shortlisted"])
    ]
    ob = open_bookings(d, f)
    return PipelineStats(
        open_pipeline_leads=len(pipeline),
        current_sla_share=float(within.mean()),
        conversion_within_sla=float(booked[within].mean()),
        conversion_outside_sla=float(booked[~within].mean()),
        avg_commission_gbp=float(ob["commission_gbp"].mean()) if len(ob) else 0.0,
        avg_survival=float(1 - ob["p_cancel"].mean()) if len(ob) else 0.0,
    )


def simulate(bookings: pd.DataFrame, stats: PipelineStats, inputs: WhatIfInputs) -> WhatIfResult:
    """Apply the three levers in order and return the ENC bridge."""
    c = bookings["commission_gbp"].to_numpy(dtype=float)
    p = bookings["p_cancel"].to_numpy(dtype=float)
    p_dep = bookings["p_cancel_if_deposit"].to_numpy(dtype=float)
    no_deposit = ~bookings["deposit_paid"].to_numpy(dtype=bool)
    base_enc = float((c * (1 - p)).sum())

    # 1. Deposits: expected risk after chasing (a share of no-deposit students pay).
    p_after = np.where(no_deposit, p + inputs.deposit_chase_success * (p_dep - p), p)
    deposit_gain = float((c * (p - p_after)).sum())

    # 2. Calls: rank by remaining expected loss, call the top share, keep save_rate of it.
    expected_loss = c * p_after
    n_calls = int(round(inputs.share_of_queue_worked * len(c)))
    top = np.argsort(-expected_loss, kind="mergesort")[:n_calls]
    calls_gain = float(expected_loss[top].sum() * inputs.save_rate)

    # 3. SLA: extra pipeline leads answered in time, converting at the within-SLA rate.
    extra_share = max(0.0, inputs.sla_target_share - stats.current_sla_share)
    uplift = max(0.0, stats.conversion_within_sla - stats.conversion_outside_sla)
    sla_gain = (
        stats.open_pipeline_leads
        * extra_share
        * uplift
        * stats.avg_commission_gbp
        * stats.avg_survival
    )

    return WhatIfResult(
        base_enc_gbp=base_enc,
        deposit_gain_gbp=deposit_gain,
        calls_gain_gbp=calls_gain,
        sla_gain_gbp=float(sla_gain),
        calls_made=n_calls,
        deposits_collected=float(no_deposit.sum() * inputs.deposit_chase_success),
    )
