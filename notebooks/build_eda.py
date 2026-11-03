"""Build notebooks/01_eda.ipynb: define the cells, execute them in a real Jupyter kernel, save outputs.

    uv run python notebooks/build_eda.py

Uses only jupyter_client + ipykernel (already installed), so every output is a genuine run.
"""

from __future__ import annotations

import json
import queue
from pathlib import Path

from jupyter_client.manager import start_new_kernel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "notebooks" / "01_eda.ipynb"

CELLS: list[tuple[str, str]] = [
    (
        "markdown",
        """# StayGuard — exploratory analysis

**Question:** how much of the commission we book actually lands, what makes bookings cancel, and where
should the business act?

> **Synthetic data, portfolio project.** The data is simulated with known effects planted
> (`docs/DATA_GENERATION.md`), so this analysis can be checked against ground truth. All money is in
> GBP; outcome rates use intakes that have already moved in.""",
    ),
    (
        "code",
        """import duckdb, pandas as pd
from pathlib import Path
pd.set_option("display.precision", 3); pd.set_option("display.width", 120)

ROOT = Path.cwd() if (Path.cwd() / "data").exists() else Path.cwd().parent
con = duckdb.connect(str(ROOT / "data" / "stayguard.duckdb"), read_only=True)
def q(sql): return con.execute(sql).df()
def sql_file(name): return q((ROOT / "sql" / f"{name}.sql").read_text(encoding="utf-8"))
q("SELECT snapshot_date, seed FROM meta_build")""",
    ),
    (
        "markdown",
        """## 1. Three currencies: totals must be converted first
Bookings are priced in GBP, AUD and EUR. Adding local amounts together is a classic silent error, so
every total in StayGuard uses the `*_gbp` columns of `v_bookings_gbp`.""",
    ),
    (
        "code",
        """q('''SELECT country, currency, COUNT(*) AS bookings,
       ROUND(SUM(commission_local)) AS commission_local, ROUND(SUM(commission_gbp)) AS commission_gbp
FROM v_bookings_gbp GROUP BY ALL ORDER BY commission_gbp DESC''')""",
    ),
    (
        "code",
        """naive, right = q("SELECT SUM(commission_local) AS a, SUM(commission_gbp) AS b FROM v_bookings_gbp").iloc[0]
print(f"Naive local-currency total £{naive:,.0f} vs converted £{right:,.0f}: off by {naive / right - 1:.1%}")""",
    ),
    ("markdown", "## 2. Where does the funnel leak?"),
    (
        "code",
        """f = sql_file("01_funnel_by_city_intake").query("is_closed_intake")
stages = f[["leads", "contacted", "shortlisted", "booked", "moved_in"]].sum()
pd.DataFrame({"students": stages, "share_of_enquiries": stages / stages["leads"],
              "kept_from_previous_step": stages / stages.shift(1)})""",
    ),
    ("markdown", "## 3. Why and when do bookings cancel?"),
    (
        "code",
        """sql_file("04_cancellation_reasons_pareto")[["cancel_reason", "cancellations", "share_pct", "running_share_pct", "in_vital_few"]]""",
    ),
    (
        "code",
        """curve = sql_file("03_cohort_cancellation_curve").query("is_closed_intake")
by_bucket = curve.groupby(["bucket_order", "bucket_label"])["cancellations_in_bucket"].sum()
(by_bucket / by_bucket.sum()).rename("share_of_cancellations").to_frame()""",
    ),
    (
        "markdown",
        """## 4. Who cancels? Visa status, deposit and lead time
These are the planted effects. Section 4c is the important subtlety: the action queue works on bookings
that are still alive 72 days before move-in, and for that group the lead-time effect reverses.""",
    ),
    (
        "code",
        """v = sql_file("09_source_country_visa_risk")
v.query("not small_sample").sort_values("cancellation_pct", ascending=False).head(6)[
    ["source_country", "visa_status_at_booking", "bookings", "cancellation_pct", "visa_refusal_pct"]]""",
    ),
    (
        "code",
        """q('''SELECT deposit_paid, COUNT(*) AS bookings, ROUND(AVG(is_cancelled::INT), 3) AS cancellation_rate
FROM v_bookings_gbp WHERE is_closed_intake GROUP BY 1''')""",
    ),
    (
        "code",
        """# 4c. Lead time: all bookings vs bookings still alive 72 days before move-in (ADR-005)
band = '''CASE WHEN days_booked_before_intake < 90 THEN '1: under 90 days'
               WHEN days_booked_before_intake < 180 THEN '2: 90-179 days' ELSE '3: 180+ days' END'''
q(f'''WITH b AS (SELECT *, {band} AS lead_time,
                       CAST(intake_start_date - 72 AS TIMESTAMP) AS as_of FROM v_bookings_gbp WHERE is_closed_intake)
SELECT lead_time,
       ROUND(AVG(is_cancelled::INT), 3) AS cancel_rate_all_bookings,
       ROUND(AVG(COALESCE(is_cancelled AND cancelled_at >= as_of, FALSE)::INT)
             FILTER (WHERE booked_at < as_of AND NOT COALESCE(is_cancelled AND cancelled_at < as_of, FALSE)), 3)
             AS cancel_rate_if_alive_72_days_out
FROM b GROUP BY 1 ORDER BY 1''')""",
    ),
    ("markdown", "## 5. Is postgraduate demand softening?"),
    (
        "code",
        """pg = sql_file("11_yoy_pg_demand_by_city")
seg = pg.groupby(["segment", "academic_year"])["pg_bookings"].sum().unstack()
seg.assign(change_2025_26=seg["2025-26"] / seg["2024-25"] - 1)""",
    ),
    ("markdown", "## 6. Operations: response time and agent workload"),
    ("code", """sql_file("08_response_time_vs_conversion")"""),
    (
        "code",
        """sql_file("06_agent_leaderboard").sort_values("load_days", ascending=False).head(4)[
    ["agent_name", "team", "open_bookings", "max_daily_capacity", "load_days", "cancellation_pct"]]""",
    ),
    ("markdown", "## 7. What will land from the open intake?"),
    (
        "code",
        """sql_file("07_revenue_at_risk_by_city").head(5)[
    ["city", "open_bookings", "booked_commission_gbp", "expected_net_commission_gbp", "revenue_at_risk_gbp", "share_of_total_risk_pct"]]""",
    ),
    (
        "code",
        """ev = q("SELECT * FROM model_evaluation WHERE dataset LIKE 'validation%'")
ev.pivot_table(index="model", columns="metric", values="value")[["roc_auc", "pr_auc", "lift_top_decile", "saved_gbp"]]""",
    ),
    (
        "markdown",
        "## Takeaways\nComputed from the cells above, so the numbers always match this run.",
    ),
    (
        "code",
        """open_ = sql_file("07_revenue_at_risk_by_city")
enc, rar = open_["expected_net_commission_gbp"].sum(), open_["revenue_at_risk_gbp"].sum()
top = open_.iloc[0]
pareto = sql_file("04_cancellation_reasons_pareto")
vital_rows = pareto.loc[pareto["in_vital_few"]]
vital, vital_share = vital_rows["cancel_reason"].tolist(), vital_rows["running_share_pct"].iloc[-1]
print(f"1. Of £{enc + rar:,.0f} open commission, £{enc:,.0f} is expected to land; {top.city} holds {top.share_of_total_risk_pct:.0f}% of the £{rar:,.0f} at risk.")
print(f"2. {len(vital)} of 7 reasons ({', '.join(vital)}) explain {vital_share:.1f}% of cancellations.")
print(f"3. Biggest funnel leak: {(1 - stages['shortlisted'] / stages['contacted']):.0%} of contacted students never shortlist.")
print(f"4. UK non-London PG bookings changed {seg.loc['UK non-London', '2025-26'] / seg.loc['UK non-London', '2024-25'] - 1:+.0%} in 2025-26.")""",
    ),
]


