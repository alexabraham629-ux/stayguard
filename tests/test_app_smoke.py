"""Every Streamlit page renders without an exception, against the session's test database."""

import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from stayguard.config import PROJECT_ROOT

PAGES = [PROJECT_ROOT / "app" / "Home.py", *sorted((PROJECT_ROOT / "app" / "pages").glob("*.py"))]


@pytest.fixture(autouse=True)
def use_test_database(db_path: Path, model_run, monkeypatch):
    """Point the app at the session's freshly built (and scored) database."""
    import stayguard.ui.data as ui_data

    monkeypatch.setattr(ui_data, "DB_PATH", db_path)
    ui_data.connection.clear()
    ui_data.metric_data.clear()
    ui_data.query.clear()
    ui_data.table.clear()


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_renders_without_exceptions(page):
    started = time.perf_counter()
    at = AppTest.from_file(str(page), default_timeout=60).run()
    elapsed = time.perf_counter() - started
    assert not at.exception, [e.value for e in at.exception]
    assert "Synthetic data" in " ".join(m.value for m in at.markdown)
    print(f"{page.stem}: {elapsed:.2f}s")


def test_pages_render_fast_when_warm():
    """Acceptance: < 3 s per page once the server has imported its libraries."""
    for page in PAGES:
        AppTest.from_file(str(page), default_timeout=60).run()  # warm imports and caches
        started = time.perf_counter()
        at = AppTest.from_file(str(page), default_timeout=60).run()
        assert not at.exception
        assert time.perf_counter() - started < 3.0, page.stem


def _no_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")


def test_ask_the_data_demo_mode_shows_cached_verified_answers(con, monkeypatch, tmp_path):
    import stayguard.ai.demo as demo
    from stayguard.ai.client import ScriptedClient
    from stayguard.ai.nl2sql import answer_question
    from stayguard.ai.verifier import verify
    from stayguard.metrics import load_metric_data

    _no_api_key(monkeypatch)
    sql = "SELECT AVG(is_cancelled::INT) AS cancellation_rate FROM v_bookings_gbp WHERE intake = 'Sep-2026'"
    response = {
        "sql": sql,
        "answer_column": "cancellation_rate",
        "assumptions": [],
        "explanation": "Share of Sep-2026 bookings that cancelled.",
        "canonical_metric": {
            "name": "cancellation_rate",
            "filters": {"countries": [], "cities": [], "intakes": ["Sep-2026"], "channels": []},
            "group_by": "none",
        },
    }
    question = "What was the cancellation rate for the Sep-2026 intake?"
    answer = answer_question(question, con, ScriptedClient([response]))
    entry = demo.entry_from(answer, verify(answer, con, None, load_metric_data(con)))
    cache = tmp_path / "demo_cache.json"
    demo.save_demo_cache([entry], cache)
    monkeypatch.setattr(demo, "DEMO_CACHE", cache)

    at = AppTest.from_file(
        str(PROJECT_ROOT / "app" / "pages" / "8_Ask_the_Data.py"), default_timeout=60
    ).run()
    assert not at.exception
    assert any("Demo mode" in i.value for i in at.info)
    assert any("Verified" in s.value for s in at.success)


def test_home_shows_a_checked_memo_with_unmatched_numbers_highlighted(monkeypatch, tmp_path):
    import json

    import stayguard.ai.memo as memo

    cache = tmp_path / "memo_cache.json"
    cache.write_text(
        json.dumps(
            {
                "memo": {
                    "headline": "Revenue at risk is up 99.9%.",
                    "insights": [{"title": "t", "detail": "d"}] * 3,
                    "recommendations": [{"action": "a", "owner": "Ops", "expected_impact": "i"}]
                    * 3,
                },
                "unmatched": ["99.9%"],
                "passed": False,
                "attempts": 2,
                "model": "scripted",
                "prompt_version": "memo_v1",
                "generated_at": "2026-11-03T10:00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(memo, "MEMO_CACHE", cache)
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "Home.py"), default_timeout=60).run()
    assert not at.exception
    assert any("could not be found" in w.value for w in at.warning)
    assert any("color:#d03b3b" in m.value for m in at.markdown)
