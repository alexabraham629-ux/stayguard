"""Demo mode: pre-recorded, genuine AI answers for when no API key is configured (CLAUDE.md §9.4).

The cache is written by the eval run (`make ai-eval`), so every entry is a real model answer
with its real verification. Nothing in it is hand-written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stayguard.ai.nl2sql import Answer
from stayguard.ai.verifier import Verification, checks_as_dicts
from stayguard.config import DATA_DIR

DEMO_CACHE = DATA_DIR / "demo_cache.json"
MAX_ROWS = 50


def entry_from(answer: Answer, verification: Verification | None) -> dict[str, Any]:
    """A JSON-serialisable record of one question, answer and verification (also used live)."""
    rows = answer.rows.head(MAX_ROWS) if answer.rows is not None else None
    alt = verification.alternative if verification else None
    return {
        "question": answer.question,
        "sql": answer.sql,
        "answer_column": answer.answer_column,
        "assumptions": answer.assumptions,
        "explanation": answer.explanation,
        "canonical_metric": answer.canonical_metric,
        "error": answer.error,
        "repaired": answer.repaired,
        "rows": json.loads(rows.to_json(orient="records", date_format="iso"))
        if rows is not None
        else None,
        "verification_status": verification.status
        if verification
        else ("blocked" if answer.error else ""),
        "checks": checks_as_dicts(verification.checks) if verification else [],
        "alternative_sql": alt.sql if alt else None,
        "model": answer.model,
        "prompt_version": answer.prompt_version,
        "latency_ms": answer.latency_ms,
        "input_tokens": answer.input_tokens,
        "output_tokens": answer.output_tokens,
    }


def save_demo_cache(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    path = path or DEMO_CACHE
    payload = {"source": "make ai-eval (live model answers, verified)", "entries": entries}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_demo_cache(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or DEMO_CACHE  # resolved at call time so tests can point it elsewhere
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["entries"]
