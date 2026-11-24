# Cycle 27 — War-Room Re-Review, Seat rev-r6 (FORCED DISSENT, chair)

Re-review of the fix round against my first-round verdict
(FIX, 0.45; findings F1–F5). Evidence: the current uncommitted
tree in `~/workspace/ai` — the cycle-27 README migration
section, `trust/wiring.py` as amended, and
`tests/test_cycle27_journal_anchors.py` including the new
migration test, which I ran
(`python3 -m unittest tests.test_cycle27_journal_anchors.IssuanceMigrationCeremonyTests`
— 1 test, OK). I attacked each claimed closure on its own
terms; where the fix is real, this record says so.

**Score: 0.70 / 1.00**
**Verdict: FIX** (narrow — three small items, listed at the
end. The blocking character of the first round is gone: F1's
outage-with-no-exit is answered for the issuance journal, and
F2/F3 are genuinely closed. What remains is that two of the
fix round's claims are stated more strongly than the tree
supports, and one finding was answered with a euphemism
instead of the disclosure it asked for.)

---

## F1 — No migration path for established journals

**Status: NARROWED, not closed. The issuance half is proven;
the supersession half and the production walk are not.**

What is real, and credit where due:

- The README now carries a proper cycle-20-style migration
  section ("Cycle-27 migration (established deployments)"):
  it names both fail-closed breaks, explains why INIT pins
  only empty journals (a deleted anchor must not launder a
  rolled-back journal), states that the first pin blesses
  current history and cannot detect a pre-pin rollback, and
  puts the intact-home verification on the operator. That is
  the disclosure the first round demanded.
- The migration test
  (`IssuanceMigrationCeremonyTests.test_issuance_migration_first_pin_ceremony_on_established_journal`,
  test file line 903) is a genuine walk, not a refusal
  restated: it builds a non-empty issuance journal with no
  anchor configured, first-pins it outside the verifier via
  `initialise_anchor(..., kind="ceremony-issuance",
  allow_nonempty_ceremony=True)`, asserts the pin matches
  seq/head, then runs a real verifier subprocess invocation
  with the anchor path set — it starts (code 0) and a
  subsequent authorisation advances the anchor by exactly
  one. I ran it; it passes. My first round's central claim —
  "no test demonstrates a legitimate operator recovering" —
  is false for issuance now.

Where the response is weaker than claimed:

1. **Supersession has no migration test at all.** The README
   procedure and the fix round's claim cover "issuance or
   supersession" journals, but the only migration test pins
   the issuance journal. There is no test that first-pins an
   established (non-empty) supersession journal and starts a
   verifier against it. The code path is the same generic
   `initialise_anchor`, so the risk is low — but "a migration
   test proving the path" (the fix round's wording) proves
   one of the two paths it is cited for. An established
   supersession journal is precisely the rarer, less
   exercised object; symmetry is an argument, not evidence.
2. **The proven walk is research-mode only, and partial-env.**
   The migration fixture sets `anchored = False` — no anchor
   paths at all — and the post-pin invocation adds only
   `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`. A real production
   deployment migrating under the note must pin *both*
   journals, add *both* paths, and start in production mode
   with the ceremony seed configured (where both paths are
   required and INIT is refused). No test walks that
   sequence, so the exact deployment the note is written for
   has never been executed end-to-end in the suite.
3. **The "ceremony" is a library call with no runnable
   procedure.** There is still no operator tool or call site
   outside `trust/verifier_main.py`'s INIT paths that passes
   `allow_nonempty_ceremony=True` (grep over non-test code:
   the flag appears only in `trust/anchoring.py` itself).
   The README tells the operator to "call
   `trust.anchoring.initialise_anchor` on the journal" but
   never says how to construct that journal object, what
   `recorded_at` to pass (it is a required keyword), what
   working directory / import path to run from, or where the
   anchor path argument comes from. An operator following
   only the README cannot complete the ceremony without
   reading the source. The cycle-17 ship-tx precedent is
   real as a *code* precedent; as an *operator* precedent it
   had the same gap, and citing it does not close this one.

None of this re-opens the wedge: an exit now exists, is
documented in substance, and is test-proven for issuance.
But F1's fix requirement asked for the ceremony plus a test
that walks an established journal from unanchored to
anchored — for both journals the cycle anchors. One of two
is walked, in the wrong mode. Narrowed, honestly; not
closed.

## F2 — Wiring break contradicting wiring's own rationale

**Status: CLOSED.**

The fix round took option (b) from the first round, exactly
as specified. `trust/wiring.py` now records the exception in
the comment above `REQUIRED_ENV_KEYS`: the ceremony anchor
paths are "the standing exception to the not-wiring-required
treatment below", the consumption anchor has carried that
status since cycle 22, an anchor path is "client-construction
configuration, not ceremony capability", and existing
production envs must add both new paths (fail-closed, with a
pointer to the README migration note). The
not-wiring-required paragraph for operators/evidence/seed
below it is left intact and now reads consistently, because
the exception is named before it. The README migration note
discloses the wiring-level break separately as item (1),
including that `setup.sh`'s template carries the new lines
for new installs and never overwrites an existing env file
(verified in the `setup.sh` diff). The remaining asymmetry —
wiring unconditional, verifier seed-keyed — is now a stated,
argued design choice rather than a contradiction. No
residual.

## F3 — Availability coupling undisclosed

**Status: CLOSED (as a disclosure finding).**

