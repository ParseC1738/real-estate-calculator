"""Listing history: detecting changes and deriving values from snapshots (SPEC §4.3).

Everything here is a pure function. The repository decides *when* to store a snapshot,
this module decides *what* counts as a change and what the history means.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from immo.core.models import Listing, ListingSnapshot

# A change in one of these fields creates a new snapshot.
TRACKED_FIELDS = ("price", "living_area_m2", "plot_area_m2", "title", "is_active")


class UpsertOutcome(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    RELISTED = "relisted"


class UpsertResult(BaseModel):
    listing_id: str
    outcome: UpsertOutcome
    changes: dict[str, Any] = {}


def diff_tracked(old: Listing, new: Listing) -> dict[str, dict[str, Any]]:
    """Return `{field: {"old": x, "new": y}}` for every tracked field that differs."""
    changes: dict[str, dict[str, Any]] = {}
    for field in TRACKED_FIELDS:
        before, after = getattr(old, field), getattr(new, field)
        if before != after:
            changes[field] = {"old": before, "new": after}
    return changes


class HistorySummary(BaseModel):
    days_online: int
    price_change_count: int
    price_drop_count: int
    first_price: float
    total_price_change_pct: float  # negative = cheaper than at first sight
    relisted: bool
    last_price_change_at: datetime | None = None


def summarize_history(
    listing: Listing, snapshots: list[ListingSnapshot], now: datetime
) -> HistorySummary:
    """Derive the history values shown in the UI.

    - days online: first sighting until now (active) or until the last sighting (gone).
      Gaps while a relisted listing was offline are not subtracted.
    - total price change: current price vs. the price at the first sighting.
    """
    ordered = sorted(snapshots, key=lambda s: s.seen_at)
    end = now if listing.is_active else listing.last_seen
    days_online = max((end - listing.first_seen).days, 0)

    price_changes = [s for s in ordered if "price" in s.changes]
    drops = [s for s in price_changes if s.changes["price"]["new"] < s.changes["price"]["old"]]
    first_price = ordered[0].price if ordered else listing.price
    total_pct = (listing.price - first_price) / first_price * 100 if first_price else 0.0
    relisted = any(s.changes.get("is_active", {}).get("new") is True for s in ordered if s.changes)
    return HistorySummary(
        days_online=days_online,
        price_change_count=len(price_changes),
        price_drop_count=len(drops),
        first_price=first_price,
        total_price_change_pct=total_pct,
        relisted=relisted,
        last_price_change_at=price_changes[-1].seen_at if price_changes else None,
    )


def price_series(snapshots: list[ListingSnapshot]) -> list[tuple[datetime, float]]:
    """(time, price) points for the price-history chart."""
    return [(s.seen_at, s.price) for s in sorted(snapshots, key=lambda s: s.seen_at)]
