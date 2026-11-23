# RE-REVIEW — Cycle 21, rev-r6 (FORCED DISSENT, after fix round)

Seat: rev-r6, forced dissent. Re-read: my original review
(review-r6.md, FIX 0.58), the reconciliation addendum at the
end of DESIGN-FINAL.md, DECISION-CONSUMPTION-HEAD.md, the
fixed code/tests (my own greps and reads, not the builders'
summaries), and review-r2.md for flip condition (6). I ran
tests/test_trust_ceremony_consume myself: 32 tests OK,
including the polymorphic head test and the B1 regression.

## Verdict: FIX (narrowed) — score 0.72

The dissent NARROWS but STANDS. It does not flip to SHIP.
The fix round genuinely closed conditions (2) and (5),
closed (6) in substance, and handled (1) honestly. What
remains is not code polish: condition (3) is unbuilt by
admission, condition (1) is unmet by construction, and
condition (4) is a pre-commitment about documents that do
not exist yet, with one already-present unqualified summary
to repair. My original terms were explicit: a provisional
code ship with 2–5 as named follow-ups narrows this FIX to
those follow-ups — it does not convert it to SHIP
retroactively. That is exactly where we are.

## Condition-by-condition judgement

### (1) External acceptance of R5 + R10 — NOT MET; disposition HONEST

External seats have not seen cycle 21. The addendum does
not pretend otherwise: it keeps the cycle PROVISIONAL, puts
F1 and F4 "to the external seats explicitly / in the brief
as an open item," and DECISION-CONSUMPTION-HEAD.md states
14–16 re-review is "the next step after cycle 21 reconciles
with the external seats." I found no internal record that
claims more than that — no BUILD-CYCLE-21.md or
REVIEW-CYCLE-21.md exists yet claiming item (3) closed.
One exception, carried under (4) below: a single sentence
in DECISION-CONSUMPTION-HEAD.md's "Why" section ("It
closes the blocking defect as an integrated-system
property…") summarises closure without the intact-home
qualifier in that sentence. That is a wording defect in an
existing record, not a false claim of external acceptance.
Judgement: the honest handling of my condition. The
condition itself remains unmet, so the claim gate remains
shut: no item-(3)-closed language, no 14–16 re-review,
until seat-gpt and seat-gemini accept the R5 wording and
the R10 residual — including F4 as an explicitly accepted
deferral, if that is their ruling.

### (2) head() trap — MET (verified independently)

My own grep over the tree: `CeremonyConsumptionLedger` no
longer defines `head()`; trust/ledger.py defines the base
`head()` (line 213), `chain_head()` (743) and
`head_target()` (761) only. Every `.head()` call site in
the tree is on a base-contract ledger (shipcheck,
health_check, anchoring, crashlab, ship tests); the only
consumption-ledger target reads are `head_target()` calls.
`head_target()` also now reloads before reading, removing
the stale-snapshot half of F2. The test
`test_head_contract_polymorphic` in
tests/test_trust_ceremony_consume.py pins the contract as
required: for an empty and a populated
CeremonyConsumptionLedger, a ShipLedger, a SigningLedger
and a CeremonyAuthorisationLedger it asserts head() is a
64-char lowercase-hex string equal to the last entry_hash
(or GENESIS_HASH when empty), that an empty consumption
ledger's head() is GENESIS_HASH with head_target() None,
and that after a real consume head_target() returns
(47, CAND_HASH) while head() stays the chain hash. I ran
it: passes, in a suite of 32 OK. Condition met, before
ceremony-journal-anchoring starts, as required.

### (3) Truthful burned-but-unmoved recovery — NOT BUILT; deferral acceptable ONLY under provisional

