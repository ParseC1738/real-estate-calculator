"""Headless tests for the M6 pages: assumptions, area statistics, rentals, overrides."""

import pytest
from streamlit.testing.v1 import AppTest

from immo.core.assumptions import Assumptions, list_profiles, load_profile, save_profile
from immo.core.models import OfferType, OverrideField, PropertyType
from immo.paths import PROJECT_ROOT

APP = str(PROJECT_ROOT / "src" / "immo" / "ui" / "app.py")


def open_page(page: str, **session) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=30)
    for key, value in session.items():
        app.session_state[key] = value
    app.run()
    app.switch_page(f"pages/{page}.py").run()
    assert not app.exception
    return app


def metric(app: AppTest, label: str) -> str:
    return next(m.value for m in app.metric if m.label == label)


def widget(collection, label_start: str):
    return next(w for w in collection if w.label.startswith(label_start))


@pytest.fixture
def profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMO_PROFILES_DIR", str(tmp_path))
    return tmp_path


# --- assumptions -------------------------------------------------------------------


def test_assumptions_page_shows_the_defaults(sample_db, profiles):
    app = open_page("assumptions")
    assert widget(app.slider, "Interest rate").value == 3.8
    assert widget(app.slider, "Equity").value == 20.0
    assert widget(app.number_input, "Transfer tax Brandenburg").value == 6.5
    assert widget(app.radio, "Strategy").value == "blend"
    assert metric(app, "Median gross yield") != "n/a"


def test_changed_assumption_affects_metrics_immediately(sample_db, profiles):
    """The M6 acceptance criterion: change an assumption -> metrics change everywhere."""
    app = open_page("assumptions")
    cashflow_before = metric(app, "Median cash flow / month")
    net_before = metric(app, "Median net yield")

    widget(app.slider, "Interest rate").set_value(1.0).run()
    assert not app.exception
    assert app.session_state["assumptions"].interest_rate_pct == 1.0
    cashflow_after = metric(app, "Median cash flow / month")
    assert cashflow_after != cashflow_before  # cheaper loan -> better cash flow
    assert metric(app, "Median net yield") == net_before  # net yield ignores financing

    # ... and the overview, a different page, uses the same assumptions at once
    app.switch_page("pages/overview.py").run()
    assert not app.exception
    assert metric(app, "Median cash flow / month") != ""
    overview_default = open_page("overview")
    assert metric(app, "Median cash flow / month") != metric(
        overview_default, "Median cash flow / month"
    )


def test_rent_strategy_changes_the_estimates(sample_db, profiles):
    app = open_page("assumptions")
    blend = metric(app, "Median gross yield")
    widget(app.radio, "Strategy").set_value("mietspiegel").run()
    assert not app.exception
    assert metric(app, "Median gross yield") < blend  # the official table is lower


def test_signal_thresholds_are_editable(sample_db, profiles):
    app = open_page("assumptions")
    good_before = metric(app, "🟢 good signal")
    widget(app.number_input, "🟢 good from").set_value(2.0).run()
    assert not app.exception
    assert int(metric(app, "🟢 good signal").split()[0]) > int(good_before.split()[0])
    threshold = app.session_state["assumptions"].traffic_light["gross_yield_pct"]
    assert threshold.green_min == 2.0
    assert threshold.yellow_min <= threshold.green_min


def test_save_load_and_reset_profile(sample_db, profiles):
    app = open_page("assumptions")
    widget(app.slider, "Equity").set_value(35.0).run()
    widget(app.text_input, "Save current values as").input("Cautious").run()
    widget(app.button, "💾 Save profile").click().run()
    assert not app.exception
    assert list_profiles(profiles) == ["cautious"]
    assert load_profile("cautious", profiles).equity_pct == 35.0

    widget(app.button, "↩️ Reset to defaults").click().run()
    assert not app.exception
    assert widget(app.slider, "Equity").value == 20.0
    assert app.session_state["assumptions"] == Assumptions()

    widget(app.selectbox, "Saved profiles").select("cautious").run()
    widget(app.button, "📂 Load profile").click().run()
    assert not app.exception
    assert widget(app.slider, "Equity").value == 35.0
    assert app.session_state["assumptions"].equity_pct == 35.0


def test_profile_saved_elsewhere_is_listed(sample_db, profiles):
    save_profile(Assumptions(interest_rate_pct=5.0), "expensive money", profiles)
    app = open_page("assumptions")
    assert widget(app.selectbox, "Saved profiles").options == ["expensive-money"]


