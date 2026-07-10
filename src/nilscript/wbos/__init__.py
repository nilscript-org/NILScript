"""Wave 5 (AI Boundary) — Frozen Intent API and Kernel Dispatch.

Public API:
- intent: Intent taxonomy v1 (frozen, versioned)
- capability_resolver: Server-side resolver (Kernel-owned, Hermes-opaque)
- kernel: Kernel.execute and Kernel.compile (the two-entry-point API)

See docs/WAVE-5-MIGRATION.md for the full AI boundary architecture.
"""

from nilscript.wbos.capability_resolver import (
    CapabilityResolver,
    ResolvedCapability,
    ResolutionResult,
)
from nilscript.wbos.intent import (
    ClarifyRequest,
    CreateBusinessCycleIntent,
    ExecuteCycleIntent,
    ExplainDecisionIntent,
    HermesIntent,
    Intent,
    IntentKind,
    KernelClarification,
    QueryThreadIntent,
    ReplyToThreadIntent,
    SummarizeThreadIntent,
)
from nilscript.wbos.kernel import CompiledPlan, ExecutionResult, Kernel

__all__ = [
    # Intent taxonomy
    "Intent",
    "IntentKind",
    "CreateBusinessCycleIntent",
    "ExecuteCycleIntent",
    "ReplyToThreadIntent",
    "QueryThreadIntent",
    "ExplainDecisionIntent",
    "SummarizeThreadIntent",
    "ClarifyRequest",
    "HermesIntent",
    "KernelClarification",
    # Resolver
    "CapabilityResolver",
    "ResolutionResult",
    "ResolvedCapability",
    # Kernel
    "Kernel",
    "ExecutionResult",
    "CompiledPlan",
]
