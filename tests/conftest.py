"""Shared pytest fixtures and small factories."""

from datetime import datetime

import pytest

from immo.core.models import Listing, OfferType, PropertyType
from immo.storage.db import IN_MEMORY_URL, make_engine
from immo.storage.repository import Repository

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


@pytest.fixture
def repo() -> Repository:
    """A repository on a fresh in-memory SQLite database (gone after the test)."""
    return Repository(make_engine(IN_MEMORY_URL))


@pytest.fixture(scope="session")
def seeded_repo() -> Repository:
    """One sample database for all read-only tests (seeding takes about a second).

    Tests that write must use the function-scoped `repo` fixture instead.
    """
    from immo.pipeline.seed import seed_database

    repository = Repository(make_engine(IN_MEMORY_URL))
    seed_database(repository, now=T0)
    return repository


@pytest.fixture(scope="module")
def sample_db(tmp_path_factory):
    """A seeded SQLite FILE for the Streamlit page tests (one per test module).

    The app finds it through the IMMO_DB_PATH environment variable. Tests that write
    (overrides, imports) must undo their changes, because the module shares the file.
    """
    from immo.pipeline.seed import seed_database

    path = tmp_path_factory.mktemp("ui") / "immo.db"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("IMMO_DB_PATH", str(path))
        repository = Repository(make_engine())
        seed_database(repository, now=T0)
        yield repository
