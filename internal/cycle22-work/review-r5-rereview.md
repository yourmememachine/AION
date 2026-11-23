# Cycle 22 — war-room RE-REVIEW, seat rev-r5 (claims & wording honesty)

Date: 2026-11-23. Scope: the current tree after the fix round,
re-examined against this seat's first review
(`internal/cycle22-work/review-r5.md`, verdict FIX 0.78, all
wording: F1–F6). Blind re-review: no other seat's re-review
was read (directory listing only, to confirm this file's own
path). No production code, tests, or docs were edited by this
seat; `state/calibration` untouched.

## Verdict: SHIP — 0.96

Every one of F1–F6 is fixed in substance, in most places
near-verbatim to the replacement wording this seat prescribed.
The tree-wide grep for the old claims returns no survivor in
any current-claim surface. The two new passages this seat was
asked to check fresh — the one-shot recovery docstrings in
`trust/ledger.py` (`match_head_burn` / `check_head`) and the
`signing/pin_store.py` genesis shape-rule wording — are
accurate against the code they describe. Targeted tests pass
(see below). No replacement wording is outstanding: there is
nothing still wrong for this seat to prescribe text for.

---

## Verification of F1–F6

### F1 — FIXED — `CeremonyConsumptionLedger` R10 docstring rewritten

`trust/ledger.py:717-733` now carries the prescribed cycle-22
R2 paragraph in substance, essentially verbatim: the journal
"IS externally anchored in its own right (anchor kind
"ceremony-consumption", verified by the verifier at startup
on every invocation when configured; required in production
when the ceremony seed is configured)"; anchor-completed
burns survive a verifier-home rollback "(detected at
startup, anchor_refused)"; the append→anchor-update window
"is protected against an intact home but NOT against a full
rollback inside that window — the same window every anchored
append in this system carries"; "research mode / anchor
unconfigured: no rollback claim, and this journal can be
deleted or rolled back undetectably"; and "The follow-up
ceremony-journal-anchoring is narrowed to the issuance
journal only." The old "NOT externally anchored" / "covers
both journals" text is gone from this class.

### F2 — FIXED — deploy README burned-recovery + configuration passages

