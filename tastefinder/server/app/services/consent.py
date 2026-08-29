"""
app/services/consent.py
-----------------------
Whether an operation is authorised by the consent on record.

This is a decision function, not the import flow -- the Google Data
Portability integration is explicitly out of scope for the bootstrap
(`docs/00_BOOTSTRAP.md`). It exists in Phase 3 because `INV-CONSENT-1`,
`INV-CONSENT-4` and `INV-MINOR-1` all say the import path must *fail closed*,
and a fail-closed rule needs something callable to be a rule rather than an
aspiration. Building the gate before the thing it gates means the import code,
whenever it is written, has to come through here.

Every path returns a refusal by default. There is no branch that allows an
operation because nothing objected to it.

**Age eligibility is a parameter, not stored state.** Google's Data
Portability API does not serve accounts under 18 (`INV-MINOR-1`), so the
decision needs an age signal -- but where that signal comes from, and whether
anything about it may be persisted against a `User`, is a data-retention
question and therefore the owner's (see `CLAUDE.md`, "What to ask about rather
than decide"). Passing it in leaves `User` and its table untouched: no age
column has been added.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.enums import ConsentScope
from app.domain.models import ConsentRecord, GoogleImportJob


class Operation(StrEnum):
    """What a caller wants to do, at the granularity consent is given at."""

    DIRECT_CURATION = "DIRECT_CURATION"
    GOOGLE_IMPORT_INITIAL = "GOOGLE_IMPORT_INITIAL"
    GOOGLE_IMPORT_REPEAT = "GOOGLE_IMPORT_REPEAT"


class RefusalReason(StrEnum):
    """Why an operation was refused.

    Deliberately a closed set of codes rather than free text: a refusal reason
    travels into logs and error bodies, and `docs/03_API_CONTRACT.md` requires
    that an error message never names a specific user, contribution, or cohort
    size.
    """

    AGE_NOT_ESTABLISHED = "AGE_NOT_ESTABLISHED"
    NO_CONSENT = "NO_CONSENT"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    CONSENT_NOT_YET_ACTIVE = "CONSENT_NOT_YET_ACTIVE"
    SCOPE_NOT_AUTHORISED = "SCOPE_NOT_AUTHORISED"
    ONE_TIME_CONSENT_ALREADY_USED = "ONE_TIME_CONSENT_ALREADY_USED"


# How informative each refusal is. Where several consents are refused for
# different reasons, the caller is told the most specific one: "your import
# consent was revoked" is actionable, "no consent" is misleading if the user
# did in fact grant one.
REFUSAL_PRIORITY: dict[RefusalReason, int] = {
    RefusalReason.NO_CONSENT: 0,
    RefusalReason.SCOPE_NOT_AUTHORISED: 1,
    RefusalReason.CONSENT_NOT_YET_ACTIVE: 2,
    RefusalReason.CONSENT_EXPIRED: 3,
    RefusalReason.CONSENT_REVOKED: 4,
    RefusalReason.ONE_TIME_CONSENT_ALREADY_USED: 5,
    RefusalReason.AGE_NOT_ESTABLISHED: 6,
}


# INV-CONSENT-4. Consent to direct curation authorises nothing about Google,
# and a one-time import authorises exactly one import.
SCOPE_AUTHORISES: dict[ConsentScope, frozenset[Operation]] = {
    ConsentScope.DIRECT_CURATION: frozenset({Operation.DIRECT_CURATION}),
    ConsentScope.GOOGLE_IMPORT_ONE_TIME: frozenset({Operation.GOOGLE_IMPORT_INITIAL}),
    ConsentScope.GOOGLE_IMPORT_TIME_BOUNDED: frozenset(
        {Operation.GOOGLE_IMPORT_INITIAL, Operation.GOOGLE_IMPORT_REPEAT}
    ),
}


@dataclass(frozen=True)
class Decision:
    """The outcome of an authorisation check.

    `consent_id` is populated only on an allow, so that the caller records
    which consent it acted under -- `INV-CONSENT-2` makes the consent history
    the audit trail, and an import with no recorded basis breaks it.
    """

    allowed: bool
    reason: RefusalReason | None = None
    consent_id: UUID | None = None

    def __bool__(self) -> bool:
        return self.allowed


def authorises(scope: ConsentScope, operation: Operation) -> bool:
    """Whether a scope covers an operation, ignoring validity in time."""
    return operation in SCOPE_AUTHORISES.get(scope, frozenset())


def _validity_refusal(consent: ConsentRecord, now: datetime) -> RefusalReason | None:
    """Why this consent is not active as at `now`, or None if it is."""
    if consent.revoked_at is not None and consent.revoked_at <= now:
        return RefusalReason.CONSENT_REVOKED
    if consent.expires_at is not None and consent.expires_at <= now:
        return RefusalReason.CONSENT_EXPIRED
    if consent.granted_at > now:
        return RefusalReason.CONSENT_NOT_YET_ACTIVE
    return None


def authorise_google_import(
    consents: Sequence[ConsentRecord],
    existing_jobs: Sequence[GoogleImportJob],
    now: datetime,
    *,
    age_verified_adult: bool | None,
    operation: Operation = Operation.GOOGLE_IMPORT_INITIAL,
) -> Decision:
    """Decide whether a Google import may be initiated.

    Args:
        consents: the user's consent records. A route holding a single
            `consent_id` passes a one-element sequence.
        existing_jobs: the user's import jobs, used to tell an initial import
            from a repeat under the same consent.
        now: the instant the decision is made at.
        age_verified_adult: True only where adult status has been positively
            established. `None` means unknown and is refused, not allowed --
            that is the whole content of INV-MINOR-1.
        operation: which import this is.

    Returns:
        A `Decision`. Falsy when refused, so `if not authorise_...(): refuse`.
    """
    # Age first, so that an indeterminate age refuses regardless of what
    # consent exists. Fails closed (INV-MINOR-1).
    if age_verified_adult is not True:
        return Decision(allowed=False, reason=RefusalReason.AGE_NOT_ESTABLISHED)

    if not consents:
        return Decision(allowed=False, reason=RefusalReason.NO_CONSENT)

    refusal = RefusalReason.NO_CONSENT

    def note(reason: RefusalReason) -> None:
        nonlocal refusal
        if REFUSAL_PRIORITY[reason] > REFUSAL_PRIORITY[refusal]:
            refusal = reason

    for consent in consents:
        if not authorises(consent.scope, operation):
            note(RefusalReason.SCOPE_NOT_AUTHORISED)
            continue

        invalid = _validity_refusal(consent, now)
        if invalid is not None:
            note(invalid)
            continue

        # INV-CONSENT-4: a one-time scope is spent by the first job raised
        # under it. Retrying a FAILED job is not a new import and goes through
        # GoogleImportJob.can_retry(), not through here.
        if consent.scope is ConsentScope.GOOGLE_IMPORT_ONE_TIME and any(
            job.consent_id == consent.consent_id for job in existing_jobs
        ):
            note(RefusalReason.ONE_TIME_CONSENT_ALREADY_USED)
            continue

        return Decision(allowed=True, consent_id=consent.consent_id)

    return Decision(allowed=False, reason=refusal)
