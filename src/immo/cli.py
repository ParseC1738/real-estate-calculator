"""Command line interface: `uv run python -m immo.cli <command>`.

Kept deliberately thin: it parses arguments, calls a function from `pipeline/` and
prints the result. All real work is importable and testable without the CLI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from immo.core.models import FetchRun
from immo.core.sample_data import DEFAULT_SEED
from immo.paths import db_path
from immo.pipeline.ingest import run_ingest
from immo.pipeline.seed import seed_database
from immo.sources.csv_import import CsvAdapter
from immo.sources.registry import active_adapters
from immo.storage.db import make_engine
from immo.storage.repository import Repository


def _cmd_seed(args: argparse.Namespace) -> int:
    repo = Repository(make_engine())
    try:
        summary = seed_database(repo, seed=args.seed, reset=args.reset)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Database: {db_path()}")
    print(f"Replayed {summary.rounds} simulated weekly fetches (seed {args.seed}).")
    print(f"  listings:        {summary.listings_total} ({summary.listings_active} active)")
    print(f"  snapshots:       {summary.snapshots}")
    print(f"  area references: {summary.area_references}")
    return 0


def _print_run(run: FetchRun) -> None:
    print(
        f"{run.source}: fetched {run.fetched} | new {run.new} | changed {run.changed} | "
        f"relisted {run.relisted} | gone {run.gone} | unchanged {run.unchanged} | "
        f"errors {len(run.errors)}"
    )
    if run.note:
        print(f"  note: {run.note}")
    for message in run.errors[:10]:
        print(f"  ! {message}")
    if len(run.errors) > 10:
        print(f"  ... and {len(run.errors) - 10} more")


def _cmd_ingest(args: argparse.Namespace) -> int:
    """Run the pipeline: for a CSV file, or for every active adapter ("fetch now")."""
    repo = Repository(make_engine())
    if args.csv:
        try:
            adapter = CsvAdapter.from_path(args.csv)
        except OSError as error:
            print(f"Error: cannot read {args.csv}: {error}", file=sys.stderr)
            return 1
        runs = [run_ingest(adapter, repo, deactivate_missing=args.deactivate_missing)]
    else:
        runs = [run_ingest(adapter, repo) for adapter in active_adapters(repo)]
    for run in runs:
        _print_run(run)
    failed = any(run.note.startswith("fetch failed") for run in runs)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="immo", description="Immo-Rendite command line")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="load reproducible sample data into the database")
    seed.add_argument("--reset", action="store_true", help="delete ALL existing data first")
    seed.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default 42)")
    seed.set_defaults(func=_cmd_seed)

    ingest = commands.add_parser(
        "ingest", help="fetch from every active adapter, or import a CSV file with --csv"
    )
    ingest.add_argument("--csv", metavar="FILE", help="import listings from this CSV file")
    ingest.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="with --csv: mark csv listings that are NOT in the file as no longer online",
    )
    ingest.set_defaults(func=_cmd_ingest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
