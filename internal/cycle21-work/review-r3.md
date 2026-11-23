# Cycle 21 war-room review — rev-r3 (verifier side: ledger + consume mode)

Blind review. I did not build this cycle and did not read any other
reviewer's review-*.md. Scope: CROSS-CHECK-14 item (3), DESIGN-FINAL
R1–R4, R7, R10, `trust/ledger.py` (whole `HashChainJournal` base,
`CeremonyConsumptionLedger`, `SigningLedger.append_ceremony_consumption`),
`trust/verifier_main.py` (`_mode_ceremony_consume`, `_MODES`),
`trust/protocol.py`, `tests/test_trust_ceremony_consume.py`.
Spot-verified: I re-ran the consume suite myself — 26 tests OK.

**Score: 0.78 — Verdict: FIX**

The core mechanism is right: commit point, ordering, head rules,
taxonomy codes, and the seed-only gate all check out in code (details
below). Two things stop a SHIP: the single-code no-oracle guarantee is
defeated by a stderr side channel that the production client faithfully
delivers to the caller (HIGH-1), and the `head()` override is a
type-contract break in a security-journal hierarchy that the named
anchoring follow-up will walk into (MEDIUM-1, with the race test's
weakness at MEDIUM-2).

---

## HIGH-1 — Verify-reason stderr print defeats R2's single-code no-oracle rule, and the production client delivers it to the caller

`trust/verifier_main.py:2473-2474` (in `_mode_ceremony_consume`, step 4):

```python
print(f"ceremony_consume verify reasons: {reasons}", file=sys.stderr)
```

`reasons` is the full discriminating vocabulary from
`signing/ceremony_authorisation.py:686-755` — `unknown_key`,
`payload_hash_mismatch`, `authorisation_id_mismatch`,
`signature_mismatch`, `signer_mismatch`, `operator_mismatch`,
`ceremony_mismatch`, `old_pin_mismatch`, `candidate_mismatch`,
`evidence_mismatch`, … R2's rule is explicit: ONE code
(`ceremony_authorisation_invalid`) for all non-temporal failures, "no
forger oracle". The response document honours it; stderr does not.

This is not a theoretical "verifier-side log" defence:
`trust/client.py:205-212` appends a stderr excerpt to the exception
message on **every** non-zero exit (`message += f" (stderr:
{excerpt!r})"`), and `VerifierClient.ceremony_consumer()` translates
that exception into the `SigningError` that `reanchor_pin` propagates.
So the caller on the production wiring receives the exact reason tuple
(e.g. distinguishing `signature_mismatch` from
`payload_hash_mismatch` from `signer_mismatch`) in the refusal text —
precisely the per-reason oracle R2 forbids, delivered through the
integrated system's own client. A raw subprocess caller captures
stderr directly and gets it even more plainly.

Note the cycle-20 precedent this copies
(`trust/verifier_main.py:1873-1882`) asserts the sub-case is "logged
verifier-side only, on stderr, and never reaches the caller" — that
assertion is false against `client.py:205-212` for the same reason.
For consume it is worse: the leaked values are forgery-relevant
verification discriminations, not filesystem sub-cases.

Fix: drop the print, or reduce it to a non-discriminating marker
(e.g. count only). Do not rely on "stderr is operator territory" —
the client excerpt code disproves it.

## MEDIUM-1 — `CeremonyConsumptionLedger.head()` override is a latent landmine (nothing trips today; graded honestly)

`trust/ledger.py:756-765` overrides `HashChainJournal.head()`
(`ledger.py:213-215`, returns the last `entry_hash` or `GENESIS_HASH`)
to return `(new_cycle_seq, new_payload_hash)` — or `None` on an empty
journal. Two type breaks in one: tuple-vs-hex64-string, and
`None`-vs-`GENESIS_HASH` as the empty sentinel. The class compensates
internally: `_append` is overridden to use `chain_head()`
(`ledger.py:738-754`), and `check_head` works from entries, never
`head()`.

I grepped the entire tree for `.head()` on journal objects. Every
live caller today is safe:

