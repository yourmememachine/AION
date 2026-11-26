# Cycle 31 — Design B: Error-surface trace (seat B)

Scope: `JournalIntegrityError` and every error surface in
ship-tx recovery (`ShipTxJournal.recover`). Sources traced:
`trust/anchoring.py`, `trust/shiptx.py`,
`tests/test_trust_shiptx_anchoring.py`,
`internal/BUILD-CYCLE-17.md`, `internal/BUILD-CYCLE-18.md`.
No code was changed for this note; it is a trace for the
cycle-31 design decision.

## 0. Map of the surfaces

Recovery has exactly four ways to report an anchor problem,
and which one fires depends on (a) failure kind, (b) whether
a non-terminal transaction exists to carry it, and (c) when
in the run the failure is observed:

| Surface | When | Carrier |
|---|---|---|
| Park outcome | Pre-settlement chain-mismatch, ≥1 non-terminal tx | outcome dict `to_state=ANOMALY`, `reasons`, `anchor_sources` (`trust/shiptx.py:1079` via `_recover_one`, gated by `anchor_reasons` set at `trust/shiptx.py:904-905`) |
| Per-tx error outcome | Pre-settlement operator error only, ≥1 non-terminal tx | outcome dict `error=…`, tx unmoved (`trust/shiptx.py:911-922`) |
| `JournalIntegrityError` raise | Pre-settlement tx chain-mismatch with NO non-terminal tx; or post-settlement NEW chain-mismatch | exception, §1–§4 below |
| Plain `AnchorError` raise | Post-settlement NEW anchor-load failure only (no new park reason) | exception with ad-hoc `.outcomes` (`trust/shiptx.py:1047-1053`) |

Plus the silent fifth surface — return `[]` — in §7.

Classification constants, duplicated by design and required
to stay equal: `JOURNAL_INTEGRITY_REASONS`
(`trust/anchoring.py:145-147`) ≡ `ANCHOR_PARK_REASONS`
(`trust/shiptx.py:341-343`) =
`{anchor_head_not_in_chain, anchor_ahead_of_journal,
anchor_kind_mismatch}`. Everything else from `verify_anchor`
— `anchor_missing`, `anchor_missing_established_ledger`,
`anchor_malformed` (`ANCHOR_ERROR_REASONS`,
`trust/shiptx.py:344-346`; producers at
`trust/anchoring.py:729-739`) — plus any wrapped
`anchor_error:<exc>` string, is operator error
(`trust/shiptx.py:335-340`, wrapping at
`trust/shiptx.py:813-838`).

## 1. `JournalIntegrityError` constructor validation

Definition: `class JournalIntegrityError(AnchorError)`
(`trust/anchoring.py:159`); base `AnchorError(Exception)` at
`trust/anchoring.py:134`. Signature is keyword-only after
the message: `__init__(self, message, *, reasons,
anchor_sources, outcomes=(), anchor_errors=())`
(`trust/anchoring.py:194-195`). All validation failures are
`ValueError`, never `AnchorError` — a mis-constructed raise
is a programming error, not an anchor refusal. In order:

1. **Bare-string guard (all four structured args).** If
   `reasons`, `anchor_sources`, `outcomes` or
   `anchor_errors` is `str`/`bytes`, `ValueError`
   (`trust/anchoring.py:196-203`). Without it a bare reason
   string would iterate character-by-character into nonsense
   that might accidentally pass the set checks. Pinned by
   `test_constructor_validation_fix_round`
   (`tests/test_trust_shiptx_anchoring.py:822`).
2. **Reasons deduped, order-preserving, non-empty.**
   `tuple(dict.fromkeys(reasons))` (`trust/anchoring.py:204`);
   empty → `ValueError`, with the rationale stated in the
   message: an empty-reasons raise "would recreate the
   silent-clean-recovery problem in typed form"
   (`trust/anchoring.py:205-210`). Also pinned by
   `test_constructor_contract` (empty reasons refused,
   duplicates collapsed to one;
   `tests/test_trust_shiptx_anchoring.py:697`).
