# CLAUDE.md – Immo-Rendite

Local web app that collects real-estate listings (Brandenburg a. d. Havel, Potsdam,
Berlin) and calculates investment metrics. **The full specification is in `SPEC.md` – read
it before every larger task.**

## About the user
- Computer Engineering master's student who knows Python and is new to Claude Code.
- Wants to **learn**: explain *why* you are doing something (architecture decisions, Git
  steps, patterns such as adapters or pure functions), not only *what*. Keep explanations
  short, but don't skip them.
- When there are several sensible options, briefly lay out the trade-offs and let the user
  decide.

## Workflow
- Work **one milestone at a time** (see SPEC.md §11). Before starting, present a short plan
  and wait for approval.
- Create a branch per milestone: `git switch -c m<N>-<short-name>`.
- Small, meaningful commits (Conventional Commits: `feat:`, `fix:`, `test:`, `refactor:`,
  `docs:`).
- Before every commit: `uv run ruff check --fix . && uv run ruff format . && uv run pytest`.
- At the end of a milestone: summary + how the user can try it out themselves.

## Architecture rules (must be followed)
- `core/` has **no** dependency on Streamlit, SQLAlchemy or the internet.
- Metrics are **pure functions** (input → output, no side effects) and fully tested.
- Only `storage/repository.py` accesses the database.
- New data sources only as an adapter in `sources/` that implements `SourceAdapter`.
- Every estimated or overridden value carries its origin (`ValueOrigin`).
- Money values in EUR as `float`, rounded only when displayed. Percentages as e.g. `5.2`
  (not `0.052`).
- No real portal scraping without the user's explicit approval.

## Commands
```bash
uv sync                                          # install dependencies
uv run pytest                                    # tests
uv run python -m immo.cli seed --reset           # load sample data
uv run streamlit run src/immo/ui/app.py          # start the UI
```

## Domain glossary
- **Kaltmiete** – rent without heating/utility costs
- **Kaufpreisfaktor** – price ÷ annual cold rent
- **Bruttomietrendite** – gross yield: annual cold rent ÷ price × 100
- **Kaufnebenkosten** – purchase costs: transfer tax (Grunderwerbsteuer) + notary/land
  registry + broker commission
- **Hausgeld** – monthly fee a flat owner pays to the owners' association; only part of it
  can be passed on to the tenant
- **Mietspiegel** – official local rent table (reflects existing rents)
- **Bodenrichtwert / BORIS** – official land value per m²
