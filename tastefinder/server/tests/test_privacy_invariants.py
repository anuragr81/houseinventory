"""
tests/test_privacy_invariants.py
--------------------------------
Every invariant in docs/04_PRIVACY_INVARIANTS.md, as an executable test.

Reading rules, from that document:

- Every test name contains the ID of the invariant it covers, so the mapping
  can be checked by grepping rather than by trust.
- None of these may be skipped, xfailed, or relaxed to make a build pass. A
  failure here means the code is wrong.
- Where an invariant says something MUST NOT exist, the test asserts absence.
  "It hasn't been built yet" is not a pass; the test has to be the thing that
  fails when somebody builds it.

Several invariants constrain layers that do not exist yet (routes beyond
/health, any repository at all). Those are tested by introspecting what *is*
there -- the mapped tables, the generated OpenAPI schema, and the source tree
under app/ -- so the assertion starts failing on the commit that introduces the
breach rather than waiting for a suite to be written later.
"""

import ast
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.enums import (
    CommunityStatus,
    Confidence,
    ConsentScope,
    ContributionSource,
    FacetValueType,
    ImportJobState,
)
from app.domain.facet_catalogue import (
    SCOREABLE_VALUE_TYPES,
    FacetCatalogue,
    FacetCatalogueError,
    FacetDefinition,
    UnknownFacetKeyError,
)
from app.domain.models import (
    CohortBucketing,
    Community,
    CommunityAggregate,
    ConsentRecord,
    FacetStat,
    GoogleImportJob,
    PlaceRef,
    PublicAggregateView,
    RawContribution,
)
from app.main import create_app
from app.persistence.tables import Base
from app.services import consent as consent_service
from app.services.aggregation import (
    MismatchedAggregateError,
    StreamingAggregator,
    is_purged,
)
from app.services.community_founding import FoundingContribution, found_community
from app.services.consent import Decision, Operation, RefusalReason
from app.services.place_cache import coordinates, purge_expired_coordinates
from app.services.privacy_gate import NoiseConfig, PrivacyGate

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
COORD_RETENTION = timedelta(days=30)
BUCKETING = CohortBucketing(boundaries=(0, 10, 25, 50, 100))

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

COMMUNITY_ID = uuid4()
PLACE_ID = "ChIJ_invariant_test_place"
FACET_A = uuid4()
FACET_B = uuid4()


# ── Fixtures and helpers ──────────────────────────────────────────────────────


def _aggregate(cohort_size: int = 0, **stats: FacetStat) -> CommunityAggregate:
    return CommunityAggregate(
        community_id=COMMUNITY_ID,
        place_id=PLACE_ID,
        facet_stats={stat.facet_id: stat for stat in stats.values()},
        cohort_size=cohort_size,
        last_updated_at=NOW,
    )


def _contribution(
    *,
    user_id: UUID | None = None,
    scores: dict[UUID, float] | None = None,
    free_text: str | None = None,
    community_id: UUID | None = None,
    place_id: str = PLACE_ID,
) -> RawContribution:
    return RawContribution(
        user_id=user_id or uuid4(),
        community_id=community_id or COMMUNITY_ID,
        place_id=place_id,
        facet_scores=scores if scores is not None else {FACET_A: 4.0},
        free_text=free_text,
        source=ContributionSource.DIRECT,
        confidence=Confidence.STATED,
        captured_at=NOW,
    )


def _gate(threshold: int = 10) -> PrivacyGate:
    return PrivacyGate(min_cohort_threshold=threshold, bucketing=BUCKETING)


def _app_sources() -> list[tuple[Path, str]]:
    """Every Python source file under app/, with its text."""
    return [(path, path.read_text()) for path in sorted(APP_ROOT.rglob("*.py"))]


def _all_function_defs() -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for path, text in _app_sources():
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found.append((path, node))
    return found


def _routes() -> list[tuple[str, frozenset[str]]]:
    """(path, methods) for every route the application actually exposes."""
    routes = []
    for route in create_app().routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        routes.append((path, frozenset(getattr(route, "methods", None) or set())))
    return routes


# ══ Group RAW ═════════════════════════════════════════════════════════════════


