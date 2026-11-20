# INTERNAL — Build Cycle 7 Record (do not publish)

Scope: signed-gate-decisions (leverage 7.5): "Signed gate decisions so
a memory commit can prove the gate ran (closes A30); signature must
cover the decision including its content-hash binding segment."
This was also the #1 next build named independently by both external
reviewers in CROSS-CHECK-1.

## Why this item
Highest-leverage unblocked backlog item. phase-handlers (9.0) stays
BLOCKED on a protected edit. Both prior packages state the same
forgery limit in their docstrings: a gate decision / approval is a
plain unsigned record, so a commit proved presentation, not that a
key-holder authorised the decision. No protected file was edited:
eval/, core/loop.py, oversight/ and memory/ are all unchanged; the
build is a new package signing/ plus its tests.

## Staffing — all 15 seats, 5 pods of 3 coders (design phase)
Five pod agents designed in parallel; coordinator reconciled, wrote
the code and tests.
- Pod A Foundation (1, 5, 8): envelope over every GateDecision field,
  full verifier_note, attestation hash, key outside workspace, 0600,
  fingerprint-derived key id, MAC-not-signature honesty.
- Pod B Memory & World (2, 6, 7): separate wrapper (never extend
  GateDecision), additive strict path, full note + gate-inputs hash,
  proposal id as the v1 single-use nonce, no store schema change.
- Pod C Agents & Tools (9, 10, 11): typed payload allowlist, floats
  banned or bound exactly, strict JSON (exact keys, duplicate-key
  refusal), golden vectors, verify-by-delegation deployment.
- Pod D Safety & Eval (3, 4, 15): HMAC-SHA256 chosen over hand-rolled
  Ed25519 (not stdlib), signer-must-recompute caveat, sign rejects
  too, 13-item red-team list.
- Pod E Action (12, 13, 14): operator flow (fingerprint-only display,
  pre-sign binding summary, self-test), fail-closed error shape, key
  lifecycle and the rollback false-confidence failure mode.

## Reconciled design choices
- New package signing/ (single module gate_decision.py, repo pattern),
  stdlib only. HMAC-SHA256; the docstring says MAC, never signature
  properties, and downgrades the closure claim: the strict path is an
  un-enforced bypass boundary until a store requires envelopes.
- Payload: domain-separated canonical JSON over EVERY GateDecision
  field (full verifier_note verbatim, binding segment must be exactly
  content-hash:<hex64>), attestation hash, gate-inputs hash, signer
  id, key id, purpose, and a UTC-normalised signing window (TTL
  60s–48h; default shortened to 900s after the Gemini seat's review).
- commit_signed(): verifies against the exact entry (proposal id +
  recomputed content hash), optional require_attestation and
  expected signer, then delegates to the unchanged commit_write.
- Keys: 32 bytes exactly in a 0600 file; repo tree forbidden by
  default, symlinks anywhere in the path refused, group/world-
  writable parent refused, key id derived from the key fingerprint.

## War room outcome (see REVIEW-CYCLE-7.md)
Blind round: R1 FIX 0.92, R2 FIX 0.90 (dissent), R3 SHIP 0.87,
R4 FIX high, R5 FIX high, R6 FIX 0.88. Every code finding was fixed
and pinned by tests (87 signing tests, +38 in the fix round);
verification round: V1 SHIP (8/8 re-probes), V2 SHIP (7/7),
V3 SHIP (full suite 466). Final verdict: RECONCILED SHIP.

## External seats (see CROSS-CHECK-2.md)
Per Dilip's upgraded rule the external AIs sit in the war room.
Gemini: received, solid-v1 assessment; two points applied this cycle
(default TTL 900s; sharper un-enforced-boundary and rollback-replay
wording), the rest queued (store-state/epoch binding, attestation-
by-default — both belong to the store-enforcement cycle). ChatGPT:
UNREACHABLE — chatgpt.com loaded but no saved sign-in exists and a
detached run cannot complete Google sign-in; recorded as a vacant
seat, never as a pass.

## New backlog from this cycle
- store-enforced-signed-commits (8.0): make a store require the
  envelope (the gated change that actually closes A30), bind a
  store id/epoch into the payload, and decide attestation-by-default
  there. Gemini + R2 converge on this as the follow-up.
- signing-key-rotation (5.0): keyring with verify-only grace window;
  v1 has no rotation and says so.

## Self-improvement delta
tests_passing 379 -> 466 (+87), verified by rev-r1/V3 (full suite
run in the coordinator run after all fixes). Process deltas: (1) a
"golden vector" test that pins no literal value pins nothing — every
canonical form now carries a literal hash pin; (2) validation must
live in the payload builder, not beside it — a MAC faithfully binds
garbage, so every MACed field is type/semantics-checked at sign and
re-derived at verify; (3) constructors must type-check BEFORE
coercion (bytes(32) is a predictable all-zero key); (4) docstring
claims are reviewable defects — R6's honesty pass downgraded four
overstatements before ship.

## Honest limits
All module-docstring limits stand: HMAC symmetry (verifier can
forge), unsigned path still live (advisory, not enforced), signer
recomputation is a deployment duty not a code property, cross-store
and rollback replay, no rotation, host-clock timestamps, 64-bit
key id is a label.

## Scorecard (ASI map, after cycle 7)
1 Autonomous research ~10% (unchanged)
2 Autonomous building ~40% (+: third consecutive full
   design->build->review->fix->verify cycle, 15 coder seats,
   6 blind reviewers, 3 verification seats, 1 external seat)
3 Self-improvement ~35% (+: a memory commit on the strict path can
   now prove a key-holder authorised that exact decision for that
   exact entry — the A30 proof gap is closed on the strict path,
   open only on the legacy path, which is now queued as its own
   gated item)
4 Long memory + world model ~30% (unchanged)
5 Action with guardrails ~38% (+: gate decisions are MAC-bound with
   key placement rules; store-level enforcement is the queued
   follow-up)
Phase status: P1/P2 exits met earlier; P5 prerequisite chain
(selfmod canary -> protected-gate workflow -> signed decisions)
complete. Next unblocked item: signed-state (7.0);
store-enforced-signed-commits (8.0) is the highest-leverage pending
item but touches the store, so it goes through the war room as a
design-first cycle; phase-handlers (9.0) and
gate-path-canonicalisation (7.0) remain blocked on owner approval
via the oversight workflow.
