"""NL-to-SQL, verifier, memo, audit, demo cache and eval harness, all with a scripted (fake) LLM.

No test here calls the real API: `make test` passes with no key (CLAUDE.md §10).
"""

import pytest

from stayguard.ai.audit import AuditLog, AuditRecord
from stayguard.ai.client import AIError, ScriptedClient
from stayguard.ai.demo import entry_from, load_demo_cache, save_demo_cache
from stayguard.ai.eval import load_questions, run_eval
from stayguard.ai.memo import build_snapshot, check_numbers, generate_memo
from stayguard.ai.nl2sql import answer_question
from stayguard.ai.prompts import list_prompts, load_prompt
from stayguard.ai.verifier import (
    currency_mixing_check,
    date_range_check,
    duplicates_check,
    verify,
)
from stayguard.metrics import load_metric_data
from stayguard.sql_runner import run_query

FILTER_KEYS = ("countries", "cities", "intakes", "channels")


def nl(sql, column="", metric="none", group_by="none", assumptions=None, **filters):
    return {
        "sql": sql,
        "answer_column": column,
        "assumptions": assumptions or [],
        "explanation": "Test answer.",
        "canonical_metric": {
            "name": metric,
            "filters": {k: list(filters.get(k, [])) for k in FILTER_KEYS},
            "group_by": group_by,
        },
    }


def alt(sql, column=""):
    return {"sql": sql, "answer_column": column, "assumptions": [], "explanation": "Independent."}


@pytest.fixture(scope="module")
def data(con):
    return load_metric_data(con)


CANCEL_SEP26 = "SELECT AVG(is_cancelled::INT) AS cancellation_rate FROM v_bookings_gbp WHERE intake = 'Sep-2026'"


# --- Prompts ---------------------------------------------------------------------------------------


def test_prompts_are_versioned_files():
    prompts = {p.name: p for p in list_prompts()}
    assert {"nl2sql_v1", "alt_sql_v1", "memo_v1"} <= set(prompts)
    for p in prompts.values():
        assert p.version == p.name and p.meta["purpose"]
    assert "{schema_context}" in load_prompt("nl2sql_v1").body


# --- NL to SQL --------------------------------------------------------------------------------------


def test_answer_happy_path(con):
    client = ScriptedClient([nl(CANCEL_SEP26, "cancellation_rate")])
    answer = answer_question("Cancellation rate Sep-2026?", con, client)
    assert answer.ok and answer.attempts == 1 and not answer.repaired
    assert answer.sql.endswith("LIMIT 1000")
    assert 0.2 < answer.rows["cancellation_rate"].item() < 0.4
    assert "v_bookings_gbp" in client.calls[0]["system"]  # schema context reached the prompt


def test_one_self_repair_after_sql_error(con):
    client = ScriptedClient(
        [
            nl(
                "SELECT AVG(is_canceled::INT) AS cancellation_rate FROM v_bookings_gbp",
                "cancellation_rate",
            ),
            nl(CANCEL_SEP26, "cancellation_rate"),
        ]
    )
    answer = answer_question("Cancellation rate Sep-2026?", con, client)
    assert answer.ok and answer.repaired and answer.attempts == 2
    assert "is_canceled" in client.calls[1]["user"] and "Error" in client.calls[1]["user"]


def test_gives_up_after_one_repair(con):
    bad = nl("SELECT no_such_column FROM v_bookings_gbp")
    answer = answer_question("anything", con, ScriptedClient([bad, bad, bad]))
    assert not answer.ok and answer.attempts == 2 and "failed" in answer.error


def test_guardrail_block_is_final_and_nothing_runs(con):
    client = ScriptedClient([nl("DELETE FROM fact_booking"), nl("SELECT 1")])
    answer = answer_question("Delete the cancelled bookings", con, client)
    assert answer.rows is None and answer.error.startswith("Blocked")
    assert len(client.calls) == 1  # no second chance to talk round the guardrails


def test_llm_errors_become_friendly_messages(con):
    def boom(system, user):
        raise AIError("The AI service is rate-limited right now.")

    answer = answer_question("anything", con, ScriptedClient([boom]))
    assert answer.error == "The AI service is rate-limited right now."


# --- Verifier --------------------------------------------------------------------------------------


def test_verified_when_metric_and_independent_query_agree(con, data):
    client = ScriptedClient(
        [nl(CANCEL_SEP26, "cancellation_rate", "cancellation_rate", intakes=["Sep-2026"])]
    )
    answer = answer_question("What was the cancellation rate for the Sep-2026 intake?", con, client)
    independent = (
        "SELECT SUM(CASE WHEN b.status = 'cancelled' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct "
        "FROM v_clean_bookings b WHERE b.intake = 'Sep-2026'"
    )
    v = verify(answer, con, ScriptedClient([alt(independent, "pct")]), data)
    statuses = {c.name: c.status for c in v.checks}
    assert statuses["Canonical metric"] == "pass"
    assert statuses["Independent re-derivation"] == "pass"  # fraction vs percentage reconciled
    assert v.status == "verified" and v.badge.startswith("✅")


