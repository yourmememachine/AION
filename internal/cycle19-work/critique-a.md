# Cycle 19 — Cross-critique, seat A (gate closure angle)

Scope of this critique: rulings from the gate side only — what the
`eval/gate.py` protected-list extension does and does not depend on,
and what the extension's own logic (close the demonstrated hole
exactly, name residuals, never overclaim) implies for the B/C
disputes. No production code.

## Verdicts

### D1 — Legacy `authorised_operators` list: **B (REMOVE). Gate side supports removal.**

- The gate extension exists because a verdict is only as good as
  the code/authority it trusts. Keeping a caller-supplied list as a
  shipped, named alternative path leaves the exact CROSS-CHECK-9
  circularity in the tree: the caller still asserts its own
  authority on that path. C's exactly-one-path contract makes the
  choice *explicit and auditable*, which is better than cycle 16's
  silent opt-in — C's §2 defence on that point is correct as far as
  it goes — but explicitness does not fix provenance. A clearly
  labelled UNPROTECTED path is still an unprotected path, and the
  cycle's ship claim ("authority comes from the protected store")
  would need a permanent asterisk.
- Cost asymmetry favours B: cycles 14–16 are HELD and unshipped,
  `pin_ceremony` has no production caller, and the test rewrite is
  mechanical (mint a test authorisation under a test verifier key).
  That rewrite is also *desirable* at re-review: the held cycles'
  tests should exercise the real authority path, not a preserved
  legacy one.
- **Effect on the gate closure / Item A: none, either way.** The
  §1 list, the mirror in `trust/pathpolicy.py`, N1/N2, and Item A's
  P-1/P-2/adoption tests are independent of `reanchor_pin`'s
  signature. My section ships identically under B or C. What D1
  affects is the *cycle's* P0 claim, not Item A's: under C the
  cycle could not honestly be described as closing the operator-
  authority gate, and I would expect both external seats to split
  on it. Under B there is no such exposure.
- One B detail the gate side endorses explicitly: no-pin bootstrap
  reasons are authorised through the same envelope (old_pin null),
  so removal leaves no uncovered legitimate flow.

### D2 — Key separation: **B (in-process refusal on key-id equality).**

- GPT's cycle-16 mandatory gate says key separation "provisioned
  **and enforced**". C's reading — domain separation suffices,
  distinctness is a deployment property — satisfies "provisioned"
  only. Domain separation stops *cross-artefact reinterpretation*;
  it does not stop one key holder from minting both artefacts,
  which is the boundary the envelope exists to create.
- Gate-side precedent is decisive for me: the gate does not trust
  deployment to keep protected files unchanged — it *checks*, in
  code, on every verdict. Enforcement-in-code is this codebase's
  house rule for every other P0 property (exact key sets, single-
  use ledgers, canonicalisation before judging). A one-line
  `authorisation_key.key_id == signing_key.key_id ⇒ SigningError`
  in the contract-resolution step is the same rule applied here.
- C's fixture objection (trust fixtures run one key for the whole
  verifier home) is a fixture cost, not a design argument: the E2E
  fixture grows a second key file, as B §9(c) already anticipates.
  Research deployments that genuinely run one key lose the
  protected path — which is the correct fail-closed outcome, since
  with one key there is no separation to protect.

### D3 — `PinCeremonyRecord` fields: **B (REQUIRED, no defaults).**

- A defaulted `""` is D1's defect in miniature: a record that
  claims no authorisation becomes constructible, and
  `verify_ceremony_record` must then treat empty as a legitimate
  legacy state forever. Under D1=B there *is* no legacy state, so
  the empty value has no honest meaning at all.
- B's breakage analysis matches my own reading and C's grep:
  records are minted and verified in the same code version, no
  persisted record store exists, the sole constructor is
  `reanchor_pin` itself. Required fields break loudly (TypeError)
  at exactly the sites that must be updated — the safe kind of
  breakage. C's trailing-default construction buys source
  compatibility for callers that, post-D1, should not exist.
- Corollary: C's §4 invariants (`""` = legacy, no reason) are
  moot under B+B. Non-empty hex64/`_check_id` validation of both
  fields applies unconditionally.

### D4 — Operator config fail-closed level: **A stands, narrowed: production startup refusal + mode refusal in all modes. B's mode-only design is rejected for production.**

- Cycle 11's deployment-mode precedent is the controlling one:
  production mode already refuses *at startup* for missing
  security-critical config (the `AION_ANCHOR_PATH` production
  rule is the direct analogue my note cited). Production fail-
  closed in this codebase means "the deployment does not come up
  incomplete", not "the incomplete capability refuses politely
  when first exercised". B's design silently downgrades that
  precedent for the newest, most sensitive capability.
