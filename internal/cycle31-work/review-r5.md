# Cycle 31 — War-room review R5 (tests evidence, blind)

Reviewer seat: R5, tests evidence only.
Scope read: `docs/RECOVERY-CONTRACT.md` and `tests/test_trust_shiptx_anchoring.py` only.
Not read: `internal/cycle31-work/` (per brief).
Evidence run: `python3 -m unittest tests.test_trust_shiptx_anchoring` — 58 tests, OK
(pytest is not installed on this VM; unittest is the runner used).

## Score: 0.82

## Verdict: FIX

The behavioural core of the contract is pinned unusually well — every
major park / error / raise / post-settlement claim I checked maps to a
named test whose assertions actually discriminate the claimed behaviour,
and all 58 tests pass. The FIX is for the contract's own framing claim:
"Every claim is pinned by a test in `tests/test_trust_shiptx_anchoring.py`
unless stated as a limit" is not true for several claims (findings 1–4).
Either pin them in this file, point those claims at the file that does
pin them, or mark them as limits / non-claims. No code defect was found
by this seat.

## Spot-checks (12 claims checked against test names / behaviour)

1. PASS — Same-file guard suppresses BOTH verifications, yields one
   operator error, never a park.
   `test_same_path_for_both_anchors_is_error_not_anomaly`,
   `test_same_file_tx_anchor_shared_is_error_not_anomaly` (the shared
   file is a valid tx anchor, so an unsuppressed ship-side check would
   kind-mismatch-park; result is a single `"same file"` error outcome,
   state stays `POST_RECORD_VERIFIED`, ledger stays `["burn"]`),
   `test_same_file_symlink_alias_is_error_not_anomaly`, and the two
   hardlink tests in `JournalIntegrityErrorTests`.

2. PASS — Byte-identical copy on a distinct inode is NOT the same file
   and still parks on kind mismatch (identity, not content).
   `test_byte_copy_distinct_inode_still_parks`: copied ship anchor
   passed as tx anchor → `ANOMALY`, `anchor_kind_mismatch`.

3. PASS — Park reasons are exactly the three named, each exercised in
   recovery (not only in `verify_anchor`):
   `anchor_head_not_in_chain` — `test_recovery_parks_on_tx_head_not_in_chain`;
   `anchor_kind_mismatch` — `test_recovery_parks_on_tx_kind_mismatch`,
   `test_ship_tx_file_passed_as_ship_anchor_parks`;
   `anchor_ahead_of_journal` — `test_truncated_journal_with_live_tx_parks_ahead_of_journal`,
   `test_deleted_tx_journal_raises_instead_of_empty_recovery`.

4. PASS — Park-over-error combination, operator errors absorbed.
   `test_combined_park_beats_operator_error` (ship missing + tx park →
   `ANOMALY`), `test_combined_ship_park_tx_error_parks_with_source`
   (asserts no `error` key and
   `anchor_sources == ["ship: anchor_head_not_in_chain"]`).

5. PASS — Operator-error-only leaves transactions unmoved, per-tx
   `error` outcomes, no extra ledger write.
   `test_missing_tx_anchor_is_error_and_retry_succeeds` (state unchanged,
   then retry commits and ledger gains only `finalise`),
   `test_malformed_tx_anchor_is_error_not_anomaly`,
   `test_inside_dir_tx_anchor_is_error_not_anomaly` (`anchor_error:` /
   `OUTSIDE`).

