"""Glue between Streamlit and the rest of the app.

Streamlit re-runs a page's script from top to bottom on every interaction. Two tools
keep that cheap and consistent:
- `st.cache_resource` keeps ONE repository (database connection) per database file,
- `st.session_state` keeps the current assumptions while the browser tab is open.

Metrics are NOT cached: they are recalculated on every run, which is exactly why a
changed assumption shows up everywhere immediately (SPEC §6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from immo.core.assumptions import Assumptions, load_assumptions
from immo.core.estimates import MarketIndex
from immo.core.evaluate import BuyEvaluation, RentalEvaluation, evaluate_buy, evaluate_rental
from immo.core.models import (
    AreaReference,
    Listing,
    ListingSnapshot,
    OfferType,
    Override,
    utcnow,
)
from immo.paths import db_path
from immo.storage.db import make_engine
from immo.storage.repository import Repository

DETAIL_KEY = "detail_listing_id"


@st.cache_resource
def _repository(path: str) -> Repository:
    # `path` is only the cache key: a different database file gets its own repository.
    return Repository(make_engine())


def get_repo() -> Repository:
    return _repository(str(db_path()))


def get_assumptions() -> Assumptions:
    if "assumptions" not in st.session_state:
        st.session_state["assumptions"] = load_assumptions()
    return st.session_state["assumptions"]


def set_assumptions(assumptions: Assumptions) -> None:
    st.session_state["assumptions"] = assumptions


def chart_theme() -> str:
    """'light' or 'dark', following the theme the browser currently shows."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # theme info is unavailable in tests / very old browsers
        return "light"


@dataclass
class Market:
    """Everything loaded from the database for one script run."""

    listings: list[Listing]
    references: list[AreaReference]
    overrides: dict[str, list[Override]]
    snapshots: dict[str, list[ListingSnapshot]]
    index: MarketIndex
    now: datetime

    @property
    def is_empty(self) -> bool:
        return not self.listings

    def of_type(self, offer_type: OfferType) -> list[Listing]:
        return [x for x in self.listings if x.offer_type is offer_type]


def load_market(assumptions: Assumptions) -> Market:
    repo = get_repo()
    listings = repo.list_listings()
    references = repo.list_area_references()
    now = utcnow()
    return Market(
        listings=listings,
        references=references,
        overrides=repo.overrides_by_listing(),
        snapshots=repo.snapshots_by_listing(),
        index=MarketIndex(
            listings,
            references,
            min_samples=assumptions.min_samples_own_listings,
            on_date=now.date(),
        ),
        now=now,
    )


def evaluate_buy_listing(
    listing: Listing, market: Market, assumptions: Assumptions
) -> BuyEvaluation:
    return evaluate_buy(
        listing,
        market.index,
        assumptions,
        overrides=market.overrides.get(listing.id, ()),
        snapshots=market.snapshots.get(listing.id, []),
        now=market.now,
    )


def evaluate_all_buy(market: Market, assumptions: Assumptions) -> list[BuyEvaluation]:
    return [
        evaluate_buy_listing(listing, market, assumptions)
        for listing in market.of_type(OfferType.KAUF)
    ]


def evaluate_all_rentals(market: Market) -> list[RentalEvaluation]:
    return [
        evaluate_rental(
            listing, market.index, snapshots=market.snapshots.get(listing.id, []), now=market.now
        )
        for listing in market.of_type(OfferType.MIETE)
    ]


def show_empty_database_hint() -> None:
    st.info(
        "The database is empty. Load the sample data first:\n\n"
        "```bash\nuv run python -m immo.cli seed --reset\n```"
    )


def show_chart(figure) -> None:
    """Render a Plotly figure with our own styling (theme=None keeps Streamlit from
    overriding legend position, margins and colours)."""
    st.plotly_chart(figure, width="stretch", theme=None, config={"displayModeBar": False})
