"""The world a program is validated against: the skill registry (V4/V5) and per-workspace grant
scopes (V4). Default-deny — a verb passes only if the workspace's scopes allow it
(`nilscript.sdk.grants.scope_allows`: exact match or a `profile.*` wildcard).

Built either from the conformance corpus (`from_corpus`) or, at runtime, from the live skill
catalog + a tenant's scopes (`from_skills`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nilscript.sdk.grants import scope_allows


@dataclass(frozen=True)
class SkillSpec:
    """What the validator needs about one skill: its verbs (V4) and arg shape (V5)."""

    required_verbs: frozenset[str]
    hint_schema: dict[str, Any]
    deprecated: bool = False


@dataclass(frozen=True)
class ValidationContext:
    skills: dict[str, SkillSpec]
    read_verbs: frozenset[str]
    workspaces: dict[str, frozenset[str]]
    # NIL 0.2: verb → typed QUERY response schema (shape of a query node's `output`). Drives
    # V5 output-reference typing ($.read.output.clients[0].id). Empty ⇒ untyped read (no check).
    query_responses: dict[str, dict[str, Any]] = field(default_factory=dict)

    def skill(self, name: str) -> SkillSpec | None:
        return self.skills.get(name)

    def workspace_known(self, workspace: str) -> bool:
        return workspace in self.workspaces

    def verb_allowed(self, workspace: str, verb: str) -> bool:
        return scope_allows(self.workspaces.get(workspace, frozenset()), verb)

    def is_read_verb(self, verb: str) -> bool:
        return verb in self.read_verbs

    def response_schema_for(self, verb: str) -> dict[str, Any] | None:
        """The typed response schema for a read verb, or None if untyped (no V5 typing)."""
        return self.query_responses.get(verb)

    @classmethod
    def from_corpus(cls, raw: dict[str, Any]) -> ValidationContext:
        skills = {
            name: SkillSpec(
                required_verbs=frozenset(spec["required_verbs"]),
                hint_schema=dict(spec.get("hint_schema", {})),
                deprecated=bool(spec.get("deprecated", False)),
            )
            for name, spec in raw.get("skills", {}).items()
        }
        workspaces = {
            name: frozenset(spec.get("scopes", ()))
            for name, spec in raw.get("workspaces", {}).items()
        }
        # NIL 0.2: query_skills carry a typed response_schema; map each read verb to it, and make
        # those verbs recognised reads (so V4 admits them without a separate read_verbs entry).
        query_responses: dict[str, dict[str, Any]] = {}
        query_verbs: set[str] = set()
        for spec in raw.get("query_skills", {}).values():
            response = spec.get("response_schema")
            for verb in spec.get("required_verbs", ()):
                query_verbs.add(verb)
                if response is not None:
                    query_responses[verb] = response
        return cls(
            skills=skills,
            read_verbs=frozenset(raw.get("read_verbs", ())) | frozenset(query_verbs),
            workspaces=workspaces,
            query_responses=query_responses,
        )

    @classmethod
    def from_skills(
        cls,
        skills: dict[str, SkillSpec],
        *,
        workspace: str,
        scopes: frozenset[str],
        read_verbs: frozenset[str] = frozenset(),
    ) -> ValidationContext:
        """Single-workspace context for runtime validation of a tenant's program."""
        return cls(skills=skills, read_verbs=read_verbs, workspaces={workspace: scopes})
