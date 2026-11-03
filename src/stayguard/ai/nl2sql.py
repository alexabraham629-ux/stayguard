"""Natural language -> SQL with guardrails and one automatic self-repair (CLAUDE.md §9.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
import pandas as pd

from stayguard.ai.client import AIError, LLMClient
from stayguard.ai.context import build_schema_context
from stayguard.ai.guardrails import GuardrailError, check_sql, run_readonly
from stayguard.ai.prompts import load_prompt

PROMPT_NAME = "nl2sql_v1"
FILTER_KEYS = ("countries", "cities", "intakes", "channels")

_STRING_LIST = {"type": "array", "items": {"type": "string"}}
QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "answer_column": {"type": "string"},
        "assumptions": _STRING_LIST,
        "explanation": {"type": "string"},
    },
    "required": ["sql", "answer_column", "assumptions", "explanation"],
    "additionalProperties": False,
}
NL2SQL_SCHEMA: dict[str, Any] = {
    **QUERY_SCHEMA,
    "properties": {
        **QUERY_SCHEMA["properties"],
        "canonical_metric": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "filters": {
                    "type": "object",
                    "properties": {k: _STRING_LIST for k in FILTER_KEYS},
                    "required": list(FILTER_KEYS),
                    "additionalProperties": False,
                },
                "group_by": {
                    "type": "string",
                    "enum": ["none", "country", "city", "intake", "channel"],
                },
            },
            "required": ["name", "filters", "group_by"],
            "additionalProperties": False,
        },
    },
    "required": [*QUERY_SCHEMA["required"], "canonical_metric"],
}


@dataclass
class Answer:
    question: str
    sql: str | None = None
    answer_column: str = ""
    assumptions: list[str] = field(default_factory=list)
    explanation: str = ""
    canonical_metric: dict[str, Any] = field(default_factory=dict)
    rows: pd.DataFrame | None = None
    error: str | None = None
    attempts: int = 0
    repaired: bool = False
    prompt_version: str = PROMPT_NAME
    model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and self.rows is not None


def system_prompt(prompt_name: str, con: duckdb.DuckDBPyConnection) -> str:
    return load_prompt(prompt_name).body.replace("{schema_context}", build_schema_context(con))


def _repair_message(question: str, sql: str, error: str) -> str:
    return (
        f"{question}\n\nYour previous query failed when it ran.\n```sql\n{sql}\n```\n"
        f"Error: {error}\nReturn a corrected query in the same JSON format."
    )


def generate_and_run(
    question: str,
    con: duckdb.DuckDBPyConnection,
    client: LLMClient,
    prompt_name: str,
    schema: dict[str, Any],
) -> Answer:
    """Ask the model for SQL, check it, run it; on a SQL execution error, repair once."""
    answer = Answer(question=question, prompt_version=prompt_name, model=client.model)
    system = system_prompt(prompt_name, con)
    user = question
    for attempt in (1, 2):
        answer.attempts = attempt
        try:
            response = client.complete_json(system=system, user=user, schema=schema)
        except AIError as e:
            answer.error = str(e)
            return answer
        answer.latency_ms += response.latency_ms
        answer.input_tokens += response.input_tokens
        answer.output_tokens += response.output_tokens
        data = response.data
        raw_sql = str(data.get("sql", ""))
        answer.answer_column = str(data.get("answer_column", ""))
        answer.assumptions = list(data.get("assumptions", []))
        answer.explanation = str(data.get("explanation", ""))
        answer.canonical_metric = dict(data.get("canonical_metric", {}))
        try:
            answer.sql = check_sql(raw_sql)
        except GuardrailError as e:
            # Safety rejections are final: the model does not get a second try to get round them.
            answer.sql = raw_sql
            answer.error = f"Blocked by guardrails: {e}"
            return answer
        try:
            answer.rows = run_readonly(con, answer.sql)
            answer.error = None
            answer.repaired = attempt == 2
            return answer
        except GuardrailError as e:  # timeout
            answer.error = str(e)
            return answer
        except duckdb.Error as e:
            message = str(e).splitlines()[0]
            answer.error = f"The query failed: {message}"
            user = _repair_message(question, answer.sql, message)
    return answer


def answer_question(question: str, con: duckdb.DuckDBPyConnection, client: LLMClient) -> Answer:
    """The main NL-to-SQL entry point used by the Ask the Data page."""
    return generate_and_run(question, con, client, PROMPT_NAME, NL2SQL_SCHEMA)
