import pytest
from pydantic import ValidationError

from immo.core.models import (
    OverrideField,
    PropertyType,
    area_keys_for,
    listing_fingerprint,
)
from tests.conftest import make_listing


def test_listing_gets_an_id_and_defaults():
    listing = make_listing()
    assert len(listing.id) == 36  # UUID
    assert listing.is_active is True
    assert listing.commission_pct is None  # None means "unknown -> use default"
    assert listing.raw == {}


def test_two_listings_get_different_ids():
    assert make_listing().id != make_listing().id


def test_enums_accept_plain_strings():
    listing = make_listing(property_type="MFH", offer_type="KAUF")
    assert listing.property_type is PropertyType.MFH


@pytest.mark.parametrize(
    "field, value",
    [("price", 0), ("price", -5), ("living_area_m2", 0), ("units", 0), ("commission_pct", 120)],
)
def test_invalid_numbers_are_rejected(field, value):
    with pytest.raises(ValidationError):
        make_listing(**{field: value})


def test_unknown_property_type_is_rejected():
    with pytest.raises(ValidationError):
        make_listing(property_type="SCHLOSS")


def test_blank_strings_become_none_and_text_is_stripped():
    listing = make_listing(district="  ", address="", city="  Potsdam ")
    assert listing.district is None
    assert listing.address is None
    assert listing.city == "Potsdam"


def test_area_keys_most_specific_first():
    listing = make_listing(city="Berlin", district="Mitte", postal_code="10115")
    assert area_keys_for(listing) == ["Berlin/Mitte", "plz:10115", "Berlin"]
    assert area_keys_for(make_listing(district=None))[0] == "plz:14482"


def test_fingerprint_ignores_source_and_small_price_differences():
    a = make_listing(source="portal_a", source_listing_id="1", price=200_000)
    b = make_listing(source="portal_b", source_listing_id="99", price=200_300)
    assert listing_fingerprint(a) == listing_fingerprint(b)


def test_fingerprint_changes_with_area():
    assert listing_fingerprint(make_listing()) != listing_fingerprint(
        make_listing(living_area_m2=75)
    )


def test_override_fields_are_limited():
    assert {f.value for f in OverrideField} == {"rent_month", "price", "living_area_m2"}
