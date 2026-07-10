"""The ApprovalStrategy AST — the MVP-5 approval algebra (CAPABILITY-SHIFT plan §A2).

`Strategy` is the governed answer to "who must sign, in what shape": `Auto | Approve | Seq |
Quorum | Conditional`, over the same `.nil` grammar family as cycles and capabilities. V9
well-formedness (`validate_strategy`) returns structured refusals; reserved future forms
parse-refuse with `V9_UNSUPPORTED_FORM`.
"""

from __future__ import annotations

from nilscript.cycle.nil_parser import NilSyntaxError
from nilscript.strategy.hash import strategy_content_hash
from nilscript.strategy.models import (
    PREPARER,
    RESERVED_FORMS,
    ApprovalUnit,
    Approve,
    Auto,
    Conditional,
    EscalateRoute,
    Quorum,
    RejectRoute,
    Seq,
    Strategy,
    StrategyNode,
    UnitTimeout,
)
from nilscript.strategy.nil_parser import NilUnsupportedFormError, parse_strategy_nil
from nilscript.strategy.nil_printer import print_strategy_nil
from nilscript.strategy.validate import validate_strategy

__all__ = [
    "PREPARER",
    "RESERVED_FORMS",
    "ApprovalUnit",
    "Approve",
    "Auto",
    "Conditional",
    "EscalateRoute",
    "NilSyntaxError",
    "NilUnsupportedFormError",
    "Quorum",
    "RejectRoute",
    "Seq",
    "Strategy",
    "StrategyNode",
    "UnitTimeout",
    "parse_strategy_nil",
    "print_strategy_nil",
    "strategy_content_hash",
    "validate_strategy",
]
