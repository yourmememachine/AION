# Cycle 27 — War-Room Review, seat rev-r3 (test adequacy)

Reviewer: rev-r3 (did not build this slice). Reviewed blind and
independently: the uncommitted `git diff`, `internal/cycle27-work/
design-final.md`, and `tests/test_cycle27_journal_anchors.py` (11 new
tests), plus the five updated fixtures named in the brief.

Evidence run by this seat: `python3 -m unittest
tests.test_cycle27_journal_anchors tests.test_trust_wiring
tests.test_verifier_deploy tests.test_trust_pin_adoption` — 86 tests,
OK (1 skipped); `tests.test_trust_production_deploy` — 18 tests, OK
(11 skipped). All 11 cycle-27 tests pass as shipped.

**Score: 0.80**
**Verdict: FIX** — the core rollback/burn properties are genuinely
proven (findings 3–4 record the mutation checks that pass), but two
properties the design explicitly claims have no discriminating test:
the INIT-only-on-missing discipline (finding 1) and the production
gate for the supersession anchor (finding 2). A mutation that
silently defeats rollback protection passes the whole suite today.
Both fixes are test-only additions; no production defect was found.

## Findings

1. **[FIX — sharpest gap] INIT-only-on-`anchor_missing` is never
   discriminated.** The design and the module docstring claim INIT
   "may pin only when the verification reasons are exactly
   (`anchor_missing`,)", and the production helper implements
   exactly that check. But no test exercises INIT=1 against a
   non-missing refusal reason: no INIT + rolled-back/stale anchor
   (anchor_ahead_of_journal / anchor_head_not_in_chain), no INIT +
   malformed anchor, and no INIT + missing anchor on an
   *established* journal (anchor_missing_established_ledger).
   Mutation check: widening the helper's condition from
   `reasons == ("anchor_missing",) and anchor_init` to "re-pin on
   any reasons when INIT is set" passes all 11 tests — while
   letting anyone who can set INIT bless a rolled-back journal and
   erase exactly the evidence the anchor exists to keep. The one
   missing-anchor test
   (`test_issuance_anchor_missing_on_established_journal_refused`)
   runs *without* INIT, so it cannot catch this. Add: (a) INIT=1
   with a truncated journal against a valid anchor → anchor_refused
   and anchor file unchanged; (b) INIT=1 with the anchor deleted
   from an established journal → anchor_refused.

2. **[FIX] Production gate is tested for issuance only.** Design:
   production + ceremony seed requires *both* anchor paths and
   refuses *both* INIT flags. `IssuanceProductionGateTests` varies
   only issuance (missing path; INIT=1). There is no
   production-without-supersession-anchor test and no
   production-supersession-INIT-refused test at the `_load_config`
   level. Mutation check: dropping the supersession branch's
   production requirement/INIT refusal passes all 11 cycle-27
   tests. (The wiring-level tests in `test_trust_wiring.py` do loop
   all five INIT flags and both new paths in REQUIRED_ENV_KEYS,
   but that is the client factory, not the verifier's seed-keyed
   production gate that these tests exist to pin.) Add the two
   supersession variants mirroring the issuance pair. Related
   minor gap: no negative test that production *without* the
   ceremony seed does not require the new anchors, so an
   over-broad unconditional gate would also pass.

3. **[PASS — mutation checks that hold] The two headline mutations
   are caught.** (a) If `_update_ceremony_issuance_anchor` were a
   no-op: `test_issuance_anchor_update_failure_burns_pair` fails
   (the kind-filtered patch is never invoked, the authorise
   succeeds and the signing mirror lands), and
   `test_issuance_rollback_replay_refused_at_startup` fails (the
   anchor stays at the genesis prefix, which verifies against the
   restored journal, so the replay succeeds). The same holds for
   the supersession update via
   `test_supersession_anchor_update_failure_decision_stands`.
   (b) If the loader's startup verification were removed: the
   issuance rollback-replay test, the missing-on-established test,
   and `test_supersession_journal_only_rollback_refused_at_startup`
   all fail (the replay / authorise / sealed_eval would succeed).
   The issuance failure test is the strongest in the file: it pins
   ledger_failed, envelope withheld (`assertNotIn
   signed_authorisation`), journal entry present (pair burned),
   signing mirror absent (commit order), and the burn's
   consequence on retry (ceremony_id_reused — correct, because
   verify_anchor accepts a journal ahead of its anchor as a valid
   prefix, per the stated window caveat).

