"""Approval ceiling (parametric policy): a money-moving verb whose numeric arg exceeds a declared
cap has its tier floored to HIGH at PROPOSE, so it parks for a human DECIDE. A breach ESCALATES —
it never refuses. Here commerce.create_coupon (base tier MEDIUM) declares discount_value <= SAR 500,
so a larger discount is observably escalated to HIGH."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pocketbase_nil_adapter.edge import CapturingEmitter, create_app
from pocketbase_nil_adapter.system import FakeSystem


def _client() -> TestClient:
    return TestClient(create_app(FakeSystem(), CapturingEmitter(), bearer=None), raise_server_exceptions=False)


def _propose(client: TestClient, discount_value: object) -> dict:
    env = {"nil": "0.1", "grant": "g", "workspace": "w",
           "body": {"verb": "commerce.create_coupon",
                    "args": {"code": "SAVE", "discount_type": "fixed",
                             "discount_value": discount_value}}}
    return client.post("/nil/v0.1/propose", json=env).json()["body"]


def test_discount_over_cap_escalates_to_high() -> None:
    body = _propose(_client(), 750)  # over the SAR 500 ceiling
    assert body["outcome"] == "proposal", "a ceiling breach ESCALATES, it never refuses"
    assert body["tier"] == "HIGH", "the breaching arg floors the MEDIUM tier to HIGH (parks for a human DECIDE)"


def test_discount_under_cap_keeps_base_tier() -> None:
    body = _propose(_client(), 300)  # under the SAR 500 ceiling
    assert body["outcome"] == "proposal"
    assert body["tier"] == "MEDIUM", "under the cap, the verb's declared base tier (MEDIUM) is unchanged"


def test_discount_non_numeric_never_breaches() -> None:
    body = _propose(_client(), "not-a-number")  # non-numeric never breaches the ceiling
    assert body["outcome"] == "proposal"
    assert body["tier"] == "MEDIUM", "a non-numeric value never escalates — base tier stands"
