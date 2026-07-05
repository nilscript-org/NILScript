"""Seed the FULL governed capability catalog for ws_acme (the Sewar × ASK trading business).

This is the executable form of docs/capability-catalog-plan.md. It registers:

  * 6 reusable approval STRATEGIES (auto / single / owner-approve / two two-key quorums).
  * ~30 CAPABILITIES across the 10 domains — the complete governed surface, so the Capabilities
    page shows the whole business, not a fragment.
  * The ones with REAL executable backing on the currently-active adapters (comms + daftara) and
    the live cyc_order cycle are PUBLISHED + AI-exposed (`exposure.ai=true`) with correct verb-arg
    mappings taken from the daftara adapter SSOT (translate.py WRITE_VERBS).
  * Everything whose adapter does not exist yet (customs / SFDA / documents / warehouse / org) is
    registered as a DRAFT — fail-closed, not AI-discoverable — pointing at a `cycpending` stub. It
    lights up the moment its adapter+cycle land and someone performs the publish governance act.

Honesty rule: a capability is only PUBLISHED if a `prepare` self-check succeeds; on any failure it
is auto-downgraded to draft (so we never ship a capability the agent can pick but not run).

Run against a live control-plane DB:   python deploy/seed_catalog.py /data/controlplane.db
Run with no arg to self-validate against an in-memory store.
"""

from __future__ import annotations

import sys

WS = "ws_acme"


# --------------------------------------------------------------------------------------------------
# Strategies — authored once, referenced by id everywhere (capability.strategy is a ref, never inline)
# --------------------------------------------------------------------------------------------------
def _approve(role: str) -> dict:
    return {"form": "approve", "unit": {"by": "role", "name": role}}


def _two_key(role_a: str, role_b: str) -> dict:
    # quorum(2, distinct, of: [approve(A), approve(B)]) — two DISTINCT signatures (SoD by construction).
    return {
        "form": "quorum",
        "k": 2,
        "distinct": True,
        "of": [_approve(role_a), _approve(role_b)],
    }


STRATEGIES = {
    "AutoSmallOps": {"form": "auto", "policy": "small_ops"},   # reads / LOW only (auto forbidden > MEDIUM)
    "SingleApprove": _approve("Manager"),                       # MEDIUM writes
    "OwnerApprove": _approve("Owner"),                          # HIGH writes
    "SendApproval": _approve("Owner"),                          # comms (idempotent re-register)
    "CustomsTwoKey": _two_key("Logistics", "Finance"),          # customs / LC
    "CfoTwoKey": _two_key("Finance", "Owner"),                  # large disbursements
}


# --------------------------------------------------------------------------------------------------
# Implementing cycles for the PUBLISHED capabilities — one governed action mapping capability inputs
# to the real verb args (arg names verified against the daftara adapter SSOT). `$name` = capability input.
# --------------------------------------------------------------------------------------------------
def _flow(entry: str, verb: str, with_map: dict) -> dict:
    return {"flow": {"entry": entry, "steps": [
        {"id": entry, "type": "action", "use": verb, "with": with_map},
    ]}}


def _plan(entry: str, verb: str, with_map: dict) -> dict:
    """The EXECUTABLE plan the runner walks (auto['plan']) — a source.flow alone dispatches NOTHING
    (the runner ignores it). `$field` in the with-map binds the prepared inputs as `$.input.field`;
    `skill` is the verb's namespace (comms/crm/services/commerce/procurement)."""
    args = {k: (f"$.input.{v[1:]}" if isinstance(v, str) and v.startswith("$") else v)
            for k, v in with_map.items()}
    return {
        "wosool": "0.1", "workspace": WS, "locale": "ar", "entry": entry,
        "pipeline": [{
            "id": entry, "type": "action", "skill": verb.split(".", 1)[0], "verb": verb, "args": args,
            "next": None, "retry_policy": None, "on_error": None, "compensate_with": None,
        }],
    }


