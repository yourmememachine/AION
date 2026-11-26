# Cycle 32 — War-room review R3 (FORCED DISSENT)

Reviewer seat: R3, arguing against shipping. Scope reviewed: `git diff`
only — `trust/shiptx.py` (post-settlement re-verification in
`ShipTxJournal.recover()`), `docs/RECOVERY-CONTRACT.md`, and the 10 new
tests in `tests/test_trust_shiptx_anchoring.py` (68 tests in that file,
all passing locally). No code edited by this reviewer.

## Verdict: FIX — score 4/10

The gap is real and the patch does detect the narrow case it targets.
It should not ship as-is: it escalates a soft, per-transaction operator
error into a hard raise *after* settlements have irreversibly landed,
classifies by string-negation instead of by the named error set,
dedups on reason spelling rather than on anchor identity, freezes the
same-file decision at the stale initial snapshot, and the contract doc
declares the gap "Closed" in terms the code does not deliver. Each
item below is independently fixable; together they mean the fix trades
a silent-miss bug for a false-alarm / misclassification bug in the
recovery path — the worst place in this system to trade one for the
other.

## 1. Raising on an operator error after settlements stand is the wrong surface (strongest objection)

Pre-settlement, this exact condition — `anchor_malformed`,
`anchor_missing*` — is deliberately a *soft* outcome: a
non-destructive per-transaction error dict, transaction left in place
for the next run, no raise (the classification block at the top of
`recover()`, and `ANCHOR_PARK_REASONS`' own comment: parking/raising
is reserved for chain-mismatch evidence). Post-settlement, the
identical string now produces a hard `AnchorError` / rides
`JournalIntegrityError.anchor_errors` and discards the return value.
Nothing about the anchor got more dangerous in those milliseconds;
only the timing changed. Severity-by-timing is not a principle
anywhere else in this module, and the patch offers no argument for it.

Consequences the tests actually enshrine rather than prevent:

- `test_post_returned_malformed_only_raises_plain` and
  `test_post_real_anchor_corrupted_mid_recovery_raises`: the run's
  only settlement succeeded (`COMMITTED`), yet the caller receives an
  exception, not `[COMMITTED]`. The one production caller,
  `trust/shipcheck.py:recover_ship_tx`, simply
  `return journal.recover(...)` with no `try`, and its docstring
  still promises "Returns the list of outcome dicts" and "One
  transaction's failure … does not block the others." Any caller that
  does not know to fish `.outcomes` off the exception will read a
  fully successful recovery as a total failure — and the natural
  response to that reading is to retry or escalate.
- Retry is incoherent. On a second run the transactions are terminal
  (skipped), the still-malformed anchor is now the *initial* verdict,
  and the post-check dedups against it — so run 2 returns `[]`
  cleanly while the anchor is exactly as malformed as when run 1
  raised. Raise-then-silence is flapping at the API level: an
  operator (or an automated loop) cannot tell from the sequence
  whether anything is still wrong.
- `test_post_returned_error_with_no_settlements_raises` proves the
  raise fires even with `outcomes == ()` — nothing settled, nothing
  at risk, pure noise — where the pre-settlement equivalent with no
  non-terminal transactions also produces no raise. The module
  already has a considered rule for "park evidence with nothing to
  park" (the cycle-17 no-park-target raise, tx-anchor only, with
  reasoning spelled out); this patch creates a second, unreasoned
  no-target raise for the *operator-error* class.
- `plain.outcomes = tuple(outcomes)` is an attribute bolted onto a
  plain `AnchorError` after construction. `AnchorError` raised from
  anywhere else has no `.outcomes`; a consumer written against this
  cycle's behaviour will `AttributeError` on every other raise site.
  That is a trap this cycle manufactures for the next one.

A returned per-run flag / error outcome, or carrying the new reason
in the outcomes of the affected run without raising, would preserve
the pre-settlement contract. If a raise is truly wanted, it needs a
justification for why post-settlement operator error outranks
pre-settlement operator error — the brief asserts "treated exactly
like a new exception-path failure" as if that settled it; the
exception path's raise-after-settlement behaviour for *load
failures* was itself a contested cycle-18 compromise, and importing
it wholesale for the much more common returned-reason channel
multiplies its blast radius.

