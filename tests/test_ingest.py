"""Ingest pipeline tests. The CSV scenarios are the M7 acceptance criterion:
"CSV import creates snapshots correctly"."""

from datetime import timedelta

import pytest

from immo.core.history import summarize_history
from immo.core.models import OfferType, SearchQuery
from immo.core.sample_data import HISTORY_ROUNDS
from immo.pipeline.ingest import MAX_LOGGED_ERRORS, run_ingest
from immo.pipeline.seed import seed_database
from immo.sources.base import RawListing
from immo.sources.csv_import import CsvAdapter
from immo.sources.registry import active_adapters, next_sample_round
from immo.sources.sample import SampleAdapter
from tests.conftest import T0, make_listing

T1 = T0 + timedelta(days=7)
T2 = T0 + timedelta(days=14)
T3 = T0 + timedelta(days=21)

HEADER = "source_listing_id;offer_type;property_type;title;city;postal_code;price;living_area_m2\n"


def csv(*rows: str) -> CsvAdapter:
    return CsvAdapter(HEADER + "".join(row + "\n" for row in rows))


FLAT = "flat-1;KAUF;ETW;Flat;Potsdam;14482;{price};60"
HOUSE = "house-1;KAUF;HAUS;House;Berlin;10115;500.000;140"


# --- CSV import creates snapshots correctly ----------------------------------------


def test_first_csv_import_creates_listings_with_initial_snapshots(repo):
    run = run_ingest(csv(FLAT.format(price="200.000"), HOUSE), repo, now=T0)

    assert (run.source, run.fetched, run.new, run.errors) == ("csv", 2, 2, [])
    flat = repo.get_listing_by_source("csv", "flat-1")
    assert (flat.price, flat.first_seen, flat.last_seen, flat.is_active) == (200_000, T0, T0, True)
    (snapshot,) = repo.list_snapshots(flat.id)
    assert (snapshot.seen_at, snapshot.price, snapshot.changes) == (T0, 200_000, {})


def test_reimporting_the_same_file_creates_no_new_snapshots(repo):
    adapter = csv(FLAT.format(price="200.000"), HOUSE)
    run_ingest(adapter, repo, now=T0)
    run = run_ingest(adapter, repo, now=T1)

    assert (run.new, run.changed, run.unchanged) == (0, 0, 2)
    flat = repo.get_listing_by_source("csv", "flat-1")
    assert len(repo.list_snapshots(flat.id)) == 1
    assert (flat.first_seen, flat.last_seen) == (T0, T1)


def test_changed_price_in_csv_creates_a_snapshot_with_old_and_new_value(repo):
    run_ingest(csv(FLAT.format(price="200.000"), HOUSE), repo, now=T0)
    run = run_ingest(csv(FLAT.format(price="185.000"), HOUSE), repo, now=T1)
    run_ingest(csv(FLAT.format(price="179.000"), HOUSE), repo, now=T2)

    assert (run.changed, run.unchanged, run.new) == (1, 1, 0)
    flat = repo.get_listing_by_source("csv", "flat-1")
    snapshots = repo.list_snapshots(flat.id)
    assert [(s.seen_at, s.price) for s in snapshots] == [
        (T0, 200_000),
        (T1, 185_000),
        (T2, 179_000),
    ]
    assert snapshots[1].changes == {"price": {"old": 200_000.0, "new": 185_000.0}}
    assert snapshots[2].changes == {"price": {"old": 185_000.0, "new": 179_000.0}}

    summary = summarize_history(flat, snapshots, now=T3)
    assert summary.price_drop_count == 2
    assert summary.total_price_change_pct == pytest.approx(-10.5)
    assert summary.days_online == 21
    # the house never changed: still exactly one snapshot
    house = repo.get_listing_by_source("csv", "house-1")
    assert len(repo.list_snapshots(house.id)) == 1


def test_partial_csv_does_not_deactivate_by_default(repo):
    run_ingest(csv(FLAT.format(price="200.000"), HOUSE), repo, now=T0)
    run = run_ingest(csv(HOUSE), repo, now=T1, deactivate_missing=False)
    assert run.gone == 0
    assert repo.get_listing_by_source("csv", "flat-1").is_active is True


def test_full_csv_marks_missing_listings_gone_and_relists_them(repo):
    both = csv(FLAT.format(price="200.000"), HOUSE)
    run_ingest(both, repo, now=T0)
    gone_run = run_ingest(csv(HOUSE), repo, now=T1)
    back_run = run_ingest(csv(FLAT.format(price="195.000"), HOUSE), repo, now=T2)

    assert gone_run.gone == 1
    assert (back_run.relisted, back_run.changed) == (1, 0)
    flat = repo.get_listing_by_source("csv", "flat-1")
    snapshots = repo.list_snapshots(flat.id)
    assert [s.changes.get("is_active", {}).get("new") for s in snapshots] == [None, False, True]
    assert snapshots[2].changes["price"] == {"old": 200_000.0, "new": 195_000.0}
    assert summarize_history(flat, snapshots, now=T3).relisted is True


# --- validation and failures -------------------------------------------------------


