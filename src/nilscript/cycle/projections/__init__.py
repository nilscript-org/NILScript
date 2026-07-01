"""Projection generators over the Cycle AST v0.2 (docs/PLAN-cycle-ast-ssot.md §5).

Every function here is a PURE, read-only VIEW of one `Cycle` — no execution, no control plane, no
new source of truth. The Cycle remains the single SSOT; these just re-present it:

  - `to_mermaid`        — a `flowchart TD` diagram of the flow
  - `to_markdown`       — human documentation (bilingual-aware)
  - `simulate`          — an ordered happy-path dry-run ("preview what will happen", proposes only)
  - `governance_report` — the trust summary (gates, approvals, reversibility)
"""

from __future__ import annotations

from nilscript.cycle.projections.docs import to_markdown
from nilscript.cycle.projections.governance import governance_report
from nilscript.cycle.projections.mermaid import to_mermaid
from nilscript.cycle.projections.simulate import simulate

__all__ = ["to_mermaid", "to_markdown", "simulate", "governance_report"]
