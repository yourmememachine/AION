# CROSS-CHECK BRIEF — Re-review of cycles 14–16 (blind)

You are an external reviewer seat for the AION trust-boundary
work. In November 2026 you reviewed cycles 14 (snapshot chain-gap
enforcement), 15 (snapshot pin ceremony) and 16 (ceremony
hardening) and returned FIX verdicts; the three cycles were HELD.
Cycles 17–24 have since been built. An internal re-review of
14–16 against the current tree is complete; its verdicts are NOT
shown to you — this brief gives you the evidence and the open
questions. Your verdicts, with the other external seat's, decide
whether the three cycles ship. Please return, per cycle: SHIP or
FIX, a score 0..1, and answers to the numbered questions that
concern you.

## What the shipped unit actually is (authorship, stated plainly)

Not the November artefacts. Cycle 14's chain-gap rule in
signing/state_snapshot.py is substantively unchanged (wording
amended by cycle 15). signing/pin_ceremony.py today is a
cumulative artefact: cycle 15 authored the ceremony core
(advance_pin, reanchor_pin, classify_verification,
PinCeremonyRecord); cycle 16 the recomputed eligibility, the
shared sole-chain-gap atom, relation gates, history checks,
record-context verification; cycle 19 the authorisation binding
(ceremony_id/authorisation_id) and the DELETION of the
caller-supplied operator list; cycle 20 the Ed25519 authorisation
envelope and verifier-resolved evidence provenance; cycle 21 the
mandatory verifier-owned consumption head and the demotion of
ceremony_history to audit-only; cycle 22 the burned_unadopted
recovery reason and the PinStore (single-document, CAS, atomic)
composition; cycle 23 schema-v2 lineage with bounded recovery;
cycle 24 the journaled supersession gate described in Q1.

## Your original objections and what stands against them now

Cycle 14 (Gemini FIX: liveness trap — refusal before recovery
existed; dense-emission assumption unproven at the loop layer;
"chain continuity" over-claim. ChatGPT SHIP with the condition
that the pin ceremony became the top trust item): the recovery
path now exists end-to-end and is production-wired (strict
refusal → classification → verifier-issued Ed25519 authorisation
with verifier-resolved evidence → verifier-owned consumption →
atomic adoption), exercised in a live run on a byte copy of the
real loop state (genesis → dense advance → two unpinned cycles →
chain_gap_recovery ceremony) and in restoration tests. Dense
emission is implemented at the loop layer (a cycle hook fires the
adopter after every recorded cycle) and fails closed when absent.
Wording now claims step-observation gating relative to the pin,
not continuity.

Cycle 15 (both seats FIX: caller-supplied operator list =
circular authority / authority laundering; evidence non-equality
= theatre; atomic persistence; rollback-resistant audit; MAC key
separation; verification gating; anti-fork/stale-head): the
operator list now lives only in the verifier's protected env
config; the caller's list parameter is deleted with no fallback;
the authorisation is an Ed25519 envelope whose seed never leaves
the verifier (the ceremony side holds a public-key type that
cannot hold secrets); evidence is resolved and hashed by the
verifier from its own evidence root, retained byte-exact, and
event-bound; pin + history persist as one document via a single
fsync'd os.replace under a flock CAS; consumption is mandatory,
verifier-owned, hash-chained and externally anchored; no pin can
move on an unverified or unconsumed ceremony.

Cycle 16 (Gemini FIX: history opt-in; records not hash-chained;
reason exhaustion. ChatGPT FIX, blocking: history proves
authenticity not completeness — omission grants — and no
independently protected rollback-resistant authority/history
source): ceremony_history is now a required keyword (explicit
None refuses) AND demoted — it can only refuse, never grant; the
granting checks run against the verifier's own consumption
journal, so an omitted or truncated caller history can refuse a
legitimate ceremony but cannot authorise a replayed, forked, or
behind-head movement. The consumption journal is hash-chained
and externally anchored (journal-only rollback is refused at
verifier startup; a consumed envelope does not become consumable
again).

## Regression evidence (new, written for this re-review)

tests/test_rereview_ceremony_regressions.py: a pin adopted
through the production path binds cycle 14's rule exactly
(pin+1 accepted; correctly-linked pin+2 refused with sole
("chain_gap",) → reanchor_required); the classification partition
holds end-to-end including a reachable mixed case
(chain_gap + calibration_mismatch → integrity_failure); a
cycle-15-shaped (v1) ceremony record is refused under current
semantics (flag-day is clean); a fabricated consume callable
journals nothing and moves no pin (see Q4).
tests/test_rereview_restoration_regressions.py: verifier-home
rollback refused (anchor_refused; no re-consumption); ceremony
key rotation refuses old-key envelopes and lands fresh ones;
pin-store restoration under an advanced head recovers only via a
legitimate ceremony plus a journaled supersession decision, and
the store never fabricates the lost record back (see Q5);
operator removal behaviour is pinned in test_03 (see Q2).
Full suite: 1710 tests OK (skipped=28, deployment-gated) on the
final tree, coordinator-run at the re-review's close. Two
single-occurrence load-shaped failures in contention tests were
observed during the re-review, each passing in isolation and on
re-run; attribution to VM contention is a judgement, not a proof,
and we do not claim otherwise.

