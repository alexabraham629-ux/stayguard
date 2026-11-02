# StayGuard task runner. Recipes only call `uv`, so they behave the same under
# cmd.exe (GNU make on Windows) and sh (macOS/Linux). See ADR-003.

.DEFAULT_GOAL := help
.PHONY: help setup data test app export lint format reqs

help:
	@echo Targets: setup data test app export lint format reqs

setup:  ## create .venv with Python 3.12 and install all dependencies from uv.lock
	uv sync

data:  ## generate synthetic data and build data/stayguard.duckdb
	@echo make data: the generator arrives in Phase 2

test:  ## run the test suite (no API key needed)
	uv run pytest

app:  ## launch the Streamlit app
	uv run streamlit run app/Home.py

export:  ## write star-schema CSV/Parquet for Power BI / Tableau
	@echo make export: star-schema export arrives in Phase 8

lint:  ## lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

format:  ## auto-fix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .

reqs:  ## regenerate requirements.txt from uv.lock (keep both in sync)
	uv export --format requirements-txt --no-hashes --no-dev --output-file requirements.txt
