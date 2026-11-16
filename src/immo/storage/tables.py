"""Database tables (SQLAlchemy 2.0 declarative style).

These classes describe *how data is stored*. They are deliberately separate from the
Pydantic models in `core/models.py`, which describe *what the data means*. Only
`repository.py` converts between the two, so the rest of the app never sees a table row.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ListingRow(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "source_listing_id", name="uq_listing_source_id"),
        Index("ix_listing_offer_city", "offer_type", "city"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_listing_id: Mapped[str] = mapped_column(String(100))
    url: Mapped[str | None]
    offer_type: Mapped[str] = mapped_column(String(10))
    property_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str]
    city: Mapped[str]
    district: Mapped[str | None]
    postal_code: Mapped[str] = mapped_column(String(10))
    address: Mapped[str | None]
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    price: Mapped[float]
    living_area_m2: Mapped[float | None]
    plot_area_m2: Mapped[float | None]
    rooms: Mapped[float | None]
    units: Mapped[int | None]
    year_built: Mapped[int | None]
    condition: Mapped[str | None]
    energy_class: Mapped[str | None]
    actual_rent_month: Mapped[float | None]
    hausgeld_month: Mapped[float | None]
    commission_pct: Mapped[float | None]
    is_rented: Mapped[bool | None]
    first_seen: Mapped[datetime]
    last_seen: Mapped[datetime]
    is_active: Mapped[bool] = mapped_column(default=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # derived from the listing on every upsert; prepared for later deduplication
    fingerprint: Mapped[str | None] = mapped_column(String(16), index=True)


class ListingSnapshotRow(Base):
    __tablename__ = "listing_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    seen_at: Mapped[datetime]
    price: Mapped[float]
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AreaReferenceRow(Base):
    __tablename__ = "area_references"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    area_key: Mapped[str] = mapped_column(index=True)
    metric: Mapped[str] = mapped_column(String(20))
    property_type: Mapped[str | None] = mapped_column(String(20))
    segment: Mapped[str | None]
    value: Mapped[float]
    low: Mapped[float | None]
    high: Mapped[float | None]
    source: Mapped[str] = mapped_column(String(30))
    valid_from: Mapped[date]
    valid_to: Mapped[date | None]
    note: Mapped[str] = mapped_column(default="")
    sample_size: Mapped[int | None]


class OverrideRow(Base):
    __tablename__ = "overrides"
    __table_args__ = (UniqueConstraint("listing_id", "field", name="uq_override_field"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    listing_id: Mapped[str] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(30))
    value: Mapped[float]
    created_at: Mapped[datetime]
    note: Mapped[str] = mapped_column(default="")
