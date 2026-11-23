# Cycle 22 — rev-r6 (FORCED DISSENT)

Verdict: **FIX** — Score: **0.70**

Scope reviewed: uncommitted working tree on aeb6ef6
(16 modified files, +637/−75, plus untracked
signing/pin_store.py, trust/pin_adoption.py and four new test
files). Read: DESIGN-FINAL.md (R1–R4), CROSS-CHECK-15.md in
full, REVIEW-CYCLE-21.md (predecessor dissent + flip
conditions). I did not read other cycle-22 reviewer notes.
Tests run by this seat: the six cycle-22 modules
(ceremony_recovery, pin_store, ceremony_journal_anchor,
pin_adoption, ceremony_consumption, ceremony_authorisation)
— 127 tests, OK. I did NOT run the full suite; see F6.

Credit where due, because the dissent is about claims, not
craft: F4's authorise-side validation is real (F4 below),
the R2 commit order is the right order and its mandatory
adversarial test is genuine, the diff is clean and in-scope
(F7), and the residuals are mostly disclosed in docstrings
rather than buried. What follows is why "mostly disclosed,
narrowed, and built-but-unwired" still does not earn an
unconditional SHIP, and why the external seats — Gemini in
particular — can honestly still say no.

---

## F1 — HIGH: the consume-side recovery exception is self-perpetuating; target-level single-use for the head target is waived permanently, not once

Evidence:
- `trust/ledger.py` `check_head` (diff hunk, ~L836–856): when
  `signed.reason == "burned_unadopted"` and
  `match_head_burn(entries, candidate, old_pin)` matches, the
  `AlreadyConsumedError` for candidate==head is skipped AND
  the entire old-pin rule is skipped (`if not recovery …`).
- `match_head_burn` (`trust/ledger.py` ~L785–803) matches on
  (candidate seq+hash, old-pin seq+hash) ONLY. It does not —
  and cannot — distinguish the original burn from a
  recovery's own consumption.
- `append_consumption` (`trust/ledger.py` ~L915–928) records
  authorisation_id, ceremony_id, operator, old/new target,
  evidence_hash, consumed_at — **no reason field**. The
  journal therefore contains nothing that marks a head entry
  as "this was itself a burned_unadopted recovery."

Consequence: a recovery consumption appends a head entry
with the *identical* candidate and old pin that
`match_head_burn` looks for. The exception's precondition is
re-created by its own use. Any number of burned_unadopted
envelopes authorised while that target is head (authorise
does not consume; design-a §4.4.5 concedes both race
recoveries "can also land") can each consume the same target
in succession, indefinitely — each is a fresh
authorisation_id, so the one single-use check that survives
(by authorisation_id, `append_consumption`) never fires.
Design-a §4.4.1/§4.4.5 disclose this and bound it ("pin value
cannot change; worst case is a redundant, journaled
ceremony"). The bound is real — no fork, no substitution, no
backwards move — which is why this is HIGH, not CRITICAL.
But the shipped claim grammar still says "single-use": at
the verifier, single-use *per target* for the head target is
now permanently waived, and the only things preventing a
second consumption of an **already-adopted** target are
caller-side obligations (FRESH-PIN binding, COMPLETE-HISTORY)
that cycle 21 itself classified as not in-process verifiable.
A verifier-side one-shot (e.g. record the reason in the
consumption entry and refuse to match a head entry that is
itself a recovery consumption) is not present and, on the
current journal format, not possible. Gemini asked for
single-use; this ships single-use-except-when-it-isn't, with
the exception self-renewing.

## F2 — HIGH: the mirror gap is narrowed to a window, not closed; item (3) still carries scoping — now a different scoping

Evidence:
- `tests/test_trust_ceremony_journal_anchor.py:366`
  `test_append_anchor_window_rollback_replay_succeeds`:
  a rollback inside the append→anchor-update window
  resurrects the envelope and **replay SUCCEEDS**. This is
  pinned deliberately and disclosed in the module docstring
  (L22–25), the consume docstring in
  `trust/verifier_main.py`, and the DECISION-CONSUMPTION-HEAD
  addendum. Not buried — credit.
- `:393` `test_research_no_anchor_rollback_replay_succeeds`:
  with no anchor configured there is no rollback claim at
  all; production requires the anchor only when the ceremony
  seed is configured (`trust/verifier_main.py` `_load_config`
  production block).

Gemini's cycle-21 defect (CROSS-CHECK-15) was stated
absolutely: "a burn that a verifier-home rollback erases,
resurrecting a still-valid envelope." That sentence is still
literally true inside the window. R2's answer redefines
"closed" as "closed outside the window every anchored append
in this system carries." That may be the right engineering
call — the signing ledger has the same window — but it is a
*claim narrowing*, and the external seats have not accepted
the narrowing. The brief question for cycle 22 is whether
item (3) is closed **without the provisional scoping**. It is
not: the old scoping (intact home / mirror-reached burns) was
traded for a new one (anchor configured + anchor update
completed + production-seed-configured). Honest wording is
"mirror gap narrowed to the append→anchor window," not
"mirror gap closed."

Issuance side: R2 defers anchoring `ceremony-authorisations.json`
and *narrows* the `ceremony-journal-anchoring` follow-up to
it unilaterally (DESIGN-FINAL R2; DECISION addendum). Seat
B §1.4's argument (a resurrected issuance pair must still
pass consumption) is plausible — but it leans on consumption
single-use/head strength that F1 weakens for exactly the
head target, and the narrowing has not been put to the
externals. A resurrected issuance record also erases the
anti-replay/evidence-reuse history authorise step (5) scans;
re-issuance still needs an allowlisted operator and fresh
evidence resolution, so this is a residual, not a bypass —
but it is *our* seat that decided it is out of scope, not
the seats that raised the defect.