## 2. Unknown-string handling: classification by negation will misclassify the next integrity reason

The new branches are:

```python
elif r not in ANCHOR_PARK_REASONS and r not in ship_reasons:  # / tx_reasons
    new_park.append((f"ship: {r}", None))                    # operator error
```

That is not "is one of the three named operator reasons." The file
already defines the named set — `ANCHOR_ERROR_REASONS =
{anchor_missing, anchor_missing_established_ledger, anchor_malformed}`
at `trust/shiptx.py:344` — and this patch *does not use it* (it has
no other user in the codebase either). Anything `verify_anchor`
ever returns that is not one of the three park strings is, by this
code, an operator error with bare reason `None`: it can never enter
`.reasons`, never become a `JournalIntegrityError` on its own, and
surfaces at most in `.anchor_errors` / a plain `AnchorError`.

That is a forward-compatibility downgrade, and the codebase already
contains the counterexample-in-waiting: `verify_anchor(...,
check_reanchor_audit=True)` appends audit reasons such as
`reanchor_audit_anchor_mismatch`, `reanchor_audit_chain_broken`,
`reanchor_audit_malformed` — integrity evidence about a rewritten
anchor, not operator typos. `recover()` happens to call with the
flag off today, but the day any caller (or a future cycle closing
the reanchor-audit gap) turns it on in the re-verification path,
anchor-rewrite evidence will be silently demoted to "operator
error" by this branch. The same fate awaits any *future* park-class
reason added to `verify_anchor` before someone remembers to add it
to `ANCHOR_PARK_REASONS` in a different file: fail-open toward the
weaker classification, in a security check.