def test_INV_RAW_1_contribution_does_not_survive_folding() -> None:
    """Folded contributions are unreadable afterwards, through any path."""
    user_id = uuid4()
    contribution = _contribution(
        user_id=user_id,
        scores={FACET_A: 4.25, FACET_B: 1.5},
        free_text="the tannins were extraordinary and my usual table was free",
    )
    folded = StreamingAggregator().fold(contribution, _aggregate(), NOW)

    assert folded.cohort_size == 1
    # The object the caller still holds carries nothing identified.
    assert is_purged(contribution)
    assert contribution.user_id != user_id
    assert contribution.facet_scores == {}
    assert contribution.free_text is None
    # Nothing was written anywhere: there is no table to look it up in.
    assert "raw_contribution" not in Base.metadata.tables


def test_INV_RAW_1_no_repository_can_retrieve_a_contribution() -> None:
    """No lookup-by-id/user/community/place path exists for contributions.

    Asserted as absence over the source tree, per the rules in docs/04: the
    retrieval paths the invariant names must not merely be unbuilt.
    """
    offenders = [
        (path.name, node.name)
        for path, node in _all_function_defs()
        if "contribution" in node.name.lower()
        and any(verb in node.name.lower() for verb in ("get", "find", "list", "load", "fetch"))
    ]
    assert offenders == [], f"Contribution retrieval path(s) exist: {offenders}"


def test_INV_RAW_2_no_persisted_table_holds_user_id_beside_rating_data() -> None:
    rating_columns = {"facet_scores", "facet_id", "mean", "variance", "score", "rating"}
    for name, table in Base.metadata.tables.items():
        columns = set(table.columns.keys())
        if "user_id" in columns:
            assert not (columns & rating_columns), (
                f"Table {name!r} holds user_id beside rating data: "
                f"{sorted(columns & rating_columns)}"
            )


def test_INV_RAW_2_no_function_takes_a_user_id_and_returns_contributions() -> None:
    """No query, index, ORM relationship or method is user-indexed over ratings."""
    offenders = []
    for path, node in _all_function_defs():
        params = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
        if "user_id" not in params:
            continue
        returns = ast.unparse(node.returns) if node.returns else ""
        if "Contribution" in returns or "FacetStat" in returns:
            offenders.append((path.name, node.name, returns))
    assert offenders == [], f"User-indexed rating lookups exist: {offenders}"


def test_INV_RAW_2_no_orm_relationship_reaches_ratings_from_a_user() -> None:
    user_table = Base.metadata.tables["user"]
    inbound = [fk for table in Base.metadata.tables.values() for fk in table.foreign_keys]
    referencing_user = {
        fk.parent.table.name for fk in inbound if fk.column.table is user_table
    }
    rating_tables = {"facet_stat", "community_aggregate"}
    assert not (referencing_user & rating_tables), (
        f"Rating tables reference user: {sorted(referencing_user & rating_tables)}"
    )


def test_INV_RAW_3_free_text_is_not_retained_on_any_persisted_model() -> None:
    prose_columns = {"free_text", "review", "review_text", "comment", "notes", "body"}
    for name, table in Base.metadata.tables.items():
        assert not (set(table.columns.keys()) & prose_columns), (
            f"Table {name!r} has a free-text column"
        )


def test_INV_RAW_3_public_view_has_no_field_capable_of_holding_prose() -> None:
    """The only strings that leave are a place identifier and a bucket label.

    Both are bounded-vocabulary values, not prose. Any *other* string field
    appearing on this model is the failure this test exists to catch.
    """
    string_fields = {
        name
        for name, field in PublicAggregateView.model_fields.items()
        if field.annotation is str
    }
    assert string_fields == {"place_id", "cohort_size_bucket"}


def test_INV_RAW_3_free_text_is_dropped_by_folding() -> None:
    contribution = _contribution(free_text="a distinctive sentence nobody else would write")
    folded = StreamingAggregator().fold(contribution, _aggregate(), NOW)
    assert contribution.free_text is None
    assert "free_text" not in folded.model_dump()


