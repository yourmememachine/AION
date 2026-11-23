# Blind review brief — Cycle 23: production integration of the ceremony line

For external seats seat-gpt / seat-gemini. No internal
verdicts or scores are included in this brief.

## The four questions

1. Item (3) — consumption integrity. In CROSS-CHECK-16,
   seat-gpt closed the verifier's scoped implementation
   work but not the broader production claim; seat-gemini
   held item (3) open (FIX 0.84) on zero live loop wiring,
   a research-mode test harness, unclosed crash/mode
   windows, and incomplete ledger-head anchoring. **Is
   item (3) now closed — and if so, in what form?**
2. **Recovery bounds, re-ruled.** In cycle 22 seat-gpt
   RATIFIED one-shot recovery; seat-gemini did NOT,
   calling the (old,new) pair-scan a blunt patch for a
   missing schema lineage field. This cycle replaced the
   pair-scan with an explicit lineage schema and re-ruled
   the bound to **bounded chains, depth cap 2**. We flag
   plainly: this CHANGES the bound seat-gpt ratified.
   **Do you ratify the re-ruled bound?**
3. **The supersede rule** (new this cycle; its own
   question). In `check_head`, a fresh non-recovery
   consumption whose candidate is strictly ahead of the
   consumed head may carry an old pin behind the head —
   the burned head movement is superseded (abandoned,
   never adopted). **Is this rule sound, and is its scope
   right?**
4. **May cycles 14–16 now proceed to re-review** for
   ship? (They were not re-reviewed or shipped in this
   cycle, and the real loop state was not advanced.)

## Headline claims — with their qualifiers, in substance

- The pin adopter is integrated into the loop: `CoreLoop`
  (a file on the Protected Gate's protected list — the
  change is a keyword-only optional `cycle_hook`, default
  off, one post-save call, no new imports) and
  `pin_cycle_hook` pins every recorded cycle's snapshot
  through the adopter. The composition is proven in
  production MODE and in a live run against a BYTE COPY
  of the real state directory (pin 13 → 16, two
  consumptions). Qualifiers: the only callers of the hook
  factory and of `build_pin_adopter` in the tree are
  still tests — no non-test production entry point
  constructs a hooked loop yet; the real state directory
  was NOT advanced; production MODE under same-user spawn
  on a disposable home is NOT production deployment (no
  separate OS user exists on this machine; the wrapper
  launch is refused by design).
- The production e2e surfaced a latent defect from cycle
  22, stated plainly: a correctly gate-pinned production
  client refused EVERY production ceremony, because one
  key pin (`key-<16 hex>`, the HMAC gate key) was applied
  to ceremony envelopes carrying the Ed25519 public key
  id (`pub-<16 hex>`). Cycle 22's adopter evidence came
  from research-mode fixtures pinned with the `pub-` id,
  which masked it. The client now pins ceremony responses
  against the pinned ceremony public key. Gate and
  attestation pin checks are unchanged.
- Recovery is bounded, not one-shot: schema v2 records
  `consumption_kind` / `recovery_of` / `recovery_depth`
  per consumption; the issuance journal records the
  `recovery_of` binding at authorise time, computed by
  the verifier from its own journal — never from the
  request. A movement is consumable at most 3 times
  (primary + 2 recoveries). Load-time coherence: a
  recovery grounds only on its immediate predecessor, a
  primary may not re-root a consumed pair, duplicate
  authorisation ids are corrupt.
- The ship/signing ledger heads for the project's own
  recording path are anchored, and the sanctioned
  recording path no longer takes a caller-supplied head:
  `anchored_record_ship` derives the expected head from
  the anchor and requires the anchor to be CURRENT.
  Qualifier: the real anchors live in the same repository
  on the same disk (committed to git); joint
  ledger+anchor rollback is detectable against git
  history — not "outside writable storage" in the
  deployment sense.

## Workstream 1 — loop integration + live run

- `CoreLoop.__init__` gains keyword-only `cycle_hook=None`
  and a read-only property. `run_one_cycle` calls the
  hook exactly once with the recorded entry AFTER the
  cycle is persisted (outside the snapshot-restore
  try/except): a hook exception propagates unwrapped, the
  cycle stays recorded, stored state is exactly what the
  save wrote. Contract: "cycle recorded, pin pending,
  alert". Idle cycles never fire it. With no hook,
  behaviour is unchanged.
- `pin_cycle_hook(adopter)` attaches the cycle entry to
  adoption refusals/burns before re-raising (the existing
  driver contract). `run_one_cycle_and_pin` refuses a
  hooked loop (double wiring). `record_ship` refuses a
  hooked loop BEFORE opening its transaction (an adoption
  burn is not a loop InvalidTransition and would strand
  the ship transaction mid-state).
- Live run, exact sequence, on a byte copy of the real
  `state/` (loop state at sequence 13) under the
  workstream-2 production home: direct adoption → genesis
  `initial_anchor` ceremony at 13; one hooked loop cycle
  → dense `advance_pin` to 14 (no consumption); two
  hookless cycles → state 15, 16 unpinned; direct
  adoption → `chain_gap_recovery` ceremony to 16; repeat
  → `already_current`. Exactly 2 consumptions in the
  verifier's consumption journal. The test asserts the
  real state file's sha256 is identical before/after.

