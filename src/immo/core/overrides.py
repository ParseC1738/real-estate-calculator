"""Applying user overrides to a listing (SPEC §4.5): overrides always win."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from immo.core.models import Listing, Override, OverrideField, ValueOrigin


class EffectiveListing(BaseModel):
    """A listing after overrides, plus the information where each value came from."""

    listing: Listing
    price_origin: ValueOrigin = ValueOrigin.ACTUAL
    area_origin: ValueOrigin = ValueOrigin.ACTUAL
    rent_override: float | None = None  # handled by the rent resolution (estimates.py)


def apply_overrides(listing: Listing, overrides: Iterable[Override]) -> EffectiveListing:
    """Return a copy of the listing with overridden price / living area.

    Pure function: the stored listing is never modified, so removing an override
    brings the original value straight back.
    """
    by_field = {o.field: o.value for o in overrides if o.listing_id == listing.id}
    update: dict[str, float] = {}
    price_origin = area_origin = ValueOrigin.ACTUAL
    if OverrideField.PRICE in by_field:
        update["price"] = by_field[OverrideField.PRICE]
        price_origin = ValueOrigin.OVERRIDE
    if OverrideField.LIVING_AREA_M2 in by_field:
        update["living_area_m2"] = by_field[OverrideField.LIVING_AREA_M2]
        area_origin = ValueOrigin.OVERRIDE
    return EffectiveListing(
        listing=listing.model_copy(update=update) if update else listing,
        price_origin=price_origin,
        area_origin=area_origin,
        rent_override=by_field.get(OverrideField.RENT_MONTH),
    )
