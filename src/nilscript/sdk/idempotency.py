"""The NIL idempotency protocol (02-NIL-CLIENT).

NIL_UUID = sha256(session_id + request_timestamp + command_index). Generated exactly
once when a skill emits a batch, persisted with the conversation turn, and reused
verbatim by every retry — Temporal or otherwise — so a timeout can never double-send.
"""

import hashlib


def nil_uuid(session_id: str, request_timestamp: str, command_index: int) -> str:
    material = f"{session_id}:{request_timestamp}:{command_index}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def batch_tokens(session_id: str, request_timestamp: str, count: int) -> tuple[str, ...]:
    """Tokens for one multi-intent batch; command_index orders intents within it."""
    return tuple(nil_uuid(session_id, request_timestamp, i) for i in range(count))


def commit_idempotency_key(session_id: str, proposal_id: str) -> str:
    """The deterministic COMMIT key for (session, proposal). The proposal id is stable and
    globally unique, so it fills the timestamp slot here (one commit per proposal per session).
    Both the chat-confirm path and the MCP tool MUST mint the key this way — identical inputs
    replay the same COMMIT sentence, so a duplicate confirm never double-commits."""
    return nil_uuid(session_id, proposal_id, 0)
