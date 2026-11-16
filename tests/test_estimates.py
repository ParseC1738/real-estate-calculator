"""Rent estimate tests (SPEC §5.2), all with small hand-made markets."""

from datetime import date

import pytest

from immo.core.assumptions import Assumptions, RentStrategy
from immo.core.estimates import (
    Confidence,
    MarketIndex,
    estimate_rent,
    resolve_rent,
    size_band,
)
from immo.core.models import (
    AreaMetric,
    AreaReference,
    PropertyType,
    ReferenceSource,
    ValueOrigin,
)
from tests.conftest import make_listing

TODAY = date(2026, 6, 1)
A = Assumptions()  # blend 0.6 market / 0.4 mietspiegel, min 5 samples


def rental(i: int, rent_m2: float, area: float = 60.0, **overrides):
    """A MIETE flat in Potsdam/Babelsberg with the given rent per m²."""
    data = {
        "source_listing_id": f"R-{i}",
        "offer_type": "MIETE",
        "price": rent_m2 * area,
        "living_area_m2": area,
    }
    data.update(overrides)
    return make_listing(**data)


def rentals(count: int, rent_m2: float = 12.0, **overrides):
    return [rental(i, rent_m2, **overrides) for i in range(count)]


def ref(source, value, area_key="Potsdam", metric=AreaMetric.RENT_M2, **overrides):
    data = {
        "area_key": area_key,
        "metric": metric,
        "value": value,
        "source": source,
        "valid_from": date(2026, 1, 1),
    }
    data.update(overrides)
    return AreaReference(**data)


MIETSPIEGEL_10 = ref(ReferenceSource.MIETSPIEGEL, 10.0)
PRICE_MAP_13 = ref(ReferenceSource.PRICE_MAP, 13.0)


def index(listings=(), references=(), min_samples=5):
    return MarketIndex(listings, references, min_samples=min_samples, on_date=TODAY)


def weights(estimate):
    return {c.source: c.weight for c in estimate.components}


# --- size bands --------------------------------------------------------------------


@pytest.mark.parametrize(
    "area, band",
    [(25, "<40"), (40, "40-60"), (59.9, "40-60"), (60, "60-90"), (100, "90-130"), (250, ">130")],
)
def test_size_band(area, band):
    assert size_band(area) == band


def test_size_band_unknown_area():
    assert size_band(None) is None


# --- strategy: market --------------------------------------------------------------


def test_market_uses_median_of_own_listings():
    listings = [rental(i, rent) for i, rent in enumerate([10, 11, 12, 13, 14])]
    estimate = estimate_rent(make_listing(), index(listings), A, RentStrategy.MARKET)

    assert estimate.rent_m2 == 12.0  # median
    assert estimate.value_month == 720.0  # 12 EUR × 60 m²
    assert estimate.origin is ValueOrigin.ESTIMATED
    assert estimate.strategy is RentStrategy.MARKET
    (component,) = estimate.components
    assert component.source is ReferenceSource.OWN_LISTINGS
    assert component.sample_size == 5
    assert component.weight == 1.0


def test_median_is_robust_against_outliers():
    listings = [rental(i, rent) for i, rent in enumerate([11, 12, 12, 13, 150])]
    estimate = estimate_rent(make_listing(), index(listings), A, RentStrategy.MARKET)
    assert estimate.rent_m2 == 12.0


def test_too_few_samples_falls_back_to_the_price_map():
    """SPEC: own listings are only used with at least N comparable listings."""
    four = rentals(4, rent_m2=12.0)
    estimate = estimate_rent(make_listing(), index(four, [PRICE_MAP_13]), A, RentStrategy.MARKET)

    assert estimate.rent_m2 == 13.0
    assert weights(estimate) == {ReferenceSource.PRICE_MAP: 1.0}
    assert estimate.confidence is Confidence.LOW


def test_too_few_samples_and_no_price_map_gives_no_estimate():
    estimate = estimate_rent(make_listing(), index(rentals(4)), A, RentStrategy.MARKET)
    assert estimate is None


def test_min_samples_is_configurable():
    four = rentals(4, rent_m2=12.0)
    estimate = estimate_rent(make_listing(), index(four, min_samples=4), A, RentStrategy.MARKET)
    assert estimate.rent_m2 == 12.0


