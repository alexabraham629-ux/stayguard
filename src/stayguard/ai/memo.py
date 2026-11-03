"""Grounded weekly memo + number checker (CLAUDE.md §9.3).

1. Build a metrics snapshot (JSON) from metrics.py, the KPI layer and the SQL library.
2. The model writes a memo ONLY from that JSON.
3. The checker extracts every number in the memo and requires each to match a JSON value
   (allowing rounding, percentages of fractions, and £k / £m). Unmatched numbers -> regenerate
   once with feedback; still unmatched -> the memo is shown with those numbers highlighted.

`python -m stayguard.ai.memo` generates data/memo_cache.json (needs an API key).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from stayguard.ai.client import AIError, LLMClient
from stayguard.ai.prompts import load_prompt
from stayguard.calendar import (
    comparable_intake,
    days_to_open_intake,
    latest_closed_intake,
    open_intake,
)
from stayguard.config import DATA_DIR
from stayguard.kpis import executive_kpis
from stayguard.metrics import (
    Filters,
    MetricData,
    live_commission_loss_share,
    saveable_revenue_gbp,
)

PROMPT_NAME = "memo_v1"
MEMO_CACHE = DATA_DIR / "memo_cache.json"
SMALL_COUNT_LIMIT = 10  # digits 0-10 ("3 actions", "2 agents") are allowed without a JSON source

MEMO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["title", "detail"],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "owner": {"type": "string"},
                    "expected_impact": {"type": "string"},
                },
                "required": ["action", "owner", "expected_impact"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "insights", "recommendations"],
    "additionalProperties": False,
}


# --- Snapshot -------------------------------------------------------------------------------------


def _r(x: float, digits: int = 4) -> float:
    return float(round(float(x), digits))


def build_snapshot(
    d: MetricData, run: Callable[[str], pd.DataFrame], tables: Callable[[str], pd.DataFrame]
) -> dict[str, Any]:
    """Everything the memo may cite, as plain JSON. `run(name)` runs a named SQL query;
    `tables(name)` reads a pipeline table (model_evaluation)."""
    a = d.assumptions
    kpis = {
        k.label: {
            "value": _r(k.value, 2 if k.unit == "gbp" else 4),
            "change": _r(k.delta, 4),
            "change_kind": "relative change"
            if k.delta_kind == "pct_change"
            else "percentage points",
            "compared_with": k.comparison,
        }
        for k in executive_kpis(d, Filters())
    }
    days_left = days_to_open_intake(a)
    now, then = open_intake(a), comparable_intake(open_intake(a))
    kpis["Revenue at risk"]["share_of_live_commission_at_risk"] = _r(
        live_commission_loss_share(d, Filters(), now, days_left), 4
    )
    kpis["Revenue at risk"]["comparable_intake_share_actually_lost"] = _r(
        live_commission_loss_share(d, Filters(), then, days_left), 4
    )
    risk = run("07_revenue_at_risk_by_city").head(3)
    reasons = run("04_cancellation_reasons_pareto").head(3)
    visa = run("09_source_country_visa_risk")
    visa = visa.loc[
        ~visa["small_sample"] & visa["visa_status_at_booking"].isin(["pending", "not_applied"])
    ]
    visa = visa.sort_values("cancellation_pct", ascending=False).head(3)
    agents = run("06_agent_leaderboard").sort_values("load_days", ascending=False)
    channels = run("12_channel_unit_economics")
    pg = run("11_yoy_pg_demand_by_city")
    seg = pg.groupby(["segment", "academic_year"])["pg_bookings"].sum().unstack()
    queue = run("13_action_queue")
    ev = tables("model_evaluation")
    candidates = ev.loc[
        ev["dataset"].str.startswith("validation")
        & ~ev["model"].isin(["baseline_segment_rate", "leaky_demo"])
    ]
    # The chosen model is the candidate with the best validation PR-AUC (same rule as the pipeline).
    pr_auc = candidates.loc[candidates["metric"] == "pr_auc"].set_index("model")["value"]
    validation = candidates.loc[candidates["model"] == pr_auc.idxmax()].set_index("metric")["value"]

    return {
        "as_of": str(a["project"]["snapshot_date"]),
        "open_intake": open_intake(a),
        "comparable_intake": comparable_intake(open_intake(a)),
        "latest_closed_intake": latest_closed_intake(a),
        "kpis": kpis,
        "revenue_at_risk_top_cities": [
            {
                "city": r.city,
                "revenue_at_risk_gbp": _r(r.revenue_at_risk_gbp, 0),
                "share_of_total_risk_pct": _r(r.share_of_total_risk_pct, 1),
            }
            for r in risk.itertuples()
        ],
        "top_cancellation_reasons": [
            {
                "reason": r.cancel_reason,
                "share_pct": _r(r.share_pct, 1),
                "running_share_pct": _r(r.running_share_pct, 1),
            }
            for r in reasons.itertuples()
        ],
        "highest_risk_visa_segments": [
            {
                "source_country": r.source_country,
                "visa_status": r.visa_status_at_booking,
                "bookings": int(r.bookings),
                "cancellation_pct": _r(r.cancellation_pct, 1),
                "visa_refusal_pct": _r(r.visa_refusal_pct, 1),
            }
            for r in visa.itertuples()
        ],
        "overloaded_agents": {
            "agents": [
                {
                    "agent_name": r.agent_name,
                    "team": r.team,
                    "load_days": _r(r.load_days, 2),
                    "cancellation_pct": _r(r.cancellation_pct, 1),
                }
                for r in agents.head(2).itertuples()
            ],
            "team_median_load_days": _r(agents.iloc[2:]["load_days"].median(), 2),
        },
        "channels": [
            {
                "channel": r.channel,
                "conversion_pct": _r(r.conversion_pct, 1),
                "cancellation_pct": _r(r.cancellation_pct, 1),
                "realised_commission_per_lead_gbp": _r(r.realised_commission_per_lead_gbp, 0),
            }
            for r in channels.itertuples()
        ],
        "pg_bookings_change_2025_26_vs_2024_25_pct": {
            s: _r(100 * (seg.loc[s, "2025-26"] / seg.loc[s, "2024-25"] - 1), 1) for s in seg.index
        },
        "call_queue": {
            "open_bookings": len(queue),
            "calls_that_fit_today": int(queue["call_today"].sum()),
            "calls_over_capacity": int((~queue["call_today"]).sum()),
            "saveable_if_top_share_called_gbp": _r(saveable_revenue_gbp(d), 0),
            "assumed_queue_share_called": a["operations"]["queue_top_share"],
            "assumed_save_rate": a["operations"]["intervention_save_rate"],
        },
        "risk_model": {
            "share_of_cancellations_in_riskiest_10pct": _r(validation["gains_top_decile"], 3),
            "riskiest_10pct_cancel_rate_vs_average_x": _r(validation["lift_top_decile"], 2),
        },
    }


# --- Number checker -------------------------------------------------------------------------------

_LABELS = re.compile(r"\b(?:Sep|Jan)-20\d\d\b|\b20\d\d-\d\d\b|\b20[2-3]\d\b")
_NUMBER = re.compile(
    r"(?P<sign>[-−+])?(?P<cur>[£$€])?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"\s?(?P<suffix>%|pp|k\b|m\b|bn\b|x\b)?",
    flags=re.IGNORECASE,
)
_MULTIPLIER = {"k": 1e3, "m": 1e6, "bn": 1e9}


@dataclass
class NumberMatch:
    text: str
    matched: bool


def _numbers(obj: Any) -> Iterator[float]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v)


def memo_text(memo: dict[str, Any]) -> str:
    parts = [memo.get("headline", "")]
    for i in memo.get("insights", []):
        parts += [i.get("title", ""), i.get("detail", "")]
    for r in memo.get("recommendations", []):
        parts += [r.get("action", ""), r.get("owner", ""), r.get("expected_impact", "")]
    return "\n".join(parts)


def check_numbers(text: str, snapshot: dict[str, Any]) -> list[NumberMatch]:
    """Every number in `text`, and whether it matches a value in `snapshot`."""
    sources = list(_numbers(snapshot))
    cleaned = _LABELS.sub(" ", text)
    results = []
    for m in _NUMBER.finditer(cleaned):
        digits = m.group("int").replace(",", "")
        decimals = m.group("dec") or ""
        n = float(digits + decimals)
        if m.group("sign") in ("-", "−"):
            n = -n
        suffix = (m.group("suffix") or "").lower()
        scale = _MULTIPLIER.get(suffix, 1.0)
        value = n * scale
        half_step = 0.5 * 10 ** -(len(decimals) - 1 if decimals else 0) * scale
        if not suffix and not decimals and abs(n) <= SMALL_COUNT_LIMIT:
            results.append(NumberMatch(m.group(0).strip(), True))
            continue
        candidates = []
        for s in sources:
            candidates += [s, -s]
            if suffix in ("%", "pp") or abs(s) <= 1.5:
                candidates += [s * 100, -s * 100]
        ok = any(abs(value - c) <= max(half_step, 0.005 * abs(c)) for c in candidates)
        results.append(NumberMatch(m.group(0).strip(), ok))
    return results


# --- Generation -----------------------------------------------------------------------------------


@dataclass
class Memo:
    memo: dict[str, Any]
    numbers: list[NumberMatch]
    attempts: int
    model: str
    prompt_version: str = PROMPT_NAME
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    @property
    def unmatched(self) -> list[str]:
        return [n.text for n in self.numbers if not n.matched]

    @property
    def passed(self) -> bool:
        return not self.unmatched


def generate_memo(client: LLMClient, snapshot: dict[str, Any]) -> Memo:
    """Write the memo, check every number, regenerate once if any number is not in the JSON."""
    system = load_prompt(PROMPT_NAME).body
    payload = json.dumps(snapshot, indent=2)
    user = f"Metrics snapshot (JSON):\n```json\n{payload}\n```"
    memo = None
    for attempt in (1, 2):
        response = client.complete_json(system=system, user=user, schema=MEMO_SCHEMA)
        numbers = check_numbers(memo_text(response.data), snapshot)
        if memo is None:
            memo = Memo(response.data, numbers, attempt, client.model)
        else:
            memo.memo, memo.numbers, memo.attempts = response.data, numbers, attempt
        memo.input_tokens += response.input_tokens
        memo.output_tokens += response.output_tokens
        memo.latency_ms += response.latency_ms
        if memo.passed:
            break
        user += (
            "\n\nYour previous memo used numbers that are not in the JSON: "
            + ", ".join(memo.unmatched)
            + ". Rewrite it using only numbers that appear in the JSON."
        )
    return memo


def save_memo(memo: Memo, snapshot: dict[str, Any]) -> None:
    payload = asdict(memo) | {
        "unmatched": memo.unmatched,
        "passed": memo.passed,
        "snapshot": snapshot,
    }
    MEMO_CACHE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_memo(path: Path | None = None) -> dict[str, Any] | None:
    path = path or MEMO_CACHE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    from stayguard.ai.audit import AuditLog, AuditRecord
    from stayguard.ai.client import AnthropicClient
    from stayguard.db import connect
    from stayguard.metrics import load_metric_data
    from stayguard.sql_runner import run_query

    with connect() as con:
        data = load_metric_data(con)
        snapshot = build_snapshot(
            data, lambda n: run_query(con, n), lambda t: con.execute(f"SELECT * FROM {t}").df()
        )
    try:
        client = AnthropicClient()
        memo = generate_memo(client, snapshot)
    except AIError as e:
        raise SystemExit(f"Memo not generated: {e}") from e
    save_memo(memo, snapshot)
    AuditLog().log(
        AuditRecord(
            feature="memo",
            prompt_version=PROMPT_NAME,
            model=memo.model,
            verification_status="verified" if memo.passed else "mismatch",
            checks=[
                {
                    "name": "Number checker",
                    "status": "pass" if memo.passed else "fail",
                    "detail": f"unmatched: {memo.unmatched}",
                }
            ],
            latency_ms=memo.latency_ms,
            input_tokens=memo.input_tokens,
            output_tokens=memo.output_tokens,
        )
    )
    print(json.dumps(memo.memo, indent=2))
    print(
        f"\nNumber check: {'PASS' if memo.passed else 'FAIL'} after {memo.attempts} attempt(s)."
        + (f" Unmatched: {memo.unmatched}" if memo.unmatched else "")
    )


if __name__ == "__main__":
    main()