## F3 — HIGH: "first production adopter" still has zero production callers; Gemini's cycle-21 objection (b) is answered in form, not substance

Evidence:
- `grep -rn "run_one_cycle_and_pin|PinAdopter|build_pin_adopter|snapshot_and_adopt"`
  across the tree outside `trust/pin_adoption.py` and tests:
  **no callers**. `core/loop.py` untouched (by R3 design);
  no runner switch exists; nothing in production code imports
  `trust.pin_adoption` or `signing.pin_store`.
- The end-to-end integration harness
  (`tests/test_trust_pin_adoption.py:92–97`) constructs a
  direct `VerifierClient` with
  `AION_DEPLOYMENT_MODE: "research"` — the R12 pattern,
  honestly docstringed. `build_pin_adopter` /
  `production_client` are exercised only in `test_08`
  (config refusals), never end-to-end in production mode
  with anchors configured. Design C §8.2 listed the
  production-mode anchored variant as "an option, not
  smuggled in"; the option was not taken.
- R3 itself concedes: no live run against `state/state.json`;
  live recording "additionally needs a runner switch +
  verifier provisioning (deployment)."

Cycle 21, Gemini (b): closure "rejected with zero production
callers — the claim currently rests on test-harness wiring."
Cycle 22 builds a caller-*shaped* object and wires it in
test-harness wiring. The structural fact Gemini rejected is
unchanged, one level up. "First production adopter" should
read "first adopter implementation, exercised in research
mode; unwired." As worded, it invites exactly the rejection
it got last cycle.

## F4 — MEDIUM: F4 is genuinely validated at authorise — with three soft spots the other seats may under-weight

What is solid (verified in the diff):
- `trust/verifier_main.py` authorise step (5b): only for
  `reason == burned_unadopted`; `CeremonyConsumptionLedger.match_head_burn`
  exact equality on candidate AND old pin (None encoded
  seq=None/hash=""); `burn["ceremony_id"] == ceremony_id`
  refused; ONE exit-3 code `ceremony_recovery_unproven` for
  every predicate failure (no journal-state oracle);
  unreadable journal → `ledger_failed`; ordinary issuance
  gains no new dependency. The read runs after `_load_config`'s
  per-request anchor verification when configured. There is
  no path I found where authorise asserts the label without
  the journal's head entry proving it.
- `reanchor_pin` (`signing/pin_ceremony.py`): with-pin
  burned_unadopted requires the strict `("chain_gap",)`
  recomputation exactly as chain_gap_recovery; no-pin case
  gets none. History checks unchanged.
