from datetime import timedelta

from immo.core.history import diff_tracked, price_series, summarize_history
from immo.core.models import ListingSnapshot
from tests.conftest import T0, make_listing


def snap(days: int, price: float, changes: dict | None = None) -> ListingSnapshot:
    return ListingSnapshot(
        listing_id="x", seen_at=T0 + timedelta(days=days), price=price, changes=changes or {}
    )


def test_diff_only_reports_tracked_fields():
    old = make_listing(price=200_000, title="Alt", condition="renovated")
    new = make_listing(price=190_000, title="Alt", condition="needs renovation")
    assert diff_tracked(old, new) == {"price": {"old": 200_000.0, "new": 190_000.0}}


def test_diff_is_empty_for_identical_listings():
    assert diff_tracked(make_listing(), make_listing()) == {}


def test_summary_for_listing_without_changes():
    listing = make_listing()
    summary = summarize_history(listing, [snap(0, 200_000)], now=T0 + timedelta(days=10))
    assert summary.days_online == 10
    assert summary.price_change_count == 0
    assert summary.total_price_change_pct == 0
    assert summary.relisted is False
    assert summary.last_price_change_at is None


def test_summary_counts_price_drops_and_total_change():
    # 200,000 -> 190,000 -> 180,000: two drops, -10 % in total
    listing = make_listing(price=180_000)
    snapshots = [
        snap(0, 200_000),
        snap(7, 190_000, {"price": {"old": 200_000, "new": 190_000}}),
        snap(14, 180_000, {"price": {"old": 190_000, "new": 180_000}}),
    ]
    summary = summarize_history(listing, snapshots, now=T0 + timedelta(days=20))
    assert summary.price_change_count == 2
    assert summary.price_drop_count == 2
    assert summary.first_price == 200_000
    assert summary.total_price_change_pct == -10.0
    assert summary.last_price_change_at == T0 + timedelta(days=14)


def test_price_increase_is_a_change_but_not_a_drop():
    listing = make_listing(price=210_000)
    snapshots = [snap(0, 200_000), snap(7, 210_000, {"price": {"old": 200_000, "new": 210_000}})]
    summary = summarize_history(listing, snapshots, now=T0 + timedelta(days=8))
    assert (summary.price_change_count, summary.price_drop_count) == (1, 0)
    assert summary.total_price_change_pct == 5.0


def test_days_online_stops_at_last_seen_for_inactive_listings():
    listing = make_listing(is_active=False, last_seen=T0 + timedelta(days=5))
    summary = summarize_history(listing, [snap(0, 200_000)], now=T0 + timedelta(days=100))
    assert summary.days_online == 5


def test_relisted_is_detected_from_status_changes():
    listing = make_listing()
    snapshots = [
        snap(0, 200_000),
        snap(7, 200_000, {"is_active": {"old": True, "new": False}}),
        snap(21, 200_000, {"is_active": {"old": False, "new": True}}),
    ]
    assert summarize_history(listing, snapshots, now=T0 + timedelta(days=30)).relisted is True
    # only going offline is not a relisting
    assert summarize_history(listing, snapshots[:2], now=T0).relisted is False


def test_price_series_is_sorted_by_time():
    series = price_series([snap(7, 190_000), snap(0, 200_000)])
    assert [price for _, price in series] == [200_000, 190_000]
