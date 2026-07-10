"""Per-tenant quotas + rate limiting — a noisy tenant cannot starve the others (the Odoo-429 lesson).

A token-bucket per (tenant, kind) bounds request rate; a per-tenant daily counter bounds volume (e.g.
exports/writes). Pure + deterministic: the clock is injected, so it is unit-testable without sleeping and
resume-safe. SaaS fairness: tenant A hitting its limit returns a refusal; tenant B is untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class TenantRateLimiter:
    """Token bucket per (tenant, kind). `rate` tokens/sec refill up to `burst`. `allow()` returns
    False when a tenant has spent its bucket — caller turns that into a per-tenant throttle refusal."""

    rate: float = 5.0
    burst: float = 20.0
    now: Callable[[], float] = lambda: 0.0  # inject a clock; tests pass a fake, prod time.monotonic
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)

    def allow(self, tenant: str, kind: str = "default", cost: float = 1.0) -> bool:
        key = (tenant, kind)
        t = self.now()
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket(tokens=self.burst, updated=t)
            self._buckets[key] = b
        b.tokens = min(self.burst, b.tokens + (t - b.updated) * self.rate)
        b.updated = t
        if b.tokens >= cost:
            b.tokens -= cost
            return True
        return False


@dataclass
class TenantQuota:
    """Per-tenant volume caps per day-bucket (e.g. {'export': 100, 'write': 5000}). `charge()` returns
    False once a tenant exhausts a kind for the current period; isolated per tenant."""

    limits: dict[str, int] = field(default_factory=dict)
    period: Callable[[], str] = lambda: "static"  # inject a period key (e.g. 'YYYY-MM-DD'); tests fix it
    _used: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def charge(self, tenant: str, kind: str, amount: int = 1) -> bool:
        limit = self.limits.get(kind)
        if limit is None:
            return True  # unmetered kind
        key = (tenant, kind, self.period())
        used = self._used.get(key, 0)
        if used + amount > limit:
            return False
        self._used[key] = used + amount
        return True

    def remaining(self, tenant: str, kind: str) -> int | None:
        limit = self.limits.get(kind)
        if limit is None:
            return None
        return max(0, limit - self._used.get((tenant, kind, self.period()), 0))
