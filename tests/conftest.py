"""Shared pytest fixtures and small factories."""

from datetime import datetime

import pytest

from immo.core.models import Listing, OfferType, PropertyType

T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_listing(**overrides) -> Listing:
    """A valid KAUF flat; pass keyword arguments to change single fields."""
    data = {
        "source": "test",
        "source_listing_id": "A-1",
        "offer_type": OfferType.KAUF,
        "property_type": PropertyType.ETW,
        "title": "2-Zimmer-Wohnung",
        "city": "Potsdam",
        "district": "Babelsberg",
        "postal_code": "14482",
        "price": 200_000.0,
        "living_area_m2": 60.0,
        "rooms": 2.0,
        "first_seen": T0,
        "last_seen": T0,
    }
    data.update(overrides)
    return Listing(**data)


@pytest.fixture
def listing() -> Listing:
    return make_listing()
