# Immo-Rendite

A local web app that collects real-estate listings for Brandenburg an der Havel, Potsdam
and Berlin and automatically calculates investment metrics: gross and net yield, the
price-to-rent multiple (Kaufpreisfaktor), cash flow and the comparison with area averages.

> Status: early proof of concept. Currently works with **sample data only**.

## Features (planned)
- Overview of properties for sale (flats, houses, apartment buildings, plots) with filters
- Metrics calculated automatically, assumptions editable (interest, down payment, costs …)
- Rent estimate from three sources: own rental listings, official rent tables
  (Mietspiegel), price maps; can be overridden by hand per property
- Price history for every listing (price drops, days online)
- Swappable data sources (adapter pattern)

## Requirements
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Getting started
```bash
uv sync                                          # install dependencies
uv run python -m immo.cli seed --reset           # load sample data
uv run streamlit run src/immo/ui/app.py          # start the app
```

## Development
```bash
uv run pytest                                    # run tests
uv run ruff check --fix . && uv run ruff format .
```

## Documentation
- [`SPEC.md`](SPEC.md) – full specification and milestones
- [`CLAUDE.md`](CLAUDE.md) – working rules for Claude Code
- `PROGRESS.md` – progress log (created during development)

## Disclaimer
The calculations are a starting point for a decision, not tax or investment advice.
