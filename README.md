# Immo-Rendite

A local web app that collects real-estate listings for Brandenburg an der Havel, Potsdam
and Berlin and automatically calculates investment metrics: gross and net yield, the
price-to-rent multiple (Kaufpreisfaktor), cash flow and the comparison with area averages.

> Status: proof of concept (milestones M0–M7). Works with **sample data** and **CSV
> imports**; the area references are invented sample values until the real rent tables
> are entered (M8).

## Features
- Overview of properties for sale (flats, houses, apartment buildings, plots) with
  filters, a simple good/fair/weak signal and summary charts
- Metrics calculated on the fly: purchase costs, gross and net yield, Kaufpreisfaktor,
  cash flow, cash-on-cash – every step visible in the detail view
- Assumptions editable in the app (interest, equity, costs …) and saved as profiles
- Rent estimate from own rental listings, official rent tables (Mietspiegel) and price
  maps, with every source shown; can be overridden by hand per property
- Price history for every listing (price drops, days online, relisted)
- Area statistics: own medians next to the reference sources
- Swappable data sources (adapter pattern): sample market and CSV import so far

## Requirements
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Getting started
```bash
uv sync                                          # install dependencies
uv run python -m immo.cli seed --reset           # load sample data
uv run streamlit run src/immo/ui/app.py          # start the app
```

More commands:
```bash
uv run python -m immo.cli ingest                 # fetch from all active adapters
uv run python -m immo.cli ingest --csv data/examples/listings_example.csv
```

## Importing your own listings (CSV)
One listing per row, `;` or `,` as separator, column names as in
[`data/examples/listings_example.csv`](data/examples/listings_example.csv). Required:
`source_listing_id`, `offer_type` (`KAUF`/`MIETE`), `property_type`
(`ETW`/`HAUS`/`MFH`/`GRUNDSTUECK`), `title`, `city`, `postal_code`, `price`. Importing the
same `source_listing_id` again updates the listing and records the change in its history.

## Project layout
```
src/immo/core/      models, metrics, estimates – pure Python, no DB, no UI
src/immo/storage/   SQLite via SQLAlchemy; repository.py is the only DB access
src/immo/sources/   data-source adapters (sample, csv)
src/immo/pipeline/  ingest: fetch → normalize → validate → upsert + snapshot
src/immo/ui/        Streamlit app (pages/ = one script per page)
config/             assumptions.yaml (defaults), profiles/ (your saved sets)
```

## Development
```bash
uv run pytest                                    # run tests
uv run ruff check --fix . && uv run ruff format .
```

## Documentation
- [`SPEC.md`](SPEC.md) – full specification and milestones
- [`CLAUDE.md`](CLAUDE.md) – working rules for Claude Code
- [`PROGRESS.md`](PROGRESS.md) – what was built per milestone, decisions and open questions

## Disclaimer
The calculations are a starting point for a decision, not tax or investment advice.
