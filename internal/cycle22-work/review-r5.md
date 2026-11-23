# Cycle 22 — war-room review, seat rev-r5 (claims & wording honesty)

Date: 2026-11-23. Scope: full cycle-22 diff on top of aeb6ef6
(`git diff HEAD`) plus new files `signing/pin_store.py`,
`trust/pin_adoption.py` and the new test files. Lens:
CROSS-CHECK-14/15 — the external seats have repeatedly caught
WORDING over-claims in this project; code behaviour was checked
only where a claim depends on it. Blind review: no other
reviewers' notes read.

## Verdict: FIX — 0.78

The new cycle-22 wording in `trust/verifier_main.py` (consume
docstring, header env block) and in the
DECISION-CONSUMPTION-HEAD addendum is exact and honest. But
three pre-existing passages that DESIGN-FINAL R4 explicitly
ordered swept were NOT swept, and they now directly contradict
the shipped design: the consumption journal's own R10 docstring
still says it is not anchored, the deploy README still says a
consumed target is never re-anchorable and its recovery
candidate is ahead of the head, and `signing/pin_ceremony.py`
still summarises the old R10 residual. A reader of
`trust/ledger.py` or the deploy README — exactly the readers
the external seats read — gets the cycle-21 claim, not the
cycle-22 one. Targeted tests pass (see below); this FIX is
wording-only, no code behaviour is impugned.

---

## Findings

### F1 — HIGH — `CeremonyConsumptionLedger` R10 docstring not rewritten; states the opposite of R2

Evidence: `trust/ledger.py:715-727`:

> "Anchoring residual (cycle 21, R10, stated precisely):
> this journal is NOT externally anchored this cycle. A
> rollback of the verifier home cannot resurrect a
> consumed envelope whose consumption is mirrored in the
> anchored signing ledger (production), but can lower the
> enforced head for never-consumed envelopes. The
> follow-up ceremony-journal-anchoring covers both
> journals (issuance + consumption) jointly. In research
> mode (anchoring unconfigured) the mirror itself is
> unanchored …"