- `trust/ledger.py:197` — base `_append` uses `self.head()`; for this
  subclass the overridden `_append` shadows it, so the base body
  never runs. Correct today, but only by shadowing: any future base
  or sibling method that builds chain entries via `self.head()`
  (the exact pattern at `ledger.py:546`,
  `SigningLedger.try_consume_eval_records`) would write a tuple/`None`
  into `prev_hash`, producing a journal whose entries fail the
  `_load` chain check on next open — corruption by construction.
- `trust/anchoring.py` — `_chain_prefixes` builds `{seq: entry_hash}`
  from `entries()` and never calls `head()`, so anchoring this
  journal would in fact work. But the follow-up named in R10
  (`ceremony-journal-anchoring`, covering this journal) is exactly
  where an implementer will reach for the established head idioms:
  `trust/shipcheck.py:187` (`ledger.head() != expected_ledger_head`)
  and `deploy/verifier-identity/health_check.py:744-749`
  (`ledger.head()[:12]`). Copied onto this class, the first silently
  mismatches forever (fail-closed, but a permanent false
  `ledger_head_mismatch`), the second raises `TypeError` on a tuple,
  and any anchor document built from `head()` fails the hex64
  validator loudly. Failure modes are loud or fail-closed, not
  silently-accepting — which is why this is MEDIUM, not HIGH.
- `trust/budgets.py` uses a separate `head_hash()`; shipcheck /
  crashlab / anchoring tests all call `head()` on `ShipLedger`,
  `SigningLedger`, or the ship-tx journal — none on the consumption
  ledger. The only consumption-ledger `head()` callers are the new
  tests asserting the tuple (`test_trust_ceremony_consume.py:239,338`).

The docstring at `ledger.py:718-726` does disclose the override and
`chain_head()` exists. But the hazard is structural: the hierarchy's
contract ("head() is the chain hash, GENESIS when empty") now has a
subclass that violates it, and the R10 follow-up is already scheduled
to touch this journal. Recommend, before that follow-up: rename the
target accessor (e.g. `head_target()`) and restore `head()` to the
base semantics, updating the two test call sites — cheap now,
confusing later. At minimum the follow-up's brief must carry this
warning explicitly.

## MEDIUM-2 — The two-process race test does not force the append interleave it claims to prove

`tests/test_trust_ceremony_consume.py:462-479,541-575`: `BARRIER_MODULE`
polls for a barrier **file** (5 ms sleep loop) before `vm.main()` runs,
and the parent touches the file after a wall-clock `time.sleep(1.0)`
(line 562). This synchronises process *start*, not the race window
inside `append_consumption` (reload → check → `_save`). Nothing
instruments or widens the reload→save window, so the two processes
can — and on an unloaded box plausibly do — execute the whole mode
serially, in which case the loser is refused at the mode's step-(5)
snapshot pre-check (`verifier_main.py:2490-2496`) and the in-loop
re-check/retry path in `append_consumption` is never exercised at
all. The test then proves end-to-end double-consume prevention
(which is real and worth having) but not the R4 claim it is cited
for — that the concurrent loser surfaces via the bounded-retry
re-check as `AlreadyConsumedError` rather than `CorruptLedgerError`.

The mechanism itself is correct by inspection (see Race composition
below); the gap is evidentiary. A barrier placed inside the append
path (e.g. wrapper patching `_save` or `_reload` to rendezvous both
processes after reload, before save) would force the interleave
deterministically.

## LOW-1 — Retry exhaustion surfaces as `ledger_failed`, not the R4 loser codes

`trust/ledger.py:834-877`: after `_APPEND_RETRY_ATTEMPTS` (8)
contended attempts, `append_consumption` re-raises the last
`CorruptLedgerError`; `_mode_ceremony_consume` maps any non-typed
exception to `ledger_failed` (exit 3). R4 says the concurrent loser
surfaces as `ceremony_already_consumed`, not `ledger_failed` — true
for the realistic two-process case, not under sustained >8-way
contention inside the retry windows, where even a legitimate
different-target consume can land on `ledger_failed`. Fail-closed
and bounded; noted for wording precision in R4, not a blocker.

