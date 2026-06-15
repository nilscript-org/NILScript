# Example 5 — DECIDE with modification: the human counter-offers
1. PROPOSE `commerce.create_coupon {code:"EID25", discount_type:"percentage",
   discount_value:25}`
2. Workspace rule: discounts above 20% ⇒ HIGH → PROPOSAL `tier:HIGH,
   modifiable:["discount_value","expiry_date"],
   preview.ar:"إنشاء كوبون EID25 — خصم ٢٥٪ بلا حد استخدام"`
3. COMMIT → parks; the Owner's WhatsApp shows the preview with reply affordances.
4. Owner replies on the Approval Surface: *approve, but make it 15%* →
   DECIDE `{approved:true, modification:{discount_value:15}, actor:"owner:whatsapp:+9665…"}`
5. The System re-resolves and re-tiers the modified action: 15% is below the workspace
   threshold → executes; EVENT `modified` then `executed` with the re-rendered preview in
   the audit trail.
✅ §7.4 (modification bounded to `modifiable`; re-resolve + re-tier), §10 (decision actor +
channel + modification audited)

Counter-case: DECIDE attempting `modification:{code:"FREE100"}` is rejected — `code` is not
in the verb's modifiable facts.
