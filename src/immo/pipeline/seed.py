"""Fill the database with sample data (used by `immo.cli seed` and later by the UI)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from immo.core.models import utcnow
from immo.core.sample_data import (
    DEFAULT_SEED,
    HISTORY_ROUNDS,
    SAMPLE_SOURCE,
    SampleWorld,
    round_time,
)
from immo.storage.repository import Repository


class SeedSummary(BaseModel):
    rounds: int
    listings_total: int
    listings_active: int
    snapshots: int
    area_references: int


def seed_database(
    repo: Repository,
    *,
    seed: int = DEFAULT_SEED,
    now: datetime | None = None,
    reset: bool = False,
) -> SeedSummary:
    """Replay the simulated fetch rounds into the database.

    Each round is handled like a real fetch: upsert everything that is online, then
    mark what was not seen as inactive. Price drops, listings going offline and
    relistings therefore end up in the snapshot history by themselves.
    """
    now = now or utcnow()
    if reset:
        repo.reset()
    elif repo.count_listings() > 0:
        raise RuntimeError("database already contains listings; run the seed with --reset")

    world = SampleWorld(seed=seed)
    for round_index in range(HISTORY_ROUNDS):
        seen_at = round_time(round_index, now)
        listings = world.listings_at(round_index, seen_at)
        repo.upsert_listings(listings, seen_at)
        repo.deactivate_missing(
            SAMPLE_SOURCE, [listing.source_listing_id for listing in listings], seen_at
        )
    references = repo.add_area_references(world.area_references(valid_from=now.date()))

    snapshots = repo.snapshots_by_listing()
    return SeedSummary(
        rounds=HISTORY_ROUNDS,
        listings_total=repo.count_listings(),
        listings_active=len(repo.list_listings(active_only=True)),
        snapshots=sum(len(items) for items in snapshots.values()),
        area_references=references,
    )
