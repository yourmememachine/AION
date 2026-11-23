# BUILD — Cycle 20: cycle-19 Parts B/C fix round (ceremony authorisation)

Mandate: internal/CROSS-CHECK-13.md (external reconciliation of
cycle 19 — Parts B/C HELD on convergent FIX, seat-gpt 0.91 /
seat-gemini 0.88) + Dilip's ratification of the verifier-env
authority model (DECISION-PROTECTED-GATE-EXTENSION.md,
2026-11-23). Part A + Item A shipped in cycle 19 and were NOT
touched (eval/ diff is empty). Cycles 14–16 were NOT
re-reviewed and remain HELD. Design record:
internal/cycle20-work/ (design-a/b/c, critique-a/b/c,
DESIGN-FINAL.md — three coder seats designing together,
cross-critiqued, coordinator rulings R1–R11). War room:
REVIEW-CYCLE-20.md. Verdict: **SHIP (internal, unanimous after
the fix round, rev-r6's conditional dissent preserved) —
PROVISIONAL** on the external seats (brief:
internal/CROSS-CHECK-BRIEF-CYCLE-20.md).

Baseline (coordinator-verified): 1322 tests OK (skipped=26).

## Staffing

3 coder seats building together (design round + cross-critique
round + build round, disjoint file ownership per DESIGN-FINAL
R11): seat A key boundary, seat B verifier mode/config +
evidence, seat C consumption. Seat B's build agent died on a
runtime error mid-round; a continuation seat audited the
partial tree against the brief and completed it (recorded
here for honesty). War room: 6 reviewer seats that did not
build (rev-r1 scope fidelity, rev-r2 cryptography, rev-r3
verifier mode, rev-r4 consumption, rev-r5 claims, rev-r6
forced dissent); blind scores locked in
state/calibration/calibration.json BEFORE reconciliation
(subjects cycle-20-fixround, cycle-20-rereview,
cycle-20-spotcheck). The original rev-r3 agent ended without
delivering; a replacement seat reviewed blind under the same
id. Fix round: 2 seats + 1 micro-fix seat; re-reviews by the
four FIX seats under their original ids.

## The key-boundary route (the seats' strongest defect)

**Route taken: asymmetric signing — pure-Python Ed25519
(RFC 8032), implemented in-repo over stdlib only.** Reasons
(design-a §1–2, ratified in DESIGN-FINAL R1): it is the only
route that makes verifier authority cryptographic rather than
procedural while keeping the ceremony an offline, in-process
function; key generation is one 32-byte draw and signing is
deterministic (no RNG at sign time); measured verify cost is
≈10 ms class on this VM (coordinator re-measurement during
the build: median 6.4 ms, p95 29.9 ms, n=60, shared-CPU VM —
R10 actuals). Rejected: RSA (keygen needs Miller–Rabin prime
search or CLI provisioning; PKCS#1 v1.5 strict-parse forgery
history; PSS is more code than Ed25519 verify); openssl
subprocess (still needs the pure-Python verify half, adds an
undeclared system dependency against the stdlib-only
invariant). Runner-up: route 4, verifier-delegated
consumption — the only route that also closes F1; NOT built,
remains the named route for the cycles 14–16 consumption
head. Verification profile pinned verbatim (R2): exact
lengths → canonical decode (y<q, re-encode equality) → the 8
small-order encodings as literal constants → S<L →
cofactorless equation; verify never raises on bad input.

## What was built

**Key boundary (seat A).** New signing/ed25519.py (extended
twisted-Edwards coordinates; the affine form exists only as a
test oracle). signing/ceremony_authorisation.py cut over to
v2 as a flag day with NO dual-verify window (a dual window is
the silent fallback): domain signed-ceremony-authorisation-v2,
payload "v" …/2, "alg" "ed25519", signature hex128, key_id
"pub-" + sha256(public_key)[:16]; the HMAC path is deleted
(no _mac, no hmac import — grep-pinned). CeremonySigningKey
(seed; verifier-side only) / CeremonyPublicKey (the pin;
cannot hold secret material) replace the shared SigningKey;
load_ceremony_seed / generate_ceremony_key_file reuse
gate_decision's key-file discipline. Key separation is now
type + role separation; cycle 19's key-id-inequality check
was DELETED as vacuous (all three design critiques converged:
"pub-…"/"key-…" namespaces can never collide, so it could
never fire — seed reuse is refused at provisioning instead,
byte-equality in _load_config). A v1 envelope is refused
explicitly at parse when it carries its HMAC-era markers;
a fully relabelled envelope carries no version field and
dies at signature verification (wording corrected in the fix
round to state exactly this).

**Evidence provenance at issuance (seat B).** New env-only
config AION_CEREMONY_EVIDENCE_DIR (absolute; production +
absent refuses startup; research + absent refuses
per-request, exit-3 ceremony_evidence_unconfigured).
evidence_ref is now a relative name under that root (grammar:
≤512 chars, 1–8 canonical lowercase segments, no leading/
trailing slash, backslash, or ./.. segments). The verifier
resolves it by an fd-walk with O_NOFOLLOW on every component
below the root resolved once at config load (root ancestors
may be symlinks; the residual root window is named), reads
the artifact itself (regular file only, chunked, 1 MiB cap),
computes sha256 itself, and signs the COMPUTED hash; the
request's evidence_hash is demoted to a cross-check
(mismatch = exit-2 ceremony_evidence_hash_mismatch, before
any ledger write). The body stays 7 keys. The exact bytes are
retained at <verifier-home>/ceremony-evidence/<authorisation_id>
(O_EXCL, 0600, fsync) before the journal commit, so every
committed ceremony has its evidence retained; retention is
not a consumption input (stated as a non-goal in both
docstrings). All existence/type/symlink failures share the
single exit-3 ceremony_evidence_unresolvable (sub-case logged
verifier-side only; a test asserts caller-visible bytes are
identical across sub-cases).

**Verifier config (seat B).** Second new env var
AION_CEREMONY_SIGNING_SEED_PATH with the full fail-closed
matrix (malformed/unloadable → startup refusal both modes;
production + absent → startup refusal; research + absent →
per-request exit-3 ceremony_seed_unconfigured; seed byte-equal
to the HMAC key refused at startup; refused-seed list is
signing's exported REFUSED_TEST_SEEDS — RFC 8032 §7.1 vector
seeds + predictable test keys — imported unconditionally
after the fix round). Wrapper allowlist 15 → 17 in one pass
across all five copies. Deployment gains: combined migration
note (production must set AION_CEREMONY_OPERATORS +
AION_CEREMONY_EVIDENCE_DIR + AION_CEREMONY_SIGNING_SEED_PATH),
the flag-day drain procedure, a seed-rotation procedure, and
a retained-evidence store policy (deploy README).

**Consumption integrity (seat C).** reanchor_pin's
authorisation_key: SigningKey is replaced by
authorisation_public_key: CeremonyPublicKey (a SigningKey
there is a type refusal). ceremony_history is now a REQUIRED
keyword: explicit None refuses early — before envelope
verification — for every reason ("fail-closed ON OMISSION");
per-reason, chain_gap_recovery accepts an empty history
(bootstrap), initial_anchor requires empty-only,
lost_pin/corrupted_pin accept either. _check_ceremony_history
is unchanged; only its opt-in guard is gone. Caller
preconditions (FRESH-PIN / COMPLETE-HISTORY / ATOMIC-ADOPTION /
EVIDENCE-INTENT) are documented as obligations the function
cannot verify. VerifierClient.ceremony_authorise now also
verifies the Ed25519 signature against its pinned
CeremonyPublicKey (R8 — the same verify call consumers make,
not a second path). There is NO verifier-side role in
consumption and no consume-side client helper.

**Operator authentication (seat B + all docstrings).** No
token scheme was built: the system's machinery contains no
per-operator credential to bind to (inventoried in
design-b §2). The claim is narrowed instead — the fused
canonical sentence (DESIGN-FINAL R7) stands verbatim in
signing/ceremony_authorisation.py, signing/pin_ceremony.py,
trust/verifier_main.py (×2) and trust/client.py: operator
identity is operator-id allowlist eligibility via the
verifier's launch channel, not authentication; the envelope
is workflow provenance, not cryptographic attribution.
Follow-up recorded: operator-authentication-channel.

## Fix round (war-room findings, all closed)

- **Concurrent duplicate issuance (rev-r1 HIGH, rev-r3
  BLOCKER — same defect, found independently):**
  CeremonyAuthorisationLedger.append_authorisation reloaded
  but never re-checked duplicates; a competitor commit
  between the mode's scan and the append handed out two
  envelopes for one pair, and the cycle-19 race-honesty
  paragraph claimed the contrary. FIXED: post-reload
  duplicate re-check inside append_authorisation (LedgerError
  → exit-3 ledger_failed), composing with _save's under-flock
  freshness; regression test reproduces the interleave;
  rev-r3's re-review confirmed single issuance under a true
  two-process barrier probe. The docstring now describes the
  composed mechanism.
- **FIFO hang (rev-r3 HIGH):** the evidence walk's leaf open
  lacked O_NONBLOCK, so a FIFO leaf blocked the verifier
  forever before the S_ISREG check. FIXED (O_NONBLOCK) +
  FIFO added to the identical-bytes sub-case test.
- **Scan placement + retained growth (rev-r3 MEDIUM, rev-r6
  F2):** the mode's order deviated from DESIGN-FINAL R5(a)
  (sign → retention → scan), so refused replays wrote
  retained files. FIXED: scan now runs before signing and
  retention (its inputs — ceremony_id + computed hash — exist
  after evidence resolution); a test pins that both replay
  refusals leave retained count and journal length unchanged.
- **Exports (rev-r5 MEDIUM):** signing/__init__.py now
  exports the full cycle-20 surface + the ed25519 submodule.
- **REFUSED_TEST_SEEDS (rev-r6 F5.1):** single source in
  signing/ceremony_authorisation.py, unconditional import,
  exact-equality drift test.
- **Adversarial decode vectors (rev-r6 F3):** 7 Wycheproof/
  C2SP-style vectors added (S+L malleation, identity/order-2
  A and R constructions, mixed-torsion R and A, non-canonical
  identity spelling) — each rejects for exactly the strict-
  profile reason stated; none unexpectedly verified.
- **README wording (rev-r5 re-review F1/F2):** the rotation
  procedure's re-retention claim was FALSE (evidence stays
  single-use across rotation — the journal persists; identical
  evidence is refused ceremony_evidence_reused, and the text
  now warns against clearing the journal); the retained-store
  policy's absolutes were scoped (post-retention commit
  failures can leave orphan files for withheld envelopes).
