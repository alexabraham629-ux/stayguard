"""Smoke test: every Streamlit page runs without raising."""

from streamlit.testing.v1 import AppTest

from stayguard.config import PROJECT_ROOT


def test_home_page_renders_without_exceptions():
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "Home.py"), default_timeout=60).run()
    assert not at.exception
    assert any("Synthetic data" in c.value for c in at.caption)
