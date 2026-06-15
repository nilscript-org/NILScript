# Example 4 — Ambiguous reference: Candidates, never guesses
The merchant says (in any language): "delete the black shirt". Two products match.
1. PROPOSE `commerce.delete_product {product_id:"القميص الأسود"}`
2. Deterministic resolution: live lookup + recent-entities pool both return 2 matches; the
   bounded disambiguator cannot separate them (or times out) →
   PROPOSAL `outcome:refusal, code:AMBIGUOUS,
   candidates:[{id:"prd_812", name:"قميص أسود — قطن", source:"live_catalog"},
               {id:"prd_977", name:"قميص أسود — حرير", source:"recent_entities"}]`
3. The Speaker relays the choice to the human; the human picks the cotton one.
4. PROPOSE `commerce.delete_product {product_id:"prd_812"}` → PROPOSAL `tier:CRITICAL`
   (destructive floor) → COMMIT → parks → Owner approves → cooling delay → EVENT `executed`.
✅ §6.3 (three outcomes; fabrication defense), §7.3 (destructive ⇒ park + cooling)

Counter-case locked by conformance tests: a disambiguator answer of `prd_999` (not in the
candidate set) is treated as disambiguator failure → the same AMBIGUOUS refusal. The model
can choose; it can never introduce.