# --- area statistics ---------------------------------------------------------------


def test_area_statistics_compares_sources_per_city(sample_db):
    app = open_page("areas")
    table = app.dataframe[0].value
    assert list(table["area"]) == ["Berlin", "Brandenburg an der Havel", "Potsdam"]
    assert {"own_listings", "mietspiegel", "price_map", "own_vs_mietspiegel_pct"} <= set(
        table.columns
    )
    assert table["own_listings"].notna().all()
    assert len(app.get("plotly_chart")) == 1


def test_area_statistics_switches_metric_type_and_level(sample_db):
    app = open_page("areas")
    widget(app.selectbox, "Metric").select("land_value_m2").run()
    assert not app.exception
    assert "boris" in app.dataframe[0].value.columns

    widget(app.selectbox, "Metric").select("buy_price_m2").run()
    widget(app.selectbox, "Property type").select(PropertyType.MFH).run()
    assert not app.exception
    assert "gutachterausschuss" in app.dataframe[0].value.columns

    widget(app.selectbox, "Areas").select("Districts of Potsdam").run()
    assert not app.exception
    districts = set(app.dataframe[0].value["area"])
    assert "Babelsberg" in districts and "Berlin" not in districts


# --- rental listings ---------------------------------------------------------------


def test_rental_listings_table_and_filter(sample_db):
    app = open_page("rentals")
    table = app.dataframe[0].value
    assert {"rent_per_m2", "rent_vs_mietspiegel_pct", "rent_vs_area_pct"} <= set(table.columns)
    assert table["is_active"].all()
    assert metric(app, "Listings shown").endswith("of 400")

    widget(app.sidebar.multiselect, "City").set_value(["Berlin"]).run()
    assert not app.exception
    assert set(app.dataframe[0].value["city"]) == {"Berlin"}


# --- overrides ---------------------------------------------------------------------


@pytest.fixture
def vacant_flat(sample_db):
    flat = next(
        x
        for x in sample_db.list_listings(offer_type=OfferType.KAUF, active_only=True)
        if x.property_type is PropertyType.ETW and x.living_area_m2 and not x.actual_rent_month
    )
    yield flat
    for override in sample_db.list_overrides(flat.id):  # leave the shared DB clean
        sample_db.delete_override(flat.id, override.field)


def test_override_changes_the_metrics_immediately(sample_db, vacant_flat):
    app = open_page("detail", detail_listing_id=vacant_flat.id)
    yield_before = metric(app, "Gross yield")
    assert "estimated" in app.caption[1].value

    # set a rent that gives exactly 12 % gross yield
    rent = vacant_flat.price * 0.12 / 12
    # widgets inside a form are only sent together with the submit button: no .run() before
    widget(app.number_input, "Cold rent per month").set_value(rent)
    widget(app.text_input, "Note").input("test")
    widget(app.button, "Save overrides").click().run()

    assert not app.exception
    assert metric(app, "Gross yield") == "12.00 %" != yield_before
    assert any("override" in c.value for c in app.caption)
    (stored,) = sample_db.list_overrides(vacant_flat.id)
    assert (stored.field, stored.note) == (OverrideField.RENT_MONTH, "test")
    assert stored.value == pytest.approx(rent)
    # the stored listing itself is untouched
    assert sample_db.get_listing(vacant_flat.id) == vacant_flat

    # the overview marks the listing as overridden
    app.switch_page("pages/overview.py").run()
    table = app.dataframe[0].value
    assert table["overridden"].sum() == 1


def test_price_override_and_removal(sample_db, vacant_flat):
    app = open_page("detail", detail_listing_id=vacant_flat.id)
    original_price = metric(app, "Price")

    widget(app.number_input, "Purchase price").set_value(vacant_flat.price / 2)
    widget(app.button, "Save overrides").click().run()
    assert not app.exception
    assert metric(app, "Price") != original_price
    assert len(sample_db.list_overrides(vacant_flat.id)) == 1

    widget(app.button, "Remove override: Purchase price").click().run()
    assert not app.exception
    assert metric(app, "Price") == original_price
    assert sample_db.list_overrides(vacant_flat.id) == []


def test_plot_only_offers_a_price_override(sample_db):
    plot = sample_db.list_listings(
        offer_type=OfferType.KAUF, property_type=PropertyType.GRUNDSTUECK
    )[0]
    app = open_page("detail", detail_listing_id=plot.id)
    labels = [n.label for n in app.number_input]
    assert labels == ["Purchase price (€)"]
