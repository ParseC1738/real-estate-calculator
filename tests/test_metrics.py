"""Metrics tests with hand-calculated examples.

The expected numbers are written out as literals with the calculation in a comment, so
the tests document the formulas and do not just repeat the implementation.
"""

import pytest

from immo.core.assumptions import Assumptions, Threshold
from immo.core.metrics import (
    Indicator,
    RentInput,
    annuity_month,
    buy_metrics,
    pct_diff,
    price_per_m2,
    purchase_costs,
    rent_listing_metrics,
    traffic_light,
)
from immo.core.models import ValueOrigin
from tests.conftest import make_listing

A = Assumptions()  # SPEC defaults


def actual(rent: float) -> RentInput:
    return RentInput(value_month=rent, origin=ValueOrigin.ACTUAL)


# --- building blocks ---------------------------------------------------------------


def test_pct_diff():
    assert pct_diff(90, 100) == -10
    assert pct_diff(125, 100) == 25
    assert pct_diff(None, 100) is None
    assert pct_diff(100, None) is None
    assert pct_diff(100, 0) is None


def test_price_per_m2_uses_living_area():
    flat = make_listing(price=200_000, living_area_m2=60)
    assert price_per_m2(flat) == pytest.approx(3333.33, abs=0.01)
    assert price_per_m2(make_listing(living_area_m2=None)) is None


def test_price_per_m2_uses_plot_area_for_plots():
    plot = make_listing(
        property_type="GRUNDSTUECK", price=120_000, living_area_m2=None, plot_area_m2=600
    )
    assert price_per_m2(plot) == 200


def test_purchase_costs_brandenburg_with_default_commission():
    # 200,000 × (6.5 + 2.0 + 3.57) % = 200,000 × 12.07 % = 24,140
    costs = purchase_costs(200_000, "Potsdam", None, A)
    assert costs.transfer_tax == pytest.approx(13_000)
    assert costs.notary_land_registry == pytest.approx(4_000)
    assert costs.commission == pytest.approx(7_140)
    assert costs.commission_origin is ValueOrigin.ESTIMATED
    assert costs.total_pct == pytest.approx(12.07)
    assert costs.total == pytest.approx(24_140)


def test_purchase_costs_berlin_with_commission_from_listing():
    # 300,000 × (6.0 + 2.0 + 2.38) % = 300,000 × 10.38 % = 31,140
    costs = purchase_costs(300_000, "Berlin", 2.38, A)
    assert costs.transfer_tax == pytest.approx(18_000)
    assert costs.commission == pytest.approx(7_140)
    assert costs.commission_origin is ValueOrigin.ACTUAL
    assert costs.total == pytest.approx(31_140)


def test_zero_commission_is_a_real_value_not_unknown():
    costs = purchase_costs(300_000, "Berlin", 0.0, A)
    assert costs.commission == 0
    assert costs.commission_origin is ValueOrigin.ACTUAL
    assert costs.total == pytest.approx(24_000)  # 8 %


def test_annuity_month():
    # 100,000 × (3.8 + 2.0) % / 12 = 5,800 / 12 = 483.33
    assert annuity_month(100_000, 3.8, 2.0) == pytest.approx(483.33, abs=0.01)
    assert annuity_month(0, 3.8, 2.0) == 0


def test_traffic_light_thresholds():
    t = Threshold(green_min=5.0, yellow_min=3.5)
    assert traffic_light(5.0, t) is Indicator.GREEN
    assert traffic_light(6.2, t) is Indicator.GREEN
    assert traffic_light(4.99, t) is Indicator.YELLOW
    assert traffic_light(3.5, t) is Indicator.YELLOW
    assert traffic_light(3.49, t) is Indicator.RED
    assert traffic_light(None, t) is None
    assert traffic_light(5.0, None) is None


# --- ETW: the full calculation -----------------------------------------------------