The migration note states it in the terms the first round
asked for: "all five anchors are verified at startup on
EVERY verifier invocation, so a fault in any one anchor or
journal refuses every mode until repaired — fail-closed, and
the price of startup enforcement." `internal/DECISION-CONSUMPTION-HEAD.md`
Addendum 7 (c) records the same ruling. The coupling is now
chosen on the record, not inherited silently.
`design-final.md` itself was not amended, but it is the
pre-review design record; the decision record and the
operator README — the two places a ship decision and an
operator actually read — both carry it. I do not hold F3
open over the unamended design draft.

## F4 — Non-transactional multi-anchor bootstrap

**Status: NARROWED. Repeatability is disclosed; the
side-effect itself is described with a euphemism, the
cross-operation pinning is still undisclosed, and the
partial state still has no test.**

What the fix round added (README, migration section):
"Bootstrapping several anchors in one research-mode INIT
invocation is safe to repeat: each anchor is verified
independently, and an invocation that stops halfway leaves
the remaining anchors missing, which refuses startup until
the ceremony is completed."

Attacks:

1. **The sentence mis-describes the state it discloses.** An
   invocation that stops halfway does not merely "leave the
   remaining anchors missing" — it leaves the earlier anchors
   *created on disk by an invocation that was refused*. In
   `_load_config` order the issuance helper call
   (`trust/verifier_main.py:1217`) completes before the
   supersession call (`:1232`) runs; if the second fails, the
   first anchor file persists. That persistence-of-effect
   under refusal was the finding. The note's phrasing makes
   it sound as though a stopped invocation leaves nothing
   behind but absence. "Safe to repeat" is true — re-running
   INIT verifies the created anchors and pins the rest — and
   I verified that logic against the helper; but safety of
   recovery is not the same as honesty about the side
   effect, and the note claims the first while phrasing away
   the second.
2. **Cross-operation pinning is still nowhere disclosed.**
   One `ceremony_authorise` request carrying the INIT flags
   pins the *supersession* journal's anchor, although the
   request performs no supersession (the cycle's own
   `bootstrap_anchors()` fixture does exactly this). Neither
   the migration note nor the decision addendum mentions
   that a journal's first pin can be performed as a side
   effect of an unrelated operation on another journal.
3. **Still no test pins the partial-bootstrap state.** Grep
   of the cycle-27 test file: no test drives
   issuance-created / supersession-failed (or any
   halfway-stop) and asserts the on-disk intermediate state
   plus recovery. My first round's minimum was "document the
   non-transactional, side-effecting bootstrap **and** add a
   test for the intermediate state". Half of that minimum,
   in softened wording, is what landed.

This remains non-blocking on its own — recovery by re-run is
real — but it was answered as if disclosure of repeatability
were disclosure of the side effect. It is not.

## F5 — Stale documentation counts

**Status: NARROWED, not closed. The headline numbers are
fixed; one instance of exactly the flagged staleness
survives in the same file, which falsifies the claim that
the sweep was done.**

Fixed, verified: the README cycle-27 paragraph now reads
"(allowlist 20 → 24)" — the true numbers (direct count of
`ALLOWED_KEYS` in the shipped `run-verifier.sh` = 24);
`trust/wiring.py`'s production-client prose now says
"24 names", "all five anchor paths are required", and "All
anchor paths must be absolute"; the comment above
`REQUIRED_ENV_KEYS` says "all five anchor paths";
`tests/test_trust_wiring.py`'s allowlist test asserts the
shipped 24 names.

Surviving: `trust/wiring.py:177-179`, the comment directly
above `ALLOWED_ENV_KEYS` — the definition an operator or
reviewer reads first — still says the wrapper's allowlist is
"(20 names)". That is not a new nitpick; it is one of the
specific stale sites my first round enumerated (the
production-client prose's "20 names" was fixed; this twin
comment was not). A sweep that misses the comment sitting on
top of the very constant being changed was not completed.
(For completeness: the module docstring of
`tests/test_trust_wiring.py` also still recites "the wrapper
allowlist has 19 names" as its ground-truth paragraph. It is
framed as at-write-time history and the test body supersedes
it, so I count it as untidy, not as a second F5 instance.)

One line to fix. It stays on the list because the fix round
claimed this finding closed, and "closed" is checkable.

---

## Remaining fix list (complete — nothing else is held)

1. **F1:** add the supersession twin of the migration test
   (established supersession journal → first-pin with
   `allow_nonempty_ceremony=True` → verifier starts and a
   supersede advances the anchor), and make one of the two
   migration walks run the production-shaped sequence (both
   paths added, seed configured, production mode). Add the
   runnable ceremony detail to the README note: journal
   construction, `recorded_at`, and the invocation context —
   enough that an operator need not read source.
2. **F4:** reword the bootstrap paragraph to state plainly
   that a refused invocation can leave already-created
   anchor files on disk and that one operation's INIT
   invocation pins anchors for journals it does not touch;
   add one test asserting the issuance-created /
   supersession-failed intermediate state and its recovery
   by re-run.
3. **F5:** correct `trust/wiring.py:178` "(20 names)" →
   "(24 names)".

## What is NOT held

F2 and F3 are closed without residual. The core anchoring
mechanics were sound in round one and remain so; the
migration exit exists and is proven for issuance; the wiring
break and the availability coupling are now disclosed where
operators will actually see them. This FIX is about the fix
round's own claims — "a migration test proving the path",
"stale counts fixed", a bootstrap disclosure — each being
one step stronger than the tree. Land the three items above
and this seat signs SHIP without a further round of dissent.

— rev-r6 (forced dissent), re-review
