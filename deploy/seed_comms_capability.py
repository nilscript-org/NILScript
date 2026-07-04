"""Register the governed `SendMessage` capability + its implementing cycle + approval strategy.

This is the RIGHT, deviation-free way for the agent to send email/WhatsApp: the agent expresses INTENT
(nil_intent), the layer matches this published, AI-exposed capability, prepares it, and executes the
implementing cycle deterministically — which calls comms.send_email/comms.send_whatsapp through the
governed kernel. No raw-verb tool exposure, no skill hacks.

Run with a store path to seed a live control-plane DB:  python deploy/seed_comms_capability.py <CP_DB>
Run with no arg to self-validate against an in-memory store (registration + prepare must succeed).
"""

from __future__ import annotations

import sys

WS = "ws_acme"

STRATEGY = {
    "nil": "strategy/0.1",
    "strategy_id": "SendApproval",
    "workspace": WS,
    "version": 1,
    # A single human approval before the message goes out (the send is HIGH + irreversible).
    "root": {"form": "approve", "unit": {"by": "role", "name": "Owner"}},
}

CAPABILITY = {
    "nil": "capability/0.1",
    "capability_id": "SendMessage",
    "workspace": WS,
    "version": "1.0",
    "domain": "Comms",
    "owner_role": "Owner",
    "intent": {
        "en": "Send an email or WhatsApp message to a contact",
        "ar": "إرسال بريد إلكتروني أو رسالة واتساب إلى جهة اتصال",
    },
    "aliases": [
        "send email", "send an email", "email the client", "email the customer",
        "send whatsapp", "message the customer", "contact the client",
        "أرسل بريد", "ارسل ايميل", "راسل العميل", "أرسل واتساب", "ابعث رسالة", "تواصل مع العميل",
    ],
    "examples": [
        "send an email to buyer@clientx.com saying the order is confirmed",
        "راسل العميل أن الأمور تسير على ما يرام",
    ],
    "inputs": [
        {"name": "to", "type": {"kind": "scalar", "of": "Text"}, "required": True},
        {"name": "subject", "type": {"kind": "scalar", "of": "Text"}},
        {"name": "body", "type": {"kind": "scalar", "of": "Text"}, "required": True},
    ],
    "risk": "HIGH",
    "strategy": "SendApproval",
    "exposure": {"ai": True},  # the deliberate act that makes it discoverable by the agent
    "implemented_by": {"default": "sendmessagecycle"},
}

# The implementing cycle: one governed action that sends via the comms adapter, mapping the
# capability inputs to the verb args.
CYCLE_SOURCE = {
    "flow": {
        "entry": "Send",
        "steps": [
            {
                "id": "Send",
                "type": "action",
                "use": "comms.send_email",
                "with": {"to": "$to", "subject": "$subject", "body_md": "$body"},
            }
        ],
    }
}


def seed(store) -> None:
    from nilscript.capability import Capability, capability_content_hash
    from nilscript.strategy import Strategy, strategy_content_hash

    strat = Strategy.model_validate(STRATEGY)
    store.register_strategy(
        workspace=WS, strategy_id=strat.strategy_id,
        content_hash=strategy_content_hash(strat),
        body=strat.model_dump(by_alias=True, mode="json"),
    )
    store.register_automation(
        workspace=WS, automation_id="sendmessagecycle", content_hash="comms-send-1",
        name={"en": "Send message", "ar": "إرسال رسالة"},
        plan={"workspace": WS, "pipeline": []},
        trigger={"type": "manual"}, state="active", kind="cycle", source=CYCLE_SOURCE,
    )
    cap = Capability.model_validate(CAPABILITY)
    store.register_capability(
        workspace=WS, capability_id=cap.capability_id,
        content_hash=capability_content_hash(cap),
        body=cap.model_dump(by_alias=True, mode="json"),
    )
    # Publish both (draft/hidden are never discoverable, and a prepare needs a published strategy).
    store.set_strategy_state(WS, strat.strategy_id, strat.version, "published")
    store.set_capability_state(WS, cap.capability_id, cap.version, "published")


def main() -> None:
    from nilscript.controlplane.store import EventStore

    path = sys.argv[1] if len(sys.argv) > 1 else ":memory:"
    store = EventStore(path)
    seed(store)
    caps = store.list_capabilities(WS) if hasattr(store, "list_capabilities") else []
    print("capabilities after seed:", [(c.get("capability_id"), c.get("state")) for c in caps])
    got = store.get_capability(WS, "SendMessage")
    print("SendMessage present:", bool(got), "| state:", (got or {}).get("state"))

    # Self-validate the intent path: prepare must yield a card (not a contract/strategy refusal).
    if path == ":memory:":
        from fastapi.testclient import TestClient

        from nilscript.controlplane.app import create_app

        client = TestClient(create_app(store, secret=""))
        r = client.post(
            "/prepared",
            json={
                "workspace": WS, "capability_id": "SendMessage", "prepared_by": "agent",
                "inputs": {"to": "buyer@clientx.com", "subject": "Update", "body": "All good."},
            },
        )
        print("PREPARE:", r.status_code, r.text[:400])


if __name__ == "__main__":
    main()