`deploy/verifier-identity/README.md:271-301` ("Ceremony
consumption (cycle 21)" section) now states, in substance
verbatim from the prescribed replacement: "Cycle 22 adds one
new configuration pair for the mode: the consumption journal
is externally anchored via
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` /
`AION_CEREMONY_CONSUMPTION_ANCHOR_INIT` (allowlist 17 → 19);
production mode with the ceremony seed configured requires
the path and refuses the INIT flag", followed by the full
residual (anchor-completed survival / startup detection;
window NOT protected against a full rollback inside it;
research/unconfigured = no rollback claim). The
"Burned-but-unmoved recovery" paragraph now reads: the burned
authorisation "is permanently spent and is never
re-consumed; recovery is a NEW ceremony (new `ceremony_id`,
new evidence bundle) under reason `burned_unadopted`, whose
candidate is the consumed head target itself (not ahead of
it) and whose old pin exactly equals the head entry's
recorded old pin, proven by the verifier against its
consumption journal at authorise and again at consume. There
is no un-consume, and the client never retries a consume
automatically." Neither "no new configuration is needed" nor
"never re-anchorable" nor "ahead of the consumption head"
survives anywhere in `deploy/`, `trust/`, or `signing/`.

### F3 — FIXED — `signing/pin_ceremony.py` residual summary

`signing/pin_ceremony.py:301-314` now carries the prescribed
replacement in substance: the section is explicitly headed as
the ISSUANCE journal's residual (so the two journals are no
longer conflated), and the consumption paragraph states
"since cycle 22 the consumption journal is externally
anchored in its own right; with the consumption anchor
configured, a burn whose anchor update completed survives a
verifier-home rollback (detected at startup), the
append→anchor-update window is not protected against a full
rollback inside that window, and research mode / anchor
unconfigured makes no rollback claim." The cycle-21
mirror-based R10 summary is gone, and the pointer to
`CeremonyConsumptionLedger`'s docstring now lands on the
rewritten F1 text, so it no longer compounds an error.

### F4 — FIXED — design-A §8 claim wording now present in full, in both places

The §8 paragraph appears in substance in BOTH locations this
seat prescribed:

- Module docstring, `signing/pin_ceremony.py:273-288` (end of
  the crash-contract bullet): "The verifier cannot observe
  pin adoption; it proves only that the recovery's candidate
  and old pin exactly equal its consumption journal's head
  entry. Under the production wiring (fresh pin, complete
  history, atomic adoption) an adopted target cannot be
  recovered, because the recovery envelope cannot bind to
  the adopted pin and the adopted target is already a
  ceremonied target in history. Outside that wiring the
  worst case is a redundant, fully journaled re-consumption
  of the identical target — never a different, forked or
  backwards movement. The burn proof inherits the
  consumption journal's anchoring position: trustworthy
  under the per-request anchor verification when the
  consumption anchor is configured; research mode / anchor
  unconfigured makes no rollback claim."
- `reanchor_pin` docstring, `signing/pin_ceremony.py:686-701`:
  the same paragraph, mirrored as prescribed.

All four previously missing elements are present: (1)
cannot-observe-adoption, (2) the production-wiring bound with
both of its mechanisms, (3) the redundant-identical-target
worst case outside that wiring, and (4) the anchoring
qualifier on the burn proof, in its R2-narrowed per-request
form. The over-claim §8 was written to prevent ("the verifier
proves the pin was not adopted") is now expressly excluded by
the text itself.

### F5 — FIXED — deploy README WS2 residual + production+seed requirement

Both halves landed:

- Production bullet, `deploy/verifier-identity/README.md:132-141`:
  "Production mode with the ceremony seed configured
  additionally requires
  `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH` for the ceremony
  consumption journal. With that anchor configured, a
  consumption whose anchor update completed survives a
  verifier-home rollback (detected at startup); a full
  rollback inside the append→anchor-update window is not
  protected against; in research mode, or with the
  consumption anchor unconfigured, no rollback claim is made
  for consumptions." — the prescribed replacement in
  substance, verbatim in most clauses. The same bullet's
  INIT-refusal list at :124-126 now also names
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`.
- The consumption section (see F2 above) independently
  restates the full WS2 residual, so the README no longer
  depends on a single passage for the claim.

Note (not a finding): the "Co-located rollback" section
(:167-196) still discusses only the signing ledger/anchor
pair, but it makes no claim about consumptions in either
direction, and the consumption residual is now stated twice
elsewhere in the same document — the F5 defect (no WS2
wording at all + understated production requirement) is
closed.

### F6 — FIXED — signing-ledger mirror docstring

`trust/ledger.py:437-441` (`SigningLedger.append_ceremony_consumption`)
now reads: "it puts the consumption fact into the signing
ledger as an anchored audit trace (since cycle 22 the
consumption journal carries its own external anchor,
advanced before this mirror write)" — the prescribed
replacement in substance, including the commit-order clause
(anchor before mirror) that ties it to R2's order. "The one
journal that is externally anchored" survives nowhere in the
tree.

---

## Grep sweep for the old claims — survivors judged in context

Command: recursive grep over the tree for `no new
configuration`, `never re-anchorable`, `NOT externally
anchored`, `one journal that is externally anchored`,
`covers both journals` (plus `ahead of the consumption head`
as an F2 companion). Survivors, all judged legitimate:

- `internal/cycle22-work/review-*.md`, `internal/cycle21-work/*`,
  `internal/REVIEW-CYCLE-2.md`,
  `internal/CROSS-CHECK-BRIEF-CYCLE-19.md`,
  `internal/DECISION-CONSUMPTION-HEAD.md:47,77` — dated review,
  design, and decision HISTORY quoting the old claims in
  order to supersede them (the DECISION addendum amends by
  addition; the historical body is not a current claim). Not
  current-claim surfaces; no change wanted.
- `trust/verifier_main.py:255-262`: "The ceremony ISSUANCE
  journal is NOT externally anchored (follow-up:
  ceremony-journal-anchoring, narrowed in cycle 22 to this
  issuance journal only — the consumption journal is
  separately anchored, see above)". This is the narrowed,
  TRUE form of the claim — the issuance journal genuinely has
  no anchor this cycle — and it expressly distinguishes the
  consumption journal. Correct, and it is the F1 narrowing
  stated from the verifier's side.
- `trust/ledger.py:612` (`CeremonyAuthorisationLedger`): "no
  external anchor covers this journal yet (follow-up:
  ceremony-journal-anchoring)" — same issuance journal, same
  true claim, with its rollback residual stated plainly
  immediately after. Correct.
- `eval/calibration.py:18` and `selfmod/canary.py:110`:
  unrelated subsystems' own "not externally anchored"
  statements about calibration/canary artefacts, untouched by
  cycle 22 and not ceremony claims. Out of this seat's F1–F6
  scope; no contradiction with anything cycle 22 ships.

No survivor in `trust/ledger.py`'s consumption class,
`signing/pin_ceremony.py`, `trust/verifier_main.py`'s
consumption passages, or the deploy README states or implies
a superseded cycle-21 claim.

## New passages checked fresh

### One-shot recovery docstrings — `trust/ledger.py` `match_head_burn` / `check_head` — ACCURATE

- `match_head_burn` (`trust/ledger.py:792-826`): "the head
  entry is returned ONLY IF no earlier journal entry carries
  the same (old_cycle_seq, old_payload_hash, new_cycle_seq,
  new_payload_hash) pair. A recovery consumption writes an
  entry indistinguishable from the original burn (same
  old->new pair; the strict entry schema carries no reason
  field), so the original burn is the FIRST consumption of
  that movement and any later identical-pair head entry is
  itself a recovery consumption — it cannot ground another
  recovery." Checked against the code directly below the
  docstring: candidate/old-pin equality with the head is
  required first, then the identical-pair scan over
  `entries[:-1]` returns None on any hit. The "any later
  identical-pair entry is itself a recovery consumption"
  inference is sound inside this system: `check_head` refuses
  a second ordinary consumption of the head target with
  `AlreadyConsumedError`, so only the scoped exception can
  write the duplicate pair. The closing claim — "Recovery is
  therefore one-shot per burned movement at both the
  authorise step (5b) and consume (check_head), which both
  go through here" — is verified in the tree:
  `trust/verifier_main.py:2539` (authorise step 5b) and
  `check_head` itself (`trust/ledger.py:876-879`) both call
  `match_head_burn`.
- `check_head` (`trust/ledger.py:829-873`): the one-shot
  bullet — "once a recovery consumption of that same pair has
  landed (it becomes the head, with an identical earlier
  entry behind it), a further burned_unadopted envelope for
  the same target raises AlreadyConsumedError here instead
  of riding the exception again" — traces exactly: with the
  recovery entry as head, `match_head_burn` returns None, so
  `recovery` is False, and the candidate-at-head-with-head's-hash
  branch raises `AlreadyConsumedError` (`trust/ledger.py:890-895`).
  The rest of the docstring (head-regression / fork / ahead
  cases, old-pin rules, `initial_anchor` against a non-empty
  journal) matches the implementation line for line. No
  over-claim: both docstrings scope the rule to "per burned
  movement", which is exactly what the pair-equality test
  enforces — neither claims one-shot per target across
  different movements.

### `signing/pin_store.py` genesis shape-rule wording — ACCURATE

- Module docstring (`signing/pin_store.py:31-34`): "adopting
  onto a missing file requires a no-pin ceremony record (its
  old side absent — `initial_anchor` / `lost_pin` /
  `corrupted_pin` / a no-pin `burned_unadopted` recovery)."
  The parenthetical is a list of shapes that CAN present
  no-pin, not a claim that genesis is reason-gated — and the
  code makes the shape-not-reason rule explicit.
- `adopt` genesis branch (`signing/pin_store.py:366-397`):
  genesis requires a record, refuses any record whose
  `old_cycle_seq is not None or old_payload_hash != ""`, and
  the inline comment states the rule precisely: "The genesis
  defect is SHAPE, not reason: a record minted against an
  existing pin elsewhere … must not splice its foreign
  history in as genesis", with the no-pin `burned_unadopted`
  case justified (verifier already proved and consumed the
  burn; refusing it would dead-end recovery when adoption
  failed before the store file existed). The refusal message
  matches: "genesis adoption requires a no-pin ceremony
  record (old pin absent)". The context-bound
  `verify_ceremony_record(..., expected_old_pin=current_pin, ...)`
  check below enforces the same shape mechanically, as the
  comment claims. `tests/test_signing_pin_store.py` test_15
  ("genesis_no_pin_burned_unadopted_creates_store") and
  test_12 ("genesis_with_pin_record_refused") exercise both
  sides of exactly this wording. No over-claim found: the
  docstring does not say genesis proves the burn — that proof
  is correctly left to the verifier.

## Test evidence

Targeted subset re-run by this seat on the current tree:
`python3 -m unittest tests.test_signing_ceremony_recovery
tests.test_trust_ceremony_journal_anchor
tests.test_trust_pin_adoption tests.test_signing_pin_store
tests.test_trust_ceremony_consumption
tests.test_trust_production_deploy tests.test_verifier_deploy`
— **109 tests, OK (skipped=11)**. (The first review's subset
was 72 tests; the deploy suites were added this round because
F2/F5 live in the deploy README they guard.) Full-suite green
remains the build's obligation, not re-verified here.

## Headlines

- SHIP 0.96: F1–F6 all fixed in substance — F1, F2, F3, F5 near-verbatim to the prescribed replacements; F4's §8 paragraph now present in both the module and `reanchor_pin` docstrings; F6's stale "the one journal" sentence replaced with the anchored-audit-trace wording including the anchor-before-mirror order.
- Grep sweep clean: no old claim ("no new configuration", "never re-anchorable", "NOT externally anchored", "one journal that is externally anchored", "covers both journals") survives in any current-claim surface; every survivor is dated internal history or the true, narrowed issuance-journal statement.
- New one-shot docstrings (`match_head_burn` / `check_head`) verified accurate against the code and both call sites (authorise 5b + consume); pin_store genesis wording correctly states a SHAPE rule, not a reason rule, and matches its tests.
- No replacement wording outstanding; nothing in this seat's lens blocks shipping cycle 22.