- End-to-end: `tests/test_trust_pin_adoption.py::test_05b`
  performs burn → discard pair → fresh ceremony →
  `record.reason == "burned_unadopted"`, consumption count
  exactly +2, no `lost_pin` anywhere in history.

Soft spots:
1. **Offline record verification proves no burn.**
   `verify_ceremony_record`'s new docstring
   (`signing/pin_ceremony.py`) admits it: for a
   burned_unadopted record it proves only coherent
   reason/pin shape under the MAC key; burn linkage at audit
   time is a manual record → journals correlation. Minting
   is gated (5b + consume); *verification* is not. An auditor
   handed only the pin store — the artefact PinStore exists
   to make self-verifying — cannot distinguish a proven
   burned_unadopted record from a merely-labelled one.
   Disclosed, but it means F4's honesty guarantee is
   verifier-online-only.
2. **The adopter's computed reason rests on unprotected
   local files that are functionally sole-source.**
   `trust/pin_adoption.py` `_read_journal` silently skips
   malformed lines; `_journal_ceremonies` merges lines with
   `candidate_envelope` surviving from the authorised line;
   the journal is plain JSONL — no hash chain, no anchor, no
   MAC — and `snapshot-candidate.json` is a bare side file.
   Tamper cannot mint a label (verifier 5b is the backstop —
   good), but *loss* dead-ends recovery: the burned candidate
   envelope's only copy lives in these files, and a fresh
   signing of the same sequence yields a different hash,
   which the head refuses as a fork. The code calls the
   journal "a detection aid, never authority" while recovery
   liveness depends on it absolutely. That tension is
   undisclosed.
3. **`_retained_candidate` does not check the hash.**
   `trust/pin_adoption.py`: `_retained_candidate` returns an
   envelope matching candidate_seq + old pin without checking
   `signed.payload_hash` against the journal entry's
   `candidate_hash` — unlike `_retained_current_candidate`,
   which does check. Downstream verification fails closed
   (the wrong-hash envelope cannot verify against current
   bytes / cannot match the burn in `_find_unadopted_burn`),
   so this is sloppiness, not a bypass — but in the
   security-critical path, the two retained-candidate paths
   should not differ in the one check that matters.

## F5 — MEDIUM: WS3 deviations are caches, not bypasses — except one weakened assertion in the one test that counts ceremonies

- `candidate_envelope` retained in `adoption-pending.jsonl`
  and the `snapshot-candidate.json` side file
  (`trust/pin_adoption.py`): the retained artefact is a
  *snapshot* envelope (state attestation), not a ceremony
  authorisation; it carries no consumption authority, is
  re-verified against current state/calibration bytes on
  every attempt, and the side-file path additionally checks
  seq+hash against the live pin. I found no adoption bypass
  or authority leak in either. They are, however, deviations
  from design C as flagged, and they enlarge the pin_dir
  trust surface in ways F4.2 covers.
- Weakened assertion: `tests/test_trust_pin_adoption.py:324`
  (test_05b) asserts `assertGreaterEqual(len(artefacts), 3)`
  for evidence artefacts where the scenario mints a known,
  exact set (genesis + gap + recovery). `>=` in precisely
  the test that proves "exactly one extra ceremony, no
  lost_pin" would let an unexpected extra ceremony's
  artefact pass unnoticed. The exact consumption-count
  assertion (+2) bounds the damage — hence MEDIUM-LOW in
  effect — but the assertion should be `assertEqual(..., 3)`.
- Counts otherwise meet spec: pin-store tests 14 methods vs
  §8.1's 11 specified; adoption tests 9 vs §8.2's 8 cases.

## F6 — MEDIUM: the ship record does not yet exist; R4/R2 bookkeeping is unverifiable from the tree

- No `internal/BUILD-CYCLE-22.md` and no
  `internal/CROSS-CHECK-BRIEF-CYCLE-22.md` in the tree at
  review time (both are R4 deliverables). The full-suite
  total R4 requires (baseline 1472 OK, skipped=28) is
  recorded nowhere I could find; this seat verified only
  the 127 cycle-22-module tests.
- R2's mutation discipline (mandatory test shown to FAIL
  against the pre-cycle-22 commit order, "result recorded")
  has no recorded result in any build record in the tree.
  (A grep surfaced the claim inside another reviewer's file,
  which I did not read; a reviewer's scratch run is not the
  build record R2 specified.)