# cycle_id -> (name_en, entry, verb, with_map); both the executable plan and the .flow source derive.
_CYCLE_SPECS = {
    "sendmessagecycle": ("Send message", "Send", "comms.send_email",
                         {"to": "$to", "subject": "$subject", "body_md": "$body"}),
    "requestconfirmationcycle": ("Request confirmation", "Ask", "comms.send_email",
                                 {"to": "$to", "subject": "$subject", "body_md": "$body", "reply_token": "$order_ref"}),
    "managecontactcycle": ("Add client", "AddClient", "crm.create_client",
                           {"name": "$name", "phone": "$phone", "email": "$email"}),
    "createproductcycle": ("Create product", "AddProduct", "commerce.create_product",
                           {"name": "$name", "price": "$price", "sku": "$sku"}),
    "issueinvoicecycle": ("Issue invoice", "Invoice", "services.create_invoice",
                          {"client_id": "$client_id", "currency": "$currency", "description": "$description"}),
    "recordpaymentcycle": ("Record payment", "Pay", "commerce.record_payment",
                           {"invoice_id": "$invoice_id", "amount": "$amount", "method": "$method"}),
    "recordpurchaseinvoicecycle": ("Record purchase invoice", "PurchaseInvoice", "procurement.create_purchase_invoice",
                                   {"supplier_id": "$supplier_id", "currency": "$currency"}),
}


# cycle_id -> (name_en, plan, source). Each has a REAL executable plan (the runner walks plan, NOT
# the .flow) — an empty pipeline was why approved sends dispatched nothing. cyc_order already exists.
CYCLES = {
    cid: (name, _plan(entry, verb, wm), _flow(entry, verb, wm))
    for cid, (name, entry, verb, wm) in _CYCLE_SPECS.items()
}
# Stub for every not-yet-buildable capability — a single notify, never AI-exposed (fail-closed).
CYCLES["cycpending"] = (
    "Pending adapter",
    {"wosool": "0.1", "workspace": WS, "locale": "ar", "entry": "Pending", "pipeline": [
        {"id": "Pending", "type": "notify", "message": {"en": "Pending its adapter/cycle.", "ar": "بانتظار المُحوِّل/الدورة."}, "next": None}]},
    {"flow": {"entry": "Pending", "steps": [
        {"id": "Pending", "type": "notify", "text": "Capability pending its adapter/cycle."}]}},
)


# --------------------------------------------------------------------------------------------------
# Capability builders
# --------------------------------------------------------------------------------------------------
def _txt(name: str, required: bool = False) -> dict:
    return {"name": name, "type": {"kind": "scalar", "of": "Text"}, **({"required": True} if required else {})}


def cap(cid, domain, owner, en, ar, aliases, inputs, risk, strategy, cycle, ai):
    return {
        "nil": "capability/0.1",
        "capability_id": cid,
        "workspace": WS,
        "version": "1.0",
        "domain": domain,
        "owner_role": owner,
        "intent": {"en": en, "ar": ar},
        "aliases": aliases,
        "inputs": inputs,
        "risk": risk,
        "strategy": strategy,
        "exposure": {"ai": ai},
        "implemented_by": {"default": cycle},
    }