def test_mixed_currency_answer_is_flagged(con, data):
    wrong = "SELECT SUM(gbv_local) AS gbv FROM v_bookings_gbp WHERE intake = 'Sep-2025'"
    answer = answer_question(
        "Total GBV across all markets for Sep-2025",
        con,
        ScriptedClient([nl(wrong, "gbv", "gbv", intakes=["Sep-2025"])]),
    )
    right = "SELECT SUM(gbv_gbp) AS gbv_gbp FROM v_bookings_gbp WHERE intake = 'Sep-2025'"
    v = verify(answer, con, ScriptedClient([alt(right, "gbv_gbp")]), data)
    statuses = {c.name: c.status for c in v.checks}
    assert statuses["Currency mixing"] == "fail"
    assert statuses["Canonical metric"] == "fail"
    assert statuses["Independent re-derivation"] == "fail"
    assert v.status == "mismatch"


def test_grouped_canonical_metric(con, data):
    sql = (
        "SELECT country, AVG(is_cancelled::INT) AS cancellation_rate FROM v_bookings_gbp "
        "WHERE is_closed_intake GROUP BY country"
    )
    answer = answer_question(
        "x", con, ScriptedClient([nl(sql, "cancellation_rate", "cancellation_rate", "country")])
    )
    assert verify(answer, con, None, data).checks[0].status == "pass"


def test_wrong_filter_is_caught_by_metric_and_date_checks(con, data):
    sql = "SELECT AVG(is_cancelled::INT) AS cancellation_rate FROM v_bookings_gbp WHERE intake = 'Sep-2025'"
    answer = answer_question(
        "What was the cancellation rate for the Sep-2026 intake?",
        con,
        ScriptedClient([nl(sql, "cancellation_rate", "cancellation_rate", intakes=["Sep-2026"])]),
    )
    v = verify(answer, con, None, data)
    statuses = {c.name: c.status for c in v.checks}
    assert statuses["Date range"] == "fail"
    assert v.status == "mismatch"


def test_unverifiable_without_metric_or_second_opinion(con, data):
    sql = "SELECT room_type, COUNT(*) AS properties FROM dim_property GROUP BY room_type"
    answer = answer_question(
        "Properties by room type", con, ScriptedClient([nl(sql, "properties")])
    )
    v = verify(answer, con, ScriptedClient([alt("SELECT broken")]), data)
    assert v.status == "unverifiable" and v.badge.startswith("◻️")


def test_sanity_checks():
    assert (
        currency_mixing_check(
            "SELECT SUM(b.commission_local * c.fx_to_gbp) FROM fact_booking b JOIN dim_city c ON true"
        ).status
        == "pass"
    )
    assert (
        currency_mixing_check("SELECT AVG(weekly_rent_local) FROM v_clean_bookings").status
        == "fail"
    )
    assert duplicates_check("SELECT COUNT(*) FROM fact_booking").status == "warn"
    assert date_range_check("PG demand in 2025-26?", "SELECT 1").status == "fail"


# --- Memo -------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot(con, data):
    return build_snapshot(
        data, lambda n: run_query(con, n), lambda t: con.execute(f"SELECT * FROM {t}").df()
    )


def memo_with(text):
    return {
        "headline": text,
        "insights": [{"title": "t", "detail": "d"}] * 3,
        "recommendations": [{"action": "a", "owner": "Ops", "expected_impact": "i"}] * 3,
    }


def test_number_checker_matches_rounded_and_formatted_values(snapshot):
    enc = snapshot["kpis"]["Expected to land"]["value"]
    london = snapshot["revenue_at_risk_top_cities"][0]
    text = f"We expect £{enc / 1000:.0f}k to land; {london['city']} holds {london['share_of_total_risk_pct']}% of the risk."
    assert all(n.matched for n in check_numbers(text, snapshot))


def test_number_checker_flags_invented_numbers(snapshot):
    results = check_numbers("Revenue at risk rose 37.3% and we could save £987k.", snapshot)
    assert [n.text for n in results if not n.matched] == ["37.3%", "£987k"]


def test_memo_regenerates_once_then_passes(snapshot):
    enc = snapshot["kpis"]["Expected to land"]["value"]
    client = ScriptedClient(
        [memo_with("We will save £987k."), memo_with(f"We expect £{enc / 1000:.0f}k.")]
    )
    memo = generate_memo(client, snapshot)
    assert memo.passed and memo.attempts == 2
    assert "£987k" in client.calls[1]["user"]  # the checker's feedback reached the model


