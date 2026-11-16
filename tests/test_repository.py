from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from immo.core.history import UpsertOutcome, summarize_history
from immo.core.models import (
    AreaMetric,
    AreaReference,
    OfferType,
    Override,
    OverrideField,
    PropertyType,
    ReferenceSource,
)
from tests.conftest import T0, make_listing

T1 = T0 + timedelta(days=7)
T2 = T0 + timedelta(days=14)


# --- create / read -----------------------------------------------------------------


def test_new_listing_is_stored_and_read_back(repo):
    listing = make_listing(raw={"original": "data"}, commission_pct=3.57)
    result = repo.upsert_listing(listing, seen_at=T0)

    assert result.outcome is UpsertOutcome.NEW
    stored = repo.get_listing(result.listing_id)
    assert stored == listing  # every field survives the round trip, incl. enums and JSON
    assert repo.get_listing_by_source("test", "A-1") == listing


def test_unknown_id_returns_none(repo):
    assert repo.get_listing("does-not-exist") is None
    assert repo.get_listing_by_source("test", "nope") is None


def test_new_listing_gets_an_initial_snapshot(repo):
    result = repo.upsert_listing(make_listing(), seen_at=T0)
    snapshots = repo.list_snapshots(result.listing_id)
    assert len(snapshots) == 1
    assert snapshots[0].price == 200_000
    assert snapshots[0].changes == {}


def test_list_listings_filters(repo):
    repo.upsert_listings(
        [
            make_listing(source_listing_id="1", city="Berlin"),
            make_listing(source_listing_id="2", city="Potsdam", property_type="HAUS"),
            make_listing(source_listing_id="3", city="Potsdam", offer_type="MIETE", price=800),
        ],
        seen_at=T0,
    )
    assert len(repo.list_listings()) == 3
    assert len(repo.list_listings(offer_type=OfferType.KAUF)) == 2
    assert len(repo.list_listings(city="Potsdam")) == 2
    assert len(repo.list_listings(property_type=PropertyType.HAUS)) == 1
    assert repo.count_listings() == 3


# --- upsert + snapshots ------------------------------------------------------------


def test_unchanged_listing_updates_last_seen_without_snapshot(repo):
    first = repo.upsert_listing(make_listing(), seen_at=T0)
    second = repo.upsert_listing(make_listing(), seen_at=T1)

    assert second.outcome is UpsertOutcome.UNCHANGED
    assert second.listing_id == first.listing_id  # same row, not a duplicate
    stored = repo.get_listing(first.listing_id)
    assert (stored.first_seen, stored.last_seen) == (T0, T1)
    assert len(repo.list_snapshots(first.listing_id)) == 1
    assert repo.count_listings() == 1


def test_price_change_creates_snapshot_and_keeps_identity(repo):
    first = repo.upsert_listing(make_listing(price=200_000), seen_at=T0)
    second = repo.upsert_listing(make_listing(price=185_000), seen_at=T1)

    assert second.outcome is UpsertOutcome.CHANGED
    assert second.changes == {"price": {"old": 200_000.0, "new": 185_000.0}}
    stored = repo.get_listing(first.listing_id)
    assert stored.price == 185_000
    assert stored.first_seen == T0

    snapshots = repo.list_snapshots(first.listing_id)
    assert [s.price for s in snapshots] == [200_000, 185_000]
    assert snapshots[1].seen_at == T1


def test_untracked_change_updates_the_listing_but_creates_no_snapshot(repo):
    first = repo.upsert_listing(make_listing(condition=None), seen_at=T0)
    second = repo.upsert_listing(make_listing(condition="renovated"), seen_at=T1)

    assert second.outcome is UpsertOutcome.UNCHANGED
    assert repo.get_listing(first.listing_id).condition == "renovated"
    assert len(repo.list_snapshots(first.listing_id)) == 1


def test_same_source_id_from_another_source_is_a_different_listing(repo):
    repo.upsert_listing(make_listing(source="a"), seen_at=T0)
    result = repo.upsert_listing(make_listing(source="b"), seen_at=T0)
    assert result.outcome is UpsertOutcome.NEW
    assert repo.count_listings() == 2


def test_duplicate_key_inside_one_batch_is_treated_as_update(repo):
    results = repo.upsert_listings(
        [make_listing(price=200_000), make_listing(price=190_000)], seen_at=T0
    )
    assert [r.outcome for r in results] == [UpsertOutcome.NEW, UpsertOutcome.CHANGED]
    assert repo.count_listings() == 1


def test_batch_is_one_transaction(repo):
    """If one listing in a batch fails, nothing from the batch is stored."""
    good = make_listing(source_listing_id="ok")
    bad = make_listing(source_listing_id="bad").model_copy(update={"title": None})
    with pytest.raises(IntegrityError):
        repo.upsert_listings([good, bad], seen_at=T0)
    assert repo.count_listings() == 0


# --- going offline / relisting -----------------------------------------------------


