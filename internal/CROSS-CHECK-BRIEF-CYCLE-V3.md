# Cross-Check Brief — Trust Boundary v3 (Cycle 10)

**For the external reviewers.** This brief states what AION's
Trust Boundary v3 claims, what demonstrates each claim, and what
it declares as limits. It contains no internal review scores.
Please review adversarially: try to break the claims, check that
the demonstrations prove what is claimed, and vote SHIP or FIX
with a confidence score.

Context: v2 (cycle 9) passed its internal war room, but both of
you voted FIX (0.94 / 0.82) and set six demands — demonstrations
and fault injection over new features. v3 is the response. The
suite stands at 964 tests (was 820), all passing; the 2 skips are
explained under Claim 5. Repository: local, stdlib-only Python.

## Claim 1 — Evaluator provenance chain

The chain trusted registry → trusted evaluation configuration →
controlled evaluation execution → authenticated score record →
independently derived decision → signed attestation is specified
in `docs/PROVENANCE.md` with the exact decision predicate
(approve iff sealed_after >= sealed_before under plain float >=,
AND no gaming flag, AND no sealed regression; gap assessment
EPSILON=1e-9, widen threshold 0.05, fixed reason precedence).
Demonstration: `tests/test_trust_provenance.py` (20 tests) drives
eight attack classes through the real verifier subprocess —
config substitution, cross-registry, cross-key (isolated: the
foreign record is ledgered in a shared home, refusal pinned to
the MAC reason), expiry, signer misuse, config injection, forgery,
predicate probes including the exact boundaries (widening of
exactly 0.05 not flagged; 0.05+2e-9 flagged; a 1e-10 sealed drop
rejects via the >= conjunct without being a "sealed regression").

## Claim 2 — Ship exactly-once, crash-tested

`tests/test_trust_crashlab.py` kills the shipping process
(os._exit) at every durable side-effect boundary of record_ship:
after each journal transition and ledger append, inside the burn
save, the tx-journal save, the finalise save, and — in the
anchored variant — after COMMITTED and inside the anchor write.
Double recovery is idempotent; a consumed decision is never
replayed; another transaction's cycle is never attributed
(duplicate-value attacks included); recovery never journals a
verification it did not perform. The remaining during-save
windows are covered by a stated state-equivalence argument (all
saves are atomic tmp+fsync+replace+dir-fsync); the one window
that is NOT an equivalence (a kill during the initial begin save
leaves no journal at all — strictly safer) is explicitly excluded
from the claim. The lab found and fixed a real race: concurrent
ShipLedger burns now use bounded reload-and-retry with full
re-validation per attempt.

## Claim 3 — Extraction accounting, authenticated identity, single-use consumption

`docs/EXTRACTION-ACCOUNTING.md` quantifies the sealed-eval
extraction bound in distinct disclosed positions: one response =
one aggregate (correct/n), ≤ log2(n+1) bits; caps of 25/proposal
and 500/identity enforced inside the verifier; replay and
near-duplicate probe rules (≥0.8 similarity OR ≤2 differing
positions vs any prior transcript of the identity; 3rd probe
latches the family). Measured attacks against the real verifier
(n=8) recover at most 4/8 positions; full extraction fails.
Budget identity is the operator-configured actor id — the wire
protocol has no identity field. Eval records are consumed
single-use at attestation issuance in one atomic ledger save,
including on derived rejects; two concurrent issuances on one
pair yield exactly one success. The budgets anchor's INIT
ceremony can pin only the genesis head.

## Claim 4 — Gate path-policy divergence is enumerated and bounded

`tests/test_trust_pathpolicy_differential.py` compares the
protected gate's path behaviour against path-policy/1 across a
66-spelling corpus. Equivalence holds on canonical spellings;
every divergence class is pinned (gate-miss is an OPEN family —
any separator/dot perturbation of the exact-file entry — and the
document says so; the production bound is the verifier's
canonical-only rule, and all 34 non-canonical spellings of
protected paths are refused by the real verifier). The fix for
the gate itself is written up as a proposal for the project
owner under the Protected Gate Rule
(`internal/PROTECTED-GATE-PROPOSAL.md`); the gate was not edited.