- **Lows closed:** load_ceremony_seed odd-hex now raises
  SigningError (rev-r2); retention partial-write orphan
  unlinked best-effort (rev-r3 F4); seed/key path env-pop
  test (rev-r3 F5); pin_ceremony "workflow attribution"
  heading (rev-r5).
- **production_client pin (rev-r6 F5.3):** making
  authorisation_public_key REQUIRED in production_client was
  attempted and reverted on evidence — 39 test errors, all
  legitimate non-ceremony production clients. It stays
  optional; the deploy README carries the explicit warning
  that a pinless production client fails only at first
  ceremony use. (rev-r6's re-review accepted this outcome on
  its evidence and noted the attempt's paper trail was thin —
  this paragraph is that trail.)

## What remains open — stated plainly

- **F1, narrowed, still open (rev-r6's dissent, preserved).**
  Consumption single-use is NOT achieved. Duplicate
  consumption fails on omitted history (new) and on an
  updated history (cycle 16), but with a STALE or
  honestly-empty history the same envelope consumed twice
  within its TTL still succeeds and can regress a since-moved
  pin — pinned executably by tests T7/T8, which assert the
  regressed pin value. GPT's cycles 14–16 condition
  (duplicate consumption fails with stale history) is
  explicitly NOT met. The fix is the protected monotonic
  consumption head (owner-level store decision) or route-4
  delegated consumption; both are named follow-ups, and
  cycles 14–16's re-review requires the head regardless.
- **Operator authentication** is narrowed wording, not a
  mechanism (above). Whether the narrowed claim satisfies
  the external seats' item (4) is put to them in the brief.
- **In-process limits unchanged in kind:** the ceremony
  record's MAC still uses the snapshot HMAC key (asymmetry
  covers the authorisation envelope only); sign-time scalar
  multiplication is not constant-time (verifier process only,
  dedicated-OS-user deployment — R9 documented limit);
  retained evidence and the ceremony journal remain
  unanchored (follow-up ceremony-journal-anchoring);
  gate_decision.load_signing_key shares the pre-existing
  odd-hex ValueError pattern rev-r2 found in the new loader
  (follow-up, out of this cycle's ownership).

## Test totals

Full suite (coordinator runs): baseline **1322 OK
(skipped=26)** → after implementation **1391 OK
(skipped=26)** → after the fix round **1406 OK
(skipped=26)**. Net +84: ed25519 primitive 18 → 25,
ceremony-authorisation unit 50 → 55, pin ceremony 50,
ceremony mode 32 → 35, E2E 8, wiring/deploy/production
updates, ledger race regression, package-export tests.

## Self-improvement delta

tests_passing 1322 → 1406 (evidence: coordinator full-suite
runs; verifiers rev-r1..rev-r6, non-builder reviewers).
Process lessons: (1) the cycle-19 "race honesty" paragraph
survived a full cycle as a false guarantee — two independent
reviewers probing the interleaving killed it; claims about
concurrency must be probed, not read. (2) The dissent seat's
cheapest findings (scan placement, a silent try/except
fallback, a missing rotation procedure) were all seams
BETWEEN slices — per-file review scopes structurally miss
them; the forced-dissent seat's cross-slice brief is what
caught them. (3) A fix round can introduce its own false
claim (the README rotation sentence) — re-review must read
the fix's NEW text, not only the code it changed.