def test_flat_full_example():
    """Flat in Potsdam: 200,000 EUR, 60 m², 800 EUR cold rent, commission unknown."""
    m = buy_metrics(make_listing(), A, rent=actual(800), area_avg_price_per_m2=4_000)

    # §6.2
    assert m.price_per_m2 == pytest.approx(3_333.33, abs=0.01)  # 200,000 / 60
    assert m.price_vs_area_pct == pytest.approx(-16.67, abs=0.01)  # 3,333.33 vs 4,000
    assert m.purchase_costs.total == pytest.approx(24_140)  # 12.07 %
    assert m.total_investment == pytest.approx(224_140)

    # §6.3 rent and yields
    assert m.rent_origin is ValueOrigin.ACTUAL
    assert m.annual_cold_rent == 9_600  # 800 × 12
    assert m.gross_yield_pct == pytest.approx(4.8)  # 9,600 / 200,000
    assert m.price_to_rent_factor == pytest.approx(20.833, abs=0.001)  # 200,000 / 9,600
    assert m.non_recoverable_costs == pytest.approx(1_440)  # 15 % of 9,600
    assert m.maintenance_costs == pytest.approx(720)  # 12 EUR × 60 m²
    assert m.vacancy_costs == pytest.approx(192)  # 2 % of 9,600
    assert m.net_operating_income == pytest.approx(7_248)  # 9,600 − 1,440 − 720 − 192
    assert m.net_yield_pct == pytest.approx(3.2337, abs=0.0001)  # 7,248 / 224,140

    # financing
    assert m.equity == pytest.approx(44_828)  # 20 % of 224,140
    assert m.loan == pytest.approx(179_312)
    assert m.annuity_month == pytest.approx(866.67, abs=0.01)  # 179,312 × 5.8 % / 12
    assert m.cashflow_month_pretax == pytest.approx(-262.67, abs=0.01)  # 604 − 866.67
    assert m.cash_on_cash_pct == pytest.approx(-7.03, abs=0.01)  # −3,152.10 / 44,828

    assert m.indicator is Indicator.YELLOW  # 3.5 <= 4.8 < 5
    assert m.notes == []
    # not applicable to a flat
    assert m.rent_per_unit is None
    assert m.rent_upside_pct is None
    assert m.price_vs_land_value_pct is None


def test_flat_in_berlin_uses_berlin_tax_and_listing_commission():
    listing = make_listing(city="Berlin", price=300_000, living_area_m2=75, commission_pct=0)
    m = buy_metrics(listing, A, rent=actual(1_250))
    assert m.purchase_costs.total == pytest.approx(24_000)  # (6 + 2 + 0) %
    assert m.total_investment == pytest.approx(324_000)
    assert m.gross_yield_pct == pytest.approx(5.0)  # 15,000 / 300,000
    assert m.price_to_rent_factor == pytest.approx(20.0)
    assert m.indicator is Indicator.GREEN


def test_changed_assumptions_change_the_result():
    cash_buyer = A.model_copy(update={"equity_pct": 100.0})
    m = buy_metrics(make_listing(), cash_buyer, rent=actual(800))
    assert m.loan == 0
    assert m.annuity_month == 0
    assert m.cashflow_month_pretax == pytest.approx(604)  # 7,248 / 12
    assert m.cash_on_cash_pct == pytest.approx(3.2337, abs=0.0001)  # equals the net yield


def test_zero_equity_has_no_cash_on_cash():
    m = buy_metrics(make_listing(), A.model_copy(update={"equity_pct": 0.0}), rent=actual(800))
    assert m.equity == 0
    assert m.loan == pytest.approx(224_140)
    assert m.cash_on_cash_pct is None


def test_origins_are_passed_through():
    m = buy_metrics(
        make_listing(),
        A,
        rent=RentInput(value_month=800, origin=ValueOrigin.ESTIMATED),
        price_origin=ValueOrigin.OVERRIDE,
        area_origin=ValueOrigin.OVERRIDE,
    )
    assert m.rent_origin is ValueOrigin.ESTIMATED
    assert m.price_origin is ValueOrigin.OVERRIDE
    assert m.area_origin is ValueOrigin.OVERRIDE


def test_without_rent_only_the_basic_metrics_exist():
    m = buy_metrics(make_listing(), A, rent=None)
    assert m.price_per_m2 is not None
    assert m.total_investment == pytest.approx(224_140)
    assert m.gross_yield_pct is None
    assert m.cashflow_month_pretax is None
    assert m.indicator is None
    assert m.notes


def test_missing_living_area_skips_maintenance_and_says_so():
    m = buy_metrics(make_listing(living_area_m2=None), A, rent=actual(800))
    assert m.price_per_m2 is None
    assert m.maintenance_costs == 0
    assert m.net_operating_income == pytest.approx(7_968)  # 9,600 − 1,440 − 192
    assert any("maintenance" in note for note in m.notes)


# --- HAUS / MFH / GRUNDSTUECK ------------------------------------------------------


