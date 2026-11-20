# Cross-check brief — AION trust-boundary cycle (for ChatGPT & Gemini, war-room external seats)

You are sitting as an external reviewer seat in this project's
war room. Review what was built, attack it, and return: (1) a
score 0–1, (2) a verdict (ship / fix), (3) findings ordered by
severity, (4) what you would build next. This brief deliberately
contains no internal reviewers' scores or verdicts.

## Context

AION is a local, stdlib-only Python research system that
improves itself in gated cycles: builders propose changes, an
evaluation gate (`eval/gate.py`) accepts or rejects them based
on public + sealed benchmark scores and a verifier attestation,
accepted lessons commit to a memory store, and shipped cycles
record into a core loop's state. A prior cycle added HMAC-signed
gate decisions (`signing/`). This cycle's mandate, set by two
independent external reviews converging on the same priority:
close the trust boundary — signed attestations, store-enforced
signed commits, artifact-bound authorisation, and an
out-of-process verifier — before new capability work.

## What was built this cycle

1. **Signed verifier attestations** (`signing/attestation.py`):
   an HMAC envelope over a `VerifierAttestation` (domain
   `signed-verifier-attestation-v1`), binding proposal id and
   optionally a build-manifest hash; TTL 60s–48h (default 900s).
   `commit_signed` can require and verify the presented envelope:
   payload-hash equality with the decision's `attestation_hash`,
   inner approve + reward-hacking-checked, nested expiry
   (attestation must not outlive the decision — enforced at sign
   time too). Manifest-bound attestations are refused on the
   memory-commit path at both sign and commit.
2. **Store-enforced signed commits** (`memory/store.py`):
   `MemoryStore(signed_only=True)` refuses plain `commit_write`;
   commits arrive via `signing.commit_signed`, which verifies
   the envelope and delegates to the store's internal
   `_commit_gated`. Optional epoch binding: the decision can
   carry the store's state digest, compared inside the store's
   lock at commit time.
3. **Artifact-bound authorisation** (`trust/manifest.py`,
   `trust/release.py`): a build manifest canonically hashes the
   source/test/evaluator trees (buckets by path), the review
   record, and per-file sha256/size/executable-bit; a release
   record ties manifest + ship decision + expected cycle +
   pre-ship loop state (cycle counter and state-file sha256).
   Any file inside a `__pycache__` directory — including a
   symlinked one — refuses a build and invalidates verification
   (bytecode shadows are an execution channel).
4. **Out-of-process verifier** (`trust/verifier_main.py`,
   `trust/client.py`, `trust/protocol.py`): a subprocess service
   (one process per request, single strict-JSON document in/out,
   config only from the environment) with four modes:
   `gate` (runs the evaluation gate verifier-side and signs the
   decision), `sealed_eval` (scores a positional answer
   transcript against the sealed registry in-process and signs
   an eval attestation), `attest` (issues signed attestations
   under the service's attesting identity), and
   `verify_envelope` (advisory). Gate accepts are refused unless
   a signed attestation is presented; the signer may not be a
   builder, a reviewer, or the attester; the sealed set must be
   non-empty; every signature is appended to a hash-chained
   signing ledger before the response is returned, and the
   service refuses to run without its ledger home. Exit codes:
   0 = protocol success (including signed rejections),
   2 = malformed request, 3 = verifier-side failure.
5. **Signed ship path** (`trust/shipcheck.py`,
   `trust/ledger.py`): `check_ship` re-derives everything from
   primary artefacts (manifest rebuilt from the live tree,
   envelope re-verified, attestation verified, release record
   cross-checked, optional externally pinned ship-ledger head).
   `record_ship` requires the release record and the pinned
   head, verifies the loop's pick and pre-ship state BEFORE
   burning the decision in the hash-chained ship ledger, records
   the cycle, re-verifies the tree, then finalises the burn.
6. **Call-graph lint** (`tests/test_trust_lint.py`): the suite
   fails if production code calls `commit_write`,
   `_commit_gated`, or `run_one_cycle`, or constructs
   `GateDecision`, outside a counted allowlist. Documented blind
   spots: `getattr` indirection, bare method references,
   `functools.partial`.

## Design decisions worth attacking

- HMAC (symmetric) rather than asymmetric signatures: key
  placement is the boundary; the docs state a separate OS user
  is required for a real one and this prototype is same-user
  process isolation only.
- The gate's score maps are caller-asserted inputs to `gate`
  mode; verifier-produced evidence exists only via `sealed_eval`.
  The signed-attestation requirement binds an identified seat's
  assertion to the decision; it does not make the assertion
  true. This is the design's known soft underbelly — judge
  whether the mitigation (identity + ledger + sealed-hash
  binding) is proportionate at this stage.
- The manifest excludes `state/` by design (it authorises code,
  not data); loop state is bound separately through the release
  record's pre-ship snapshot.
- `signed_only` is a construction-time flag and is not
  persisted; a plain store over the same directory re-enables
  unsigned commits. Documented as an operator warning.
- Ledger security rests on an externally pinned head; a deleted
  ledger is indistinguishable from first use without one.
- The verifier canonicalises `changed_paths` spellings itself
  because the gate's own protected-path list lives in a
  protected module that this cycle could not change; the gate's
  list and the oversight system's list are known to differ.

## Test evidence

Full suite: **602 tests, all passing** (466 before this cycle).
New this cycle: signed-attestation round-trips and adversarial
cases (forgery, transplant, replay/stale, nested expiry,
manifest-binding misuse), `signed_only` store refusals and epoch
binding, manifest golden-vector + tamper/shadow cases
(including a forged timestamp-header `.pyc` and a symlinked
`__pycache__`), ship-path end-to-end and pre-burn refusal cases,
verifier subprocess tests (forged/oversize/nested/malformed
requests, killed/misbehaving fixture verifiers, empty registry,
signer conflicts, ledger failure withholding signatures), and
the call-graph lint in both directions. Adversarial coverage
was a first-class deliverable, per the mandate.

## Honest limits (as documented in the code)

- Same machine, same OS user: process isolation, not a
  separate trust domain. Anyone who can read the 0600 key file
  can forge envelopes.
- The verifier is a signing oracle for well-formed inputs: it
  signs decisions over the evidence it is handed (and signs
  rejections too); every signature is ledgered.
- No production flow traverses the signed paths yet beyond this
  cycle's own recording; the memory reuse harness still commits
  unsigned in-process decisions under a recorded legacy
  exception in the lint allowlist.
- `sealed_eval` returns an exact score (a per-position oracle
  for short answer spaces) and registry reads burn access-log
  entries; rate control is the orchestrator's problem.
- Registry disk-TOCTOU windows exist (documented per mode);
  the verifier has no internal timeout (the client's timeout
  is the bound).
- No key rotation or revocation in this version.

## What we want from you

Attack the design, not just the code: Is the attestation
requirement meaningful given who issues attestations? Is the
manifest's exclusion of state defensible? Does the ship path's
burn-then-record ordering fail safe in the cases that matter?
What is the highest-leverage next build for the trust boundary,
and what would you refuse to ship?
