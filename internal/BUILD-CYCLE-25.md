# BUILD CYCLE 25 — independent supersession authorisation (Q1)

**Summary (claim scope):** Cycle 25 resolves the one split
left by the cycles 14–16 re-review (internal/CROSS-CHECK-18.md):
Q1. Seat-gemini shipped all three cycles while rejecting the
"separate authorisation" LABEL for cycle 24's auto-requested
supersession decision; seat-gpt held all three (FIX 0.91–0.94)
solely because a separately signed decision the adopter
auto-requests after a refusal is not a separately authorised
one. Cycle 25 makes supersession a genuinely independent
authorisation event per seat-gpt's five minimum criteria. All
ship decisions this cycle are PROVISIONAL on the parent's
external round on the focused Q1 brief
(internal/CROSS-CHECK-BRIEF-CYCLE-25.md). Cycles 14–16 were
NOT shipped or recorded; loop state was NOT advanced.

Baseline: cycle-24 tree at da9bc0b, 1710 tests OK (skipped=28),
coordinator-verified before building. Design:
internal/cycle25-work/design-approval.md (seat A). Decision
record: DECISION-CONSUMPTION-HEAD Addendum 5, which supersedes
Addendum 4's "separately authorised" reading (Addendum 4 itself
unedited, as history). Three builder seats, disjoint files;
war room and two fix rounds in internal/REVIEW-CYCLE-25.md.

## The approval channel (seat A)

New artefact: the **supersession approval** — a signed,
domain-separated Ed25519 artefact minted ONLY by the
standalone CLI `trust/supersession_approval_tool.py`
(`generate-key` / `public-key` / `approve`) under a dedicated
**approver key**, a third key distinct from the snapshot
signing key and the verifier's ceremony seed. The verify-side
primitives live in `trust/supersession_approval.py`, which
contains no signing function, seed type or loader (test-pinned
at import level; the real barrier is seed absence, recorded
honestly in the war room). The approval binds: (a) the
abandoned head movement (authorisation id, ceremony id, full
old→new pair), (b) the replacement candidate (authorisation
id, seq, payload hash), (c) the exact movement on both sides,
and (d) the original failed consumption attempt (attempted
authorisation id, the refusal code, and the head entry's
authorisation id + journal `seq` + `entry_hash`, so any head
movement stales the approval). TTL 900 s default, [60, 3600] s
window, projection-enforced at verification (the tool REFUSES
an out-of-window TTL since the fix round; it previously
clamped). `burned_unadopted` approvals are un-mintable at both
the projection and the tool-report surfaces.

**Precise trust claim** (design §1, carried verbatim in
substance in the verifier and adopter docstrings and Addendum
5): independence is at the authorisation-event level — a
deliberate separate act with its own artefact and key, such
that supersession cannot happen as a side effect of an
automated recovery flow. It is NOT a claim of a separate human
or separate OS user; on this same-user VM the operator and
approver are the same person running a second command, and a
fully malicious same-user process remains outside the claim.

## Verifier side (seat B)

- Exactly one new verifier env var:
  `AION_SUPERSESSION_APPROVER_PUBLIC_KEY` (hex64, public key
  only). Allowlist 19 → 20 at every site design §4.3
  enumerates (run-verifier.sh, health_check.py, trust/wiring.py
  + docstrings, verifier_main `_load_config`/`_Config`,
  setup.sh, deploy README, all pinned test fixtures incl.
  cycle23_harness, which provisions a real approver key and
  puts only its public hex in the env). The approver SEED path
  var is deliberately not a verifier variable: absent from the
  wrapper allowlist (a non-allowlisted env-file key hard-fails
  the launch) and refused by `production_client` as unknown
  (live-verified by rev-r4).
- Production + ceremony seed configured requires the approver
  key at startup; malformed refuses in both modes; startup
  also refuses approver == ceremony public key and (fix round)
  approver == snapshot signing key in raw or derived form.
- `ceremony_supersede` mode, new check order: step 0 gate
  (`ceremony_supersede_approval_unconfigured`); step 5b —
  approval parsed and verified (signature, key id, temporal
  validity) BEFORE any journal is read, under dedicated codes
  (`malformed_request`, `ceremony_supersede_approval_invalid`,
  `_expired`) that leak only artefact-local facts; step 8b —
  binding re-derived from the verifier's OWN journals
  (`supersede_head` over its consumption entries; head `seq` /
  `entry_hash` from its own head entry — the request names no
  head field) plus the approval-not-spent check, all folded
  into the single `ceremony_supersede_unproven`; step 9
  journals the decision recording `approval_id`,
  `approval_payload_hash`, `approver_key_id`. An adopter
  auto-request alone has no viable shape. Seat B's deviation
  from a single collapsed code (dedicated authenticity codes,
  pre-journal) was judged acceptable by rev-r2 and defended on
  oracle grounds by rev-r6: authenticity codes are emitted
  before any journal read and cannot leak journal state.