# --- PUBLISHED: real backing on active adapters (comms + daftara) + the live cyc_order -------------
PUBLISHED = [
    # SendMessage is (re)seeded by seed_comms_capability; we re-assert it here for a single source.
    cap("SendMessage", "Comms", "Owner",
        "Send an email or WhatsApp message to a contact",
        "إرسال بريد إلكتروني أو رسالة واتساب إلى جهة اتصال",
        ["send email", "email the client", "send whatsapp", "message the customer",
         "أرسل بريد", "ارسل ايميل", "راسل العميل", "أرسل واتساب"],
        [_txt("to", True), _txt("subject"), _txt("body", True)],
        "HIGH", "SendApproval", "sendmessagecycle", True),
    cap("RequestConfirmation", "Comms", "Owner",
        "Email a contact and correlate their reply back to this order",
        "مراسلة جهة اتصال وربط ردّها بهذا الطلب",
        ["request confirmation", "ask the supplier to confirm", "send and await reply",
         "اطلب تأكيد", "راسل المورد للتأكيد"],
        [_txt("to", True), _txt("subject"), _txt("body", True), _txt("order_ref")],
        "HIGH", "SendApproval", "requestconfirmationcycle", True),
    cap("ManageContact", "CRM", "Sales",
        "Create a customer / client contact",
        "إنشاء جهة اتصال أو عميل",
        ["add client", "create customer", "new contact", "أضف عميل", "أنشئ جهة اتصال"],
        [_txt("name", True), _txt("phone"), _txt("email")],
        "MEDIUM", "SingleApprove", "managecontactcycle", True),
    cap("CreateProduct", "Inventory", "Warehouse",
        "Onboard a new product / SKU",
        "إضافة منتج جديد",
        ["create product", "add item", "new sku", "onboard product", "أضف منتج", "أنشئ صنف"],
        [_txt("name", True), _txt("price"), _txt("sku")],
        "MEDIUM", "SingleApprove", "createproductcycle", True),
    cap("IssueInvoice", "Finance", "Finance",
        "Issue a customer invoice",
        "إصدار فاتورة للعميل",
        ["issue invoice", "create invoice", "bill the client", "أصدر فاتورة", "افتح فاتورة للعميل"],
        [_txt("client_id", True), _txt("currency", True), _txt("description")],
        "HIGH", "OwnerApprove", "issueinvoicecycle", True),
    cap("RecordPayment", "Finance", "Finance",
        "Record a payment against an invoice",
        "تسجيل دفعة على فاتورة",
        ["record payment", "log a payment", "mark invoice paid", "سجل دفعة", "أضف دفعة"],
        [_txt("invoice_id", True), _txt("amount", True), _txt("method")],
        "HIGH", "OwnerApprove", "recordpaymentcycle", True),
    cap("RecordPurchaseInvoice", "Procurement", "Procurement",
        "Record a purchase invoice from a supplier",
        "تسجيل فاتورة مشتريات من مورّد",
        ["record purchase invoice", "supplier invoice", "log a purchase", "فاتورة مشتريات", "سجل فاتورة مورد"],
        [_txt("supplier_id", True), _txt("currency", True)],
        "HIGH", "OwnerApprove", "recordpurchaseinvoicecycle", True),
    cap("RunProcurementOrder", "Procurement", "Procurement",
        "Run the governed procurement order cycle",
        "تشغيل دورة طلب الشراء المحوكمة",
        ["start a procurement order", "raise an order", "run the order cycle",
         "ابدأ طلب شراء", "شغّل دورة الطلب"],
        [_txt("order_ref"), _txt("supplier"), _txt("notes")],
        "HIGH", "OwnerApprove", "cyc_order", True),
]


