"""The baseline capability catalog — the versioned SSOT of what EVERY workspace gets.

This is the data half of the baseline bundle (see nilscript.baseline.apply_baseline): the
governed capability surface (8 published + 32 fail-closed drafts across 10 domains), the 6
reusable approval strategies they reference, and the implementing cycles with REAL executable
plans. It is the library form of deploy/seed_catalog.py, parameterized by workspace so the
identical baseline materializes for workspace #1 and #10,000.

Change discipline: any edit here is a baseline change — bump nilscript.baseline.BASELINE_VERSION
in the same commit, and the reconcile applier rolls it out per-workspace.
"""

from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------------------------------
# Strategies — authored once, referenced by id everywhere (capability.strategy is a ref, never inline)
# --------------------------------------------------------------------------------------------------
def _approve(role: str) -> dict[str, Any]:
    return {"form": "approve", "unit": {"by": "role", "name": role}}


def _two_key(role_a: str, role_b: str) -> dict[str, Any]:
    # quorum(2, distinct, of: [approve(A), approve(B)]) — two DISTINCT signatures (SoD by construction).
    return {
        "form": "quorum",
        "k": 2,
        "distinct": True,
        "of": [_approve(role_a), _approve(role_b)],
    }


STRATEGIES: dict[str, dict[str, Any]] = {
    "AutoSmallOps": {"form": "auto", "policy": "small_ops"},  # reads / LOW only (auto forbidden > MEDIUM)
    "SingleApprove": _approve("Manager"),                      # MEDIUM writes
    "OwnerApprove": _approve("Owner"),                         # HIGH writes
    "SendApproval": _approve("Owner"),                         # comms (idempotent re-register)
    "CustomsTwoKey": _two_key("Logistics", "Finance"),         # customs / LC
    "CfoTwoKey": _two_key("Finance", "Owner"),                 # large disbursements
}


# --------------------------------------------------------------------------------------------------
# Implementing cycles — one governed action mapping capability inputs to the real verb args
# (arg names verified against the daftara adapter SSOT). `$name` = capability input.
# --------------------------------------------------------------------------------------------------
def _flow(entry: str, verb: str, with_map: dict[str, Any]) -> dict[str, Any]:
    return {"flow": {"entry": entry, "steps": [
        {"id": entry, "type": "action", "use": verb, "with": with_map},
    ]}}


def _plan(workspace: str, entry: str, verb: str, with_map: dict[str, Any]) -> dict[str, Any]:
    """The EXECUTABLE plan the runner walks (auto['plan']) — a source.flow alone dispatches NOTHING
    (the runner ignores it). `$field` in the with-map binds the prepared inputs as `$.input.field`;
    `skill` is the verb's namespace (comms/crm/services/commerce/procurement)."""
    args = {k: (f"$.input.{v[1:]}" if isinstance(v, str) and v.startswith("$") else v)
            for k, v in with_map.items()}
    return {
        "wosool": "0.1", "workspace": workspace, "locale": "ar", "entry": entry,
        "pipeline": [{
            "id": entry, "type": "action", "skill": verb.split(".", 1)[0], "verb": verb, "args": args,
            "next": None, "retry_policy": None, "on_error": None, "compensate_with": None,
        }],
    }


