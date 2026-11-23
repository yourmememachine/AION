# REVIEW — Cycle 21, rev-r6 (FORCED DISSENT, blind)

Seat: rev-r6, forced dissent. I did not build this cycle. I did
not read any other cycle-21 review. Sources: CROSS-CHECK-14,
DESIGN-FINAL (cycle 21), DECISION-CONSUMPTION-HEAD,
REVIEW-CYCLE-20, and the built code/tests named in my brief.
Suite as reported to me: 1464 tests OK (skipped=28), baseline
1406.

## Verdict: FIX — score 0.58

Not a code-quality rejection. Most of what was built is built
well (see Concessions). The dissent is that the cycle's central
claim — seat-gpt's cycle-20 item (3) condition is now met —
is asserted in a scoped form of exactly the kind seat-gpt
refused last cycle, the recovery story requires a false
reason label in the one incident case it exists for, and a
known polymorphic trap is being shipped into the follow-up
that is supposed to complete this work. Ship the code if the
room insists; do NOT ship the claim, and do not start the
14–16 re-review on this basis, until the flip conditions
below are met.

## Findings

### F1 — HIGH. The "integrated system" framing is the cycle-20 scope manoeuvre, one level up

Seat-gpt, cycle 20 (CROSS-CHECK-14, item (3), FIX 0.96,
blocking): a demonstrated replay that regresses protected
state is "an active defect in the integrated system, not a
deferrable enhancement; two-of-three legs is not partial
credit on a single replay-resistance guarantee." The
reconciliation adds the process finding: the narrower scope
reading elsewhere does not override the external FIX.

Cycle 21's answer (DESIGN-FINAL R5, DECISION-CONSUMPTION-HEAD
"Accepted residuals", pin_ceremony docstring): single-use
and non-regression are "properties of the INTEGRATED SYSTEM
under its production wiring … not properties of reanchor_pin
for an arbitrary caller-supplied callable. A no-op callable
gets no protection."

The verifier-side half of this is real (see Concessions).
But the guarantee's subject does not yet exist as code:
`grep` over the tree finds NO production caller of
`reanchor_pin` outside tests — the loop/storage layer that
is supposed to do the wiring is future work. So the claim
being shipped is: a property of a system whose integrating
component has not been written, conditional on that
component choosing the right callable, adopting the pin
atomically, and reading a fresh pin — three caller
obligations (production wiring, ATOMIC-ADOPTION, FRESH-PIN)
that remain unverifiable in-process, exactly as
COMPLETE-HISTORY was in cycle 20. The cycle replaced
"caller-supplied history the function treats as authority"
with "caller-supplied code the function treats as authority,
plus caller obligations the function cannot check." That is
an improvement in kind (a no-op callable is self-sabotage by
the caller, like supplying its own signing key — the R5
analogy has genuine force, and I concede it), but it is a
difference of degree presented as a difference of category:
GPT's condition was about the integrated system, and the
integrated system is still the part that isn't built. In
cycle 20, "binds only 14–16" scoping was refused as a way to
narrow an external FIX; in cycle 21, "binds only under
production wiring that does not exist yet" is accepted as a
way to satisfy one. What distinguishes the two, honestly:
the enforcement point moved inside the trust boundary, so a
correctly-wired caller now gets the guarantee for real.
What does not distinguish them: in both cases the external
condition is declared met by re-scoping the claim to the
subset where it holds, before the external seat has seen
and accepted the re-scoping. That acceptance is the missing
step, and it is not this room's to grant itself.

### F2 — MEDIUM. `CeremonyConsumptionLedger.head()` is a shipped trap with the follow-up's name on it