## Questions we need you to rule on

Q1 — SUPERSEDE (headline disclosure). Cycle 24 implemented your
Option A (seat-gpt) as: a separate verifier mode
(ceremony_supersede) issuing a journaled supersession decision
binding an abandoned head movement to a newer candidate. The
decision is a distinct signed envelope, mode, journal and receipt
from the consumption authorisation — but it is NOT a separate
human act: PinAdopter requests it AUTOMATICALLY (exactly one
request, exactly one re-run of the consume attempt with the same
envelope) when a consume surfaces the pre-commit
supersede-required refusal, using the same configured operator id
and launch channel (operator identity is allowlist eligibility,
not authentication — the standing documented limit). The
supersession journal is not yet externally anchored (Q6), and the
consume mode reads it on every consume, so it is also an
availability dependency (a corrupt journal refuses ordinary
consumes fail-closed, consuming nothing). Do you ratify this
reading of "separately authorised", or must the decision be a
genuinely out-of-band act? Cycles 14–16's restoration evidence
routes through this path; if you reject the reading, say whether
their verdicts fall with it.

Q2 — ISSUANCE-TIME-ONLY OPERATOR MEMBERSHIP. Removing an
operator from the verifier's list refuses NEW authorisations for
it, but its previously issued, still-valid envelope still
consumes and lands (pinned by test). Membership is documented as
an issuance fact; envelopes are single-use, event-bound, and
TTL-capped at 900 s. The supersede mode, being a new authorising
act, DOES re-check membership. Is issuance-time-only membership
acceptable as disclosed, or do you require a consume-time
re-check / revocation mechanism?

Q3 — RECORD-LAYER CHAIN SUBSTITUTION (cycle 16). Gemini asked
for hash-chained ceremony RECORDS. What was built instead: the
records are individually MAC'd and context-bound (not chained);
the hash chain lives in the verifier-owned consumption journal,
which is externally anchored, and the pin-store history was
rescoped in writing (in the code) as a non-authoritative,
restoration-lossy replica — the journal is the sole authoritative
ceremony audit history. Do you accept the substitution, or do you
require a chain at the record layer itself?

Q4 — INTEGRATED-SYSTEM SCOPING (the "R5" pattern). Several
guarantees are claimed only as properties of the integrated
system under production wiring, not of the library functions for
arbitrary callers: single-use (reanchor_pin with a fabricated
consume callable returns a (pin, record) pair — it journals
nothing and the PinStore does not move, but the function itself
does not refuse); the cap-2 lineage bound (a direct in-process
ledger caller using the recovery_of=None sentinel is outside the
guarantee; the verifier path converts the sentinel so it is
unreachable there). The only production caller wires the
verifier-backed consumer. Do you accept this scoping, stated in
the code and records, or do you require the properties at the
function level?

Q5 — POST-RESTORE AUDIT. After a pin-store restoration, the
store's history can lack a ceremony the journal records (the
test ends with store history [seq 1, seq 4]; the seq-3 record is
reconstructible from the anchored consumption journal, its
signing-ledger mirror, and the supersession journal, but no check
flags the store-side absence). The claim was rescoped (Q3)
rather than the absence detected. Do you accept the rescope, or
require detection (store↔journal reconciliation)?

Q6 — UNANCHORED JOURNALS. The consumption journal is anchored;
the ISSUANCE journal and the SUPERSESSION journal are not (a
named follow-up, ceremony-journal-anchoring, covers both, with a
completed design). Known consequences: a verifier-home rollback
of the issuance journal degrades reuse detection to audit-only
(consumption single-use still blocks replaying a movement); a
supersession-journal rollback fails closed (decision absent →
refusal; rolled-in decisions are inert by binding). Is deferring
their anchoring acceptable for shipping 14–16, or is it blocking?

Q7 — REASON EXHAUSTION RULING. The internal ruling we ask you to
confirm or reject: per-movement caps (one primary + at most two
issuance-bound recoveries), single-use authorisations, one
genesis per journal, and a strictly monotonic consumption head
are the whole of the exhaustion claim; unbounded SEQUENTIAL
legitimate ceremonies (each: fresh envelope, fresh evidence,
strictly-ahead attested candidate) are operation, not exhaustion,
and no per-pin/per-operator primary-ceremony bound exists or is
claimed. (The pin store also has a 1000-record storage cap, which
is a liveness limit, not an exhaustion bound.)

## Residuals disclosed without a question

Operator identity is eligibility, not authentication (no
per-operator credential exists; follow-up
operator-authentication-channel). The ceremony record's MAC uses
the symmetric snapshot signing key — asymmetry covers the
authorisation envelope only; the record is never claimed to prove
authorisation, burn existence, or attribution, and burn linkage
runs record → authorisation_id → the verifier's journals. A
corrupted pin store is not adopter-recoverable (operator replaces
the file out-of-band, then genesis). Production mode on this VM
is same-user spawn, not OS-user-separated deployment; the
deployment is not provisioned here and deployment-gated tests
skip by design. Loop state has not been advanced for cycles
14–16 (the signed ship path's pick order is blocked by unrelated
backlog items, one genuinely unfinished; the re-review record
states the blocker in full).
