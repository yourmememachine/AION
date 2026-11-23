# Cycle 22 — rev-r6 RE-REVIEW (FORCED DISSENT seat)

Verdict: **SHIP** — Score: **0.88**

Scope: re-examined the working tree after the fix round,
blind (no other seats' re-reviews read). Re-read
`trust/ledger.py` (`match_head_burn`, `check_head`,
`append_consumption`), `signing/pin_store.py` (`adopt`),
`trust/pin_adoption.py` (`_retained_candidate`), the new
tests in `tests/test_signing_ceremony_recovery.py`
(`OneShotRecoveryTests`) and
`tests/test_trust_ceremony_consumption.py`
(`test_recovery_is_one_shot_second_recovery_refused`).
Ran the six cycle-22 test modules myself: **135 tests, OK**
(127 at first review; +8, consistent with the added
one-shot and pin-binding tests). I did not run the full
suite; the full-suite total remains a commit-time record
item (below).

---

## F1 (HIGH, self-perpetuating exception) — FIXED, and I could not break it

The fix is the one I asked for in substance, achieved
without a journal format change: `match_head_burn` now
returns the head entry only if NO earlier entry carries
the same (old seq, old hash, new seq, new hash) pair. A
recovery consumption writes an entry indistinguishable
from the original burn, so a recovery head can never
ground a second recovery. The rule is enforced at both
gates because both go through `match_head_burn`:
authorise step (5b) and consume (`check_head`).

Why the invariant is sound, not just test-pinned: a
duplicate pair at the head is *unreachable* except via a
recovery consumption. A non-recovery envelope for an
already-consumed target is refused by `check_head`
(candidate == head → AlreadyConsumed; candidate behind
head → HeadRegression), so no ordinary ceremony can mint
the second identical entry, and the head can never
legitimately "return" to an old pair. The earlier-entry
scan therefore has no false-positive against any sequence
`append_consumption` can actually produce — the only
legitimate casualty is design-A's iterated chain, which
the coordinator ruling explicitly supersedes.

My own break attempts (scratch in /tmp, real ledger and
real minted envelopes, six trials — all refused):
- non-adjacent duplicate pair at head (different pair in
  between): `match_head_burn` → None;
- re-burn of the same movement after the head advanced:
  HeadRegressionError;
- genesis (no-pin) second recovery: AlreadyConsumedError;
- recovery carrying a foreign old pin (same seq, different
  hash): AlreadyConsumedError;
- recovery authorised pre-advance, consumed after a normal
  ceremony moved the head: HeadRegressionError;
- stale recovery for an earlier movement after a later
  movement's own burn + recovery landed: HeadRegressionError.

Pinned in-tree at both levels I demanded: unit level
(second consume refused at the ledger; the §4.4.5 race now
pins both-authorised / first-lands / second-refused) and
end-to-end through the real verifier (second recovery
*authorise* refused with the single code
`ceremony_recovery_unproven`, consumption count unchanged).
The supersession of design-A §4.4.5 / §6.2 is recorded in
the test docstrings and the `check_head` docstring, not
silently flipped. Flip condition 2: **MET** (verifier-side
branch, not the re-scoped-claim branch).

## F5 — MET

`tests/test_trust_pin_adoption.py` test_05b now asserts
`assertEqual(len(artefacts), 3)` — exact, as required.

## Bundled minor F4.3 — MET

`_retained_candidate` in `trust/pin_adoption.py` now checks
`signed.payload_hash == entry["candidate_hash"]`, matching
its sibling. The asymmetry I flagged is gone.

## New since my review: PinStore.adopt binding — sound, and it strengthens F3/F4

- `adopt` re-reads and re-verifies under the flock and
  CASes against `expected_old_pin`; the record is verified
  context-bound (`expected_old_pin=current_pin`,
  `expected_new_pin=new_captured`), so a genuine record
  minted against a different pin cannot be spliced into
  this store's history.
- The prospective history (history + record, with the pin
  being adopted) is run through the load-side consistency
  check before serialising — the store never writes a
  document its own load would refuse.
- Genesis follows a shape rule (old side absent), not a
  reason whitelist. This is the right call: the defect was
  a record minted against an existing pin creating a store,
  and shape is exactly that defect; the no-pin
  `burned_unadopted` case the shape rule admits is safe
  because the verifier already proved and consumed the burn
  before adoption is attempted. A replayed record target
  already in history is refused separately.
No new finding from this seat on the binding change.

## F2 (append→anchor window) — NOT code-fixed; claim-scope resolution accepted

The window remains exactly as characterised: a full
rollback inside the append→anchor window resurrects the
envelope, and research mode / no anchor carries no rollback
claim at all. Nothing about the code changed my analysis.
What changed is the claim: the coordinator puts the window
to the external seats explicitly as an *unprotected
residual*, and the closure wording no longer asserts
"mirror gap closed" without that boundary. That is the
downgrade branch of my flip condition 1, and I accept it —
provided the brief actually carries it in those terms
(commit-time requirement below). My honest answer to
external question (i) is unchanged in substance: item (3)
is closed *outside the disclosed window*, and the record
must keep saying so.

## F3 (adopter, zero live callers) — NOT code-fixed; claim-scope resolution accepted, with the docstring doing real work

The structural fact is unchanged: no runner switch, no
live run, `core/loop.py` untouched. But the claim that
travels with the code is now honest where it matters most:
`trust/pin_adoption.py`'s module docstring states plainly
that this is production code exercised end-to-end in temp
dirs against the real verifier subprocess, that no live
run against the live state dir happens, and that the first
live adoption is gated on verifier provisioning;
DESIGN-FINAL R3 carries the same wording ("first production
adopter built and wired as specified; no live run"). That
is the rename/downgrade branch of my flip condition 3, in
the artefacts themselves rather than only in a brief.
Accepted — again conditional on the brief repeating it
verbatim in substance (below).

## F6 (records) — the one condition I hold at commit time

`internal/BUILD-CYCLE-22.md`, `internal/REVIEW-CYCLE-22.md`
and `internal/CROSS-CHECK-BRIEF-CYCLE-22.md` do **not**
exist in the tree as I write this. The coordinator states
they are being written this cycle before the commit. My
SHIP is a verdict on the code and claim state reviewed
here; it covers the commit **only if** all three land in
that same commit, with:
- BUILD-CYCLE-22.md recording the full-suite total
  (baseline 1472 OK, skipped=28) and the R2 mutation result
  — still unverifiable from the tree today;
- the brief carrying (a) the append→anchor window as an
  unprotected residual, (b) the adopter claim worded as
  built-and-wired-as-specified with no live run, and
  (c) the one-shot supersession of design-A §4.4.5 / §6.2
  stated as a coordinator ruling the externals are asked to
  ratify, not as a detail.
If any of the three is missing or the brief softens (a)–(c),
this verdict does not extend to that commit and my F6 FIX
stands for it.

## Carried minors (not flip conditions, recorded so they are not lost)

- F4.1: offline `verify_ceremony_record` for a
  burned_unadopted record still proves shape, not burn;
  the honesty guarantee remains verifier-online-only.
  Disclosed in the docstring; unchanged by this round.
- F4.2: recovery *liveness* still depends absolutely on the
  unanchored local pending journal + retained envelope
  (loss dead-ends recovery; tamper cannot mint — the
  verifier backstop holds). The "detection aid, never
  authority" wording still understates that liveness
  dependence. Safety is unaffected; the tension should be
  named in a future docstring pass.

## The two external questions, updated

(i) Item (3) without provisional scoping? Still no — but
the scoping is now *in the claim*, disclosed as an
unprotected residual and put to the externals directly,
which is the honest form of closure available for this
design. (ii) Cycles 14–16 to re-review? Still gated on the
external seats actually seating on cycle 22 and reconciling
— an internal SHIP, mine included, does not release them.

## Flip-condition ledger (from review-r6)

1. External reconciliation OR downgraded wording —
   **MET via the downgrade branch** (window as stated
   residual; adopter wording downgraded in DESIGN-FINAL
   and the module docstring), conditional on the brief
   carrying it (F6 above). The external seating itself
   remains outstanding by design and still gates 14–16.
2. One-shot the recovery exception — **MET** (verifier-side,
   both gates, unit + end-to-end pinned; break attempts
   failed).
3. Adopter honesty — **MET via the rename branch**.
4. Records — **PENDING, required at commit time** (above).
5. Bundled minors (F4.3, F5) — **MET**.

No updated flip conditions: the verdict is SHIP, with the
single commit-time requirement stated under F6.
