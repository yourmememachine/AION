# Decision — Protected Gate scope EXTENDED
Date: 2026-11-22. Decided by Dilip in the main chat: asked directly, he delegated the call ("do whatever is the best decision"). Decision taken: EXTEND.

The gate will hold its own protected operator-authority list and verify evidence provenance itself, from a protected source. It must no longer accept the operator list and the "independent evidence" from the same caller — the circularity ChatGPT and Gemini both flagged (CROSS-CHECK-9/10) and the reason cycles 14-16 are held.

Consequences:
- Item A (cycle 13, gate path canonicalisation + P-1/P-2 duplicate-key loaders) may ship once the extension lands and the war room reconciles.
- Cycles 14+15+16 (snapshot chain-gap, pin ceremony, ceremony hardening) are re-reviewed for shipping only AFTER the extended gate lands and passes review. They stay HELD until then — do not ship them on the old gate.
- The pin ceremony's independent operator authority and authenticated evidence provenance are to be sourced from the extended gate's protected store.
- Implementation follows the standing process: >=3 coder seats building together, war room >=6 reviewers from other pods + ChatGPT and Gemini as blind external seats, reconciled unanimous verdict before anything ships.

## Ratification (2026-11-23)
Dilip was presented the as-built substitution (operator list in the verifier's protected env config, not a list inside the gate) with both external seats' positions (Gemini: the placement is the right call, the literal reading would be a security regression; ChatGPT: ratification itself is required). Dilip's answer: "Do the best." Recorded as RATIFIED: the verifier-env authority model stands as the accepted interpretation of this decision.

## Standing rule — decisions go to the war room (Dilip, 2026-11-23)
Dilip, asked to decide the consumption head's store location: "Don't ask me discuss in the war room and take decision not now anytime do the same." Recorded as a standing rule for AION (and his projects generally): do NOT bring design/store-location decisions to Dilip. The war room (internal seats + ChatGPT + Gemini as blind seats) discusses and decides; the decision and its reasoning go in the project records. Dilip is informed of outcomes in the normal updates, not asked for approvals mid-build. Applied immediately: the consumption head's store location is decided by the war room — the verifier-owned form (route-4) is the leading candidate on the existing record.
