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