def test_deactivate_missing_marks_unseen_listings_inactive(repo):
    repo.upsert_listings(
        [make_listing(source_listing_id="stays"), make_listing(source_listing_id="goes")],
        seen_at=T0,
    )
    other = repo.upsert_listing(make_listing(source="other", source_listing_id="x"), seen_at=T0)

    gone = repo.deactivate_missing("test", seen_source_ids=["stays"], seen_at=T1)

    assert len(gone) == 1
    assert repo.get_listing(gone[0]).is_active is False
    assert repo.get_listing(gone[0]).last_seen == T0  # last time it was actually seen
    assert repo.get_listing_by_source("test", "stays").is_active is True
    assert repo.get_listing(other.listing_id).is_active is True  # other source untouched
    assert len(repo.list_listings(active_only=True)) == 2
    # a second run does not deactivate (or snapshot) again
    assert repo.deactivate_missing("test", seen_source_ids=["stays"], seen_at=T2) == []


def test_relisted_listing_is_reactivated_with_full_history(repo):
    first = repo.upsert_listing(make_listing(price=200_000), seen_at=T0)
    repo.deactivate_missing("test", seen_source_ids=[], seen_at=T1)
    back = repo.upsert_listing(make_listing(price=195_000), seen_at=T2)

    assert back.outcome is UpsertOutcome.RELISTED
    assert back.listing_id == first.listing_id
    listing = repo.get_listing(first.listing_id)
    assert listing.is_active is True

    snapshots = repo.list_snapshots(first.listing_id)
    assert len(snapshots) == 3
    summary = summarize_history(listing, snapshots, now=T2 + timedelta(days=1))
    assert summary.relisted is True
    assert summary.price_drop_count == 1
    assert summary.days_online == 15


def test_snapshots_by_listing_groups_everything(repo):
    a = repo.upsert_listing(make_listing(source_listing_id="a"), seen_at=T0)
    b = repo.upsert_listing(make_listing(source_listing_id="b"), seen_at=T0)
    repo.upsert_listing(make_listing(source_listing_id="a", price=150_000), seen_at=T1)

    grouped = repo.snapshots_by_listing()
    assert len(grouped[a.listing_id]) == 2
    assert len(grouped[b.listing_id]) == 1


# --- area references ---------------------------------------------------------------


def make_reference(**overrides) -> AreaReference:
    data = {
        "area_key": "Potsdam",
        "metric": AreaMetric.RENT_M2,
        "value": 9.5,
        "low": 8.0,
        "high": 11.0,
        "source": ReferenceSource.MIETSPIEGEL,
        "valid_from": date(2026, 1, 1),
        "note": "test value",
    }
    data.update(overrides)
    return AreaReference(**data)


def test_area_references_round_trip_and_filters(repo):
    references = [
        make_reference(),
        make_reference(source=ReferenceSource.PRICE_MAP, value=12.0, property_type="ETW"),
        make_reference(
            area_key="Berlin",
            metric=AreaMetric.LAND_VALUE_M2,
            value=900.0,
            source=ReferenceSource.BORIS,
        ),
    ]
    assert repo.add_area_references(references) == 3

    assert repo.list_area_references(source=ReferenceSource.MIETSPIEGEL) == [references[0]]
    assert len(repo.list_area_references(metric=AreaMetric.RENT_M2)) == 2
    assert len(repo.list_area_references(area_key="Berlin")) == 1

    assert repo.delete_area_references(source=ReferenceSource.BORIS) == 1
    assert repo.delete_area_references() == 2
    assert repo.list_area_references() == []


# --- overrides ---------------------------------------------------------------------


def test_override_set_replace_delete(repo):
    listing_id = repo.upsert_listing(make_listing(), seen_at=T0).listing_id

    repo.set_override(Override(listing_id=listing_id, field="rent_month", value=750, note="a"))
    repo.set_override(Override(listing_id=listing_id, field="rent_month", value=800, note="b"))
    repo.set_override(Override(listing_id=listing_id, field="price", value=180_000))

    overrides = repo.list_overrides(listing_id)
    assert {(o.field, o.value) for o in overrides} == {
        (OverrideField.PRICE, 180_000),
        (OverrideField.RENT_MONTH, 800),  # replaced, not duplicated
    }
    assert set(repo.overrides_by_listing()) == {listing_id}

    assert repo.delete_override(listing_id, OverrideField.PRICE) is True
    assert repo.delete_override(listing_id, OverrideField.PRICE) is False
    assert len(repo.list_overrides()) == 1


def test_override_for_unknown_listing_is_rejected(repo):
    with pytest.raises(IntegrityError):
        repo.set_override(Override(listing_id="ghost", field="price", value=1))


def test_reset_empties_the_database(repo):
    repo.upsert_listing(make_listing(), seen_at=T0)
    repo.add_area_references([make_reference()])
    repo.reset()
    assert repo.count_listings() == 0
    assert repo.list_area_references() == []


def test_file_database_persists_between_engines(tmp_path, monkeypatch):
    from immo.storage.db import make_engine
    from immo.storage.repository import Repository

    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "sub" / "immo.db"))
    Repository(make_engine()).upsert_listing(make_listing(), seen_at=T0)
    assert Repository(make_engine()).count_listings() == 1
