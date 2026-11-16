"""Put the pieces together: overrides -> rent -> metrics -> history for one listing.

The UI calls these functions once per listing. They are still pure: everything they
need (index, assumptions, overrides, snapshots) is passed in.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from pydantic import BaseModel

from immo.core.assumptions import Assumptions
from immo.core.estimates import MarketIndex, RentEstimate, estimate_rent, resolve_rent
from immo.core.history import HistorySummary, summarize_history
from immo.core.metrics import (
    YIELD_TYPES,
    BuyMetrics,
    RentInput,
    RentListingMetrics,
    buy_metrics,
    rent_listing_metrics,
)
from immo.core.models import AreaReference, Listing, ListingSnapshot, Override
from immo.core.overrides import apply_overrides


class BuyEvaluation(BaseModel):
    """Everything the UI shows about one KAUF listing."""

    listing: Listing  # as stored
    effective: Listing  # after overrides (what the metrics were calculated with)
    rent: RentEstimate | None  # the rent used: override, actual or estimate
    market_rent: RentEstimate | None  # the pure estimate, always shown for comparison
    area_price: AreaReference | None
    land_value: AreaReference | None
    metrics: BuyMetrics
    history: HistorySummary | None = None


class RentalEvaluation(BaseModel):
    listing: Listing
    mietspiegel: AreaReference | None
    area_rent: AreaReference | None
    metrics: RentListingMetrics
    history: HistorySummary | None = None


def evaluate_buy(
    listing: Listing,
    index: MarketIndex,
    assumptions: Assumptions,
    overrides: Iterable[Override] = (),
    snapshots: list[ListingSnapshot] | None = None,
    now: datetime | None = None,
) -> BuyEvaluation:
    effective = apply_overrides(listing, overrides)
    current = effective.listing

    rent = market_rent = None
    if current.property_type in YIELD_TYPES:
        market_rent = estimate_rent(current, index, assumptions)
        rent = resolve_rent(current, market_rent, effective.rent_override)

    area_price = index.area_price_m2(current)
    land_value = index.land_value_m2(current)
    metrics = buy_metrics(
        current,
        assumptions,
        rent=RentInput(value_month=rent.value_month, origin=rent.origin) if rent else None,
        area_avg_price_per_m2=area_price.value if area_price else None,
        land_value_m2=land_value.value if land_value else None,
        market_rent_month=market_rent.value_month if market_rent else None,
        price_origin=effective.price_origin,
        area_origin=effective.area_origin,
    )
    history = None
    if snapshots is not None and now is not None:
        # history is about the listing as published, so it uses the stored listing
        history = summarize_history(listing, snapshots, now)
    return BuyEvaluation(
        listing=listing,
        effective=current,
        rent=rent,
        market_rent=market_rent,
        area_price=area_price,
        land_value=land_value,
        metrics=metrics,
        history=history,
    )


def evaluate_rental(
    listing: Listing,
    index: MarketIndex,
    snapshots: list[ListingSnapshot] | None = None,
    now: datetime | None = None,
) -> RentalEvaluation:
    mietspiegel = index.mietspiegel_rent_m2(listing)
    area_rent = index.own_rent_m2(listing)
    history = None
    if snapshots is not None and now is not None:
        history = summarize_history(listing, snapshots, now)
    return RentalEvaluation(
        listing=listing,
        mietspiegel=mietspiegel,
        area_rent=area_rent,
        metrics=rent_listing_metrics(
            listing,
            mietspiegel_rent_m2=mietspiegel.value if mietspiegel else None,
            area_rent_m2=area_rent.value if area_rent else None,
        ),
        history=history,
    )