## Claim 5 — Production isolation is provisioned and live-tested

A separate OS user (`aion-verifier`) runs the verifier via a
root-only wrapper with an allowlisted environment; keys, registry,
ledgers and anchors are verifier-owned under 0700 directories;
code executes from a root-owned staged copy. A new production
mode makes anchoring mandatory and fail-closed and refuses the
anchor INIT flags outright. The provisioning ceremony was
executed on the machine, and the live adversarial tests
(`tests/test_trust_production_deploy.py`: nobody denial battery,
direct-invocation refusal, wrapper environment probe, rollback
detection on copies, production-mode refusals) passed against
the real deployment at provisioning time (11/11). Two of the
live tests (test_10/test_11) skip on subsequent suite runs —
their fixed transcripts were consumed by the provisioning run,
and replay accounting is stateful by design; they re-run after
an operator budget reset. That skip behaviour is deliberate and
documented, not a silent pass.

## Claim 6 — One unambiguous interpretation per signed input

`tests/test_trust_serialisation.py` (59 tests) covers duplicate
keys at any depth (including post-decode unicode escapes),
unknown/nested fields, bool/int confusion, null vs missing,
numeric spellings (NaN, infinities, 1e999, huge ints, -0.0),
timestamp spellings, and field order across the wire protocol,
all five verifier modes, and the signed artefact loaders. The
war room's dissent seat found three artefact-layer defects in
this claim during the cycle; all three are fixed and the fixes
are part of what you are reviewing:
(a) sealed_eval's proposal_id becomes the signed scope — it is
now validated with the same id grammar issuance enforces,
applied to the scope root (one `:baseline`/`:candidate` suffix
is the legitimate pair-scope form); refusals happen before any
budget recording or signing.
(b) The eval record's score is value-bound, not spelling-bound
(int 1 ≡ float 1.0): the verifier's attestation check and the
first-party client now share one payload-rebuild helper, so both
consumers reach the same accept/reject outcome on the same
record (probed in both directions, including tampered records).
(c) issue_attestation validates proposal_id and public scores
BEFORE consuming the single-use evidence pair, so malformed
input can no longer burn genuine evidence (consumption on a
derived reject is unchanged and deliberate).
The JSON loaders for attestations, manifests and releases also
gained structural non-finite-number rejection.

## Declared limits (please judge whether these are acceptable, not whether they exist)

- An issuance `approve` certifies sealed non-regression plus no
  gaming flag computed over CALLER-ASSERTED public scores — not
  gain, and not the truth of the public scores. The composed gate
  flow backstops this (strict sealed improvement required). This
  is now stated plainly in `docs/PROVENANCE.md`.
- The extraction bound covers the score channel; the record's
  manifest hash is a public commitment and, for low-entropy
  answers, an offline guess-verification oracle. For small or
  low-entropy sealed sets the aggregate cap can exceed the set's
  total entropy — the concrete-attacker measurements, not the
  cap, are the operative evidence there.
- Co-located rollback: a ledger and its anchor rolled back
  together are undetectable if the attacker can write both
  (root, the verifier uid, or a member of the verifier's group —
  the group must remain single-member). Whole-machine snapshot
  restore by the machine's owner is out of scope.
- Ship recovery does not advance a stale anchor after a
  post-COMMITTED crash; the anchor remains a valid prefix until a
  later anchor update.
- All callers of one verifier deployment share its single actor
  budget (availability, not confidentiality).
- Blanking the deployment-mode variable in the root-owned env
  file silently selects research mode; production-ness rests on
  that one string (operator-error path, requires root).
- Known test flake: under concurrent issuance, the losing
  racer's refusal code occasionally reads `registry_untrusted`
  instead of `eval_evidence_consumed`. Exactly one issuance
  succeeds and the loser is refused fail-closed in every observed
  run; the item is backlogged.
- Reviewer independence (yours and ours) is still organisational,
  not measured.

## What we ask

For each claim: does the demonstration prove it as worded? Are
the declared limits honest and complete? Vote SHIP or FIX with a
confidence score, and name the single strongest remaining defect
you can find.
