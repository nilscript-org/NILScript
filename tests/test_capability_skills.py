"""The Skill layer (Wave 4 §14.3b): named operations on a capability with a per-Skill governance
envelope (D5) + semantic-first resolution (D3). The model makes an under-governed skill (below the
capability floor, I3) and a non-verb effect unrepresentable; the resolvers are the exact lookups the
compiler performs (refuse — never guess — on an unknown skill or an ambiguous `via`).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nilscript.capability import (
    Capability,
    GovernanceEnvelope,
    Skill,
    resolve_skill,
    resolve_skill_verb,
)


def _env(tier="MEDIUM", effects=("comms.send_email",), reversibility="COMPENSABLE") -> GovernanceEnvelope:
    return GovernanceEnvelope(tier=tier, reversibility=reversibility, effects=tuple(effects))


def _skill(name="send", resolves_to=("comms.send_email",), env=None) -> Skill:
    return Skill(
        name=name,
        intent={"en": "Send a message", "ar": "إرسال رسالة"},
        resolves_to=tuple(resolves_to),
        envelope=env or _env(),
    )


def _cap(*, risk="MEDIUM", skills=()) -> Capability:
    return Capability(
        nil="capability/0.1", capability_id="Communication", workspace="acme", version="2.0",
        domain="Ops", owner_role="Ops", intent={"en": "Communicate", "ar": "تواصل"},
        risk=risk, strategy="AutoSmallOps", skills=tuple(skills),
        implemented_by={"default": "CommunicationCycle"},
    )


# ── Envelope (D5) ─────────────────────────────────────────────────────────────────────────────────
def test_envelope_effects_must_be_verb_ids() -> None:
    with pytest.raises(ValidationError, match="verb ids"):
        GovernanceEnvelope(tier="LOW", effects=("NotAVerb",))


def test_envelope_defaults_to_irreversible() -> None:
    assert GovernanceEnvelope(tier="HIGH").reversibility == "IRREVERSIBLE"


# ── Skill model ───────────────────────────────────────────────────────────────────────────────────
def test_skill_resolves_to_must_be_verb_ids() -> None:
    with pytest.raises(ValidationError, match="resolves_to must be verb ids"):
        _skill(resolves_to=("Bogus",))


def test_capability_carries_skills() -> None:
    cap = _cap(skills=[_skill(), _skill(name="notify", resolves_to=("comms.send_whatsapp",))])
    assert [s.name for s in cap.skills] == ["send", "notify"]


# ── I3: tier floor + uniqueness ───────────────────────────────────────────────────────────────────
def test_duplicate_skill_names_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate skill names"):
        _cap(skills=[_skill(name="send"), _skill(name="send")])


def test_skill_below_capability_floor_rejected() -> None:
    # Capability floor HIGH; a LOW skill would lower the governance — refused (I3).
    with pytest.raises(ValidationError, match="below the capability risk floor"):
        _cap(risk="HIGH", skills=[_skill(env=_env(tier="LOW"))])


def test_skill_at_or_above_floor_allowed() -> None:
    cap = _cap(risk="MEDIUM", skills=[_skill(env=_env(tier="CRITICAL"))])
    assert cap.skills[0].envelope.tier == "CRITICAL"


def test_capability_without_skills_still_valid() -> None:
    # Wrapped v0 capabilities omit skills — the field is optional, existing catalog unaffected.
    assert _cap().skills == ()


# ── Resolution (D3, what the compiler calls) ──────────────────────────────────────────────────────
def test_resolve_skill_by_name() -> None:
    cap = _cap(skills=[_skill(name="send")])
    assert resolve_skill(cap, "send").name == "send"
    assert resolve_skill(cap, "ghost") is None


def test_semantic_resolution_single_candidate() -> None:
    assert resolve_skill_verb(_skill(resolves_to=("comms.send_email",))) == "comms.send_email"


def test_ambiguous_resolution_needs_a_via() -> None:
    s = _skill(resolves_to=("comms.send_email", "comms.send_whatsapp"))
    assert resolve_skill_verb(s) is None  # ambiguous → compiler asks for a via
    assert resolve_skill_verb(s, via="comms.send_whatsapp") == "comms.send_whatsapp"


def test_via_must_be_a_sanctioned_candidate() -> None:
    s = _skill(resolves_to=("comms.send_email",))
    assert resolve_skill_verb(s, via="comms.send_carrier_pigeon") is None  # unsanctioned → refused
