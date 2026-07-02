"""V9 — strategy well-formedness (CAPABILITY-SHIFT plan §A4-V9). Refusals as answers.

Pure functions over the frozen Strategy AST (plus the owning Capability as governance context).
Every rule returns `Diagnostic`s through the kernel's collector — the same structured refusal
shape V1–V6 use — and NEVER raises: a governance verdict is data the caller renders, not an
exception the caller catches.

Rules (each carries its own code so callers branch on codes, never wording):

  V9_SELF_APPROVAL        an approve unit without `distinct_from: [preparer]` under a capability
                          whose sod declares preparer_not_approver (invariant I6)
  V9_QUORUM_UNSATISFIABLE k exceeds the number of offered units
  V9_QUORUM_DISTINCT      `distinct` demanded but the offered units cannot yield k distinct signers
  V9_TIMEOUT_NO_ROUTE     a unit deadline with no escalate/reject route (a silent expiry hole)
  V9_AUTO_FORBIDDEN       `auto(...)` under a capability whose risk floor exceeds MEDIUM (I3)
"""

from __future__ import annotations

from nilscript.capability.models import Capability
from nilscript.kernel.diagnostics import DiagnosticCollector, ValidationResult
from nilscript.strategy.models import (
    PREPARER,
    Approve,
    Auto,
    Conditional,
    Quorum,
    Seq,
    Strategy,
    StrategyNodeType,
)

_AUTO_ALLOWED_RISK = ("LOW", "MEDIUM")


def validate_strategy(
    strategy: Strategy, capability_ctx: Capability | None = None
) -> ValidationResult:
    """Run every V9 rule. `capability_ctx` is the capability that binds this strategy — the SoD
    and risk rules need it; without it only the capability-independent rules run (quorum shape,
    timeout routes). Returns the kernel's structured `ValidationResult`, never raises."""
    collector = DiagnosticCollector()
    root = strategy.root
    if isinstance(root, Conditional):
        _walk(root.then, "root.then", collector, capability_ctx)
        _walk(root.else_, "root.else", collector, capability_ctx)
    else:
        _walk(root, "root", collector, capability_ctx)
    return ValidationResult.of(collector.items)


def _walk(
    node: StrategyNodeType,
    path: str,
    collector: DiagnosticCollector,
    capability: Capability | None,
) -> None:
    if isinstance(node, Auto):
        _check_auto(path, collector, capability)
    elif isinstance(node, Approve):
        _check_approve(node, path, collector, capability)
    elif isinstance(node, Seq):
        for i, item in enumerate(node.items):
            _walk(item, f"{path}.items[{i}]", collector, capability)
    elif isinstance(node, Quorum):
        _check_quorum(node, path, collector)
        for i, member in enumerate(node.of):
            _check_approve(member, f"{path}.of[{i}]", collector, capability)


def _check_auto(
    path: str, collector: DiagnosticCollector, capability: Capability | None
) -> None:
    if capability is not None and capability.risk not in _AUTO_ALLOWED_RISK:
        collector.error(
            "V9_AUTO_FORBIDDEN",
            f"auto() is not allowed for capability {capability.capability_id!r} with risk "
            f"{capability.risk} — automatic approval stops at MEDIUM (the floor only rises)",
            location=path,
        )


def _check_approve(
    node: Approve, path: str, collector: DiagnosticCollector, capability: Capability | None
) -> None:
    unit = node.unit
    if (
        capability is not None
        and capability.sod.preparer_not_approver
        and PREPARER not in unit.distinct_from
    ):
        collector.error(
            "V9_SELF_APPROVAL",
            f"capability {capability.capability_id!r} declares sod.preparer_not_approver, but the "
            f"approve unit for {unit.by} {unit.name!r} does not carry distinct_from: [preparer] — "
            "the preparer could sign their own card",
            location=path,
        )
    if unit.timeout is not None and unit.timeout.then is None:
        collector.error(
            "V9_TIMEOUT_NO_ROUTE",
            f"the approve unit for {unit.by} {unit.name!r} times out after "
            f"{unit.timeout.after} with no route — every timeout needs escalate(...) or reject",
            location=path,
        )


def _check_quorum(node: Quorum, path: str, collector: DiagnosticCollector) -> None:
    if node.k > len(node.of):
        collector.error(
            "V9_QUORUM_UNSATISFIABLE",
            f"quorum needs {node.k} signatures but offers only {len(node.of)} unit(s)",
            location=path,
        )
        return
    if node.distinct:
        identities = {(member.unit.by, member.unit.name) for member in node.of}
        if len(identities) < node.k:
            collector.error(
                "V9_QUORUM_DISTINCT",
                f"quorum demands {node.k} DISTINCT signatures but its units resolve to only "
                f"{len(identities)} distinct identit(y/ies)",
                location=path,
            )


__all__ = ["validate_strategy"]
