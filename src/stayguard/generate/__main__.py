"""`python -m stayguard.generate`: generate data, write CSVs, build DuckDB, print quality report."""

from __future__ import annotations

import argparse
from pathlib import Path

from stayguard.config import DB_PATH, RAW_DIR
from stayguard.db import build_database, connect
from stayguard.generate.pipeline import generate, write_raw
from stayguard.quality.checks import format_report, run_quality_report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="override the global seed")
    parser.add_argument("--scale", type=float, default=1.0, help="volume multiplier (tests use <1)")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    data = generate(seed=args.seed, scale=args.scale)
    write_raw(data, args.raw_dir)
    build_database(data.tables, args.db, data.manifest)

    print(f"Generated in {data.manifest['generation_seconds']} s (seed {data.manifest['seed']})")
    for name, rows in data.manifest["row_counts"].items():
        print(f"  {name:<20} {rows:>8,}")
    print(f"Database: {args.db}")
    with connect(args.db) as con:
        print(format_report(run_quality_report(con)))


if __name__ == "__main__":
    main()
