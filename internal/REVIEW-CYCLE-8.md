# War-room review — cycle 8 (trust boundary, completion)

Subject: `cycle-8-build` — signed attestations, `signed_only`
memory store, artifact-bound build manifest, out-of-process
verifier, signed ship path. Backlog item:
`store-enforced-signed-commits` (leverage 8.0). Calibration log:
`state/calibration` (subject `cycle-8-build`, discussion closed
after the blind round).

## Re-prioritisation ruling (recorded as required)

Cycle 7's ruling C7-R1 stands and is extended by this cycle:
`signed-gate-decisions` (7.5) was built in cycle 7 ahead of
`phase-handlers` (9.0, BLOCKED on protected `core/loop.py`) on
BLOCKED_PROTECTED / CRITICAL_PATH / EXTERNAL_CONVERGENCE grounds;
leverage scores were NOT rescored. This cycle completes the
trust boundary with `store-enforced-signed-commits` (8.0) for
the same reason: cross-check #1 (ChatGPT + Gemini, independently)
named the signed, artifact-bound, out-of-process verification
boundary the #1 priority ahead of new capability work, and cycle
7's own external review (Gemini) queued store-state/epoch
binding and attestation-by-default — both delivered here.
`phase-handlers` remains blocked, not demoted on merit.

## Blind round (scores locked before any discussion)

| Seat | Role | Score | Verdict |
|------|------|-------|---------|
| rev-r1 | cryptography & signing | 0.68 | FIX |
| rev-r2 | assigned forced dissent | 0.32 | FIX |
| rev-r3 | verifier protocol & process boundary | 0.74 | FIX |
| rev-r4 | manifest, ledger & ship path | 0.45 | FIX |
| rev-r5 | integration, regressions & enforcement | 0.74 | FIX |
| rev-r6 | honesty & claims audit | 0.68 | FIX |

Unanimous FIX. Principal findings: a `__pycache__` bytecode
smuggling channel past the manifest (r4, blocker); the store's
`_commit_gated` neither lint-watched nor refusal-checked (r5/r6,
blocker); signed-attestation machinery issuance-dead on the
sanctioned path (r6, blocker); `record_ship` always spent the
decision when a release was presented (int/str cycle-id defect)
and never checked the loop before burning (r4); the verifier as
a signing oracle for caller-asserted evidence (r2, dissent
flagship); empty-registry fail-open, nested-JSON crash, signer
self-attestation (r3); NaN/huge-int score defects in the eval
attestation (r1); release record barely verified (r4); ledger
optionality and rollback (r2/r4); a shelf of documentation
overclaims (r6).

## Fix rounds

Three fix rounds were run against the union of findings, each
pinned by tests (571 → 602 tests, all passing):

- Round 1 (union fix): exact/finite eval-attestation scores;
  validated attestation parsing; manifest-binding discipline on
  the memory path; nested expiry at sign time; `signed_only`
  store with the epoch check moved inside the store lock;
  commit fallback deleted; `__pycache__` shadows refuse builds
  and invalidate verification; release/cycle-id typing repaired;
  pre-burn loop + release + ledger-head checks in the ship path;
  ledgers made mandatory and extended to all signature formats;
  verifier `attest` mode (accepts now require a signed
  attestation); empty-registry, config-validation, canonical
  changed-path, and oversize-response hardening; counted
  call-graph lint including `_commit_gated`; documentation
  corrections throughout.
- Round 2 (verification-driven): a symlinked `__pycache__`
  variant of the smuggling channel closed; `record_ship` made
  to REQUIRE an externally pinned ledger head; six sentence
  level claim corrections (r6).
- Round 3 (verification-driven): verifier ship mode now checks
  the attestation's artifact binding at issuance (r2 probe P4);
  `record_ship` made to REQUIRE a release record; attestation
  parse strictness (non-string manifest_hash); client response
  cap wired in.

## Verification round (same seats, fresh agents, re-probed)

| Seat | Score | Verdict |
|------|-------|---------|
| rev-r1 | 0.95 | SHIP |
| rev-r2 (dissent) | 0.40 | FIX — dissent preserved (below) |
| rev-r3 | 0.90 | SHIP |
| rev-r4 | 0.78 | FIX → confirmation probe: all items CLOSED |
| rev-r5 | 0.87 | SHIP |
| rev-r6 | 0.88 | FIX → confirmation probe: all corrections verified; seat no longer blocks |

## Dissent preserved (rev-r2, verification round)

The dissent seat's case, in substance: the attestation
requirement adds a procedure, not evidence — `attest` mode signs
a seat's assertions, and the gate's score maps remain
caller-asserted, so a gate accept rests on asserted evidence
routed twice through one key; the sealed-eval mode is the only
verifier-produced evidence and the gate does not require it.
Nothing in production yet calls either sanctioned path (the
cycle's own recording is the first traversal — see the build
record). `signed_only` remains one constructor flag away from
unsigned commits, and ledger replay protection depends on the
head pin the sanctioned path now requires but external callers
must still supply. The seat's verdict: the cycle delivers an
achieved *kit*, honestly documented — not yet an achieved
property of a running system.

Reconciliation response: the dissent is correct about the
evidence model, and the records and docs say so in those terms
(trust/README.md residual risks; build record limits). The
evidence problem is a design change (signer recomputes from raw
inputs), scanned as a follow-up backlog item, not a patch.
Production wiring is likewise a scanned follow-up. The internal
room accepts the cycle as the machinery milestone it was
scoped to be, with the dissent attached — it does not convert
the dissent into a ship claim.

## External seats (Dilip's standing rule, 2026-11-20)

| Seat | Status |
|------|--------|
| seat-gpt (ChatGPT) | PENDING — brief at `internal/CROSS-CHECK-BRIEF-CYCLE-5.md` |
| seat-gemini (Gemini) | PENDING — same brief |

## Verdict

**PROVISIONAL: war-room passed (internal reconciliation
complete, dissent preserved), awaiting external cross-check.**
The cycle is not finally shipped until seat-gpt and seat-gemini
reviews are reconciled in `internal/CROSS-CHECK-3.md`; any fixes
they force will be recorded there with the re-verification loop.
Calibration outcome recording is deferred while the verdict is
provisional.