- B's counter-argument proves too much. It is valid against
  *unconditional* startup-required (which neither A's note nor
  this ruling proposes): research/test deployments and the
  existing fixture surface run in non-production modes and are
  unaffected. For a *production* deployment, "gate-only, never
  calls the ceremony mode" is not a reason to start without the
  operator list — it is a deployment that has not finished
  configuring the protected gate it claims to run. Setting one
  env var is a trivial cost; a production verifier that starts
  happily with ceremony authority unconfigured, and only fails
  when an operator actually needs a re-anchor (the worst possible
  moment to discover it), is the operational failure mode
  startup refusal exists to prevent.
- Belt and braces: B's mode-level refusal
  (`ceremony_operators_unconfigured`, exit 3, before body
  validation) is *also* adopted — it covers non-production modes
  and any production config path that reaches the mode without
  the list. The two refusals are complementary, not alternatives.
  Malformed value ⇒ startup refusal in all modes (B §1.1) is
  agreed without reservation.

### D5 — Anti-replay sibling ledger + dual append: **Acceptable for this cycle, with the residual carried exactly as B names it. No gate-side interaction.**

- The design is forced by the facts B verified: `SigningLedger`'s
  fixed `EXTRA_KEYS` cannot carry `ceremony_id`/`evidence_hash`,
  and widening it is a journal-format migration. The sibling
  `CeremonyAuthorisationLedger` + dual append respects the key-set
  discipline and preserves the core inference (every issued
  envelope appears in the anchored signing ledger). Agreed,
  including commit-point ordering, no idempotent re-issue, and the
  honest race analysis (flock freshness check makes the loser
  fail-closed with `ledger_failed`).
- The rollback residual is real and correctly bounded by B §4.5:
  rolling back the ceremony journal alone erases reuse *memory*,
  but the duplicate issuance remains *visible* in the anchored
  signing ledger — detectable by audit, not preventable at
  issuance. This matches my note's philosophy for R-A (named,
  bounded, backlogged beats silently absorbed or prefix-inflated).
  Conditions for acceptance, all cheap: (1) the follow-up
  `ceremony-journal-anchoring` is filed with this cycle — it is
  seat A territory and I accept ownership of filing it; (2) no
  doc, docstring, or war-room brief claims rollback resistance
  for the ceremony journal until it lands; (3) the signing-ledger
  half of the dual append is non-optional — a build that lands
  the sibling journal without `append_ceremony_authorisation`
  has not implemented this design.
- Gate-side interaction: none. The ceremony journals live in the
  verifier home, are not on the gate's verdict path, and do not
  touch the protected list, the mirror, or the anchor the gate
  side owns (`AION_ANCHOR_PATH` still covers the signing ledger
  only — unchanged semantics).

## B's `trust/protocol.py` MODES addition — gate assessment

No interaction with the closure or the pins. `trust/protocol.py`
is not in the §1 list, defines nothing the verdict's
canonicalisation uses, and adding `"ceremony_authorise"` to
`MODES` changes no constant the mirror or the differential
harness pins. It *is* executed transitively via
`trust/__init__` → `.client` (L3 in my note), so it falls under
the already-named R-A pre-seeding residual — it does not widen
that residual in kind (any L3 module edit already had the same
reach) and is not a reason to expand the protected list this
cycle. One-line change, seat A raises no objection; B should
still expect protocol/mode-count assertions in the verifier test
surface to move with it (B's/verifier owner's surface, not the
gate's).

## Further test-surface changes from B/C — what seat A must own

Beyond my note's §4.2/§4.3 items (differential reclassifications,
the oversight-isolation re-derivation in
`test_trust_pathpolicy.py`), **B and C add nothing further that
the gate side must own**:

- B's allowlist 14→15 updates live in wiring/deploy tests
  (enumerated in B §1.2) — verifier/deploy surface, not gate.
  The mirror-constant test does not pin env names.
- B's ledger work adds a class and a method; `SigningLedger`'s
  entry shape is unchanged, so no journal-format or gate test
  moves.
- C's record/signature changes are `signing/`-internal.
- **Consequence of D1=B + D3=B that C must own, flagged so it is
  not discovered mid-build:** C's §6.3 claim that
  `tests/test_signing_pin_ceremony.py` stays byte-identical is
  *void* under these rulings. Removing `authorised_operators`
  and making the record fields required necessarily rewrites
  that file's call sites. That is accepted (see D1 — the rewrite
  is part of the point), but the build plan and the held cycles'
  re-review must budget for it, and C's "touching that file is a
  design smell" tripwire is superseded by this ruling.

