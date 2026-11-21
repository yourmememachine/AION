# REVIEW — Cycle 13 (combined run): two war rooms

Six blind reviewers per item, drawn from pods that did not
build the item under review; scores locked in
state/calibration/calibration.json BEFORE reconciliation
(subjects `cycle-13-gate-adoption` and `cycle-13-build`;
re-review scores under `cycle-13-fixround`). External seats
(seat-gpt, seat-gemini) re-review the delta brief
(internal/CROSS-CHECK-BRIEF-CYCLE-13.md); both verdicts below
are PROVISIONAL on that round. An external approval never
overrides an internal FIX.

## Item A — Protected Gate adoption

Builders: Pod D (production), Pod B (tests/wording). Reviewers
from Pods A, C, E.

| seat | scope | score | verdict |
|---|---|---|---|
| rev-r1 (seat 1) | scope fidelity vs the proposal | 0.95 | SHIP |
| rev-r2 (seat 5) | import-cycle robustness | 0.88 | SHIP |
| rev-r3 (seat 9) | negative-integration test quality | 0.90 | SHIP |
| rev-r4 (seat 11) | parser-differential closure (P-1/P-2) | 0.97 | SHIP |
| rev-r5 (seat 12) | caller impact | 0.86 | SHIP |
| rev-r6 (seat 14) | whole item (forced dissent) | 0.38 | FIX |

Reconciled verdict: **SPLIT — ship withheld.** The majority
verified the implementation is exactly the approved proposal
(scope fidelity verbatim to the sketch + Round-C correction;
P-1/P-2 closed at every nesting depth; the negative test is
real end-to-end proof, mutation-verified). The dissent's
blocking finding is NOT about the implementation's fidelity —
it is about the proposal's scope, and it cannot be landed
inside that scope:

- **rev-r6 F1 HIGH (ship-blocking, unreconciled) — the judge
  now imports from a world no judge protects.** Since adoption,
  the gate's verdict depends on `trust/pathpolicy.py` (which
  the gate lazily imports) and `oversight/approval.py`'s
  canonicaliser (which the policy delegates to). Neither file
  is in the GATE's protected list (`eval/` + `core/loop.py`);
  `trust/` is in NO protected list (oversight's workflow list
  covers `oversight/`, and the canary's local lists do not
  cover `trust/` either). Verified live by the dissent:
  `check_protected_paths(["trust/pathpolicy.py"]) == ()` and
  `oversight.is_protected_path("trust/pathpolicy.py") ==
  False`. Two-step consequence inside the gate's own threat
  model: a self-change editing only the canonicaliser passes
  every list; a later `eval/` change is then judged by the
  poisoned canonicaliser. The pre-adoption gate could not be
  poisoned this way — its normaliser lived inside protected
  `eval/gate.py`. F2 (same fix): one gate call now loads the
  whole trust/signing stack (21 modules) via `trust/__init__`.
  What would change the dissent's mind: extend the gate's
  protected scope to cover the code it now trusts (at minimum
  `trust/pathpolicy.py`, `trust/__init__.py`,
  `oversight/approval.py`) or relocate the canonicaliser
  inside protected scope, plus a negative test proving a
  canonicaliser change is itself flagged `protected_path`.
- **Coordinator disposition:** extending the protected list is
  a NEW protected change. The approved proposal does not
  propose it (its divergence section states adoption does not
  merge the lists), and the backlog already carries it as a
  separate owner-approved item (`protected-list-reconciliation`,
  seq 22). It is therefore ESCALATED TO DILIP as a decision
  item, with the dissent preserved verbatim in the calibration
  log and summarised in the delta brief for the external
  seats. Counter-considerations the owner should weigh (from
  the majority reviews): the exposure pre-exists in the
  verifier signing path, which has depended on the same
  canonicaliser since Trust Boundary v2 and shipped three
  externally-reviewed cycles in that shape — adoption extends
  the consumer set of an already-trusted component and removes
  the gate's independent second spelling implementation
  (diversity loss is the genuinely new element); oversight's
  approval workflow does cover `oversight/approval.py`
  itself. Under the standing rule the split stands until the
  owner rules: **Item A is not recorded; `gate-path-
  canonicalisation` stays blocked.** The implementation
  remains in the tree, fully tested.
- Record-and-proceed items landed in the fix round: exact
  `registry_untrusted` assertion in the negative test (rev-r3
  LOW); stale rationale comments in `trust/verifier_main.py`
  and `selfmod/canary.py` corrected (rev-r5 F3); STATUS banner
  prepended to the proposal recording the shipped form and
  this escalation (rev-r6 F4). Recorded as follow-ups, not
  landed (protected-file or out-of-scope): wrap the lazy
  import's failure into `GateInputError` (rev-r2 LOW — the
  failure is fail-closed everywhere but surfaces untyped);
  `oversight.is_protected_path` leaking `GateInputError` for
  out-of-contract input (rev-r5 F1 — fail-closed, documented
  here); a generative/property test over the open spelling
  family (rev-r6 F5 — EXPECTED is literal-pinned for the
  66-row corpus; no spec-independent oracle exists yet);
  the gate header's transitive-load understatement (rev-r1
  LOW — the in-function comment names the full chain).

