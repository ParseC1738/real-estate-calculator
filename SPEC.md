# SPEC – Immo-Rendite (working title)

Version 0.1 · 2026-11-16 · Status: proof of concept, single user

## 1. Goal

A local web app that collects real-estate listings for a region, adds estimates (rent,
purchase costs, area averages), and calculates investment metrics automatically, so a
property can be judged at a glance instead of being calculated by hand each time.

- **Primary use:** evaluate properties **for sale** (is the purchase profitable?).
- **Secondary use:** collect **rental** listings, mainly as a data source for rent estimates.

**Region (initial):** Brandenburg an der Havel and surrounding municipalities, Potsdam, Berlin.

**Property types:** flats (Eigentumswohnung, ETW), houses (Haus), apartment buildings
(Mehrfamilienhaus, MFH) and plots of land (Grundstück).

## 2. Guiding principles

1. **Sample data first.** The dashboard and all calculations are built and tested with
   generated sample data. Real website importers come last.
2. **Swappable modules.** Every data source is an adapter behind one interface. The core
   (models, metrics, estimates) never knows where the data came from. A paid data API can
   later replace the website importers without touching anything else.
3. **Core is independent of the UI.** `core/` must not import Streamlit. The UI could later
   be replaced (e.g. FastAPI + React) without changing the calculation logic.
4. **Transparency.** Every estimate stores its source(s). The UI always shows *where a
   number comes from*, and whether it is actual, estimated or overridden by the user.
5. **Keep history.** Listings are never overwritten, only snapshotted.
6. **Manual triggering.** Data is fetched when the user clicks "Fetch now". There is no
   scheduler yet (planned for later).

## 3. Tech stack

| Purpose | Choice | Why |
|---|---|---|
| Language | Python 3.12 | the user already knows it |
| Packages / env | `uv` | fast, one tool for venv + dependencies |
| Data models | Pydantic v2 | validation + clear schemas |
| Database | SQLite via SQLAlchemy 2.0 | one file, no server; can move to Postgres later |
| UI (first version) | Streamlit + Plotly | quick dashboards in pure Python |
| Config | YAML (`config/*.yaml`) | default assumptions editable without code |
| Tests | pytest | |
| Lint / format | ruff | |
| Version control | Git, one feature branch per milestone | |

## 4. Data model

### 4.1 Enums
- `PropertyType`: `ETW`, `HAUS`, `MFH`, `GRUNDSTUECK`
- `OfferType`: `KAUF` (for sale), `MIETE` (for rent)
- `ValueOrigin`: `ACTUAL` (from the listing), `ESTIMATED`, `OVERRIDE` (set by the user)

### 4.2 `Listing` (the current state of a listing)
| Field | Type | Notes |
|---|---|---|
| id | str | internal UUID |
| source | str | e.g. `sample`, `csv`, later the portal name |
| source_listing_id | str | ID at the source; (`source`, `source_listing_id`) is unique |
| url | str? | |
| offer_type | OfferType | |
| property_type | PropertyType | |
| title | str | |
| city | str | |
| district | str? | part of town / Ortsteil |
| postal_code | str | |
| address | str? | often missing |
| lat, lon | float? | for a map later |
| price | float | purchase price (KAUF) or cold rent per month (MIETE) |
| living_area_m2 | float? | not for GRUNDSTUECK |
| plot_area_m2 | float? | HAUS, MFH, GRUNDSTUECK |
| rooms | float? | |
| units | int? | MFH: number of residential units |
| year_built | int? | |
| condition | str? | e.g. renovated, needs renovation |
| energy_class | str? | |
| actual_rent_month | float? | cold rent if already rented (ETW/MFH) |
| hausgeld_month | float? | ETW: monthly owners' association fee |
| commission_pct | float? | buyer's broker commission; `null` = unknown → use default |
| is_rented | bool? | |
| first_seen, last_seen | datetime | |
| is_active | bool | false if no longer found during a fetch |
| raw | JSON | original data, for debugging |

### 4.3 `ListingSnapshot` (history)
Every fetch creates a snapshot whenever a relevant field has changed (price, area, title,
status). Fields: `listing_id`, `seen_at`, `price`, plus a JSON of the changed fields.

Derived values: **days online**, **number of price changes**, **total price change in %**,
**relisted** (disappeared and came back).

### 4.4 `AreaReference` (area statistics)
One row per value and source:
`area_key` (city / district / postal code), `metric` (`rent_m2`, `buy_price_m2`,
`land_value_m2`), `property_type?`, `segment?` (e.g. size or year-built band),
`value`, `low?`, `high?`, `source` (`mietspiegel`, `gutachterausschuss`, `boris`,
`price_map`, `own_listings`), `valid_from`, `valid_to?`, `note`.

