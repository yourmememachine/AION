# Cycle 22 — design B (coder seat B): Workstream 2, closing the mirror gap

Primary slice: WS2. Plus the Gemini oracle sub-task, and the
design-together critiques of WS1 and WS3. Design only; no
production code touched.

Sources read: `internal/CROSS-CHECK-15.md`,
`internal/BUILD-CYCLE-21.md`, `internal/DECISION-CONSUMPTION-HEAD.md`,
`trust/ledger.py` (incl. the R10 docstring on
`CeremonyConsumptionLedger`), `trust/verifier_main.py`
(`_load_config` anchor blocks, `_mode_ceremony_authorise`,
`_mode_ceremony_consume` ~line 2394, `_update_anchor`),
`trust/anchoring.py`, `trust/wiring.py`,
`tests/test_trust_ceremony_consumption.py`,
`tests/test_trust_ceremony_consume.py` (K1–K6 crash wrappers).

---

## 0. The defect, restated precisely

Current commit order in `_mode_ceremony_consume` step (8):

1. `CeremonyConsumptionLedger.append_consumption` — THE commit
   point, in `ceremony-consumptions.json`, **unanchored**.
2. `SigningLedger.append_ceremony_consumption` — the mirror,
   in the externally anchored signing ledger.
3. `_update_anchor(config)` — advance the signing anchor
   (`AION_ANCHOR_PATH`, kind `"signing"`).

