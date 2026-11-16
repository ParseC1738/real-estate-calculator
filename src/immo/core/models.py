"""Pydantic models and enums of the domain (SPEC §4).

These classes are the common language of the whole app: adapters produce them, the
repository stores them, the metrics consume them. They know nothing about the database
or the UI.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyType(StrEnum):
    ETW = "ETW"  # Eigentumswohnung (flat)
    HAUS = "HAUS"  # house
    MFH = "MFH"  # Mehrfamilienhaus (apartment building)
    GRUNDSTUECK = "GRUNDSTUECK"  # plot of land


class OfferType(StrEnum):
    KAUF = "KAUF"  # for sale
    MIETE = "MIETE"  # for rent


class ValueOrigin(StrEnum):
    """Where a number comes from. Shown next to every value in the UI."""

    ACTUAL = "ACTUAL"  # taken from the listing
    ESTIMATED = "ESTIMATED"  # calculated from references / other listings
    OVERRIDE = "OVERRIDE"  # set by the user


class AreaMetric(StrEnum):
    RENT_M2 = "rent_m2"
    BUY_PRICE_M2 = "buy_price_m2"
    LAND_VALUE_M2 = "land_value_m2"


class ReferenceSource(StrEnum):
    MIETSPIEGEL = "mietspiegel"
    GUTACHTERAUSSCHUSS = "gutachterausschuss"
    BORIS = "boris"
    PRICE_MAP = "price_map"
    OWN_LISTINGS = "own_listings"


class OverrideField(StrEnum):
    RENT_MONTH = "rent_month"
    PRICE = "price"
    LIVING_AREA_M2 = "living_area_m2"


def utcnow() -> datetime:
    """Current time as naive UTC.

    SQLite has no time-zone support and returns naive datetimes, so the whole app uses
    naive UTC consistently instead of mixing aware and naive values.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _new_id() -> str:
    return str(uuid4())


class Listing(BaseModel):
    """The current state of one listing (SPEC §4.2)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(default_factory=_new_id)
    source: str
    source_listing_id: str
    url: str | None = None
    offer_type: OfferType
    property_type: PropertyType
    title: str
    city: str
    district: str | None = None
    postal_code: str
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    price: float = Field(gt=0, description="purchase price (KAUF) or cold rent/month (MIETE)")
    living_area_m2: float | None = Field(default=None, gt=0)
    plot_area_m2: float | None = Field(default=None, gt=0)
    rooms: float | None = Field(default=None, gt=0)
    units: int | None = Field(default=None, gt=0)
    year_built: int | None = Field(default=None, ge=1000, le=2100)
    condition: str | None = None
    energy_class: str | None = None
    actual_rent_month: float | None = Field(default=None, gt=0)
    hausgeld_month: float | None = Field(default=None, ge=0)
    commission_pct: float | None = Field(default=None, ge=0, le=100)
    is_rented: bool | None = None
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    is_active: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url", "district", "address", "condition", "energy_class", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Sources often deliver '' for missing text; treat that as 'unknown'."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ListingSnapshot(BaseModel):
    """One entry in a listing's history (SPEC §4.3).

    `changes` maps a field name to `{"old": ..., "new": ...}`. The first snapshot of a
    listing has no changes; it records the starting price.
    """

    listing_id: str
    seen_at: datetime
    price: float
    changes: dict[str, Any] = Field(default_factory=dict)


class AreaReference(BaseModel):
    """One statistical value for an area from one source (SPEC §4.4)."""

    area_key: str
    metric: AreaMetric
    property_type: PropertyType | None = None
    segment: str | None = None
    value: float
    low: float | None = None
    high: float | None = None
    source: ReferenceSource
    valid_from: date
    valid_to: date | None = None
    note: str = ""
    sample_size: int | None = None  # only for values derived from own listings


class Override(BaseModel):
    """A value set by the user; always wins over actual and estimated values (SPEC §4.5)."""

    listing_id: str
    field: OverrideField
    value: float = Field(gt=0)
    created_at: datetime = Field(default_factory=utcnow)
    note: str = ""


# --- area keys -------------------------------------------------------------------------
# `AreaReference.area_key` can address three levels. One string format per level keeps
# the lookup trivial:   "Berlin"   |   "Berlin/Mitte"   |   "plz:10115"


def city_key(city: str) -> str:
    return city.strip()


def district_key(city: str, district: str) -> str:
    return f"{city.strip()}/{district.strip()}"


def postal_key(postal_code: str) -> str:
    return f"plz:{postal_code.strip()}"


def area_keys_for(listing: Listing) -> list[str]:
    """Candidate area keys for a listing, most specific first."""
    keys = []
    if listing.district:
        keys.append(district_key(listing.city, listing.district))
    if listing.postal_code:
        keys.append(postal_key(listing.postal_code))
    keys.append(city_key(listing.city))
    return keys


def listing_fingerprint(listing: Listing) -> str:
    """Stable hash to recognise the same property on several portals (SPEC §9).

    Built from address/postal code + area + rooms + price rounded to 1,000 EUR.
    Deduplication itself comes later; the field is only prepared and stored.
    """
    area = listing.living_area_m2 or listing.plot_area_m2
    parts = [
        (listing.address or "").lower(),
        listing.postal_code,
        listing.offer_type.value,
        listing.property_type.value,
        "" if area is None else str(round(area)),
        "" if listing.rooms is None else str(listing.rooms),
        str(round(listing.price, -3)),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