### 4.5 `Override`
`listing_id`, `field` (e.g. `rent_month`, `price`, `living_area_m2`), `value`, `created_at`,
`note`. Overrides always take precedence over any other value.

## 5. Area statistics and rent estimates

### 5.1 Sources
1. **Own rental listings** (`own_listings`): median cold rent per m² by area, property type
   and size band. Only used when there are at least *N* comparable listings (default 5).
2. **Official rent tables** (`mietspiegel`): Berlin 2026, Potsdam 2026, Brandenburg a. d.
   Havel 2026. Entered **by hand** as YAML/CSV under `data/reference/` and loaded with an
   import command. Note: these tables reflect **existing rents** (lower than new-letting
   rents).
3. **Price maps / market reports** (`price_map`, `gutachterausschuss`, `boris`): entered by
   hand for now.
4. **Own sale listings**: median asking price per m², to compare against the area.

### 5.2 Rent estimate (KAUF listings of type ETW, HAUS, MFH)
Order of precedence for the rent used in calculations:
1. `Override`
2. `actual_rent_month` from the listing (if rented)
3. Estimate = living area × rent per m² according to a **strategy** that can be chosen in
   the UI:
   - `market`: own listings, falling back to the price map
   - `mietspiegel`: official table (the conservative value)
   - `blend` (default): weighted average; weights in `config/assumptions.yaml`

The result is a `RentEstimate` object: `value_month`, `rent_m2`, `origin`, the list of
`components` (source, value, weight, sample size) and a `confidence` (`high` / `medium` /
`low`) based on how many sources agree and how many samples there are.

## 6. Metrics

All metrics are **pure functions** in `core/metrics.py`: listing + assumptions → result.
They are calculated when a page is shown, not stored, so changed assumptions take effect
immediately.

### 6.1 Assumptions (`config/assumptions.yaml`, editable in the UI)
| Key | Default | Note |
|---|---|---|
| transfer_tax_pct.berlin | 6.0 | Grunderwerbsteuer |
| transfer_tax_pct.brandenburg | 6.5 | Grunderwerbsteuer |
| notary_land_registry_pct | 2.0 | notary ~1.5 + land registry ~0.5 |
| default_commission_pct | 3.57 | when the listing gives no value |
| equity_pct | 20 | share of total cost paid with own money |
| interest_rate_pct | 3.8 | |
| repayment_pct | 2.0 | initial yearly repayment |
| non_recoverable_costs_pct_of_rent | 15 | costs that can't be passed on to tenants |
| maintenance_eur_m2_year | 12 | maintenance reserve |
| vacancy_pct | 2 | rent loss risk |
| rent_blend_weights | market 0.6 / mietspiegel 0.4 | |
| min_samples_own_listings | 5 | |

Tax rates must be checked against official sources before real use.

### 6.2 For all KAUF listings
- `price_per_m2` (living area, or plot area for GRUNDSTUECK)
- `area_avg_price_per_m2` and `price_vs_area_pct` (negative = cheaper than the area)
- `purchase_costs` = price × (transfer tax + notary/land registry + commission)
- `total_investment` = price + purchase_costs

### 6.3 For ETW, HAUS, MFH (KAUF)
- `annual_cold_rent` = rent per month × 12 (with its origin: actual / estimated / override)
- `gross_yield_pct` = annual_cold_rent / price × 100
- `price_to_rent_factor` = price / annual_cold_rent (Kaufpreisfaktor)
- `net_operating_income` = annual_cold_rent − non-recoverable costs − maintenance − vacancy
- `net_yield_pct` = net_operating_income / total_investment × 100
- Financing: `equity`, `loan`, `annuity_month`, `cashflow_month_pretax`,
  `cash_on_cash_pct` = (cashflow_month × 12) / equity × 100
- MFH in addition: `rent_per_unit`, `rent_upside_pct` = (estimated market rent − actual
  rent) / actual rent

### 6.4 For GRUNDSTUECK
- `price_per_m2` vs. `land_value_m2` (BORIS land value) → `price_vs_land_value_pct`
- No yield metrics (shown as "n/a" in the UI)

### 6.5 For MIETE listings
- `rent_per_m2`, `rent_vs_mietspiegel_pct`, `rent_vs_area_pct`

### 6.6 Simple traffic-light indicator (first version)
Configurable thresholds, e.g. gross yield: green ≥ 5 %, yellow 3.5–5 %, red < 3.5 %.
The final visual design comes later.

## 7. Sample data