## LOW-2 — Crash coverage is narrower than R7's K1–K6

Delivered in this suite: kill-before-append (burns nothing, retry
succeeds), kill-after-append-before-response, mirror-failure-after-
commit. Not covered: kill between mirror and `_update_anchor`, and a
torn write mid-`_save` (the corrupt-journal test writes hand-made
garbage, `test_...py:392-401`, which validates fail-closed load but
is not a torn-write simulation; `_save`'s tmp+replace+fsync makes a
torn main file structurally unlikely, so the residual risk is
small). The two delivered kill tests are genuine — see below.

## LOW-3 — `append_consumption`'s own duplicate detection is consumption-journal only (by design, worth stating)

`trust/ledger.py:858-861` checks `authorisation_id` against the
consumption journal only; the signing-ledger mirror cross-check
lives in the mode (`verifier_main.py:2498-2504`). That matches R4
(the journal is the authority, the mirror is audit), and the mode
pre-check closes the rollback case (mirror present, journal rolled
back) on the integrated path. Direct ledger-level callers — e.g.
the ledger-backed test consumer in the pin-ceremony suite — bypass
the mirror check. Acceptable, but the class docstring should say
the mirror check is a mode responsibility, since
`append_consumption` is described as "THE commit point" and a
future direct caller could assume it re-checks everything the mode
does.

## LOW-4 — The normal next-ceremony head edge (old_pin == head, equal hash) has no mode-level test

Code is correct (see Head-rule edges). The consume suite tests
old-pin behind (`:322-335`) and old-pin ahead (`:337-354`) but not
old_pin exactly equal to the head with the head's hash and a
candidate ahead — the single most common legitimate second
ceremony. The pin-ceremony suite exercises the path indirectly via
its ledger-backed consumer, so this is a coverage nit, not a gap in
the mechanism.

---

## Verified correct (the bulk of the scope)

**(2) Commit ordering — PASS.** `verifier_main.py:2540-2560`:
`append_consumption` → `SigningLedger.append_ceremony_consumption` →
`_update_anchor(config)`, in that order, each step reached only if
the previous returned (typed append failures raise before the mirror
is constructed; mirror failure raises `ledger_failed` with the
"stays burned" detail and no success response). Mirror-before-commit
nowhere in the tree: the only other `kind="consume"` writer is
`try_consume_eval_records` (`ledger.py:541-552`), correctly scoped
to `format="eval-consumption"`.

**(3) R4 trap — PASS.** Every signing-ledger cross-check for
consumptions is scoped to `kind="consume"` **and**
`format="ceremony-consumption"`: the mode's already-consumed scan
(`verifier_main.py:2498-2504`) is the only one, and the happy-path
test proves the issuance mirror's `kind="sign"` /
`format="ceremony-authorisation"` entry for the same
`authorisation_id` does not trip it (`test_...py:246-261`).
`SigningLedger.append_ceremony_consumption` (`ledger.py:424-460`)
reuses EXISTING `EXTRA_KEYS` — no format migration.

**(4) Race composition — PASS (mechanism); see MEDIUM-2 for the test.**
`append_consumption` (`ledger.py:856-877`) reloads and re-runs both
checks on every attempt. Mental interleaves, two processes:
same envelope → loser's retry reload sees the `authorisation_id`
→ `AlreadyConsumedError`; same target, different envelopes →
loser's retry hits `check_head`'s candidate==head rule →
`AlreadyConsumedError`; different targets → loser retries against
the new head and either appends cleanly (candidate still ahead) or
refuses `HeadRegressionError`. The only escape to a corruption
surface is retry exhaustion (LOW-1). The mode maps the two typed
errors to their distinct codes and everything else to
`ledger_failed` (`verifier_main.py:2543-2549`).

