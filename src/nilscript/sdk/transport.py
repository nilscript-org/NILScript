"""Resilient HTTP transport for the NIL binding (spec §13).

Every call: explicit timeout + bounded jittered retry + circuit breaker. Retries cover
transport faults, 429 and 5xx only; COMMIT retries are safe because the idempotency key
is supplied by the caller and reused verbatim. 4xx is our bug — abort immediately.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from nilscript.sdk.breaker import CircuitBreaker
from nilscript.sdk.errors import (
    NilCircuitOpenError,
    NilProtocolError,
    NilTimeoutError,
    NilTransportError,
)

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE_SECONDS = 0.2

RETRIABLE_STATUS = frozenset({429, 500, 502, 503, 504})

AsyncSleep = Callable[[float], Awaitable[None]]


class NilTransport:
    def __init__(
        self,
        *,
        base_url: str,
        bearer_secret: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        breaker: CircuitBreaker | None = None,
        backoff_base: float = DEFAULT_BACKOFF_BASE_SECONDS,
        sleep: AsyncSleep = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._breaker = breaker if breaker is not None else CircuitBreaker()
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._rng = rng
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {bearer_secret}"},
        )

    async def post_sentence(self, path: str, wire: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", path, json=wire)

    async def get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if not self._breaker.allow():
                raise NilCircuitOpenError(f"circuit open for {path}")
            if attempt > 0:
                await self._sleep(self._backoff_base * (2**attempt) * (1.0 + self._rng()))
            try:
                response = await self._client.request(method, path, json=json)
            except httpx.TimeoutException as exc:
                self._breaker.record_failure()
                last_error = NilTimeoutError(f"{method} {path} timed out")
                last_error.__cause__ = exc
                continue
            except httpx.TransportError as exc:
                self._breaker.record_failure()
                last_error = NilTransportError(f"{method} {path} transport failure: {exc}")
                last_error.__cause__ = exc
                continue
            if response.status_code in RETRIABLE_STATUS:
                self._breaker.record_failure()
                last_error = NilTransportError(f"{method} {path} → HTTP {response.status_code}")
                continue
            if response.is_client_error:
                raise NilProtocolError(f"{method} {path} → HTTP {response.status_code} (our bug)")
            self._breaker.record_success()
            payload = response.json()
            if not isinstance(payload, dict):
                raise NilProtocolError(f"{method} {path}: response body is not a JSON object")
            return payload
        assert last_error is not None
        raise last_error
