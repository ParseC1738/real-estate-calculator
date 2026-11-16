"""Rent estimates and area averages (SPEC §5).

Two parts:
- `MarketIndex` groups the own listings and the stored references once, so looking up
  "what is the typical rent / price here?" is a dictionary access per listing.
- `estimate_rent()` / `resolve_rent()` turn those lookups into a `RentEstimate` that
  records every source it used (transparency principle, SPEC §2.4).

Everything is pure: the index is built from plain lists, nothing is read from a database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from statistics import median, quantiles

from pydantic import BaseModel

from immo.core.assumptions import Assumptions, RentStrategy
from immo.core.models import (
    AreaMetric,
    AreaReference,
    Listing,
    OfferType,
    PropertyType,
    ReferenceSource,
    ValueOrigin,
    area_keys_for,
    city_key,
    district_key,
)

# Size bands for comparing like with like (small flats cost more per m² than large ones).
SIZE_BANDS: tuple[tuple[float, str], ...] = (
    (40, "<40"),
    (60, "40-60"),
    (90, "60-90"),
    (130, "90-130"),
    (float("inf"), ">130"),
)
# Two sources "agree" when they are within this distance of the estimate.
AGREEMENT_TOLERANCE_PCT = 25.0


def size_band(area_m2: float | None) -> str | None:
    if area_m2 is None:
        return None
    for upper, label in SIZE_BANDS:
        if area_m2 < upper:
            return label
    return None  # pragma: no cover - unreachable, the last band is open-ended


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RentComponent(BaseModel):
    """One source that was looked at for a rent estimate."""

    source: ReferenceSource
    rent_m2: float
    weight: float  # share in the final value; 0 = shown for comparison only
    sample_size: int | None = None
    area_key: str
    note: str = ""


class RentEstimate(BaseModel):
    """The monthly cold rent used for a listing, and where it comes from."""

    value_month: float
    rent_m2: float | None
    origin: ValueOrigin
    strategy: RentStrategy | None = None  # None for actual rents and overrides
    components: list[RentComponent] = []
    confidence: Confidence


# --- the index -------------------------------------------------------------------------

_GroupKey = tuple[str, PropertyType | None, str | None]  # (area_key, type, size band)


def _unit_area(listing: Listing) -> float | None:
    """Area used to pick the size band: an MFH is compared by its average flat size."""
    if listing.living_area_m2 is None:
        return None
    if listing.property_type is PropertyType.MFH:
        return listing.living_area_m2 / listing.units if listing.units else None
    return listing.living_area_m2


def _comparable_rental_type(property_type: PropertyType) -> PropertyType:
    """Which rental listings are comparable: an MFH consists of flats."""
    return PropertyType.HAUS if property_type is PropertyType.HAUS else PropertyType.ETW


class MarketIndex:
    """Own listings and references, grouped for fast lookups.

    Build it once per page view from everything in the database; then ask it per
    listing. `min_samples` is the minimum number of own listings for a usable median.
    """

    def __init__(
        self,
        listings: Iterable[Listing],
        references: Iterable[AreaReference],
        min_samples: int = 5,
        on_date: date | None = None,
    ) -> None:
        self.min_samples = min_samples
        self.on_date = on_date or date.today()
        self._rents: dict[_GroupKey, list[float]] = defaultdict(list)
        self._prices: dict[_GroupKey, list[float]] = defaultdict(list)
        self._references: dict[tuple[AreaMetric, ReferenceSource, str], list[AreaReference]] = (
            defaultdict(list)
        )

        for listing in listings:
            self._add_listing(listing)
        for reference in references:
            if self._is_valid(reference):
                key = (reference.metric, reference.source, reference.area_key)
                self._references[key].append(reference)

    def _is_valid(self, reference: AreaReference) -> bool:
        if reference.valid_from > self.on_date:
            return False
        return reference.valid_to is None or reference.valid_to >= self.on_date

    def _add_listing(self, listing: Listing) -> None:
        is_plot = listing.property_type is PropertyType.GRUNDSTUECK
        area = listing.plot_area_m2 if is_plot else listing.living_area_m2
        if not area:
            return
        per_m2 = listing.price / area
        target = self._rents if listing.offer_type is OfferType.MIETE else self._prices
        band = size_band(_unit_area(listing))
        city = city_key(listing.city)
        keys: list[_GroupKey] = [(city, listing.property_type, None), (city, None, None)]
        if band:
            keys.append((city, listing.property_type, band))
        if listing.district:
            district = district_key(listing.city, listing.district)
            keys.append((district, listing.property_type, None))
            if band:
                keys.append((district, listing.property_type, band))
        for key in keys:
            target[key].append(per_m2)

    def _median_reference(
        self,
        groups: dict[_GroupKey, list[float]],
        candidates: list[_GroupKey],
        metric: AreaMetric,
    ) -> AreaReference | None:
        """Median of the first (most specific) group with enough samples."""
        for key in candidates:
            values = groups.get(key, [])
            if len(values) < self.min_samples:
                continue
            low, _, high = quantiles(values, n=4) if len(values) >= 2 else (values[0],) * 3
            area_key, property_type, band = key
            return AreaReference(
                area_key=area_key,
                metric=metric,
                property_type=property_type,
                segment=band,
                value=median(values),
                low=low,
                high=high,
                source=ReferenceSource.OWN_LISTINGS,
                valid_from=self.on_date,
                note=f"median of {len(values)} own listings",
                sample_size=len(values),
            )
        return None

    def _candidates(self, listing: Listing, property_type: PropertyType) -> list[_GroupKey]:
        """Group keys from most to least specific."""
        band = size_band(_unit_area(listing))
        city = city_key(listing.city)
        candidates: list[_GroupKey] = []
        if listing.district:
            district = district_key(listing.city, listing.district)
            if band:
                candidates.append((district, property_type, band))
            candidates.append((district, property_type, None))
        if band:
            candidates.append((city, property_type, band))
        candidates.append((city, property_type, None))
        return candidates

    # --- lookups -------------------------------------------------------------------

    def own_rent_m2(self, listing: Listing) -> AreaReference | None:
        """Median asking rent per m² of comparable own rental listings, if enough exist.

        Tried in this order: district + type + size band, district + type,
        city + type + size band, city + type, whole city.
        """
        property_type = _comparable_rental_type(listing.property_type)
        candidates = self._candidates(listing, property_type)
        candidates.append((city_key(listing.city), None, None))
        return self._median_reference(self._rents, candidates, AreaMetric.RENT_M2)

    def own_price_m2(self, listing: Listing) -> AreaReference | None:
        """Median asking price per m² of own sale listings of the same type."""
        candidates = [
            key for key in self._candidates(listing, listing.property_type) if key[2] is None
        ]
        return self._median_reference(self._prices, candidates, AreaMetric.BUY_PRICE_M2)

    def reference(
        self,
        listing: Listing,
        metric: AreaMetric,
        source: ReferenceSource,
        property_type: PropertyType | None = None,
    ) -> AreaReference | None:
        """The most specific stored reference: district, then postal code, then city.

        Within an area, a reference for exactly this property type / size band beats a
        general one; references for a *different* type or band are never used.
        """
        property_type = property_type or listing.property_type
        band = size_band(_unit_area(listing))
        for area_key in area_keys_for(listing):
            best: tuple[tuple[int, int, date], AreaReference] | None = None
            for ref in self._references.get((metric, source, area_key), []):
                if ref.property_type not in (None, property_type):
                    continue
                if ref.segment not in (None, band):
                    continue
                rank = (ref.property_type is not None, ref.segment is not None, ref.valid_from)
                if best is None or rank > best[0]:
                    best = (rank, ref)
            if best:
                return best[1]
        return None

    def area_price_m2(self, listing: Listing) -> AreaReference | None:
        """Area average price per m² (SPEC §6.2): own sale listings, else references."""
        own = self.own_price_m2(listing)
        if own or listing.property_type is PropertyType.GRUNDSTUECK:
            return own  # plots are compared with the BORIS land value separately
        return self.reference(
            listing, AreaMetric.BUY_PRICE_M2, ReferenceSource.PRICE_MAP
        ) or self.reference(listing, AreaMetric.BUY_PRICE_M2, ReferenceSource.GUTACHTERAUSSCHUSS)

    def land_value_m2(self, listing: Listing) -> AreaReference | None:
        return self.reference(listing, AreaMetric.LAND_VALUE_M2, ReferenceSource.BORIS)

    def mietspiegel_rent_m2(self, listing: Listing) -> AreaReference | None:
        return self.reference(
            listing,
            AreaMetric.RENT_M2,
            ReferenceSource.MIETSPIEGEL,
            property_type=_comparable_rental_type(listing.property_type),
        )

    def price_map_rent_m2(self, listing: Listing) -> AreaReference | None:
        return self.reference(
            listing,
            AreaMetric.RENT_M2,
            ReferenceSource.PRICE_MAP,
            property_type=_comparable_rental_type(listing.property_type),
        )


# --- rent estimate ---------------------------------------------------------------------


def _component(reference: AreaReference, weight: float, note: str = "") -> RentComponent:
    return RentComponent(
        source=reference.source,
        rent_m2=reference.value,
        weight=weight,
        sample_size=reference.sample_size,
        area_key=reference.area_key,
        note=note or reference.note,
    )


def _confidence(rent_m2: float, evidence: list[AreaReference], min_samples: int) -> Confidence:
    """How much to trust an estimate (SPEC §5.2).

    - high:   at least two sources agree with the estimate AND it rests on many own
              listings (>= 2 × min_samples)
    - medium: one of the two conditions holds
    - low:    neither
    """
    agreeing = sum(
        1 for ref in evidence if abs(ref.value - rent_m2) / rent_m2 * 100 <= AGREEMENT_TOLERANCE_PCT
    )
    samples = max(
        (ref.sample_size or 0 for ref in evidence if ref.source is ReferenceSource.OWN_LISTINGS),
        default=0,
    )
    points = int(agreeing >= 2) + int(samples >= 2 * min_samples)
    return (Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH)[points]


def estimate_rent(
    listing: Listing,
    index: MarketIndex,
    assumptions: Assumptions,
    strategy: RentStrategy | None = None,
) -> RentEstimate | None:
    """Estimate the market rent: living area × rent per m² according to the strategy.

    Ignores actual rents and overrides (see `resolve_rent`). Returns None when the
    living area is unknown or the strategy has no data for this area.

    The result lists *every* source that was found. Sources the strategy did not use
    have weight 0, so the UI can still show them side by side.
    """
    area = listing.living_area_m2
    if not area or listing.property_type is PropertyType.GRUNDSTUECK:
        return None
    strategy = strategy or assumptions.rent_strategy

    own = index.own_rent_m2(listing)
    price_map = index.price_map_rent_m2(listing)
    mietspiegel = index.mietspiegel_rent_m2(listing)
    market = own or price_map  # "market" = own listings, falling back to the price map

    used: dict[ReferenceSource, float] = {}  # source -> weight
    if strategy is RentStrategy.MARKET and market:
        used[market.source] = 1.0
    elif strategy is RentStrategy.MIETSPIEGEL and mietspiegel:
        used[mietspiegel.source] = 1.0
    elif strategy is RentStrategy.BLEND:
        weights = assumptions.rent_blend_weights
        parts = [(market, weights.market), (mietspiegel, weights.mietspiegel)]
        available = [(ref, weight) for ref, weight in parts if ref is not None and weight > 0]
        total = sum(weight for _, weight in available)
        for ref, weight in available:
            used[ref.source] = weight / total  # renormalise if one side is missing
    if not used:
        return None

    evidence = [ref for ref in (own, price_map, mietspiegel) if ref is not None]
    rent_m2 = sum(ref.value * used.get(ref.source, 0.0) for ref in evidence)
    return RentEstimate(
        value_month=rent_m2 * area,
        rent_m2=rent_m2,
        origin=ValueOrigin.ESTIMATED,
        strategy=strategy,
        components=[_component(ref, used.get(ref.source, 0.0)) for ref in evidence],
        confidence=_confidence(rent_m2, evidence, index.min_samples),
    )


def resolve_rent(
    listing: Listing,
    estimate: RentEstimate | None,
    rent_override: float | None = None,
) -> RentEstimate | None:
    """Pick the rent used in calculations (SPEC §5.2 order of precedence).

    1. override by the user   2. actual rent from the listing   3. the estimate
    """
    area = listing.living_area_m2
    if rent_override is not None:
        return RentEstimate(
            value_month=rent_override,
            rent_m2=rent_override / area if area else None,
            origin=ValueOrigin.OVERRIDE,
            confidence=Confidence.HIGH,
        )
    if listing.actual_rent_month is not None and listing.is_rented is not False:
        return RentEstimate(
            value_month=listing.actual_rent_month,
            rent_m2=listing.actual_rent_month / area if area else None,
            origin=ValueOrigin.ACTUAL,
            confidence=Confidence.HIGH,
        )
    return estimate