def _source(text: str) -> list[str]:
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]]


def run() -> None:
    km, kc = start_new_kernel(kernel_name="python3", cwd=str(ROOT / "notebooks"))
    cells, count = [], 0
    try:
        for kind, text in CELLS:
            if kind == "markdown":
                cells.append({"cell_type": "markdown", "metadata": {}, "source": _source(text)})
                continue
            count += 1
            msg_id = kc.execute(text)
            outputs = []
            while True:
                try:
                    msg = kc.get_iopub_msg(timeout=120)
                except queue.Empty as e:
                    raise RuntimeError("kernel timed out") from e
                if msg["parent_header"].get("msg_id") != msg_id:
                    continue
                t, c = msg["msg_type"], msg["content"]
                if t == "stream":
                    outputs.append(
                        {"output_type": "stream", "name": c["name"], "text": _source(c["text"])}
                    )
                elif t in ("execute_result", "display_data"):
                    data = {k: v for k, v in c["data"].items() if k in ("text/plain", "text/html")}
                    out = {"output_type": t, "metadata": {}, "data": data}
                    if t == "execute_result":
                        out["execution_count"] = count
                    outputs.append(out)
                elif t == "error":
                    raise RuntimeError(f"Cell {count} failed: {c['ename']}: {c['evalue']}")
                elif t == "status" and c["execution_state"] == "idle":
                    break
            cells.append(
                {
                    "cell_type": "code",
                    "execution_count": count,
                    "metadata": {},
                    "outputs": outputs,
                    "source": _source(text),
                }
            )
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} ({count} code cells executed)")


if __name__ == "__main__":
    run()
