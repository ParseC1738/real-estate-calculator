# PROGRESS – Immo-Rendite

Progress log for the autonomous run through milestones M0–M7 (M8 skipped on request).
Per milestone: what was built, key decisions and **why**, rejected alternatives, and open
questions for you.

## Status

| # | Milestone | Branch | Status |
|---|---|---|---|
| M0 | Repo setup | `m0-setup` | ✅ merged |
| M1 | Data model | `m1-data-model` | ✅ merged |
| M2 | Assumptions + metrics | `m2-metrics` | ✅ merged |
| M3 | Sample data | `m3-sample-data` | ✅ merged |
| M4 | Rent estimate | `m4-rent-estimate` | ✅ merged |
| M5 | UI: overview + detail | `m5-ui-overview` | ✅ merged |
| M6 | UI: assumptions, areas, rentals, overrides | `m6-ui-pages` | ⏳ |
| M7 | Adapters + ingest + CSV | `m7-ingest` | ⏳ |
| M8 | Real reference data | – | skipped (as requested) |

## Blockers

- none at the moment.
- *Resolved:* during M0 every `git push` was refused (HTTP 403, the Claude GitHub App had
  no write access). Work continued with local commits; from M1 on the pushes went through
  and the M0 branch was pushed afterwards.

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

---

## M2 – Assumptions + metrics engine

**Built**
- `config/assumptions.yaml` with all defaults from SPEC §6.1 (commented).
- `core/assumptions.py`: `Assumptions` model, `load_assumptions` / `save_assumptions`,
  and profiles (`save_profile`, `list_profiles`, `load_profile` → one YAML file per
  profile in `config/profiles/`).
- `core/metrics.py`: `buy_metrics()` (all KAUF types), `rent_listing_metrics()` (MIETE),
  and the building blocks `purchase_costs()`, `annuity_month()`, `price_per_m2()`,
  `pct_diff()`, `traffic_light()`.
- `core/overrides.py`: `apply_overrides()` returns a copy of the listing with overridden
  price / living area and remembers the origin of each value.
- 41 new tests; every metric has a hand-calculated example with the calculation written
  next to the expected number.

**Formulas (as implemented)**
```
purchase_costs        = price × (transfer_tax + notary_land_registry + commission) / 100
total_investment      = price + purchase_costs
annual_cold_rent      = rent_month × 12
gross_yield_pct       = annual_cold_rent / price × 100
price_to_rent_factor  = price / annual_cold_rent
net_operating_income  = annual_cold_rent
                        − annual_cold_rent × non_recoverable_costs_pct / 100
                        − maintenance_eur_m2_year × living_area_m2
                        − annual_cold_rent × vacancy_pct / 100
net_yield_pct         = net_operating_income / total_investment × 100
equity                = total_investment × equity_pct / 100
loan                  = total_investment − equity
annuity_month         = loan × (interest_rate_pct + repayment_pct) / 100 / 12
cashflow_month_pretax = net_operating_income / 12 − annuity_month
cash_on_cash_pct      = cashflow_month_pretax × 12 / equity × 100
rent_upside_pct (MFH) = (market_rent − actual_rent) / actual_rent × 100
```

**Decisions and why**
- **`buy_metrics()` receives everything "external" as plain numbers** (the rent, the
  area average, the land value). It never looks anything up itself. That is what keeps
  it pure: no database, no estimate logic, and each test fits in a few lines.
- **One flat result object (`BuyMetrics`) with `None` for "not applicable".** A plot
  simply has `gross_yield_pct = None`; the UI shows that as "n/a" (SPEC §6.4). A flat
  object also maps 1:1 to table columns later.
- **`commission_pct = None` ≠ `0`.** `None` means "unknown → use the default" and the
  commission is marked `ESTIMATED`; `0` is a real "commission-free" and marked `ACTUAL`.
- **Defaults exist twice (YAML + model defaults), guarded by a test.** The YAML is for
  editing without code; the model defaults make a missing key or file harmless.
  `test_shipped_yaml_equals_the_code_defaults` fails if they drift apart.
- **Unknown keys in the YAML are an error** (`extra="forbid"`). A typo like
  `intrest_rate_pct` would otherwise be ignored silently and you would calculate with
  the default without noticing.
- **`rent_strategy` and the traffic-light thresholds are part of the assumptions**, so a
  saved profile captures them too.
- **Profiles are YAML files**, not database rows: readable, diff-able, easy to copy.
  They are git-ignored (`config/profiles/*.yaml`) because they are personal.
