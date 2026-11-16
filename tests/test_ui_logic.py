"""Tests for the UI helpers that contain logic but no Streamlit calls."""

from datetime import timedelta

import pandas as pd
import pytest

from immo.core.assumptions import Assumptions, Threshold
from immo.core.estimates import MarketIndex
from immo.core.evaluate import evaluate_buy, evaluate_rental
from immo.core.metrics import RentInput, buy_metrics
from immo.core.models import AreaMetric, OfferType, Override, PropertyType, ValueOrigin
from immo.ui import charts
from immo.ui import formatting as fmt
from immo.ui.explain import explain_buy
from immo.ui.tables import (
    BuyFilters,
    RentalFilters,
    area_table,
    buy_table,
    filter_buy_table,
    filter_rental_table,
    rental_table,
)
from tests.conftest import T0, make_listing

A = Assumptions()


# --- formatting --------------------------------------------------------------------


def test_formatting_rounds_only_for_display():
    assert fmt.eur(224_140.4) == "224,140 €"
    assert fmt.eur(866.6747, 2) == "866.67 €"
    assert fmt.pct(4.8) == "4.8 %"
    assert fmt.pct(-16.666, signed=True) == "-16.7 %"
    assert fmt.pct(12.0, signed=True) == "+12.0 %"
    assert fmt.num(20.8333, 1) == "20.8"
    assert fmt.area(60) == "60.0 m²"


def test_missing_values_are_shown_as_na():
    assert fmt.eur(None) == fmt.pct(None) == fmt.num(None) == fmt.signal(None) == "n/a"
    assert fmt.origin(None) == "n/a"


def test_signal_and_origin_have_icon_and_word():
    assert fmt.origin(ValueOrigin.ESTIMATED) == "🧮 estimated"
    assert all(" " in label for label in fmt.SIGNAL_LABEL.values())


# --- table + filters ---------------------------------------------------------------


@pytest.fixture(scope="module")
def table(seeded_repo) -> pd.DataFrame:
    listings = seeded_repo.list_listings()
    index = MarketIndex(listings, seeded_repo.list_area_references(), on_date=T0.date())
    snapshots = seeded_repo.snapshots_by_listing()
    evaluations = [
        evaluate_buy(x, index, A, snapshots=snapshots[x.id], now=T0)
        for x in listings
        if x.offer_type is OfferType.KAUF
    ]
    return buy_table(evaluations)


def test_buy_table_has_one_row_per_listing(table):
    assert len(table) == 300
    assert table["id"].is_unique
    assert {"gross_yield_pct", "cashflow_month", "days_online", "signal"} <= set(table.columns)
    plots = table[table["type"] == "GRUNDSTUECK"]
    assert plots["gross_yield_pct"].isna().all()
    assert plots["signal"].isna().all()
    assert plots["area_m2"].notna().all()  # plot area


def test_empty_table_keeps_its_columns():
    empty = buy_table([])
    assert empty.empty
    assert "gross_yield_pct" in empty.columns
    assert filter_buy_table(empty, BuyFilters(only_active=True)).empty


def test_no_filters_keep_everything(table):
    assert len(filter_buy_table(table, BuyFilters())) == len(table)


def test_category_filters(table):
    berlin = filter_buy_table(table, BuyFilters(cities=["Berlin"]))
    assert set(berlin["city"]) == {"Berlin"}
    flats = filter_buy_table(table, BuyFilters(cities=["Berlin"], types=["ETW"]))
    assert set(flats["type"]) == {"ETW"} and 0 < len(flats) < len(berlin)
    mitte = filter_buy_table(table, BuyFilters(districts=["Mitte"]))
    assert set(mitte["district"]) == {"Mitte"}


def test_range_filters_exclude_unknown_values(table):
    result = filter_buy_table(table, BuyFilters(price=(100_000, 300_000)))
    assert result["price"].between(100_000, 300_000).all() and len(result) > 0
    with_year = filter_buy_table(table, BuyFilters(year_built=(1990, 2030)))
    assert with_year["year_built"].notna().all()
    assert with_year["year_built"].min() >= 1990


def test_return_filters(table):
    good = filter_buy_table(table, BuyFilters(min_gross_yield_pct=5.0))
    assert (good["gross_yield_pct"] >= 5.0).all()
    assert "GRUNDSTUECK" not in set(good["type"])  # no yield -> filtered out
    positive = filter_buy_table(table, BuyFilters(min_cashflow_month=0))
    assert (positive["cashflow_month"] >= 0).all()
    cheap = filter_buy_table(table, BuyFilters(max_price_vs_area_pct=-10))
    assert (cheap["price_vs_area_pct"] <= -10).all() and len(cheap) > 0
    net = filter_buy_table(table, BuyFilters(min_net_yield_pct=3.0))
    assert (net["net_yield_pct"] >= 3.0).all()


