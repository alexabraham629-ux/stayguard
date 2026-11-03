"""Audit log of every AI request, in its own DuckDB file (ADR-010).

The main database is always opened read-only by the app, so AI calls are logged to
data/ai_audit.duckdb instead. Each write opens and closes a short connection.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from stayguard.config import AUDIT_DB_PATH

DDL = """
CREATE TABLE IF NOT EXISTS ai_audit (
    ts                   TIMESTAMP NOT NULL,
    session_id           VARCHAR,
    feature              VARCHAR NOT NULL,   -- nl2sql | verifier | memo | eval | mcp
    prompt_version       VARCHAR,
    model                VARCHAR,
    question             VARCHAR,
    generated_sql        VARCHAR,
    verification_status  VARCHAR,     -- verified | mismatch | unverifiable | blocked | error | ran
    checks               VARCHAR,            -- JSON list of {name, status, detail}
    latency_ms           INTEGER,
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    error                VARCHAR,
    demo_mode            BOOLEAN
)
"""
_LOCK = threading.Lock()


@dataclass
class AuditRecord:
    feature: str
    question: str = ""
    prompt_version: str = ""
    model: str = ""
    generated_sql: str | None = None
    verification_status: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    demo_mode: bool = False
    session_id: str = ""
    ts: datetime = field(default_factory=datetime.now)


class AuditLog:
    def __init__(self, path: Path = AUDIT_DB_PATH) -> None:
        self.path = path

    def log(self, record: AuditRecord) -> None:
        row = asdict(record)
        row["checks"] = json.dumps(row["checks"], default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, duckdb.connect(str(self.path)) as con:
            con.execute(DDL)
            con.execute(
                f"INSERT INTO ai_audit ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                list(row.values()),
            )

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=[f.split()[0] for f in _columns()])
        with _LOCK, duckdb.connect(str(self.path), read_only=True) as con:
            return con.execute("SELECT * FROM ai_audit ORDER BY ts DESC").df()


VERIFIER_STATUSES = ("verified", "mismatch", "unverifiable")


def verified_share(log: pd.DataFrame) -> float | None:
    """Share of verifier-checked answers that verified; None if the verifier has seen none.

    Only Ask the Data answers pass through the verifier. Blocked and failed requests, and MCP
    queries (status "ran"), are excluded rather than counted as failures.
    """
    checked = log.loc[log["verification_status"].isin(VERIFIER_STATUSES)]
    return float((checked["verification_status"] == "verified").mean()) if len(checked) else None


def _columns() -> list[str]:
    body = DDL.split("(", 1)[1].rsplit(")", 1)[0]
    return [line.strip() for line in body.splitlines() if line.strip()]