# --- DRAFT: the rest of the governed surface — fail-closed until each adapter/cycle lands -----------
# (cid, domain, owner, en, ar, risk, strategy)
_DRAFTS = [
    # D2 Importation & Logistics
    ("CreateShipment", "Logistics", "Logistics", "Open an inbound shipment for a purchase order", "فتح شحنة واردة لأمر شراء", "MEDIUM", "SingleApprove"),
    ("TrackShipment", "Logistics", "Logistics", "Track a shipment's departure and arrival", "تتبع مغادرة ووصول الشحنة", "LOW", "AutoSmallOps"),
    ("ClearCustoms", "Logistics", "Logistics", "Submit and pay the customs declaration", "تقديم ودفع البيان الجمركي", "CRITICAL", "CustomsTwoKey"),
    ("PayFreight", "Logistics", "Finance", "Pay the freight forwarder", "دفع مستحقات شركة الشحن", "HIGH", "OwnerApprove"),
    ("GenerateImportDocs", "Logistics", "Logistics", "Produce bill of lading / packing list", "إصدار بوليصة الشحن وقائمة التعبئة", "MEDIUM", "SingleApprove"),
    ("ManageFreightForwarder", "Logistics", "Logistics", "Create or update a freight forwarder", "إضافة أو تعديل شركة شحن", "MEDIUM", "SingleApprove"),
    # D3 Compliance (SFDA)
    ("RegisterSFDA", "Compliance", "Compliance", "File a product SFDA registration", "تسجيل منتج لدى الهيئة (SFDA)", "HIGH", "OwnerApprove"),
    ("RenewSFDA", "Compliance", "Compliance", "Renew an expiring SFDA registration", "تجديد تسجيل هيئة الغذاء والدواء", "MEDIUM", "SingleApprove"),
    ("SubmitComplianceDoc", "Compliance", "Compliance", "Upload a regulatory document", "رفع مستند تنظيمي", "MEDIUM", "SingleApprove"),
    ("TrackSFDAStatus", "Compliance", "Compliance", "Await the authority's decision", "انتظار قرار الجهة التنظيمية", "LOW", "AutoSmallOps"),
    ("IssueCertificate", "Compliance", "Compliance", "Produce a compliance certificate", "إصدار شهادة مطابقة", "HIGH", "OwnerApprove"),
    # D4 Inventory & Stock
    ("UpdateStock", "Inventory", "Warehouse", "Adjust on-hand quantity", "تعديل الكمية المتوفرة", "MEDIUM", "SingleApprove"),
    ("CheckStockLevel", "Inventory", "Warehouse", "Read current stock levels", "عرض مستويات المخزون", "LOW", "AutoSmallOps"),
    ("ReorderStock", "Inventory", "Procurement", "Raise replenishment when stock is low", "طلب تجديد المخزون عند انخفاضه", "HIGH", "OwnerApprove"),
    ("TransferStock", "Inventory", "Warehouse", "Move stock between warehouses", "نقل المخزون بين المستودعات", "MEDIUM", "SingleApprove"),
    ("StockCount", "Inventory", "Warehouse", "Reconcile a physical stock count", "جرد المخزون الفعلي", "MEDIUM", "SingleApprove"),
    # D5 Finance (advanced)
    ("ApproveExpense", "Finance", "Finance", "Authorise an expense or disbursement", "اعتماد مصروف أو صرف", "CRITICAL", "CfoTwoKey"),
    ("OpenLetterOfCredit", "Finance", "Finance", "Open a letter of credit for an import", "فتح اعتماد مستندي لاستيراد", "CRITICAL", "CustomsTwoKey"),
    ("ReconcileAccount", "Finance", "Finance", "Reconcile a ledger account", "تسوية حساب دفتري", "MEDIUM", "SingleApprove"),
    ("GenerateFinancialReport", "Finance", "Finance", "Produce a P&L / AR-aging / cashflow report", "إصدار تقرير مالي (أرباح/أعمار ديون/تدفق نقدي)", "LOW", "AutoSmallOps"),
    # D6 Sales & CRM (advanced)
    ("CreateQuote", "Sales", "Sales", "Issue a sales quotation", "إصدار عرض سعر", "MEDIUM", "SingleApprove"),
    ("CreateSalesOrder", "Sales", "Sales", "Confirm a sale", "تأكيد عملية بيع", "HIGH", "OwnerApprove"),
    ("ScheduleDelivery", "Sales", "Logistics", "Plan an outbound delivery", "جدولة تسليم صادر", "MEDIUM", "SingleApprove"),
    ("LogInteraction", "Sales", "Sales", "Note a customer touchpoint", "تسجيل تواصل مع عميل", "LOW", "AutoSmallOps"),
    # D8 Documents
    ("GenerateDocument", "Documents", "Ops", "Render a PO / invoice / certificate PDF", "توليد مستند PDF (أمر شراء/فاتورة/شهادة)", "MEDIUM", "SingleApprove"),
    ("RequestSignature", "Documents", "Ops", "Route a document for e-signature", "إرسال مستند للتوقيع الإلكتروني", "HIGH", "OwnerApprove"),
    # D9 Org & Governance
    ("InviteUser", "Org", "Admin", "Provision a workspace user", "إضافة مستخدم لمساحة العمل", "HIGH", "OwnerApprove"),
    ("AssignRole", "Org", "Admin", "Grant or revoke a role", "منح أو سحب دور", "HIGH", "OwnerApprove"),
    ("DefinePolicy", "Org", "Admin", "Author an approval policy", "تعريف سياسة اعتماد", "CRITICAL", "CfoTwoKey"),
    # D10 Reporting & Observability
    ("GetCycleStatus", "Reporting", "Ops", "Read the live status of a run or cycle", "عرض حالة تشغيل أو دورة", "LOW", "AutoSmallOps"),
    ("GenerateKPIReport", "Reporting", "Ops", "Produce operational KPIs", "إصدار مؤشرات الأداء", "LOW", "AutoSmallOps"),
    ("GetAuditTrail", "Reporting", "Admin", "Read the signed action history", "عرض سجل الإجراءات الموقّع", "LOW", "AutoSmallOps"),
]

