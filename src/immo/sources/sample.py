"""Adapter for the simulated sample market (see `core/sample_data.py`)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from immo.core.models import Listing, SearchQuery, utcnow
from immo.core.sample_data import DEFAULT_SEED, HISTORY_ROUNDS, SAMPLE_SOURCE, SampleWorld
from immo.sources.base import RawListing

# timestamps are set by the pipeline, not by the source
_NOT_PART_OF_RAW = {"first_seen", "last_seen", "is_active", "raw"}


class SampleAdapter:
    """Delivers the listings that are online in one simulated fetch round.

    `round_index` selects the round: 0..11 are the history that `seed` replays,
    12 and later are "future" rounds in which new listings appear, prices drop and
    listings disappear, so every "Fetch now" has something to show.
    """

    name = SAMPLE_SOURCE

    def __init__(
        self,
        round_index: int = HISTORY_ROUNDS - 1,
        seed: int = DEFAULT_SEED,
        world: SampleWorld | None = None,
    ) -> None:
        self.round_index = round_index
        self._world = world or SampleWorld(seed=seed)

    def fetch(self, query: SearchQuery) -> Iterable[RawListing]:
        placeholder: datetime = utcnow()
        for listing in self._world.listings_at(self.round_index, placeholder):
            if not query.matches(listing):
                continue
            data = listing.model_dump(mode="json", exclude=_NOT_PART_OF_RAW)
            data.update(listing.raw)  # e.g. the "sample_note" that marks an outlier
            yield RawListing(
                source=self.name, source_listing_id=listing.source_listing_id, data=data
            )

    def normalize(self, raw: RawListing) -> Listing:
        fields = {key: value for key, value in raw.data.items() if key in Listing.model_fields}
        return Listing(**fields, raw=raw.data)
