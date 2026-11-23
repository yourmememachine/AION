# Blind review brief — Cycle 19: Protected Gate scope extension + protected pin-ceremony authority

For external seats seat-gpt / seat-gemini. No internal
verdicts or scores are included in this brief.

## Context

Cycle 13 adopted path-policy/1 in the gate and was HELD on a
convergent finding (internal dissent + both external seats):
the gate's verdict now depends on trust/pathpolicy.py and
oversight/approval.py, which sat outside every protected
list — a change editing only the canonicaliser passed every
list, and a later eval/ change would be judged by the
poisoned canonicaliser. Both seats directed: extend the
gate's protected scope (starting closure + dependency
closure analysis, NOT relocation) with two negative tests.
Separately, cycles 14–16 (snapshot chain-gap, pin ceremony,
ceremony hardening) are HELD on your convergent FIX: the pin
ceremony's operator authority was circular (caller-supplied
operator list) and its evidence was a bare caller-supplied
digest whose only check was non-equality with the candidate
("theatre"). Your mandatory gates included independent
operator authority from a protected source and evidence
provenance authenticated and bound to the recovery event.

On 2026-11-22 the owner delegated the pending Protected
Gate decision and the decision taken was EXTEND. This cycle
implements it. Cycles 14–16 are NOT re-reviewed here and
remain held; their re-review is a later step.

## What was built

### A. Gate scope extension (eval/gate.py — the only eval/ change)
PROTECTED_FILES is now ("core/loop.py",
"oversight/__init__.py", "oversight/approval.py",
"trust/__init__.py", "trust/pathpolicy.py");
PROTECTED_PREFIXES unchanged ("eval/",). The additions are
the canonicaliser the gate lazily imports
(trust/pathpolicy.py), the canonicalise_path source it
delegates to (oversight/approval.py), and both package
__init__ files executed on that import path. The mirror in
trust/pathpolicy.py was updated in the same change (drift
tests enforce lockstep); the first gate/oversight overlap is
reported by classify(), not hidden. A new docs/GATE-CLOSURE.md
gives the layered closure analysis: L0 verdict logic, L1
canonicaliser chain (verified to terminate in stdlib +
eval.gate), L2 import-path __init__ files, L3 the modules
executed via trust/__init__ re-exports — including the
sys.modules pre-seeding vector, which is named as residual
R-A, NOT closed (structural fix is a named follow-up,
gate-import-isolation). Negative tests: N1 — a change
editing only any of the four newly protected files is
refused by the gate itself through evaluate_self_change,
including non-canonical spellings reported canonically;
N2 — two-step form (canonicaliser edit refused at step 1;
former gate-miss spellings still refused at step 2). The
negative control trust/manifest.py stays unprotected.

### B. Protected operator authority + evidence provenance
- New signing/ceremony_authorisation.py: a verifier-issued
  envelope (domain signed-ceremony-authorisation-v1)
  binding operator_id, ceremony_id, reason, old pin
  {cycle_seq, payload_hash}|null, candidate {cycle_seq,
  payload_hash, signer_id, key_id}, evidence_hash,
  evidence_ref, signed by the verifier's key, TTL hard-capped
  at 900s. The payload projection enforces the reason
  allowlist, reason/pin coherence, the gap-only sequence
  relation, and evidence non-equality vs both pin hashes.
- The operator list lives ONLY in the verifier's environment
  config (AION_CEREMONY_OPERATORS), parsed at startup:
  malformed refuses startup in both deployment modes;
  production + absent/empty refuses startup; research +
  absent leaves the mode refusing per-request. The wrapper
  allowlist grew 14 → 15 names in all four copies, pinned.
- New verifier mode ceremony_authorise: strict 7-key body;
  validation order config gate → cheap validation (exit 2,
  no ledger touched) → operator membership (unsigned,
  unledgered exit-3 refusal; no signed-reject artefact) →
  anti-replay scan → sign → ledger-before-return. Single-use
  at issuance is kept by a new sibling hash-chain journal
  (CeremonyAuthorisationLedger) plus a dual append into the
  anchored signing ledger; the journal append is the commit
  point and a post-commit failure burns the
  (ceremony_id, evidence_hash) pair (recovery = new id + new
  evidence bundle, documented).