## Agreements (brief)

- Verifier-env placement of the operator list; zero new gate API;
  the list never arrives via the request (B §1.1/§3.1 strict key
  set is the right mechanism). Matches my §6(i)/(ii) exactly.
- Envelope shape and binding discipline: nested `old_pin`
  exactly `{cycle_seq, payload_hash}`, candidate exactly 4 keys,
  exact-equality binding against captured locals, single clock
  capture, no fallback from envelope to any weaker path.
- TTL 900 s cap for the authorisation envelope (B §2.4).
- B §6.2/§6.4 honesty limits (verifier does not inspect the
  evidence artefact; list membership is not operator
  authentication; HMAC symmetry) — these must survive into
  docstrings unweakened; see missed item M2 for where C's draft
  currently violates this.

## Missed by all three notes

- **M1 — `ceremony_id` minting: B and C contradict each other and
  nobody flagged it as a dispute.** B §7(e): minting is the
  CALLER's duty, the verifier "binds and burns it, never invents
  it". C §1.1: "The verifier generates it… a caller-proposed id
  defeats its purpose as a verifier-side nonce." These cannot
  both be built. Gate-side view: C has the stronger argument —
  anti-replay single-use is only meaningful if the burned id is
  not caller-chosen (a caller can pre-burn or predict ids; a
  verifier-minted id is the nonce the ledger actually needs) —
  but B's client signature takes `ceremony_id` as an input,
  so this changes B's §5 interface too. Needs a ruling before
  the build round; it is at least as blocking as D1–D5.
- **M2 — C's docstring draft §5(c) overclaims evidence
  provenance against B's own honesty section.** C's draft says
  the verifier issues "only against evidence it has itself
  sourced/checked in its protected store". B §6.2 states the
  opposite: the verifier never opens or inspects the artefact,
  and a random hex64 from a listed operator is issuable. C's
  §7(8) even asks A to confirm the claim — unconfirmed, it
  cannot ship in the docstring. The draft must be weakened to
  B's formulation (authenticated, event-bound, attributable,
  single-use — not artefact-verified) before the build.
- **M3 — Naming drift in the envelope's domain/purpose strings.**
  B fixes `CEREMONY_AUTHORISATION_DOMAIN =
  "signed-ceremony-authorisation-v1"` and `PURPOSE =
  "pin-ceremony-authorisation"`; C's assumed payload uses
  `"ceremony-authorisation-v1"` / `"ceremony-authorisation"`
  and version string `"ceremony-authorisation/1"` vs B's
  `"signed-ceremony-authorisation/1"`. Cosmetic only until two
  seats implement against different literals and every cross-
  seat test fails on MAC/payload mismatch. Pin B's literals as
  canonical (B owns the module) and correct C's assumptions in
  reconciliation.
- **M4 — The new trust-critical code is itself unprotected, and
  no note asks whether it should be.** `signing/
  ceremony_authorisation.py`, the ceremony ledger class, and
  the `ceremony_authorise` mode will *define* the ceremony's
  authority checks, yet none of them enters the gate list
  (correctly — they are not on the gate's verdict path) or any
  other protected list discussed this cycle. The F1 pattern —
  edit the checker as an ordinary change, then use the weakened
  checker — re-applies one level over, against the ceremony
  rather than the gate. I am not proposing list additions this
  cycle (that would breach the authorised `eval/` scope and my
  own §2.3 anti-escalation argument), but the residual should
  be named in the cycle record alongside R-A, not left for a
  future reviewer to rediscover.
- **M5 — Consumption-side ledger check is designed by nobody.**
  B §6.4/§7(ii) notes an unledgered (forged-by-key-holder)
  envelope is only detectable if consumers check ledger
  presence, then states the loop cannot read the verifier home
  — and stops. C's consumption sequence has no ledger step;
  my note does not mention it. For the cycle record this is
  acceptable as a stated v1 limit, but it should be stated
  *in the record*, as one sentence, rather than only implied
  across two design notes.

## Summary of rulings

D1 B (remove) · D2 B (enforce in-process) · D3 B (required
fields) · D4 A-as-narrowed (production startup refusal + mode
refusal everywhere; B mode-only rejected for production) ·
D5 accept with named residual + `ceremony-journal-anchoring`
follow-up owned by seat A. Plus one unlisted blocking dispute
(M1, ceremony_id minting) and one docstring overclaim (M2) that
must be settled before the build round.