## Item B — production signed-path wiring

Builders: Pod C (module/lint), Pod E (tests). Reviewers from
Pods A, B, D. Blind round:

| seat | scope | blind | verdict |
|---|---|---|---|
| rev-r1 (seat 1) | design fidelity | 0.92 | SHIP |
| rev-r2 (seat 8) | open_production_store | 0.71 | FIX |
| rev-r3 (seat 2) | production_client smuggles | 0.86 | SHIP |
| rev-r4 (seat 6) | commit_production strength | 0.74 | FIX |
| rev-r5 (seat 3) | the lint | 0.80 | FIX |
| rev-r6 (seat 15) | whole item (forced dissent) | 0.61 | FIX |

Reconciled verdict after two fix rounds: **SHIP, unanimous**
(re-review scores, subject `cycle-13-fixround`: rev-r2 0.96
third look, rev-r4 0.88, rev-r5 0.95, rev-r6 0.82 — the
dissent's SHIP is conditional on the two pre-record gates
below, both satisfied before recording).

Principal findings and dispositions:

- **rev-r2 F1 MAJOR → F1′ → CLOSED.** The store-open
  inspection and construction were two unbound reads: a
  post-inspection swap to an unsigned file was opened via the
  constructor's in-memory ratchet, the re-assert was
  tautological, and a later `save()` would have persisted the
  ratchet — falsifying the module's own claim. Fix round 1
  byte-bound the two reads; the second look found the
  straddle (restore after load, before re-read) and specified
  the real fix: bind the CONSTRUCTED state. Round 2 landed it
  (`store.state_digest()` must equal the inspected document's
  `state_digest` field) plus the docstring corrections and
  the corrupt-swap quarantine note. Third look: 0.96 SHIP,
  both straddle variants refused under the reviewer's own
  probes, docstrings judged literally true.
- **rev-r4 HIGH → CLOSED.** `commit_production`'s signer pin
  defaulted to None — an attacker-signer envelope committed
  unpinned, contradicting "the strong form is the only form".
  The pin is now mandatory; its docstring states it names the
  gate decision's signer and declares the attestation's
  verifier_id UNBOUND at this surface (attester eligibility
  belongs to the `decide_write` flow) — the documentation
  branch of the reviewer's own requested fix, verified by
  re-probe (0.88 SHIP).
- **rev-r5 F1 LOW → CLOSED.** Subclassing was an undocumented
  lint blind spot under an overclaiming sentence. The claims
  in the lint docstring and `trust/wiring.py` are now scoped
  to the detected forms, with five named blind spots
  (getattr, bare method references, partial, subclassing,
  name-reassignment) each pinned by a test (0.95 SHIP).
- **rev-r6 (dissent) — conditions and their fate.** (1) Live
  leg green before recording, as a hard gate: SATISFIED —
  deployment re-provisioned, `LiveProductionWiringTests` RAN
  and PASSED, health check 10/10 (BUILD-CYCLE-13.md, Live
  operations). (2) Honest narrowed-scope record + named
  follow-ons: SATISFIED in BUILD-CYCLE-13.md's scope
  reconciliation; `reuse-legacy-migration` added to the
  backlog at recording, `verifier-wrapper-routing` already
  pending. (3) A production caller, or the finding that none
  exists: SATISFIED as a written finding with grep evidence
  (zero production callers; the factory is the sanctioned
  site, not yet load-bearing). (4) Dynamic wrapper-allowlist
  test: LANDED and passing. Record-and-proceed items all
  verified landed (per-function laundering sentences,
  numbering reconciliation, anchor/relative-path hardening).
- **rev-r3 / rev-r1 LOWs:** anchor collisions with key path /
  registry dir / directories, relative-path and
  whitespace-only acceptances — landed in fix round 1.
  Recorded follow-ups (not landed, by design or layer):
  numeric budget values are unbounded in BOTH wiring and the
  verifier (verifier-layer concern; a config error there
  silently disables the query cap — flagged for a future
  trust cycle); TTL/budget/purpose formats are validated by
  the verifier at spawn, not by the factory (fail-closed,
  late); swapped anchors are content-blind at the factory and
  refused downstream on kind/format.
- **rev-r2 F2/F3/F4:** strict hooks at inspection landed;
  refusal taxonomy documented; symlink behaviour noted in
  review (safe-direction; `save()` replaces the link itself).

## Verification summary

- Full suite (coordinator run): **1145 tests, OK (skipped=2)**
  — baseline 1081, +64 net new.
- Live deployment: health check **10/10**; production suite
  18/18 on fresh budgets; `LiveProductionWiringTests` ran and
  passed against the real deployment.
- Item A suites: 145 tests across the seven touched suites,
  all OK; Item B suites: wiring 49 (48 + 1 live, which ran at
  close), lint 14, all OK.

Verdicts: **Item B — SHIP (PROVISIONAL on the external
seats). Item A — SHIP WITHHELD (split room; escalated to
Dilip; PROVISIONAL on the external seats in the other
direction — their view joins the owner's decision).**