## F7 — LOW / clean: no out-of-scope damage

`git diff --stat`: 16 files, all inside R1–R3 scope
(signing/, trust/, deploy allowlist copies, DECISION
addendum, tests). `eval/` and Part A untouched. Allowlist
17→19 applied consistently across run-verifier.sh,
health_check.py, wiring.py, setup.sh and both test suites.
No GitHub push. This finding is a pass, recorded so the
record shows it was checked.

---

## The two external questions, argued honestly

**(i) Is item (3) now closed WITHOUT the provisional
scoping?** No. The cycle-21 scoping (intact home;
mirror-reached burns; F4 deferred; no production caller) was
replaced, not removed: closure now holds for
anchor-configured deployments, for burns whose anchor update
completed, with target-level single-use waived for the head
target (F1), and with the adopter unwired in production
(F3). GPT (FIX 0.96, scoped-provisional last cycle) plausibly
flips: its four mandatory conditions are met in form — F4
built, an adopter built, intact-home preserved *stronger*
than before for consumptions, head/pin distinction retained.
Gemini (FIX 0.88) has three fresh, honest grounds to hold:
its defect statement remains literally true in-window (F2);
its zero-production-callers objection remains structurally
true (F3); and F1 gives it a new verifier-side single-use
exception its "single-use" framing never accepted. Expect a
continued split.

**(ii) May cycles 14–16 proceed to re-review?** On this
diff, no — not because the code is weak, but because the
standing rule (no ship on a split; an external FIX is not
overridden) makes 14–16 hostage to the externals actually
seating on cycle 22, and the brief they must seat on does
not yet exist (F6). An internal SHIP here would pre-empt
the exact reconciliation CROSS-CHECK-15 prescribed.

## Predecessor flip conditions (REVIEW-CYCLE-21, rev-r6) — judged

- Condition (1), alternative branch — "`burned-but-unmoved-recovery-reason`
  lands and is tested end-to-end": **MET in substance**
  (F4: 5b validation, check_head exception, test_05b
  end-to-end, no lost_pin). My predecessor would flip on F4
  alone. I do not, because cycle 22 makes *new* claims
  (mirror-gap closure, first production adopter) that the
  cycle-21 conditions never priced, and F1/F2/F3 attach to
  those new claims, not to F4.
- Condition (2): discharged in cycle 21; cycle-22 wording
  (R10 rewrite, DECISION addendum, oracle narrowing in
  `trust/ledger.py` AlreadyConsumedError docstring and the
  consume docstring) is honest and travels with the claims —
  except the two wordings flagged in F2/F3.

## Flip conditions — what would make rev-r6 SHIP

1. **External reconciliation actually happens:** seat-gpt
   and seat-gemini seated on the cycle-22 brief, and both
   accept (a) the append→anchor window as the stated
   boundary of the mirror-gap closure, (b) the issuance-journal
   anchoring deferral/narrowing, and (c) the adopter's
   current wiring status — OR the claim wording is downgraded
   to match reality ("mirror gap narrowed to the
   append→anchor window"; "first adopter implementation,
   unwired, research-mode exercised") so there is nothing
   left for them to reject. A split keeps my FIX.
2. **One-shot the recovery exception (F1):** record the
   reason (or an equivalent marker) in the consumption
   journal so `match_head_burn` cannot be satisfied by a
   recovery's own consumption entry, plus a test: two
   pre-authorised recoveries for one burn — the second
   consume is refused *at the verifier*. Alternatively, a
   recorded war-room ruling that explicitly re-scopes the
   single-use claim to per-authorisation for the head target,
   carried in the consume docstring and the brief headline.
3. **Adopter honesty (F3):** one production-mode, anchored,
   `build_pin_adopter`-built end-to-end fixture (the
   production_client path, not the R12 research pattern), or
   rename the deliverable per (1c).
4. **Records (F6):** BUILD-CYCLE-22.md with the full-suite
   total and the R2 mutation result recorded; the cycle-22
   cross-check brief written.
5. **Bundled minors (F4.3, F5):** `_retained_candidate`
   gains the payload-hash check its sibling already has;
   test_05b's artefact assertion becomes exact.