DRAFTS = [
    cap(cid, dom, owner, en, ar, [en.lower()], [_txt("ref")], risk, strat, "cycpending", False)
    for (cid, dom, owner, en, ar, risk, strat) in _DRAFTS
]


# --------------------------------------------------------------------------------------------------
def seed(store) -> dict:
    from nilscript.capability import Capability, capability_content_hash
    from nilscript.strategy import Strategy, strategy_content_hash

    # 1) strategies — register auto-increments an integer version; publish THAT version (never assume 1).
    for sid, root in STRATEGIES.items():
        strat = Strategy.model_validate(
            {"nil": "strategy/0.1", "strategy_id": sid, "workspace": WS, "version": 1, "root": root})
        reg = store.register_strategy(workspace=WS, strategy_id=sid,
                                      content_hash=strategy_content_hash(strat),
                                      body=strat.model_dump(by_alias=True, mode="json"),
                                      state="published")
        store.set_strategy_state(WS, sid, reg["version"], "published")

    # 2) implementing cycles — REAL executable plan (the runner walks plan; an empty pipeline
    # dispatched nothing, which is why approved sends never left the building).
    for cid, (name_en, plan, source) in CYCLES.items():
        store.register_automation(workspace=WS, automation_id=cid, content_hash=f"cat-{cid}-plan",
                                  name={"en": name_en, "ar": name_en}, plan=plan,
                                  trigger={"type": "manual"}, state="active", kind="cycle", source=source)

    # 3) capabilities — register with the target state AND pin that state on the returned version
    # (register auto-versions; a stale pre-existing row must not shadow the new one).
    def _register(c, state):
        cp = Capability.model_validate(c)
        reg = store.register_capability(workspace=WS, capability_id=cp.capability_id,
                                        content_hash=capability_content_hash(cp),
                                        body=cp.model_dump(by_alias=True, mode="json"),
                                        state=state)
        store.set_capability_state(WS, cp.capability_id, reg["version"], state)
        return cp.capability_id

    published = [_register(c, "published") for c in PUBLISHED]
    drafted = [_register(c, "draft") for c in DRAFTS]
    return {"published": published, "drafted": drafted}


def main() -> None:
    from nilscript.controlplane.store import EventStore

    path = sys.argv[1] if len(sys.argv) > 1 else ":memory:"
    store = EventStore(path)
    result = seed(store)
    print(f"PUBLISHED ({len(result['published'])}):", ", ".join(result["published"]))
    print(f"DRAFTED   ({len(result['drafted'])}):", ", ".join(result["drafted"]))

    # Honesty self-check: every published capability must `prepare` cleanly (else downgrade to draft).
    if path == ":memory:":
        from fastapi.testclient import TestClient
        from nilscript.controlplane.app import create_app

        client = TestClient(create_app(store, secret=""))
        samples = {
            "SendMessage": {"to": "a@b.com", "subject": "x", "body": "y"},
            "RequestConfirmation": {"to": "a@b.com", "subject": "x", "body": "y", "order_ref": "PO-1"},
            "ManageContact": {"name": "Acme", "phone": "+966500000000", "email": "a@b.com"},
            "CreateProduct": {"name": "Widget", "price": "10", "sku": "W-1"},
            "IssueInvoice": {"client_id": "1", "currency": "SAR", "description": "x"},
            "RecordPayment": {"invoice_id": "1", "amount": "10", "method": "cash"},
            "RecordPurchaseInvoice": {"supplier_id": "1", "currency": "SAR"},
            "RunProcurementOrder": {"order_ref": "PO-1", "supplier": "Acme", "notes": ""},
        }
        for cid, inputs in samples.items():
            r = client.post("/prepared", json={"workspace": WS, "capability_id": cid,
                                               "prepared_by": "agent", "inputs": inputs})
            print(f"PREPARE {cid}: {r.status_code} {r.text[:120]}")


if __name__ == "__main__":
    main()
