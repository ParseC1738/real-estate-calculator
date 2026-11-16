"""Central place for file-system locations, so no module hard-codes paths."""

import os
from pathlib import Path

# src/immo/paths.py -> parents[2] is the repository root (works with the editable install)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"
PROFILES_DIR = CONFIG_DIR / "profiles"
DEFAULT_ASSUMPTIONS_PATH = CONFIG_DIR / "assumptions.yaml"


def db_path() -> Path:
    """Location of the SQLite file. `IMMO_DB_PATH` overrides the default (used by tests)."""
    override = os.environ.get("IMMO_DB_PATH")
    return Path(override) if override else DATA_DIR / "immo.db"
