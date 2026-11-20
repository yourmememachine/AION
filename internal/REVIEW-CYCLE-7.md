# INTERNAL — War Room Record, Build Cycle 7 (do not publish)

Six reviewer seats, none of them authors of the code under review
(all 15 scientist seats coded this cycle in 5 pods of 3, so review
seats are fresh rev-r1..rev-r6, the established pattern). Blind pass
first; R2 held the assigned dissent role. Two external seats
(ChatGPT, Gemini) sit in the war room per Dilip's 2026-11-20
upgrade — see CROSS-CHECK-2.md; the verdict stayed provisional
until Gemini's review was reconciled in. ChatGPT's seat was vacant
(sign-in unavailable in a detached run), recorded, not counted.

Reviewer seats: R1 Correctness, R2 Adversarial (dissent),
R3 Binding/Integration, R4 Lifecycle/Keys, R5 Tests, R6 Honesty/Docs.

## Blind verdicts (as reported)
- R1 — FIX, 0.92. HIGH: non-ASCII signature crashes compare_digest
  with TypeError; lone surrogates crash canonicalisation with
  UnicodeEncodeError; MACed payload fields never validated
  (evaluated_at garbage, Regression suite/benchmark verbatim,
  reasons untyped, _check_text dead code). MEDIUM: envelope
  reconstruction leaks TypeError/OverflowError; float coercion lossy
  and non-injective (2^53 collision, -0.0 split); timestamps MACed
  as raw strings (one instant, many envelopes); attestation binding
  optional and unenforceable. LOW: envelope auth fields not
  hex-checked at load; entry binding strip-lenient (kept: it matches
  the store's own comparison exactly).
- R2 (dissent) — FIX, 0.90. CRITICAL: the plain unsigned commit path
  bypasses signing entirely (live probe: hand-built decision commits
  via commit_write). HIGH: symmetric MAC = verifier holds forge
  capability (live probe: fabricated entry committed via
  commit_signed with the verify key); attestation/gate-input
  bindings optional and never verified; replay across stores and
  after rollback. MEDIUM: verify()==() accepts an inconsistent
  accept; non-ASCII signature TypeError; unvalidated fields;
  commit_signed proposal check evaporates when the key is absent.
  Its minimum fix list is the backbone of the reconciled list below;
  its #1 (store must require envelopes) is resolved as a claim fix
  this cycle (docstring downgrade) plus a queued gated item
  (store-enforced-signed-commits, 8.0), because changing the store's
  acceptance rule is a separate design-first cycle, not a patch.
- R3 — SHIP, 0.87. Binding for this entry/proposal/verifier is
  tight; all store checks preserved via unchanged delegation (9
  probes); signed reject refuses commit; compat clean; full suite
  428 at its check. Medium caveat carried: commit_signed proves
  key-holder-signed, not gate-ran (documented; attestation option
  now enforceable via require_attestation).
- R4 — FIX, high. HIGH: make_signing_key coerces before type-check:
  make_signing_key(32) silently mints the all-zero key (live probe,
  signs and verifies). MEDIUM: no rotation story and its absence
  undocumented; symlinked-parent refusal claimed but unimplemented;
  forbidden_roots opt-in and unused. LOW: verify never checks the
  verifier key's own id/material consistency; load accepts any
  length >= 32 and reads unbounded files; parent-dir safety
  unchecked; now="" silently becomes wall-clock; self_test raises
  instead of returning False.
- R5 — FIX, high (tests only; code behaved correctly in every one
  of its probes). HIGH: golden-vector test pinned no literal hash;
  decision_id check and gate_inputs_hash completely untested.
  MEDIUM: tamper tests under-assert (membership, not exact reason
  sets); field-flip coverage partial; nonfinite test vacuous;
  JSON round-trip exercised only empty collections; _check_text
  dead/untested. LOW: other-entry test accepted two exception types;
  13 of 27 exports untested; validation branches and boundaries
  unpinned.
- R6 — FIX, 0.88 (docs only). HIGH: "closes the forgery limit"
  opening overstates an opt-in path; "a rejection cannot be
  suppressed" is false as a module property (no ledger). MEDIUM:
  attestation listed unconditionally though optional; hashing inputs
  presented as a substitute for recomputation; key-placement claims
  are deployment requirements, not enforcement; function docstrings
  overstate symlink protection. LOW: single-use scoped too narrowly;
  "standard library only" phrasing; load "wrong size" is undersize
  only. Checked clean: HMAC wording, MAC coverage, TTL arithmetic,
  no prohibited references, no process branding.

## Reconciled fix list (all implemented, pinned by tests)
1. Signature/payload_hash/decision_id validated as hex64 before a
   bytes compare_digest; non-ASCII yields signature_mismatch,
   never TypeError. (R1/R2)
2. Every MACed field validated in decision_payload: _check_text on
   the note (surrogates/invisibles refused), reasons as ids,
   protected violations as bounded text, Regression suite allowlist
   + benchmark id + exact float scores in range with -0.0
   normalised, evaluated_at parsed, attestation fields validated,
   binding segment must be exactly content-hash:<hex64>. (R1/R2)
3. Timestamps normalised to UTC isoformat in the payload (one
   instant, one envelope; Z/offset spellings hash identically);
   _parse_time only rewrites a trailing Z. (R1)
4. make_signing_key type-checks before coercion; int/list/str/None
   raise SigningError. (R4)
5. Key placement enforced: repo root forbidden by default plus
   caller roots; symlink in any path component refused; parent dir
   group/world-writable refused; load requires exactly 0600,
   exactly 32 bytes, lowercase hex, size-capped read; generate
   wraps OS errors as SigningError. (R4/R6)
6. verify checks the verifier key's id/material consistency
   (key_id_inconsistent), flags inconsistent accepts
   (inconsistent_decision), and supports expected attestation /
   gate-inputs / signer expectations; commit_signed refuses a
   missing proposal id and offers require_attestation. (R1/R2/R3/R4)
7. verify's payload re-derivation returns malformed_payload for
   tampered fields instead of raising; envelope reconstruction
   wraps TypeError/ValueError/OverflowError as SigningError and
   validates list shapes and auth-field hex at load. (R1)
8. Docstring reconciled end-to-end: closure downgraded to an
   un-enforced bypass boundary, rejection-ledger scope, optional
   bindings stated, recompute-vs-hash corrected, placement
   enforcement scoped, rotation absence disclosed, single-use
   scoped to the commit_signed path, key id labelled 64-bit.
   (R2/R4/R6)
9. Tests: +38 pinning tests — literal golden hash, decision_id
   isolated tamper, gate_inputs_hash both ways, exact reason tuples
   for headline flips, all remaining field flips, non-vacuous
   nonfinite path, non-empty round-trips (dict + JSON), nested
   duplicate keys, constants pinned, validation branches, TTL and
   skew/expiry boundaries, key coercion/symlink/repo/oversize
   refusals, empty-now refusal, self_test False paths. (R5)
10. External-seat fixes (Gemini, post-round): default TTL 7200 ->
    900s; docstring gains the un-enforced-boundary and
    rollback-resurrects-poisoned-memory wording. Store-state/epoch
    binding and attestation-by-default queued to
    store-enforced-signed-commits — recorded dissent, not dropped.

## Verification round
V1 (adversarial re-probe) SHIP — 8/8 previously-found defects
confirmed fixed live. V2 (keys/lifecycle) SHIP — 7/7, including
repo-tree refusal with no file created. V3 (tests/honesty) SHIP —
87 signing tests, full suite 466, literal pin confirmed, docstring
clean. Coordinator final run after the external-seat fixes: full
suite 466 tests, all passing (379 before the cycle).

Final verdict: RECONCILED SHIP — unanimous after verification
(R3 shipped blind; R1/R2/R4/R5/R6 findings all verified closed or
explicitly queued as gated backlog with the claim downgraded to
match). External seat: Gemini reconciled in; ChatGPT vacant
(sign-in unavailable), recorded in CROSS-CHECK-2.

## Calibration (X4)
Blind ship-confidence scores for subject cycle-7-build: R1 0.08,
R2 0.10 (dissent role), R3 0.87, R4 0.05, R5 0.10, R6 0.12. (FIX
seats reported confidence in their FIX verdict; the recorded score
is 1 minus that, i.e. confidence the build should ship as-is — the
low scores were accurate: the blind build had a genuinely
predictable-key defect and a crash-on-malformed class.) Outcome
recorded after ship: 1.0. Minority note: R2's dissent — that an
opt-in strict path must not be called a closure — was upheld in
substance: the claim was downgraded and the enforcement change
queued as the highest-leverage pending item (8.0).
