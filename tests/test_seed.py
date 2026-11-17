from datetime import timedelta

import pytest

from immo import cli
from immo.core.history import summarize_history
from immo.core.models import OfferType
from immo.pipeline.seed import seed_database
from immo.storage.db import make_engine
from immo.storage.repository import Repository
from tests.conftest import T0, make_listing


@pytest.fixture(scope="module")
def seeded():
    """Seeding takes a few seconds, so all read-only tests share one database."""
    from immo.storage.db import IN_MEMORY_URL

    repo = Repository(make_engine(IN_MEMORY_URL))
    summary = seed_database(repo, now=T0)
    return repo, summary


def test_seed_fills_the_database(seeded):
    repo, summary = seeded
    assert summary.listings_total == 700
    assert len(repo.list_listings(offer_type=OfferType.KAUF)) == 300
    assert len(repo.list_listings(offer_type=OfferType.MIETE)) == 400
    assert 0 < summary.listings_active < 700
    assert summary.snapshots > 700  # more than the initial snapshot per listing
    assert summary.area_references == len(repo.list_area_references()) > 0


def test_seed_creates_a_real_history(seeded):
    repo, _ = seeded
    snapshots = repo.snapshots_by_listing()
    summaries = [
        summarize_history(listing, snapshots[listing.id], now=T0)
        for listing in repo.list_listings(offer_type=OfferType.KAUF)
    ]
    assert {s.price_drop_count for s in summaries} >= {0, 1, 2, 3}
    assert any(s.relisted for s in summaries)
    assert any(s.total_price_change_pct < -5 for s in summaries)
    assert max(s.days_online for s in summaries) == 77  # 11 weeks before "now"
    assert min(s.days_online for s in summaries) == 0


def test_seed_timestamps_span_the_simulated_weeks(seeded):
    repo, _ = seeded
    listings = repo.list_listings()
    assert min(x.first_seen for x in listings) == T0 - timedelta(days=77)
    assert max(x.last_seen for x in listings) == T0
    inactive = [x for x in listings if not x.is_active]
    assert inactive and all(x.last_seen < T0 for x in inactive)


def test_seed_refuses_to_mix_with_existing_data(repo):
    repo.upsert_listing(make_listing(), seen_at=T0)
    with pytest.raises(RuntimeError, match="--reset"):
        seed_database(repo, now=T0)


def test_seed_with_reset_replaces_existing_data(repo):
    repo.upsert_listing(make_listing(), seen_at=T0)
    seed_database(repo, now=T0, reset=True)
    assert repo.get_listing_by_source("test", "A-1") is None
    assert repo.count_listings() == 700


def test_cli_seed_reset(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "immo.db"))

    assert cli.main(["seed", "--reset"]) == 0
    assert "700" in capsys.readouterr().out
    assert Repository(make_engine()).count_listings() == 700

    # without --reset the command refuses and returns an error code
    assert cli.main(["seed"]) == 1
    assert "--reset" in capsys.readouterr().err


def test_cli_ingest_fetches_from_active_adapters(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "immo.db"))
    cli.main(["seed", "--reset"])
    capsys.readouterr()

    assert cli.main(["ingest"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("sample: fetched") and "new 8" in out
    assert Repository(make_engine()).count_listings() == 708


def test_cli_ingest_csv(tmp_path, monkeypatch, capsys):
    from immo.sources.csv_import import TEMPLATE_CSV

    monkeypatch.setenv("IMMO_DB_PATH", str(tmp_path / "immo.db"))
    good = tmp_path / "listings.csv"
    good.write_text(TEMPLATE_CSV, encoding="utf-8")
    bad = tmp_path / "bad.csv"
    bad.write_text("title;price\nFlat;1\n", encoding="utf-8")

    assert cli.main(["ingest", "--csv", str(good)]) == 0
    assert "csv: fetched 4 | new 4" in capsys.readouterr().out
    assert Repository(make_engine()).count_listings() == 4

    assert cli.main(["ingest", "--csv", str(bad)]) == 1  # wrong columns
    assert "fetch failed" in capsys.readouterr().out
    assert cli.main(["ingest", "--csv", str(tmp_path / "missing.csv")]) == 1
    assert "cannot read" in capsys.readouterr().err