def test_own_listings_win_over_price_map_but_both_are_shown():
    estimate = estimate_rent(
        make_listing(), index(rentals(5), [PRICE_MAP_13]), A, RentStrategy.MARKET
    )
    assert estimate.rent_m2 == 12.0
    assert weights(estimate) == {ReferenceSource.OWN_LISTINGS: 1.0, ReferenceSource.PRICE_MAP: 0.0}


def test_district_level_is_preferred_when_it_has_enough_samples():
    babelsberg = rentals(5, rent_m2=14.0)
    elsewhere = [rental(100 + i, 10.0, district="Drewitz", postal_code="14480") for i in range(20)]
    estimate = estimate_rent(make_listing(), index(babelsberg + elsewhere), A, RentStrategy.MARKET)
    assert estimate.rent_m2 == 14.0
    assert estimate.components[0].area_key == "Potsdam/Babelsberg"


def test_falls_back_to_city_level_when_the_district_is_thin():
    babelsberg = rentals(2, rent_m2=14.0)
    elsewhere = [rental(100 + i, 10.0, district="Drewitz", postal_code="14480") for i in range(20)]
    estimate = estimate_rent(make_listing(), index(babelsberg + elsewhere), A, RentStrategy.MARKET)
    assert estimate.rent_m2 == 10.0  # median of all 22 Potsdam flats
    assert estimate.components[0].area_key == "Potsdam"
    assert estimate.components[0].sample_size == 22


def test_size_band_is_preferred_when_it_has_enough_samples():
    small = [rental(i, 16.0, area=30.0) for i in range(5)]
    medium = [rental(50 + i, 12.0, area=70.0) for i in range(5)]
    estimate = estimate_rent(
        make_listing(living_area_m2=32), index(small + medium), A, RentStrategy.MARKET
    )
    assert estimate.rent_m2 == 16.0
    assert estimate.value_month == 512.0  # 16 × 32


def test_other_cities_are_never_used():
    berlin = [rental(i, 18.0, city="Berlin", district="Mitte") for i in range(10)]
    assert estimate_rent(make_listing(), index(berlin), A, RentStrategy.MARKET) is None


def test_sale_listings_do_not_count_as_rent_samples():
    sales = [make_listing(source_listing_id=f"K-{i}") for i in range(10)]
    assert estimate_rent(make_listing(), index(sales), A, RentStrategy.MARKET) is None


def test_apartment_building_is_compared_with_flats_of_its_average_unit_size():
    small = [rental(i, 16.0, area=30.0) for i in range(5)]
    medium = [rental(50 + i, 12.0, area=70.0) for i in range(5)]
    mfh = make_listing(property_type="MFH", living_area_m2=420, units=6, price=900_000)
    estimate = estimate_rent(mfh, index(small + medium), A, RentStrategy.MARKET)
    assert estimate.rent_m2 == 12.0  # 420 / 6 = 70 m² per flat -> band 60-90
    assert estimate.value_month == 5040.0


def test_house_prefers_house_rentals_and_falls_back_to_all():
    flats = rentals(6, rent_m2=12.0)
    houses = [rental(50 + i, 15.0, area=120.0, property_type="HAUS") for i in range(5)]
    house = make_listing(property_type="HAUS", living_area_m2=120, price=500_000)

    with_houses = estimate_rent(house, index(flats + houses), A, RentStrategy.MARKET)
    assert with_houses.rent_m2 == 15.0
    only_flats = estimate_rent(house, index(flats), A, RentStrategy.MARKET)
    assert only_flats.rent_m2 == 12.0  # whole-city fallback
    assert only_flats.components[0].sample_size == 6


# --- strategy: mietspiegel ---------------------------------------------------------


def test_mietspiegel_strategy_uses_the_official_table():
    estimate = estimate_rent(
        make_listing(), index(rentals(10), [MIETSPIEGEL_10]), A, RentStrategy.MIETSPIEGEL
    )
    assert estimate.rent_m2 == 10.0
    assert estimate.value_month == 600.0
    assert weights(estimate) == {
        ReferenceSource.OWN_LISTINGS: 0.0,
        ReferenceSource.MIETSPIEGEL: 1.0,
    }


def test_mietspiegel_strategy_without_table_gives_no_estimate():
    assert estimate_rent(make_listing(), index(rentals(10)), A, RentStrategy.MIETSPIEGEL) is None


