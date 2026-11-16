"""The repository: the ONLY module that talks to the database.

Repository pattern in one sentence: the rest of the app asks for domain objects
("give me all KAUF listings") and never writes SQL or touches a session. Benefits:
- the storage technology can change without touching metrics, pipeline or UI,
- tests can run against a throw-away in-memory database,
- every query lives in one file, so it is easy to see what the app does with its data.

Every public method opens its own session and commits once (one method = one
transaction). Callers receive Pydantic models, never table rows.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from immo.core.history import UpsertOutcome, UpsertResult, diff_tracked
from immo.core.models import (
    AreaMetric,
    AreaReference,
    FetchRun,
    Listing,
    ListingSnapshot,
    OfferType,
    Override,
    OverrideField,
    PropertyType,
    ReferenceSource,
    SearchQuery,
    listing_fingerprint,
    utcnow,
)
from immo.storage.tables import (
    AreaReferenceRow,
    Base,
    FetchRunRow,
    ListingRow,
    ListingSnapshotRow,
    OverrideRow,
)

_LISTING_FIELDS = tuple(Listing.model_fields)
# fields that an update from a source must never change
_KEEP_ON_UPDATE = {"id", "first_seen"}


def _row_to_listing(row: ListingRow) -> Listing:
    return Listing(**{name: getattr(row, name) for name in _LISTING_FIELDS})


def _listing_to_values(listing: Listing) -> dict:
    values = listing.model_dump(mode="python")
    values["offer_type"] = listing.offer_type.value
    values["property_type"] = listing.property_type.value
    values["fingerprint"] = listing_fingerprint(listing)
    return values


def _row_to_reference(row: AreaReferenceRow) -> AreaReference:
    return AreaReference(
        area_key=row.area_key,
        metric=row.metric,
        property_type=row.property_type,
        segment=row.segment,
        value=row.value,
        low=row.low,
        high=row.high,
        source=row.source,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        note=row.note,
        sample_size=row.sample_size,
    )


def _row_to_override(row: OverrideRow) -> Override:
    return Override(
        listing_id=row.listing_id,
        field=row.field,
        value=row.value,
        created_at=row.created_at,
        note=row.note,
    )


def _row_to_snapshot(row: ListingSnapshotRow) -> ListingSnapshot:
    return ListingSnapshot(
        listing_id=row.listing_id, seen_at=row.seen_at, price=row.price, changes=row.changes
    )


class Repository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _session(self) -> Session:
        # expire_on_commit=False: rows stay readable after commit, which we need to
        # convert them into Pydantic models before the session closes.
        return Session(self._engine, expire_on_commit=False)

    # --- maintenance ---------------------------------------------------------------

    def reset(self) -> None:
        """Delete ALL data and recreate empty tables (used by `seed --reset`)."""
        Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)

    # --- listings ------------------------------------------------------------------

    def upsert_listing(self, listing: Listing, seen_at: datetime | None = None) -> UpsertResult:
        return self.upsert_listings([listing], seen_at)[0]

    def upsert_listings(
        self, listings: Iterable[Listing], seen_at: datetime | None = None
    ) -> list[UpsertResult]:
        """Insert new listings, update known ones, and snapshot relevant changes.

        A listing is "known" when (source, source_listing_id) already exists. The
        stored `id` and `first_seen` never change. A snapshot is written for a new
        listing and whenever a tracked field (price, area, title, status) differs.
        All listings are handled in one transaction: either all are stored or none.
        """
        seen_at = seen_at or utcnow()
        listings = list(listings)
        results: list[UpsertResult] = []
        with self._session() as session:
            # Load all known rows of the affected sources with ONE query instead of
            # one query per listing (matters for fetches with hundreds of listings).
            sources = {listing.source for listing in listings}
            known = {
                (row.source, row.source_listing_id): row
                for row in session.scalars(select(ListingRow).where(ListingRow.source.in_(sources)))
            }
            for listing in listings:
                results.append(self._upsert_one(session, known, listing, seen_at))
            session.commit()
        return results

    def _upsert_one(
        self,
        session: Session,
        known: dict[tuple[str, str], ListingRow],
        listing: Listing,
        seen_at: datetime,
    ) -> UpsertResult:
        key = (listing.source, listing.source_listing_id)
        row = known.get(key)
        if row is None:
            new = listing.model_copy(
                update={"first_seen": seen_at, "last_seen": seen_at, "is_active": True}
            )
            row = ListingRow(**_listing_to_values(new))
            session.add(row)
            session.add(
                ListingSnapshotRow(listing_id=new.id, seen_at=seen_at, price=new.price, changes={})
            )
            # remember it, so a second listing with the same key in this batch is an update
            known[key] = row
            return UpsertResult(listing_id=new.id, outcome=UpsertOutcome.NEW)

        old = _row_to_listing(row)
        # Being seen again means the listing is online, whatever the stored state was.
        new = listing.model_copy(
            update={
                "id": old.id,
                "first_seen": old.first_seen,
                "last_seen": seen_at,
                "is_active": True,
            }
        )
        changes = diff_tracked(old, new)
        for name, value in _listing_to_values(new).items():
            if name not in _KEEP_ON_UPDATE:
                setattr(row, name, value)
        if not changes:
            return UpsertResult(listing_id=old.id, outcome=UpsertOutcome.UNCHANGED)

        session.add(
            ListingSnapshotRow(listing_id=old.id, seen_at=seen_at, price=new.price, changes=changes)
        )
        relisted = changes.get("is_active", {}).get("new") is True
        outcome = UpsertOutcome.RELISTED if relisted else UpsertOutcome.CHANGED
        return UpsertResult(listing_id=old.id, outcome=outcome, changes=changes)

    def deactivate_missing(
        self,
        source: str,
        seen_source_ids: Iterable[str],
        seen_at: datetime | None = None,
        scope: SearchQuery | None = None,
    ) -> list[str]:
        """Mark active listings of `source` that were NOT seen in a fetch as inactive.

        `scope` is the query of the fetch: a fetch that only asked for Berlin must not
        deactivate listings in Potsdam. Returns the ids of the listings that went
        offline. Each gets a snapshot with the status change, so "relisted" can be
        derived later.
        """
        seen_at = seen_at or utcnow()
        seen = set(seen_source_ids)
        gone: list[str] = []
        with self._session() as session:
            rows = session.scalars(
                select(ListingRow).where(ListingRow.source == source, ListingRow.is_active)
            ).all()
            for row in rows:
                if row.source_listing_id in seen:
                    continue
                if scope is not None and not scope.matches(_row_to_listing(row)):
                    continue
                row.is_active = False
                session.add(
                    ListingSnapshotRow(
                        listing_id=row.id,
                        seen_at=seen_at,
                        price=row.price,
                        changes={"is_active": {"old": True, "new": False}},
                    )
                )
                gone.append(row.id)
            session.commit()
        return gone

    def get_listing(self, listing_id: str) -> Listing | None:
        with self._session() as session:
            row = session.get(ListingRow, listing_id)
            return _row_to_listing(row) if row else None

    def get_listing_by_source(self, source: str, source_listing_id: str) -> Listing | None:
        with self._session() as session:
            row = session.scalar(
                select(ListingRow).where(
                    ListingRow.source == source,
                    ListingRow.source_listing_id == source_listing_id,
                )
            )
            return _row_to_listing(row) if row else None

    def list_listings(
        self,
        offer_type: OfferType | None = None,
        property_type: PropertyType | None = None,
        city: str | None = None,
        source: str | None = None,
        active_only: bool = False,
    ) -> list[Listing]:
        query = select(ListingRow).order_by(ListingRow.first_seen.desc(), ListingRow.id)
        if offer_type is not None:
            query = query.where(ListingRow.offer_type == offer_type.value)
        if property_type is not None:
            query = query.where(ListingRow.property_type == property_type.value)
        if city is not None:
            query = query.where(ListingRow.city == city)
        if source is not None:
            query = query.where(ListingRow.source == source)
        if active_only:
            query = query.where(ListingRow.is_active)
        with self._session() as session:
            return [_row_to_listing(row) for row in session.scalars(query)]

    def count_listings(self) -> int:
        with self._session() as session:
            return session.scalar(select(func.count()).select_from(ListingRow)) or 0

    # --- snapshots -----------------------------------------------------------------

    def list_snapshots(self, listing_id: str) -> list[ListingSnapshot]:
        with self._session() as session:
            rows = session.scalars(
                select(ListingSnapshotRow)
                .where(ListingSnapshotRow.listing_id == listing_id)
                .order_by(ListingSnapshotRow.seen_at, ListingSnapshotRow.id)
            )
            return [_row_to_snapshot(row) for row in rows]

    def snapshots_by_listing(self) -> dict[str, list[ListingSnapshot]]:
        """All snapshots grouped by listing id (one query instead of one per listing)."""
        grouped: dict[str, list[ListingSnapshot]] = defaultdict(list)
        with self._session() as session:
            rows = session.scalars(
                select(ListingSnapshotRow).order_by(
                    ListingSnapshotRow.seen_at, ListingSnapshotRow.id
                )
            )
            for row in rows:
                grouped[row.listing_id].append(_row_to_snapshot(row))
        return dict(grouped)

    # --- area references -----------------------------------------------------------

    def add_area_references(self, references: Iterable[AreaReference]) -> int:
        rows = [
            AreaReferenceRow(
                area_key=ref.area_key,
                metric=ref.metric.value,
                property_type=ref.property_type.value if ref.property_type else None,
                segment=ref.segment,
                value=ref.value,
                low=ref.low,
                high=ref.high,
                source=ref.source.value,
                valid_from=ref.valid_from,
                valid_to=ref.valid_to,
                note=ref.note,
                sample_size=ref.sample_size,
            )
            for ref in references
        ]
        with self._session() as session:
            session.add_all(rows)
            session.commit()
        return len(rows)

    def list_area_references(
        self,
        metric: AreaMetric | None = None,
        source: ReferenceSource | None = None,
        area_key: str | None = None,
    ) -> list[AreaReference]:
        query = select(AreaReferenceRow).order_by(
            AreaReferenceRow.area_key, AreaReferenceRow.metric, AreaReferenceRow.source
        )
        if metric is not None:
            query = query.where(AreaReferenceRow.metric == metric.value)
        if source is not None:
            query = query.where(AreaReferenceRow.source == source.value)
        if area_key is not None:
            query = query.where(AreaReferenceRow.area_key == area_key)
        with self._session() as session:
            return [_row_to_reference(row) for row in session.scalars(query)]

    def delete_area_references(self, source: ReferenceSource | None = None) -> int:
        statement = delete(AreaReferenceRow)
        if source is not None:
            statement = statement.where(AreaReferenceRow.source == source.value)
        with self._session() as session:
            deleted = session.execute(statement).rowcount
            session.commit()
        return deleted

    # --- overrides -----------------------------------------------------------------

    def set_override(self, override: Override) -> None:
        """Create or replace the override for (listing, field)."""
        with self._session() as session:
            row = session.scalar(
                select(OverrideRow).where(
                    OverrideRow.listing_id == override.listing_id,
                    OverrideRow.field == override.field.value,
                )
            )
            if row is None:
                session.add(
                    OverrideRow(
                        listing_id=override.listing_id,
                        field=override.field.value,
                        value=override.value,
                        created_at=override.created_at,
                        note=override.note,
                    )
                )
            else:
                row.value = override.value
                row.created_at = override.created_at
                row.note = override.note
            session.commit()

    def delete_override(self, listing_id: str, field: OverrideField) -> bool:
        with self._session() as session:
            deleted = session.execute(
                delete(OverrideRow).where(
                    OverrideRow.listing_id == listing_id, OverrideRow.field == field.value
                )
            ).rowcount
            session.commit()
        return deleted > 0

    def list_overrides(self, listing_id: str | None = None) -> list[Override]:
        query = select(OverrideRow).order_by(OverrideRow.listing_id, OverrideRow.field)
        if listing_id is not None:
            query = query.where(OverrideRow.listing_id == listing_id)
        with self._session() as session:
            return [_row_to_override(row) for row in session.scalars(query)]

    def overrides_by_listing(self) -> dict[str, list[Override]]:
        grouped: dict[str, list[Override]] = defaultdict(list)
        for override in self.list_overrides():
            grouped[override.listing_id].append(override)
        return dict(grouped)

    # --- fetch log -----------------------------------------------------------------

    def add_fetch_run(self, run: FetchRun) -> None:
        with self._session() as session:
            session.add(FetchRunRow(**run.model_dump()))
            session.commit()

    def list_fetch_runs(self, limit: int = 20, source: str | None = None) -> list[FetchRun]:
        """The most recent runs first."""
        query = select(FetchRunRow).order_by(FetchRunRow.id.desc()).limit(limit)
        if source is not None:
            query = query.where(FetchRunRow.source == source)
        fields = tuple(FetchRun.model_fields)
        with self._session() as session:
            return [
                FetchRun(**{name: getattr(row, name) for name in fields})
                for row in session.scalars(query)
            ]

    def count_fetch_runs(self, source: str) -> int:
        with self._session() as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(FetchRunRow)
                    .where(FetchRunRow.source == source)
                )
                or 0
            )