`core/sample_data.py` with a fixed seed so results are reproducible:
- ~300 KAUF listings and ~400 MIETE listings, spread over the 3 cities and all 4 types
- Realistic ranges per city (rough guide, does not need to be exact):
  - rent €/m²: Brandenburg a. d. H. 7–10, Potsdam 11–16, Berlin 10–20
  - flat purchase price €/m²: Brandenburg a. d. H. 1,800–3,000, Potsdam 3,500–5,500,
    Berlin 3,500–7,000
- **Realistically messy data:** missing fields, outliers, a few listings with an actual
  rent, MFH with 3–12 units
- **Simulated history:** some listings with 1–3 price drops, some that go offline,
  some relisted
- Sample area references (`AreaReference`) for all 3 cities
- Command: `uv run python -m immo.cli seed --reset`

## 8. UI (Streamlit, multiple pages)

1. **Overview** – table of all KAUF listings with the key metrics and the colour indicator.
   Filters: city, district, type, price, area, rooms, year built, gross yield, net yield,
   cash flow, price vs. area, days online, only price-reduced, only active.
   Sorting by any column. A few summary charts (e.g. yield distribution, €/m² by city).
2. **Detail view** – all data on one property, metrics with their calculation steps,
   rent estimate with every source shown, override fields, price history chart, link to
   the listing.
3. **Assumptions** – edit all assumptions (sliders/inputs) and save them as a profile.
   All metrics update immediately.
4. **Area statistics** – references per area and source side by side; your own medians
   compared with the Mietspiegel and the price map.
5. **Rental listings** – table and filters for MIETE listings.
6. **Data / import** – "Fetch now" button (runs every active adapter), log of the last
   runs (when, how many new/changed/gone), CSV import, reload sample data.

## 9. Data sources (adapters)

```python
class SourceAdapter(Protocol):
    name: str
    def fetch(self, query: SearchQuery) -> Iterable[RawListing]: ...
    def normalize(self, raw: RawListing) -> Listing: ...
```

- `SearchQuery`: region(s), property types, offer type
- Pipeline: `fetch → normalize → validate → upsert + snapshot → deactivate missing`
- Initial adapters: `SampleAdapter`, `CsvAdapter`
- **Later:** real portal adapters. Before building one, check the site's terms of use and
  robots.txt and prefer official APIs. Build in rate limits and caching.
- Deduplication (the same property on several portals): later; prepare a
  `fingerprint` field for it (address/postal code + area + rooms + rounded price).

## 10. Project structure

```
immo-rendite/
├── CLAUDE.md
├── SPEC.md
├── pyproject.toml
├── config/
│   └── assumptions.yaml
├── data/
│   ├── reference/          # Mietspiegel etc. entered by hand (YAML/CSV)
│   └── immo.db             # SQLite (git-ignored)
├── src/immo/
│   ├── core/
│   │   ├── models.py       # Pydantic models + enums
│   │   ├── metrics.py      # pure calculation functions
│   │   ├── estimates.py    # rent estimate, area averages
│   │   ├── assumptions.py  # load/save assumptions
│   │   └── sample_data.py
│   ├── storage/
│   │   ├── db.py           # SQLAlchemy setup
│   │   ├── tables.py
│   │   └── repository.py   # the only place that talks to the DB
│   ├── sources/
│   │   ├── base.py         # SourceAdapter protocol
│   │   ├── sample.py
│   │   └── csv_import.py
│   ├── pipeline/
│   │   └── ingest.py       # fetch → normalize → upsert → snapshot
│   ├── ui/
│   │   ├── app.py          # Streamlit entry point
│   │   └── pages/
│   └── cli.py              # seed, ingest, import-reference
└── tests/
```

## 11. Milestones

Each milestone = its own branch, small commits, tests passing, then merge into `main`.

| # | Content | Done when |
|---|---|---|
| M0 | Repo setup: uv, ruff, pytest, folder structure, .gitignore, README | `uv run pytest` runs (empty) |
| M1 | Data model (models + DB tables + repository) | create/read/upsert tested |
| M2 | Assumptions + metrics engine for all types | unit tests with hand-calculated examples |
| M3 | Sample data generator incl. history + area references | `cli seed` fills the DB |
| M4 | Rent estimate (3 strategies + override) | tests incl. "too few samples" |
| M5 | UI: overview + filters + detail view | runs with `uv run streamlit run src/immo/ui/app.py` |
| M6 | UI: assumptions, area statistics, rental listings, overrides | changes affect metrics immediately |
| M7 | Adapter interface + ingest pipeline + CSV import + "Fetch now" | CSV import creates snapshots correctly |
| M8 | Load real reference data (Mietspiegel tables) | values visible on the area page |
| later | real portal adapters, scheduler (twice a day), notifications, map, design, deduplication, deployment | |

## 12. Not in scope for now
- Automatic scheduling
- Users / login
- Tax calculation (depreciation etc.)
- Final visual design
- Scraping real portals
