"""Typed transport-layer errors. Refusals are NOT errors — they are returned values."""


class NilTransportError(Exception):
    """Network-level failure talking to the NIL endpoint (after retries)."""


class NilTimeoutError(NilTransportError):
    """The NIL endpoint did not answer within the explicit timeout."""


class NilCircuitOpenError(NilTransportError):
    """The circuit breaker is open; no call was attempted."""


class NilProtocolError(Exception):
    """The server answer (or our request) violates the NIL contract — a bug, not weather."""