# --- strategy: blend ---------------------------------------------------------------


def test_blend_is_the_default_and_weights_both_sources():
    estimate = estimate_rent(make_listing(), index(rentals(5), [MIETSPIEGEL_10]), A)

    assert estimate.strategy is RentStrategy.BLEND
    assert estimate.rent_m2 == pytest.approx(11.2)  # 0.6 × 12 + 0.4 × 10
    assert estimate.value_month == pytest.approx(672.0)  # 11.2 × 60
    assert weights(estimate) == {
        ReferenceSource.OWN_LISTINGS: 0.6,
        ReferenceSource.MIETSPIEGEL: 0.4,
    }


def test_blend_weights_come_from_the_assumptions_and_are_normalised():
    custom = Assumptions(rent_blend_weights={"market": 3, "mietspiegel": 1})
    estimate = estimate_rent(make_listing(), index(rentals(5), [MIETSPIEGEL_10]), custom)
    assert estimate.rent_m2 == pytest.approx(11.5)  # 0.75 × 12 + 0.25 × 10


def test_blend_market_part_falls_back_to_price_map():
    estimate = estimate_rent(make_listing(), index(rentals(2), [MIETSPIEGEL_10, PRICE_MAP_13]), A)
    assert estimate.rent_m2 == pytest.approx(11.8)  # 0.6 × 13 + 0.4 × 10
    assert weights(estimate) == {ReferenceSource.PRICE_MAP: 0.6, ReferenceSource.MIETSPIEGEL: 0.4}


def test_blend_with_only_one_side_uses_it_fully():
    only_market = estimate_rent(make_listing(), index(rentals(5)), A)
    assert only_market.rent_m2 == 12.0
    assert weights(only_market) == {ReferenceSource.OWN_LISTINGS: 1.0}

    only_table = estimate_rent(make_listing(), index([], [MIETSPIEGEL_10]), A)
    assert only_table.rent_m2 == 10.0
    assert weights(only_table) == {ReferenceSource.MIETSPIEGEL: 1.0}


def test_no_data_at_all_gives_no_estimate():
    assert estimate_rent(make_listing(), index(), A) is None


def test_unknown_living_area_gives_no_estimate():
    listing = make_listing(living_area_m2=None)
    assert estimate_rent(listing, index(rentals(10), [MIETSPIEGEL_10]), A) is None


def test_plots_have_no_rent_estimate():
    plot = make_listing(property_type="GRUNDSTUECK", living_area_m2=None, plot_area_m2=500)
    assert estimate_rent(plot, index(rentals(10), [MIETSPIEGEL_10]), A) is None


# --- confidence --------------------------------------------------------------------


def test_confidence_high_needs_agreeing_sources_and_many_samples():
    # 10 own listings (>= 2 × 5) at 12.0, Mietspiegel 10.0: estimate 11.2, both within 25 %
    estimate = estimate_rent(make_listing(), index(rentals(10), [MIETSPIEGEL_10]), A)
    assert estimate.confidence is Confidence.HIGH


def test_confidence_medium_with_agreeing_sources_but_few_samples():
    estimate = estimate_rent(make_listing(), index(rentals(5), [MIETSPIEGEL_10]), A)
    assert estimate.confidence is Confidence.MEDIUM


def test_confidence_medium_with_many_samples_but_disagreeing_sources():
    # estimate 0.6 × 12 + 0.4 × 5 = 9.2; own listings are 30 % above, the table 46 % below
    far_off = ref(ReferenceSource.MIETSPIEGEL, 5.0)
    estimate = estimate_rent(make_listing(), index(rentals(10, 12.0), [far_off]), A)
    assert estimate.rent_m2 == pytest.approx(9.2)
    assert estimate.confidence is Confidence.MEDIUM


def test_confidence_low_with_a_single_reference():
    estimate = estimate_rent(make_listing(), index([], [MIETSPIEGEL_10]), A)
    assert estimate.confidence is Confidence.LOW


# --- order of precedence -----------------------------------------------------------


def test_override_beats_actual_rent_and_estimate():
    listing = make_listing(actual_rent_month=700, is_rented=True)
    estimate = estimate_rent(listing, index(rentals(5)), A)
    rent = resolve_rent(listing, estimate, rent_override=900)
    assert rent.value_month == 900
    assert rent.rent_m2 == 15.0
    assert rent.origin is ValueOrigin.OVERRIDE
    assert rent.confidence is Confidence.HIGH
    assert rent.strategy is None


