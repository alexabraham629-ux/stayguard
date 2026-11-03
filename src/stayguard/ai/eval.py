"""Run the 15-question NL-to-SQL eval against the live model (`make ai-eval`, needs an API key).

For each question: generate SQL, verify it, grade it against the hand-written gold query, log it
to the audit table, and keep the genuine answer for the demo cache. The headline is not only
accuracy but "wrong but verified": an incorrect answer that still got a Verified badge, which
is exactly what the verifier exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from stayguard.ai.audit import AuditLog, AuditRecord
from stayguard.ai.client import AIError, AnthropicClient, LLMClient
from stayguard.ai.demo import entry_from, save_demo_cache
from stayguard.ai.guardrails import check_sql, run_readonly
from stayguard.ai.nl2sql import Answer, answer_question
from stayguard.ai.verifier import Verification, checks_as_dicts, compare_results, verify
from stayguard.config import PROJECT_ROOT
from stayguard.db import connect
from stayguard.metrics import MetricData, load_metric_data

QUESTIONS = PROJECT_ROOT / "tests" / "ai_eval" / "questions.yaml"
RESULTS_DIR = PROJECT_ROOT / "tests" / "ai_eval" / "results"
# Approximate list price per million tokens (input, output) for cost reporting only.
PRICE_PER_MTOK = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def gold_answer(con: duckdb.DuckDBPyConnection, q: dict[str, Any]) -> Answer:
    sql = check_sql(q["gold_sql"])
    return Answer(
        question=q["question"], sql=sql, answer_column=q["gold_column"], rows=run_readonly(con, sql)
    )


def grade(q: dict[str, Any], ai: Answer, gold: Answer | None) -> tuple[bool, str]:
    """Did the AI get it right? Returns (passed, reason)."""
    if q["expect"] == "blocked":
        if ai.error and ai.error.startswith("Blocked"):
            return True, "Guardrails blocked the query."
        if ai.ok:
            text = " ".join(map(str, ai.rows.to_numpy().ravel())).lower()
            harmless = ai.rows.shape[0] <= 1 and (
                "not" in text or "cannot" in text or ai.rows.empty
            )
            return (
                harmless,
                "Model declined with a harmless reply." if harmless else "Returned data.",
            )
        return True, f"Nothing ran ({ai.error})."
    if not ai.ok:
        return False, f"No answer: {ai.error}"
    if q["expect"] == "judgement":
        ok = bool(ai.assumptions)
        return (
            ok,
            "Answered and stated assumptions." if ok else "Answered without stating assumptions.",
        )
    check = compare_results(ai, gold)
    return check.status == "pass", check.detail


def run_eval(
    client: LLMClient,
    con: duckdb.DuckDBPyConnection,
    data: MetricData,
    audit: AuditLog | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    questions = questions or load_questions()
    results, demo_entries = [], []
    for q in questions:
        ai = answer_question(q["question"], con, client)
        verification: Verification | None = verify(ai, con, client, data) if ai.ok else None
        gold = gold_answer(con, q) if q["expect"] == "answer" else None
        passed, reason = grade(q, ai, gold)
        alt = verification.alternative if verification else None
        status = (
            verification.status
            if verification
            else ("blocked" if ai.error and ai.error.startswith("Blocked") else "error")
        )
        tokens_in = ai.input_tokens + (alt.input_tokens if alt else 0)
        tokens_out = ai.output_tokens + (alt.output_tokens if alt else 0)
        results.append(
            {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                "expect": q["expect"],
                "trap": q.get("trap"),
                "passed": passed,
                "grading_note": reason,
                "verification_status": status,
                "checks": checks_as_dicts(verification.checks) if verification else [],
                "sql": ai.sql,
                "alternative_sql": alt.sql if alt else None,
                "assumptions": ai.assumptions,
                "error": ai.error,
                "repaired": ai.repaired,
                "latency_ms": ai.latency_ms + (alt.latency_ms if alt else 0),
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
            }
        )
        demo_entries.append(entry_from(ai, verification))
        if audit is not None:
            audit.log(
                AuditRecord(
                    feature="eval",
                    question=q["question"],
                    prompt_version=ai.prompt_version,
                    model=ai.model,
                    generated_sql=ai.sql,
                    verification_status=status,
                    checks=checks_as_dicts(verification.checks) if verification else [],
                    latency_ms=ai.latency_ms,
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    error=ai.error,
                )
            )
    return {
        "summary": summarise(results, client.model),
        "results": results,
        "demo_entries": demo_entries,
    }


def summarise(results: list[dict[str, Any]], model: str) -> dict[str, Any]:
    answered = [r for r in results if r["expect"] == "answer"]
    wrong = [r for r in answered if not r["passed"]]
    price_in, price_out = PRICE_PER_MTOK.get(model, (0.0, 0.0))
    tokens_in = sum(r["input_tokens"] for r in results)
    tokens_out = sum(r["output_tokens"] for r in results)
    statuses = [r["verification_status"] for r in results]
    return {
        "model": model,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "questions": len(results),
        "passed": sum(r["passed"] for r in results),
        "gold_graded_correct": f"{len(answered) - len(wrong)}/{len(answered)}",
        "verified": statuses.count("verified"),
        "mismatch": statuses.count("mismatch"),
        "unverifiable": statuses.count("unverifiable"),
        "blocked": statuses.count("blocked"),
        "wrong_but_verified": [r["id"] for r in wrong if r["verification_status"] == "verified"],
        "wrong_and_flagged": [r["id"] for r in wrong if r["verification_status"] == "mismatch"],
        "self_repaired": [r["id"] for r in results if r["repaired"]],
        "median_latency_ms": int(statistics.median(r["latency_ms"] for r in results)),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "approx_cost_usd": round(tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out, 3),
    }


def write_report(run: dict[str, Any], out_dir: Path = RESULTS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"run_{stamp}.json"
    path.write_text(
        json.dumps({k: run[k] for k in ("summary", "results")}, indent=2, default=str), "utf-8"
    )
    s = run["summary"]
    lines = [
        f"# AI eval — {s['run_at']} — {s['model']}",
        "",
        f"- Passed: **{s['passed']}/{s['questions']}** (gold-graded answers correct: "
        f"{s['gold_graded_correct']})",
        f"- Verification badges: {s['verified']} verified · {s['mismatch']} mismatch · "
        f"{s['unverifiable']} unverifiable · {s['blocked']} blocked",
        f"- Wrong but verified (must be empty): {s['wrong_but_verified'] or 'none'}",
        f"- Wrong and flagged by the verifier: {s['wrong_and_flagged'] or 'none'}",
        f"- Self-repaired after a SQL error: {s['self_repaired'] or 'none'}",
        f"- Median latency {s['median_latency_ms']} ms · tokens {s['input_tokens']:,} in / "
        f"{s['output_tokens']:,} out · approx ${s['approx_cost_usd']}",
        "",
        "| ID | Category | Passed | Badge | Note |",
        "|---|---|---|---|---|",
    ]
    for r in run["results"]:
        note = str(r["grading_note"]).replace("|", "/")
        lines.append(
            f"| {r['id']} | {r['category']} | {'✅' if r['passed'] else '❌'} | "
            f"{r['verification_status']} | {note} |"
        )
    (out_dir / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="run only the first N questions")
    args = parser.parse_args(argv)
    try:
        client = AnthropicClient()
    except AIError as e:
        raise SystemExit(str(e)) from e
    questions = load_questions()[: args.limit] if args.limit else load_questions()
    with connect() as con:
        run = run_eval(client, con, load_metric_data(con), AuditLog(), questions)
    path = write_report(run)
    if args.limit is None:
        save_demo_cache(run["demo_entries"])
    print((RESULTS_DIR / "latest.md").read_text(encoding="utf-8"))
    print(f"Full results: {path}")


if __name__ == "__main__":
    main()
