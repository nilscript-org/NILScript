# Example 6 — Human takeover suspends the Speaker
1. A human support agent takes over a customer conversation (owner plane act).
   System emits EVENT `handoff_human {scope:"conversation:cnv_44"}`; the scope is suspended.
2. The Speaker, mid-plan, sends COMMIT for a previously-proposed
   `commerce.send_message` in that conversation →
   PROPOSAL `outcome:refusal, code:SUSPENDED`. No side effect.
3. The human finishes; the owner plane resumes the scope → EVENT `resumed`.
4. The Speaker may re-PROPOSE; the old proposal has meanwhile expired →
   COMMIT against it would refuse with `EXPIRED`.
✅ §12 (Speaker cannot lift its own suspension), §6.6 (expiry), Annex A
