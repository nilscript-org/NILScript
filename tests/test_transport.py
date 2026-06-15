"""Transport resilience: bounded retry, no-retry on 4xx, breaker short-circuit."""

import httpx
import pytest
import respx
from nilscript.sdk.breaker import BreakerState, CircuitBreaker
from nilscript.sdk.errors import NilCircuitOpenError, NilProtocolError, NilTransportError
from nilscript.sdk.transport import NilTransport

BASE = "https://os.example.sa"


async def no_sleep(_: float) -> None:
    return None


def make_transport(breaker: CircuitBreaker | None = None) -> NilTransport:
    return NilTransport(
        base_url=BASE,
        bearer_secret="secret",
        timeout=1.0,
        max_retries=2,
        breaker=breaker or CircuitBreaker(failure_threshold=5, recovery_seconds=30.0),
        sleep=no_sleep,
    )


@respx.mock
async def test_post_success_carries_bearer_and_returns_json() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/propose").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    result = await make_transport().post_sentence("/nil/v0.1/propose", {"nil": "0.1"})
    assert result == {"ok": True}
    assert route.calls.last.request.headers["authorization"] == "Bearer secret"


@respx.mock
async def test_retries_503_then_succeeds() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/propose")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    result = await make_transport().post_sentence("/nil/v0.1/propose", {})
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_retries_429_then_succeeds() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/commit")
    route.side_effect = [httpx.Response(429), httpx.Response(200, json={"ok": True})]
    result = await make_transport().post_sentence("/nil/v0.1/commit", {})
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_exhausted_retries_raise_transport_error() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/propose").mock(return_value=httpx.Response(503))
    with pytest.raises(NilTransportError):
        await make_transport().post_sentence("/nil/v0.1/propose", {})
    assert route.call_count == 3  # initial + 2 retries


@respx.mock
async def test_4xx_is_protocol_error_without_retry() -> None:
    route = respx.post(f"{BASE}/nil/v0.1/propose").mock(return_value=httpx.Response(400))
    with pytest.raises(NilProtocolError):
        await make_transport().post_sentence("/nil/v0.1/propose", {})
    assert route.call_count == 1


@respx.mock
async def test_breaker_opens_then_short_circuits() -> None:
    breaker = CircuitBreaker(failure_threshold=3, recovery_seconds=30.0)
    transport = make_transport(breaker)
    respx.post(f"{BASE}/nil/v0.1/propose").mock(return_value=httpx.Response(503))
    with pytest.raises(NilTransportError):
        await transport.post_sentence("/nil/v0.1/propose", {})
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(NilCircuitOpenError):
        await transport.post_sentence("/nil/v0.1/propose", {})
    assert respx.calls.call_count == 3  # the open breaker attempted no HTTP call


@respx.mock
async def test_get_status_success() -> None:
    respx.get(f"{BASE}/nil/v0.1/status/prop-1").mock(
        return_value=httpx.Response(200, json={"proposal": "prop-1", "state": "executed"})
    )
    result = await make_transport().get("/nil/v0.1/status/prop-1")
    assert result["state"] == "executed"


@respx.mock
async def test_non_object_response_is_protocol_error() -> None:
    respx.post(f"{BASE}/nil/v0.1/propose").mock(return_value=httpx.Response(200, json=[1, 2]))
    with pytest.raises(NilProtocolError):
        await make_transport().post_sentence("/nil/v0.1/propose", {})