def test_INV_RAW_4_handled_failure_logs_no_contribution_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_id = uuid4()
    secret_prose = "ZZQX-distinctive-prose-marker"
    contribution = _contribution(
        user_id=user_id,
        scores={FACET_A: 7.7654321},
        free_text=secret_prose,
        community_id=uuid4(),  # forces a handled mismatch
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(MismatchedAggregateError) as raised:
            StreamingAggregator().fold(contribution, _aggregate(), NOW)
        # Emulate the handler a route would have: log the caught error.
        logging.getLogger("app.api").warning("Contribution rejected: %s", raised.value)

    captured = caplog.text + str(raised.value)
    assert str(user_id) not in captured
    assert secret_prose not in captured
    assert "7.7654321" not in captured


def test_INV_RAW_4_unhandled_failure_logs_no_contribution_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An error tracker capturing the traceback must not capture the payload."""
    user_id = uuid4()
    secret_prose = "ZZQX-unhandled-prose-marker"
    contribution = _contribution(
        user_id=user_id, scores={FACET_A: float("nan")}, free_text=secret_prose
    )
    with caplog.at_level(logging.DEBUG):
        try:
            StreamingAggregator().fold(contribution, _aggregate(), NOW)
        except Exception:
            logging.getLogger("app.api").exception("Unhandled failure during folding")

    assert str(user_id) not in caplog.text
    assert secret_prose not in caplog.text


def test_INV_RAW_4_successful_fold_logs_no_contribution_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_id = uuid4()
    secret_prose = "ZZQX-success-prose-marker"
    contribution = _contribution(
        user_id=user_id, scores={FACET_A: 3.1415926}, free_text=secret_prose
    )
    with caplog.at_level(logging.DEBUG):
        StreamingAggregator().fold(contribution, _aggregate(), NOW)

    assert caplog.text, "the aggregator logs nothing at all, so this test proves nothing"
    assert str(user_id) not in caplog.text
    assert secret_prose not in caplog.text
    assert "3.1415926" not in caplog.text


# ══ Group EXPOSE ══════════════════════════════════════════════════════════════


def test_INV_EXPOSE_1_no_individual_read_route_exists() -> None:
    """No route returns data attributable to an identified individual."""
    forbidden_fragments = ("contribution", "/users/", "/me", "history", "profile")
    offenders = [
        (path, sorted(methods))
        for path, methods in _routes()
        if any(fragment in path.lower() for fragment in forbidden_fragments)
    ]
    assert offenders == [], f"Individual read route(s) exist: {offenders}"


def test_INV_EXPOSE_1_openapi_declares_no_individual_retrieval_operation() -> None:
    schema = create_app().openapi()
    offenders = [
        path
        for path in schema.get("paths", {})
        if "contribution" in path.lower() or "/users/" in path.lower()
    ]
    assert offenders == [], f"OpenAPI advertises individual retrieval: {offenders}"


def test_INV_EXPOSE_2_exact_cohort_size_is_never_published() -> None:
    stat = FacetStat(facet_id=FACET_A, mean=4.0, variance=1.0, n=37)
    aggregate = _aggregate(cohort_size=37, a=stat)
    view = _gate(threshold=10).public_view(aggregate)
    assert view is not None

    payload = view.model_dump()
    assert "cohort_size" not in payload
    assert 37 not in payload.values()
    assert view.cohort_size_bucket == "25-49"
    # And not smuggled in as a string anywhere in the serialised form.
    assert '"cohort_size"' not in view.model_dump_json()


def test_INV_EXPOSE_2_public_view_model_has_no_exact_count_field() -> None:
    assert "cohort_size" not in PublicAggregateView.model_fields
    assert "cohort_size_bucket" in PublicAggregateView.model_fields


def test_INV_EXPOSE_3_suppressed_is_indistinguishable_from_absent() -> None:
    gate = _gate(threshold=10)
    below_threshold = _aggregate(cohort_size=9)

    suppressed = gate.public_view(below_threshold)
    absent = gate.public_view(None)

    assert suppressed is absent is None
    # A route rendering these cannot tell them apart, because there is nothing
    # to tell apart -- same value, same type.
    assert repr(suppressed) == repr(absent)


def test_INV_EXPOSE_3_suppressed_slice_is_omitted_without_a_marker() -> None:
    """Collection reads drop suppressed slices silently: no count, no placeholder."""
    gate = _gate(threshold=10)
    published = _aggregate(cohort_size=40)
    suppressed = _aggregate(cohort_size=3)

    views = gate.public_views([published, suppressed])

    assert len(views) == 1
    assert views[0].cohort_size_bucket == "25-49"


@given(
    cohort_size=st.integers(min_value=0, max_value=10_000),
    threshold=st.integers(min_value=2, max_value=500),
)
def test_INV_EXPOSE_4_threshold_is_enforced_on_every_read(
    cohort_size: int, threshold: int
) -> None:
    """Property: nothing below threshold is ever returned by a read path."""
    gate = PrivacyGate(min_cohort_threshold=threshold, bucketing=BUCKETING)
    aggregate = _aggregate(cohort_size=cohort_size)

    view = gate.public_view(aggregate)
    suppressed = gate.suppress_if_below_threshold(aggregate)
    collection = gate.public_views([aggregate])

    if cohort_size < threshold:
        assert view is None
        assert suppressed is None
        assert collection == []
    else:
        assert view is not None
        assert suppressed is aggregate
        assert collection == [view]


@pytest.mark.parametrize("cohort_size", [0, 1, 9, 10, 11])
def test_INV_EXPOSE_4_threshold_boundary_cases(cohort_size: int) -> None:
    """The dangerous sizes, spelled out: empty, single, just-under, at, just-over."""
    gate = _gate(threshold=10)
    view = gate.public_view(_aggregate(cohort_size=cohort_size))
    assert (view is not None) == (cohort_size >= 10)


def test_INV_EXPOSE_4_a_live_community_does_not_make_every_slice_safe() -> None:
    """Go-live is a community-level fact; suppression is per slice."""
    community = Community(
        slug="wine",
        min_cohort_threshold=10,
        status=CommunityStatus.LIVE,
        created_at=NOW,
    )
    assert community.can_go_live(current_cohort=500)

    thin_slice = _aggregate(cohort_size=4)
    assert _gate(threshold=community.min_cohort_threshold).public_view(thin_slice) is None


def test_INV_EXPOSE_5_no_route_serialises_a_community_aggregate() -> None:
    offenders = [
        (getattr(route, "path", "?"), model)
        for route in create_app().routes
        if (model := getattr(route, "response_model", None)) is CommunityAggregate
    ]
    assert offenders == [], f"Route(s) serialise CommunityAggregate directly: {offenders}"


def test_INV_EXPOSE_5_community_aggregate_is_absent_from_the_openapi_schema() -> None:
    schema = create_app().openapi()
    components = schema.get("components", {}).get("schemas", {})
    assert "CommunityAggregate" not in components


def test_INV_EXPOSE_5_the_gate_is_the_only_projection_used_by_services() -> None:
    """`to_public_view` is called only from inside the privacy gate.

    The projection deliberately does not check the threshold, so a caller that
    reaches past the gate to call it directly publishes unsuppressed data.
    """
    offenders = [
        path.name
        for path, text in _app_sources()
        if "to_public_view" in text and path.name not in ("models.py", "privacy_gate.py")
    ]
    assert offenders == [], f"to_public_view called outside the gate: {offenders}"


# ══ Group CACHE ═══════════════════════════════════════════════════════════════


def test_INV_CACHE_1_place_ref_stores_no_display_fields() -> None:
    display_fields = {
        "name",
        "display_name",
        "formatted_address",
        "address",
        "rating",
        "user_ratings_total",
        "photos",
        "photo_reference",
        "opening_hours",
        "reviews",
        "review_text",
        "website",
        "phone_number",
    }
    assert not (set(PlaceRef.model_fields) & display_fields)
    assert not (set(Base.metadata.tables["place_ref"].columns.keys()) & display_fields)


def test_INV_CACHE_1_expired_coordinate_entries_are_purged() -> None:
    fresh = PlaceRef(
        place_id="fresh",
        last_refreshed_at=NOW,
        cached_lat=51.5,
        cached_lng=-0.12,
        coords_cached_at=NOW - timedelta(days=1),
    )
    stale = PlaceRef(
        place_id="stale",
        last_refreshed_at=NOW,
        cached_lat=51.5,
        cached_lng=-0.12,
        coords_cached_at=NOW - COORD_RETENTION - timedelta(seconds=1),
    )

    cleared = purge_expired_coordinates([fresh, stale], NOW, COORD_RETENTION)

    assert cleared == 1
    assert stale.cached_lat is None and stale.cached_lng is None
    assert stale.coords_cached_at is None
    assert fresh.cached_lat == 51.5
    # place_id may be kept indefinitely; only the coordinates are time-bounded.
    assert stale.place_id == "stale"


def test_INV_CACHE_2_stale_coordinates_are_treated_as_absent() -> None:
    stale = PlaceRef(
        place_id="stale",
        last_refreshed_at=NOW,
        cached_lat=51.5,
        cached_lng=-0.12,
        coords_cached_at=NOW - COORD_RETENTION,
    )
    assert stale.needs_refresh(NOW, COORD_RETENTION) is True
    # The read path signals "refetch", it does not hand back the stale value.
    assert coordinates(stale, NOW, COORD_RETENTION) is None


def test_INV_CACHE_2_fresh_coordinates_are_served() -> None:
    fresh = PlaceRef(
        place_id="fresh",
        last_refreshed_at=NOW,
        cached_lat=51.5,
        cached_lng=-0.12,
        coords_cached_at=NOW - COORD_RETENTION + timedelta(seconds=1),
    )
    assert coordinates(fresh, NOW, COORD_RETENTION) == (51.5, -0.12)


def test_INV_CACHE_2_uncached_coordinates_are_absent_not_stale() -> None:
    never = PlaceRef(place_id="never", last_refreshed_at=NOW)
    assert never.needs_refresh(NOW, COORD_RETENTION) is True
    assert coordinates(never, NOW, COORD_RETENTION) is None


def test_INV_CACHE_3_no_derived_venue_catalogue_can_be_queried() -> None:
    """Nothing lists or searches PlaceRef rows by anything but an exact id."""
    offenders = []
    for path, node in _all_function_defs():
        returns = ast.unparse(node.returns) if node.returns else ""
        returns_many_places = "PlaceRef" in returns and (
            "list" in returns or "Sequence" in returns or "Iterable" in returns
        )
        if not returns_many_places:
            continue
        params = {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
        # Accepting a caller-supplied collection is fine; searching is not.
        if params & {"query", "q", "name", "text", "bbox", "lat", "lng", "radius", "near"}:
            offenders.append((path.name, node.name))
    assert offenders == [], f"Venue search path(s) exist: {offenders}"


def test_INV_CACHE_3_no_route_lists_place_references() -> None:
    offenders = [path for path, _ in _routes() if "place" in path.lower()]
    assert offenders == [], f"Place routes exist and need review against INV-CACHE-3: {offenders}"


# ══ Group CONSENT ═════════════════════════════════════════════════════════════


def _consent(
    scope: ConsentScope = ConsentScope.GOOGLE_IMPORT_ONE_TIME,
    *,
    granted_at: datetime = NOW - timedelta(days=1),
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> ConsentRecord:
    return ConsentRecord(
        user_id=uuid4(),
        scope=scope,
        granted_at=granted_at,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _adult_import(
    consents: list[ConsentRecord],
    jobs: list[GoogleImportJob] | None = None,
    operation: Operation = Operation.GOOGLE_IMPORT_INITIAL,
) -> Decision:
    return consent_service.authorise_google_import(
        consents, jobs or [], NOW, age_verified_adult=True, operation=operation
    )


def test_INV_CONSENT_1_import_is_refused_without_consent() -> None:
    decision = _adult_import([])
    assert not decision
    assert decision.reason is RefusalReason.NO_CONSENT


def test_INV_CONSENT_1_import_is_refused_with_revoked_consent() -> None:
    decision = _adult_import([_consent(revoked_at=NOW - timedelta(hours=1))])
    assert not decision
    assert decision.reason is RefusalReason.CONSENT_REVOKED


def test_INV_CONSENT_1_import_is_refused_with_expired_consent() -> None:
    decision = _adult_import([_consent(expires_at=NOW - timedelta(hours=1))])
    assert not decision
    assert decision.reason is RefusalReason.CONSENT_EXPIRED


def test_INV_CONSENT_1_import_is_refused_with_direct_curation_consent() -> None:
    decision = _adult_import([_consent(ConsentScope.DIRECT_CURATION)])
    assert not decision
    assert decision.reason is RefusalReason.SCOPE_NOT_AUTHORISED


def test_INV_CONSENT_1_import_is_allowed_with_active_import_consent() -> None:
    """The positive case, so the four refusals above are not vacuous."""
    granted = _consent(ConsentScope.GOOGLE_IMPORT_ONE_TIME)
    decision = _adult_import([granted])
    assert decision
    assert decision.consent_id == granted.consent_id


def test_INV_CONSENT_2_no_code_path_updates_or_deletes_a_consent_record() -> None:
    """Append-only: revocation writes revoked_at, nothing rewrites or removes."""
    offenders = []
    for path, text in _app_sources():
        if path.name == "tables.py":
            continue
        if "ConsentRecordTable" not in text:
            continue
        for marker in ("delete(", ".delete()", "update(", "sa.update"):
            if marker in text:
                offenders.append((path.name, marker))
    assert offenders == [], f"Consent mutation path(s) exist: {offenders}"


def test_INV_CONSENT_2_no_consent_field_other_than_revoked_at_is_writable() -> None:
    """No repository exists yet; this fails the moment one grants writes."""
    offenders = [
        (path.name, node.name)
        for path, node in _all_function_defs()
        if "consent" in node.name.lower()
        and any(verb in node.name.lower() for verb in ("update", "delete", "amend", "edit"))
    ]
    assert offenders == [], f"Consent mutation function(s) exist: {offenders}"


def test_INV_CONSENT_3_signed_urls_are_never_persisted() -> None:
    url_fields = {"signed_url", "url", "download_url", "archive_url"}
    assert not (set(GoogleImportJob.model_fields) & url_fields)
    assert not (set(Base.metadata.tables["google_import_job"].columns.keys()) & url_fields)
    # Only the expiry instant is recorded.
    assert "signed_url_expires_at" in GoogleImportJob.model_fields


def test_INV_CONSENT_3_no_signed_url_is_logged() -> None:
    """No logging call anywhere in app/ interpolates a signed URL."""
    offenders = [
        path.name
        for path, text in _app_sources()
        if "signed_url" in text and "logger" in text and "signed_url_expires_at" not in text
    ]
    assert offenders == [], f"Signed URL may reach logs from: {offenders}"


@pytest.mark.parametrize(
    ("scope", "operation", "expected"),
    [
        (ConsentScope.DIRECT_CURATION, Operation.DIRECT_CURATION, True),
        (ConsentScope.DIRECT_CURATION, Operation.GOOGLE_IMPORT_INITIAL, False),
        (ConsentScope.DIRECT_CURATION, Operation.GOOGLE_IMPORT_REPEAT, False),
        (ConsentScope.GOOGLE_IMPORT_ONE_TIME, Operation.GOOGLE_IMPORT_INITIAL, True),
        (ConsentScope.GOOGLE_IMPORT_ONE_TIME, Operation.GOOGLE_IMPORT_REPEAT, False),
        (ConsentScope.GOOGLE_IMPORT_ONE_TIME, Operation.DIRECT_CURATION, False),
        (ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED, Operation.GOOGLE_IMPORT_INITIAL, True),
        (ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED, Operation.GOOGLE_IMPORT_REPEAT, True),
        (ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED, Operation.DIRECT_CURATION, False),
    ],
)
def test_INV_CONSENT_4_each_scope_authorises_only_its_own_operation(
    scope: ConsentScope, operation: Operation, expected: bool
) -> None:
    assert consent_service.authorises(scope, operation) is expected


def test_INV_CONSENT_4_one_time_consent_does_not_authorise_a_second_import() -> None:
    granted = _consent(ConsentScope.GOOGLE_IMPORT_ONE_TIME)
    already_run = GoogleImportJob(
        job_id="job-1",
        user_id=granted.user_id,
        consent_id=granted.consent_id,
        state=ImportJobState.COMPLETE,
        initiated_at=NOW - timedelta(days=1),
        completed_at=NOW - timedelta(hours=2),
    )

    assert _adult_import([granted])
    second = _adult_import([granted], [already_run])
    assert not second
    assert second.reason is RefusalReason.ONE_TIME_CONSENT_ALREADY_USED


def test_INV_CONSENT_4_direct_curation_consent_never_reaches_the_import_path() -> None:
    decision = _adult_import([_consent(ConsentScope.DIRECT_CURATION)])
    assert not decision
    assert decision.consent_id is None


# ══ Group MINOR ═══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("age_verified_adult", [None, False])
def test_INV_MINOR_1_import_fails_closed_without_established_adult_age(
    age_verified_adult: bool | None,
) -> None:
    """Absent or indeterminate age refuses, even with perfect consent."""
    decision = consent_service.authorise_google_import(
        [_consent(ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED)],
        [],
        NOW,
        age_verified_adult=age_verified_adult,
    )
    assert not decision
    assert decision.reason is RefusalReason.AGE_NOT_ESTABLISHED


def test_INV_MINOR_1_no_age_field_was_added_to_the_user_model() -> None:
    """Age eligibility is a decision-time parameter, not stored state.

    Persisting an age or date of birth against a pseudonymous User is a
    retention decision for the owner (CLAUDE.md). This test fails if one
    appears without that decision being taken.
    """
    age_fields = {"age", "date_of_birth", "dob", "birth_date", "age_verified", "is_adult"}
    assert not (set(Base.metadata.tables["user"].columns.keys()) & age_fields)


# ══ Open decisions: guards, not invariants ════════════════════════════════════


def test_OPEN_1_threshold_below_the_individual_floor_is_refused() -> None:
    """A cohort of one is an individual; publishing it breaches INV-EXPOSE-1."""
    for unsafe in (-1, 0, 1):
        with pytest.raises(Exception, match="min_cohort_threshold"):
            PrivacyGate(min_cohort_threshold=unsafe, bucketing=BUCKETING)


def test_OPEN_3_noise_is_a_declared_no_op_when_disabled() -> None:
    gate = _gate()
    aggregate = _aggregate(cohort_size=40)
    assert gate.apply_noise(aggregate) is aggregate


def test_OPEN_3_enabling_noise_without_parameters_fails_loudly() -> None:
    gate = PrivacyGate(
        min_cohort_threshold=10, bucketing=BUCKETING, noise=NoiseConfig(enabled=True)
    )
    with pytest.raises(Exception, match="mechanism and epsilon are unset"):
        gate.apply_noise(_aggregate(cohort_size=40))


def test_OPEN_3_enabling_noise_with_parameters_still_fails_loudly() -> None:
    """No mechanism exists. A configured epsilon must not imply one does."""
    gate = PrivacyGate(
        min_cohort_threshold=10,
        bucketing=BUCKETING,
        noise=NoiseConfig(enabled=True, mechanism="laplace", epsilon=1.0),
    )
    with pytest.raises(Exception, match="no noise mechanism is implemented"):
        gate.apply_noise(_aggregate(cohort_size=40))


# ══ Group SCHEMA ══════════════════════════════════════════════════════════════


def test_INV_SCHEMA_1_facet_names_come_from_the_catalogue_not_the_request() -> None:
    """A founder selects a facet; they cannot author its name."""
    catalogue = FacetCatalogue(
        definitions=(
            FacetDefinition(
                key="body",
                name="Body",
                value_type=FacetValueType.NUMERIC,
                scale_min=0.0,
                scale_max=10.0,
            ),
        )
    )
    batch = [
        FoundingContribution(
            user_id=uuid4(), place_id=f"place-{i}", facet_scores={"body": 4.0}
        )
        for i in range(5)
    ]

    result = found_community("wine", 10, frozenset({"body"}), catalogue, batch, NOW)

    assert [facet.name for facet in result.facets] == ["Body"]
    with pytest.raises(UnknownFacetKeyError):
        found_community("wine", 10, frozenset({"invented"}), catalogue, batch, NOW)


def test_INV_SCHEMA_1_no_founding_input_carries_a_facet_name() -> None:
    """Asserted structurally: the request-side type has no name field."""
    assert "name" not in FoundingContribution.__dataclass_fields__
    # Scores are keyed by catalogue key, so a request cannot invent a facet.
    annotation = FoundingContribution.__dataclass_fields__["facet_scores"].type
    assert "str" in str(annotation)


def test_INV_SCHEMA_2_a_text_facet_cannot_be_offered() -> None:
    """No path from text to a float, and prose must not be persisted."""
    with pytest.raises(FacetCatalogueError):
        FacetDefinition(key="notes", name="Notes", value_type=FacetValueType.TEXT)


def test_INV_SCHEMA_2_scoreable_types_exclude_text() -> None:
    assert FacetValueType.TEXT not in SCOREABLE_VALUE_TYPES
    assert FacetValueType.NUMERIC in SCOREABLE_VALUE_TYPES


# ══ Group AUTH ════════════════════════════════════════════════════════════════
#
# Nothing in docs/05_AUTH_DESIGN.md is built yet, so these are assertions of
# absence in the sense docs/04 requires: they fail on the commit that
# introduces the breach, rather than waiting to be written once the layer
# exists. Each one is phrased so that it also holds -- and keeps meaning --
# once the real thing lands.


# Columns that could only be an external identity. Deliberately not a bare
# "name": facet.name is a platform-authored facet label, which is a different
# thing entirely and legitimately stored (INV-SCHEMA-1).
FORBIDDEN_IDENTITY_COLUMNS = {
    "email",
    "email_address",
    "full_name",
    "given_name",
    "family_name",
    "picture",
    "avatar_url",
    "phone",
    "phone_number",
    "sub",
    "subject",
    "google_sub",
    "id_token",
    "access_token",
    "refresh_token",
}


def test_INV_AUTH_1_no_table_holds_a_plaintext_external_identifier() -> None:
    """Holds now because identity_link does not exist; holds later because a
    correct one stores only a keyed digest."""
    for name, table in Base.metadata.tables.items():
        offending = set(table.columns.keys()) & FORBIDDEN_IDENTITY_COLUMNS
        assert not offending, (
            f"Table {name!r} holds a plaintext external identifier: {sorted(offending)}"
        )


def test_INV_AUTH_1_the_identity_link_is_never_joined_to_rating_data() -> None:
    """An identity link answers 'which account is this', never 'what did it rate'."""
    rating_tables = {"community_aggregate", "facet_stat"}
    identity_tables = {
        name for name in Base.metadata.tables if "identity" in name or "oauth" in name
    }

    for name in identity_tables:
        foreign = {fk.column.table.name for fk in Base.metadata.tables[name].foreign_keys}
        assert not (foreign & rating_tables), (
            f"{name!r} references rating data: {sorted(foreign & rating_tables)}"
        )

    # And nothing on the rating side points back at it either.
    for name in rating_tables & set(Base.metadata.tables):
        foreign = {fk.column.table.name for fk in Base.metadata.tables[name].foreign_keys}
        assert not (foreign & identity_tables)


def test_INV_AUTH_2_no_authorisation_seam_accepts_a_contribution() -> None:
    """The issuance endpoint takes a digest, never facet scores or free text.

    Fails the moment somebody adds a function that both looks like the
    authorisation-issuance seam and accepts rating data "to compute the hash
    server-side" -- which would put INV-RAW-2 back in play through a side door.
    """
    rating_params = {"facet_scores", "free_text", "contribution", "contributions"}
    offenders = []
    for path, node in _all_function_defs():
        name = node.name.lower()
        if not ("authorisation" in name or "authorization" in name or "token" in name):
            continue
        params = {arg.arg for arg in node.args.args} | {
            arg.arg for arg in node.args.kwonlyargs
        }
        if params & rating_params:
            offenders.append((path.name, node.name, sorted(params & rating_params)))
    assert offenders == [], f"Authorisation seam accepts rating data: {offenders}"


# ══ The rule this file must keep about itself ═════════════════════════════════


INVARIANTS_DOC = Path(__file__).resolve().parents[2] / "docs" / "04_PRIVACY_INVARIANTS.md"


def _documented_invariant_ids() -> set[str]:
    """Every INV- id defined by a heading in docs/04."""
    return {
        line.split("`")[1]
        for line in INVARIANTS_DOC.read_text().splitlines()
        if line.startswith("### `INV-")
    }


def test_every_documented_invariant_has_a_test() -> None:
    """docs/04: "Every invariant has at least one test whose name contains that ID."

    Enforced here rather than trusted, so that adding an invariant to the
    document without covering it fails the build -- which is the only way that
    rule stays true over time.
    """
    test_names = "\n".join(
        node.name
        for node in ast.walk(ast.parse(Path(__file__).read_text()))
        if isinstance(node, ast.FunctionDef)
    )
    uncovered = sorted(
        invariant_id
        for invariant_id in _documented_invariant_ids()
        if invariant_id.replace("-", "_") not in test_names
    )
    assert uncovered == [], f"Invariants with no test: {uncovered}"


def test_the_invariant_document_is_readable_and_non_empty() -> None:
    """Guards the test above from passing because the doc failed to parse."""
    assert len(_documented_invariant_ids()) >= 13