4. **[PASS with a caveat] Supersession rollback is proven only at
   the level the docstring honestly declares.** The rollback test
   appends the decision through the ledger API and advances the
   anchor by calling `update_anchor` *in the test itself*; it
   proves loader startup verification, not the production commit
   wiring. There is no positive end-to-end assertion that a
   successful real supersede advances the supersession anchor
   (compare the issuance bootstrap test, which asserts the anchor's
   kind and `seq == len(entries)`). Deleting the production call
   is still caught indirectly by the failure-injection test
   (finding 3), but a wrong-journal/wrong-kind update on the
   success path has no direct test. Should-add: after a successful
   supersede, assert the supersession anchor's kind/seq/head match
   the journal, then roll back the journal file alone and assert
   startup refusal — closing the supersession headline claim
   end-to-end.

5. **[Minor] Placement/distinctness coverage is one-sided.** Only
   issuance-inside-home and issuance==consumption are tested. Not
   tested: supersession-inside-home; issuance==supersession
   aliasing (the most likely alias pair, and its detection rests
   entirely on the supersession call's `other_anchors`, since the
   issuance call runs before the supersession path is resolved —
   removing issuance from that tuple passes all 11 tests);
   relative-path refusal for either new anchor; INIT without a
   path; malformed INIT value. The shared helper lowers the risk,
   but the alias-pair test is cheap and protects the one place the
   two calls are *not* symmetric.

6. **[Minor] Asymmetries in the failure and characterisation
   tests.** (a) The supersession anchor-failure test does not
   explicitly assert the receipt is withheld (the issuance twin
   asserts the envelope's absence); code 3 + ledger_failed implies
   it, but the docstring claims it, so pin it. It also has no
   retry/consequence assertion paralleling the issuance burn test.
   (b) The research-mode characterisation exists only for issuance;
   there is no supersession no-anchor characterisation, though the
   design's no-claim residual is stated for both journals.

7. **[PASS] Updated fixtures are not weakened.** All five fixture
   diffs are additive or exact count updates matching the design:
   `test_trust_wiring.py` — allowlist 20→24 with `assertIn` for all
   four new keys and the INIT-refusal loop extended to all five
   flags (strengthened); `test_verifier_deploy.py` — count 20→24
   only; `cycle23_harness.py` — the two new anchor paths added to
   the production provisioning and the two new INIT keys added to
   the strip list (necessary, not weakening);
   `test_trust_production_deploy.py` — the two new anchors
   initialised at genesis in the production fixture, no assertion
   removed; `test_trust_pin_adoption.py` — the two new path keys
   added to an env whose refusal assertion is unchanged. One stale
   comment, not an assertion: the renamed
   `test_allowlist_is_the_shipped_24_names` still carries a comment
   block saying the shipped wrapper "has 20 names" — tidy it so the
   next reader is not misled.

## Summary for reconciliation

Must-add before SHIP: finding 1 (INIT discrimination, both
variants) and finding 2 (supersession production pair). Should-add:
finding 4 (positive supersession anchor-advance assertion),
finding 5 (issuance==supersession alias test). Everything else in
the claimed property list — issuance rollback replay refused at
startup, anchor-update failure burning the pair and withholding
the envelope, INIT bootstrap on a missing anchor/empty journal,
issuance placement/distinctness refusals, supersession rollback at
the `_load_config` level, and the research-mode characterisation —
is genuinely proven by tests that fail under the corresponding
production mutation.