3. **Reasons canonical-only.** Every element must be a
   `str` and `set(reasons) <= JOURNAL_INTEGRITY_REASONS`,
   else `ValueError` (`trust/anchoring.py:211-218`). This is
   the load-bearing invariant of the whole type: an operator
   reason such as `anchor_malformed` can never mint it
   (pinned: `tests/test_trust_shiptx_anchoring.py:822`,
   first case). Note what is NOT checked: elements of
   `outcomes`/`anchor_errors` get no content validation at
   all beyond the bare-string guard in step 1 — any sequence
   of arbitrary objects is accepted and merely tupled
   (`trust/anchoring.py:252-253`). The contract is strict
   exactly where the type's distinction lives (reasons /
   sources) and permissive on the two passenger fields.
4. **Sources deduped, non-empty.** Same dedupe
   (`trust/anchoring.py:219`); empty → `ValueError` —
   "a raise with no source fabricates provenance"
   (`trust/anchoring.py:220-224`).
5. **Each source well-formed and from the closed set.**
   Must be a `str` containing `": "`, split on the first
   `": "`; the prefix must be in
   `_ANCHOR_SOURCE_NAMES = ("ship", "ship-tx")`
   (`trust/anchoring.py:148`, check at
   `trust/anchoring.py:226-238`). No third anchor can be
   named until that tuple grows.
6. **Suffix↔reason correspondence** — see §2.
7. Only after all checks: `super().__init__(message)`,
   attributes assigned (`trust/anchoring.py:245-253`).
   `message` itself is never validated (any object
   `Exception` accepts); both raise sites pass a plain
   `str` built from the bare reasons
   (`trust/shiptx.py:889-899` pre-settlement,
   `trust/shiptx.py:1023-1027` post-settlement), and the
   class docstring records that these strings are
   byte-unchanged from the pre-cycle-18 `AnchorError`
   messages (`trust/anchoring.py:182-184`) — existing
   substring tests survive the retype (BUILD-CYCLE-18,
   Pod B contract).

Gap worth naming for cycle 31: validation is construction-
time only. The attributes are plain public attributes
(`self.reasons = …` etc.); nothing prevents a caller from
mutating `exc.reasons` afterwards into a non-canonical
value. The type is a contract at the raise site, not an
immutable value object.

## 2. `reasons` / `anchor_sources` correspondence

The correspondence is **set equality of suffixes**, not a
positional or one-to-one pairing
(`trust/anchoring.py:239-244`):

```python
if suffixes != set(reasons): raise ValueError(...)
```

where `suffixes` is the set of post-`": "` parts of
`anchor_sources` (`trust/anchoring.py:225,233-238`).
Consequences, all deliberate:

- **Every reason must be named by ≥1 source, and every
  source suffix must be a declared reason.** A reason with
  no matching labelled source is refused (pinned:
  `tests/test_trust_shiptx_anchoring.py:822`, third case —
  two reasons, one source).
