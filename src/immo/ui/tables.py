"""Turn evaluations into pandas tables and filter them.

No Streamlit in here: these are plain functions (evaluations in, DataFrame out), so the
table logic can be unit-tested without starting the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from immo.core.estimates import MarketIndex
from immo.core.evaluate import BuyEvaluation, RentalEvaluation
from immo.core.metrics import pct_diff
from immo.core.models import AreaMetric, PropertyType, ReferenceSource, ValueOrigin
from immo.ui import formatting as fmt

Range = tuple[float, float]


def buy_table(evaluations: list[BuyEvaluation]) -> pd.DataFrame:
    """One row per KAUF listing with the key metrics (raw numbers, not rounded)."""
    rows = []
    for e in evaluations:
        listing, m, history = e.effective, e.metrics, e.history
        rows.append(
            {
                "id": listing.id,
                "signal": fmt.signal(m.indicator) if m.indicator else None,
                "title": listing.title,
                "city": listing.city,
                "district": listing.district,
                "type": listing.property_type.value,
                "price": m.price,
                "area_m2": m.area_m2,
                "price_per_m2": m.price_per_m2,
                "price_vs_area_pct": m.price_vs_area_pct,
                "rooms": listing.rooms,
                "year_built": listing.year_built,
                "rent_month": m.rent_month,
                "rent_origin": fmt.origin(m.rent_origin) if m.rent_origin else None,
                "gross_yield_pct": m.gross_yield_pct,
                "net_yield_pct": m.net_yield_pct,
                "price_to_rent_factor": m.price_to_rent_factor,
                "cashflow_month": m.cashflow_month_pretax,
                "cash_on_cash_pct": m.cash_on_cash_pct,
                "days_online": history.days_online if history else None,
                "price_change_pct": history.total_price_change_pct if history else None,
                "price_drops": history.price_drop_count if history else 0,
                "relisted": history.relisted if history else False,
                "is_active": listing.is_active,
                "overridden": e.effective != e.listing or m.rent_origin is ValueOrigin.OVERRIDE,
                "url": listing.url,
            }
        )
    return pd.DataFrame(rows, columns=list(rows[0]) if rows else _BUY_COLUMNS)


_BUY_COLUMNS = [
    "id", "signal", "title", "city", "district", "type", "price", "area_m2", "price_per_m2",
    "price_vs_area_pct", "rooms", "year_built", "rent_month", "rent_origin", "gross_yield_pct",
    "net_yield_pct", "price_to_rent_factor", "cashflow_month", "cash_on_cash_pct", "days_online",
    "price_change_pct", "price_drops", "relisted", "is_active", "overridden", "url",
]  # fmt: skip


@dataclass
class BuyFilters:
    """Filter settings of the overview page. `None` / empty means "no restriction"."""

    cities: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    price: Range | None = None
    area_m2: Range | None = None
    rooms: Range | None = None
    year_built: Range | None = None
    days_online: Range | None = None
    min_gross_yield_pct: float | None = None
    min_net_yield_pct: float | None = None
    min_cashflow_month: float | None = None
    max_price_vs_area_pct: float | None = None
    only_price_reduced: bool = False
    only_active: bool = False


def _mask(
    table: pd.DataFrame,
    *,
    isin: dict[str, list] | None = None,
    ranges: dict[str, Range | None] | None = None,
    minimums: dict[str, float | None] | None = None,
    maximums: dict[str, float | None] | None = None,
) -> pd.Series:
    """Combine all active restrictions with AND. Unknown values (NaN) fail a restriction."""
    mask = pd.Series(True, index=table.index)
    for column, allowed in (isin or {}).items():
        if allowed:
            mask &= table[column].isin(allowed)
    for column, bounds in (ranges or {}).items():
        if bounds is not None:
            mask &= table[column].between(bounds[0], bounds[1])
    for column, minimum in (minimums or {}).items():
        if minimum is not None:
            mask &= table[column] >= minimum
    for column, maximum in (maximums or {}).items():
        if maximum is not None:
            mask &= table[column] <= maximum
    return mask


def filter_buy_table(table: pd.DataFrame, filters: BuyFilters) -> pd.DataFrame:
    """Apply the filters. A listing with an unknown value fails an active filter on it

    (e.g. a plot has no gross yield, so it disappears once a minimum yield is set).
    """
    mask = _mask(
        table,
        isin={"city": filters.cities, "district": filters.districts, "type": filters.types},
        ranges={
            "price": filters.price,
            "area_m2": filters.area_m2,
            "rooms": filters.rooms,
            "year_built": filters.year_built,
            "days_online": filters.days_online,
        },
        minimums={
            "gross_yield_pct": filters.min_gross_yield_pct,
            "net_yield_pct": filters.min_net_yield_pct,
            "cashflow_month": filters.min_cashflow_month,
        },
        maximums={"price_vs_area_pct": filters.max_price_vs_area_pct},
    )
    if filters.only_price_reduced:
        mask &= table["price_drops"] > 0
    if filters.only_active:
        mask &= table["is_active"]
    return table[mask]


# --- rental listings -------------------------------------------------------------------

_RENTAL_COLUMNS = [
    "id", "title", "city", "district", "type", "rent_month", "area_m2", "rent_per_m2",
    "rent_vs_mietspiegel_pct", "rent_vs_area_pct", "rooms", "year_built", "days_online",
    "price_change_pct", "is_active", "url",
]  # fmt: skip


def rental_table(evaluations: list[RentalEvaluation]) -> pd.DataFrame:
    """One row per MIETE listing (SPEC §6.5 metrics)."""
    rows = []
    for e in evaluations:
        listing, m, history = e.listing, e.metrics, e.history
        rows.append(
            {
                "id": listing.id,
                "title": listing.title,
                "city": listing.city,
                "district": listing.district,
                "type": listing.property_type.value,
                "rent_month": listing.price,
                "area_m2": listing.living_area_m2,
                "rent_per_m2": m.rent_per_m2,
                "rent_vs_mietspiegel_pct": m.rent_vs_mietspiegel_pct,
                "rent_vs_area_pct": m.rent_vs_area_pct,
                "rooms": listing.rooms,
                "year_built": listing.year_built,
                "days_online": history.days_online if history else None,
                "price_change_pct": history.total_price_change_pct if history else None,
                "is_active": listing.is_active,
                "url": listing.url,
            }
        )
    return pd.DataFrame(rows, columns=_RENTAL_COLUMNS)


@dataclass
class RentalFilters:
    cities: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    rent_month: Range | None = None
    area_m2: Range | None = None
    rooms: Range | None = None
    rent_per_m2: Range | None = None
    only_active: bool = False


def filter_rental_table(table: pd.DataFrame, filters: RentalFilters) -> pd.DataFrame:
    mask = _mask(
        table,
        isin={"city": filters.cities, "district": filters.districts, "type": filters.types},
        ranges={
            "rent_month": filters.rent_month,
            "area_m2": filters.area_m2,
            "rooms": filters.rooms,
            "rent_per_m2": filters.rent_per_m2,
        },
    )
    if filters.only_active:
        mask &= table["is_active"]
    return table[mask]


# --- area statistics -------------------------------------------------------------------

# which stored sources exist for which metric (own listings are always added)
AREA_SOURCES: dict[AreaMetric, tuple[ReferenceSource, ...]] = {
    AreaMetric.RENT_M2: (ReferenceSource.MIETSPIEGEL, ReferenceSource.PRICE_MAP),
    AreaMetric.BUY_PRICE_M2: (ReferenceSource.PRICE_MAP, ReferenceSource.GUTACHTERAUSSCHUSS),
    AreaMetric.LAND_VALUE_M2: (ReferenceSource.BORIS,),
}


def area_table(
    index: MarketIndex,
    area_keys: list[str],
    metric: AreaMetric,
    property_type: PropertyType | None,
) -> pd.DataFrame:
    """Sources side by side: one row per area, one column per source (SPEC §8.4).

    Extra columns show how far the own-listings median is above (+) or below (-) each
    stored source, in percent.
    """
    sources = AREA_SOURCES[metric]
    rows = []
    for area_key in area_keys:
        own = index.own_median(metric, area_key, property_type)
        row: dict = {
            "area": area_key,
            "own_listings": own.value if own else None,
            "own_samples": own.sample_size if own else None,
        }
        for source in sources:
            stored = index.stored_reference(metric, source, area_key, property_type)
            row[source.value] = stored.value if stored else None
        for source in sources:
            row[f"own_vs_{source.value}_pct"] = pct_diff(row["own_listings"], row[source.value])
        rows.append(row)
    columns = ["area", "own_listings", "own_samples", *(s.value for s in sources)]
    columns += [f"own_vs_{s.value}_pct" for s in sources]
    return pd.DataFrame(rows, columns=columns)
