"""Wave 6 §3: Hermes as a Governed Actor — God Rules.

Hermes (the AI orchestrator) is constrained to proposals only:
- Can draft cycles, propose parameters, reply on threads, suggest clarifications
- NEVER executes, approves, modifies thread state, or calls adapters

These constraints are enforced as explicit God Rules via the Policy Engine.
Hermes cannot be granted exceptions to these rules — they are unchecked.
"""

from __future__ import annotations

from nilscript.authority.layers import AuthorityLevel, ActorAuthority, RoleBundle


class HermesActor:
    """Hermes as a governed actor with hard constraints.

    God Rules (unchecked, no exceptions):
    - Hermes can only PROPOSE LOW-tier actions
    - Hermes NEVER executes, approves, or modifies thread state
    - Hermes is the AI coordinator, not a decision-maker

    These constraints are enforced by the Policy Engine and Permission Cards.
    """

    # Hermes' fixed identity
    ACTOR_ID = "hermes"
    AUTHORITY_LEVEL = AuthorityLevel.LOW  # Can only propose LOW-tier actions

    # Whitelist: what Hermes CAN do
    ALLOWED_ACTIONS = {
        # Cycle authoring
        "draft_cycle",  # Generate a new cycle blueprint
        "propose_parameters",  # Fill in cycle parameters based on context
        "propose_strategy",  # Suggest a strategy execution plan

        # Thread communication
        "reply_to_thread",  # Send message on a cycle or case thread
        "suggest_clarification",  # Ask user/participant to clarify something

        # Information retrieval (read-only)
        "query_capability",  # Look up capability definitions
        "query_domain",  # Look up domain bindings
        "query_thread_history",  # Read past messages in a thread
    }

    # Blacklist: what Hermes ABSOLUTELY CANNOT do
    FORBIDDEN_ACTIONS = {
        # Execution
        "execute_cycle",  # Never
        "execute_verb",  # Never
        "call_adapter",  # Never

        # Approval / Authorization
        "approve_proposal",  # Never
        "reject_proposal",  # Never
        "grant_permission",  # Never
        "revoke_permission",  # Never

        # State mutation
        "modify_cycle_state",  # Never
        "modify_thread_state",  # Never
        "modify_actor_authority",  # Never
        "delete_resource",  # Never

        # System administration
        "create_domain",  # Never
        "modify_domain",  # Never
        "register_capability",  # Never
        "create_role",  # Never
    }

    @classmethod
    def build_authority(cls) -> ActorAuthority:
        """Build Hermes' ActorAuthority model (L3–L7 layers).

        Hermes has a fixed authority model:
        - No role bundles (fixed-function actor)
        - No capability scopes (only LOW tier, everywhere)
        - No thread relationships (Hermes is not "in" threads)
        - No time-scoped grants (fixed forever)
        - No delegations (Hermes cannot delegate)
        """
        return ActorAuthority(
            actor_id=cls.ACTOR_ID,
            authority_level=cls.AUTHORITY_LEVEL,
            role_bundles=[
                RoleBundle(
                    name="HermesProposer",
                    permissions=list(cls.ALLOWED_ACTIONS),
                    authority_level=AuthorityLevel.LOW,
                    description="Hermes' fixed role: proposal-only coordinator",
                )
            ],
            capability_scopes=[],  # No per-capability overrides
            thread_relationships=[],  # Hermes is not in threads
            time_scoped_grants=[],  # No temporary grants
            delegations=[],  # Hermes cannot delegate
        )

    @classmethod
    def validate_action(cls, action: str) -> None:
        """Validate that Hermes is allowed to perform this action.

        Raises PermissionError if the action violates God Rules.
        Returns silently if the action is allowed.
        """
        if action in cls.FORBIDDEN_ACTIONS:
            raise PermissionError(
                f"Hermes cannot {action} (God Rule: Hermes is proposal-only, "
                f"never executes/approves/modifies state)"
            )
        if action not in cls.ALLOWED_ACTIONS:
            raise PermissionError(
                f"Hermes {action} is not whitelisted. Allowed: {sorted(cls.ALLOWED_ACTIONS)}"
            )

    @classmethod
    def is_hermes(cls, actor_id: str) -> bool:
        """Check if an actor ID is Hermes."""
        return actor_id == cls.ACTOR_ID

    @classmethod
    def get_god_rules(cls) -> dict:
        """Return a structured description of Hermes' God Rules.

        Used for documentation, audit logs, and policy explanations.
        """
        return {
            "actor_id": cls.ACTOR_ID,
            "god_rules": [
                {
                    "rule": "Hermes is proposal-only",
                    "consequence": "Can draft cycles, propose parameters, reply on threads",
                },
                {
                    "rule": "Hermes never executes",
                    "consequence": "Cannot call execute_cycle, execute_verb, or call_adapter",
                },
                {
                    "rule": "Hermes never approves",
                    "consequence": "Cannot approve_proposal or reject_proposal",
                },
                {
                    "rule": "Hermes never modifies state",
                    "consequence": "Cannot modify_cycle_state, modify_thread_state, or delete_resource",
                },
                {
                    "rule": "Hermes cannot manage authority",
                    "consequence": "Cannot grant_permission, revoke_permission, or create_role",
                },
            ],
            "authority_level": cls.AUTHORITY_LEVEL.value,
            "allowed_actions": sorted(cls.ALLOWED_ACTIONS),
            "forbidden_actions": sorted(cls.FORBIDDEN_ACTIONS),
        }