- Ledger: `CeremonySupersessionLedger` widened by the three
  approval fields; legacy key set still loads; load enforces
  all-empty-or-all-present and duplicate non-empty
  `approval_id` = corrupt; `append_decision` rechecks
  single-use inside its retry loop; `find_by_approval_id`
  added. Race probe (rev-r2): two concurrent verifier
  processes — exactly one decision lands.
- Client: `VerifierClient.ceremony_supersede(operator_id,
  envelope_dict, approval_dict)` — approval is a REQUIRED
  parameter (no default: a caller without an approval has no
  request to make); the artefact is presented in the request
  body (the adopter merely carries what it cannot create);
  the client echo-checks the approval's replacement binding
  against the sent envelope before sending.

## Adopter side (seat C)

- The cycle-24 auto-request is DELETED, not gated (rev-r3
  verified: the sole `ceremony_supersede` call site is the
  approval-gated resume). On `CeremonySupersedeRequired`,
  `_reanchor` only: appends a `supersession_pending_approval`
  journal phase, writes the pending-supersession report to
  `pin_dir/pending-supersession.json`, and raises the new
  structured outcome **`PinSupersessionPendingApproval`**
  carrying every binding fact an approver needs (ceremony id,
  authorisation id, operator id, original reason, replacement
  candidate seq/hash, exact old→new movement, adopter-side
  abandoned-movement candidates honestly labelled as an aid —
  the verifier is authoritative — plus the retained envelope
  dict). Pending ceremonies are excluded from genuine-burn
  classification, so a pending envelope never drives
  `burned_unadopted` reason selection.
- The report's `head` block is the adopter's belief with
  `seq`/`entry_hash` written **null** — the adopter cannot
  read the verifier's journals; the approver completes them
  from the consumption journal as a disclosed transcription
  step inside the act (design §7), and the tool's projection
  refuses nulls, so an uncompleted report cannot be approved
  by accident. A wrong transcription is inert (verifier step
  8b re-derives).
- Resume (a separately invoked attempt): with no inbox
  approval it re-raises pending with ZERO authorise/consume/
  supersede calls. With an approval (inbox scan via the
  verify-side parser; selection on the retained envelope's
  authorisation id) it presents the artefact exactly once,
  journals `supersede_decided`, re-runs the SAME envelope's
  consume exactly once, and adopts. Config:
  `PinAdopterConfig.supersession_approval_path` /
  `AION_PIN_SUPERSESSION_APPROVAL_PATH`, threaded through the
  runner. Runner: new exit **7** for adopt steps stopping at
  supersession-pending, with a structured outcome line
  (movement fields + `report_written`); cycle steps surface
  it as exit 5 like burned/refused.
- Single-file inbox mode never moves the artefact aside; the
  presented-once property there rests entirely on verifier
  single-use — documented in the module, `_resume_pending`
  and `_find_supersession_approval` docstrings.

## Fix round 1 (war-room findings)

- **r3 F1 (blocker, availability):** a decision journaled at
  the verifier whose outcome was lost to the adopter (step-10
  `ledger_failed` with the decision standing, crash after the
  decision, failed `supersede_decided` append) stranded the
  movement: approval moved aside, fresh approvals refused at
  the prior-decision gate, consume never attempted. Resume is
  now consume-first in those states (`_consume_retained`:
  exactly one consume of the retained envelope; a
  supersede-required refusal from it re-pends, never burns).
  Regression tests pin the ambiguous-response shape end to
  end (pin lands, exactly one decision, no second decision).
- **TTL:** the tool now REFUSES out-of-window TTLs (was:
  silent clamp to 3600, contradicting design §3).
- **Text:** client `ceremony_consumer` docstring rewritten to
  the stop-and-report flow; `signing/pin_ceremony.py` module
  docstring reframed to the three-stage flow; Q4
  INTERNAL/TEST-ONLY SEAM markers on both ledger classes in
  trust/ledger.py (the supersession marker names the concrete
  consequence: `append_decision`'s approval fields default to
  `""`, so a direct in-process append records an approval-free
  decision `check_head` would honour — the guarantee lives in
  the verifier mode); approval-tool CLI help relabelled
  ("separate approval act"); design §4.1 corrected (wrapper
  hard-fails, not "discards"); design §6 effective-window
  statement; design §7 transcription disclosure; stale
  restoration-test docstring corrected.