def test_house_gets_yield_metrics():
    house = make_listing(property_type="HAUS", price=450_000, living_area_m2=140, plot_area_m2=500)
    m = buy_metrics(house, A, rent=RentInput(value_month=1_500, origin=ValueOrigin.ESTIMATED))
    assert m.price_per_m2 == pytest.approx(3_214.29, abs=0.01)  # living area, not plot
    assert m.gross_yield_pct == pytest.approx(4.0)  # 18,000 / 450,000
    assert m.rent_per_unit is None


def test_apartment_building_adds_rent_per_unit_and_upside():
    """MFH: 900,000 EUR, 480 m², 6 units, actual rent 4,200, market estimate 4,800."""
    mfh = make_listing(
        property_type="MFH",
        price=900_000,
        living_area_m2=480,
        units=6,
        actual_rent_month=4_200,
        is_rented=True,
    )
    m = buy_metrics(mfh, A, rent=actual(4_200), market_rent_month=4_800)
    assert m.gross_yield_pct == pytest.approx(5.6)  # 50,400 / 900,000
    assert m.price_to_rent_factor == pytest.approx(17.857, abs=0.001)
    assert m.rent_per_unit == pytest.approx(700)  # 4,200 / 6
    assert m.rent_upside_pct == pytest.approx(14.29, abs=0.01)  # (4,800 − 4,200) / 4,200
    assert m.indicator is Indicator.GREEN


def test_apartment_building_without_actual_rent_has_no_upside():
    mfh = make_listing(property_type="MFH", price=900_000, living_area_m2=480, units=None)
    m = buy_metrics(
        mfh,
        A,
        rent=RentInput(value_month=4_800, origin=ValueOrigin.ESTIMATED),
        market_rent_month=4_800,
    )
    assert m.rent_upside_pct is None
    assert m.rent_per_unit is None  # number of units unknown


def test_plot_has_land_value_comparison_but_no_yield():
    """Plot in Brandenburg a. d. H.: 120,000 EUR, 600 m², land value 160 EUR/m²."""
    plot = make_listing(
        property_type="GRUNDSTUECK",
        city="Brandenburg an der Havel",
        price=120_000,
        living_area_m2=None,
        plot_area_m2=600,
    )
    m = buy_metrics(plot, A, rent=actual(500), land_value_m2=160, area_avg_price_per_m2=250)
    assert m.price_per_m2 == 200  # 120,000 / 600
    assert m.area_m2 == 600
    assert m.price_vs_land_value_pct == pytest.approx(25.0)  # 200 vs 160
    assert m.price_vs_area_pct == pytest.approx(-20.0)  # 200 vs 250
    assert m.purchase_costs.total == pytest.approx(14_484)  # 12.07 %
    assert m.total_investment == pytest.approx(134_484)
    # no yield metrics, even if a rent is passed in by mistake
    assert m.annual_cold_rent is None
    assert m.gross_yield_pct is None
    assert m.net_yield_pct is None
    assert m.cashflow_month_pretax is None
    assert m.indicator is None


def test_buy_metrics_rejects_rental_listings():
    with pytest.raises(ValueError):
        buy_metrics(make_listing(offer_type="MIETE", price=800), A)


def test_buy_metrics_does_not_modify_its_inputs():
    listing, assumptions = make_listing(), Assumptions()
    before = (listing.model_copy(deep=True), assumptions.model_copy(deep=True))
    buy_metrics(listing, assumptions, rent=actual(800))
    assert (listing, assumptions) == before


# --- MIETE -------------------------------------------------------------------------


def test_rental_listing_metrics():
    """780 EUR for 60 m² = 13.00 EUR/m²; Mietspiegel 10.00, area median 12.50."""
    rental = make_listing(offer_type="MIETE", price=780, living_area_m2=60)
    m = rent_listing_metrics(rental, mietspiegel_rent_m2=10.0, area_rent_m2=12.5)
    assert m.rent_per_m2 == pytest.approx(13.0)
    assert m.rent_vs_mietspiegel_pct == pytest.approx(30.0)
    assert m.rent_vs_area_pct == pytest.approx(4.0)


def test_rental_listing_without_area_or_references():
    rental = make_listing(offer_type="MIETE", price=780, living_area_m2=None)
    m = rent_listing_metrics(rental)
    assert m.rent_per_m2 is None
    assert m.rent_vs_mietspiegel_pct is None
    assert m.rent_vs_area_pct is None


def test_rent_listing_metrics_rejects_sale_listings():
    with pytest.raises(ValueError):
        rent_listing_metrics(make_listing())
