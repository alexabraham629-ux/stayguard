"""NL-to-SQL guardrails (CLAUDE.md §9.1): enforced in code, tested without any LLM."""

import duckdb
import pytest

from stayguard.ai.guardrails import GuardrailError, check_sql, run_readonly

REJECTED = {
    "drop": "DROP TABLE fact_booking",
    "delete": "DELETE FROM fact_booking",
    "insert": "INSERT INTO dim_city VALUES (99, 'X', 'UK', 'GBP', 1, 1.0)",
    "update": "UPDATE fact_booking SET status = 'moved_in'",
    "create": "CREATE TABLE t AS SELECT 1",
    "alter": "ALTER TABLE dim_city ADD COLUMN x INT",
    "multiple_statements": "SELECT 1; DROP TABLE dim_city",
    "non_whitelisted_table": "SELECT * FROM model_evaluation",
    "audit_table": "SELECT * FROM ai_audit",
    "information_schema": "SELECT * FROM information_schema.tables",
    "attached_catalog": "SELECT * FROM other.main.dim_city",
    "attach": "ATTACH 'other.duckdb' AS other",
    "pragma": "PRAGMA database_list",
    "copy": "COPY dim_city TO 'out.csv'",
    "read_csv": "SELECT * FROM read_csv('C:/secrets.csv')",
    "file_path": "SELECT * FROM 'data/raw/fact_lead.csv'",
    "glob": "SELECT * FROM glob('*')",
    "getenv": "SELECT getenv('ANTHROPIC_API_KEY')",
    "range_table_function": "SELECT * FROM range(10)",
    "empty": "   ",
    "unparseable": "SELEC city FRM dim_city",
}


@pytest.mark.parametrize("sql", REJECTED.values(), ids=REJECTED.keys())
def test_guardrails_reject(sql):
    with pytest.raises(GuardrailError):
        check_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM v_bookings_gbp",
        "WITH c AS (SELECT city, SUM(gbv_gbp) AS g FROM v_bookings_gbp GROUP BY city) SELECT * FROM c",
        "SELECT city FROM dim_city UNION ALL SELECT city FROM dim_city",
        "SELECT b.city, AVG(s.p_cancel) FROM v_bookings_gbp b JOIN scored_bookings s USING (booking_id) GROUP BY 1",
    ],
)
def test_guardrails_accept_read_only_selects(sql):
    assert "LIMIT" in check_sql(sql).upper()


def test_limit_is_added_and_capped():
    assert check_sql("SELECT city FROM dim_city").endswith("LIMIT 1000")
    assert "LIMIT 1000" in check_sql("SELECT city FROM dim_city LIMIT 50000")
    assert "LIMIT 5" in check_sql("SELECT city FROM dim_city LIMIT 5")


def test_cte_names_are_allowed_but_not_other_tables():
    check_sql("WITH my_cte AS (SELECT 1 AS x) SELECT x FROM my_cte")
    with pytest.raises(GuardrailError):
        check_sql("WITH my_cte AS (SELECT 1 AS x) SELECT x FROM not_a_table")


def test_runs_only_on_read_only_connections(db_path):
    with duckdb.connect(str(db_path), read_only=False) as writable, pytest.raises(GuardrailError):
        run_readonly(writable, check_sql("SELECT 1 AS x"))


def test_slow_queries_are_interrupted(con):
    slow = check_sql(
        "SELECT SUM(a.interaction_id * b.lead_id) AS s FROM fact_interaction a, fact_lead b"
    )
    with pytest.raises(GuardrailError, match="stopped"):
        run_readonly(con, slow, timeout_s=0.5)


def test_results_are_returned_for_safe_queries(con):
    df = run_readonly(con, check_sql("SELECT COUNT(*) AS n FROM dim_city"))
    assert df["n"].item() == 12
