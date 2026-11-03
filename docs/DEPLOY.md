# Deploy: Streamlit Community Cloud

The public demo runs **without an API key** (ADR-013). On first boot the app builds the synthetic
database itself, in about 20 s behind a spinner (ADR-011), so no data files need to be committed.

## Steps (you do these: they publish the project)

1. **Push to GitHub.** Create a public repository and push `main`. Nothing secret is tracked: `.env`
   and `data/*.duckdb` are gitignored, and the checklist below verifies it.
2. **Create the app** at [share.streamlit.io](https://share.streamlit.io): **New app**, then:
   - Repository: your repo; branch `main`; main file **`app/Home.py`**.
   - **Advanced settings:** Python **3.12**. Add **no secrets**, so the public demo stays in demo mode.
3. **Watch the first boot.** The logs should show dependencies installing from `requirements.txt`
   (which includes `-e .`, so the `stayguard` package is installed), then the spinner *"First start:
   generating the synthetic data…"*. Confirm in the logs which dependency file was used.
4. **Smoke-test the live URL.** Every page loads, the footer says *Synthetic data — portfolio project*,
   and Ask the Data shows the demo-mode banner.
5. **Link it.** Put the app URL at the top of the README. The About page already links to the
   GitHub repo.

The deployed filesystem is temporary: the AI audit log resets on restart (ADR-010). That's acceptable,
because the public demo makes no live AI calls.

## Checklist

| Check | How | Status (2026-11-03) |
|---|---|---|
| Tests pass with no API key | `make test` | ✅ 208 passed |
| Lint clean | `make lint` | ✅ |
| `requirements.txt` in sync with `pyproject.toml` | `make reqs`; `test_requirements_txt_covers_every_runtime_dependency` | ✅ |
| No secrets tracked | `git ls-files` contains no `.env`; no `sk-ant` string in tracked files | ✅ |
| Database not committed; first boot builds it | `test_first_boot_builds_a_complete_database` | ✅ |
| Fresh clone → `make setup data app` works | Clone into an empty folder, run all three, check the app answers | ✅ Verified 2026-11-03 on commit `7cc531e` (Windows 11): `make setup` 14 s, `make data` 38 s with identical results; the app served the same KPIs (£821k / £562k / £141k / 28.8% / 30.6%); 208 tests and lint pass in the clone. First page load of a brand-new environment: 10.6 s (one-off compile and import) |
| Every page labelled synthetic | `test_page_renders_without_exceptions` checks the footer on all 10 pages | ✅ |
| No marketplace brand in the app or data | `test_no_brand_name_in_any_generated_text`; the README only says "inspired by" | ✅ |
| Pages load in under 3 s once warm | `test_pages_render_fast_when_warm` | ✅ |
| Demo answers for Ask the Data | `make ai-eval` with a key, then commit `data/demo_cache.json` | ⏳ pending a key (ADR-027) |
| Weekly AI memo on Home | `make ai-memo` with a key, then commit `data/memo_cache.json` | ⏳ pending a key; the rule-based insights show meanwhile |
| GitHub push | Step 1 | ✅ [alexabraham629-ux/stayguard](https://github.com/alexabraham629-ux/stayguard), commits authored with the GitHub noreply address |
| Streamlit app | Steps 2–5 above | ⏳ yours to do (needs your Streamlit account) |
| Licence | Add a `LICENSE` file (e.g. MIT) if you want others to reuse the code | ⏳ your choice |
