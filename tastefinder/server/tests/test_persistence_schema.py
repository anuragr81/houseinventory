"""
tests/test_persistence_schema.py
--------------------------------
Structural assertions about what the database may and may not hold, plus the
Phase 2 gate check that the migration applies and rolls back.

These are deliberately assertions of *absence*: docs/04_PRIVACY_INVARIANTS.md
requires that "MUST NOT exist" is tested rather than merely not-yet-built, and
the persistence layer is where that goes wrong first.
"""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.persistence.tables import Base

SERVER_ROOT = Path(__file__).resolve().parent.parent

# Columns that would indicate rating data sitting on a row.
RATING_COLUMNS = {"facet_scores", "facet_id", "mean", "variance", "score", "rating"}

# Fields that would make a row identifiable to a person.
IDENTIFYING_COLUMNS = {"user_id"}


def test_no_raw_contribution_table_exists() -> None:
    """RawContribution is never persisted. See docs/02_DOMAIN_MODEL.md."""
    names = set(Base.metadata.tables)
    assert not any("contribution" in name for name in names), names


def test_no_table_holds_user_id_beside_rating_data() -> None:
    """INV-RAW-2: no persisted row may pair a user with their ratings."""
    offenders = []
    for name, table in Base.metadata.tables.items():
        columns = {c.name for c in table.columns}
        if columns & IDENTIFYING_COLUMNS and columns & RATING_COLUMNS:
            offenders.append((name, sorted(columns)))
    assert offenders == []


def test_no_persisted_table_has_a_free_text_column() -> None:
    """INV-RAW-3: free text is consumed at normalisation, never stored."""
    offenders = []
    for name, table in Base.metadata.tables.items():
        for column in table.columns:
            if column.name in {"free_text", "review_text", "comment", "notes"}:
                offenders.append(f"{name}.{column.name}")
    assert offenders == []


def test_place_ref_has_no_display_columns() -> None:
    """INV-CACHE-1: only place_id indefinitely; coordinates time-bounded."""
    columns = {c.name for c in Base.metadata.tables["place_ref"].columns}
    forbidden = {"name", "address", "formatted_address", "rating", "photos",
                 "opening_hours", "reviews", "review_text"}
    assert not columns & forbidden
    assert columns == {"place_id", "last_refreshed_at", "cached_lat", "cached_lng",
                       "coords_cached_at"}


def test_google_import_job_has_no_signed_url_column() -> None:
    """INV-CONSENT-3: signed URLs live in memory for the download only."""
    columns = {c.name for c in Base.metadata.tables["google_import_job"].columns}
    assert not any("signed_url" in c and c != "signed_url_expires_at" for c in columns)
    assert "signed_url" not in columns


def test_community_aggregate_carries_no_user_reference() -> None:
    columns = {c.name for c in Base.metadata.tables["community_aggregate"].columns}
    assert "user_id" not in columns


def test_expected_tables_and_nothing_more() -> None:
    assert set(Base.metadata.tables) == {
        "user",
        "identity_link",
        "session_token",
        "community",
        "community_membership",
        "facet",
        "consent_record",
        "google_import_job",
        "place_ref",
        "community_aggregate",
        "facet_stat",
    }


def test_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    """GATE 2: upgrade head then downgrade base against a scratch SQLite DB."""
    db = tmp_path / "scratch.db"
    url = f"sqlite+pysqlite:///{db}"

    def alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
            cwd=SERVER_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    alembic("upgrade", "head")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert "community_aggregate" in tables
    assert not any("contribution" in t for t in tables)

    alembic("downgrade", "base")
    engine = create_engine(url)
    remaining = set(inspect(engine).get_table_names())
    engine.dispose()
    assert remaining <= {"alembic_version"}


def test_migration_matches_the_models(tmp_path: Path) -> None:
    """A migrated database and Base.metadata must agree on table names.

    Guards the usual drift: a model edited without a matching migration.
    """
    db = tmp_path / "compare.db"
    url = f"sqlite+pysqlite:///{db}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", "upgrade", "head"],
        cwd=SERVER_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(url)
    migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    engine.dispose()
    assert migrated == set(Base.metadata.tables)
