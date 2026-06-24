"""Annex A refusal codes (nilscript 0.1.0-draft). Refusals are outcomes, not errors."""

from enum import StrEnum


class RefusalCode(StrEnum):
    MALFORMED = "MALFORMED"
    UNKNOWN_PERFORMATIVE = "UNKNOWN_PERFORMATIVE"
    UNKNOWN_VERB = "UNKNOWN_VERB"
    SCOPE_DENIED = "SCOPE_DENIED"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"
    POLICY_DENIED = "POLICY_DENIED"
    INVALID_ARGS = "INVALID_ARGS"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    # Backward-recovery refusals (ROLLBACK): the System refuses to *pretend* it can
    # reverse an effect it cannot. An honest refusal, never a silent corrective write.
    IRREVERSIBLE = "IRREVERSIBLE"
    COMPENSATION_EXPIRED = "COMPENSATION_EXPIRED"
    # State-witness (TOCTOU): a proposal is bound to the SSOT state it previewed; if that state
    # drifts before COMMIT (a delayed approval against a changed world), the kernel fails closed
    # rather than writing against stale reality. Re-preview, re-approve — never a blind commit.
    PRECONDITION_FAILED = "PRECONDITION_FAILED"


RETRIABLE_REFUSALS: frozenset[RefusalCode] = frozenset(
    {RefusalCode.RATE_LIMITED, RefusalCode.UPSTREAM_UNAVAILABLE}
)