If step (2) fails (or the process dies between (1) and (2),
or between (2) and (3)), the mode returns `ledger_failed`,
the envelope stays burned — but the burn exists **only** in
the unanchored journal. A rollback of the verifier home
(`AION_VERIFIER_HOME`, the directory holding all three
journals) to a pre-consumption snapshot erases it. The
signing ledger rolls back with it, and the external signing
anchor still names a prefix of the rolled-back ledger (the
anchor never advanced past the burn), so `_load_config`'s
startup `verify_anchor` passes. The envelope — still inside
its 900 s TTL — verifies, is absent from every rolled-back
journal, passes the head rules, and **consumes a second
time**. Gemini is right, and the cycle-21 mitigation (step
(5)'s mirror cross-check) does not cover it: it only reads
burns that reached the mirror.

Two facts that shape every option below:

- **The verifier is one process per request.** `_load_config`
  runs on every invocation and already verifies the signing
  anchor at startup (`anchor_refused`, exit 3, when the
  anchor is missing on an established ledger, ahead of the
  journal, or names no prefix). Any protection the signing
  anchor gains is therefore checked *before every mode runs*,
  not just at service start. This is the strongest lever in
  the system and it is already built.
- **No two-file protocol is atomic.** Any design with an
  in-home write and a separate external anchor write has a
  crash window between them during which a rollback to the
  pre-write snapshot is indistinguishable from "the write
  never happened". The design goal cannot be "no window"; it
  is: (i) no *failure-returned* consume leaves an
  unanchored-only burn (the Gemini case — the process lived,
  reported `ledger_failed`, and still left the gap), and
  (ii) the residual crash window is no wider than the one
  the system already accepts for every signing-ledger append
  (`_update_anchor`'s documented philosophy: ledgered but
  anchor update failed → withheld, `ledger_failed`).

---

## 1. Option (a) — anchor the ceremony journals themselves

### 1.1 Shape

- `trust/anchoring.py`: `ANCHOR_KINDS` gains
  `"ceremony-consumption"` and (if both journals)
  `"ceremony-authorisation"`. `_validate_anchor` and
  `_check_kind` pick this up automatically; the anchor
  format (`ledger-anchor/1`, exact key set) is unchanged —
  no format migration.
- New env vars, following the budgets precedent
  (`AION_BUDGETS_ANCHOR_PATH` / `AION_BUDGETS_ANCHOR_INIT`):
  `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` +
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`, and for the
  issuance journal `AION_CEREMONY_AUTHORISATION_ANCHOR_PATH`
  + `AION_CEREMONY_AUTHORISATION_ANCHOR_INIT`.
- Placement: `_check_outside_journal` refuses any anchor
  inside the journal's directory. All three verifier
  journals share one directory (`config.home`), so the new
  anchors must live outside `AION_VERIFIER_HOME` — in
  production, alongside the existing ones:
  `/var/lib/aion-verifier/anchors/ceremony-consumption.anchor.json`
  (see `deploy/verifier-identity/setup.sh`, where
  `AION_ANCHOR_PATH=/var/lib/aion-verifier/anchors/signing.anchor.json`).
  They must also be **distinct** from each other and from
  the signing/budgets anchors (extend the distinctness
  checks in `_load_config` and `trust/wiring.py`, which
  today only compare signing vs budgets).
- `_Config` gains `ceremony_consumption_anchor_path/_init`
  (and the authorisation pair). `_load_config` gains a
  startup block per journal, cloned from the signing block:
  absolute-path check; production requires the path and
  refuses the INIT flag; if configured, construct the
  ledger and `verify_anchor(..., kind="ceremony-consumption")`;
  `("anchor_missing",)` + INIT → `initialise_anchor`;
  any other reasons → `_config("anchor_refused", ...)`.
- Genesis pinning: exactly the signing pattern — the anchor
  is created **only** by the INIT ceremony outside
  production steady state. The trap: both ceremony journals
  may already be non-empty when this ships, and
  `initialise_anchor` refuses a non-empty journal unless
  `allow_nonempty_ceremony=True`. First deployment of (a)
  therefore needs a documented, operator-run
  first-initialisation ceremony passing that flag for each
  pre-existing journal — which *blesses whatever history is
  on disk at that moment*, including a rolled-back one. That
  is inherent to retrofitting an anchor and must be said in
  the deploy README, not discovered later.
- Consume path: because `_load_config` verifies per
  request, verify-before-consume is automatic and
  fail-closed: any anchor reason → `anchor_refused`
  (exit 3) for **every** mode, before the body is read.
  After commit, `_mode_ceremony_consume` gains
  `_update_ceremony_consumption_anchor(config)`, cloned from
  `_update_anchor`: no-op when unconfigured; `AnchorError` →
  `ledger_failed`, envelope burned, no success returned.
  `ceremony_authorise` gets the symmetric update for the
  issuance anchor after its commit.

### 1.2 Does (a) pass the mandatory adversarial test?

Sequence: consumption append lands → **mirror fails** →
`ledger_failed` → home rolled back → replay.

Under (a) the commit order becomes: journal append →
consumption-anchor update → mirror → signing-anchor update.
The mirror failure now happens *after* the consumption
anchor has advanced past the burn. Rollback restores the
journal to its pre-consumption length; the external
consumption anchor (untouched by a home rollback) is now
**ahead of the journal** → startup `verify_anchor` returns
`anchor_ahead_of_journal` → `anchor_refused` → replay
**REFUSED**. ✔ — but only because the anchor update was
moved *before* the mirror. If the anchor update stayed
after the mirror (the naive reading of "update after
commit"), (a) changes nothing for this test. The ordering
inside (a) is load-bearing and must be specified, as here.

Residual window under (a): journal append lands, anchor
update itself fails or the process dies in between →
`ledger_failed`, burn in the journal, anchor still names
the pre-burn prefix. Home intact: step (5) refuses replay
as `ceremony_already_consumed`. Home rolled back to
pre-burn: journal and anchor agree again → **undetectable,
replay succeeds**. (a) narrows the Gemini gap from "any
mirror failure" to "anchor-update failure / death in the
append→anchor window" — one atomic file replace wide — but
does not eliminate the class. That is the §0 limit, but (a)
pays full price (below) and still carries it.

### 1.3 Cost of (a)

- Allowlist 17 → **21** (both journals) or 19 (consumption
  only). The 17 names live in (at least) five copies, all of
  which must move together: (1)
  `deploy/verifier-identity/run-verifier.sh` `ALLOWED_KEYS`;
  (2) `deploy/verifier-identity/health_check.py`
  `ALLOWED_KEYS` (plus its `_INIT_KEYS` / `_PATH_KEYS`
  tuples); (3) `trust/wiring.py` `ALLOWED_ENV_KEYS` (plus
  `_INIT_ENV_KEYS`, `_ANCHOR_ENV_KEYS`, and the
  distinctness/outside-home validation loops); (4)
  `deploy/verifier-identity/setup.sh` (the env file itself);
  (5) the test copies — `tests/test_trust_wiring.py` parses
  the wrapper and asserts `len(ALLOWED_ENV_KEYS) == 17`, and
  `tests/test_trust_production_deploy.py` carries its own
  env-name list. `trust/verifier_main.py`'s header docstring
  env list is a sixth, documentary copy.
- Two new startup anchor blocks, two new `_update_*`
  helpers, two genesis ceremonies, production-required
  wiring for two more paths, health-check coverage.
- A subtle regression risk: making the new anchors
  production-*required* means every existing production
  deployment refuses to start until both ceremonies are run
  — a flag day on a deployment that, per BUILD-CYCLE-21
  item 7, is not currently provisioned on this VM at all.

### 1.4 Both journals or consumption only, under (a)?

If (a) were chosen: **consumption only this cycle.**
The issuance journal has the *analogous* defect (authorise
commits to `ceremony-authorisations.json` first, mirrors
second; a mirror failure + rollback resurrects a burned
`(ceremony_id, evidence_hash)` pair) — but it is not the
defect Gemini raised, its replay value is lower (a
resurrected pair yields a second *issuance*, whose envelope
must still pass consumption — where the head and
single-use rules live), and doubling the env/allowlist and
ceremony surface in one cycle is how anchoring work goes
wrong. The issuance residual is already stated honestly in
`CeremonyAuthorisationLedger`'s docstring; it would stay,
with `ceremony-journal-anchoring` narrowed to the issuance
journal as a named follow-up. (My actual recommendation
below keeps that same scoping, for different reasons.)

---

## 2. Option (b) — restructure the commit: anchored mirror first

### 2.1 Shape

Move the commit point into the journal that is **already
anchored**. New commit order in `_mode_ceremony_consume`
step (8):

1. `SigningLedger.append_ceremony_consumption` — **THE
   commit point.** Before this lands, nothing is burned;
   after it lands, the authorisation is spent.
2. `_update_anchor(config)` — advance the signing anchor
   over the mirror entry, immediately, before any other
   write. (This is the step the naive mirror-first sketch
   omits, and omitting it re-opens the gap: mirror in the
   ledger but anchor unadvanced is exactly a burn the
   rollback can erase consistently.)
3. `CeremonyConsumptionLedger.append_consumption` — the
   head-authority append, now post-commit.
4. Return success only after (3).

Failure semantics, re-derived per step:

- **(1) fails** → `ledger_failed`, **nothing burned**. The
  envelope remains consumable within its TTL. This is a
  deliberate contract change from cycle 21 (where a mirror
  failure burned): a failure *before* the commit point
  burning the envelope was only ever a consequence of the
  mirror's post-commit position, never a requirement.
  Pre-commit fail-closed is strictly safer: the signing
  ledger refusing appends (corrupt, oversize, disk) is
  precisely when no new state should be created anywhere.
- **(2) fails** → `ledger_failed`, envelope **burned**
  (mirror entry durable in the ledger; this is
  `_update_anchor`'s existing philosophy for signatures,
  unchanged). Home intact: step (5)'s mirror cross-check
  refuses any replay. This is the §0 residual window —
  see §4.3.
- **(3) fails** → `ledger_failed`, envelope **burned**, no
  success returned, pin unmoved. The state is a
  *mirror-only burn*: an anchored burn with no journal
  entry. Analysed in §2.2 — this is the case the mandatory
  test exercises, and it is safe.
- **Crash between any steps** resolves to one of the above
  states on next read; there is no state in which a success
  was returned but the burn is unanchored, because success
  requires (1)–(3) and (2) anchors (1).

Because the mirror is now the commit point, it must inherit
commit-point discipline — today `append_ceremony_consumption`
is a plain `_append` with no duplicate re-check, safe only
because the journal append serialised first. Required
change in `trust/ledger.py`: give it the
`append_consumption` treatment — bounded reload-retry
(`_APPEND_RETRY_ATTEMPTS`), re-checking single-use against
freshly reloaded entries on every attempt, scoped exactly
as today (`kind="consume"` +
`format="ceremony-consumption"` +
`decision_id == authorisation_id`), raising
`AlreadyConsumedError` on a duplicate. The concurrent loser
of a double-consume race then surfaces as
`ceremony_already_consumed` from the *mirror* re-check,
exactly as K5 today surfaces it from the journal re-check.
`append_consumption` keeps its own in-loop re-checks (the
journal remains the head authority; its append can still
raise `AlreadyConsumedError` / `HeadRegressionError`, e.g.
when a competitor's journal entry landed first — the mode
already maps those).

The mode's step ordering also changes at the front: step
(7)'s `check_head` pre-check stays (cheap refusal before
any write), and step (5) stays as-is — it already reads
both journals. Nothing before step (8) writes anything.

Docstring fallout (must all move together): the
`SigningLedger.append_ceremony_consumption` docstring
("an audit mirror, NOT a second commit… invoked only after
append_consumption has committed… must never be appended
first") is inverted; the `CeremonyConsumptionLedger`
docstring ("The append here is THE commit point") and its
R10 anchoring-residual paragraph are rewritten;
`_mode_ceremony_consume`'s "Commit order" paragraph and
the crash-consistency contract in `signing/pin_ceremony.py`
/ `trust/client.py` keep their *guarantees* (consumption
committed at the verifier before `reanchor_pin` returns
anything; burned stays burned; never retry) — they survive
verbatim, because the new order preserves them; what
changes is *which append* the words "consumption-journal
append" name. Grep for "mirror" across `trust/` and
`signing/` and reconcile every hit; stale mirror-language
is exactly the class of defect rev-r5/r6 caught in cycle 21.

### 2.2 The mirror-only burn: what breaks, what doesn't

State: signing ledger has the scoped consume entry for
authorisation *A*; consumption journal has no entry for *A*;
signing anchor covers the mirror entry; caller got
`ledger_failed`; pin never moved; `reanchor_pin` returned
nothing (the consumer raised, per its contract).

- **Replay of the same envelope** → step (5) mirror
  cross-check → `ceremony_already_consumed`. ✔ (This check
  already exists; under (b) it stops being a mitigation and
  becomes load-bearing — it must be covered by a test that
  fails if the scoping is widened or dropped, §6 T4.)
- **`check_head` / `head_target()`** read the journal only,
  so the head does not advance for a mirror-only burn. A
  *fresh* envelope (new ceremony, new evidence — the only
  recovery path) for the **same target** therefore passes
  the head rules and can consume successfully. Is that
  safe-but-wrong or acceptable? **Acceptable — in fact it
  is the correct recovery semantics.** A mirror-only burn
  never produced a success and never moved the pin, so the
  target was never *adopted*; letting a new ceremony move
  the pin to it is precisely WS1's burned-but-unmoved
  recovery. The laundering case is different and stays
  closed: same-target under a fresh envelope is refused
  when the first consumption *succeeded* (journal entry
  exists → `check_head` raises `AlreadyConsumedError`).
  What (b) gives up is only: same-target refusal after a
  *failed* consume — a case where refusal would be pure
  harm (it would make the target permanently
  un-anchorable for a movement that never happened).
- **Response/adoption flow**: unchanged. Success is
  returned only after the journal append, so
  `VerifierClient.ceremony_consume`'s echo validation and
  `reanchor_pin`'s adopt-on-success logic see no new
  states. The one new caller-visible behaviour: a consume
  refused `ledger_failed` *may or may not* have burned
  (step (1) failure: not burned; steps (2)/(3): burned).
  The client already treats every ambiguous outcome as
  burned and never retries, so this is compatible — but
  the wording in `trust/client.py` ("the envelope is
  treated as burned") should gain one clause: a
  `ledger_failed` consume whose failure preceded the
  mirror append has burned nothing, and the *system*
  cannot distinguish the two for the caller, so the
  caller-side rule (treat as burned, new ceremony) is
  unchanged and conservative.
- **Journal/mirror divergence as a standing state**: a
  mirror-only burn is now a *legitimate* state, not
  corruption. Anything that later asserts the two journals
  agree entry-for-entry would false-positive on it. This
  constrains option (c)'s reconciliation (§3) and WS1
  (§7.1): divergence checks must be directional, never
  symmetric.

### 2.3 Does (b) pass the mandatory adversarial test?

Sequence: commit consumption → **fail the second write**
(the journal append) → roll back the verifier home → replay
the same envelope.

After step (2), the external signing anchor names the
mirror entry at signing-ledger seq *S*. Rollback restores
the signing ledger to length < *S* (the mirror entry is
gone) while the anchor — outside the home — still says
*S*. The replay spawns a fresh verifier process;
`_load_config` runs `verify_anchor` on the signing ledger
**before the mode executes** and gets
`anchor_ahead_of_journal` (or `anchor_head_not_in_chain`
if the rollback restored a different history of the same
length) → `_config("anchor_refused", …)`, exit 3. Replay
**REFUSED** — refused wholesale, for every mode, until an
operator deliberately repairs via the audited
`force_reanchor` path. ✔

Variant — **fail the mirror itself** (step (1)): nothing
committed, nothing burned, anchor untouched. Rollback is a
no-op against this consume; a later replay is not a
resurrection but the first consumption of an envelope
whose consume never happened. The test's premise ("commit
consumption → fail the mirror") cannot be constructed
under (b), because the mirror *is* the commit; §6 T2 pins
the new semantics explicitly so the change is a decision
on record, not a silent flip of K6.

Variant — **rollback that rolls back the signing ledger
but NOT its external anchor** (the anchored case in the
brief): this is the general rollback case above and is
already the signing anchor's designed behaviour for *any*
post-anchor append; (b) extends consumption's protection
to exactly that behaviour by making every consumption a
post-anchor signing append before anything else happens.
Note the asymmetry the other way: a rollback that restores
*only* `ceremony-consumptions.json` (file-level, signing
ledger intact) is caught by step (5)'s mirror check for
the same envelope, and by §3's reconciliation for the head.

---

## 3. Option (c) — hybrid: (b) + directional reconciliation

(b) plus one addition, in `_mode_ceremony_consume` between
steps (5) and (7):

> **Mirror→journal reconciliation.** Every scoped mirror
> entry (`kind="consume"`, `format="ceremony-consumption"`)
> whose `decision_id` has **no** consumption-journal entry
> is a mirror-only burn (§2.2 — legitimate). But a
> mirror-only burn whose target can be recovered must not
> silently lower the enforced head for *other* envelopes:
> the mirror entry carries no candidate seq/hash (the
> signing entry shape has no column for them — widening
> `EXTRA_KEYS` is a format migration and is out of scope),
> so the head effect of a mirror-only burn is
> **unknowable from the mirror**. Therefore: if any
> mirror-only burn exists, `ceremony_consume` refuses
> **all** further consumptions with `ledger_failed`
> (detail: consumption state diverged; operator
> reconciliation required) until the divergence is
> resolved.

Wait — that is too strong, and I reject my own first
formulation on the numbers: a mirror-only burn arises from
an ordinary step-(3) failure (disk full, crash), and
freezing all ceremonies until an operator intervenes turns
a recoverable per-envelope failure into a system outage,
for a head risk that is narrower than it looks: a
mirror-only burn's *envelope* is refused forever (step
(5)); the only head exposure is a fresh envelope whose
candidate/old-pin relationship to the *unknown* burned
target would have been refused had the target been
journaled — i.e. a fork or regression **at exactly the
burned target's seq**, attempted via a brand-new ceremony
with new evidence, by an allowlisted operator, inside the
window before anyone notices a `ledger_failed` consume.
The pin itself never moved for the burned target, so even
that consumption moves the pin *from its actual current
position*; the monotonicity the head protects is about
adopted pins, and no adoption occurred.

**Adopted form of (c)** — reconciliation as *detection and
surfacing*, not a gate:

- Step (5) already loads both journals. Compute the
  mirror-only set there (scoped mirror ids minus journal
  ids) — no new reads.
- If the presented envelope's own id is in it → already
  refused by the existing cross-check.
- If the set is non-empty for *other* ids, the consume
  **proceeds**, but the divergence is recorded where an
  operator will see it: it is included in the mode's
  stderr-free detail? No — refusals carry detail, successes
  carry the fixed result key set, and the client validates
  that set exactly; there is no success-side warning
  channel, and inventing one is scope creep. The honest
  surfacing mechanism that exists today is the journals
  themselves plus the health check
  (`deploy/verifier-identity/health_check.py`): add a
  health-check item reporting mirror-only burns by
  authorisation_id. Operator resolution of a mirror-only
  burn needs no tooling: it is already terminal (envelope
  burned, recovery = new ceremony, WS1 validates the burn
  from the mirror — §7.1); the health-check line exists so
  the state is *known*, not so anyone must clear it before
  the system works.
- The reverse divergence (journal entry with no mirror —
  the cycle-21 failure shape) **cannot occur** under (b)'s
  order except by selective file rollback of the signing
  ledger, which the signing anchor catches at startup. No
  consume-time check is needed for it; assert it in tests
  (T5) rather than code.

So (c) = (b) + a health-check visibility item + the
explicit directional-divergence doctrine. The doctrine is
the real deliverable: *mirror ⊇ journal is a legal state;
journal ⊄ mirror is impossible-by-construction and
anchor-detected if forced.*

---

## 4. Recommendation

### 4.1 Pick: **(c) — mirror-first restructure (§2) with the
§3 reconciliation doctrine.** Not (a).

Justification, in order of weight:

1. **It closes the Gemini defect using protection that
   already exists and is already mandatory in
   production.** Production already requires
   `AION_ANCHOR_PATH` and refuses startup on anchor
   mismatch. (b) makes every consumption an anchored
   signing-ledger append *before* any unanchored write, so
   the class "burn exists only in an unanchored journal"
   is eliminated by construction, not mitigated: there is
   no code path that creates a consumption fact in the
   journal before the anchored mirror. (a), by contrast,
   builds a *second, parallel* anchor apparatus to protect
   the journal in place.
2. **Zero env/allowlist growth.** Allowlist stays **17** in
   all five copies (§1.3); no new `_Config` fields, no new
   startup blocks, no genesis ceremonies, no flag day for
  undeployed-yet production config. (a) spends 2–4 new env
   names and two ceremonies to reach a *narrower* version
   of the same guarantee (§1.2's residual is identical in
   kind to §4.3's).
3. **The mandatory test passes at the strongest layer.**
   Under (c), the rolled-back replay is refused in
   `_load_config` — before mode dispatch, before envelope
   parsing — with `anchor_refused`. Under (a) it is also
   refused at startup, but only for deployments that
   configured the new anchor; under (c) the protection is
   coextensive with the signing anchor production already
   mandates.
4. **Failure semantics improve.** Pre-commit mirror failure
   no longer burns an envelope for an infrastructure fault
   that created no state (§2.1). Cycle 21's burn-on-mirror-
   failure was an artefact of ordering, and Gemini's defect
   is the proof it bought nothing.
5. **The head authority is untouched.** The journal still
   owns `head_target()` and the R3 rules; `check_head`,
   the polymorphic head contract, and T7′/T8′ semantics do
   not move. The change is confined to commit order, one
   ledger method's retry discipline, docstrings, and tests.

### 4.2 What (c) deliberately does not do

- **Issuance journal: not anchored, not restructured, this
  cycle.** The authorise order (journal → mirror → anchor)
  has the analogous gap, and I considered applying the same
  mirror-first flip there for symmetry. Rejected for this
  cycle: authorise's journal append is also its
  anti-replay scan's commit (the `(ceremony_id,
  evidence_hash)` re-check lives inside
  `append_authorisation`), and the signing entry shape
  cannot carry `evidence_hash`/`operator_id`, so a
  mirror-first authorise would need the mirror to enforce
  a uniqueness it cannot express — a genuinely different
  design, not a flip. The issuance residual stays exactly
  as documented in `CeremonyAuthorisationLedger`'s
  docstring (rollback resurrects a burned pair; duplicate
  issuance under the *same* `ceremony_id` remains visible
  in the anchored signing ledger; evidence reuse under a
  *new* `ceremony_id` is not detectable from the anchored
  store). `ceremony-journal-anchoring` is **narrowed, not
  closed**: it now covers the issuance journal only, and
  (a)'s §1.1 shape is the sketched route if it is ever
  built. Flagging honestly: if the external seats judge
  the issuance gap equal in severity to the consumption
  gap, this scoping is the first thing they will push on —
  the defence is severity asymmetry (issuance resurrection
  yields an envelope that must still survive consumption,
  where single-use and the head now anchored-side commit;
  consumption resurrection yields a *second pin movement*)
  plus the inexpressibility point above.
- **No new anchor kinds.** `ANCHOR_KINDS` stays
  `("signing", "ship", "ship-tx")`.
- **No pin-store anchoring** (WS3, §7.2).

### 4.3 Residuals, stated plainly (for the build record)

- **Append→anchor crash window (inherited, not new).**
  Mirror append lands; process dies (or anchor write
  fails) before `_update_anchor`; *then* the home is
  rolled back to before the mirror append. Journal, ledger
  and anchor mutually agree on the shorter history; the
  burn is undetectable and the envelope can be consumed
  after rollback. This window is one atomic anchor-file
  replace wide, exists today for **every** signing-ledger
  append (gate decisions included), and (a) has the
  identical window in its own append→anchor step. Closing
  it would require the anchor write to precede the journal
  write (impossible — the anchor names the entry's hash)
  or synchronous multi-file transactions the journal
  mechanism does not have. The claim wording must carry
  it: rollback-resistance holds for consumptions whose
  consume returned **or** whose anchor update completed;
  equivalently, a consume that reported `ledger_failed`
  from the anchor step is rollback-protected only against
  an intact-or-partially-rolled-back home, not against a
  full pre-consume snapshot restore in that window.
  Practical narrowing, worth the one line it costs: in
  step (8), call `_update_anchor` **before** the journal
  append (already specified) — and nothing else may be
  inserted between mirror append and anchor update.
- **Research mode is not rollback-protected — unchanged
  and now load-bearing in the wording.** With
  `AION_ANCHOR_PATH` unconfigured, `_update_anchor` is a
  no-op, the mirror is an unanchored file in the same home,
  and a home rollback erases journal + mirror together:
  replay succeeds within the TTL. (c)'s entire rollback
  claim is conditional on anchoring being configured,
  which production mandates and research does not. Every
  claim sentence in the rewritten docstrings must keep
  the cycle-21 qualifier form ("in production /
  with anchoring configured"); the R10 paragraph's
  research-mode sentence carries over verbatim in
  substance.
- **Mirror-only burns are permanent and visible-but-not-
  self-healing** (§3). The envelope is burned; the target
  is recoverable only via a new ceremony (WS1). No
  un-consume, no backfill of the journal entry is
  permitted — backfilling would fabricate a head entry
  whose `consumed_at`/seq ordering the journal never
  witnessed. (Considered and rejected; if a future cycle
  wants journal completeness, it must be an operator-
  initiated, audited repair, not verifier behaviour.)

### 4.4 Exact change list (for the build seats)

| File | Change |
|---|---|
| `trust/verifier_main.py` `_mode_ceremony_consume` | Step (8) reordered: mirror append → `_update_anchor(config)` → journal append. Docstring "Commit order" + crash-contract paragraphs rewritten; step (5) gains the mirror-only-set computation (no new reads). Error mapping unchanged (`AlreadyConsumedError`→`ceremony_already_consumed`, `HeadRegressionError`→`ceremony_head_regression`, other→`ledger_failed`) but now reachable from either append. |
| `trust/ledger.py` `SigningLedger.append_ceremony_consumption` | Bounded reload-retry with in-loop scoped duplicate re-check raising `AlreadyConsumedError` (§2.1). Docstring inverted: it is the commit point, written FIRST. |
| `trust/ledger.py` `CeremonyConsumptionLedger` | Class + `append_consumption` docstrings: no longer the commit point; remains the head authority; R10 paragraph replaced (§5 wording). The "mode-level cross-check" scope note in `append_consumption` is updated: the mirror is now prior, not posterior. |
| `trust/client.py` | `ceremony_consume` / `ceremony_consumer` docstrings: one clause on pre-/post-commit `ledger_failed` indistinguishability (§2.2). No code change. |
| `signing/pin_ceremony.py` | Crash-contract docstring: name the mirror append as the commit it already describes. No code change. |
| `deploy/verifier-identity/health_check.py` | New check item: report mirror-only burns (scoped signing entries with no journal entry) by authorisation_id; informational, not a failure — mirror-only is a legal state (§3). |
| `internal/DECISION-CONSUMPTION-HEAD.md` | Addendum (new dated section, do not rewrite history): commit point moved to the anchored mirror; "Accepted residuals" consumption-anchoring bullet superseded; follow-up `ceremony-journal-anchoring` narrowed to the issuance journal. |

No env vars. No `_Config` changes. No `trust/protocol.py`
change (mode set unchanged). No allowlist change (17, five
copies untouched). No journal format change (both
`EXTRA_KEYS` sets untouched — this is the decisive
advantage over any design that puts the candidate target
in the mirror).

Startup/genesis behaviour: **unchanged.** The signing
anchor's existing startup verification and INIT ceremony
are the whole story; there is nothing new to initialise,
which is precisely why (c) can ship without a deployment
ceremony.

---

## 5. Claim wording after WS2 (drop-in replacements)

For the `CeremonyConsumptionLedger` R10 paragraph and the
BUILD-CYCLE-22 record, replacing cycle 21's residual text:

> Consumption is committed in the externally anchored
> signing ledger (scoped `kind="consume"`,
> `format="ceremony-consumption"` mirror entry) and the
> signing anchor is advanced over that entry **before**
> the consumption-journal append; the journal remains the
> monotonic-head authority but is never the first durable
> record of a burn. With anchoring configured (mandatory
> in production), a rollback of the verifier home that
> erases a consumption whose anchor update completed is
> detected at verifier startup (`anchor_refused`) and the
> envelope cannot be consumed again; a rollback that
> erases only the consumption journal is refused by the
> mirror cross-check. In research mode (anchoring
> unconfigured) neither journal is rollback-protected and
> no rollback claim is made. A consumption whose mirror
> append landed but whose anchor update did not complete
> is protected against an intact home (mirror cross-check)
> but not against a full rollback to a pre-consumption
> snapshot taken before the anchor update — the same
> append→anchor window every signing-ledger append in
> this system carries.

---

## 6. Test list

Harness facts used: `tests/test_trust_ceremony_consume.py`
drives the mode in-process (`ConsumeFixture`, `patch.object`
for fault injection) **and** via wrapper modules —
subprocesses that monkeypatch a ledger method then call
`verifier_main.main()` (K1 kill-before-append, K2
kill-after-append, K6 `MIRROR_FAIL_MODULE`, K6b
kill-after-mirror, K5 barrier in `_save`).
`tests/test_trust_ceremony_consumption.py` drives the real
verifier end-to-end via `VerifierClient` against a temp
home, in **research mode with no anchor configured** — the
rollback tests below need a second fixture variant with
`AION_ANCHOR_PATH` set to a path **outside** the home
(e.g. `base / "anchors" / "signing.anchor.json"`) and
`AION_ANCHOR_INIT="1"` for the bootstrap request, then
INIT removed (research mode tolerates the flag, but the
fixture should model the production steady state: anchor
exists, no INIT).

**Mandatory adversarial test (the brief's test) — T-WS2-1,
subprocess suite.** Configure the anchored fixture.
Authorise envelope *E*. Snapshot the **entire verifier
home directory** (`shutil.copytree` of `home/"ledger"` —
all journals, since a home rollback restores all of them)
to `base/"home-snapshot"`. Consume *E* via a wrapper
module in the K6 pattern that patches
`CeremonyConsumptionLedger.append_consumption` to raise
**after** the mirror append and anchor update have landed
(the journal append is the second write under the new
order; failing it is the exact Gemini analogue). Assert:
exit 3, `ledger_failed`; signing ledger contains exactly
one scoped consume entry for *E*; consumption journal has
no entry for *E*; the anchor file's `seq` equals the
signing ledger's length. Then roll back: delete the live
ledger dir, restore it from `home-snapshot` (anchor file,
living outside the home, is **not** touched). Replay *E*
through a fresh `VerifierClient`: must **REFUSE** —
assert the refusal is the startup refusal
(`anchor_refused`, surfaced by the client as a
`VerifierConfigError`/SigningError chain naming it), not
merely any error, and assert no new entry appears in any
journal. This test fails against cycle-21 code (replay
succeeds) and against a mirror-first-without-anchor-update
variant (anchor never advances; rollback is consistent) —
both mutations should be run once during the build to
prove the test has teeth, and the results recorded in the
build record.

**T-WS2-2 — mirror failure no longer burns (K6 flipped).**
Rewrite `test_k6_mirror_failure_after_commit_burns` as
`test_k6_mirror_failure_before_commit_burns_nothing`:
`MIRROR_FAIL_MODULE` (patch
`SigningLedger.append_ceremony_consumption` to raise) →
exit 3 `ledger_failed`; **zero** entries in both journals;
a subsequent clean consume of the same envelope
**succeeds**. The flip must be called out in the build
record as an intentional semantics change (§2.1), the way
T7/T8's flips were in cycle 21. K6b is re-pointed: kill
after mirror+anchor, before journal append → state is a
mirror-only burn; replay refuses
`ceremony_already_consumed`; exactly one scoped mirror
entry, zero journal entries; a *fresh* envelope for the
same target (new ceremony/evidence) consumes successfully
(pins §2.2's recovery semantics).

**T-WS2-3 — anchored-case rollback (no fault injection).**
Anchored fixture; consume *E* cleanly (success). Snapshot
was taken before the consume (as in T-WS2-1); roll back
home only; replay *E* → `anchor_refused` at startup. Also
the signing-ledger-only variant: restore **only**
`signing-ledger.json` from the snapshot (journal left at
post-consume state) → startup still refuses
(`anchor_ahead_of_journal`), proving protection does not
depend on which in-home file the rollback restores.

**T-WS2-4 — mirror scoping stays load-bearing.** Existing
`test_mirror_scoping_sign_and_consume_entries_coexist`
(subprocess suite) must pass unchanged; add the negative
pin: a unit test that constructs the step-(5) check
inputs with the issuance `kind="sign"` entry only and
asserts the first consume is **not** refused (the trap
`append_ceremony_consumption`'s docstring already warns
about, now guarding the commit path itself).

**T-WS2-5 — directional divergence.** Hand-craft (via the
real ledgers, not file edits) a journal entry with no
mirror — possible only by calling
`append_consumption` directly, bypassing the mode — then
run a mode consume of a *different* envelope: it must
**succeed** (no symmetric reconciliation gate, §3), and
the health-check item must report the mirror-only set
correctly in the T-WS2-2 state (mirror entry, no journal
entry) and report empty in the clean state. (The
journal-only state is asserted as *detectable in
principle*, not gated on.)

**T-WS2-6 — race re-pointed.** K5's forced interleave
moves from `CeremonyConsumptionLedger._save` to the
mirror's reload→save window (barrier in
`SigningLedger._save` filtered to the consume append, or
in `append_ceremony_consumption` itself): two concurrent
consumes of one envelope → exactly one success, loser
`ceremony_already_consumed` (now surfaced from the
mirror's in-loop re-check), exactly one scoped mirror
entry and one journal entry. The APPEND_WINDOW_REACHED
proof-of-interleave discipline carries over.

**T-WS2-7 — anchor-update failure burns, wording
pinned.** Wrapper patching `verifier_main._update_anchor`
to raise when called from the consume commit (after the
mirror append): exit 3 `ledger_failed`; mirror entry
present, journal entry absent; replay against the
**intact** home refuses `ceremony_already_consumed`.
(This is §4.3's residual state, minus the rollback; the
rollback half is *not* tested as a refusal — it is the
documented window. Add a characterisation test in the
anchored fixture that performs it and asserts the replay
**succeeds**, labelled as pinning the §5 claim's boundary,
so a future cycle that closes the window must flip a
test deliberately rather than silently. If the war room
judges a success-asserting test unacceptable in the suite,
the fallback is asserting the §5 wording's presence in
the docstrings — but a behavioural pin is the honest
option and I recommend it.)

**T-WS2-8 — research-mode honesty.** In the existing
unanchored subprocess fixture: consume, roll back the
home (both journals), replay within TTL **succeeds** —
characterisation test pinning §5's "no rollback claim in
research mode", mirroring T-WS2-7's rationale.

**T-WS2-9 — oracle regressions** (§7 tests): the existing
`test_invalid_envelopes_indistinguishable_to_caller`
passes unchanged; new test enumerating the consume
refusal surface (§7.2's table) asserting each row's exit
code and error code, so any future collapse or split of
codes is a deliberate test change.

**Unchanged suites that must stay green:** K1 (kill before
any append burns nothing — now: before the mirror), K2/K3
(commit-before-response / lost response), K4 (deleted
journal, mirror refuses — under (c) this is now a
first-order property, not a mitigation), head-rule tests,
seed-hygiene and Ed25519 suites (untouched).

---

## 7. Oracle sub-task — the ceremony refusal surface

### 7.1 Audit: what is actually distinguishable today

`ceremony_consume` refusals, as coded in
`_mode_ceremony_consume` (exit codes from `_Refuse`:
`_malformed` = 2, `_config` = 3):

| Code | Exit | Class | Reached only if |
|---|---|---|---|
| `ceremony_seed_unconfigured` | 3 | config | mode disabled — before body is read |
| `malformed_request` | 2 | parse | body key set wrong, or envelope unparseable |
| `ceremony_authorisation_invalid` | 2 | **verification** | `verify_ceremony_authorisation` returned any reason set **not** ⊆ {expired, signed_in_future} |
| `ceremony_authorisation_expired` | 3 | **temporal** | reasons ⊆ {`expired`, `signed_in_future`} — i.e. the envelope is valid in **every non-temporal respect** and only its time window is wrong (note: a not-yet-valid envelope also lands here; the code name says "expired" for both) |
| `ceremony_already_consumed` | 3 | state | envelope **passed verification**, and its id (journal or scoped mirror) or its target is consumed |
| `ceremony_not_issued` | 3 | state | passed verification; no matching issuance-journal entry/fields |
| `ceremony_head_regression` | 3 | state | passed verification + issuance + single-use; head rules refuse (detail string varies — `str(exc)` from `HeadRegressionError` is included) |
| `ledger_failed` | 3 | infrastructure | a journal could not be read/committed/mirrored at some step — including, today, *after* the commit (so it also leaks "your envelope was valid and is now burned" to a caller who correlates it with a subsequent `already_consumed`) |

`ceremony_authorise` is more granular still, by design:
`ceremony_operator_not_authorised`,
`ceremony_evidence_hash_mismatch`,
`ceremony_id_reused`, `ceremony_evidence_reused` (all
exit 3/2 config/malformed classes) — each names exactly
which single-use fact collided.

**Who can observe.** The only caller is the ceremony
process: `VerifierClient.ceremony_consume`, whose `_run`
surfaces exit-3 codes as `VerifierConfigError` and exit-2
as protocol/malformed errors, and `ceremony_consumer()`
folds all of them into `SigningError("ceremony consumption
refused: …")` for `reanchor_pin`. There is no unauthenticated
network surface; the "forger" of the threat model is a
party who has obtained (or fabricated) an envelope and can
present it to a verifier they can launch — i.e. they
already hold whatever the envelope contains. Stdout/stderr
uniformity within the verification class was established
in cycle 21 (rev-r3 HIGH-1: byte-identical across
verification-failure classes, regression-tested); the
distinctions above are carried in the **error code of the
structured response**, deliberately, not leaked via side
channels.

**What each distinction actually leaks, honestly:**

- *expired vs invalid* is a genuine validity oracle: an
  `expired` response certifies that the presented envelope
  is a **genuine, correctly-signed, correctly-bound**
  envelope whose only defect is time. A forger holding a
  *stolen* envelope learns it is genuine (worth attacking
  the clock/TTL for, or worthless); a forger holding a
  *fabricated* envelope learns nothing from `invalid`
  beyond "some non-temporal check failed" — the class
  itself stays uniform. The oracle is real but narrow: it
  confirms authenticity of an artefact the presenter
  already possesses in full.
- *State codes vs verification codes*: `already_consumed`
  / `not_issued` / `head_regression` are reachable **only
  after verification passes**, so they leak state only
  about genuine envelopes the presenter already holds.
  They are also operationally necessary: the recovery
  workflow (new ceremony? new evidence? wait for head to
  advance?) is chosen from them, and WS1's honest-reason
  validation depends on `already_consumed` remaining
  distinct.
- *`ledger_failed`* leaks verifier-internal health and,
  correlated across two calls, commit state. Under WS2's
  reorder it is emitted both pre-commit (mirror failure —
  nothing burned) and post-commit (anchor/journal failure
  — burned) **under the same code**, so the code alone
  does not disclose which side of the commit a failure
  fell on; the follow-up `already_consumed` on retry is
  what discloses it, and that disclosure is the state
  oracle already accepted above.

### 7.2 Recommendation: **narrow the claim; do not collapse
the codes.**

Collapsing `expired` into `invalid` would (i) contradict
cycle 21's deliberate introduction of the expired code,
reviewed by both external seats without objection to its
existence; (ii) break the client's recovery guidance
("the correct operator response is a new ceremony" is
calibrated per code in `trust/client.py`); (iii) buy
almost nothing — the genuine-envelope holder's authenticity
confirmation is the only leak, and the same holder learns
the same fact from any subsequent state code. Collapsing
the state codes into one would destroy WS1's validation
surface and the head-regression diagnostics for a leak
that requires already holding a valid envelope. The
defect Gemini named is in the **claim wording**, which
currently reads (consume docstring): "ONE failure code
(`ceremony_authorisation_invalid`) for all non-temporal
verification failures — no forger oracle". Read literally,
"no forger oracle" over-claims: temporal and state
distinctions exist and are observable. Fix the sentence,
not the codes.

**Exact replacement wording** — for the
`_mode_ceremony_consume` docstring (validation-order
paragraph) and any place the "no forger oracle" phrase
appears (grep `oracle` across `trust/`, `signing/`,
`internal/BUILD-CYCLE-21.md`'s successor text):

> One refusal code, `ceremony_authorisation_invalid`, for
> **all verification-failure classes** — signature,
> signer, payload structure and binding failures returned
> by `verify_ceremony_authorisation` — with byte-identical
> stdout and stderr across those classes: within
> verification failure there is no per-reason forger
> oracle. The no-oracle claim covers **verification
> failures only**. By design, and outside that claim:
> temporal failure (reasons ⊆ {expired, signed_in_future})
> returns `ceremony_authorisation_expired` — which
> therefore certifies an envelope valid in every
> non-temporal respect; post-verification state refusals
> return `ceremony_already_consumed`,
> `ceremony_not_issued` and `ceremony_head_regression`,
> reachable only by an envelope that passed verification;
> and infrastructure failure returns `ledger_failed`,
> the same code on both sides of the commit point.

And in `trust/ledger.py`, `AlreadyConsumedError`'s
docstring already describes the mode mapping accurately;
add one sentence: "These distinctions are state oracles
by design (see the consume mode's docstring); the
no-oracle claim covers verification failures only." —
so the next reader does not re-derive the over-claim
from the ledger side.

Under WS2's reorder nothing in this table changes: same
codes, same exits, same reachability preconditions. That
stability is a further argument for (c) over any design
that introduces new refusal codes (e.g. a divergence code
in §3's rejected strong form).

---

## 8. Design-together critiques

### 8.1 WS1 — honest recovery reason (`burned_unadopted`)

WS1 (as scoped in CROSS-CHECK-15): a new ceremony reason,
validated at authorise time against a **recorded burn**,
replacing the false `lost_pin` label for the
consumed-but-pin-unmoved case.

**What WS2 implies for that validation read — it must not
read the consumption journal alone.** Three reasons, in
increasing order of severity:

1. **Under WS2, the journal is no longer the complete
   burn record.** The mirror-only burn (§2.2) is a real,
   WS2-created state: genuinely burned, journal entry
   absent. A journal-only validation would refuse honest
   recovery for exactly the failure class WS2 makes most
   visible — the step-(3)-failure cases — recreating the
   F4 falsification pressure one level down (operators
   would fall back to `lost_pin` when `burned_unadopted`
   validation spuriously fails). WS1's validation must
   read the **union**: journal `find_by_authorisation`
   **or** the scoped signing-ledger mirror entry
   (`kind="consume"` + `format="ceremony-consumption"` +
   `decision_id`). The mirror is the commit point under
   WS2, so the mirror is the *authoritative* burn proof;
   the journal entry is corroboration. If WS1's seat
   designs validation as journal-primary, this critique is
   my formal objection.
2. **Under rollback, the validation fails closed — say
   so in WS1's claim.** Rolling back the home erases the
   journal record of the burn; the mirror record survives
   only via the signing anchor's startup check, which
   refuses the *whole verifier* (`anchor_refused`) rather
   than letting authorise proceed on a partial history.
   So in production, WS1 validation never silently reads a
   rolled-back burn record: either the anchor check has
   already halted everything, or (selective journal-only
   rollback) the mirror half of the union still proves the
   burn. The dangerous direction would be validation as a
   *grant* on journal evidence that a rollback could
   **fabricate** — it cannot: rollback only ever *removes*
   entries, and removal makes validation refuse (liveness
   loss, safe direction). WS1's docstring should state:
   validation is fail-closed under rollback; a burn whose
   records were rolled back cannot be validated, and
   recovery then needs operator intervention, not a
   weaker check.
3. **Placement cost WS1 must budget for:** validation
   lives in `_mode_ceremony_authorise`, which today reads
   the issuance journal but **never** the consumption
   journal or the signing ledger's consume entries. WS1
   adds both reads to the authorise path; an unreadable
   consumption journal / signing ledger there must refuse
   `ledger_failed` (never validate against partial state),
   mirroring the consume mode's step-(5) discipline. Also
   note the reason-vocabulary mechanics WS1 inherits:
   `REASONS` in `signing/pin_ceremony.py` and its mirror
   in `signing/ceremony_authorisation.py` (drift-tested
   equal) both gain `burned_unadopted`, and since it is a
   recovery *with* an old pin (the pin exists; it merely
   never moved), it does **not** join `_NO_PIN_REASONS` —
   the mode's coherence rule ("old pin present ⇒ reason
   must be `chain_gap_recovery`") needs a deliberate
   second admitted reason for the old-pin case, which is
   a real change to `_mode_ceremony_authorise`'s
   validation, not just a vocabulary addition. Flagging
   for WS1's seat; not my slice to design further.

### 8.2 WS3 — first production adopter (loop/storage pin adoption)

**Shape I support:** the adopter is a small function in
the loop/storage layer (not in `trust/`, not in
`signing/`) that: builds the production client via
`trust/wiring.production_client` (never a hand-rolled
`VerifierClient`); calls `reanchor_pin(...,
consume_authorisation=client.ceremony_consumer())`; and
**adopts** the returned pin by atomic replace of the pin
store file (write temp in the same directory, fsync,
`os.replace`, fsync the directory — the
`HashChainJournal._save` discipline, reused as a pattern,
not imported as a class). Adoption happens only on
`reanchor_pin` success; any exception leaves the on-disk
pin byte-identical. The consumed-but-not-adopted crash
(crash between consume success and the replace, or a lost
response) is exactly WS1's `burned_unadopted` case — WS3
is where that state stops being hypothetical, which is
why WS1 and WS3 are correctly in the same cycle.

**Placement cautions:** (i) the adopter must present the
*on-disk* pin as `old_pin`, re-read at ceremony start,
never a cached in-memory pin — a stale cached old-pin is
how the adopter would manufacture head regressions the
verifier then has to refuse; the verifier's old-pin
not-behind rule is the backstop, not the mechanism.
(ii) The adopter owns **no** retry: `reanchor_pin`'s
contract (never re-consume; recovery is a new ceremony)
must survive wrapping — an adopter-level "try the whole
ceremony again on failure" helper would silently re-mint
ceremonies and must not be built.

**Should the adopter's pin store be anchored? No — not
this cycle, and the argument is scope, not dismissal.**
(a) The pin store lives in the *caller's* trust domain
(loop user), not the verifier's; anchoring it means a new
anchor kind, a new external location meaningful against
the *loop's* rollback attacker, and a startup/genesis
story for a store this cycle is creating for the first
time — a second anchoring design inside a cycle that
already closes one. (b) The protection it would buy is
already partially present: a rolled-back pin store
presents an old pin behind the consumption head, and the
verifier refuses (`ceremony_head_regression`) — the
rollback is *detected at the next ceremony* by WS2's
anchored head, which is the correct division of labour.
What pin-store rollback can still do is lose *advance_pin*
movements (which never pass through the verifier) — that
is the long-standing pin-store compare-and-swap /
`ledger-head-anchoring` follow-up, named since cycle 21,
and WS3 should **unblock** it (a real pin store with a
real adoption path is its precondition) without absorbing
it. WS3's build record should state the residual in one
sentence: the adopted pin store is caller-side state,
unanchored; its rollback is detected only insofar as the
verifier's ceremony head has seen the movements it rolls
back over.

**Interaction with WS2 specifically:** none adverse. The
adopter is indifferent to which journal commits first —
it sees only `reanchor_pin`'s success/exception contract,
which WS2 preserves. One request to WS3's seat: the
adopter's integration test should run against the
**anchored** fixture variant (§6), not the research
fixture, so the first production adopter is never
exercised only in the mode where WS2 makes no claim.

---

## 9. Risks and open questions, honestly

- **R-1. The claim shrinks before it grows.** WS2's
  reorder changes a cycle-21 *tested* behaviour (K6:
  mirror failure burns). External seats accepted the
  burn-on-failure semantics as part of cycle 21's
  crash contract; flipping it — even to strictly safer
  semantics — needs the same explicit flip treatment
  T7/T8 got, and seat-gemini may read "mirror failure no
  longer burns" as weakening single-use. My reading: it
  strengthens it (no state ⇒ no burn is the only coherent
  commit definition), but this is the design's most
  contestable call and the war room should spend its
  argument there.
- **R-2. `_update_anchor` is shared.** It is called by
  every signing mode after its appends. WS2 changes only
  the consume mode's *call site order*, not the helper —
  but a builder who "tidies" the helper or the other call
  sites in passing can break gate/attestation anchoring.
  The change list (§4.4) is deliberately call-site-only;
  reviewers should diff-guard it.
- **R-3. Signing-ledger growth and contention.** Every
  consumption now appends to the signing ledger *first*,
  under its `_save` freshness discipline, in the same
  directory flock domain as all other verifier appends.
  Consumption volume is ceremony volume (rare, operator-
  paced), so contention is not a practical concern; the
  8 MB journal cap is the only long-horizon watch item,
  unchanged in kind from issuance mirrors.
- **R-4. The §4.3 window will be quoted back.** The
  characterisation tests T-WS2-7/8 assert replay
  *successes*. If the external seats treat any
  success-asserting rollback test as an admission that
  item (3) is still open, the fallback (docstring-presence
  assertions) keeps the honesty with less evidence. I
  recommend keeping the behavioural pins and letting the
  seats react to facts.
- **R-5. Health-check scope.** §3's health-check item
  reads both journals from the deploy tooling; the health
  checker today validates anchors and env, not journal
  cross-consistency. If its seat judges journal reads out
  of the checker's remit, the fallback is a line in the
  cycle-22 build record + the T-WS2-5 assertion, and the
  visibility item moves to a named follow-up — the
  *doctrine* (directional divergence is legal) must land
  in the ledger docstrings regardless, because WS1's
  validation depends on it.
- **Open question for the coordinator:** does WS1's
  validation read land in `ceremony_authorise` as §8.1(3)
  assumes, or does WS1's seat place it in a pre-check the
  *client* performs? If the latter, my union-read
  requirement applies there instead — but a client-side
  validation would be caller-supplied-state reasoning all
  over again, and I would object. Confirming the
  verifier-side placement in the design-final would close
  this.

---

*Seat B, cycle 22 design phase. Recommendation in one
line: move the consumption commit point into the anchored
signing ledger (mirror append → anchor update → journal
append), keep the journal as head authority, add no env
vars and no anchor kinds, narrow the no-oracle claim to
verification failures, and let WS1 validate burns against
the mirror ∪ journal union.*
