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

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

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
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_url_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    last_refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cached_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    cached_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    coords_cached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
