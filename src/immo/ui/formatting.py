"""Display formatting. Numbers are rounded HERE and nowhere else (CLAUDE.md rule)."""

from __future__ import annotations

from immo.core.estimates import Confidence
from immo.core.metrics import Indicator
from immo.core.models import PropertyType, ValueOrigin

MISSING = "n/a"

TYPE_LABEL = {
    PropertyType.ETW: "Flat (ETW)",
    PropertyType.HAUS: "House",
    PropertyType.MFH: "Apartment building (MFH)",
    PropertyType.GRUNDSTUECK: "Plot",
}
TYPE_SHORT = {"ETW": "Flat", "HAUS": "House", "MFH": "MFH", "GRUNDSTUECK": "Plot"}
# Status is never shown by colour alone: every signal has an icon AND a word.
SIGNAL_LABEL = {
    Indicator.GREEN: "🟢 good",
    Indicator.YELLOW: "🟡 fair",
    Indicator.RED: "🔴 weak",
}
ORIGIN_LABEL = {
    ValueOrigin.ACTUAL: "📄 actual",
    ValueOrigin.ESTIMATED: "🧮 estimated",
    ValueOrigin.OVERRIDE: "✏️ override",
}
CONFIDENCE_LABEL = {
    Confidence.HIGH: "high",
    Confidence.MEDIUM: "medium",
    Confidence.LOW: "low",
}
SOURCE_LABEL = {
    "own_listings": "Own listings",
    "mietspiegel": "Mietspiegel (official rent table)",
    "price_map": "Price map",
    "gutachterausschuss": "Valuation committee (Gutachterausschuss)",
    "boris": "BORIS land value",
}


def eur(value: float | None, digits: int = 0) -> str:
    if value is None:
        return MISSING
    return f"{value:,.{digits}f} €"


def pct(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return MISSING
    sign = "+" if signed else ""
    return f"{value:{sign},.{digits}f} %"


def num(value: float | None, digits: int = 1, unit: str = "") -> str:
    if value is None:
        return MISSING
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}" if unit else text


def area(value: float | None) -> str:
    return num(value, 1, "m²")


def origin(value: ValueOrigin | None) -> str:
    return ORIGIN_LABEL.get(value, MISSING)


def signal(value: Indicator | None) -> str:
    return SIGNAL_LABEL.get(value, MISSING)


def source(value: str) -> str:
    return SOURCE_LABEL.get(str(value), str(value))
