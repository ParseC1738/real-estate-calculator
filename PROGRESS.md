# PROGRESS – Immo-Rendite

Progress log for the autonomous run through milestones M0–M7 (M8 skipped on request).
Per milestone: what was built, key decisions and **why**, rejected alternatives, and open
questions for you.

## Status

| # | Milestone | Branch | Status |
|---|---|---|---|
| M0 | Repo setup | `m0-setup` | ✅ merged |
| M1 | Data model | `m1-data-model` | ⏳ |
| M2 | Assumptions + metrics | `m2-metrics` | ⏳ |
| M3 | Sample data | `m3-sample-data` | ⏳ |
| M4 | Rent estimate | `m4-rent-estimate` | ⏳ |
| M5 | UI: overview + detail | `m5-ui-overview` | ⏳ |
| M6 | UI: assumptions, areas, rentals, overrides | `m6-ui-pages` | ⏳ |
| M7 | Adapters + ingest + CSV | `m7-ingest` | ⏳ |
| M8 | Real reference data | – | skipped (as requested) |

## ⚠️ Blockers / things you need to do

- **`git push` is refused (HTTP 403).** The Claude GitHub App has no write access to
  `ParseC1738/real-estate-calculator`. Everything is committed locally (milestone
  branches + `main`), and the push is retried after every step. To fix: connect GitHub at
  <https://claude.ai/connect-github> and install the Claude GitHub App on the repository.
  See "Git workflow in this run" below for what gets pushed once access works.

## Git workflow in this run

- One branch per milestone (`m<N>-<name>`), small Conventional Commits, and
  `ruff check --fix` + `ruff format` + `pytest` before every commit.
- Merge into `main` with `git merge --no-ff`. **Why `--no-ff`?** A fast-forward would
  just move `main` forward and the milestone would disappear in a straight line of
  commits. `--no-ff` forces a merge commit, so `git log --graph` shows each milestone as
  its own visible "bubble" – handy for reviewing the run afterwards.
- The Claude cloud session is assigned its own branch (`claude/confident-carson-jx9g1x`).
  It is fast-forwarded to `main` after every milestone, so it always mirrors `main`.

---

## M0 – Repo setup

**Built**
- `pyproject.toml` (uv project, Python ≥ 3.12, `src/` layout), `uv.lock`,
  `.python-version`, `.gitignore`, folder structure from SPEC §10.
- ruff (lint + format) and pytest configured in `pyproject.toml`.
- `tests/test_smoke.py` and `tests/test_architecture.py`.

**Decisions and why**
- **`src/` layout + installable package.** `uv sync` installs `immo` into the virtualenv
  in editable mode. That is what makes `python -m immo.cli` and `import immo` work from
  anywhere, and it stops tests from accidentally importing files from the working
  directory instead of the installed package.
- **Architecture rules as tests** (`tests/test_architecture.py`). The rules in CLAUDE.md
  ("core has no dependency on Streamlit/SQLAlchemy", "only storage/ touches the DB") are
  checked by parsing every module's imports with `ast`. A written rule gets broken by
  accident; a failing test does not.
- **A smoke test instead of an empty test suite.** pytest exits with code 5 when it
  collects no tests, which would break the `ruff && pytest` chain used before commits.
- **`uv.lock` is committed.** It pins exact versions, so the app behaves the same on your
  machine as it did here.
- **ruff rule set `E, W, F, I, UP, B, SIM`** – style, unused code, import order, modern
  syntax and common bug patterns. Small enough not to be noisy.
- **Markdown excluded from ruff.** Recent ruff versions reformat Python code blocks
  inside `.md` files; that changed SPEC.md on the first run. The docs stay as you wrote
  them.

**Rejected alternatives**
- *Flat layout (package in the repo root)*: simpler at first, but imports behave
  differently in tests vs. when installed.
- *`pip` + `requirements.txt`*: SPEC §3 chooses uv; it also gives a lockfile for free.
- *pre-commit hooks*: one more tool to learn; the three commands in CLAUDE.md are enough
  for a single-user project.

**Open questions**
- none
