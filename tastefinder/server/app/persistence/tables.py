"""
app/persistence/tables.py
-------------------------
SQLAlchemy tables for the persisted entities in docs/02_DOMAIN_MODEL.md.

Note the asymmetry, which is the whole point of the design: User,
CommunityMembership, Community, Facet, ConsentRecord, GoogleImportJob,
PlaceRef, CommunityAggregate and FacetStat are persisted. **RawContribution is
not, and has no table here.** See "RawContribution persistence" in
docs/02_DOMAIN_MODEL.md.

Column types are provider-agnostic (docs/01_STACK_DECISIONS.md): `Uuid` maps to
native UUID on PostgreSQL and CHAR(32) on SQLite, so the same schema serves
tests and deployment.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import (
    CommunityStatus,
    ConsentScope,
    FacetValueType,
    ImportJobState,
    Tier,
)


class UtcDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime that survives the round trip on SQLite too.

    SQLite has no native datetime type, so `DateTime(timezone=True)` writes an
    aware value and reads back a **naive** one. That is not cosmetic: comparing
    a naive stored timestamp with an aware `now` raises TypeError, which is
    exactly what `PlaceRef.needs_refresh` and `ConsentRecord.is_active` do the
    moment their inputs come from the database. PostgreSQL has no such
    problem, so without this the two dialects disagree about a core domain
    type and the disagreement only shows up wherever the schema is not the one
    the tests ran against.

    MySQL needs the other half of the same treatment. Its `DATETIME` has no
    timezone at all -- `timezone=True` is accepted and ignored by the dialect
    -- and its drivers will not bind an aware value. So the conversion to UTC
    happens here and the offset is dropped *deliberately* before binding,
    which is safe precisely because the value is known to be UTC by then. The
    read side reattaches it.

    Naive values are rejected on the way in rather than assumed to be UTC:
    there is no way to know what zone an unlabelled timestamp meant, and
    guessing produces data that looks fine and is wrong.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "Naive datetime passed to a UtcDateTime column. Attach a timezone "
                "at the point the value is created; this layer will not guess one."
            )
        as_utc = value.astimezone(UTC)
        if dialect.name == "mysql":
            # MySQL DATETIME stores no offset and its drivers reject an aware
            # value. Dropping tzinfo here loses nothing: the value is UTC, and
            # process_result_value says so again on the way back.
            return as_utc.replace(tzinfo=None)
        return as_utc

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Declarative base. `Base.metadata` is what Alembic autogenerates from."""


class UserTable(Base):
    """Pseudonymous user.

    Deliberately has no name, email, Google account ID, or phone number. Adding
    any strong identifier here is a breach of the model in CLAUDE.md and needs
    the owner's decision, not an implementer's.
    """

    __tablename__ = "user"

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class CommunityTable(Base):
    __tablename__ = "community"

    community_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    # No default and no server_default: OPEN-1 says no safe value exists and it
    # must be set explicitly per community.
    min_cohort_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CommunityStatus] = mapped_column(
        Enum(CommunityStatus, native_enum=False, length=16), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    facets: Mapped[list["FacetTable"]] = relationship(
        back_populates="community", cascade="all, delete-orphan", passive_deletes=True
    )


class CommunityMembershipTable(Base):
    __tablename__ = "community_membership"

    membership_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    community_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("community.community_id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[Tier] = mapped_column(Enum(Tier, native_enum=False, length=16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class FacetTable(Base):
    """Owned by a community: deleting a community deletes its facets."""

    __tablename__ = "facet"

    facet_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    community_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("community.community_id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[FacetValueType] = mapped_column(
        Enum(FacetValueType, native_enum=False, length=16), nullable=False
    )
    scale_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    scale_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    community: Mapped[CommunityTable] = relationship(back_populates="facets")


class ConsentRecordTable(Base):
    """Append-only (INV-CONSENT-2).

    The database enforces shape, not the append-only rule: revocation writes
    revoked_at and nothing updates scope/granted_at or deletes a row. That
    constraint is enforced in the repository layer, which does not exist yet.
    """

    __tablename__ = "consent_record"

    consent_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope: Mapped[ConsentScope] = mapped_column(
        Enum(ConsentScope, native_enum=False, length=32), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class GoogleImportJobTable(Base):
    """Archive lifecycle state.

    Has no signed-URL column, by requirement: signed URLs are held in memory
    for the duration of the download only (INV-CONSENT-3). Only the expiry
    instant is recorded.
    """

    __tablename__ = "google_import_job"

    job_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    consent_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("consent_record.consent_id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[ImportJobState] = mapped_column(
        Enum(ImportJobState, native_enum=False, length=16), nullable=False
    )
    initiated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    signed_url_expires_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlaceRefTable(Base):
    """Pointer into Google's catalogue plus refresh bookkeeping.

    Must not gain columns for name, address, rating, photos, opening hours, or
    review text (INV-CACHE-1), and must not become searchable by anything other
    than an exact place_id (INV-CACHE-3).
    """

    __tablename__ = "place_ref"

    place_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_refreshed_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    cached_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    cached_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_cached_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime(), nullable=True
    )


class CommunityAggregateTable(Base):
    """The durable product. Carries no user_id, by construction (INV-RAW-2)."""

    __tablename__ = "community_aggregate"
    __table_args__ = (
        CheckConstraint("cohort_size >= 0", name="ck_community_aggregate_cohort_size_non_negative"),
    )

    aggregate_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    community_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("community.community_id", ondelete="CASCADE"), nullable=False, index=True
    )
    place_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("place_ref.place_id", ondelete="RESTRICT"), nullable=False
    )
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    noise_epsilon: Mapped[float | None] = mapped_column(Float, nullable=True)

    facet_stats: Mapped[list["FacetStatTable"]] = relationship(
        back_populates="aggregate", cascade="all, delete-orphan", passive_deletes=True
    )


class FacetStatTable(Base):
    """Owned by an aggregate (composition). Placeholder shape -- see OPEN-3."""

    __tablename__ = "facet_stat"

    aggregate_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("community_aggregate.aggregate_id", ondelete="CASCADE"),
        primary_key=True,
    )
    facet_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("facet.facet_id", ondelete="CASCADE"), primary_key=True
    )
    mean: Mapped[float] = mapped_column(Float, nullable=False)
    variance: Mapped[float] = mapped_column(Float, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)

    aggregate: Mapped[CommunityAggregateTable] = relationship(back_populates="facet_stats")


# Deliberately absent: a RawContribution table.
#
# RawContribution is the only structure carrying identified per-person data.
# It is constructed in memory, folded into a CommunityAggregate, and dropped.
# Nothing writes it to a database. Adding a table here -- even a "temporary"
# working one with a folded_at column -- would reintroduce exactly the
# user_id-next-to-facet-data row that INV-RAW-2 exists to forbid, and is a
# decision for the project owner rather than an implementer.
