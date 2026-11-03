"""`python -m stayguard.model`: train, evaluate and score; prints a report."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from stayguard.config import DB_PATH
from stayguard.model.pipeline import run_model_pipeline

REPORT_METRICS = ["roc_auc", "pr_auc", "brier", "brier_constant", "lift_top_decile", "saved_gbp"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args(argv)

    run = run_model_pipeline(args.db)
    pd.set_option("display.width", 160)
    table = run.evaluation.pivot_table(
        index=["dataset", "model"], columns="metric", values="value"
    )[REPORT_METRICS]
    print(f"Model pipeline finished in {run.seconds} s")
    print(table.round(3).to_string())
    print(f"\nChosen: {run.chosen} ({run.model_version}), by validation PR-AUC")
    print("\nTop features (permutation importance, PR-AUC drop):")
    print(run.importance.head(8)[["rank", "feature", "importance_mean"]].to_string(index=False))
    print("\nPlanted-effect recovery:")
    print(run.recovery.round(3).to_string(index=False))
    mean_p = run.scored["p_cancel"].mean()
    print(f"\nScored {len(run.scored):,} open bookings; mean p_cancel {mean_p:.3f}")


if __name__ == "__main__":
    main()
