"""The adapter interface every data source implements (SPEC §9).

Adapter pattern in one sentence: each source (sample data, a CSV file, later a portal
or a paid API) is wrapped in a small class with the same two methods, so the pipeline
can treat them all alike and the core never knows where a listing came from.

`SourceAdapter` is a `Protocol`: a class does not have to inherit from it, it only
needs the right attributes and methods ("duck typing" that type checkers understand).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from immo.core.models import Listing, SearchQuery


class RawListing(BaseModel):
    """One listing exactly as the source delivered it, before any cleaning."""

    source: str
    source_listing_id: str
    data: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    name: str  # stored as `Listing.source`

    def fetch(self, query: SearchQuery) -> Iterable[RawListing]:
        """Get the raw listings for a query. May use the network; never the database."""
        ...

    def normalize(self, raw: RawListing) -> Listing:
        """Turn one raw listing into a validated `Listing`.

        Raises `ValueError` (pydantic's `ValidationError` is one) if the data is
        unusable; the pipeline then skips this listing and reports it.
        """
        ...
