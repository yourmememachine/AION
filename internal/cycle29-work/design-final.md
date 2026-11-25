# Cycle 29 design — wired at-sequence attempt after a head burn

Follow-up: cycle-28 fix-round re-review caveat — "no test pins the
WIRED at-sequence candidate reaching supersession-pending".

Coder seats (3, blind, distinct angles):
- Seat A (correctness): the literal runner shape (genesis @13,
  hookless to 15, one held-lock burn 13->15, candidate 15) is
  predicted NOT to reach exit 7: candidate is the burn's exact
  pair, retained re-presentation classifies it burned_unadopted,
  recovery depth 0 < cap 2, so it LANDS (exit 0, consumption 3,
  pin 15). Rival-hash variant -> head-regression burn (exit 4);
  cap-burned variant -> terminal refused/burned. Recommendation:
  failing-first probe; if it lands, re-scope the follow-up from
  "add pending coverage" to "pin actual behaviour + correct the
  cycle-28 claim".
- Seat B (tests): exact-pair trap confirmed (head entry not even
  relevant to reconciliation at exact pair); anti-vacuity and
  mutation criteria recorded; sibling beyond-head test comment
  must be updated once the truth is pinned.
- Seat C (adversarial): at-sequence excuse can mask an adopted
  record's disappearance at the reconciliation layer in the
  compound shape; containment is downstream. With exact pair the
  excuse is not invoked at all. Claim wording must not say the
  GPT scenario is detected at-sequence.

Reconciled build:
1. Failing-first probe test expecting exit 7 (seat A's shape),
   run, actual recorded.
2. Pin the ACTUAL wired at-sequence behaviour in a new runner
   test (whatever the probe shows, verified).
3. Correct the living claim surfaces: the beyond-head runner
   test comment (it asserts the at-sequence pending reach) and
   cycle-29 records; cycle-28 records get a correction pointer,
   not a rewrite.
