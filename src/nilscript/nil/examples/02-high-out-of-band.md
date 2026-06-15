# Example 2 — HIGH verb, out-of-band approval, self-approval impossible
1. PROPOSE `services.send_proposal {biz_proposal_id:"prp_…"}` — Speaker declares NO amount.
2. System resolves amount = SAR 5,000 from the stored draft → PROPOSAL `tier:HIGH,
   preview.ar:"إرسال عرض «استشارات مايو» إلى أحمد — ٥٬٠٠٠ ريال عبر واتساب"`
3. COMMIT → STATUS `pending_approval`; Owner's WhatsApp receives the preview.
4. Speaker attempts DECIDE over the agent plane → MUST be rejected (403). ✅ G3
5. Owner replies "approve act_…" on WhatsApp → DECIDE via owner plane → EVENT `executed`.
Audit shows: proposed(agent:claude) → approval_requested → approved(owner:whatsapp:+966…) → executed. ✅ G6
