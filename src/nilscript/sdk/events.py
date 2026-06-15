"""Inbound EVENT handling: parsing + at-least-once dedup by (workspace, sequence)."""

from collections import OrderedDict
from typing import Any

from pydantic import ValidationError

from nilscript.sdk.errors import NilProtocolError
from nilscript.sdk.sentences import Envelope, EventBody, Performative

DEFAULT_MAX_ENTRIES = 10_000


def parse_event(wire: dict[str, Any]) -> tuple[Envelope, EventBody]:
    try:
        envelope = Envelope.model_validate(wire)
        if envelope.performative is not Performative.EVENT:
            raise NilProtocolError(f"not an EVENT sentence: {envelope.performative}")
        return envelope, EventBody.model_validate(envelope.body)
    except ValidationError as exc:
        # Fixed message — validation errors embed payload fragments (possible PII).
        raise NilProtocolError("malformed EVENT sentence") from exc


class EventDeduper:
    """Subscriptions are at-least-once; handlers must be idempotent by (workspace, sequence).

    `is_new` is synchronous with no await points — atomic on a single event loop.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max_entries
        self._seen: OrderedDict[tuple[str, int], None] = OrderedDict()

    def is_new(self, workspace: str, sequence: int) -> bool:
        key = (workspace, sequence)
        if key in self._seen:
            return False
        self._seen[key] = None
        if len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)
        return True
