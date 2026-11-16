from collections import Counter
from datetime import date
from statistics import median

import pytest

from immo.core.models import AreaMetric, OfferType, PropertyType, ReferenceSource
from immo.core.sample_data import (
    CITIES,
    HISTORY_ROUNDS,
    SampleWorld,
    round_time,
)
from tests.conftest import T0

LAST = HISTORY_ROUNDS - 1


@pytest.fixture(scope="module")
def world() -> SampleWorld:
    return SampleWorld(seed=42)


@pytest.fixture(scope="module")
def ever_seen(world):
    """Every listing that was online in at least one history round, by source id."""
    seen = {}
    for round_index in range(HISTORY_ROUNDS):
        for listing in world.listings_at(round_index, T0):
            seen[listing.source_listing_id] = listing
    return list(seen.values())


def test_same_seed_gives_identical_data():
    a = SampleWorld(seed=7, n_kauf=30, n_miete=30)
    b = SampleWorld(seed=7, n_kauf=30, n_miete=30)
    for round_index in (0, LAST, a.total_rounds - 1):
        assert a.listings_at(round_index, T0) == b.listings_at(round_index, T0)
    assert a.area_references(date(2026, 1, 1)) == b.area_references(date(2026, 1, 1))


def test_different_seed_gives_different_data():
    a = SampleWorld(seed=1, n_kauf=30, n_miete=30).listings_at(0, T0)
    b = SampleWorld(seed=2, n_kauf=30, n_miete=30).listings_at(0, T0)
    assert [x.price for x in a] != [x.price for x in b]


def test_volume_matches_the_spec(ever_seen):
    counts = Counter(listing.offer_type for listing in ever_seen)
    assert counts[OfferType.KAUF] == 300
    assert counts[OfferType.MIETE] == 400


def test_all_cities_and_types_are_covered(ever_seen):
    kauf = [x for x in ever_seen if x.offer_type is OfferType.KAUF]
    assert {x.city for x in kauf} == {city.name for city in CITIES}
    assert {x.property_type for x in kauf} == set(PropertyType)
    for city in CITIES:
        types_in_city = {x.property_type for x in kauf if x.city == city.name}
        assert types_in_city == set(PropertyType), city.name
    rentals = [x for x in ever_seen if x.offer_type is OfferType.MIETE]
    assert {x.property_type for x in rentals} == {PropertyType.ETW, PropertyType.HAUS}


def test_type_specific_fields(ever_seen):
    for listing in ever_seen:
        if listing.property_type is PropertyType.GRUNDSTUECK:
            assert listing.living_area_m2 is None
            assert listing.plot_area_m2 is not None
            assert listing.actual_rent_month is None
        if listing.property_type is PropertyType.MFH:
            assert 3 <= listing.units <= 12
        if listing.offer_type is OfferType.MIETE:
            assert listing.actual_rent_month is None
            assert listing.commission_pct is None


@pytest.mark.parametrize("city", CITIES, ids=lambda c: c.name)
def test_median_levels_are_in_a_realistic_range(ever_seen, city):
    """Medians (robust against the built-in outliers) land near the SPEC §7 ranges."""
    rents = [
        x.price / x.living_area_m2
        for x in ever_seen
        if x.offer_type is OfferType.MIETE and x.city == city.name and x.living_area_m2
    ]
    flats = [
        x.price / x.living_area_m2
        for x in ever_seen
        if x.offer_type is OfferType.KAUF
        and x.property_type is PropertyType.ETW
        and x.city == city.name
        and x.living_area_m2
    ]
    assert city.rent_m2[0] * 0.9 <= median(rents) <= city.rent_m2[1] * 1.1
    assert city.flat_price_m2[0] * 0.9 <= median(flats) <= city.flat_price_m2[1] * 1.1