6. PASS — No-park-target asymmetry (pre-settlement raise #1).
   Tx park with zero non-terminal raises:
   `test_all_terminal_journal_with_forged_tx_anchor_raises`,
   `test_all_terminal_forged_anchor_raises_distinct_type`.
   Ship-only park with nothing to park returns `[]`:
   `test_ship_anchor_only_park_with_nothing_to_park_no_raise`.

7. PASS — `recover()` is not type-idempotent: same evidence parks on
   run 1 and raises on run 2.
   Second-run raise inside `test_recovery_parks_on_tx_head_not_in_chain`
   (generic `AnchorError`) and pinned as the distinct type by
   `test_second_run_after_park_raises_distinct_type`.

8. PASS — `JournalIntegrityError` constructor validation and derived
   `anchor_source`.
   `test_constructor_contract` (deduped reasons, single prefix →
   `"ship-tx"`, two prefixes → `"combined"`, empty refused) and
   `test_constructor_validation_fix_round` (operator reason
   `anchor_malformed` refused with `ValueError`, empty sources refused,
   reason-without-matching-source refused, bare-string reasons refused,
   duplicate sources deduped, pickle/deepcopy round-trip preserves
   type / reasons / sources / outcomes).

9. PASS — Post-settlement re-verification: only NEW reasons count.
   `test_post_settlement_no_new_reason_does_not_raise` (constant park
   reason → parks, no raise),
   `test_post_settlement_park_reason_raises_distinct_type` (settlement
   stands, `COMMITTED` outcomes ride on `exc.outcomes`),
   `test_post_settlement_mixed_park_and_anchor_error` (load failure
   lands in `exc.anchor_errors`, not `exc.reasons`),
   `test_post_settlement_anchor_error_only_stays_plain` (plain
   `AnchorError`, explicitly not `JournalIntegrityError`, outcomes
   carried, settlement stands),
   `test_post_settlement_combined_sources` (`anchor_source == "combined"`).

10. PASS — Recovery never advances the tx anchor.
    `test_recovery_never_advances_tx_anchor_then_caller_does`:
    anchor bytes byte-identical after a committing recovery, then
    `update_anchor` (the caller) does advance it.

11. PASS — Combined / labelled-reasons behaviour.
    `test_combined_both_operator_errors_labelled` (both
    `ship:` and `ship-tx:` labels in one error string),
    `test_pre_settlement_combined_anchors_carry_both_sources`
    (`combined`, both sources, ship reasons ride along in the message).

12. PASS — Nonempty ceremony limit.
    `test_initialise_nonempty_refused_by_default` and
    `test_nonempty_ceremony_flag_pins_current_head`
    (`allow_nonempty_ceremony=True` pins current head/seq) match the
    contract's ceremony paragraph.

## Findings

1. FIX — The pinning preamble overclaims for the "Anchor advancement"
   section. The write-half claims about `anchored_record_ship`
   (requires both anchors, verifies AND requires currency, advances
   the tx anchor after COMMITTED, no non-test caller yet) are pinned
   by no test in this file — no test here references that entry point.
   Likewise "no non-test caller passes `tx_anchor_path` to recover"
   is a tree-wide grep claim, not pinnable by this file. Reword the
   preamble, cite the cycle-23 test file for the write half, or mark
   these as non-test-pinned statements.

2. FIX — "Recovery NEVER advances either anchor (pinned byte-identical
   in tests)" is pinned only for the tx anchor (spot-check 10). No
   test in this file asserts the ship anchor file is byte-identical
   after a combined-anchor recovery. Narrow the claim to the tx
   anchor, or add a combined-recovery byte-identity assertion for the
   ship anchor.

3. FIX — Two entry-point claims have no pin in this file:
   (a) "Terminal transactions are skipped, so a re-run over settled
   transactions returns `[]`" — the only `[]` assertion here is the
   ship-only-park case (spot-check 6); there is no clean re-run with
   a valid anchor over settled transactions asserting `[]`.
   (b) "Reasons are labelled by anchor only when the tx anchor
   participates; ship-only callers keep their pre-cycle-17 bare
   strings" — the ship-only park test
   (`test_ship_tx_file_passed_as_ship_anchor_parks`) asserts only
   `reasons`, never the form of `anchor_sources`. Pin both, or mark
   them as pinned elsewhere / as limits.

4. FIX (minor) — The `__reduce__` claim says round-trip goes "through
   a restoring constructor that re-validates on load". The pickle
   test in `test_constructor_validation_fix_round` round-trips only a
   valid instance with `outcomes` set; it does not show re-validation
   on load, and — as the contract itself honestly discloses — no test
   round-trips a non-empty `anchor_errors`. The disclosure is
   consistent, but the `__reduce__` sentence should carry the same
   "known gap" qualification in place, not only rely on the reader
   joining the two paragraphs.

5. NOTE (not blocking alone) — "Recovery never burns, never re-runs a
   cycle, and never journals AUTHORISATION_VERIFIED; its only ledger
   write is a completing finalise" is only indirectly pinned:
   `ledger_kinds()` assertions (`["burn"]` on park/error,
   `["burn", "finalise"]` on proceed) pin the ledger side well, but
   no test in this file asserts the journal side (no
   `AUTHORISATION_VERIFIED` entry journalled by recovery). Acceptable
   if finding 1's rewording scopes the preamble accordingly.

6. NOTE — Handler-order rule ("catch `JournalIntegrityError` BEFORE
   `AnchorError`") and the mutable-attributes / unvalidated
   `outcomes`/`anchor_errors` gaps are stated as known gaps in the
   contract and are consistent with what the tests show
   (`test_anchor_primitives_stay_plain_anchor_error` and the distinct-
   type tests pin the subclass relationship that makes the rule
   necessary). No action beyond keeping the disclosure.