- **r2 F3:** startup now enforces approver ≠ snapshot signing
  key (raw bytes or derived Ed25519 public key), making the
  distinctness docstring claim true.

## Fix round 2 (re-review findings F2/F3)

- **F2:** a decision journaled against a head that then moves
  is inert verifier-side — the consume refuses with
  `ceremony_head_regression`, NOT supersede-required, and the
  fix-round-1 code misclassified it Burned while the
  consume-first short-circuit made a fresh approval
  unreachable. The client consumer now translates
  head-regression (and already-consumed) via structured
  subclasses detected only through the wrapped cause's
  `.verifier_code`; `_consume_retained` treats head-regression
  as pre-commit, and the resume consume-first branch falls
  through to the approval lookup IN THE SAME ATTEMPT (Option A
  — no new persistent phase; staleness is attempt-local
  state). A stale decision's movement re-pends and completes
  at the next sequence under a new decision against the new
  head; fresh-ceremony head-regression shapes are unchanged.
- **F3:** a resume consume that commits verifier-side but
  loses its response looped on `ceremony_already_consumed`,
  and the genuine-burn exclusion (premise: pending ⇒
  unconsumed, invalidated by resume consumes) blocked the
  standard recovery. On that certified refusal the adopter
  now appends the `consumed` phase to its own journal before
  raising Burned, so the ceremony becomes a genuine unadopted
  burn and ordinary `burned_unadopted` recovery engages.
  Final re-review probes confirmed the translation cannot be
  spoofed by local errors (exit-class + structured-code gate)
  and the append does not leak into the fresh-ceremony path.

## Small settled adds (CROSS-CHECK-18)

- **Q2 disclosure** — removing an operator from
  `AION_CEREMONY_OPERATORS` prevents future issuance; it does
  NOT revoke authorisations already issued (valid until TTL
  expiry); pair with ceremony signing-key rotation for
  immediate cutover. Landed in
  signing/ceremony_authorisation.py's module docstring AND in
  deploy/verifier-identity/README.md beside the operator
  configuration. The README also gained the approver-key
  rotation / seed-loss procedure (rotation invalidates
  unspent approvals only; seed loss wedges supersession alone
  and is recovered by reprovisioning).
- **Q4 precaution** — `reanchor_pin`'s `consume_authorisation`
  callable and direct in-process ledger use are marked
  INTERNAL/TEST-ONLY seams in signing/pin_ceremony.py and
  trust/ledger.py: the guarantees hold only with
  `VerifierClient.ceremony_consumer` / the verifier modes.

## Restoration evidence (criterion v)

tests/test_rereview_restoration_regressions.py leg 4 (test_06)
re-run through the independently authorised route: pending
stop asserted (no decision, nothing consumed) → approver
completes the null head block from the verifier's own
consumption journal → tool-signed approval → completion, with
the decision's `approval_id` asserted equal to the artefact's.
The crash suite's scenario-6 supersede landing is re-pointed
identically. Criterion (iv) regression proof: counting-client
tests pin supersede_calls == 0 on the adopter-only flow;
forged approvals, approvals self-signed with the ceremony
seed, and approvals signed with the snapshot key all refuse;
wrong-candidate / wrong-movement / wrong-attempt bindings
refuse; approval reuse refuses with exactly one decision
journaled.

## Tests

1710 → 1749 at the builder seats' landing (coordinator-run)
→ 1752 after fix round 1 → **1756 after fix round 2**
(coordinator-verified on the final tree; skipped=28, the
documented deployment-gated skips — deployment is not
provisioned on this VM). New files:
trust/supersession_approval.py,
trust/supersession_approval_tool.py,
tests/test_trust_supersession_approval.py (22). Extended:
tests/test_trust_ceremony_supersede.py (49 → 64),
tests/test_trust_supersede_adopter.py (rewritten; 14 after
both fix rounds), tests/test_trust_ceremony_consume.py,
tests/test_trust_runner.py, tests/test_trust_wiring.py,
tests/test_verifier_deploy.py,
tests/test_trust_production_deploy.py, tests/cycle23_harness.py,
tests/test_rereview_restoration_regressions.py,
tests/test_trust_pin_adoption_crash.py. eval/ untouched. Real
state/state.json not advanced (sha256 verified identical
before/after by the coordinator's final run).