def test_actual_rent_beats_the_estimate():
    listing = make_listing(actual_rent_month=700, is_rented=True)
    rent = resolve_rent(listing, estimate_rent(listing, index(rentals(5)), A))
    assert rent.value_month == 700
    assert rent.origin is ValueOrigin.ACTUAL


def test_actual_rent_counts_when_rented_flag_is_unknown_but_not_when_vacant():
    estimate = estimate_rent(make_listing(), index(rentals(5)), A)
    unknown = make_listing(actual_rent_month=700, is_rented=None)
    vacant = make_listing(actual_rent_month=700, is_rented=False)
    assert resolve_rent(unknown, estimate).origin is ValueOrigin.ACTUAL
    assert resolve_rent(vacant, estimate).origin is ValueOrigin.ESTIMATED


def test_estimate_is_used_when_nothing_else_exists():
    listing = make_listing()
    estimate = estimate_rent(listing, index(rentals(5)), A)
    assert resolve_rent(listing, estimate) is estimate
    assert resolve_rent(listing, None) is None


# --- reference lookup --------------------------------------------------------------


def test_reference_prefers_district_then_postal_code_then_city():
    city = ref(ReferenceSource.MIETSPIEGEL, 10.0)
    plz = ref(ReferenceSource.MIETSPIEGEL, 10.5, area_key="plz:14482")
    district = ref(ReferenceSource.MIETSPIEGEL, 11.0, area_key="Potsdam/Babelsberg")
    listing = make_listing()

    assert index([], [city, plz, district]).mietspiegel_rent_m2(listing).value == 11.0
    assert index([], [city, plz]).mietspiegel_rent_m2(listing).value == 10.5
    assert index([], [city]).mietspiegel_rent_m2(listing).value == 10.0
    assert index([], []).mietspiegel_rent_m2(listing) is None


def test_reference_prefers_matching_type_and_segment_and_skips_others():
    general = ref(ReferenceSource.MIETSPIEGEL, 10.0)
    for_flats = ref(ReferenceSource.MIETSPIEGEL, 10.4, property_type="ETW")
    for_band = ref(ReferenceSource.MIETSPIEGEL, 10.8, property_type="ETW", segment="60-90")
    other_band = ref(ReferenceSource.MIETSPIEGEL, 14.0, property_type="ETW", segment="<40")
    for_houses = ref(ReferenceSource.MIETSPIEGEL, 9.0, property_type="HAUS")
    listing = make_listing()  # ETW, 60 m² -> band 60-90
    everything = [general, for_flats, for_band, other_band, for_houses]

    assert index([], everything).mietspiegel_rent_m2(listing).value == 10.8
    assert index([], [general, for_flats, other_band]).mietspiegel_rent_m2(listing).value == 10.4
    assert index([], [general, for_houses, other_band]).mietspiegel_rent_m2(listing).value == 10.0
    assert index([], [for_houses, other_band]).mietspiegel_rent_m2(listing) is None


def test_expired_and_future_references_are_ignored():
    old = ref(ReferenceSource.MIETSPIEGEL, 8.0, valid_from=date(2024, 1, 1),
              valid_to=date(2025, 12, 31))  # fmt: skip
    current = ref(ReferenceSource.MIETSPIEGEL, 10.0, valid_from=date(2026, 1, 1))
    future = ref(ReferenceSource.MIETSPIEGEL, 12.0, valid_from=date(2028, 1, 1))
    assert index([], [old, current, future]).mietspiegel_rent_m2(make_listing()).value == 10.0
    assert index([], [old, future]).mietspiegel_rent_m2(make_listing()) is None


def test_newest_valid_reference_wins():
    older = ref(ReferenceSource.MIETSPIEGEL, 9.0, valid_from=date(2024, 1, 1))
    newer = ref(ReferenceSource.MIETSPIEGEL, 10.0, valid_from=date(2026, 1, 1))
    assert index([], [newer, older]).mietspiegel_rent_m2(make_listing()).value == 10.0


# --- area price --------------------------------------------------------------------


def sale(i: int, price_m2: float, **overrides):
    data = {"source_listing_id": f"K-{i}", "price": price_m2 * 60.0, "living_area_m2": 60.0}
    data.update(overrides)
    return make_listing(**data)


