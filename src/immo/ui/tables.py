"""Turn evaluations into pandas tables and filter them.

No Streamlit in here: these are plain functions (evaluations in, DataFrame out), so the
table logic can be unit-tested without starting the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from immo.core.evaluate import BuyEvaluation
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
                "url": listing.url,
            }
        )
    return pd.DataFrame(rows, columns=list(rows[0]) if rows else _BUY_COLUMNS)


_BUY_COLUMNS = [
    "id", "signal", "title", "city", "district", "type", "price", "area_m2", "price_per_m2",
    "price_vs_area_pct", "rooms", "year_built", "rent_month", "rent_origin", "gross_yield_pct",
    "net_yield_pct", "price_to_rent_factor", "cashflow_month", "cash_on_cash_pct", "days_online",
    "price_change_pct", "price_drops", "relisted", "is_active", "url",
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


def filter_buy_table(table: pd.DataFrame, filters: BuyFilters) -> pd.DataFrame:
    """Apply the filters. A listing with an unknown value fails an active filter on it

    (e.g. a plot has no gross yield, so it disappears once a minimum yield is set).
    """
    mask = pd.Series(True, index=table.index)
    for column, allowed in (
        ("city", filters.cities),
        ("district", filters.districts),
        ("type", filters.types),
    ):
        if allowed:
            mask &= table[column].isin(allowed)
    for column, bounds in (
        ("price", filters.price),
        ("area_m2", filters.area_m2),
        ("rooms", filters.rooms),
        ("year_built", filters.year_built),
        ("days_online", filters.days_online),
    ):
        if bounds is not None:
            mask &= table[column].between(bounds[0], bounds[1])  # NaN -> False
    for column, minimum in (
        ("gross_yield_pct", filters.min_gross_yield_pct),
        ("net_yield_pct", filters.min_net_yield_pct),
        ("cashflow_month", filters.min_cashflow_month),
    ):
        if minimum is not None:
            mask &= table[column] >= minimum
    if filters.max_price_vs_area_pct is not None:
        mask &= table["price_vs_area_pct"] <= filters.max_price_vs_area_pct
    if filters.only_price_reduced:
        mask &= table["price_drops"] > 0
    if filters.only_active:
        mask &= table["is_active"]
    return table[mask]
