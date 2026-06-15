# Example 1 — LOW verb, auto-execute, idempotent retry
Speaker: any MCP client. Exchange (envelopes elided to bodies):
1. PROPOSE `services.create_client {name:"Ahmed Al-Saudi", phone:"+966555123456"}`
2. PROPOSAL `tier:LOW, preview.ar:"إنشاء عميل جديد: Ahmed Al-Saudi (+966555123456)"`
3. COMMIT `idempotency_key:"k-1"` → EVENT `executed {party_id:"pty_…"}`
4. COMMIT same key (network retry) → identical outcome replayed, no second client. ✅ G4