`test_post_returned_unknown_reason_is_operator_error` does not
mitigate this — it *locks it in*, asserting that the arbitrary
string `"some_future_reason"` is an operator error. A test that
pins unspecified behaviour for unspecified future strings is not
evidence; it is the bug, documented as intent. The brief's design
decision 4 ("any non-park returned string … consistent with the
pre-settlement classification") is precisely the problem restated:
the pre-settlement classifier can afford negation because its worst
case is a soft per-tx error; the post-settlement classifier's worst
case is now a raise/no-raise and JIE-vs-plain decision.

Minimum fix: match on `r in ANCHOR_ERROR_REASONS` explicitly, and
let an unrecognised returned string fail *closed* (integrity
channel or at least its own loud path), with the unknown-string
test inverted to assert that.

## 3. Dedup holes: novelty is judged on reason spelling, not on the anchor

Dedup is `r not in ship_reasons` / `r not in tx_reasons` — string
membership in the initial returned tuple. Three holes follow:

- **Same string, different tamper — suppressed.** `anchor_malformed`
  covers every distinct corruption `_read_anchor` can meet (bad
  JSON, wrong version, bad field types…). An anchor that was
  malformed at initial verification, was *replaced mid-recovery by a
  differently malformed file* (e.g. an attacker or a racing writer
  swapping evidence during the settlement loop), and is malformed
  again at re-verification is "an identical repeat" and is
  suppressed — even though the anchor on disk at settlement time is
  not the anchor that was classified. The unit of novelty should be
  the anchor's identity (head/seq/content hash), not its refusal
  string. As written, the cheapest way to defeat cycle 32 is to make
  the post-state fail with the *same string* as the pre-state.
- **Same failure, different spelling — false "NEW".** The initial
  verdict mixes two channels in one tuple: returned reasons and the
  synthetic `f"anchor_error:{exc}"` exception strings. Dedup compares
  within spelling, never across channels: a failure first recorded
  as `anchor_error:<text>` and later returned as a bare reason (or
  vice versa — the layers that catch/wrap `AnchorError` in
  `trust/anchoring.py` are exactly the kind of thing that changes in
  a refactor) compares unequal and raises as a "change during
  recovery" when nothing changed. No test exercises a cross-channel
  same-failure sequence; every fake returns homogeneous sequences.
- **Per-anchor dedup is asserted, not argued, for the shared-cause
  case.** `test_post_returned_reason_on_other_anchor_is_new` pins
  that `anchor_malformed` newly appearing on ship-tx raises even
  when ship was malformed throughout. But both anchors live in the
  same operator environment: a single mid-run event (directory
  replaced, mount lost, permissions flipped) corrupting both files
  is one event reported as if it were a second, independent change
  on the second anchor — and, per §1, reported by raising after
  settlements. The brief lists this as an open question for
  reviewers; the test suite answers it by fiat before the war room
  does.

Also: the within-run `new_park = list(dict.fromkeys(new_park))`
dedup and its comment ("a returned tuple could repeat a reason")
defend against something `verify_anchor` cannot currently do — every
return in `trust/anchoring.py:verify_anchor` is `()` or a
single-element tuple, and `recover()` never enables the audit
channel that could append more. Dead defence is fine; presenting it
in the contract as part of the guarantee ("Only identical repeats
are suppressed") is not — see §6.

## 4. Flapping anchors: the TOCTOU window is narrowed, not closed — and the patch can be gamed through it

Re-verification is a single extra sample at the end of the run.
An anchor swapped to malformed/missing *and restored* between the
initial verify and the re-verify is invisible (swap-and-restore);
an anchor that flaps malformed → valid → malformed across the two
samples is suppressed by §3's string dedup even though it was valid
at the moment settlements were decided… or, read the other way, an
anchor valid at both samples but absent *during* a settlement is
equally invisible. The patch therefore detects exactly one flap
shape: "different string at sample 2 than at sample 1." The design
record and contract should say that. Instead the contract says a
mid-recovery swap "therefore surfaces" (§6) — unqualified. A
detector that catches the lazy swap and misses the timed swap is
still worth having, but shipping it under a "Closed" heading
invites the next cycle to build on a guarantee that does not exist
(e.g. treating a clean `recover()` return as proof the anchor never
changed during the run — it is not).

There is also a false-flap cost: `verify_anchor` is not pure with
respect to the journal — it recomputes `_chain_prefixes(journal)`
against a journal the settlement loop has just appended to.
Stale-but-valid is handled for head/seq growth, but any transient
read state (partial write by a concurrent appender, filesystem
hiccup surfacing as malformed JSON on one read) at the re-verify
instant is now, per §1, a raise after successful settlements rather
than a soft note. One flaky read converts a good run into an
exceptional one.

## 5. Same-file suppression interplay: the guard is sampled once, the re-verification trusts it forever

The initial block goes to real trouble over the same-file case
(cycle 17): if both paths name the same file, *both* verifications
are suppressed, because running either "would manufacture a kind
mismatch and park every transaction over a typo" — i.e. same-file
is an operator error, explicitly *not* park evidence. The
post-settlement block is guarded only by the `same_path_error`
boolean computed *before* the settlement loop, and inside the loop
it re-verifies each path independently without re-checking identity.

- Distinct-at-start, same-by-recheck: if mid-recovery one anchor
  path is replaced by a symlink/hardlink to the other (exactly the
  class of mid-run filesystem swap this whole re-verification
  exists to catch), the re-check verifies one file under both kinds
  and manufactures `anchor_kind_mismatch` — a *park* reason — for
  what the module's own doctrine calls an operator typo. Result:
  `JournalIntegrityError`, settlements standing, transactions'
  evidence now framed as chain-mismatch. The patch extends the
  re-verification surface without extending the one guard that
  re-verification most needed re-evaluated at re-check time.
- Same-at-start, distinct-by-recheck: `same_path_error` skips the
  post block entirely, so a mid-run separation-plus-corruption is
  never sampled at all. The suppression decision is as stale as the
  verdicts the cycle set out to distrust — the patch distrusts the
  initial *reasons* but fully trusts the initial *wiring diagnosis*.

No new test touches the same-file case at all: no post-settlement
same-file sequence, in either direction.

A related labelling inconsistency rides along: pre-settlement,
labels are suppressed for a ship-only caller (`labelled =
tx_anchor_path is not None`; "a ship-only caller's error strings
keep their pre-cycle-17 bare form exactly"). The post loop hardcodes
`f"ship: {r}"` unconditionally. A ship-only caller that saw bare
`anchor_malformed` before this cycle can now be raised at with
`ship: anchor_malformed` — a format change to an existing caller's
error surface, untested and unmentioned in the brief.

## 6. Docs overclaiming: "Closed" says more than the code does

`docs/RECOVERY-CONTRACT.md` replaces an honest **Gap:** paragraph
with **Closed (cycle 32):** and three claims that do not survive
§§2–4:

1. "surfaces exactly like a new exception-path failure" — except
   the label format differs (`<source>: <reason>` vs
   `<source>: anchor_error:<exc>`), the classification set differs
   (negation vs exception), and the exception path has no equivalent
   of the same-string suppression for a *changed* underlying file.
   "Exactly like" is doing unearned work.
2. "Only identical repeats are suppressed" — false in both
   directions: non-identical evidence with an identical string is
   suppressed (§3, first hole), and identical failures with
   non-identical spellings are not (§3, second hole). The accurate
   sentence is "only repeats of the same reason string on the same
   anchor are suppressed," which reads — correctly — as a much
   weaker guarantee.
3. The docstring in `trust/shiptx.py` now says returned reasons are
   "`anchor_malformed` / `anchor_missing*`" — naming the closed set
   the code does not check (§2). A reader auditing the code against
   its own docstring will conclude the membership test exists. It
   does not. Either the code should match the docstring (use
   `ANCHOR_ERROR_REASONS`) or the docstring should admit the
   negation rule and its risk.

The previous "Gap:" wording was more accurate about the system's
actual posture than the replacement is. Downgrading documented
uncertainty into documented certainty is how the next incident gets
misdiagnosed.

## 7. Test-evidence gaps (why 10/10 new tests passing does not settle it)

- 9 of 10 new tests drive `_fake_seq` mocks of `verify_anchor`;
  they test the classifier's response to invented sequences, not
  anchor behaviour. Only one test corrupts a real file, and it
  covers exactly one cell: ship-tx, malformed, with a settlement.
  No real-file test for: ship anchor corrupted post-settlement,
  real deletion (`anchor_missing*`) post-settlement, both anchors
  changing in one run, swap-and-restore, or same-reason-different-
  content (§3's suppression hole — directly testable with two
  different malformed payloads, and absent).
- No test calls the production wrapper `recover_ship_tx`, so the
  caller-contract break in §1 is invisible to the suite.
- No test runs `recover()` twice after a post-settlement raise, so
  the raise-then-clean flapping in §1 is unobserved by the evidence.
- No same-file post-settlement test (§5), in either direction.

## What would change this vote to SHIP

1. Classify returned reasons by membership in `ANCHOR_ERROR_REASONS`;
   route an unrecognised returned string to the integrity channel
   (fail closed), and invert the unknown-string test.
2. Recompute the same-file check at re-verification time and apply
   the same suppression doctrine there; add both-direction tests.
3. Either stop raising for error-only post-settlement changes
   (report them in-band, preserving `recover_ship_tx`'s documented
   contract) or write down — in the contract, not just the brief —
   why post-settlement operator error escalates where pre-settlement
   does not, and give `AnchorError` a real `.outcomes` default so
   the attribute is part of the type, not a patch on one raise site.
4. Key dedup novelty to anchor content (or explicitly scope the
   guarantee to reason strings) and add the two payloads/one string
   suppression test.
5. Reword the contract from "Closed" to the scoped guarantee in
   §4/§6 above, and fix the `shiptx.py` docstring to match the
   classification actually implemented.

Until at least 1, 2 and 5 land, this is a FIX.