- **Transfer tax by city name**: "Berlin" → Berlin rate, everything else → Brandenburg
  rate (the app's region only covers these two states).
- **Missing living area**: the maintenance reserve is set to 0 and a note is attached to
  the result instead of dropping all net metrics.

**Rejected alternatives**
- *Storing metrics in the database*: SPEC §6 says they are calculated on display so that
  changed assumptions take effect immediately.
- *Decimal instead of float for money*: more exact, but CLAUDE.md prescribes float and
  for estimates the difference is irrelevant.
- *A class hierarchy per property type* (`FlatMetrics`, `PlotMetrics`, …): more types,
  no real benefit over one result with optional fields at this size.
- *Exact annuity formula with a fixed loan term*: the SPEC defines the simple German
  "Zins + anfängliche Tilgung" annuity, which is also what banks quote.

**Open questions**
4. **Hausgeld is not used in the calculation yet.** The SPEC formula takes
   non-recoverable costs as a percentage of the rent (15 %). For flats one could instead
   use a share of the actual Hausgeld (e.g. 35–40 % is typically non-recoverable). Which
   do you prefer?
5. **Financing metrics for plots** (equity/loan/annuity) are not calculated because the
   SPEC lists them under ETW/HAUS/MFH only. Would they be useful for plots too?
6. **Traffic light** is based on the gross yield only (the SPEC's example). More
   indicators (net yield, cash flow, price vs. area) can be added via the config.
7. **Surrounding municipalities** are all treated as Brandenburg for the transfer tax.
   That is correct for the current region, but would need a real city → state mapping
   if the region grows (e.g. towards Saxony-Anhalt).

---

## M3 – Sample data generator

**Built**
- `core/sample_data.py`: `SampleWorld(seed)` – a small simulated market: 300 KAUF +
  400 MIETE listings over 3 cities / 28 districts / all 4 property types, with a
  lifecycle per listing (appears, price changes, goes offline, comes back).
  `area_references()` returns 164 invented references (Mietspiegel, price map,
  valuation committee, BORIS) at city and district level.
- `pipeline/seed.py`: `seed_database()` replays 12 simulated weekly fetches.
- `cli.py`: `uv run python -m immo.cli seed --reset [--seed N]`.
- Repository: the batch upsert now loads all known rows with one query (seed went from
  ~4.5 s to ~1 s).
- 20 new tests (determinism, volumes, realistic medians, messiness, history, CLI).

**What the seeded database looks like (seed 42)**
- 700 listings, 590 active; 1,091 snapshots.
- KAUF: 73 listings with 1–3 price drops, 31 offline, 13 relisted; up to 77 days online.
- Messy on purpose: ~5 % without living area, 10 % without rooms, 8 % without district,
  55 % without commission, ~2 % outliers (a digit missing/too many in price or area –
  labelled in `raw["sample_note"]`).
- 25 % of flats and 80 % of apartment buildings have an actual rent (below asking rents).

**Decisions and why**
- **The generator simulates fetch rounds instead of writing a history directly.**
  `listings_at(round)` answers "what would a fetch see in week N?". Seeding feeds these
  rounds through `upsert_listings()` + `deactivate_missing()` – the same code path real
  fetches will use in M7. So the sample history also acts as an end-to-end test of the
  snapshot logic, and there is no second, hand-written way to create history.
- **Deterministic by seed, timestamps relative to "now".** All randomness comes from one
  `random.Random(seed)`, and listing ids are UUIDv5 hashes of the sample id, so two runs
  give identical data. Dates are anchored to the moment of seeding (last round = now);
  otherwise "days online" would grow forever. Tests pass a fixed `now`.
- **12 extra "future" rounds are simulated too.** They are not seeded; M7's "Fetch now"
  can step through them so the import log shows new / changed / gone listings.
- **Prices and rents share the same district factor** (rents with a damped exponent),
  so yields differ between districts in a plausible way: cheaper districts yield more.
- **Sample references are clearly labelled** (`note = "SAMPLE DATA - invented value …"`)
  so they can never be mistaken for the real Mietspiegel values of M8.
- **`seed` without `--reset` refuses to run on a non-empty database** instead of mixing
  sample data into real data.
- **CLI with `argparse`** (standard library) – one command does not justify a dependency.

**Rejected alternatives**
- *Faker / factory libraries*: nicer names, but an extra dependency and harder to keep
  the price logic consistent across cities.
- *Generating snapshots directly in the generator*: faster, but it would duplicate the
  change-detection rules and could drift from the real pipeline.
- *Fixed calendar dates for the history*: fully static data, but every listing would be
  "hundreds of days online" a few months from now.
- *Typer/Click for the CLI*: more comfortable for many commands; not needed yet.

**Open questions**
8. **Only the 3 cities are generated**, no surrounding municipalities of Brandenburg
   a. d. Havel (SPEC §7 says "spread over the 3 cities"). Add e.g. Kloster Lehnin or
   Beetzsee as separate "cities"?
9. **Sample ranges** follow SPEC §7 for flats and rents; house, apartment-building and
   land prices are my own rough guesses (house ≈ 0.9 ×, MFH ≈ 0.62 × the flat price per
   m²). Tell me if they look off for the region.

---

## M4 – Rent estimate

**Built**
- `core/estimates.py`
  - `MarketIndex`: groups own listings (rent and price per m²) and stored references
    once; lookups per listing are then dictionary accesses.
  - `estimate_rent()`: the three strategies `market`, `mietspiegel`, `blend`.
  - `resolve_rent()`: order of precedence override → actual rent → estimate.
  - `RentEstimate` with `components` (source, €/m², weight, sample size, area level)
    and `confidence`.
  - Area averages: `area_price_m2()` (own sale listings → price map → valuation
    committee), `land_value_m2()` (BORIS), `mietspiegel_rent_m2()`.
- `core/evaluate.py`: `evaluate_buy()` / `evaluate_rental()` chain overrides → rent →
  metrics → history for one listing. This is the single function the UI will call.
- 55 new tests, including "too few samples", every fallback, and a run over the whole
  sample database.

**How an estimate is built**
1. *Own listings*: median asking rent per m² of comparable rentals, tried from most to
   least specific – district + type + size band → district + type → city + type + size
   band → city + type → whole city. A level is only used with ≥ `min_samples` listings.
2. *References*: most specific area wins – district → postal code → city; within an
   area a value for exactly this type / size band beats a general one.
3. *Strategy*: `market` = own listings, else price map · `mietspiegel` = official table ·
   `blend` = weighted average (weights renormalised if one side is missing).
4. Rent = €/m² × living area.

On the sample database: 245 of 261 flats/houses/apartment buildings get a rent (the
rest have no living area); 171 with confidence high, 74 medium.

**Decisions and why**
- **Median, not mean.** The sample data contains typos on purpose (a rent with a digit
  too many). The median ignores them; a mean would be dragged away.
- **Every source found is listed, also the ones the strategy did not use (weight 0).**
  That is the transparency principle: the detail view can show own listings, price map
  and Mietspiegel side by side even when only one of them was used.
- **An MFH is compared with flats of its average unit size** (living area ÷ units),
  because an apartment building is rented out flat by flat. Houses prefer house
  rentals and fall back to all rentals in the city.
- **Confidence rule** (my interpretation of "how many sources agree and how many
  samples"): one point if at least two sources lie within ±25 % of the estimate, one
  point if the estimate rests on ≥ 2 × `min_samples` own listings. 2 points = high,
  1 = medium, 0 = low. Actual rents and overrides are always "high".
- **No silent fallback between strategies.** If you choose `mietspiegel` and there is no
  table for the area, there is no estimate (instead of quietly using market data). Only
  the fallbacks named in the SPEC exist (own listings → price map; blend with one side).
- **Own-listing medians are computed on the fly, not stored** as `AreaReference` rows.
  They change with every fetch; storing them would create stale copies. They are still
  returned *as* `AreaReference` objects (source `own_listings`), so the rest of the code
  treats all sources the same way.
- **The actual rent is used unless the listing says it is not rented**
  (`is_rented = False`); an unknown flag counts as rented.
- **`rent_upside_pct` for MFH always compares with the pure market estimate**, even when
  an override is active.

**Rejected alternatives**
- *Trimmed mean / outlier filtering before the median*: more knobs, no visible gain yet.
- *Regression model (rent ~ area + year + district)*: far too much for a POC and it
  would hide where a number comes from.
- *Postal code as its own grouping level for own listings*: district and city are
  enough for the sample data; postal codes are supported for stored references.

**Open questions**
10. **Inactive rental listings are included in the medians** (a flat that was rented out
    last week still describes the market). With real data you may want a time window,
    e.g. "seen in the last 6 months".
11. **Asking rents ≠ contract rents.** The market value is the median *asking* rent; no
    discount is applied. Should there be a configurable haircut?
12. **Confidence thresholds** (±25 %, 2 × min samples) are constants in
    `core/estimates.py`. Move them into `assumptions.yaml`?
13. **The area average includes the listing itself.** Negligible with many listings,
    but in a thin district it pulls "price vs. area" towards 0 %.
14. **Year-built bands** are not used as a segment yet (only size bands), although real
    Mietspiegel tables are organised by year built. Relevant for M8.

---

## M5 – UI: overview, filters, detail view

**Built**
- `ui/app.py`: entry point with `st.navigation` (one script per page in `ui/pages/`).
- `ui/pages/overview.py`: KPI row, sortable table of all KAUF listings with the signal
  column, sidebar filters (city, district, type, price, area, rooms, year built, days
  online, min. gross/net yield, min. cash flow, max. price vs. area, only price-reduced,
  only active), two summary charts and the chart data as a table.
- `ui/pages/detail.py`: header with link, KPI row, and four tabs – *Calculation* (every
  step with its numbers), *Rent estimate* (every source with weight and sample size),
  *Price history* (step chart + event list), *Property data* (with the origin of values
  and the raw source data).
- Helper modules without any Streamlit call: `ui/tables.py` (DataFrame + filters),
  `ui/charts.py` (Plotly figures), `ui/explain.py` (calculation steps),
  `ui/formatting.py` (the only place where numbers are rounded).
- `ui/state.py`: cached repository, assumptions in the session, loading the market.
- 24 new tests: 17 for the helpers, 7 headless page tests with Streamlit's `AppTest`.
- Checked by eye in a real browser (light and dark theme) via screenshots.

**Decisions and why**
- **Thin pages, logic in plain functions.** Streamlit pages are hard to unit-test, so
  everything with an "if" in it (filtering, table building, binning, formatting) lives in
  normal functions that take data and return data. The pages only wire widgets to them.
- **Nothing is cached except the database connection.** Every interaction reloads the
  listings and recalculates all metrics (≈ 0.1 s for 700 listings). That is what makes a
  changed assumption or override visible everywhere immediately – and there is no cache
  to invalidate.
- **Filters with "unknown" values:** a range slider that still covers the full range is
  treated as "no filter", so listings with a missing value (e.g. no year built) stay
  visible until you actually narrow that filter.
- **Yield / cash-flow filters are minimums, price-vs-area is a maximum.** That matches
  how you search ("at least 5 %", "at least 10 % below the area"). Property values
  (price, area, rooms, year, days online) are from–to ranges.
- **Signal = icon + word** ("🟢 good / 🟡 fair / 🔴 weak"), never colour alone, so it also
  works for colour-blind readers and in a sorted/exported table.
- **Charts** (rules I followed, in case you add more):
  - one colour for a single series; a *fixed* colour per property type, so applying a
    filter never repaints the remaining bars;
  - the palette was checked with a colour-blindness validator for light and dark theme;
  - outliers (e.g. a 40 % "yield" from a price typo) are collected in a "10+" bar
    instead of stretching the axis;
  - values are written at the bar ends and the same data is available as a table.
- **Row selection + button to open the detail view** instead of jumping on click: the
  table keeps its selection when you come back, and an automatic jump would bounce you
  straight back into the detail page.
- **English UI with the German terms in brackets** (Kaufnebenkosten, Kaufpreisfaktor …),
  matching SPEC and glossary.

**Rejected alternatives**
- *`st.cache_data` for listings/metrics*: faster on paper, but stale data after an
  override or import is a worse problem than 0.1 s per click.
- *Classic `pages/` auto-discovery*: `st.navigation` gives explicit order, titles and
  icons in one place and lets the tests switch pages by path.
- *Streamlit's built-in chart theme*: it moved the legend onto the bars; the charts now
  use their own small theme (`theme=None`) with explicit margins.
- *Colouring whole table rows by signal*: needs pandas Styler, which disables some
  dataframe features (sorting stays, but formatting conflicts) – an icon column is
  simpler and accessible.

**Open questions**
15. **Table columns**: all 24 columns are shown and you scroll horizontally. Tell me
    which ones you actually use and I will put those first / hide the rest.
16. **Detail view covers KAUF listings only.** Rental listings get their own table page
    in M6 (per SPEC §8.5) but no detail page. Needed?
17. **UI language** is English with German terms in brackets. Prefer German?