def test_status_filters(table):
    active = filter_buy_table(table, BuyFilters(only_active=True))
    assert active["is_active"].all() and len(active) < len(table)
    reduced = filter_buy_table(table, BuyFilters(only_price_reduced=True))
    assert (reduced["price_drops"] > 0).all() and len(reduced) > 0
    long_online = filter_buy_table(table, BuyFilters(days_online=(60, 100)))
    assert long_online["days_online"].min() >= 60


def test_filters_combine_with_and(table):
    both = filter_buy_table(table, BuyFilters(cities=["Potsdam"], only_price_reduced=True))
    assert set(both["city"]) <= {"Potsdam"}
    assert (both["price_drops"] > 0).all()


# --- calculation steps -------------------------------------------------------------


def test_explain_lists_every_step_with_its_numbers():
    metrics = buy_metrics(
        make_listing(),
        A,
        rent=RentInput(value_month=800, origin=ValueOrigin.ACTUAL),
        area_avg_price_per_m2=4000,
    )
    steps = {s.label: s for s in explain_buy(metrics, A)}

    assert steps["Purchase costs (Kaufnebenkosten)"].result == "24,140 €"
    assert "6.50 %" in steps["Purchase costs (Kaufnebenkosten)"].formula
    assert "estimated" in steps["Purchase costs (Kaufnebenkosten)"].formula  # default commission
    assert steps["Total investment"].result == "224,140 €"
    assert steps["Gross yield (Bruttomietrendite)"].result == "4.80 %"
    assert steps["Net operating income"].result == "7,248 €"
    assert steps["Cash flow per month (before tax)"].result == "-262.67 €"
    assert steps["Price vs. area"].result == "-16.7 %"
    assert "actual" in steps["Annual cold rent"].formula


def test_explain_for_a_plot_stops_before_the_yield_steps():
    plot = make_listing(
        property_type="GRUNDSTUECK", price=120_000, living_area_m2=None, plot_area_m2=600
    )
    labels = [s.label for s in explain_buy(buy_metrics(plot, A, land_value_m2=160), A)]
    assert labels == [
        "Price per m²",
        "Price vs. land value (BORIS)",
        "Purchase costs (Kaufnebenkosten)",
        "Total investment",
    ]


def test_explain_mfh_adds_unit_and_upside_steps():
    mfh = make_listing(
        property_type="MFH", price=900_000, living_area_m2=480, units=6, actual_rent_month=4200
    )
    metrics = buy_metrics(
        mfh,
        A,
        rent=RentInput(value_month=4200, origin=ValueOrigin.ACTUAL),
        market_rent_month=4800,
    )
    steps = {s.label: s.result for s in explain_buy(metrics, A)}
    assert steps["Rent per unit"] == "700 €"
    assert steps["Rent upside"] == "+14.3 %"


# --- charts ------------------------------------------------------------------------


def test_yield_histogram_counts_and_overflow_bin():
    values = pd.Series([3.2, 3.4, 4.8, 5.0, 42.0, None])
    fig = charts.yield_histogram(values, Threshold(green_min=5.0, yellow_min=3.5))
    bar = fig.data[0]
    assert sum(bar.y) == 5  # the missing value is ignored
    counts = dict(zip(bar.customdata, bar.y, strict=True))
    assert counts["3–3.5 %"] == 2
    assert counts["4.5–5 %"] == 1
    assert counts["5–5.5 %"] == 1
    assert counts["10 % or more"] == 1  # the outlier does not stretch the axis
    assert len(fig.layout.annotations) == 2  # both thresholds are labelled


def test_price_by_city_uses_a_fixed_colour_per_type(table):
    fig = charts.price_m2_by_city(table)
    colours = {trace.name: trace.marker.color for trace in fig.data}
    assert len(fig.data) == 3  # plots are not comparable per m² of living area
    only_houses = charts.price_m2_by_city(table[table["type"] == "HAUS"])
    assert only_houses.data[0].marker.color == colours["House"]  # survives a filter
    dark = charts.price_m2_by_city(table, theme="dark")
    assert dark.data[0].marker.color != fig.data[0].marker.color


def test_price_history_extends_the_last_price_to_the_end():
    series = [(T0, 200_000.0), (T0 + timedelta(days=7), 190_000.0)]
    fig = charts.price_history(series, end=T0 + timedelta(days=30))
    line, markers = fig.data
    assert list(line.y) == [200_000.0, 190_000.0, 190_000.0]
    assert line.x[-1] == T0 + timedelta(days=30)
    assert line.line.shape == "hv"
    assert len(markers.x) == 2
    assert charts.price_history([], end=T0).data == ()