def test_memo_still_wrong_after_retry_is_marked(snapshot):
    memo = generate_memo(ScriptedClient([memo_with("Up 99.9%."), memo_with("Up 99.9%.")]), snapshot)
    assert not memo.passed and memo.unmatched == ["99.9%"] and memo.attempts == 2


# --- Audit & demo cache -----------------------------------------------------------------------------


def test_audit_log_round_trip(tmp_path):
    log = AuditLog(tmp_path / "audit.duckdb")
    log.log(
        AuditRecord(
            feature="nl2sql",
            question="q",
            verification_status="verified",
            checks=[{"name": "c", "status": "pass", "detail": ""}],
            latency_ms=12,
        )
    )
    df = log.read()
    assert len(df) == 1 and df["verification_status"].item() == "verified"


def test_demo_cache_round_trip(con, data, tmp_path):
    answer = answer_question("q", con, ScriptedClient([nl(CANCEL_SEP26, "cancellation_rate")]))
    entry = entry_from(answer, verify(answer, con, None, data))
    path = tmp_path / "demo.json"
    save_demo_cache([entry], path)
    loaded = load_demo_cache(path)
    assert loaded[0]["sql"] == answer.sql and loaded[0]["rows"][0]["cancellation_rate"] > 0


# --- Eval harness (offline) -------------------------------------------------------------------------

CANONICAL = {
    "Q01": ("cancellation_rate", "none", {"intakes": ["Sep-2026"]}),
    "Q02": ("expected_net_commission", "none", {}),
    "Q04": ("cancellation_rate", "country", {}),
    "Q05": ("lead_to_booking_conversion", "channel", {}),
    "Q06": ("median_first_response", "none", {}),
    "Q07": ("gbv", "none", {"intakes": ["Sep-2025"]}),
    "Q12": ("lead_to_booking_conversion", "none", {"intakes": ["Jan-2026"]}),
}
CARELESS = {  # the traps each question was designed to set
    "Q07": "SELECT SUM(gbv_local) AS gbv_gbp FROM v_clean_bookings WHERE intake = 'Sep-2025'",
    "Q08": "SELECT COUNT(*) AS bookings FROM fact_booking WHERE intake = 'Jan-2026'",
    "Q09": "SELECT AVG((cancel_reason = 'visa_refused')::INT) AS visa_refusal_rate FROM v_bookings_gbp "
    "WHERE is_closed_intake AND source_country = 'Pakistan' AND visa_status_at_booking = 'pending'",
}


def fake_model(careless: bool):
    questions = {q["question"]: q for q in load_questions()}

    def respond(system, user):
        q = questions[user.split("\n")[0]]
        if "independent reviewer" in system:
            return alt(
                q.get("gold_sql", "SELECT 'not answerable from this data' AS note"),
                q.get("gold_column", ""),
            )
        if q["expect"] == "blocked":
            return nl(
                "DELETE FROM fact_booking"
                if q["id"] == "Q13"
                else "SELECT 'not answerable from this data' AS note"
            )
        if q["expect"] == "judgement":
            return nl(
                "SELECT SUM(commission_gbp) AS realised_commission_gbp FROM v_bookings_gbp WHERE is_moved_in",
                "realised_commission_gbp",
                assumptions=["'Revenue' read as realised commission"],
            )
        sql = CARELESS.get(q["id"], q["gold_sql"]) if careless else q["gold_sql"]
        name, group_by, filters = CANONICAL.get(q["id"], ("none", "none", {}))
        return nl(sql, q["gold_column"], name, group_by, **filters)

    return ScriptedClient([respond] * 200)


def test_eval_set_has_fifteen_questions_covering_the_traps():
    qs = load_questions()
    assert len(qs) == 15 and len({q["id"] for q in qs}) == 15
    assert {q["category"] for q in qs} >= {"metric", "breakdown", "trap", "guardrail", "ambiguous"}


def test_eval_with_a_perfect_model_passes_everything(con, data):
    run = run_eval(fake_model(careless=False), con, data)
    failed = [r["id"] for r in run["results"] if not r["passed"]]
    assert not failed, failed
    assert run["summary"]["wrong_but_verified"] == []


def test_eval_with_a_careless_model_is_caught_by_the_verifier(con, data):
    run = run_eval(fake_model(careless=True), con, data)
    s = run["summary"]
    assert {"Q07", "Q08", "Q09"} <= {r["id"] for r in run["results"] if not r["passed"]}
    assert s["wrong_but_verified"] == []  # every wrong answer was flagged, none got a green badge
    assert {"Q07", "Q08", "Q09"} <= set(s["wrong_and_flagged"])
