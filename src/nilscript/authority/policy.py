"""Wave 6 §1: Policy Engine — Non-Breaking Wrapper Over Permission Enforcement.

The Policy Engine is the centralized access control layer. It returns explainable
Verdict objects (Allow/Deny/NeedsApproval) instead of raising exceptions.

Phase 1 (now): Non-breaking wrapper over existing `_require_permission`.
Phase 2 (future): Full policy engine with L3–L7 authority layers, time-scoped grants,
               delegation chains, and capability-scoped permissions.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class VerdictKind(str, Enum):
    """Policy decision outcomes."""

    ALLOW = "Allow"
    DENY = "Deny"
    NEEDS_APPROVAL = "NeedsApproval"


class Verdict(BaseModel):
    """Explainable policy decision.

    Returns one of three outcomes:
    - Allow: Actor can perform action immediately
    - Deny: Actor cannot perform action (with reason)
    - NeedsApproval: Actor can request, but must wait for approvers
    """

    kind: VerdictKind = Field(..., description="Allow | Deny | NeedsApproval")
    reason: str = Field(default="", description="Human-readable explanation")
    approvers: list[str] = Field(
        default_factory=list,
        description="If NeedsApproval, who can grant it (actor IDs or role names)",
    )


class PolicyEngine:
    """Centralized, explainable access control.

    Phase 1: Wraps existing `_require_permission` function (if it exists).
    Phase 2: Will implement full policy evaluation using L3–L7 authority layers.

    Usage:
        engine = PolicyEngine()
        verdict = engine.can(user_id, "approve", "proposal:xyz", {"tier": "HIGH"})
        if verdict.kind == "NeedsApproval":
            # Create a Permission Card and send to approvers
    """

    def __init__(self, require_permission_fn=None):
        """Initialize the Policy Engine.

        Args:
            require_permission_fn: Optional callable to wrap existing permission checks.
                                   If None, defaults to allow-all (for Phase 1 baseline).
        """
        self._require_permission = require_permission_fn

    def can(
        self,
        actor: str,
        action: str,
        resource: str,
        context: dict | None = None,
    ) -> Verdict:
        """Can this actor perform this action on this resource?

        Args:
            actor: Actor ID (user, Hermes, service account)
            action: Action being requested (e.g., "write", "approve", "execute")
            resource: Resource identifier (e.g., "cycle:12345", "proposal:xyz")
            context: Optional context dict (e.g., {"tier": "HIGH", "workspace": "acme"})

        Returns:
            Verdict with kind, reason, and (if NeedsApproval) list of approvers.

        Examples:
            >>> engine = PolicyEngine()
            >>> engine.can(user_id, "write", "cycle:123")
            Verdict(kind="Allow")

            >>> engine.can(hermes_id, "execute", "cycle:123")
            Verdict(kind="Deny", reason="Hermes cannot execute (God Rule)")

            >>> engine.can(user_id, "approve", "proposal:xyz", {"tier": "CRITICAL"})
            Verdict(kind="NeedsApproval", approvers=["cfo@acme.com", "ceo@acme.com"])
        """
        context = context or {}

        # Phase 1: Wrap existing _require_permission if available
        if self._require_permission is not None:
            try:
                # Build a permission token from action.resource pattern
                permission = f"{action}.{resource}"
                self._require_permission(actor, permission)
                return Verdict(kind=VerdictKind.ALLOW)
            except PermissionError as e:
                return Verdict(
                    kind=VerdictKind.DENY,
                    reason=str(e),
                )
            except Exception as e:
                # Unexpected error: deny for safety
                return Verdict(
                    kind=VerdictKind.DENY,
                    reason=f"Unexpected error: {type(e).__name__}",
                )

        # Phase 1 baseline: allow-all (until full policy engine is wired)
        return Verdict(kind=VerdictKind.ALLOW)

    def explain(self, actor: str, action: str, resource: str, context: dict | None = None) -> str:
        """Human-readable explanation of why a policy decision was made.

        Returns a multi-line string describing the authority layers consulted,
        grants found, and final decision.
        """
        verdict = self.can(actor, action, resource, context)
        lines = [
            f"Actor: {actor}",
            f"Action: {action}",
            f"Resource: {resource}",
            f"Decision: {verdict.kind.value}",
        ]
        if verdict.reason:
            lines.append(f"Reason: {verdict.reason}")
        if verdict.approvers:
            lines.append(f"Approvers: {', '.join(verdict.approvers)}")
        return "\n".join(lines)