Nothing was built; the addendum records the named
follow-up `burned-but-unmoved-recovery-reason`, preserves
my dissent verbatim (per the addendum, in
REVIEW-CYCLE-21.md — itself not yet written, see (4)), and
puts F4 to the external seats as an open item. Is that an
acceptable deferral or a reason the internal verdict stays
FIX? Both, precisely: it is an acceptable deferral for a
PROVISIONAL code ship — the reason grammar is shared with
issuance and a fix round is the wrong place to change it —
and it is simultaneously a reason the verdict cannot
become SHIP. My flip condition (3) required a tested,
truthfully-labelled recovery path before the CLAIM ships.
A named follow-up is a promise, not a path: today the only
recovery still requires recording reason=lost_pin for a
pin that is not lost, in a MAC-bound audit record. If the
external seats explicitly accept this as a deferred
residual, condition (3) is discharged by their acceptance
(same form as condition (6)'s alternative). Until then it
stands, and any brief that presents F4 as a minor note
rather than an open item would re-open this dissent in
full.

### (4) Qualifiers travel — PARTIALLY MET; required wording stated; one existing summary already unqualified

What exists today is better than I expected. The
pin_ceremony docstrings carry the production-wiring claim
form verbatim, state the consumption journal's R10
residual precisely (rollback can lower the enforced head
for never-consumed envelopes; production mirror exception
stated), and — the C2 fix — label the issuance-journal
residual separately with its "intact issuance journal"
qualifier. DECISION-CONSUMPTION-HEAD.md's "Accepted
residuals" section carries all three qualifiers
(production wiring / not externally anchored, rollback
lowers the head for never-consumed envelopes / integrated
system, not the library function).

Two defects remain:

(a) ALREADY PRESENT, unqualified: DECISION-CONSUMPTION-
HEAD.md, "Why this location": "It closes the blocking
defect as an integrated-system property: single-use and
pin non-regression no longer depend on any history the
caller supplies…" That sentence — the one a skimming
reader will quote — omits the intact-verifier-home /
unanchored-journal qualifier entirely. The residuals
section later in the same document does not cure a
headline that travels alone; that is the exact failure
mode of F3. Amend that sentence before the brief goes
out.

(b) NOT YET WRITTEN: the brief headline and
BUILD-CYCLE-21.md. The addendum's pre-commitment ("brief
headline + BUILD record," flip condition 4) is the right
mechanism and I accept it as binding — but a commitment
is not compliance. Required wording, in substance, in
BOTH documents' headline/summary (not a footnote):

  "Item (3) is discharged only as an integrated-system
  property under production wiring (authorise via
  VerifierClient; re-anchor with the verifier-backed
  consumer; adopt the returned pin atomically), against
  an intact verifier home. The consumption journal is
  not externally anchored — a verifier-home rollback can
  lower the enforced head for never-consumed envelopes —
  until ceremony-journal-anchoring lands. Research mode
  is not rollback-protected and is outside this claim.
  Burned-but-unmoved recovery still requires the
  lost_pin label (open follow-up
  burned-but-unmoved-recovery-reason). Cycle 21 is
  PROVISIONAL pending external acceptance of this
  scoping."

Any summary of item (3) lacking the production-wiring,
intact-home, or unanchored elements — in either document —
fails this condition regardless of correct fine print
elsewhere in the same file.

### (5) Liveness in figures — MET (verified)

The ceremony_consume mode docstring in
trust/verifier_main.py now states, numerically:
"Liveness figures, stated numerically: the envelope TTL
is hard-capped at 900 s, and every ceremony now needs TWO
verifier-availability windows inside that life — one to
authorise, one to consume. A failed or lost consume burns
the issuance pair, and recovery needs a new ceremony_id
plus a new evidence artefact; the client never retries a
consume automatically." That is the figure set F7
demanded (900 s cap, two windows, per-failure burn cost).
One carry-over: pin_ceremony's docstring still says only
"inside the envelope's TTL" without the number — the
BUILD record must repeat the numeric form (it is part of
the (4) documents), at which point F7 is fully closed,
docstring half done, build-record half pending with (4).

### (6) Non-builder re-probe — MET IN SUBSTANCE; addendum's "discharges" accepted with one literal caveat

review-r2.md records a genuinely independent re-probe:
rev-r2's own openssl driver code (prefixes re-typed), the
named divergent rows reproduced, and "FULL-table re-probe:
all 51 rows, ours and openssl, zero mismatches against the
pinned pairs," plus independent KAT verification. That is
what F5 asked for in substance, and it predates the fix
round — the pinned pairs were not changed by the fix round
(A2/A3 touched the capability probe and the message-flip
dimension, not the pairs), so the re-probe still covers
them. Literal caveat, for the record: my condition said
"recorded in the test file, or external-seat acceptance in
its place." The recording lives in review-r2.md, not the
test file. I accept the review record as an equivalent
recording — it is, if anything, better provenance — but
the addendum's word "discharges" should be read with that
substitution noted, and a one-line pointer in the test
file header to review-r2.md's re-probe would close the
letter as well. This caveat does not block.

### The fix round's HIGH (rev-r3 stderr oracle) — FIXED, verified

Not my finding; credit to rev-r3. Verified myself:
trust/verifier_main.py carries the "No per-reason output
anywhere — not even stderr" discipline at the consume
mode, and test_invalid_envelopes_indistinguishable_to_caller
asserts BYTE-IDENTICAL stdout error documents AND
byte-identical stderr for a bad-signature vs a
binding-mismatch envelope, asserts the single code
ceremony_authorisation_invalid, asserts the leak strings
(signature_mismatch, payload_hash_mismatch,
authorisation_id_mismatch, "verify reasons") are absent,
and asserts nothing was consumed. It passes in the 32-test
suite I ran. This is the correct regression shape.

## Final position

Dissent STANDS, NARROWED to the claim gate. Score 0.58 →
0.72: the code findings I raised are fixed or honestly
deferred, and the reconciliation does not overclaim
external acceptance. It does not flip to SHIP, under
exactly these remaining conditions:

1. Seat-gpt and seat-gemini see cycle 21 with the R5 claim
   wording, the R10 residual, and F4 as an open item, and
   accept them as discharging CROSS-CHECK-14 item (3) —
   including explicit acceptance of the F4 deferral, or
   `burned-but-unmoved-recovery-reason` lands and is
   tested end-to-end (burn → crash before adoption →
   truthfully-labelled recovery → success).
2. The brief headline and BUILD-CYCLE-21.md carry the (4)
   wording in substance, the liveness figures in numeric
   form, and the DECISION-CONSUMPTION-HEAD.md "Why"
   sentence is amended with the intact-home qualifier.
3. Until 1 and 2: the internal record stays PROVISIONAL,
   item (3) is not described as closed, and 14–16
   re-review does not start.

Meet 1–2 and this seat flips to SHIP without a further
code round. Ship the claim, or start 14–16, before then
and the dissent re-opens at its original width.

— rev-r6, forced dissent, cycle 21 re-review