# cycle_id -> (name_en, entry, verb, with_map); both the executable plan and the .flow source derive.
_CYCLE_SPECS: dict[str, tuple[str, str, str, dict[str, Any]]] = {
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


def cycles_for(workspace: str) -> dict[str, tuple[str, dict[str, Any], dict[str, Any]]]:
    """cycle_id -> (name_en, plan, source), workspace-bound. Each has a REAL executable plan (the
    runner walks plan, NOT the .flow) — an empty pipeline was why approved sends dispatched nothing."""
    out = {
        cid: (name, _plan(workspace, entry, verb, wm), _flow(entry, verb, wm))
        for cid, (name, entry, verb, wm) in _CYCLE_SPECS.items()
    }
    # Stub for every not-yet-buildable capability — a single notify, never AI-exposed (fail-closed).
    out["cycpending"] = (
        "Pending adapter",
        {"wosool": "0.1", "workspace": workspace, "locale": "ar", "entry": "Pending", "pipeline": [
            {"id": "Pending", "type": "notify",
             "message": {"en": "Pending its adapter/cycle.", "ar": "بانتظار المُحوِّل/الدورة."}, "next": None}]},
        {"flow": {"entry": "Pending", "steps": [
            {"id": "Pending", "type": "notify", "text": "Capability pending its adapter/cycle."}]}},
    )
    return out


# --------------------------------------------------------------------------------------------------
# Capability builders
# --------------------------------------------------------------------------------------------------
def _txt(name: str, required: bool = False) -> dict[str, Any]:
    return {"name": name, "type": {"kind": "scalar", "of": "Text"}, **({"required": True} if required else {})}


def _cap(workspace, cid, domain, owner, en, ar, aliases, inputs, risk, strategy, cycle, ai):  # type: ignore[no-untyped-def]
    return {
        "nil": "capability/0.1",
        "capability_id": cid,
        "workspace": workspace,
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


def published_for(workspace: str) -> list[dict[str, Any]]:
    """PUBLISHED: real backing on active adapters (comms + daftara) + the live cyc_order."""
    return [
        _cap(workspace, "SendMessage", "Comms", "Owner",
             "Send an email or WhatsApp message to a contact",
             "إرسال بريد إلكتروني أو رسالة واتساب إلى جهة اتصال",
             ["send email", "email the client", "send whatsapp", "message the customer",
              "أرسل بريد", "ارسل ايميل", "راسل العميل", "أرسل واتساب"],
             [_txt("to", True), _txt("subject"), _txt("body", True)],
             "HIGH", "SendApproval", "sendmessagecycle", True),
        _cap(workspace, "RequestConfirmation", "Comms", "Owner",
             "Email a contact and correlate their reply back to this order",
             "مراسلة جهة اتصال وربط ردّها بهذا الطلب",
             ["request confirmation", "ask the supplier to confirm", "send and await reply",
              "اطلب تأكيد", "راسل المورد للتأكيد"],
             [_txt("to", True), _txt("subject"), _txt("body", True), _txt("order_ref")],
             "HIGH", "SendApproval", "requestconfirmationcycle", True),
        _cap(workspace, "ManageContact", "CRM", "Sales",
             "Create a customer / client contact",
             "إنشاء جهة اتصال أو عميل",
             ["add client", "create customer", "new contact", "أضف عميل", "أنشئ جهة اتصال"],
             [_txt("name", True), _txt("phone"), _txt("email")],
             "MEDIUM", "SingleApprove", "managecontactcycle", True),
        _cap(workspace, "CreateProduct", "Inventory", "Warehouse",
             "Onboard a new product / SKU",
             "إضافة منتج جديد",
             ["create product", "add item", "new sku", "onboard product", "أضف منتج", "أنشئ صنف"],
             [_txt("name", True), _txt("price"), _txt("sku")],
             "MEDIUM", "SingleApprove", "createproductcycle", True),
        _cap(workspace, "IssueInvoice", "Finance", "Finance",
             "Issue a customer invoice",
             "إصدار فاتورة للعميل",
             ["issue invoice", "create invoice", "bill the client", "أصدر فاتورة", "افتح فاتورة للعميل"],
             [_txt("client_id", True), _txt("currency", True), _txt("description")],
             "HIGH", "OwnerApprove", "issueinvoicecycle", True),
        _cap(workspace, "RecordPayment", "Finance", "Finance",
             "Record a payment against an invoice",
             "تسجيل دفعة على فاتورة",
             ["record payment", "log a payment", "mark invoice paid", "سجل دفعة", "أضف دفعة"],
             [_txt("invoice_id", True), _txt("amount", True), _txt("method")],
             "HIGH", "OwnerApprove", "recordpaymentcycle", True),
        _cap(workspace, "RecordPurchaseInvoice", "Procurement", "Procurement",
             "Record a purchase invoice from a supplier",
             "تسجيل فاتورة مشتريات من مورّد",
             ["record purchase invoice", "supplier invoice", "log a purchase", "فاتورة مشتريات", "سجل فاتورة مورد"],
             [_txt("supplier_id", True), _txt("currency", True)],
             "HIGH", "OwnerApprove", "recordpurchaseinvoicecycle", True),
        _cap(workspace, "RunProcurementOrder", "Procurement", "Procurement",
             "Run the governed procurement order cycle",
             "تشغيل دورة طلب الشراء المحوكمة",
             ["start a procurement order", "raise an order", "run the order cycle",
              "ابدأ طلب شراء", "شغّل دورة الطلب"],
             [_txt("order_ref"), _txt("supplier"), _txt("notes")],
             "HIGH", "OwnerApprove", "cyc_order", True),
    ]


# --- DRAFT: the rest of the governed surface — fail-closed until each adapter/cycle lands -----------
# (cid, domain, owner, en, ar, risk, strategy)
_DRAFTS: list[tuple[str, str, str, str, str, str, str]] = [
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


def drafts_for(workspace: str) -> list[dict[str, Any]]:
    return [
        _cap(workspace, cid, dom, owner, en, ar, [en.lower()], [_txt("ref")], risk, strat, "cycpending", False)
        for (cid, dom, owner, en, ar, risk, strat) in _DRAFTS
    ]