Every clause is now false or superseded: the journal IS
externally anchored (`trust/anchoring.py` ANCHOR_KINDS gains
`"ceremony-consumption"`; `_load_config` verifies it per
request); the follow-up is NARROWED to the issuance journal
only (DESIGN-FINAL R2; DECISION addendum); and the R2 residual
form (anchor-completed burns survive rollback, detected at
startup; append→anchor window NOT protected against a full
rollback inside it) appears nowhere in this docstring.
DESIGN-FINAL R2: "cycle-21 R10 paragraph is rewritten to
state: …"; R4: every commit-order/residual passage in
`trust/ledger.py` reconciled. Not done. The class docstring
at `trust/ledger.py:711-714` ("audit mirror written only
after this commit; it is never the authority and must never
be appended first") is by itself still true under R2's order
(journal → consumption-anchor → mirror → signing-anchor) and
needs no change beyond F1's paragraph.

Exact replacement for `trust/ledger.py:715-727`:

> Anchoring (cycle 22, R2, replacing cycle 21's R10
> residual): this journal IS externally anchored in its
> own right (anchor kind "ceremony-consumption", verified
> by the verifier at startup on every invocation when
> configured; required in production when the ceremony
> seed is configured). With the consumption anchor
> configured, a burn whose anchor update completed
> survives a verifier-home rollback (detected at startup,
> anchor_refused); the append→anchor-update window (burn
> in journal, anchor at pre-burn prefix) is protected
> against an intact home but NOT against a full rollback
> inside that window — the same window every anchored
> append in this system carries; research mode / anchor
> unconfigured: no rollback claim, and this journal can
> be deleted or rolled back undetectably. The follow-up
> ceremony-journal-anchoring is narrowed to the issuance
> journal only.

### F2 — HIGH — deploy README: burned-recovery paragraph contradicts `burned_unadopted`, and "no new configuration" is now false

Evidence: `deploy/verifier-identity/README.md:253-270`
(unchanged except the INIT-flag list at :121-125):

- :261-263: "…the consumption journal lives in the verifier
  home alongside the other journals — **no new configuration
  is needed for the mode** beyond the cycle-20 ceremony
  provisioning above." False in cycle 22: two new allowlisted
  env names (`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` /
  `_INIT`, allowlist 17→19), and production + ceremony seed
  REQUIRES the consumption anchor path.
- :266-270: "the consumed target is permanently spent and is
  **never re-anchorable**. Recovery is a NEW ceremony …
  **whose candidate is ahead of the consumption head**".
  This is precisely the pre-WS1 claim R1 abolished: a
  `burned_unadopted` recovery re-anchors the EXACT head
  target (candidate == head, exact old pin), under the one
  scoped head exception. As written, the README denies the
  feature this cycle ships and misdescribes its shape.

Exact replacement for `deploy/verifier-identity/README.md:261-270`:

> Consumption is committed at the verifier before the
> ceremony returns anything. Cycle 22 adds one new
> configuration pair for the mode: the consumption journal
> is externally anchored via
> `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` /
> `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` (allowlist
> 17 → 19); production mode with the ceremony seed
> configured requires the path and refuses the INIT flag.
> With the consumption anchor configured, a burn whose
> anchor update completed survives a verifier-home
> rollback (detected at startup); the
> append→anchor-update window is NOT protected against a
> full rollback inside that window; research mode /
> anchor unconfigured: no rollback claim.
> **Burned-but-unmoved recovery:** because the consumption
> commit precedes pin adoption, a crash or a lost response
> after the commit leaves the authorisation burned and
> the pin unmoved. The burned authorisation itself is
> permanently spent and is never re-consumed; recovery is
> a NEW ceremony (new `ceremony_id`, new evidence bundle)
> under reason `burned_unadopted`, whose candidate is the
> consumed head target itself (not ahead of it) and whose
> old pin exactly equals the head entry's recorded old
> pin, proven by the verifier against its consumption
> journal at authorise and again at consume. There is no
> un-consume, and the client never retries a consume
> automatically.

### F3 — HIGH — `signing/pin_ceremony.py` module docstring still summarises the old R10 residual

Evidence: `signing/pin_ceremony.py:291-297`:

> "The consumption journal's own rollback residual is
> different (R10, stated precisely in
> `CeremonyConsumptionLedger`'s docstring): a rollback of
> the verifier home cannot resurrect a consumed envelope
> whose consumption is mirrored in the anchored signing
> ledger (production), but can lower the enforced head for
> never-consumed envelopes."

This is the cycle-21 mirror-based residual, presented as
current, and it delegates to the docstring F1 shows was
never rewritten — so the pointer compounds the error. It
omits all three R2 qualifiers (anchor-completed survival /
startup detection; window not protected against full
rollback inside it; research/unconfigured = no claim).

Exact replacement for `signing/pin_ceremony.py:291-297`:

> The consumption journal's own rollback position is
> different (stated precisely in
> `CeremonyConsumptionLedger`'s docstring): since cycle
> 22 the consumption journal is externally anchored in
> its own right; with the consumption anchor configured,
> a burn whose anchor update completed survives a
> verifier-home rollback (detected at startup), the
> append→anchor-update window is not protected against
> a full rollback inside that window, and research mode
> / anchor unconfigured makes no rollback claim.

### F4 — MEDIUM — design A §8 claim wording for `burned_unadopted` appears nowhere in full substance

DESIGN-FINAL R1: "Claim wording: A §8 verbatim in substance,
INCLUDING the intact-verifier-home qualifier, which R2
narrows but does not remove." What the diff actually lands
is only the first half, in two places
(`signing/pin_ceremony.py:259-272` module docstring and
`:662-668` `reanchor_pin` docstring): recovery is a new
ceremony under `burned_unadopted`, validated by the verifier
against its consumption journal, never an un-consume,
`lost_pin` never the route. Missing everywhere in the diff:

1. the verifier **cannot observe pin adoption**;
2. under the production wiring (fresh pin, complete
   history, atomic adoption) an adopted target cannot be
   recovered (envelope cannot bind to the adopted pin;
   adopted target already a ceremonied target in history);
3. outside that wiring the worst case is a redundant,
   fully journaled re-consumption of the identical
   target — never a different, forked or backwards
   movement;
4. any rollback/anchor qualifier on the journal the proof
   reads (the §8 final sentence, as narrowed by R2).

`verify_ceremony_record`'s new limit paragraph
(`signing/pin_ceremony.py:990-996`) is good and honest
(offline/MAC-only; does NOT prove a burn existed; audit
linkage spelled out) — but it is not a substitute for §8.
Without (1)–(3) a reader can upgrade "validated by the
verifier against its consumption journal" into "the
verifier proves the pin was not adopted" — the exact
over-claim §8 was written to prevent, and the class of
claim the external seats have caught twice.

Exact replacement — append to the crash-contract bullet
ending at `signing/pin_ceremony.py:272` (and mirror the
same paragraph after `signing/pin_ceremony.py:668`):

> The verifier cannot observe pin adoption; it proves
> only that the recovery's candidate and old pin exactly
> equal its consumption journal's head entry. Under the
> production wiring (fresh pin, complete history, atomic
> adoption) an adopted target cannot be recovered,
> because the recovery envelope cannot bind to the
> adopted pin and the adopted target is already a
> ceremonied target in history. Outside that wiring the
> worst case is a redundant, fully journaled
> re-consumption of the identical target — never a
> different, forked or backwards movement. The burn
> proof inherits the consumption journal's anchoring
> position: trustworthy under the per-request anchor
> verification when the consumption anchor is
> configured; research mode / anchor unconfigured makes
> no rollback claim.

### F5 — MEDIUM — deploy README carries no WS2 residual wording at all; production section understates the new requirement

Task check (c) locations: verifier_main docstrings — PASS
(consume docstring `trust/verifier_main.py:2613-2621` states
all three qualifiers near-verbatim from R2; header env block
:175-190 states production-requires-path, INIT refused, and
"research mode with the path unconfigured makes NO rollback
claim for consumptions"; `_update_ceremony_consumption_anchor`
docstring :947-953 likewise). Decision addendum — PASS
(`internal/DECISION-CONSUMPTION-HEAD.md` addendum states
anchor-completed survival, the window, and research/no-claim
in full, history preserved above it, follow-up narrowed to
the issuance journal). Deploy README — FAIL, beyond F2:

- The "Deployment mode" production bullet
  (`deploy/verifier-identity/README.md:120-130`) says the
  verifier "refuses to start when no anchor path is
  configured" (singular, signing/budgets framing) and never
  states that production + ceremony seed requires the
  consumption anchor path specifically.
- The "Co-located rollback" section (:167-196) discusses
  only the signing ledger/anchor pair; no sentence states
  the consumption residual in either direction.

Exact replacement — append to the production bullet at
`deploy/verifier-identity/README.md:130`:

> Production mode with the ceremony seed configured
> additionally requires
> `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` for the
> ceremony consumption journal. With that anchor
> configured, a consumption whose anchor update
> completed survives a verifier-home rollback (detected
> at startup); a full rollback inside the
> append→anchor-update window is not protected against;
> in research mode, or with the consumption anchor
> unconfigured, no rollback claim is made for
> consumptions.

### F6 — LOW — signing-ledger mirror docstring: "the one journal that is externally anchored in production" is stale

Evidence: `trust/ledger.py:433-438`
(`SigningLedger.append_ceremony_consumption`): "it puts the
consumption fact into the one journal that is externally
anchored in production." Since cycle 22 the consumption
journal is itself externally anchored; the signing ledger
is no longer "the one" anchored journal, and this sentence
invites the cycle-21 mirror-as-protection reading R2
replaced. The rest of the docstring (audit mirror, NOT a
second commit, invoked only after `append_consumption` has
committed) is accurate under R2's order and stays.

Exact replacement for that sentence:

> it puts the consumption fact into the signing ledger
> as an anchored audit trace (since cycle 22 the
> consumption journal carries its own external anchor,
> advanced before this mirror write).

---

## Checks that PASS (no finding)

- **(a) `lost_pin` sweep.** Every remaining use in the
  changed/new tree was read and judged legitimate — none
  describes burned-but-unmoved recovery as `lost_pin`:
  `signing/pin_ceremony.py:211-213` (recovery from a
  non-empty-history `initial_anchor` refusal is a genuine
  lost pin), `:269-272` and `:664-668` (explicit "never
  the recovery path for an unmoved pin; keeps its true
  meaning"), `:897-907` (history-nonempty ⇒ missing pin
  is `lost_pin`, not `initial_anchor` — a true-loss
  case), `signing/pin_store.py:31` (genesis via an
  `initial_anchor`/`lost_pin` record — genuine absence),
  `trust/pin_adoption.py:23` and `:616` ("never selected
  for an unmoved pin"; `_reanchor` computes
  `burned_unadopted` from the pending journal, otherwise
  the honest primary reason), and the new tests
  (`tests/test_trust_pin_adoption.py:291-322` asserts no
  `lost_pin` in history after a discarded pair;
  `tests/test_signing_ceremony_recovery.py:515-521` keeps
  `lost_pin`-with-pin records invalid). Pre-cycle-22
  internal design/history files still naming the old
  route are dated history, not current claims.
- **(d) No-forger-oracle narrowing.** Consistent everywhere
  the claim appears. `trust/verifier_main.py:2665-2680`
  (consume docstring) reproduces design B §7.2's exact
  replacement in substance: one code for all
  verification-failure classes (signature, signer, payload
  structure, binding), byte-identical output, "The
  no-oracle claim covers verification failures only",
  temporal → `ceremony_authorisation_expired` certifying
  non-temporal validity, state refusals and `ledger_failed`
  on both sides of the commit named as outside the claim.
  `trust/ledger.py:60-63` carries B's required
  `AlreadyConsumedError` sentence verbatim in substance.
  The inline comment at `trust/verifier_main.py:2725` is
  scoped ("within verification failure"). Two shorthand
  comments — `trust/verifier_main.py:2527` (authorise 5b:
  one code so as not to hand a presenter a journal-state
  oracle — a rationale for the single
  `ceremony_recovery_unproven` code, not a global claim)
  and `tests/test_trust_ceremony_consumption.py:352`
  ("both refuse with the SAME code — no oracle", in the
  different-target/wrong-old-pin forgery test) — are
  locally scoped to the single-code facts they annotate
  and do not restate the un-narrowed claim. No other
  "no forger oracle" phrasing survives in `trust/` or
  `signing/`.
- **(e) WS3 scope honesty.** `trust/pin_adoption.py:1`
  claims "first production adopter" as a code artefact and
  `:39-42` states the honest scope verbatim in substance:
  "production code exercised end-to-end in temp dirs
  against the real verifier subprocess. No live run
  against the live state dir happens here; the first live
  adoption is an `initial_anchor` ceremony gated on
  verifier provisioning." `signing/pin_store.py` makes no
  live claim. `tests/test_trust_pin_adoption.py:5-16`
  honestly discloses the R12 harness (directly built
  `VerifierClient` in research env, not
  `build_pin_adopter`/`production_client`, except the
  config-refusal case), matching `trust/pin_adoption.py:252`.
  No text in the diff or new files claims a live run
  against `state/state.json`, and no text claims
  `ledger-head-anchoring` is complete — the term does not
  appear in the diff/new files at all, and the decision
  addendum does not claim it either.
- **(f) Cycles 14–16 / external item (3).** No text in the
  diff or new files claims cycles 14–16 are un-held or
  that item (3) is closed. The decision addendum amends
  by addition only and leaves "Cycles 14–16 remain HELD"
  standing in the (historical) body; it makes no closure
  judgement. (Note, not a finding: BUILD-CYCLE-22.md /
  REVIEW-CYCLE-22.md / the cycle-22 cross-check brief do
  not exist yet in the tree, so there is no record text
  to audit for a premature PROVISIONAL/closure claim —
  the coordinator should hold those records to the same
  line when written.)
- **Crash-contract survival (R4).** "Committed before
  return; burned stays burned; never retry" survives
  verbatim in substance in `signing/pin_ceremony.py`
  (module + `reanchor_pin` docstrings) and
  `trust/verifier_main.py` consume docstring (R7 paragraph
  unchanged), now with `burned_unadopted` named as the
  recovery reason.
- **Commit-order passages.** `trust/verifier_main.py`
  consume docstring and step-(8) comment state R2's order
  exactly (journal append → consumption-anchor update →
  mirror → signing anchor) including the load-bearing
  "anchor advances BEFORE the mirror write" rationale;
  `trust/client.py`'s only change (the
  `ceremony_recovery_unproven` exit-3 listing, :471-478)
  is accurate and scoped to `burned_unadopted` only.

## Test evidence

Targeted subset run by this seat:
`python3 -m unittest tests.test_signing_ceremony_recovery
tests.test_trust_ceremony_journal_anchor
tests.test_trust_pin_adoption tests.test_signing_pin_store
tests.test_trust_ceremony_consumption` — **72 tests, OK**.
Full-suite green is the build's R4 obligation, not
re-verified here; no finding above is a test failure — all
are wording contradictions between documents in the same
diff.

## Headlines

- F1 HIGH: `trust/ledger.py` R10 docstring still says the consumption journal is NOT anchored and the follow-up covers both journals — the opposite of R2.
- F2 HIGH: deploy README still says a consumed target is "never re-anchorable", recovery is "ahead of the head", and "no new configuration is needed" — all false in cycle 22.
- F3 HIGH: `signing/pin_ceremony.py:291-297` still summarises the cycle-21 mirror-based R10 residual as current.
- F4 MEDIUM: design A §8's qualifier half (verifier cannot observe adoption; production-wiring bound; redundant-identical-target worst case) appears nowhere in the diff.
- F5 MEDIUM: deploy README carries no WS2 residual wording and never states production+seed requires the consumption anchor.
- F6 LOW: `trust/ledger.py:437` still calls the signing ledger "the one journal that is externally anchored in production".