# --- M6: rental table, area table, overrides flag ----------------------------------


@pytest.fixture(scope="module")
def market_index(seeded_repo) -> MarketIndex:
    return MarketIndex(
        seeded_repo.list_listings(), seeded_repo.list_area_references(), on_date=T0.date()
    )


@pytest.fixture(scope="module")
def rentals(seeded_repo, market_index) -> pd.DataFrame:
    snapshots = seeded_repo.snapshots_by_listing()
    return rental_table(
        [
            evaluate_rental(x, market_index, snapshots=snapshots[x.id], now=T0)
            for x in seeded_repo.list_listings(offer_type=OfferType.MIETE)
        ]
    )


def test_rental_table_and_filters(rentals):
    assert len(rentals) == 400
    assert rentals["rent_vs_mietspiegel_pct"].notna().sum() > 300
    # asking rents are above the (sample) Mietspiegel on average
    assert rentals["rent_vs_mietspiegel_pct"].median() > 0

    potsdam = filter_rental_table(rentals, RentalFilters(cities=["Potsdam"], only_active=True))
    assert set(potsdam["city"]) == {"Potsdam"} and potsdam["is_active"].all()
    cheap = filter_rental_table(rentals, RentalFilters(rent_per_m2=(0, 9)))
    assert cheap["rent_per_m2"].max() <= 9 and len(cheap) > 0
    small = filter_rental_table(rentals, RentalFilters(area_m2=(0, 40), types=["ETW"]))
    assert small["area_m2"].max() <= 40 and set(small["type"]) == {"ETW"}
    assert len(filter_rental_table(rentals, RentalFilters())) == 400
    assert rental_table([]).empty


def test_area_table_puts_sources_side_by_side(market_index):
    cities = ["Berlin", "Brandenburg an der Havel", "Potsdam"]
    table = area_table(market_index, cities, AreaMetric.RENT_M2, PropertyType.ETW)

    assert list(table["area"]) == cities
    assert list(table.columns) == [
        "area", "own_listings", "own_samples", "mietspiegel", "price_map",
        "own_vs_mietspiegel_pct", "own_vs_price_map_pct",
    ]  # fmt: skip
    assert table.notna().all().all()
    assert (table["own_samples"] >= 5).all()
    # sample data: Mietspiegel (existing rents) lies below the asking rents
    assert (table["own_vs_mietspiegel_pct"] > 0).all()
    row = table.iloc[0]
    expected = (row["own_listings"] - row["mietspiegel"]) / row["mietspiegel"] * 100
    assert row["own_vs_mietspiegel_pct"] == pytest.approx(expected)


def test_area_table_for_prices_and_land_values(market_index):
    prices = area_table(market_index, ["Berlin"], AreaMetric.BUY_PRICE_M2, PropertyType.MFH)
    assert {"price_map", "gutachterausschuss"} <= set(prices.columns)
    assert pd.isna(prices.loc[0, "price_map"])  # the sample price map has no MFH values
    assert prices.loc[0, "gutachterausschuss"] > 0

    land = area_table(market_index, ["Berlin"], AreaMetric.LAND_VALUE_M2, PropertyType.GRUNDSTUECK)
    assert land.loc[0, "boris"] > 0 and land.loc[0, "own_listings"] > 0


def test_area_table_leaves_thin_areas_empty(market_index):
    table = area_table(market_index, ["Nowhere"], AreaMetric.RENT_M2, PropertyType.ETW)
    assert table.drop(columns=["area"]).isna().all().all()


def test_area_comparison_chart_keeps_source_colours():
    table = pd.DataFrame(
        {"area": ["A", "B"], "own_listings": [12.0, None], "mietspiegel": [10.0, 9.0]}
    )
    fig = charts.area_comparison(
        table, [("own_listings", "Own listings"), ("mietspiegel", "Mietspiegel")], "€/m²"
    )
    by_name = {trace.name: trace for trace in fig.data}
    assert list(by_name["Own listings"].y) == ["A"]  # the missing value is left out
    assert set(by_name["Mietspiegel"].y) == {"A", "B"}
    assert by_name["Own listings"].marker.color == charts.PALETTE["light"]["series"][0]
    assert by_name["Mietspiegel"].marker.color == charts.PALETTE["light"]["series"][1]


def test_buy_table_flags_overridden_listings(market_index):
    listing = make_listing()
    plain = evaluate_buy(listing, market_index, A)
    changed = evaluate_buy(
        listing, market_index, A, [Override(listing_id=listing.id, field="rent_month", value=900)]
    )
    table = buy_table([plain, changed])
    assert list(table["overridden"]) == [False, True]
    assert table.loc[1, "rent_origin"] == "✏️ override"
