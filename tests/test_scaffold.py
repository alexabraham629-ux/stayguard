"""Phase 1 scaffold checks: config loads, structure exists, dependency files stay in sync."""

import re
import tomllib
from datetime import date

from stayguard.config import PROJECT_ROOT, load_assumptions

REQUIRED_PATHS = [
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    ".env.example",
    "Makefile",
    "config/assumptions.yaml",
    "data/raw",
    "data/exports",
    "src/stayguard/generate",
    "src/stayguard/quality",
    "src/stayguard/model",
    "src/stayguard/ai/prompts",
    "src/stayguard/sim",
    "sql",
    "app/Home.py",
    "app/pages",
    "mcp_server",
    "tests",
    "notebooks",
    "dashboards/screenshots",
    "docs/PRD.md",
    "docs/METRICS.md",
    "docs/DATA_GENERATION.md",
    "docs/DECISIONS.md",
    "docs/PROMPTS.md",
    "docs/AI_LOG.md",
    "docs/FINDINGS.md",
]


def _normalise(name: str) -> str:
    """PEP 503 package-name normalisation, so 'python-dotenv' == 'python_dotenv'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def test_required_paths_exist():
    missing = [p for p in REQUIRED_PATHS if not (PROJECT_ROOT / p).exists()]
    assert not missing, f"missing scaffold paths: {missing}"


def test_assumptions_core_values():
    a = load_assumptions()
    assert isinstance(a["project"]["seed"], int)
    assert date.fromisoformat(a["project"]["snapshot_date"]) == date(2026, 10, 31)
    assert list(a["intakes"]) == [
        "Sep-2024",
        "Jan-2025",
        "Sep-2025",
        "Jan-2026",
        "Sep-2026",
        "Jan-2027",
    ]
    assert a["currency"]["fx_to_gbp"]["GBP"] == 1.0
    assert set(a["currency"]["fx_to_gbp"]) == {"GBP", "AUD", "EUR"}


def test_commission_rates_within_documented_range():
    rates = load_assumptions()["commission"]["rate_by_operator_type"]
    assert set(rates) == {"PBSA chain", "independent PBSA", "HMO"}
    assert all(0.08 <= r <= 0.14 for r in rates.values())


def test_model_split_is_time_ordered_and_disjoint():
    a = load_assumptions()
    order = list(a["intakes"])
    split = a["model_split"]
    train = [order.index(i) for i in split["train_intakes"]]
    valid = [order.index(i) for i in split["validation_intakes"]]
    score = [order.index(i) for i in split["score_intakes"]]
    assert max(train) < min(valid) < min(score), "split must move forward in time"


def test_requirements_txt_covers_every_runtime_dependency():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = {
        _normalise(re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0])
        for dep in pyproject["project"]["dependencies"]
    }
    pinned = {
        _normalise(line.split("==")[0])
        for line in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    }
    missing = declared - pinned
    assert not missing, f"requirements.txt is stale, run `make reqs`: missing {missing}"


def test_env_example_has_no_secret():
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    key_line = next(line for line in text.splitlines() if line.startswith("ANTHROPIC_API_KEY"))
    assert key_line.strip() == "ANTHROPIC_API_KEY="