- VerifierClient.ceremony_authorise re-derives the payload
  hash and authorisation id, checks pins/expiry, and
  verifies the full echo binding against the request.

### C. Ceremony integration (signing/pin_ceremony.py)
reanchor_pin's caller-supplied authorised_operators
parameter is REMOVED; there is no fallback. It now requires
a SignedCeremonyAuthorisation object (raw dicts refused), a
separate authorisation_key, and expected_verifier_signer_id.
Key separation is enforced in-process: authorisation key id
== snapshot signing key id refuses BEFORE envelope
verification. The envelope is verified on the ceremony's
single captured clock, then bound by EXACT equality to the
captured event (operator, reason, old pin, candidate
projection, evidence hash), each mismatch its own refusal;
the pre-existing evidence non-equality check still runs.
PinCeremonyRecord gains required ceremony_id +
authorisation_id fields (no defaults), verified under a new
invalid_authorisation reason.

## Test evidence

Full suite: 1245 → 1322 tests OK (skipped=26, unchanged).
New/updated: gate closure negative tests (N1/N2, plus the
oversight flip and negative control); pathpolicy/differential
corpus 66 → 71 rows with gate-miss/gate-stricter pinned
empty; ceremony-authorisation envelope unit tests (32);
verifier mode tests against the real subprocess (15:
unconfigured refusal, production startup refusal, invented
operator refused unsigned + unledgered, issuance ledgered in
both stores, ceremony_id reuse, evidence reuse across
events, identical re-presentation refused, dual-append burn,
config grammar); pin ceremony suite 25 → 37; end-to-end
suite (7) driving the real verifier into reanchor_pin with
no caller list anywhere.

## What remains open — stated plainly

1. **Consumption-side replay.** The burn is at issuance, not
   consumption: one envelope consumed twice within its TTL
   succeeds when ceremony_history is omitted (a test pins
   this as a documented limit). The envelope binds exactly
   one event, so a replay can only re-derive the identical
   pin movement; the residual is re-anchoring against a
   since-moved pin state. Closing it needs a protected
   monotonic consumption head — a store-location decision
   above this cycle's pay grade — recorded as a follow-up.
   Making ceremony_history merely non-optional would not
   close it (authenticity of a supplied history ≠ its
   completeness, your cycle-16 point).
2. **Ceremony journal anchoring.** The single-use journal is
   not externally anchored. After a rollback, same-ceremony_id
   reuse leaves a trace in the anchored signing ledger, but
   the anchored store keeps neither evidence_hash nor
   operator_id, so evidence reuse under a NEW ceremony_id is
   not detectable from it without the retained envelopes.
   Follow-up: ceremony-journal-anchoring.
3. **Gate L3.** The gate's lazy import still executes the
   trust package's re-export surface; a poisoned submodule
   could pre-seed sys.modules (reproduced in review).
   Follow-up: gate-import-isolation.
4. **In-process key holding.** Verifying an HMAC envelope
   in-process requires holding the verifier key, and a key
   holder can mint indistinguishable envelopes locally;
   discovery is audit-only against the issuance ledgers (no
   consumption-side ledger check exists — limit M5). This is
   the system's standing symmetric-MAC prototype limit,
   stated in the module docstrings.
5. **Decision interpretation flagged for the owner.** The
   decision text said the gate would hold the operator list
   "from the extended gate's protected store"; as built, the
   list lives in the verifier's protected env config (the
   gate stays env-free; a list constant in eval/gate.py
   would be presentable by any caller and unverifiable by
   the gate). Purpose vs letter is recorded in
   BUILD-CYCLE-19.md and flagged for owner ratification.
6. The ceremony RECORD's MAC still uses the snapshot
   signing key; key separation is enforced for the
   authorisation only.

## Questions for the seats

1. Does the verifier-env operator list + ledgered,
   event-bound envelope close your cycle 14–16 P0s
   (independent authority; authenticated, event-bound
   evidence provenance) in scoped form — and does the
   decision-interpretation flag (item 5) change that?
2. Is the consumption-replay residual (item 1) acceptable
   as a named, follow-up-gated limit for THIS cycle's
   ship, given cycles 14–16 stay held and their re-review
   will require the protected head?
3. Does anything over-claim what this cycle proves?
