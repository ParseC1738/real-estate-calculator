"""Headless tests for the Data / import page (M7). Each test gets its own database,
because these tests change data."""

import pytest
from streamlit.testing.v1 import AppTest

from immo.core.history import summarize_history
from immo.paths import PROJECT_ROOT
from immo.pipeline.seed import seed_database
from immo.sources.csv_import import TEMPLATE_CSV
from immo.storage.db import make_engine
from immo.storage.repository import Repository
from tests.conftest import T0

APP = str(PROJECT_ROOT / "src" / "immo" / "ui" / "app.py")


@pytest.fixture
def db(tmp_path, monkeypatch) -> Repository:
    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "immo.db"))
    return Repository(make_engine())


def open_import_page() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    app.switch_page("pages/data_import.py").run()
    assert not app.exception
    return app


def button(app: AppTest, label_part: str):
    return next(b for b in app.button if label_part in b.label)


def metric(app: AppTest, label: str) -> str:
    return next(m.value for m in app.metric if m.label == label)


def test_fetch_now_runs_the_sample_adapter_and_logs_it(db):
    seed_database(db, now=T0)
    app = open_import_page()
    assert metric(app, "Listings in the database") == "700"
    assert len(app.dataframe[0].value) == 12  # the seeded history in the run log

    button(app, "Fetch now").click().run()

    assert not app.exception
    assert any("8 new" in s.value for s in app.success)
    assert metric(app, "Listings in the database") == "708"
    log = app.dataframe[0].value
    assert len(log) == 13 and log.iloc[0]["New"] == 8
    assert db.count_fetch_runs("sample") == 13

    button(app, "Fetch now").click().run()  # a second click simulates the next week
    assert metric(app, "Listings in the database") == "716"


def test_csv_upload_creates_listings_and_history(db):
    app = open_import_page()
    assert any("No runs yet" in i.value for i in app.info)

    app.file_uploader[0].upload("listings.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv").run()
    button(app, "Import CSV").click().run()
    assert not app.exception
    assert any("4 new" in s.value for s in app.success)
    assert metric(app, "Sources") == "csv"

    # the same file with one price lowered and one broken row
    changed = TEMPLATE_CSV.replace("329.000", "309.000").replace(";890;", ";teuer;")
    app.file_uploader[0].upload("listings.csv", changed.encode("utf-8"), "text/csv").run()
    button(app, "Import CSV").click().run()

    assert not app.exception
    assert any("1 changed" in w.value and "2 unchanged" in w.value for w in app.warning)
    problems = app.dataframe[0].value
    assert problems["Problem"].iloc[0].startswith("my-004: price: not a number")

    flat = db.get_listing_by_source("csv", "my-001")
    snapshots = db.list_snapshots(flat.id)
    assert [s.price for s in snapshots] == [329_000, 309_000]
    assert summarize_history(flat, snapshots, now=flat.last_seen).price_drop_count == 1
    assert db.get_listing_by_source("csv", "my-004").price == 890  # broken row: unchanged
    assert all(x.is_active for x in db.list_listings())  # nothing was marked gone

    # the imported listings show up in the overview straight away
    app.switch_page("pages/overview.py").run()
    assert not app.exception
    assert {"Potsdam", "Berlin"} <= set(app.dataframe[0].value["city"])


def test_csv_with_wrong_columns_shows_an_error(db):
    app = open_import_page()
    app.file_uploader[0].upload("bad.csv", b"title;price\nFlat;1\n", "text/csv").run()
    button(app, "Import CSV").click().run()
    assert not app.exception
    assert any("missing required column" in e.value for e in app.error)
    assert db.count_listings() == 0


def test_reload_sample_data_needs_confirmation_and_replaces_everything(db):
    app = open_import_page()
    app.file_uploader[0].upload("listings.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv").run()
    button(app, "Import CSV").click().run()
    assert db.count_listings() == 4

    assert button(app, "Reload sample data").disabled
    next(c for c in app.checkbox if c.label.startswith("Yes, delete")).check().run()
    button(app, "Reload sample data").click().run()

    assert not app.exception
    assert any("Sample data reloaded: 700 listings" in s.value for s in app.success)
    assert metric(app, "Sources") == "sample"
    assert db.get_listing_by_source("csv", "my-001") is None
