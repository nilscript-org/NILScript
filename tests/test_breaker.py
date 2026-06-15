"""Circuit breaker state machine with a fake clock."""

from nilscript.sdk.breaker import BreakerState, CircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_breaker(clock: FakeClock) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=3, recovery_seconds=30.0, clock=clock)


def test_starts_closed_and_allows() -> None:
    breaker = make_breaker(FakeClock())
    assert breaker.state is BreakerState.CLOSED
    assert breaker.allow()


def test_opens_after_consecutive_failures() -> None:
    breaker = make_breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow()


def test_success_resets_failure_count() -> None:
    breaker = make_breaker(FakeClock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED


def test_half_open_after_recovery_then_closes_on_success() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31.0
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED


def test_half_open_failure_reopens() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31.0
    assert breaker.allow()
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow()
