# Decision — Protected Gate scope EXTENDED
Date: 2026-11-22. Decided by Dilip in the main chat: asked directly, he delegated the call ("do whatever is the best decision"). Decision taken: EXTEND.

The gate will hold its own protected operator-authority list and verify evidence provenance itself, from a protected source. It must no longer accept the operator list and the "independent evidence" from the same caller — the circularity ChatGPT and Gemini both flagged (CROSS-CHECK-9/10) and the reason cycles 14-16 are held.

Consequences:
- Item A (cycle 13, gate path canonicalisation + P-1/P-2 duplicate-key loaders) may ship once the extension lands and the war room reconciles.
- Cycles 14+15+16 (snapshot chain-gap, pin ceremony, ceremony hardening) are re-reviewed for shipping only AFTER the extended gate lands and passes review. They stay HELD until then — do not ship them on the old gate.
- The pin ceremony's independent operator authority and authenticated evidence provenance are to be sourced from the extended gate's protected store.
- Implementation follows the standing process: >=3 coder seats building together, war room >=6 reviewers from other pods + ChatGPT and Gemini as blind external seats, reconciled unanimous verdict before anything ships.