`HashChainJournal.head()` returns the chain head HASH
(hex64 str); every generic consumer in the tree relies on
that contract (`HashChainJournal._append` writes it as
`prev_hash`; shipcheck compares it to an expected head;
health_check slices it `ledger.head()[:12]`).
`CeremonyConsumptionLedger` overrides `head()` to return a
`(new_cycle_seq, new_payload_hash)` tuple, or `None` for an
empty journal. The subclass repairs its own `_append` to use
`chain_head()`, and today's anchoring code happens to walk
`entries()` via `_chain_prefixes` rather than calling
`head()` — so nothing live breaks today. That is precisely
the problem: the trap is latent, typed to fail silently or
confusingly (a tuple compared against a hex64 anchor head is
a mismatch, not an error; `None` vs GENESIS_HASH likewise),
and it sits in the exact class the named follow-up
`ceremony-journal-anchoring` will hand to generic anchoring /
audit / health code written against the base-class contract.
The class docstring discloses the override — disclosure of a
trap is not removal of it, and this project has repeatedly
paid for "documented, therefore fine" contract breaks.
Compounding detail: the overridden `head()` also does NOT
reload, unlike the ledger's other reads (`find_by_*`,
`entries()` consumers in the mode reload or are per-request
fresh), so a long-lived instance's `head()` is a stale
snapshot answer wearing an authoritative name. Rename the
method (`head_target()`), restore `head()` to the base
contract, and pin the polymorphic contract with a test —
this is a one-hour fix now and a debugging session inside
the anchoring cycle later.

### F3 — MEDIUM-HIGH (residual, honestly disclosed; claim still overstates). The head is monotonic only over an intact verifier home

GPT's condition: the head "cannot be replaced by
caller-supplied history." Met in letter — the caller cannot
supply it. But the head lives in an unanchored journal in
the verifier home, and the deployment reality splits:

- Production: the signing-ledger mirror is anchored, and —
  credit where due — the consume mode checks the mirror
  (scoped kind="consume" + format="ceremony-consumption")
  in step (5), so a consumption-journal rollback cannot
  resurrect a consumed envelope. That leg is genuinely
  closed in production.
- Production, the other half: the mirror entry carries the
  envelope's payload_hash, NOT the candidate (seq, hash).
  Nothing anchored records the head target. A verifier-home
  rollback therefore lowers the enforced head for
  never-consumed envelopes undetectably — DESIGN-FINAL R10
  and the ledger docstring state this precisely, and I do
  not call it hidden. I call it what it is: the monotonicity
  guarantee is "monotonic, provided the store it lives in
  was not rolled back," which is the same qualifier the
  cycle-19/20 issuance journal carried while GPT was
  refusing two-of-three legs.
- Research mode: no anchor requirement at all, the mirror
  itself is unanchored, and a verifier-home rollback
  resurrects consumed envelopes silently. The docstring
  says research "must never be described as
  rollback-protected" — good wording, but any summary that
  says "cycle 21 closes item (3)" without the mode qualifier
  will describe it as exactly that.

Grade: the gap between claim and reality is disclosed in
the fine print and overstated in the headline. Item (3)
should be recorded as "closed in production wiring against
an intact verifier home; head monotonicity itself
unanchored until ceremony-journal-anchoring" — or the
anchoring follow-up should be pulled into this cycle's
ship gate. Pick one; the current wording picks neither.

### F4 — MEDIUM-HIGH. The burned-but-unmoved recovery requires lying about the reason, and the honest path is structurally refused

