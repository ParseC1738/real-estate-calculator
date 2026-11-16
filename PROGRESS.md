# PROGRESS – Immo-Rendite

Progress log for the autonomous run through milestones M0–M7 (M8 skipped on request).
Per milestone: what was built, key decisions and **why**, rejected alternatives, and open
questions for you.

## Status

| # | Milestone | Branch | Status |
|---|---|---|---|
| M0 | Repo setup | `m0-setup` | ✅ merged |
| M1 | Data model | `m1-data-model` | ✅ merged |
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

---

## M1 – Data model

**Built**
- `core/models.py`: enums (`PropertyType`, `OfferType`, `ValueOrigin`, plus `AreaMetric`,
  `ReferenceSource`, `OverrideField`) and Pydantic models `Listing`, `ListingSnapshot`,
  `AreaReference`, `Override`; area-key helpers; `listing_fingerprint()`.
- `core/history.py`: pure functions `diff_tracked()` (what changed?) and
  `summarize_history()` (days online, price changes, total change in %, relisted).
- `storage/db.py`, `storage/tables.py`, `storage/repository.py`: SQLite via
  SQLAlchemy 2.0; upsert with snapshots, deactivate/relist, area references, overrides.
- `paths.py`: one place for file locations (`IMMO_DB_PATH` overrides the DB file).
- 40 new tests (models, history, repository on an in-memory database).

**Decisions and why**
- **Two sets of classes: Pydantic models (`core`) and table rows (`storage`).** It looks
  like duplication, but it is what keeps `core/` free of SQLAlchemy: the models describe
  *meaning and validation*, the tables describe *storage*. Only the repository converts
  between them, so the rest of the app never sees a table row.
- **Repository pattern, one method = one transaction.** Callers say *what* they want
  (`repo.list_listings(offer_type=KAUF)`), never *how* (no SQL, no sessions outside
  `storage/`). Batches (`upsert_listings`) run in a single transaction: all or nothing.
- **Change detection is a pure function in `core/history.py`; the repository only
  decides when to store.** That makes "what counts as a change" testable without a
  database. Tracked fields: `price`, `living_area_m2`, `plot_area_m2`, `title`,
  `is_active` (SPEC §4.3: "price, area, title, status").
- **The first sighting also creates a snapshot** (with empty `changes`). It records the
  starting price, so "total price change in %" and the price chart need no special case.
- **Going offline and coming back are stored as `is_active` changes in the snapshots.**
  "Relisted" is then simply "there is a snapshot where `is_active` went false → true".
- **Enums are stored as plain strings**, not as database enum types – readable in any
  SQLite browser and no migration needed when a value is added.
- **Naive UTC datetimes everywhere** (`models.utcnow()`). SQLite has no time-zone
  support and returns naive values; mixing aware and naive datetimes raises errors.
- **`fingerprint` is derived, not part of the `Listing` model.** The repository computes
  it on every upsert and stores it in an indexed column. One source of truth, and it can
  never be out of date. (Deduplication itself is "later" in the SPEC.)
- **Extra enums beyond SPEC §4.1** (`AreaMetric`, `ReferenceSource`, `OverrideField`):
  the SPEC lists these as fixed sets of strings; enums catch typos at validation time.
- **`AreaReference.sample_size`** added (not in SPEC §4.4): needed to show how many own
  listings a median is based on (SPEC §5.2 asks for the sample size per component).

**Rejected alternatives**
- *SQLModel (one class for model + table)*: less code, but it would pull SQLAlchemy into
  `core/` and break the architecture rule.
- *Alembic migrations*: overkill for a POC whose database is rebuilt with
  `seed --reset`. New tables are created automatically; changed columns need a reset.
- *Timezone-aware datetimes*: more correct in general, but painful with SQLite.
- *Keeping every version of an override*: SPEC §4.5 only needs the current value; a new
  value for the same field replaces the old one.

**Open questions**
1. **Days online for relisted listings** currently counts from the very first sighting
   and does not subtract the time the listing was offline. OK, or should gaps be removed?
2. **Overrides replace each other** (no override history). Do you want a history?
3. **No migrations**: after a schema change you must run `seed --reset` (loses overrides).
   Fine for the POC; Alembic would be the next step once real data is in the DB.
