# External cross-check brief — Cycle 20 (blind)

**Repository:** ~/workspace/ai (AION). This is the fix round
for cycle 19's Parts B/C (ceremony authorisation +
integration), which you both returned FIX on in
internal/CROSS-CHECK-13.md (seat-gpt 0.91, seat-gemini 0.88).
Cycle 19 Part A + Item A shipped and are out of scope.
Cycles 14–16 remain HELD and are NOT up for review here.

**Please read:** internal/CROSS-CHECK-13.md (your own
conditions), internal/BUILD-CYCLE-20.md (what was built —
its claims are what you are checking, not authority),
signing/ed25519.py, signing/ceremony_authorisation.py,
signing/pin_ceremony.py, trust/verifier_main.py (the
ceremony_authorise handler and _load_config),
trust/client.py, signing/__init__.py,
deploy/verifier-identity/README.md, and the cycle-20 tests
(tests/test_ed25519.py, tests/test_ceremony_authorisation.py,
tests/test_pin_ceremony.py, tests/test_ceremony_mode.py,
tests/test_ceremony_e2e.py). Full suite: 1406 tests OK
(skipped=26) at this commit.

## Your four conditions from cycle 19, and what this round did

**(1) Key boundary (both of you, strongest defect).** The
HMAC envelope is gone — no shared minting secret exists
anywhere in the tree. The envelope is now Ed25519-signed:
the verifier holds the seed (env-only
AION_CEREMONY_SIGNING_SEED_PATH, dedicated key file, refused
at startup if byte-equal to the snapshot HMAC key or on the
exported refused-test-seed list); the ceremony holds only a
pinned public verification key
(CeremonyPublicKey; key_id = "pub-" + sha256(public_key)[:16]).
stdlib has no Ed25519, so the implementation is in-repo
(signing/ed25519.py, RFC 8032, extended coordinates) with a
strict verification profile: exact lengths, canonical decode
with re-encode equality, the 8 small-order encodings blocked
as literal constants, S<L, cofactorless equation; verify
never raises on bad input. The alternative route you named
(verifier-delegated consumption) was NOT taken for this
round; it remains the named route for the consumption head
below. The v1→v2 cut-over is a flag day with no dual-verify
window. **Check the primitive and the substitution tests
hard: this project's evaluator now depends on in-house ECC.**

**(2) Evidence provenance at issuance (Gemini).** The
verifier now resolves and hashes the evidence itself. New
env-only config AION_CEREMONY_EVIDENCE_DIR names a protected
root; evidence_ref is a relative name under it (strict
grammar). Resolution is an fd-walk with O_NOFOLLOW below a
root resolved once at config load; the verifier reads the
artifact (regular file, 1 MiB cap) and signs the hash IT
computed; the request's hash is a cross-check only (mismatch
refuses before any ledger write). The exact bytes are
retained in the verifier home before the journal commit, so
a committed ceremony's evidence is retained; retention is
explicitly not a consumption input. All resolution failures
share one caller-visible refusal code.

**(3) Consumption integrity — the honest state, in three
legs.** (a) Omission: ceremony_history is now a REQUIRED
keyword; an explicit None refuses before envelope
verification, for every reason — consumption fails closed
when continuity cannot be verified by absence. (b) Updated
history: an envelope already in the supplied history still
fails (cycle 16's behaviour, unchanged). (c) **Stale or
honestly-empty history: NOT CLOSED, conceded.** With a stale
history the same envelope consumed twice within its TTL
still succeeds, and can regress a since-moved pin; two tests
pin this executably and assert the regressed value. GPT's
cycles 14–16 condition — duplicate consumption fails even
with stale history — is explicitly NOT met. The named fix is
the protected monotonic consumption head (an owner-level
store decision), or route-4 delegated consumption; cycles
14–16 stay HELD and their re-review requires the head
regardless of your verdict here. **The question put to you:
is two-of-three legs + fail-closed-on-omission enough for
THIS cycle to ship as provisional, with the head as the
binding precondition for 14–16 — or do you hold this cycle
until the head exists?**

**(4) Operator authentication (Gemini) — discharged as a
narrowed claim, not a mechanism.** The prototype's machinery
contains no per-operator credential to bind to, and none was
invented. The claim now reads, verbatim, in every relevant
docstring: "Operator identity is operator-id allowlist
eligibility via the verifier's launch channel, not
authentication: the envelope proves the verifier accepted a
request naming an allowlisted operator id; it does not prove
a particular human or process presented it. It is workflow
provenance, not cryptographic attribution." **The question
put to you: do you accept the narrowed claim as discharging
item (4) for this prototype, with operator-authentication-channel
as the named follow-up — or do you require a binding
mechanism before this cycle ships?**

**Claims wording (GPT's corrections).** Adopted: dependency
COVERAGE not complete closure; workflow provenance vs
cryptographic attribution distinguished (the canonical
sentence above); issuance accounting ≠ consumption
enforcement ≠ anchored provenance (retention is stated as a
non-goal for consumption; the retained store and ceremony
journal are unanchored — follow-up
ceremony-journal-anchoring).

**One process note.** Cycle 19 shipped Parts B/C's sibling
(Part A) on the owner's delegation after your FIX verdicts;
the owner has since ratified the verifier-env authority model
in writing (DECISION-PROTECTED-GATE-EXTENSION.md). This
round's internal process did not re-poll you before building,
on the reasoning that review seats review built code. If you
consider that sequencing itself a finding, say so in your
verdict.

## Ask

For each of (1)–(4): SHIP or FIX, with the defect class and
the smallest change that would close it. Plus an overall
verdict on the cycle with a confidence score (0–1). If you
FIX on (3) or (4), state whether your FIX blocks THIS cycle
or binds only the cycles 14–16 re-review.
