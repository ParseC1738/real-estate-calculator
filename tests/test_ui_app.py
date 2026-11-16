"""Smoke tests that run the Streamlit pages headlessly with `AppTest`.

They do not check pixels; they check that every page runs against the sample database
without an exception and shows the expected elements.
"""

import pytest
from streamlit.testing.v1 import AppTest

from immo.core.models import OfferType, PropertyType
from immo.paths import PROJECT_ROOT
from immo.pipeline.seed import seed_database
from immo.storage.db import make_engine
from immo.storage.repository import Repository
from tests.conftest import T0

APP = str(PROJECT_ROOT / "src" / "immo" / "ui" / "app.py")


@pytest.fixture(scope="module")
def sample_db(tmp_path_factory):
    """A seeded SQLite file; IMMO_DB_PATH points the app at it."""
    path = tmp_path_factory.mktemp("ui") / "immo.db"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("IMMO_DB_PATH", str(path))
        repo = Repository(make_engine())
        seed_database(repo, now=T0)
        yield repo


def run_app() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    return app


def metric(app: AppTest, label: str) -> str:
    return next(m.value for m in app.metric if m.label == label)


def test_overview_shows_table_kpis_and_charts(sample_db):
    app = run_app()
    assert not app.exception
    assert app.title[0].value.startswith("Overview")
    assert len(app.dataframe) >= 1
    table = app.dataframe[0].value
    assert "gross_yield_pct" in table.columns
    assert table["is_active"].all()  # "only active" is on by default
    assert metric(app, "Listings shown").endswith("of 300")
    assert len(app.get("plotly_chart")) == 2


def test_overview_filters_change_the_table(sample_db):
    app = run_app()
    rows_before = len(app.dataframe[0].value)

    city = next(m for m in app.sidebar.multiselect if m.label == "City")
    city.set_value(["Potsdam"]).run()
    assert not app.exception
    table = app.dataframe[0].value
    assert set(table["city"]) == {"Potsdam"}
    assert len(table) < rows_before

    minimum = next(n for n in app.sidebar.number_input if n.label.startswith("Min. gross yield"))
    minimum.set_value(4.0).run()
    assert (app.dataframe[0].value["gross_yield_pct"] >= 4.0).all()

    minimum.set_value(99.0).run()
    assert not app.exception
    assert any("No listing matches" in w.value for w in app.warning)


def test_overview_can_show_inactive_listings(sample_db):
    app = run_app()
    toggle = next(t for t in app.sidebar.toggle if t.label == "Only active listings")
    toggle.set_value(False).run()
    assert len(app.dataframe[0].value) == 300


def test_detail_view_for_a_flat(sample_db):
    flat = next(
        x
        for x in sample_db.list_listings(offer_type=OfferType.KAUF)
        if x.property_type is PropertyType.ETW and x.living_area_m2 and not x.actual_rent_month
    )
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["detail_listing_id"] = flat.id
    app.run()
    app.switch_page("pages/detail.py").run()

    assert not app.exception
    assert app.header[0].value == flat.title
    assert metric(app, "Price").replace(",", "").startswith(f"{flat.price:.0f}")
    assert metric(app, "Gross yield") != "n/a"
    assert [t.label for t in app.tabs] == [
        "Calculation",
        "Rent estimate",
        "Price history",
        "Property data",
    ]
    steps = app.tabs[0].dataframe[0].value
    assert "Gross yield (Bruttomietrendite)" in set(steps["Metric"])
    sources = app.tabs[1].dataframe[0].value
    assert {"Source", "Rent €/m²", "Weight", "Samples"} <= set(sources.columns)
    assert len(app.tabs[2].get("plotly_chart")) == 1


def test_detail_view_for_a_plot_shows_na_for_yields(sample_db):
    plot = sample_db.list_listings(
        offer_type=OfferType.KAUF, property_type=PropertyType.GRUNDSTUECK
    )[0]
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["detail_listing_id"] = plot.id
    app.run()
    app.switch_page("pages/detail.py").run()

    assert not app.exception
    assert metric(app, "Gross yield") == "n/a"
    assert metric(app, "Land value (BORIS)") != "n/a"


def test_every_sale_listing_renders_in_the_detail_view(sample_db):
    """Messy data must never crash the page (missing area, outliers, inactive …)."""
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    app.switch_page("pages/detail.py").run()
    picker = app.selectbox[0]
    for listing_id in picker.options[::12]:  # every 12th listing keeps the test fast
        picker.select(listing_id).run()
        assert not app.exception, listing_id


def test_empty_database_shows_a_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "empty.db"))
    app = run_app()
    assert not app.exception
    assert any("seed --reset" in info.value for info in app.info)
    app.switch_page("pages/detail.py").run()
    assert not app.exception
    assert any("seed --reset" in info.value for info in app.info)
