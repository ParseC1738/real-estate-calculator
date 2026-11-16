"""Assumptions used by all calculations (SPEC §6.1): model, loading and saving.

The defaults live twice on purpose: in `config/assumptions.yaml` (for editing without
code) and as field defaults here (so a missing key or a missing file still works). A
test makes sure both stay identical.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from immo.paths import DEFAULT_ASSUMPTIONS_PATH, PROFILES_DIR


class RentStrategy(StrEnum):
    MARKET = "market"
    MIETSPIEGEL = "mietspiegel"
    BLEND = "blend"


class _Strict(BaseModel):
    # extra="forbid": an unknown key in the YAML (e.g. a typo) raises an error
    model_config = ConfigDict(extra="forbid")


class TransferTax(_Strict):
    berlin: float = Field(default=6.0, ge=0, le=100)
    brandenburg: float = Field(default=6.5, ge=0, le=100)


class BlendWeights(_Strict):
    market: float = Field(default=0.6, ge=0)
    mietspiegel: float = Field(default=0.4, ge=0)

    @model_validator(mode="after")
    def _not_all_zero(self) -> BlendWeights:
        if self.market + self.mietspiegel <= 0:
            raise ValueError("at least one blend weight must be greater than 0")
        return self


class Threshold(_Strict):
    """Traffic light: green >= green_min, yellow >= yellow_min, otherwise red."""

    green_min: float
    yellow_min: float

    @model_validator(mode="after")
    def _ordered(self) -> Threshold:
        if self.yellow_min > self.green_min:
            raise ValueError("yellow_min must not be greater than green_min")
        return self


def _default_thresholds() -> dict[str, Threshold]:
    return {"gross_yield_pct": Threshold(green_min=5.0, yellow_min=3.5)}


class Assumptions(_Strict):
    transfer_tax_pct: TransferTax = Field(default_factory=TransferTax)
    notary_land_registry_pct: float = Field(default=2.0, ge=0, le=100)
    default_commission_pct: float = Field(default=3.57, ge=0, le=100)
    equity_pct: float = Field(default=20.0, ge=0, le=100)
    interest_rate_pct: float = Field(default=3.8, ge=0, le=100)
    repayment_pct: float = Field(default=2.0, ge=0, le=100)
    non_recoverable_costs_pct_of_rent: float = Field(default=15.0, ge=0, le=100)
    maintenance_eur_m2_year: float = Field(default=12.0, ge=0)
    vacancy_pct: float = Field(default=2.0, ge=0, le=100)
    rent_strategy: RentStrategy = RentStrategy.BLEND
    rent_blend_weights: BlendWeights = Field(default_factory=BlendWeights)
    min_samples_own_listings: int = Field(default=5, ge=1)
    traffic_light: dict[str, Threshold] = Field(default_factory=_default_thresholds)

    def transfer_tax_for(self, city: str) -> float:
        """Transfer tax rate for a city.

        The tax is set per federal state. In the app's region everything that is not
        Berlin lies in Brandenburg (Potsdam, Brandenburg a. d. Havel and surroundings).
        """
        if city.strip().lower() == "berlin":
            return self.transfer_tax_pct.berlin
        return self.transfer_tax_pct.brandenburg


def load_assumptions(path: Path | None = None) -> Assumptions:
    """Read assumptions from YAML. A missing file yields the built-in defaults."""
    path = path or DEFAULT_ASSUMPTIONS_PATH
    if not path.exists():
        return Assumptions()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Assumptions.model_validate(data)


def save_assumptions(assumptions: Assumptions, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = assumptions.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# --- profiles: named sets of assumptions, one YAML file each ---------------------------


def _profile_filename(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("profile name must contain at least one letter or digit")
    return f"{slug}.yaml"


def save_profile(assumptions: Assumptions, name: str, directory: Path | None = None) -> Path:
    path = (directory or PROFILES_DIR) / _profile_filename(name)
    save_assumptions(assumptions, path)
    return path


def list_profiles(directory: Path | None = None) -> list[str]:
    directory = directory or PROFILES_DIR
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.yaml"))


def load_profile(name: str, directory: Path | None = None) -> Assumptions:
    path = (directory or PROFILES_DIR) / _profile_filename(name)
    if not path.exists():
        raise FileNotFoundError(f"profile not found: {name}")
    return load_assumptions(path)