def test_area_price_uses_own_sale_listings_of_the_same_type():
    flats = [sale(i, p) for i, p in enumerate([3000, 3500, 4000, 4500, 5000])]
    houses = [sale(50 + i, 2000, property_type="HAUS") for i in range(5)]
    area = index(flats + houses).area_price_m2(make_listing())
    assert area.value == 4000
    assert area.source is ReferenceSource.OWN_LISTINGS
    assert area.sample_size == 5
    assert area.property_type is PropertyType.ETW


def test_area_price_falls_back_to_price_map_then_valuation_committee():
    price_map = ref(ReferenceSource.PRICE_MAP, 4200, metric=AreaMetric.BUY_PRICE_M2,
                    property_type="ETW")  # fmt: skip
    committee = ref(ReferenceSource.GUTACHTERAUSSCHUSS, 3900, metric=AreaMetric.BUY_PRICE_M2,
                    property_type="ETW")  # fmt: skip
    few = [sale(i, 4000) for i in range(3)]
    listing = make_listing()

    assert index(few, [price_map, committee]).area_price_m2(listing).value == 4200
    assert index(few, [committee]).area_price_m2(listing).value == 3900
    assert index(few).area_price_m2(listing) is None


def test_plots_use_plot_area_and_only_own_listings():
    def plot(i, price_m2):
        return make_listing(
            source_listing_id=f"G-{i}",
            property_type="GRUNDSTUECK",
            living_area_m2=None,
            plot_area_m2=500,
            price=price_m2 * 500,
        )

    boris = ref(ReferenceSource.BORIS, 180, metric=AreaMetric.LAND_VALUE_M2)
    market = index([plot(i, p) for i, p in enumerate([150, 200, 250, 300, 350])], [boris])
    assert market.area_price_m2(plot(99, 400)).value == 250
    assert market.land_value_m2(plot(99, 400)).value == 180
    assert index([], [boris]).area_price_m2(plot(99, 400)) is None


# --- exact lookups (area statistics page) ------------------------------------------


def test_area_keys_lists_areas_from_listings_and_references():
    market = index(rentals(1), [ref(ReferenceSource.BORIS, 500, area_key="Berlin",
                                    metric=AreaMetric.LAND_VALUE_M2)])  # fmt: skip
    assert market.area_keys() == ["Berlin", "Potsdam", "Potsdam/Babelsberg"]


def test_own_median_is_exact_and_respects_min_samples():
    market = index(rentals(5, 12.0) + [sale(i, 4000) for i in range(5)])
    rent = market.own_median(AreaMetric.RENT_M2, "Potsdam/Babelsberg", PropertyType.ETW)
    assert (rent.value, rent.sample_size) == (12.0, 5)
    price = market.own_median(AreaMetric.BUY_PRICE_M2, "Potsdam", PropertyType.ETW)
    assert price.value == 4000
    assert market.own_median(AreaMetric.RENT_M2, "Potsdam", PropertyType.HAUS) is None
    assert market.own_median(AreaMetric.RENT_M2, "Berlin", PropertyType.ETW) is None
    assert market.own_median(AreaMetric.RENT_M2, "Potsdam", None).sample_size == 5  # all types
    thin = index(rentals(4))
    assert thin.own_median(AreaMetric.RENT_M2, "Potsdam", PropertyType.ETW) is None


def test_stored_reference_is_exact_per_area():
    city = ref(ReferenceSource.MIETSPIEGEL, 10.0)
    flats = ref(ReferenceSource.MIETSPIEGEL, 10.5, property_type="ETW")
    market = index([], [city, flats])
    get = market.stored_reference
    assert get(AreaMetric.RENT_M2, ReferenceSource.MIETSPIEGEL, "Potsdam").value == 10.0
    assert (
        get(AreaMetric.RENT_M2, ReferenceSource.MIETSPIEGEL, "Potsdam", PropertyType.ETW).value
        == 10.5
    )
    # no fallback from the district to the city, and no other sources
    assert get(AreaMetric.RENT_M2, ReferenceSource.MIETSPIEGEL, "Potsdam/Babelsberg") is None
    assert get(AreaMetric.RENT_M2, ReferenceSource.PRICE_MAP, "Potsdam") is None
