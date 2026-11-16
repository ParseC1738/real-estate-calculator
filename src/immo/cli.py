"""Command line interface: `uv run python -m immo.cli <command>`.

Kept deliberately thin: it parses arguments, calls a function from `pipeline/` and
prints the result. All real work is importable and testable without the CLI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from immo.core.sample_data import DEFAULT_SEED
from immo.paths import db_path
from immo.pipeline.seed import seed_database
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="immo", description="Immo-Rendite command line")
    commands = parser.add_subparsers(dest="command", required=True)

    seed = commands.add_parser("seed", help="load reproducible sample data into the database")
    seed.add_argument("--reset", action="store_true", help="delete ALL existing data first")
    seed.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default 42)")
    seed.set_defaults(func=_cmd_seed)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
