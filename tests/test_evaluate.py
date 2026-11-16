from datetime import date, timedelta

import pytest

from immo.core.assumptions import Assumptions
from immo.core.estimates import MarketIndex
from immo.core.evaluate import evaluate_buy, evaluate_rental
from immo.core.models import (
    AreaMetric,
    AreaReference,
    ListingSnapshot,
    OfferType,
    Override,
    PropertyType,
    ReferenceSource,
    ValueOrigin,
)
from tests.conftest import T0, make_listing

A = Assumptions()
TODAY = date(2026, 6, 1)


def market() -> MarketIndex:
    """Potsdam: 10 rentals at 12 EUR/m², Mietspiegel 10, 5 flats for sale at 4,000 EUR/m²."""
    rentals = [
        make_listing(source_listing_id=f"R-{i}", offer_type="MIETE", price=720, living_area_m2=60)
        for i in range(10)
    ]
    sales = [make_listing(source_listing_id=f"K-{i}", price=240_000) for i in range(5)]
    references = [
        AreaReference(area_key="Potsdam", metric=AreaMetric.RENT_M2, value=10.0,
                      source=ReferenceSource.MIETSPIEGEL, valid_from=date(2026, 1, 1)),
        AreaReference(area_key="Potsdam", metric=AreaMetric.LAND_VALUE_M2, value=500.0,
                      source=ReferenceSource.BORIS, valid_from=date(2026, 1, 1)),
    ]  # fmt: skip
    return MarketIndex(rentals + sales, references, on_date=TODAY)


def test_vacant_flat_uses_the_estimated_rent():
    evaluation = evaluate_buy(make_listing(), market(), A)
    # blend: 0.6 × 12 + 0.4 × 10 = 11.2 EUR/m² × 60 m² = 672 EUR
    assert evaluation.rent.value_month == pytest.approx(672)
    assert evaluation.metrics.rent_origin is ValueOrigin.ESTIMATED
    assert evaluation.metrics.gross_yield_pct == pytest.approx(4.032)  # 8,064 / 200,000
    assert evaluation.metrics.area_avg_price_per_m2 == 4000
    assert evaluation.metrics.price_vs_area_pct == pytest.approx(-16.67, abs=0.01)
    assert evaluation.area_price.source is ReferenceSource.OWN_LISTINGS
    assert evaluation.history is None


def test_rented_flat_uses_the_actual_rent_but_keeps_the_market_estimate():
    listing = make_listing(actual_rent_month=600, is_rented=True)
    evaluation = evaluate_buy(listing, market(), A)
    assert evaluation.rent.origin is ValueOrigin.ACTUAL
    assert evaluation.metrics.rent_month == 600
    assert evaluation.market_rent.value_month == pytest.approx(672)


def test_overrides_flow_through_to_the_metrics():
    listing = make_listing(actual_rent_month=600, is_rented=True)
    overrides = [
        Override(listing_id=listing.id, field="rent_month", value=900),
        Override(listing_id=listing.id, field="price", value=180_000),
    ]
    evaluation = evaluate_buy(listing, market(), A, overrides)

    assert evaluation.listing.price == 200_000  # stored listing untouched
    assert evaluation.effective.price == 180_000
    assert evaluation.metrics.price_origin is ValueOrigin.OVERRIDE
    assert evaluation.metrics.rent_origin is ValueOrigin.OVERRIDE
    assert evaluation.metrics.gross_yield_pct == pytest.approx(6.0)  # 10,800 / 180,000


def test_area_override_changes_the_rent_estimate():
    listing = make_listing()
    overrides = [Override(listing_id=listing.id, field="living_area_m2", value=80)]
    evaluation = evaluate_buy(listing, market(), A, overrides)
    assert evaluation.rent.value_month == pytest.approx(896)  # 11.2 × 80
    assert evaluation.metrics.area_origin is ValueOrigin.OVERRIDE


