"""Skill resolution (Wave 4 §14.3b / Encaps D3) — the lookups the compiler performs when a cycle calls
`comms.send(...)`. Semantic-first: the skill is named by meaning; its `resolves_to` lists candidate
verbs; an explicit `via:` at the call site picks one. Pure functions over `Capability`/`Skill`; the
compiler refuses the compile when resolution is ambiguous or empty (never guesses a verb — invariant I2).
"""

from __future__ import annotations

from nilscript.capability.models import Capability, Skill


def resolve_skill(capability: Capability, name: str) -> Skill | None:
    """The named public operation on a capability, or None if the capability exposes no such skill (→
    the compiler refuses: a cycle cannot call a skill the capability doesn't declare)."""
    for skill in capability.skills:
        if skill.name == name:
            return skill
    return None


def resolve_skill_verb(skill: Skill, via: str | None = None) -> str | None:
    """The concrete verb a skill call lowers to (D3):
      · `via` given → it must be one of the skill's `resolves_to` candidates (else None — refuse an
        override the skill doesn't sanction);
      · no `via`, exactly one candidate → that verb;
      · no `via`, many candidates → None (ambiguous — the compiler asks for a `via`, never guesses).
    """
    if via is not None:
        return via if via in skill.resolves_to else None
    if len(skill.resolves_to) == 1:
        return skill.resolves_to[0]
    return None
