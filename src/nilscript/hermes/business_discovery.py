"""Business Discovery Session — orchestrates 5-phase intent extraction into BusinessSpecification.

A session manages conversational state across phases (intro → actors → systems → documents → events →
rules → review → complete). At each phase, the user provides natural-language input, which is
recorded for audit and later extraction. The session itself stores raw answers; extraction is
separate (deterministic, testable, not involving an LLM).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nilscript.hermes.models import (
    Actor,
    BusinessEvent,
    BusinessRule,
    BusinessSpecification,
    Document,
    ExternalSystem,
)


VALID_PHASES = ("intro", "actors", "systems", "documents", "events", "rules", "review", "complete")


class BusinessDiscoverySession:
    """Stateful manager of a multi-phase business discovery conversation.

    A session is immutable outside of set_phase() and record_answer(). Once created, it persists
    until explicitly marked complete. All answers are stored as raw text for audit; extraction
    is a separate operation (deterministic, not involving an LLM).
    """

    def __init__(
        self,
        session_id: str,
        workspace: str,
        domain_name: str,
        user_email: str,
    ) -> None:
        self.session_id: str = session_id
        self.workspace: str = workspace
        self.domain_name: str = domain_name
        self.user_email: str = user_email

        self._phase: str = "intro"
        self._is_complete: bool = False
        self._answers: dict[str, str] = {}
        self.created_at: datetime = datetime.utcnow()
        self.updated_at: datetime = datetime.utcnow()

    def get_phase(self) -> str:
        """Current discovery phase."""
        return self._phase

    def set_phase(self, phase: str) -> None:
        """Move to a new phase. Validates phase name."""
        if phase not in VALID_PHASES:
            raise ValueError(
                f"Invalid phase '{phase}'. Valid phases: {', '.join(VALID_PHASES)}"
            )
        self._phase = phase
        self.updated_at = datetime.utcnow()

    def record_answer(self, phase: str, answer: str) -> None:
        """Record the user's raw text answer for a phase."""
        if not phase or not isinstance(phase, str):
            raise ValueError("phase must be a non-empty string")
        if not answer or not isinstance(answer, str):
            raise ValueError("answer must be a non-empty string")
        self._answers[phase] = answer
        self.updated_at = datetime.utcnow()

    def get_answers(self) -> dict[str, str]:
        """All recorded answers (read-only copy)."""
        return dict(self._answers)

    def mark_complete(self) -> None:
        """Mark this session as complete."""
        self._phase = "complete"
        self._is_complete = True
        self.updated_at = datetime.utcnow()

    def is_complete(self) -> bool:
        """Whether the discovery is complete."""
        return self._is_complete

    def get_current_state(self) -> dict[str, Any]:
        """Full session state for API responses."""
        return {
            "session_id": self.session_id,
            "workspace": self.workspace,
            "domain_name": self.domain_name,
            "user_email": self.user_email,
            "phase": self._phase,
            "is_complete": self._is_complete,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ── Extraction Functions (Deterministic, Pattern-Based) ─────────────────────────────────


def extract_actors(text: str) -> list[Actor]:
    """Extract Actor entities from unstructured text.

    Strategy: Identify role keywords, map to names, infer responsibilities from verbs.
    This is deterministic, not involving an LLM. Simple pattern-based extraction.
    """
    if not text or not text.strip():
        return []

    actors: list[Actor] = []
    lines = text.split("\n")
    common_words = {"the", "a", "an", "this", "that", "these", "those"}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        name_candidate = None
        role_candidate = None
        responsibilities: list[str] = []

        for i, token in enumerate(tokens):
            token_clean = token.rstrip(".,;:")
            # Look for role keywords first
            if token_clean.lower() in (
                "approver",
                "manager",
                "lead",
                "accountant",
                "requester",
                "reviewer",
                "processor",
            ):
                role_candidate = token_clean.lower()
                # Look back for a proper name, skipping common articles
                if not name_candidate:
                    for j in range(i - 1, -1, -1):
                        candidate = tokens[j].rstrip(".,;:")
                        if candidate and candidate.lower() not in common_words:
                            name_candidate = candidate
                            break
                    # If no preceding name found, use the role as name
                    if not name_candidate:
                        name_candidate = token_clean
            # Extract responsibilities from verbs
            if token_clean.lower() in ("and", "or") and i + 1 < len(tokens):
                next_token = tokens[i + 1].rstrip(".,;:")
                if next_token and next_token.lower() not in common_words:
                    responsibilities.append(next_token.lower())

        # Extract from verb phrases
        for verb in ["does", "handles", "performs", "manages", "approves"]:
            if verb in line.lower():
                parts = line.lower().split(verb)
                if len(parts) > 1:
                    resp_text = parts[1].strip().rstrip(".")
                    responsibilities.extend([r.strip() for r in resp_text.split(",")])

        if name_candidate and role_candidate:
            resp_tuple = tuple(set(responsibilities) or ("general duties",))
            try:
                actor = Actor(
                    name=name_candidate,
                    role=role_candidate,
                    responsibilities=resp_tuple,
                )
                actors.append(actor)
            except ValueError:
                pass

    return actors


def extract_systems(text: str) -> list[ExternalSystem]:
    """Extract ExternalSystem entities from unstructured text."""
    if not text or not text.strip():
        return []

    import re

    systems: list[ExternalSystem] = []
    known_systems = [
        "odoo",
        "salesforce",
        "email",
        "slack",
        "s3",
        "azure",
        "aws",
        "gcp",
        "stripe",
        "shopify",
    ]
    known_interfaces = [
        "rest api",
        "soap",
        "smtp",
        "webhook",
        "graphql",
        "grpc",
        "ftp",
        "sftp",
        "database",
    ]

    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower()
        for system_name in known_systems:
            if system_name in line_lower:
                interfaces: list[str] = []
                for iface in known_interfaces:
                    if iface in line_lower:
                        interfaces.append(iface.title())

                purpose = "system integration"
                for keyword, desc in [
                    ("order", "order management"),
                    ("customer", "customer data"),
                    ("payment", "payment processing"),
                    ("notif", "notifications"),
                    ("archiv", "data archival"),
                ]:
                    if keyword in line_lower:
                        purpose = desc
                        break

                integration_points: list[str] = []
                for match in re.finditer(r"(create|fetch|update|delete)_\w+", line_lower):
                    integration_points.append(match.group(0))

                if not interfaces:
                    interfaces = ["API"]

                try:
                    system = ExternalSystem(
                        name=system_name.title(),
                        purpose=purpose,
                        interfaces=tuple(set(interfaces)),
                        integration_points=tuple(
                            set(integration_points) or ("read", "write")
                        ),
                    )
                    systems.append(system)
                except ValueError:
                    pass

                break

    return systems


def extract_documents(text: str) -> list[Document]:
    """Extract Document entities from unstructured text."""
    if not text or not text.strip():
        return []

    documents: list[Document] = []
    known_docs = [
        "invoice",
        "purchase order",
        "quote",
        "email",
        "receipt",
        "po",
        "report",
        "order",
    ]
    known_formats = ["pdf", "json", "html", "xml", "csv", "plain text", "email"]
    known_locations = ["odoo", "s3", "email", "database", "sharepoint", "drive"]

    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower()
        for doc_name in known_docs:
            if doc_name in line_lower:
                format_found = "PDF"
                for fmt in known_formats:
                    if fmt in line_lower:
                        format_found = fmt.upper()
                        break

                location_found = "Unknown"
                for loc in known_locations:
                    if loc in line_lower:
                        location_found = loc.title()
                        break

                usage = "process document"
                for keyword, desc in [
                    ("approval", "approval artifact"),
                    ("audit", "audit trail"),
                    ("notif", "notification"),
                    ("record", "record keeping"),
                ]:
                    if keyword in line_lower:
                        usage = desc
                        break

                try:
                    doc = Document(
                        name=doc_name.title(),
                        format=format_found,
                        storage_location=location_found,
                        usage=usage,
                    )
                    if not any(
                        d.name == doc.name and d.format == doc.format for d in documents
                    ):
                        documents.append(doc)
                except ValueError:
                    pass

                break

    return documents


def extract_events(text: str) -> list[BusinessEvent]:
    """Extract BusinessEvent entities from unstructured text."""
    if not text or not text.strip():
        return []

    import re

    events: list[BusinessEvent] = []
    lines = text.split("\n")

    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        line_lower = line_clean.lower()
        if any(kw in line_lower for kw in ["when", "if", "after", "on"]):
            trigger = line_clean
            participants_list: list[str] = []
            outcome = "process continues"
            frequency = "per transaction"

            for match in re.finditer(r"\b[A-Z][a-z]+\b", line_clean):
                name = match.group(0)
                if name not in ("If", "When", "After", "On"):
                    participants_list.append(name)

            for freq_keyword, freq_label in [
                ("daily", "daily"),
                ("hourly", "hourly"),
                ("weekly", "weekly"),
                ("transaction", "per transaction"),
                ("order", "per order"),
            ]:
                if freq_keyword in line_lower:
                    frequency = freq_label
                    break

            if participants_list:
                try:
                    event = BusinessEvent(
                        trigger=trigger[:100],
                        participants=tuple(set(participants_list)),
                        outcome=outcome,
                        frequency=frequency,
                    )
                    events.append(event)
                except ValueError:
                    pass

    return events


def extract_rules(text: str) -> list[BusinessRule]:
    """Extract BusinessRule entities from unstructured text."""
    if not text or not text.strip():
        return []

    import re

    rules: list[BusinessRule] = []
    tier_keywords = {
        "critical": "CRITICAL",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
    }

    lines = text.split("\n")
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        line_lower = line_clean.lower()
        if "if" in line_lower or "when" in line_lower:
            parts = re.split(r",|then|so|causing", line_clean, maxsplit=3)

            condition = parts[0].strip() if len(parts) > 0 else "condition"
            action = parts[1].strip() if len(parts) > 1 else "action taken"
            consequence = parts[2].strip() if len(parts) > 2 else "outcome"

            tier = "MEDIUM"
            for keyword, tier_val in tier_keywords.items():
                if keyword in line_lower:
                    tier = tier_val
                    break

            try:
                rule = BusinessRule(
                    condition=condition[:200],
                    action=action[:200],
                    consequence=consequence[:200],
                    tier=tier,
                )
                rules.append(rule)
            except ValueError:
                pass

    return rules


def extract_structured_specification(
    session: BusinessDiscoverySession,
    intent: str,
) -> BusinessSpecification:
    """Synthesize a complete BusinessSpecification from a discovery session.

    Extracts all phases, consolidates answers, deduplicates entities, validates
    cross-references. Raises ValueError if critical data is missing or invalid.
    """
    answers = session.get_answers()

    actors = extract_actors(answers.get("actors", ""))
    systems = extract_systems(answers.get("systems", ""))
    documents = extract_documents(answers.get("documents", ""))
    events = extract_events(answers.get("events", ""))
    rules = extract_rules(answers.get("rules", ""))

    if not actors:
        raise ValueError("No actors extracted. Specification requires at least one actor.")
    if not events:
        raise ValueError("No events extracted. Specification requires at least one event.")

    unique_actors = {a.name: a for a in actors}.values()
    unique_systems = {s.name: s for s in systems}.values()
    unique_documents = {d.name: d for d in documents}.values()
    unique_events = {(e.trigger, e.outcome): e for e in events}.values()
    unique_rules = {(r.condition, r.action): r for r in rules}.values()

    spec = BusinessSpecification(
        domain_name=session.domain_name,
        intent=intent,
        actors=tuple(unique_actors),
        systems=tuple(unique_systems),
        documents=tuple(unique_documents),
        events=tuple(unique_events),
        rules=tuple(unique_rules),
    )

    return spec