def test_invalid_rows_are_reported_and_valid_rows_still_imported(repo):
    adapter = csv(
        FLAT.format(price="200.000"),
        "bad-price;KAUF;ETW;Flat;Potsdam;14482;teuer;60",
        "bad-type;KAUF;SCHLOSS;Castle;Potsdam;14482;900.000;600",
        "negative;KAUF;ETW;Flat;Potsdam;14482;-5;60",
    )
    run = run_ingest(adapter, repo, now=T0)

    assert (run.fetched, run.new) == (4, 1)
    assert len(run.errors) == 3
    assert run.errors[0].startswith("bad-price: price: not a number")
    assert run.errors[1].startswith("bad-type: property_type:")
    assert run.errors[2].startswith("negative: price:")
    assert repo.count_listings() == 1
    assert repo.list_fetch_runs()[0].errors == run.errors


def test_a_listing_that_becomes_invalid_is_not_marked_gone(repo):
    run_ingest(csv(FLAT.format(price="200.000"), HOUSE), repo, now=T0)
    run = run_ingest(csv(FLAT.format(price="kaputt"), HOUSE), repo, now=T1)
    assert (run.gone, len(run.errors)) == (0, 1)
    assert repo.get_listing_by_source("csv", "flat-1").is_active is True


def test_failed_fetch_changes_nothing_and_is_logged(repo):
    run_ingest(csv(FLAT.format(price="200.000")), repo, now=T0)
    run = run_ingest(CsvAdapter("source_listing_id;title\nx;y\n"), repo, now=T1)

    assert run.errors[0].startswith("fetch failed: CSV is missing required column(s)")
    assert (run.new, run.gone) == (0, 0)
    assert repo.get_listing_by_source("csv", "flat-1").is_active is True
    assert [r.note for r in repo.list_fetch_runs()][0] == "fetch failed, database unchanged"


def test_empty_fetch_never_deactivates_everything(repo):
    run_ingest(csv(FLAT.format(price="200.000")), repo, now=T0)
    run = run_ingest(CsvAdapter(HEADER), repo, now=T1)
    assert run.gone == 0 and "nothing was marked as gone" in run.note
    assert repo.get_listing_by_source("csv", "flat-1").is_active is True


def test_logged_errors_are_capped(repo):
    rows = [f"bad-{i};KAUF;ETW;Flat;Potsdam;14482;x;60" for i in range(MAX_LOGGED_ERRORS + 10)]
    run = run_ingest(csv(*rows), repo, now=T0)
    assert len(run.errors) == MAX_LOGGED_ERRORS + 10  # the caller gets all of them
    assert len(repo.list_fetch_runs()[0].errors) == MAX_LOGGED_ERRORS


# --- query scope and adapter independence ------------------------------------------


def test_query_limits_import_and_deactivation(repo):
    run_ingest(csv(FLAT.format(price="200.000"), HOUSE), repo, now=T0)
    berlin = SearchQuery(cities=["Berlin"])
    # a Berlin-only run that sees no Berlin house: only the house may go, not the flat
    other = "house-2;KAUF;HAUS;Other house;Berlin;10115;450.000;120"
    run = run_ingest(csv(other, FLAT.format(price="1")), repo, query=berlin, now=T1)

    assert (run.new, run.gone) == (1, 1)
    assert repo.get_listing_by_source("csv", "house-1").is_active is False
    flat = repo.get_listing_by_source("csv", "flat-1")
    assert (flat.is_active, flat.price) == (True, 200_000)  # outside the query: untouched


def test_pipeline_works_with_any_object_that_looks_like_an_adapter(repo):
    """No inheritance needed: two methods and a name are enough (Protocol)."""

    class TwoListings:
        name = "handmade"

        def fetch(self, query):
            return [RawListing(source=self.name, source_listing_id=str(i)) for i in (1, 2)]

        def normalize(self, raw):
            return make_listing(source="whatever", source_listing_id=raw.source_listing_id)

    run = run_ingest(TwoListings(), repo, now=T0)
    assert run.new == 2
    assert {x.source for x in repo.list_listings()} == {"handmade"}  # the adapter's name wins


def test_sources_do_not_touch_each_others_listings(repo):
    run_ingest(csv(FLAT.format(price="200.000")), repo, now=T0)
    run_ingest(SampleAdapter(round_index=0), repo, now=T0)
    run_ingest(SampleAdapter(round_index=5), repo, now=T1)  # deactivates sample listings only
    assert repo.get_listing_by_source("csv", "flat-1").is_active is True


# --- sample source: seed + "fetch now" ---------------------------------------------


def test_seed_logs_every_round_and_fetch_now_continues_the_simulation(repo):
    seed_database(repo, now=T0)
    assert repo.count_fetch_runs("sample") == HISTORY_ROUNDS
    assert next_sample_round(repo) == HISTORY_ROUNDS
    snapshots_before = sum(len(s) for s in repo.snapshots_by_listing().values())

    (adapter,) = active_adapters(repo)
    assert adapter.round_index == HISTORY_ROUNDS
    run = run_ingest(adapter, repo, now=T1)

    assert run.new == 8  # 3 KAUF + 5 MIETE appear per simulated week
    assert run.changed + run.gone + run.relisted > 0
    assert run.errors == []
    snapshots_after = sum(len(s) for s in repo.snapshots_by_listing().values())
    assert snapshots_after == snapshots_before + run.new + run.changed + run.gone + run.relisted
    assert next_sample_round(repo) == HISTORY_ROUNDS + 1  # the next click moves on
    assert len(repo.list_listings(offer_type=OfferType.KAUF)) == 303