- **Cardinality may differ.** One reason may be carried by
  both sources: `reasons=("anchor_head_not_in_chain",)`,
  `anchor_sources=("ship: …", "ship-tx: …")` is valid and
  is exactly the combined pre-settlement shape
  (`trust/shiptx.py:884-903`; pinned by
  `test_pre_settlement_combined_anchors_carry_both_sources`,
  `tests/test_trust_shiptx_anchoring.py:862`, and by
  `test_constructor_contract`'s combined instance).
- **Derived `anchor_source`.** Distinct source prefixes,
  deduped in order: the single prefix if exactly one,
  else the literal `"combined"`
  (`trust/anchoring.py:248-251`). It is derived, never
  passed in, so it cannot disagree with `anchor_sources`.
- **Ordering.** `reasons` keeps first-seen order of the
  caller's sequence; `anchor_sources` keeps its own
  first-seen order. The two orders are independent — the
  pre-settlement site builds `all_reasons` tx-first then
  ship (`trust/shiptx.py:884-887`) but `all_sources`
  ship-first then tx (`trust/shiptx.py:888-890`), so a
  combined raise can have `reasons[0]` from the tx anchor
  while `anchor_sources[0]` is the ship label. Any consumer
  zipping the two tuples positionally would mis-attribute;
  the suffix is the join key, by design.

## 3. `anchor_errors` / `outcomes` carriage

Both default to `()` and are stored as tuples
(`trust/anchoring.py:252-253`). Their semantics differ per
raise site — this asymmetry is the subtlest part of the
surface:

- **Pre-settlement raise** (`trust/shiptx.py:899-903`):
  passes only `reasons` + `anchor_sources`. `outcomes`
  and `anchor_errors` are therefore `()` — correctly:
  no settlement has run yet, so there is nothing to carry,
  and any simultaneous operator-error reasons are simply
  dropped (park-over-error already decided the run; the
  operator errors were not needed to refuse). But note:
  simultaneous **ship park** reasons are NOT dropped —
  the cycle-18 fix round folds them into
  `reasons`/`anchor_sources` and appends
  `"; ship anchor also failed …"` to the message
  (`trust/shiptx.py:876-903`), precisely so evidence
  supplied to the call does not vanish because a different
  piece of evidence triggered the raise (BUILD-CYCLE-18,
  process lesson 3).
- **Post-settlement raise** (`trust/shiptx.py:1039-1046`):
  passes all four. `outcomes=outcomes` — the settlement
  list the raise discards as a return value; those
  settlements stand as journaled evidence, so the list
  rides on the exception or it would be lost.
  `anchor_errors=[label for label, r in new_park if r is
  None]` — the labelled NEW anchor-load failures
  (`"ship: anchor_error:…"` form) that accompanied the new
  park evidence. They are **never in `reasons`**: the
  mixed-case test pins `reasons == ("anchor_head_not_…",)`,
  `anchor_sources == ("ship-tx: …",)`,
  `anchor_errors == ("ship: anchor_error:anchor_malformed",)`
  and the error text present in `str(exc)`
  (`test_post_settlement_mixed_park_and_anchor_error`,
  `tests/test_trust_shiptx_anchoring.py:921`).
- **No other producer sets either field.** In particular
  the pre-settlement raise is the only raise a caller sees
  for the deleted-journal case, and it carries no
  `outcomes` — a caller that unconditionally reads
  `exc.outcomes` gets `()`, which is true (nothing settled)
  but indistinguishable from "post-settlement raise whose
  run settled nothing". The site is distinguishable only
  via the message prefix (`"ship-tx anchor verification
  failed …"` vs `"anchor verification changed during
  recovery …"`).

## 4. Handler-order rule

Stated once, in the class docstring
(`trust/anchoring.py:186-190` approx.; docstring at
`trust/anchoring.py:160-192`): because
`JournalIntegrityError` **is** an `AnchorError`, a caller
wanting the distinction must catch it **before**
`AnchorError`; a generic `except AnchorError` first makes
the specific handler unreachable and "silently re-creates
the conflation" the type exists to remove.

Corollaries visible in the tree:

- Back-compat is by construction: every pre-cycle-18
  `except AnchorError` / `assertRaises(AnchorError)` still
  catches the new raises. Cycle-17 tests asserting plain
  `AnchorError` for the deleted-journal and second-run
  cases (`tests/test_trust_shiptx_anchoring.py:488,515`
  area, `RecoveryParkTests`) still pass against the
  subclass; cycle-18 tests then pin the **exact** type
  with `assertIs(type(exc), JournalIntegrityError)`
  (`tests/test_trust_shiptx_anchoring.py:632,686`).
- The wrapper `recover_ship_tx` propagates the type
  unwrapped (`test_wrapper_propagates_distinct_type_unwrapped`,
  `tests/test_trust_shiptx_anchoring.py:686`) — no layer
  between `recover()` and the caller re-wraps it into a
  plain `AnchorError`.
- Internal consumers that must NOT see it conflated use
  exact-type or `NotIsInstance` checks; the anchor
  primitives test does the inverse pin (§6).

## 5. Pickle / deepcopy

The constructor is keyword-only for the structured fields,
so default exception pickling (replay from `args`, which
holds only the message) would lose or fail to restore the
state. The class therefore defines `__reduce__`
(`trust/anchoring.py:255-261`) returning the module-level
helper `_restore_journal_integrity_error`
(`trust/anchoring.py:151-156`) plus the full state tuple
`(str(self), reasons, anchor_sources, outcomes,
anchor_errors)`. The helper re-invokes the validating
constructor positionally-by-keyword, so a round-trip
**re-validates**: a hand-crafted pickle payload with
non-canonical reasons fails with `ValueError` at load,
it does not smuggle an invalid instance in.

- `anchor_source` is not in the payload — it is re-derived
  in `__init__` (`trust/anchoring.py:248-251`), so it
  cannot desync across a round-trip.
- `copy.deepcopy` goes through the same reduce path.
- Pinned by `test_constructor_validation_fix_round`:
  both `pickle.loads(pickle.dumps(exc))` and
  `copy.deepcopy(exc)` preserve exact type, `reasons`,
  `anchor_sources` and `outcomes`
  (`tests/test_trust_shiptx_anchoring.py:822`, tail).
  Note the pin does not assert `anchor_errors` round-trip
  on an instance that has any — the field rides in the
  payload (`trust/anchoring.py:261`) but no test loads a
  mixed-case exception through pickle. Small coverage gap,
  worth a line in the cycle-31 test plan.

## 6. Plain `AnchorError` branches (what deliberately did NOT become the subtype)

1. **All anchor primitives.** `initialise_anchor`,
   `update_anchor`, `force_reanchor`, `_read_anchor`,
   `_validate_anchor`, audit-chain validation etc. raise
   plain `AnchorError` only (e.g. `anchor_malformed` raises
   throughout `trust/anchoring.py` validation/loader code).
   Pinned exactly: `test_anchor_primitives_stay_plain_anchor_error`
   asserts `type(exc) is AnchorError` and
   `NotIsInstance(…, JournalIntegrityError)` on a double-init
   refusal (`tests/test_trust_shiptx_anchoring.py:715`).
2. **Post-settlement error-only change**
   (`trust/shiptx.py:1047-1053`): if re-verification surfaces
   only NEW `anchor_error:` failures and no new park reason,
   recovery raises a plain `AnchorError` — but the cycle-18
   fix round attaches the completed settlements as an
   ad-hoc attribute: `plain.outcomes = tuple(outcomes)`
   before raising. Asymmetry vs §3: this `.outcomes` is NOT
   a constructor field of `AnchorError` (the base class
   defines no such attribute), so (a) it exists only on
   this one raise object, (b) it does not survive pickle
   of that exception, and (c) there is no `.anchor_errors`
   attribute on it at all — a caller doing
   `getattr(exc, "anchor_errors", ())` is fine, direct
   attribute access raises `AttributeError`. Pinned by
   `test_post_settlement_anchor_error_only_stays_plain`:
   exact type `AnchorError`, not the subtype, settlement
   still `COMMITTED`, `ctx.exception.outcomes` readable
   (`tests/test_trust_shiptx_anchoring.py:970`).
3. **Per-transaction surfaces never raise at all** for
   anchor problems: operator errors become `error` outcome
   dicts (§0), park reasons become `ANOMALY` outcomes.
   The exception surfaces exist only where no outcome dict
   can carry the evidence — that is the type's stated
   raison d'être (`trust/anchoring.py:160-171`).
4. **Identical-repeat suppression (both re-verify
   branches).** A post-settlement exception whose
   `anchor_error:<exc>` string was already in the initial
   `ship_reasons`/`tx_reasons` is not a change and produces
   no raise (`trust/shiptx.py:1004-1010,1018-1021`); a
   repeated park reason already in the initial park set
   likewise produces no raise — pinned by
   `test_post_settlement_no_new_reason_does_not_raise`,
   where a constant forged verdict parks on run semantics
   and returns outcomes normally
   (`tests/test_trust_shiptx_anchoring.py:955`).

## 7. Silent-`[]` holes

`recover()` returns a list; `[]` is also its genuine
"nothing was non-terminal" answer, so any evidence that
arrives when there is no non-terminal transaction AND no
tx park reason is indistinguishable from a clean run.
Named in BUILD-CYCLE-18 "Honest scope" as follow-on (a),
explicitly NOT built: "operator-error / same-file evidence
with no transaction to carry it returns [] (a chosen
non-[] surface is a design decision for its own cycle)".

Enumerated holes, by mechanism:

- **H1 — operator-error, no carrier.** `anchor_error_reasons`
  is only materialised inside the per-tx loop
  (`trust/shiptx.py:911-922`). With zero non-terminal
  transactions the loop body never runs; a missing /
  malformed / misplaced anchor on an all-terminal or empty
  journal returns `[]`. No raise site consults
  `anchor_error_reasons`.
- **H2 — same-file, no carrier.** The same-file diagnosis
  appends its explanatory string to `anchor_error_reasons`
  (`trust/shiptx.py:850-858`) and suppresses both
  verifications and the entire post-settlement re-check
  (`trust/shiptx.py:979` guard `not same_path_error`).
  With no non-terminal tx, a real wiring mistake returns
  `[]` — the operator is never told the two paths alias.
- **H3 — ship park, no carrier** — the deliberate one,
  §8: pinned as intended behaviour by
  `test_ship_anchor_only_park_with_nothing_to_park_no_raise`
  (outcomes `== []`, tx stays `COMMITTED`;
  `tests/test_trust_shiptx_anchoring.py:723`). It is a
  hole by the same shape as H1/H2 but with a stated
  principle behind it; any cycle-31 fix for H1/H2 must
  decide whether it also reopens H3 or preserves the
  asymmetry explicitly.
- **Not holes:** tx park with no carrier (raises, §8);
  post-settlement changes (raise, §3/§6.2) — but note the
  post-settlement re-check only runs when at least one
  anchor path was passed and the call was not same-file
  (`trust/shiptx.py:979-980`); with no anchor paths there
  is nothing to re-check, correctly.

## 8. State-dependence (park run 1 vs raise run 2) and ship/tx asymmetry

### 8.1 The same evidence, two surfaces, decided by journal state

The pre-settlement raise fires on exactly one condition:
`tx_park_reasons` non-empty AND no summary in
`self.transactions()` is non-terminal
(`trust/shiptx.py:859-863` approx., condition at the head
of the raise block). Therefore, for a fixed forged /
mismatched tx anchor:

- **Run 1 (a live tx exists):** no raise. The park reasons
  become `anchor_reasons` (`trust/shiptx.py:904-905`) and
  each non-terminal tx is parked at `ANOMALY` by
  `_recover_one`, outcome carrying `reasons` +
  `anchor_sources`. Run 1 returns a normal list.
- **Run 2 (the park made everything terminal):** the same
  verification now satisfies the raise condition, and
  recovery raises `JournalIntegrityError`. The evidence
  did not change; the journal state did. Pinned twice:
  cycle-17 form (`assertRaises(AnchorError)` on the second
  run, `test_recovery_parks_on_tx_head_not_in_chain`,
  `tests/test_trust_shiptx_anchoring.py:236` area) and
  cycle-18 exact-type form
  (`test_second_run_after_park_raises_distinct_type`,
  `tests/test_trust_shiptx_anchoring.py:669`).
- Same shape without any park: an all-terminal journal
  whose tx anchor is forged raises on the first such call
  (`test_all_terminal_forged_anchor_raises_distinct_type`,
  `tests/test_trust_shiptx_anchoring.py:650`), and a
  deleted journal file — which loads as empty, hence zero
  transactions at all — raises with
  `reasons == ("anchor_ahead_of_journal",)`
  (`test_deleted_journal_raises_distinct_type_with_reasons`,
  `tests/test_trust_shiptx_anchoring.py:632`). The deleted
  case is the original cycle-17 blind spot: the pinned
  object is this journal itself, so its absence leaves
  literally nothing to park (BUILD-CYCLE-17, Pod C flag;
  widened in the fix round from "no transactions" to
  "no non-terminal transaction" to also cover rollback to
  a terminal-only prefix, BUILD-CYCLE-17 §What was built.3).

Practical consequence for callers: `recover()` is NOT
idempotent at the type level. "Call it until it returns
[]" is a broken driver pattern — the second call over a
just-parked journal raises. A correct driver treats the
raise as the terminal signal for the same evidence it
previously received as park outcomes.

### 8.2 Ship/tx asymmetry

- **Trigger asymmetry.** Only **tx** park reasons can fire
  the pre-settlement raise; ship park reasons alone, with
  nothing to park, return `[]` (H3, §7). The stated
  principle, in the code comment at the raise site
  (`trust/shiptx.py:871-877` approx.): the tx anchor pins
  **this journal's own file** — its rollback is evidence
  about the very object recovery is settling, with nowhere
  else for the evidence to land — whereas the ship anchor
  pins a **different file** (the ship ledger); an
  empty/terminal-only tx journal means no transaction is
  at risk from the ship ledger's anchor, and that anchor
  "is verified by the ledger's own consumers".
- **Carriage symmetry (partial).** Once the tx trigger
  fires, ship park reasons present in the same call ride
  on the raise (§3) — the asymmetry is in what can
  **trigger**, not in what can be **reported**. The
  message keeps the trigger legible: primary clause names
  the tx reasons; ship reasons appear only in the
  appended `"; ship anchor also failed …"` clause
  (`trust/shiptx.py:889-899`).
- **Post-settlement symmetry.** The re-verification treats
  both anchors identically: a NEW park reason from either
  contributes a `park_pair`, and the resulting
  `JournalIntegrityError` can be ship-only, tx-only or
  `"combined"` (`trust/shiptx.py:996-1046`; pinned by
  `test_post_settlement_combined_sources`,
  `tests/test_trust_shiptx_anchoring.py:890`). So the
  asymmetry is confined to the pre-settlement, no-carrier
  case — mid-run, both journals are equally "the object
  being settled on".
- **Labelling asymmetry (pre-cycle-17 compat).** When only
  the ship anchor participates, per-tx error/park strings
  keep their bare pre-cycle-17 form; labels are added only
  when `tx_anchor_path is not None`
  (`trust/shiptx.py:839-849`, `_label`). The raises have
  no such compat mode: both raise sites always build
  fully labelled `anchor_sources` (the post-settlement
  site unconditionally prefixes `ship:`/`ship-tx:`,
  `trust/shiptx.py:1003,1017`), because the constructor
  (§1.5) refuses unlabelled sources. A ship-only caller
  therefore sees bare strings in outcomes but labelled
  sources on a post-settlement raise from the same call —
  a small, forced inconsistency cycle 31 should note
  before touching either form.

## 9. Lineage (cycles 17 → 18)

- Cycle 17 built the tx anchor, the park-over-error
  combination, the same-file suppression, the no-carrier
  raise (then plain `AnchorError`) and post-settlement
  re-verification (BUILD-CYCLE-17 §What was built.2–3).
  Its external seats split on the raise: journal-level
  raise correct, generic type a conflation.
- Cycle 18 is the reconciliation of that split: the
  distinct subtype, constructor validation, hardlink pins
  for the same-file guard, ship-reasons ride-along on the
  pre-settlement raise, and `.anchor_errors` /
  `.outcomes` carriage on both post-settlement branches
  (BUILD-CYCLE-18 §What was built.1–3). It explicitly
  preserves — now typed and labelled — both the
  state-dependence of §8.1 and the asymmetry of §8.2
  (BUILD-CYCLE-18 "Honest scope"), and explicitly defers
  the §7 silent-`[]` holes as follow-on (a). Those two
  deferrals, plus the §5 pickle coverage gap for
  `anchor_errors`, are the open error-surface items this
  trace hands to cycle 31.