def test_mfh_gets_rent_upside_from_the_market_estimate():
    mfh = make_listing(
        property_type="MFH", price=900_000, living_area_m2=420, units=6,
        actual_rent_month=4_200, is_rented=True,
    )  # fmt: skip
    evaluation = evaluate_buy(mfh, market(), A)
    # market estimate: 11.2 × 420 = 4,704 -> upside (4,704 − 4,200) / 4,200 = 12 %
    assert evaluation.metrics.rent_upside_pct == pytest.approx(12.0)
    assert evaluation.metrics.rent_per_unit == pytest.approx(700)


def test_plot_gets_land_value_but_no_rent():
    plot = make_listing(
        property_type="GRUNDSTUECK", price=300_000, living_area_m2=None, plot_area_m2=500
    )
    evaluation = evaluate_buy(plot, market(), A)
    assert evaluation.rent is None
    assert evaluation.market_rent is None
    assert evaluation.metrics.gross_yield_pct is None
    assert evaluation.metrics.price_vs_land_value_pct == pytest.approx(20.0)  # 600 vs 500


def test_flat_without_any_rent_data_still_gets_basic_metrics():
    evaluation = evaluate_buy(make_listing(), MarketIndex([], [], on_date=TODAY), A)
    assert evaluation.rent is None
    assert evaluation.metrics.gross_yield_pct is None
    assert evaluation.metrics.total_investment == pytest.approx(224_140)


def test_history_is_attached_when_snapshots_are_given():
    listing = make_listing(price=190_000)
    snapshots = [
        ListingSnapshot(listing_id=listing.id, seen_at=T0, price=200_000),
        ListingSnapshot(
            listing_id=listing.id,
            seen_at=T0 + timedelta(days=7),
            price=190_000,
            changes={"price": {"old": 200_000, "new": 190_000}},
        ),
    ]
    evaluation = evaluate_buy(
        listing, market(), A, snapshots=snapshots, now=T0 + timedelta(days=10)
    )
    assert evaluation.history.price_drop_count == 1
    assert evaluation.history.days_online == 10


def test_rental_listing_is_compared_with_mietspiegel_and_area():
    rental = make_listing(offer_type="MIETE", price=780, living_area_m2=60)
    evaluation = evaluate_rental(rental, market())
    assert evaluation.metrics.rent_per_m2 == pytest.approx(13.0)
    assert evaluation.metrics.rent_vs_mietspiegel_pct == pytest.approx(30.0)
    assert evaluation.metrics.rent_vs_area_pct == pytest.approx(8.33, abs=0.01)  # 13 vs 12


# --- the whole sample database -----------------------------------------------------


@pytest.fixture(scope="module")
def sample(seeded_repo):
    repo = seeded_repo
    listings = repo.list_listings()
    index = MarketIndex(listings, repo.list_area_references(), on_date=T0.date())
    return listings, index


def test_every_sample_listing_can_be_evaluated(sample):
    listings, index = sample
    for listing in listings:
        if listing.offer_type is OfferType.KAUF:
            evaluate_buy(listing, index, A)
        else:
            evaluate_rental(listing, index)


def test_sample_listings_get_plausible_results(sample):
    listings, index = sample
    kauf = [x for x in listings if x.offer_type is OfferType.KAUF]
    evaluations = [evaluate_buy(x, index, A) for x in kauf]
    with_yield = [e for e in evaluations if e.metrics.gross_yield_pct is not None]
    plots = [e for e in evaluations if e.listing.property_type is PropertyType.GRUNDSTUECK]

    # nearly every flat/house/MFH gets a rent (only those without living area do not)
    assert len(with_yield) >= 0.9 * (len(kauf) - len(plots))
    assert all(e.metrics.gross_yield_pct is None for e in plots)
    assert all(e.metrics.price_vs_land_value_pct is not None for e in plots)

    origins = {e.metrics.rent_origin for e in with_yield}
    assert origins == {ValueOrigin.ACTUAL, ValueOrigin.ESTIMATED}
    yields = sorted(e.metrics.gross_yield_pct for e in with_yield)
    assert 2.5 < yields[len(yields) // 2] < 7  # median gross yield
    assert {e.metrics.indicator.value for e in with_yield} == {"green", "yellow", "red"}
