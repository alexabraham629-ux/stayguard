"""Project paths and the business assumptions loaded from config/assumptions.yaml."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIG_DIR: Path = PROJECT_ROOT / "config"
ASSUMPTIONS_PATH: Path = CONFIG_DIR / "assumptions.yaml"
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
EXPORTS_DIR: Path = DATA_DIR / "exports"
DB_PATH: Path = DATA_DIR / "stayguard.duckdb"
AUDIT_DB_PATH: Path = DATA_DIR / "ai_audit.duckdb"  # separate file, see ADR-010
SQL_DIR: Path = PROJECT_ROOT / "sql"


@lru_cache(maxsize=1)
def load_assumptions(path: Path = ASSUMPTIONS_PATH) -> dict[str, Any]:
    """Return the parsed assumptions file (cached; treat the result as read-only)."""
    with path.open(encoding="utf-8") as f:
        assumptions = yaml.safe_load(f)
    if not isinstance(assumptions, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return assumptions
