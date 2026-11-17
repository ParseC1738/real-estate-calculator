"""The ingest pipeline (SPEC §9):

    fetch -> normalize -> validate -> upsert + snapshot -> deactivate missing

It works with any `SourceAdapter` and knows nothing about where the data comes from.
One broken listing never stops a run: it is skipped and reported in the result.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from immo.core.history import UpsertOutcome
from immo.core.models import FetchRun, Listing, SearchQuery, utcnow
from immo.sources.base import SourceAdapter
from immo.storage.repository import Repository

MAX_LOGGED_ERRORS = 50


def _error_text(error: Exception) -> str:
    if isinstance(error, ValidationError):
        # pydantic's full message is long; keep "field: reason" per problem
        return "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'listing'}: {e['msg']}"
            for e in error.errors()
        )
    return str(error)


def run_ingest(
    adapter: SourceAdapter,
    repo: Repository,
    query: SearchQuery | None = None,
    *,
    now: datetime | None = None,
    deactivate_missing: bool = True,
) -> FetchRun:
    """Run one adapter through the pipeline, store the result and log the run.

    `deactivate_missing=True` is right for a source that always delivers everything
    that is online (a portal search). Use False for partial data such as a CSV file
    with a few hand-picked listings.
    """
    query = query or SearchQuery()
    started = now or utcnow()
    run = FetchRun(source=adapter.name, started_at=started, finished_at=started)

    # 1. fetch – if the source itself fails, nothing is changed in the database
    try:
        raw_listings = list(adapter.fetch(query))
    except Exception as error:  # a source can fail in many ways (file, network, format)
        run.errors.append(f"fetch failed: {_error_text(error)}")
        run.note = "fetch failed, database unchanged"
        return _finish(run, repo, now)
    run.fetched = len(raw_listings)

    # 2. normalize + validate – bad listings are collected, good ones continue
    listings: list[Listing] = []
    seen_ids: set[str] = set()
    for raw in raw_listings:
        # a listing that is present but invalid is still "seen": do not mark it gone
        seen_ids.add(raw.source_listing_id)
        try:
            listing = adapter.normalize(raw)
        except ValueError as error:  # includes pydantic.ValidationError
            run.errors.append(f"{raw.source_listing_id}: {_error_text(error)}")
            continue
        if not query.matches(listing):
            continue
        seen_ids.add(listing.source_listing_id)
        listings.append(listing.model_copy(update={"source": adapter.name}))

    # 3. upsert + snapshot (one transaction)
    for result in repo.upsert_listings(listings, started):
        if result.outcome is UpsertOutcome.NEW:
            run.new += 1
        elif result.outcome is UpsertOutcome.CHANGED:
            run.changed += 1
        elif result.outcome is UpsertOutcome.RELISTED:
            run.relisted += 1
        else:
            run.unchanged += 1

    # 4. deactivate what the source no longer lists
    if deactivate_missing:
        if listings:
            run.gone = len(repo.deactivate_missing(adapter.name, seen_ids, started, scope=query))
        else:
            # An empty result almost always means a broken source, not an empty market.
            run.note = "no valid listings fetched, nothing was marked as gone"
    return _finish(run, repo, now)


def _finish(run: FetchRun, repo: Repository, now: datetime | None) -> FetchRun:
    run.finished_at = now or utcnow()
    logged = run.model_copy(update={"errors": run.errors[:MAX_LOGGED_ERRORS]})
    repo.add_fetch_run(logged)
    return run