DESIGN-FINAL R3's recovery story: after a burned-but-unmoved
crash, recovery is "a no-pin lost_pin ceremony whose
candidate is AHEAD of the head." Walk it through the built
code. The caller still HAS its pin — nothing was lost. The
truthful ceremony, chain_gap_recovery against the real pin,
is impossible: the envelope's old pin sits behind the
consumption head (o_seq < H_seq), and check_head refuses it
as ceremony_head_regression. So the only working recovery
requires the operator to (a) present old_pin=None, (b)
record reason=lost_pin for a pin that is not lost, and
(c) accept everything the no-pin path skips — no strict
recomputation, no relation gates — i.e. the recovery path
for the exact incident the crash contract creates runs with
WEAKER binding than a normal ceremony, and writes a false
statement into a MAC-bound audit record that later readers
will trust. A recovery procedure whose first step is
mislabelling the incident is a design defect, not a
"narrowing … accepted and recorded" (R3's words). The price
of a head that cannot be restaged may indeed be that the
burned target is never re-anchorable; it is not necessary
that the price also be a corrupted audit vocabulary. Fix
directions (room's choice): a dedicated reason
(e.g. consumption_burned) with its own gates, or an old-pin
rule exception where the consumption journal itself proves
the caller's pin is the pre-burn pin of the burned entry.
Until one exists and is tested end-to-end, the crash
contract's "Recovery is a new ceremony" sentence promises
more than the code honestly delivers.

### F5 — LOW-MEDIUM. The differential suite's independence is thinner than its framing

The suite is good work and the security-relevant half —
ours=False on every adversarial row — is non-negotiable and
builder-independent. But: (a) the openssl half of every
pinned pair was probed BY THE BUILDER, on this VM, against
openssl 3.0.13 — the same binary the tests then assert
against. A probe-method error (wrapper, DER prefix, pkeyutl
flags) would be pinned as expectation and ratified forever;
the (False, True) divergent rows rest on that probe alone.
(b) The 1023-byte KAT: "verified against the RFC text" by
the builder is a single transcription checked by a single
reader. Mitigating, and conceded: the KAT literal is
corroborated in-build by two independent implementations
(ours and openssl both reproduce the signature byte-
identically, and the R8 guard would have blocked a literal
disagreeing with both), so the KAT itself carries real
weight. The adversarial pairs carry less: no second
prober, no second openssl version, no second source for the
probe record. One non-builder re-probe, recorded, closes
this; as shipped, "independence anchor" (the test file's
own words) overstates a builder-probed oracle.

### F6 — MEDIUM (process). Provisional-upon-provisional, again

Cycle 20 shipped PROVISIONAL on the external poll; the poll
returned a blocking FIX; cycle 21 now proposes to ship the
fix and — per DECISION-CONSUMPTION-HEAD — treat 14–16
re-review as "the next step after cycle 21 reconciles with
the external seats." Good: that sentence exists. But the
internal record must not get ahead of it: cycles 17 and 18
remain provisional, 14–16 held, 20's item (3) closure is
claimed by the same room whose cycle-20 scoping GPT
rejected, and cycle 21 also touches shared gate code (the
R9 permission-predicate widening in load_signing_key) that
provisional gate cycles depend on. Nothing in cycle 21's
ceremony path depends on unshipped 17/18 behaviour — I
checked; the dependency is the other way (shared loaders),
which is worse for blast radius, not better. The pattern
rev-r6 flagged in cycle 20 — ship on internal ratification,
let the external verdict catch up — is one reconciled poll
away from repeating. The flip condition is cheap: this
cycle's verdict stays PROVISIONAL, in writing, until
seat-gpt and seat-gemini have seen the R5 claim wording and
the R10 residual and accepted them as discharging item (3).

### F7 — MEDIUM. The liveness cost is real, quantifiable, and stated everywhere except numerically where it matters

The design accepted: the verifier is now on the critical
path of EVERY ceremony, as a SECOND availability window.
Envelopes carry a hard TTL cap of 900 seconds
(CEREMONY_AUTHORISATION_TTL_MAX_SECONDS). Issuance already
needed the verifier; consumption now needs it again, inside
the same ≤15-minute envelope life, via a subprocess spawn
with a 30 s client timeout and a never-retry rule. A
verifier outage, a transient spawn failure, or a lost
response inside that window does not merely delay the
ceremony: the issuance-side (ceremony_id, evidence_hash)
pair is already burned, so recovery costs a new ceremony_id
AND a new evidence artefact — and if the consume actually
committed, F4's mislabelled recovery on top. The records
state "fails closed when the verifier is unreachable" and
"inside the envelope's TTL" (pin_ceremony docstring, R5)
but nowhere put the number — 900 s, one window, cost per
failure = one burned issuance pair + one fresh evidence
bundle — next to the safety gains they enumerate at length.
Safety got paragraphs; liveness got an adjective. For a
ceremony whose entire purpose is recovering from incidents,
an unquantified dependency on a live second process during
the incident is a cost the owner should see in figures.

## Concessions — what is genuinely closed

- The verifier-owned consumption journal is the right store,
  and the commit-point discipline is real: append_consumption
  re-checks single-use AND the head rules against freshly
  reloaded entries inside the retry loop; the concurrent
  loser surfaces as already-consumed; K1–K6 and the
  two-process race are tested, including mirror-failure-
  after-commit burning the envelope.
- The re-mint laundering route (fresh envelope, same target)
  is closed by the candidate rule; the fork-at-head and
  old-pin-behind rules are implemented as designed and
  tested (test_trust_ceremony_consume covers each R3 branch
  I probed).
- The mirror-scoping trap (R4) was caught in design and the
  mode's step (5) mirror check is correctly scoped to
  kind="consume" + format="ceremony-consumption".
- reanchor_pin's integration is disciplined: required
  keyword, None/non-callable refuses before envelope
  verification, consumer invoked exactly once after all local
  checks, exceptions propagate as refusal with nothing
  returned; the test helper's default consumer is a real
  ledger-backed consumer, not an always-succeed fake (R12
  honoured).
- Validation order and the single invalid-code discipline in
  ceremony_consume match R2; issuance-presence with field
  match is checked at consumption, which cycle 20 lacked.
- R9's derivation-overlap set and seed-loader fd discipline
  are implemented as ruled, with the residual wording
  ("catches accidents and known derivations") intact.
- The differential suite's ours=False adversarial coverage,
  full bit-flip sweep, and byte-identical sign direction are
  substantive; F5 is about the oracle's provenance, not the
  coverage.

## Flip conditions — what turns this seat to SHIP

1. EXTERNAL ACCEPTANCE OF THE SCOPING. Seat-gpt and
   seat-gemini are polled on cycle 21 with the R5 claim
   wording and the R10/F3 residual in the brief, and accept
   them as discharging CROSS-CHECK-14 item (3) — or the
   internal record keeps cycle 21 PROVISIONAL and does not
   describe item (3) as closed, and 14–16 re-review does not
   start. (Same form as my cycle-20 flip condition; it was
   the right condition then too.)
2. HEAD() TRAP REMOVED. The target accessor is renamed off
   the base-class contract (or head() is restored to the
   hash and the target gets a new name), with a test pinning
   that every HashChainJournal subclass's head() returns the
   chain hash. Before ceremony-journal-anchoring starts, not
   during it.
3. TRUTHFUL RECOVERY. A recovery path for
   burned-but-unmoved exists whose ceremony record states
   the true situation (dedicated reason or a journal-proven
   old-pin exception), tested end-to-end:
   burn → crash before adoption → recovery ceremony →
   success, with the record's reason accurate.
4. CLAIM WORDING. Everywhere item (3) is summarised, the
   qualifier travels with it: production wiring, intact
   verifier home, head monotonicity unanchored until the
   anchoring follow-up; research mode never in scope of the
   claim.
5. LIVENESS IN FIGURES. The pin_ceremony docstring / build
   record states the number: ≤900 s envelope life, second
   verifier-availability window, per-failure cost of one
   burned issuance pair plus a new evidence artefact.
6. (Minor, F5) A non-builder re-probe of the pinned openssl
   pairs, recorded in the test file, or external-seat
   acceptance of the builder probe in its place.

Conditions 1–4 are the ship gate for the CLAIM and for
14–16 re-review. If the room ships the code alone with the
record explicitly provisional per condition 1 and conditions
2–5 scheduled as named follow-ups with owners, this seat's
FIX narrows to those follow-ups — but it does not convert
to SHIP retroactively.

— rev-r6, forced dissent, cycle 21