def test_data_is_realistically_messy(ever_seen):
    kauf = [x for x in ever_seen if x.offer_type is OfferType.KAUF]
    with_area_type = [x for x in ever_seen if x.property_type is not PropertyType.GRUNDSTUECK]
    assert any(x.living_area_m2 is None for x in with_area_type)
    assert any(x.rooms is None for x in ever_seen)
    assert any(x.district is None for x in ever_seen)
    assert any(x.year_built is None for x in ever_seen)
    assert any(x.commission_pct is None for x in kauf)
    assert any(x.commission_pct is not None for x in kauf)
    assert 0 < sum("sample_note" in x.raw for x in ever_seen) < 40  # a few outliers
    rented = [x for x in kauf if x.actual_rent_month]
    assert 20 < len(rented) < 150
    assert all(x.is_rented for x in rented)


def test_history_contains_drops_offline_and_relisted(world):
    prices: dict[str, list[float]] = {}
    online: dict[str, list[bool]] = {}
    for round_index in range(HISTORY_ROUNDS):
        present = {x.source_listing_id: x for x in world.listings_at(round_index, T0)}
        for sid in set(prices) | set(present):
            prices.setdefault(sid, [])
            online.setdefault(sid, [])
            online[sid].append(sid in present)
            if sid in present:
                prices[sid].append(present[sid].price)

    def drops(series):
        return sum(1 for a, b in zip(series, series[1:], strict=False) if b < a)

    drop_counts = Counter(drops(series) for sid, series in prices.items() if sid.startswith("S-K"))
    assert drop_counts[1] > 0 and drop_counts[2] > 0 and drop_counts[3] > 0
    assert max(drop_counts) <= 3

    gone = [sid for sid, flags in online.items() if not flags[-1]]
    relisted = [
        sid
        for sid, flags in online.items()
        if any(not now and later for now, later in zip(flags, flags[1:], strict=False))
    ]
    assert len(gone) >= 20
    assert len(relisted) >= 5


def test_listing_identity_is_stable_across_rounds(world):
    first = {x.source_listing_id: x.id for x in world.listings_at(0, T0)}
    last = {x.source_listing_id: x.id for x in world.listings_at(LAST, T0)}
    shared = set(first) & set(last)
    assert shared
    assert all(first[sid] == last[sid] for sid in shared)


def test_future_rounds_bring_new_listings_and_then_freeze(world):
    now_ids = {x.source_listing_id for x in world.listings_at(LAST, T0)}
    next_ids = {x.source_listing_id for x in world.listings_at(LAST + 1, T0)}
    assert next_ids - now_ids  # something new appears in the next fetch
    final = world.listings_at(world.total_rounds - 1, T0)
    assert world.listings_at(world.total_rounds + 50, T0) == final


def test_round_time_is_weekly_and_ends_now():
    assert round_time(LAST, T0) == T0
    assert (T0 - round_time(0, T0)).days == 7 * LAST


def test_area_references_cover_all_cities_metrics_and_sources(world):
    references = world.area_references(date(2026, 1, 1))
    for city in CITIES:
        city_refs = [r for r in references if r.area_key == city.name]
        assert {r.metric for r in city_refs} == set(AreaMetric)
        assert {r.source for r in city_refs} == {
            ReferenceSource.MIETSPIEGEL,
            ReferenceSource.PRICE_MAP,
            ReferenceSource.GUTACHTERAUSSCHUSS,
            ReferenceSource.BORIS,
        }
        # the Mietspiegel reflects existing rents and lies below the price map
        rent = {r.source: r.value for r in city_refs if r.metric is AreaMetric.RENT_M2}
        assert rent[ReferenceSource.MIETSPIEGEL] < rent[ReferenceSource.PRICE_MAP]
        # every district has its own values too
        for district in city.districts:
            assert any(r.area_key == f"{city.name}/{district.name}" for r in references)
    assert all(r.low < r.value < r.high for r in references)
    assert all("SAMPLE" in r.note for r in references)
