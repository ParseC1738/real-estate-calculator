from immo.core.models import Override, ValueOrigin
from immo.core.overrides import apply_overrides
from tests.conftest import make_listing


def test_no_overrides_returns_the_listing_unchanged():
    listing = make_listing()
    effective = apply_overrides(listing, [])
    assert effective.listing is listing
    assert effective.price_origin is ValueOrigin.ACTUAL
    assert effective.area_origin is ValueOrigin.ACTUAL
    assert effective.rent_override is None


def test_overrides_replace_values_and_mark_the_origin():
    listing = make_listing(price=200_000, living_area_m2=60)
    overrides = [
        Override(listing_id=listing.id, field="price", value=180_000),
        Override(listing_id=listing.id, field="living_area_m2", value=64),
        Override(listing_id=listing.id, field="rent_month", value=850),
    ]
    effective = apply_overrides(listing, overrides)

    assert effective.listing.price == 180_000
    assert effective.listing.living_area_m2 == 64
    assert effective.price_origin is ValueOrigin.OVERRIDE
    assert effective.area_origin is ValueOrigin.OVERRIDE
    assert effective.rent_override == 850
    # the original object is untouched
    assert listing.price == 200_000


def test_overrides_of_other_listings_are_ignored():
    listing = make_listing()
    effective = apply_overrides(listing, [Override(listing_id="other", field="price", value=1)])
    assert effective.listing.price == 200_000
    assert effective.price_origin is ValueOrigin.ACTUAL
