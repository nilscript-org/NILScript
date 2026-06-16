"""Wosool DSL AST: typed, frozen, unknown-member-rejecting program and node models.

These models ARE the V1 structural gate — parsing a program with `WosoolProgram.model_validate`
performs the schema check (closed objects, enums, id/verb patterns, per-type required fields via a
discriminated union). The semantic passes (V2-V6: references, acyclicity, whitelist, arg typing,
reachability) run over the parsed model in `validator`.

Mirrors the discipline of `nilscript.sdk.sentences.NilModel` (frozen, extra forbidden). Inline-array
branch sugar (`on_true: [ ...nodes ]`) is deferred — v0.1 supports node-id branch targets only.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NODE_ID_PATTERN = r"^step_[0-9]+$"
VERB_PATTERN = r"^[a-z]+\.[a-z_]+$"
LANG_VERSION = "0.1"


class DslModel(BaseModel):
    """Base for every DSL shape: immutable, unknown members rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RetryPolicy(DslModel):
    max_attempts: int = Field(ge=1, le=10)
    backoff: Literal["exponential", "fixed"] = "exponential"
    initial_seconds: float = Field(default=2.0, ge=0)


class NodeErrorPolicy(DslModel):
    action: Literal["halt", "continue", "route", "compensate"]
    to: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


class BilingualText(DslModel):
    ar: str = Field(min_length=1)
    en: str | None = None


class CompensateWith(DslModel):
    """SEQRD-PC: the inverse action that undoes this step during a saga unwind (`on_error:
    compensate`). A verb + (possibly reference-bearing) args — executed via PROPOSE→COMMIT /
    ROLLBACK. Absence means the step is IRREVERSIBLE (it blocks a full unwind, honestly)."""

    verb: str = Field(pattern=VERB_PATTERN)
    args: dict[str, Any] = Field(default_factory=dict)


class ActionNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["action"]
    skill: str = Field(pattern=r"^[a-z][a-z_]*$")
    verb: str = Field(pattern=VERB_PATTERN)
    args: dict[str, Any]
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)
    retry_policy: RetryPolicy | None = None
    on_error: NodeErrorPolicy | None = None
    compensate_with: CompensateWith | None = None


class QueryNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["query"]
    verb: str = Field(pattern=VERB_PATTERN)
    args: dict[str, Any] = Field(default_factory=dict)
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)
    retry_policy: RetryPolicy | None = None
    on_error: NodeErrorPolicy | None = None


class ConditionNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["condition"]
    expression: str = Field(min_length=1)
    on_true: str = Field(pattern=NODE_ID_PATTERN)
    on_false: str | None = Field(default=None, pattern=NODE_ID_PATTERN)
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


class ParallelNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["parallel"]
    branches: tuple[str, ...] = Field(min_length=2, max_length=64)
    join: Literal["all", "any"] = "all"
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)

    @model_validator(mode="after")
    def _branches_are_node_ids(self) -> ParallelNode:
        import re

        bad = [b for b in self.branches if not re.match(NODE_ID_PATTERN, b)]
        if bad:
            raise ValueError(f"branch targets must be step_N ids, got {bad}")
        return self


class ForeachNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["foreach"]
    items: str = Field(min_length=1)
    as_: str = Field(alias="as", pattern=r"^[a-z][a-z0-9_]*$")
    body: str = Field(pattern=NODE_ID_PATTERN)
    max_items: int = Field(ge=1, le=1000)
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


class AwaitApprovalNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["await_approval"]
    proposal: str = Field(min_length=1)
    timeout_seconds: int = Field(default=86400, ge=1, le=2_592_000)
    on_approved: str = Field(pattern=NODE_ID_PATTERN)
    on_rejected: str | None = Field(default=None, pattern=NODE_ID_PATTERN)
    on_timeout: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


class WaitNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["wait"]
    seconds: int = Field(ge=1, le=2_592_000)
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


class NotifyNode(DslModel):
    id: str = Field(pattern=NODE_ID_PATTERN)
    type: Literal["notify"]
    message: BilingualText
    next: str | None = Field(default=None, pattern=NODE_ID_PATTERN)


# The closed node set. A discriminated union on `type` makes an unknown type unrepresentable and
# enforces each variant's required fields — the structural half of V1.
NodeType = (
    ActionNode
    | QueryNode
    | ConditionNode
    | ParallelNode
    | ForeachNode
    | AwaitApprovalNode
    | WaitNode
    | NotifyNode
)
Node = Annotated[NodeType, Field(discriminator="type")]


class WosoolProgram(DslModel):
    wosool: Literal["0.1"]
    workspace: str = Field(min_length=1)
    locale: str = "ar"
    entry: str = Field(pattern=NODE_ID_PATTERN)
    pipeline: tuple[Node, ...] = Field(min_length=1, max_length=256)
    on_error: Literal["halt", "continue", "compensate"] = "halt"

    @model_validator(mode="after")
    def _ids_are_unique(self) -> WosoolProgram:
        ids = [node.id for node in self.pipeline]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate node ids: {dupes}")
        return self

    @property
    def nodes(self) -> dict[str, NodeType]:
        """id → node. Safe because `_ids_are_unique` guarantees no collisions."""
        return {node.id: node for node in self.pipeline}