**(5) Crash tests — PASS for what they cover.** The wrappers are
real subprocesses patching
`vm.CeremonyConsumptionLedger.append_consumption` on the imported
module and calling `os._exit(70)` (`test_...py:415-445`) — a hard
kill, no cleanup path. Kill-after-append leaves exactly one
consumption entry and the second attempt refuses
`ceremony_already_consumed` (`:513-524`): commit-before-response is
genuinely proven, including the interesting detail that the retry
refuses at the journal pre-check even though the mirror never
landed.

**(6) Refusal taxonomy — codes PASS; the leak is HIGH-1.**
Exit codes match R2 exactly: `malformed_request` and
`ceremony_authorisation_invalid` are `_malformed` → exit 2
(`verifier_main.py:2477-2480`); `ceremony_authorisation_expired`,
`ceremony_already_consumed`, `ceremony_not_issued`,
`ceremony_head_regression`, `ledger_failed`,
`ceremony_seed_unconfigured` are `_config` → exit 3. The temporal
split is sound: `set(reasons) <= {"expired", "signed_in_future"}`
→ expired; any mixed set (e.g. expired + signature_mismatch) falls
to invalid, so expiry cannot be used to probe signature validity.
The response *document* carries one code for all non-temporal
failures — the oracle exists only via stderr (HIGH-1). Envelope
parse failures surface as `malformed_request` with the
`SigningError` text as detail (`:2465-2468`): that distinguishes
structural defects in the caller's own submission, which the caller
already knows; not scored as a leak.

**(7) Config gate — PASS.** The mode's only gate is
`config.ceremony_signing_key is None` → `ceremony_seed_unconfigured`
(`verifier_main.py:2452-2457`); operators and evidence config are
never consulted in the mode, and the test blanks all three and
still gets the seed code (`test_...py:381-390`). Fail-closed on
corrupt state: step (5) constructs both the consumption ledger and
the signing ledger inside one try → `ledger_failed` on any load
failure (`:2483-2489`), and the issuance lookup is separately
wrapped (`:2507-2515`). `HashChainJournal._load` validates the
whole file (size cap, strict parse, key sets, seq, chain, hashes)
before any entry is visible — there is no partial-scan path.
(Production startup additionally requires operators/evidence —
a `_load_config` deployment fact, not a mode gate; consistent with
R2's wording.)

**(8) Head-rule edges — PASS, no off-by-one found.**
`check_head` (`ledger.py:775-832`): empty entries return before any
check, so a first `initial_anchor` is admitted; against a non-empty
journal `initial_anchor` raises `HeadRegressionError` before the
candidate/old-pin rules — R3's unconditional wording. All
comparisons are direct `<` / `==` / `>` on `cycle_seq` with no
arithmetic, so there is no seq off-by-one to find; candidate==head
with equal hash → `AlreadyConsumedError` (movement consumed),
candidate==head with different hash → regression (fork),
old_pin==head requires hash equality and passes when equal (the
normal next ceremony), old_pin ahead passes (advance_pin case,
tested at `:337-354`). `consumption_seq` in the response is the
journal entry's own `seq` (`verifier_main.py:2562-2566`), ≥ 1 by
construction. Mode-level pre-checks (steps 5–7) run on a snapshot,
but the append re-checks against fresh entries, so the snapshot is
an optimisation, not a TOCTOU hole.

**Protocol registration — PASS.** `ceremony_consume` is in both
`trust/protocol.py:29-31` (`MODES`) and `verifier_main.py:2569-2573`
(`_MODES`), per R2's seat-A catch.

---

## Verdict

**FIX (0.78).** Required before ship: remove or neutralise the
verify-reasons stderr print in `_mode_ceremony_consume` (HIGH-1) —
it silently cancels a headline R2 guarantee on the production
wiring. Strongly recommended this cycle: rename the consumption
ledger's target accessor before the R10 anchoring follow-up builds
on `head()` idioms (MEDIUM-1), and strengthen the race test to
rendezvous inside the append window (MEDIUM-2). Everything else in
scope — commit ordering, mirror scoping, head rules, taxonomy
codes, seed-only gate, fail-closed loads, commit-before-response —
verified correct in code and, where tested, in tests I re-ran.