## Workstream 2 — production-mode end-to-end

- Bootstrap order is forced: production refuses INIT
  flags at two layers, so anchors are initialised by ONE
  research-mode verifier invocation with all INIT flags
  set and a deliberately malformed request (its gate body
  refuses at its first key-set check, before any signing,
  budget or ledger mutation; the harness asserts the
  signing ledger gained no entries and all three anchors
  — signing, budgets, ceremony-consumption — exist).
  INIT keys are then removed and the mode flips to
  production with the full allowlist env.
- The e2e is the first suite test whose adopter client
  comes from `production_client` via `build_pin_adopter`:
  genesis ceremony, dense advances, and a
  `burned_unadopted` recovery, end-to-end in production
  mode against the disposable home. Negative pins:
  adopter env keys in the verifier env mapping are
  refused by `production_client`; each INIT flag in a
  production env is refused.
- The key-pin defect (headline, above): the fix adds a
  ceremony-specific pin check in the client (signer pin +
  key id bound to the pinned ceremony public key's id;
  explicit refusal when no ceremony public key is
  pinned). One finding left open: `production_client`
  does not REQUIRE the ceremony public key argument, so a
  production client can be built that refuses all
  ceremonies locally.

## Workstream 3 — schema v2 + bounded recovery + supersede

- Versioning: `HashChainJournal` gains an allowed
  key-sets seam (default = the single existing set, so
  every other journal's load behaviour is byte-identical).
  The consumption journal accepts v1 and v2 entry key
  sets with POSITIONAL MONOTONICITY (a v1 entry after a
  v2 entry is corrupt); v1 entries are never rewritten
  (their hashes are anchor-covered). The issuance
  journal gets the same treatment with one added field,
  `recovery_of`.
- Lineage: at authorise, step (5b) computes the burn
  match for `burned_unadopted` and records its
  authorisation_id as the issuance entry's `recovery_of`
  ("" otherwise) — verifier-computed, never read from the
  request (request and envelope formats unchanged). At
  consume, lineage is derived inside
  `append_consumption`'s reload-retry loop from freshly
  reloaded entries: a `burned_unadopted` envelope derives
  ("recovery", bound id, head depth + 1) ONLY IF the
  bound id equals the current head entry's authorisation
  id AND candidate + old pin exactly equal the head's
  target/old AND head depth < cap; anything else derives
  primary-shaped and the head rules refuse it as
  already-consumed. Head depth: v2 → recorded; v1 →
  pair-derived (the pair-scan survives ONLY as this v1
  derivation; a v1 pair occurring 3+ times is corrupt at
  load — exact under cycles 21–22 history, where a pair
  occurs at most twice).
- The bound: `MAX_RECOVERY_DEPTH = 2`. Depth 1 covers a
  single adopt fault; depth 2 one full incident's double
  fault; a third interruption indicates a broken adopter,
  so the movement-terminal backstop stays. Authorise
  refuses at the cap (`ceremony_recovery_unproven`);
  consume refuses as `AlreadyConsumedError`. Two
  authorisations bound to the SAME burn race: exactly one
  consumption lands (now pinned by a true multiprocess
  race test); a fresh recovery bound to the WINNER's burn
  may then land at depth + 1.
- Load-time coherence (all verified against hand-hashed
  literal journals): a recovery entry must ground on its
  IMMEDIATE PREDECESSOR (same pair, authorisation id ==
  recovery_of, depth == this depth − 1) — the burn is the
  head at consume time in every append-reachable history;
  a v2 primary whose pair occurred in any earlier entry
  is corrupt; duplicate authorisation ids are corrupt;
  the authorisation journal's `recovery_of` must be "" or
  a 64-hex id. A defensive guard at the commit point
  refuses to write any derived kind outside
  {primary, recovery}.
- Sentinel, disclosed: `check_head` / `append_consumption`
  accept `recovery_of=None` from direct in-process
  callers, meaning "bind to the current head burn". The
  verifier mode always threads an explicit value read
  from the issuance entry — except that a v1 issuance
  entry has no such field and also yields None. In-
  process callers are inside the trust boundary; the
  claim "lineage is issuance-bound" is a verifier-mode
  property, not a ledger-API property.
- THE SUPERSEDE RULE (question 3). Motivation: once a
  movement was consumed and its adoption pair discarded
  AND recovery exhausted (or its recovery artefacts
  lost), the pin sat behind the consumed head forever —
  every later primary ceremony carries an old pin behind
  the head and was refused, and `advance_pin` cannot
  cross the gap. As built (and narrowed in review): in
  `check_head`, when the candidate is STRICTLY AHEAD of
  the head, a non-recovery consumption whose old pin is
  BEHIND the head is permitted — the burned head movement
  is superseded: abandoned, never adopted, its burn a
  permanent journal fact. Narrowing applied: the rule
  NEVER applies to `burned_unadopted` envelopes (a
  recovery envelope that does not validly match the head
  burn refuses; it is never reclassified as a primary),
  and when the old pin's sequence is recorded anywhere
  in the journal (as a target or as an old side) its
  hash must match a recorded hash for that sequence.
  Unchanged: candidate behind/at head (fork and
  already-consumed refusals), old pin AT head sequence
  with a different hash (fork refusal at any candidate
  position), `initial_anchor` against a non-empty
  journal. Two residuals are named in the code: (i) an
  old-pin sequence NOT recorded in the journal cannot be
  hash-checked by the verifier (the verifier cannot
  observe the pin; adoption-side context binding in the
  pin store is the control — a record minted against a
  stale pin cannot be adopted against a store whose pin
  has moved, pinned by a composed test in which CAS and
  non-regression pass and only the context binding
  refuses); (ii) a resurfaced superseded pair adopted
  later can stall one sequence at already-consumed
  before self-healing via the next supersede. The rule
  is deliberately BROAD for primary reasons (it can
  abandon a retained, adoptable burn): the narrower
  alternative (fire only when head depth == cap) was
  rejected because depth measures the recovery chain,
  not artefact retention, which the verifier cannot
  observe — a depth-0 head with a discarded pair is
  exactly the deadlock. The pin can never regress
  through the rule (strictly-ahead candidate; pin-store
  CAS + non-regression + context-bound verification).

## Workstream 4 — crash/restart coverage

Seven scenarios across the multi-artifact boundary
(consumption journal + anchor + pin store + pending
journal + candidate side file), with the labelling
stated exactly: TRUE CRASH coverage (subprocess, SIGKILL)
for (1) death after consumption commit, before adoption
— the child is killed at a barrier strictly downstream
of the verifier commit; restart completes via
`adopt_returned` with the pair retained, and via a fresh
`burned_unadopted` recovery with the pair discarded.
(7) concurrent adopter processes on one pin store —
exactly one adoption lands, the loser refuses, the store
verifies (no kill; the refusal is the datum, and only
the refusal surface is pinned, not its Busy-vs-Moved
cause). STATE SURGERY for (2) torn pending-journal tail
and (3) mid-file pending-journal corruption — both
degrade to refusal/liveness loss only (program order
makes consume-committed-without-an-authorised-line
impossible); (4) candidate side-file loss on unchanged
state → refusal (a fresh signing cannot reproduce the
pin's hash; no `lost_pin` ceremony — asserted against
the store history), unfreezing at the next cycle. SEAM
tests (labelled, not crash coverage) for (5) returned
pair available vs discarded, and (6) the cap-2 chain
under repeated burns. One production change: an
`authorise_pending` journal line written before the
authorise call (detection aid only; it does not count
as a burn; its append failure surfaces as a refusal).

## Workstream 5 — ledger-head anchoring, completed as scoped

- `anchored_record_ship` is the production recording
  path: it takes NO caller-supplied expected head. It
  verifies the ship and ship-tx anchors AND their
  currency (each anchor's head/count must equal the
  journal's CURRENT head/length — a stale-but-valid
  prefix anchor refuses), derives the expected head from
  the ship anchor, delegates to `record_ship` (which
  verifies + advances the ship anchor), and advances the
  ship-tx anchor after the transaction commits. Sandbox
  proof: end-to-end recording of a real cycle; ledger
  rolled back one entry → refused pre-burn, nothing
  spent; ledger deleted → refused; stale-prefix anchors
  → refused.
- The project's real ship ledger (4 entries: burn +
  finalise for two recorded cycles) and ship-tx journal
  (6 entries, one committed transaction) now have anchor
  files outside the ledger directory, initialised this
  cycle and committed to git; a tripwire test asserts
  they verify current. Honest scope: same repository,
  same disk, same user — the anchors detect ledger-only
  rollback or deletion, and joint rollback is detectable
  against git history; they are not an external trust
  root.
- The real loop state was NOT advanced this cycle.
  Recording the backlog item this workstream completes
  (it is the loop's pickable item) as the next loop cycle
  ahead of cycles 14–16 would falsify the loop history's
  ordering while 14–16 are held; each of those cycles
  still needs its own signed ship package through the
  anchored path, in order, after re-review.

## What was NOT done

- Cycles 14–16: not re-reviewed, not shipped; real loop
  state not advanced (still at sequence 13).
- No live run against the real state directory itself,
  no real pin store for the real state, no production
  deployment (not provisioned on this machine;
  deployment-gated tests skip by design).
- Issuance-journal anchoring (the narrowed follow-up);
  `production_client` requiring the ceremony public key;
  a non-test entry point constructing a hooked loop.

## Liveness figures (unchanged)

Envelope TTL hard-capped at 900 s; every ceremony needs
two verifier-availability windows inside that life (one
to authorise, one to consume). A failed or lost consume
burns the issuance pair; the client never retries a
consume automatically. Recovery under the new bound: a
movement may consume at most 3 times (primary + 2
recoveries); a movement-terminal burn leaves liveness to
`adopt_returned` with the retained pair, or to the next
snapshot sequence via the supersede rule.
