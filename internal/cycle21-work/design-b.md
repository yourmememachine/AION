# Design B — Cycle 21: protected monotonic consumption head (verifier side) + Ed25519 differential validation & seed hygiene

Seat: coder B (design round — **no code in this round**).
Lead slice: **B — the protected monotonic consumption head, verifier side.**
Second slice: **A — Ed25519 differential validation + seed hygiene** (a real
position, §6, not a sketch).

Inputs read in full: `internal/CROSS-CHECK-14.md` (the requirements),
`internal/CROSS-CHECK-13.md`, `internal/BUILD-CYCLE-20.md`,
`internal/REVIEW-CYCLE-20.md`,
`internal/DECISION-PROTECTED-GATE-EXTENSION.md` (standing rule at the end:
**design decisions are made by the war room and recorded — the owner is NOT
asked**; this design takes the store-location decision itself, §1),
`trust/verifier_main.py` (module docstring, `_load_config` ~396–570,
`_mode_ceremony_authorise` ~2030 to the end of the mode, `_MODES` dispatch,
exit-code conventions: exit 2 malformed, exit 3 config-class refusal),
`trust/ledger.py` (HashChainJournal base; `CeremonyAuthorisationLedger` ~527;
`SigningLedger.consume` pattern — `try_consume_eval_records` ~440),
`trust/anchoring.py` (external head anchoring; `_update_anchor` in
verifier_main ~736), `signing/ceremony_authorisation.py` (envelope shape,
`verify_ceremony_authorisation`, `load_ceremony_seed` ~259,
`REFUSED_TEST_SEEDS`), `signing/pin_ceremony.py` (`reanchor_pin`,
`_check_ceremony_history`, caller preconditions FRESH-PIN / COMPLETE-HISTORY /
ATOMIC-ADOPTION / EVIDENCE-INTENT), `trust/client.py` (`VerifierClient._run`
and `ceremony_authorise` ~433), `tests/test_trust_ceremony_mode.py`,
`tests/test_signing_pin_ceremony.py` (Cycle20ConsumptionTests, T7/T8 ~1008),
`tests/test_signing_ed25519.py` (existing vectors: RFC 8032 TEST 1–3,
negative vectors, the 7 adversarial decode vectors, affine oracle),
`signing/gate_decision.py` (`_check_key_path`, `load_signing_key`),
`trust/protocol.py` (`MODES`), `deploy/verifier-identity/` (wrapper
allowlist, 17 names — see §5).

External verdict being answered (CROSS-CHECK-14): seat-gpt **FIX 0.96
(blocking)**: with a stale caller-supplied `ceremony_history`, a consumed
envelope replays within TTL and **REGRESSES the pin** (tests T7/T8 pin this
executably — T7: stale history re-consumes and returns the same pin; T8: the
real pin advanced to seq 6 by `advance_pin`, the stale replay returns the
seq-4 pin). Two-of-three legs is not partial credit on a single
replay-resistance guarantee; the monotonic head is a release gate. Gemini FIX
item (1): independent differential validation of the in-house Ed25519
(RFC 8032 / Wycheproof adversarial vectors + cross-implementation agreement)
+ seed-file permission enforcement (0600, fail closed) and
derivation-overlap checks at startup. Cycles 14–16 are **NOT** re-reviewed
this cycle; no GitHub push.

**Headline positions (the room can vote these up or down, but each is a
decision, not a question):**

- **D1 (store):** verifier-owned consumption state, route-4, under
  `AION_VERIFIER_HOME` — a **new** journal file
  `ceremony-consumptions.json` in the verifier home, owned by a new
  `CeremonyConsumptionLedger` in `trust/ledger.py`. No new env var (§5).
- **D2 (mode):** new verifier mode **`ceremony_consume`**, body exactly
  `{"signed_authorisation"}` — one key, nothing caller-asserted beyond the
  envelope itself. Commit point is the consumption-journal append, with a
  **dual append** to the signing ledger as an anchored audit mirror (§2.5).
- **D3 (monotonicity):** consumed candidate sequences are **strictly
  increasing**; the envelope's `old_pin` plays **no** role in the head rule
  (that is what makes the rule survive `advance_pin` bypass, §3).
- **D4 (crash):** burn-before-use. Consume **before** local `reanchor_pin`,
  never adopt on a refusal or a lost response. The response-lost ambiguity
  is named as the design's weakest point (§7.1) and is resolved in the
  fail-closed direction.
- **D5 (config):** **zero new env vars.** The five deploy allowlist copies
  stay at 17 names.
- **D6 (A):** differential suite is a **new** file with a partitioned oracle
  (agree-reject vs known-divergence — §6.1); seed hygiene is an **fd-based**
  loader rework (regular-file + owner-only via `fstat`, exactly-0600 kept,
  §6.2); derivation-overlap is **four relations** in `_load_config` (§6.3).
- **D7 (anchoring):** **do NOT anchor the consumption journal this cycle.**
  The signing-ledger mirror (D2) already gives single-use an anchored
  trace in production; the residual narrows to head-regression-after-rollback
  and is folded into a **joint** anchoring follow-up with the ceremony
  journal (§4.4).

---

## 0. What "protected monotonic consumption head" means, precisely

The guarantee GPT's blocking FIX demands, restated as checkable properties
of the **integrated system** (verifier + caller), not of any one function:

- **P1 (single-use).** Each `authorisation_id` is consumed at most once,
  regardless of what history the caller supplies — stale, empty, or omitted.
- **P2 (no regression).** No consumption can move the protected pin to a
  candidate behind the highest candidate already consumed.
- **P3 (atomicity).** No successful pin movement exists without the
  consumption record durably committed; a crash cannot leave "pin moved,
  consumption unrecorded".
- **P4 (fail-closed).** When authoritative consumption state is unavailable
  (unreadable, corrupt, journal rolled back in a detectable way), consume
  refuses rather than proceeding from a partial view.

Cycle 20 meets P1 only for omitted and updated history (T5/T6). T7/T8 pin
the failure of P1/P2 for stale history. The defect is architectural, and
the design says so plainly: `reanchor_pin` is a pure function over
caller-supplied input. It has no pin store, no ledger access, and no
monotonic counter of its own (`pin_ceremony.py` module docstring, "No
in-process check can distinguish a stale history from a complete one").
No change inside `signing/pin_ceremony.py` alone can fix this. The fix is
a store outside the ceremony caller's control, consulted at consumption.
That store is the verifier's home, and the consultation is a new verifier
mode. Seat C owns what `reanchor_pin` does with the mode's answer; §2.7
and §7.3 state the interface between the slices and where the guarantee
stops being a library property.

---

## 1. D1 — Store location: verifier-owned consumption journal

### 1.1 Decision

**New journal, verifier home, zero new configuration:**

- Class `CeremonyConsumptionLedger(HashChainJournal)` in `trust/ledger.py`,
  `FILENAME = "ceremony-consumptions.json"`, `journal_dir = config.home`
  (the same directory that already holds `signing-ledger.json` and
  `ceremony-authorisations.json`).
- One entry per **consumed** authorisation, `kind="consume"` (never `"sign"`,
  never `"authorise"` — the kind vocabulary stays role-exact, mirroring
  `try_consume_eval_records`' `kind="consume"`).
- The ledger is the **authoritative consumption record**: `reanchor_pin`'s
  caller history stops being authoritative the moment the consume mode
  exists, because the only path to a successful re-anchor runs through it
  (caller contract, §2.7).

### 1.2 Alternatives weighed (the room's decision record)

| # | Alternative | Why it loses |
|---|---|---|
| **A1** | **Caller-side store** (pin store / caller journal, i.e. keep history in `reanchor_pin`'s world) | This is the defect. The caller is the party whose stale history is the attack. Any caller-writable record can be replayed, truncated, or simply not updated. Rejected on principle, not on cost. |
| **A2** | Reuse the **signing ledger** alone for consumption (`kind="consume"`, `format="ceremony-consumption"`) | It cannot carry the head. `SigningLedger.EXTRA_KEYS` is fixed (`decision_id, payload_hash, purpose, proposal_id, accepted, signer_id, format`) — widening it is a journal format migration: every historical entry fails the exact-key-set load check. The candidate's `(cycle_seq, payload_hash)` has nowhere to live in that shape, so the monotonic rule (D3) is uncomputable from it. It is kept as an **audit mirror** (§2.5), not as the head. |
| **A3** | Extend `CeremonyAuthorisationLedger` with consume entries | Same fixed-shape problem in the other direction: its `EXTRA_KEYS` carry issuance fields (`authorisation_id, payload_hash, ceremony_id, evidence_hash, operator_id, issued_at`) and no candidate. Mixing issuance and consumption kinds in one journal also muddies the two commit points (issuance commit vs consumption commit) and their rollback analyses, which this cycle must keep separable. Rejected; the issuance journal is read, not written, by consume (for the never-issued check, §2.3). |
| **A4** | **New env-var directory** (`AION_CONSUMPTION_DIR`, or a path under the registry dir) | Pure cost, no benefit. The verifier home is already verifier-owned, already required (`AION_VERIFIER_HOME` is a startup requirement), already protected by the deploy identity (0700, `aion-verifier` user), and already the home of both sibling journals. A separate directory needs a new env var in **five** deploy copies (see §5), a new production-mandatory decision, and a new failure surface — for a store whose threat profile is identical to the ceremony journal's. Rejected. |
| **A5** | Registry dir / ship-ledger dir | Wrong domain, wrong owner semantics. The registry is eval data; the ship ledger is ship decisions. Consumption is ceremony state. Rejected. |
| **A6** | **Separate OS user / off-machine store** for the consumption journal | The strongest placement in the abstract, and the honest end-state for a production boundary — but it is a deployment change, not a cycle-21 code change, and it applies identically to the ceremony journal and signing ledger (the prototype honesty statement in `verifier_main.py` already records that same-user code can read the 0600 key file). It is out of scope for the head itself; the joint anchoring follow-up (§4.4) is where an external anchor location is decided, and that decision can include moving the journals. Not a reason to delay the head. |

### 1.3 Why a new journal file, not a new column in an old one

The codebase's own precedent is decisive: `CeremonyAuthorisationLedger`
exists as a sibling journal precisely because "the signing ledger's entry
shape carries neither ceremony_id nor evidence_hash, and widening its
EXTRA_KEYS would be a journal format migration" (`trust/ledger.py`). The
consumption journal has the same shape argument, with candidate fields in
place of evidence fields. A sibling file under the same home directory is
the established pattern, and it keeps each journal's commit point, kind
vocabulary, and rollback story separately auditable.

### 1.4 Locking note (a real interaction, not a footnote)

`HashChainJournal._save` takes an exclusive `flock` on the **journal
directory descriptor** — and all three verifier-home journals share the
directory `config.home`. That means ceremony-authorise, ceremony-consume,
and every signing mode serialise against each other at `_save` time.
This is acceptable and mildly beneficial: cross-ledger interleavings
collapse into a total order. It is **not** atomicity across ledgers —
that is handled by the ordered dual append in §2.5 — and the bounded retry
in `append_consumption` (§2.4) exists so a legitimate concurrent consume
of a *different* envelope does not spuriously fail with
`CorruptLedgerError` when its `_save` freshness check trips (the
`ShipLedger.burn` / `try_consume_eval_records` precedent, 8 attempts).

---

## 2. D2 — The consume mode: `ceremony_consume`

### 2.1 Mode registration (do not forget this)

- `trust/protocol.py`: add `"ceremony_consume"` to `MODES`. A mode the
  protocol does not list is a protocol error before any mode code runs;
  the cycle-20 mode got this right and the omission is the cheapest
  possible regression.
- `trust/verifier_main.py`: `_MODES["ceremony_consume"] =
  _mode_ceremony_consume`, placed immediately after
  `_mode_ceremony_authorise` (they are a pair: issuance and consumption).
- `trust/client.py`: `VerifierClient.ceremony_consume(envelope)` helper
  (§2.7).

### 2.2 Body: exactly one key

```json
{"signed_authorisation": { <envelope dict, the 14 _ENVELOPE_KEYS> }}
```

**Position: the body is exactly `{"signed_authorisation"}` and nothing
else.** The verifier needs nothing else, and every extra field is a
caller-asserted input smuggled back into a check whose entire purpose is
to stop trusting caller-supplied state:

- The **binding** (operator, ceremony_id, reason, old_pin, candidate,
  evidence) is inside the envelope, signed by the verifier's own seed.
- The **current pin** is deliberately **not** a body field. The head rule
  (§3) is computed over the verifier's own consumed-target history, not
  over a caller-claimed pin. A caller-claimed `current_pin` would either
  be ignored (dead surface) or consulted (a new caller-asserted input
  into the monotonic check — the exact failure mode being fixed). The
  caller's live pin is still enforced, exactly where it belongs: locally,
  by `reanchor_pin`'s exact-binding equality against the captured
  `old_pin` (step (4) of `reanchor_pin`), *after* a successful consume.
- The **history** is deliberately **not** a body field. Consume does not
  read `ceremony_history` at all. That is the point.

The client helper therefore takes the envelope dict only:
`client.ceremony_consume(signed_authorisation_dict) -> receipt dict`.
It verifies nothing cryptographically itself (the envelope was already
verified at issuance by this same client — see §2.7); it checks the
receipt shape.

### 2.3 Validation order (mirrors `ceremony_authorise`'s discipline)

`ceremony_authorise`'s order is: (1) config gates, (2) cheap validation,
(3) operator membership, (4) evidence resolution, (5) anti-replay scan,
(6) sign, (7) retention, (8) journal commit, (9) signing ledger,
(10) anchor. Consume mirrors the *discipline* — config first, cheap
before expensive, read-before-write, commit last — with the steps its own
semantics require:

1. **Config gates, before body validation** (exit 3). The mode requires
   the ceremony seed to be configured: `config.ceremony_signing_key is
   None` → `ceremony_seed_unconfigured` (research + absent; production
   cannot reach here — startup already refused). The seed is needed to
   derive the public key for signature verification; there is no other
   source for it in-process. **No operator-list gate**: operator
   eligibility was decided at issuance, and consumption must not be
   blocked by a later allowlist edit (de-listing an operator must not
   retroactively strand an already-issued envelope mid-recovery — and
   must not silently become a revocation mechanism either; revocation is
   a named non-goal, §2.8). **No evidence gate**: evidence was resolved
   at issuance; consume reads no artifact.
2. **Strict body key set** (exit 2, `malformed_request`): `set(body) !=
   {"signed_authorisation"}`. No ledger touched.
3. **Envelope parse** (exit 2, `malformed_request`): via
   `ceremony_authorisation_envelope_from_dict`. A v1 envelope refuses
   here with its superseded-version wording (the parse path already
   does this — inherit it, do not re-implement). A hand-built dict with
   wrong keys, a hex64 signature, or a malformed payload dies here,
   before any journal read.
4. **Signature + binding verification** (exit 2 / exit 3, §2.4): via the
   existing `verify_ceremony_authorisation`, with the public key derived
   from `config.ceremony_signing_key` (the verifier verifies its own
   issuance — the same call consumers make, not a second path) and
   `expected_signer_id=config.signer_id`. No expected operator/ceremony/
   candidate is passed: consume asserts nothing about the event beyond
   "this verifier issued this envelope and it is still live" — the event
   binding is enforced locally by `reanchor_pin` afterwards.
5. **Already-consumed check** (exit 3, `ceremony_already_consumed`):
   `authorisation_id` present in the consumption journal **or** in the
   signing ledger's consume entries (§2.5 mirror). Checked **first**
   among the state checks (§2.4 rationale).
6. **Never-issued check** (exit 3, `ceremony_not_issued`):
   `authorisation_id` absent from `CeremonyAuthorisationLedger`
   (needs a new `find_by_authorisation_id` method — the ledger has
   `find_by_ceremony` / `find_by_evidence`; add the third lookup, same
   pattern). A validly signed envelope that was never issued is
   impossible from an intact verifier — its only honest causes are a
   rolled-back issuance journal or a seed compromise — so it refuses
   loudly rather than proceeding.
7. **Head check** (exit 3, `ceremony_head_regression`): §3.
8. **Commit: consumption-journal append** — THE commit point (§2.5).
9. **Mirror: signing-ledger append** (`append_ceremony_consumption`).
10. **Anchor update** (`_update_anchor(config)`) — advances the signing
    anchor over the mirror entry, free because the mirror is a signing
    ledger entry.

A journal that cannot be read at steps 5–7 refuses `ledger_failed`
(exit 3) — never scan a partial history and proceed (the
`ceremony_authorise` step-(5) rule, reused verbatim).

### 2.4 Refusal codes (complete table — no unnamed refusal)

| Code | Exit | Meaning | When it fires |
|---|---|---|---|
| `malformed_request` | 2 | Body key set wrong, or envelope unparseable / malformed payload | Steps 2–3 |
| `ceremony_authorisation_invalid` | 2 | Envelope fails `verify_ceremony_authorisation` for a non-temporal reason: `signature_mismatch`, `unknown_key`, `key_id_inconsistent`, `payload_hash_mismatch`, `authorisation_id_mismatch`, `malformed_payload`, `signer_mismatch` | Step 4. Single code for all of them: distinct codes would hand a forger a per-reason oracle (the `ceremony_evidence_unresolvable` single-code precedent, cycle 20 R5(c)). The verifier-side reason tuple is logged on stderr only. |
| `ceremony_authorisation_expired` | 3 | Envelope is expired, or `signed_in_future` (both temporal, both state — not form) | Step 4. Exit 3 because expiry is a property of verifier time/state, matching the exit-3 class for state refusals; a caller retrying after expiry needs a new envelope, not a fixed request. |
| `ceremony_already_consumed` | 3 | `authorisation_id` already carries a consumption entry (primary journal or signing-ledger mirror) | Step 5. **Checked before never-issued**: in an intact world consumed ⊆ issued, so the order is unobservable; in a rolled-back issuance journal, already-consumed is the *safer* answer (it is true in the consumption record) and it is also the more informative one for the operator. |
| `ceremony_not_issued` | 3 | `authorisation_id` is absent from the issuance journal | Step 6. |
| `ceremony_head_regression` | 3 | Candidate does not strictly advance the consumed head (§3) | Step 7. |
| `ledger_failed` | 3 | Either journal unreadable/corrupt, the commit append failed, or the mirror append failed after commit | Steps 5–9. Detail distinguishes the sub-case (caller-visible detail is diagnostic, not evidence — the code is the contract). |
| `ceremony_seed_unconfigured` | 3 | Research mode with no ceremony seed configured | Step 1 (reused code from `ceremony_authorise` — the same condition, the same code). |

No other refusal may be introduced by the build round without amending
this table and its tests. In particular: there is **no**
`ceremony_operator_not_authorised` in this mode (§2.3 step 1), and no
per-reason signature oracle.

**Client-side mapping** (`trust/client.py._run` conventions): exit 2 →
`VerifierProtocolError`; exit 3 → `VerifierConfigError`. That is the
existing mapping for `ceremony_authorise`, and consume inherits it
unchanged — `ceremony_already_consumed` therefore surfaces as
`VerifierConfigError`, which is the correct class for "the verifier's
protected state refuses this", not "your request was malformed".

### 2.5 The commit point and the dual append

**The consumption-journal append is THE commit point.** The exact
semantics, mirroring `CeremonyAuthorisationLedger`'s issuance commit:

- Before the append lands, nothing is consumed; a refusal at steps 1–7
  is retryable (subject to the envelope's own TTL — a refused consume
  does not burn anything).
- After the append lands, the `authorisation_id` is spent **whether or
  not anything else succeeds**. A later failure withholds the receipt
  and the envelope stays burned; recovery is a NEW ceremony (new
  `ceremony_id`, new evidence bundle) — the same burn philosophy as
  issuance ("the pair stays burned with no envelope returned") and as
  `ShipLedger.burn` ("burns are never refunded").

**Dual append: YES — but the second append is an audit mirror, not a
second commit.** The mode appends, in order:

1. `CeremonyConsumptionLedger.append_consumption(signed, recorded_at)` —
   the commit. Entry shape (new `EXTRA_KEYS`, flat scalars, mirroring
   the issuance journal's style):
   `authorisation_id, payload_hash, ceremony_id, operator_id,
   evidence_hash, old_cycle_seq (int | null), old_payload_hash (hex64 |
   ""), new_cycle_seq, new_payload_hash, candidate_signer_id,
   candidate_key_id`, `kind="consume"`, `recorded_at` from the base.
   The `old_*` fields are the envelope's bound old pin (or null/"" for
   no-pin reasons) — recorded for audit, **not** consulted by the head
   rule (§3.4).
2. `SigningLedger.append_ceremony_consumption(signed, recorded_at)` —
   the mirror, reusing the **existing** `EXTRA_KEYS` with the documented
   column reuse (`append_ceremony_authorisation` / `append_claim`
   precedent): `decision_id = authorisation_id`,
   `payload_hash = signed.payload_hash`,
   `purpose = "pin-ceremony-consumption"`, `proposal_id = ceremony_id`
   (the ceremony id, as the authorisation mirror does),
   `accepted = False`, `signer_id = config.signer_id`,
   `format = "ceremony-consumption"`, `kind = "consume"`. No journal
   format migration: `EXTRA_KEYS` is untouched.
3. `_update_anchor(config)` — advances the signing anchor over the
   mirror entry (the anchor is over the signing ledger, which is where
   the mirror lives — this is why the mirror buys anchoring, §4.4).

**Why the mirror exists at all.** The consumption journal, like the
ceremony journal, is unanchored in this cycle (§4.4). The mirror puts the
*consumption fact* (`authorisation_id` consumed, at a recorded time,
under a recorded ceremony) into the one journal that **is** externally
anchored in production. Consequences, each pinned by tests:

- A consumption-journal rollback is **detected** on the next consume of
  the same envelope: the mirror cross-check (step 5) still refuses
  `ceremony_already_consumed`.
- A consumption-journal rollback is **auditable** for every consumed
  envelope, from the anchored store alone.
- The mirror cannot reconstruct the *head* (it carries no candidate
  sequence), so head-regression-after-rollback is the named residual
  (§4.2) — the mirror narrows it, it does not close it.

**Failure between the appends.** If (2) fails after (1) committed, the
mode raises `ledger_failed` and withholds the receipt — the envelope is
still consumed (step 5 will refuse any retry as already-consumed, from
the primary). The mirror gap is an audit gap only, and it is visible:
the primary journal has a consume entry with no matching mirror entry.
A crash between (2) and (3) leaves a stale anchor; `verify_anchor`
treats an older prefix as valid (staleness is not tampering), and the
next append's `_update_anchor` advances it — the established behaviour
for every signing mode.

**Why not the `try_consume_eval_records` single-`_save` pattern?**
That pattern builds two entries in memory and persists them with ONE
`_save` — possible there because both entries live in **one** journal.
Here the two entries live in **two** journals (different files, different
locks), so a single atomic save is impossible. The ordered dual append
with the primary-first commit is the correct adaptation, and the
asymmetry (primary = authority, mirror = audit) must be stated in both
ledgers' docstrings so no future reader "fixes" the order.

### 2.6 `append_consumption` — ledger method contract

New method on `CeremonyConsumptionLedger`, following `ShipLedger.burn`
and `try_consume_eval_records` (bounded reload → validate → append,
8 attempts, `_APPEND_RETRY_ATTEMPTS`):

```python
def append_consumption(self, signed, *, recorded_at) -> dict:
    # type-check: SignedCeremonyAuthorisation only.
    # for attempt in range(8):
    #     self._reload()
    #     if authorisation_id already in entries: raise LedgerError
    #         ("authorisation already consumed: ...")
    #     head = last entry's (new_cycle_seq, new_payload_hash) or None
    #     if head and not (signed.candidate["cycle_seq"] > head.seq):
    #         raise LedgerError("candidate does not advance the "
    #                           "consumed head")
    #     try: return self._append("consume", recorded_at, ...)
    #     except CorruptLedgerError: continue   # competitor landed
    # raise last_error
```

The duplicate and head re-checks live **inside** the method against the
freshly reloaded entries — the cycle-20 fix-round lesson for
`append_authorisation`: the mode's scan (steps 5–7) and the commit append
are not atomic as a pair, so the commit point itself must re-check, and
`_save`'s under-flock freshness check is the second leg. The loser of a
concurrent consume race gets `LedgerError` → mode maps to
`ledger_failed`... **no** — a concurrent consume of the *same*
authorisation_id must surface as `ceremony_already_consumed`, not
`ledger_failed`: the mode catches the duplicate `LedgerError` from
`append_consumption` (distinguished by a dedicated exception subclass
or by the check the mode re-runs — position: the ledger raises
`LedgerError` with a stable message prefix, and the mode re-reads the
journal after a failed append to decide between `already_consumed`
(entry now present — a competitor consumed it) and `ledger_failed`
(genuinely failed). This is the honest race handling; a build-round
shortcut that maps every post-scan failure to `ledger_failed` would make
the concurrent-consume refusal code nondeterministic, repeating the
cycle-20 race-honesty failure.

Also new: `CeremonyConsumptionLedger.consumed_head()` returning
`(cycle_seq, payload_hash)` of the last entry, or `None`; and
`is_consumed(authorisation_id)` (reload + scan, mirroring
`ShipLedger.is_consumed`); and `CeremonyAuthorisationLedger.
find_by_authorisation_id(authorisation_id)` (§2.3 step 6).

### 2.7 Client helper and the caller contract

```python
def ceremony_consume(self, signed_authorisation: dict) -> dict:
    """Consume a ceremony authorisation at the verifier.
    Returns the receipt {"authorisation_id", "ceremony_id",
    "new_pin": {"cycle_seq", "payload_hash"},
    "consumed_at", "consumption_seq", "consumption_head"}.
    Raises VerifierProtocolError (exit 2) / VerifierConfigError
    (exit 3) via _run, as with every mode. The receipt is
    UNSIGNED: it grants nothing and proves nothing in-process;
    it is the verifier's statement, via the launch channel,
    that the consumption entry is committed. Callers must not
    treat receipt possession as pin movement — the pin moves
    only when reanchor_pin succeeds and its result is adopted."""
```

Receipt fields: `new_pin` is the envelope candidate projected to pin
shape (`cycle_seq`, `payload_hash` — no `key_id`/`signer_id`, matching
`_pin_of` minus the bindings the caller already knows; the local
`reanchor_pin` returns the full pin). `consumption_head` is the
consumption journal's head hash after the append (audit aid).
`consumption_seq` is the entry's `seq`.

**The caller contract (seat C's side owns the `reanchor_pin` call, but
this design states the verifier-side expectation it must satisfy):**

1. Obtain the envelope via `ceremony_authorise` (unchanged).
2. Call `ceremony_consume(envelope)` **before** `reanchor_pin`.
   On **ok**: run `reanchor_pin` locally with the same envelope,
   the same captured `old_pin`, and the (still required)
   `ceremony_history` — the history checks stay as defence in depth;
   consume does not retire them — then adopt pin + record atomically
   (existing ATOMIC-ADOPTION).
3. On **any consume refusal** (`already_consumed`, `head_regression`,
   `not_issued`, `expired`, `invalid`, `ledger_failed`): **do not run
   `reanchor_pin`, do not adopt anything.** A refusal is terminal for
   this envelope.
4. On **transport loss** (timeout / `VerifierUnavailable` — the response
   never arrived): the consumption state is **UNKNOWN**. Retry consume
   once; if the retry says `already_consumed`, treat it as **"consumed
   by someone — possibly your own earlier attempt"** and **do not adopt
   the pin silently** (§7.1). Recovery is a new ceremony. This is the
   harshest rule in the design and it is deliberate.

### 2.8 Non-goals (stated so the build round does not invent them)

- **No signed receipt.** The receipt is unsigned, like `submit_claim`'s
  `{"claim_id", "claim_hash"}`. Signing it (HMAC under the gate key, or
  Ed25519 under the ceremony seed) would give `reanchor_pin` something
  to verify in-process — and that is exactly the temptation to refuse:
  a signature proves the verifier *said* the envelope was consumed, but
  the verifier says that only by reading its own journal, and the
  receipt's freshness cannot be verified in-process anyway (a replayed
  receipt from an earlier, different consumption of the same envelope
  would verify cleanly — the authorisation_id is the same). The
  protection is the journal + the caller contract, not a receipt
  signature. If a future cycle wants a queryable consumption proof, it
  should be a dedicated read mode with its own threat analysis, not a
  signature bolted onto this receipt.
- **No revocation.** Consume does not consult the operator allowlist and
  does not check any revocation list. An issued envelope is consumable
  until expiry or consumption, full stop.
- **No TTL extension.** Consume does not extend, refresh, or re-issue
  the envelope. An expired envelope is refused, and its recovery is a
  new ceremony.
- **No history retirement.** `ceremony_history` remains required in
  `reanchor_pin` (T5/T6 still pass in-process). Consume adds the
  authoritative layer; it does not remove the in-process layer.

---

## 3. D3 — The precise monotonic rules

### 3.1 The head

The **consumed head** `H` is the candidate of the **last** entry in the
consumption journal (append order = consumption order; the journal is
append-only and hash-chained, so "last" is well-defined):

- `H = None` when the journal is empty (bootstrap).
- Otherwise `H = (seq_H, hash_H)` from the last entry's
  `new_cycle_seq` / `new_payload_hash`.

The head is a **consumption** head, not a pin head: it names the highest
candidate ever consumed, and it is deliberately *not* the caller's live
pin (which may be ahead of it via `advance_pin`, or — in a
crash-after-consume — behind it).

### 3.2 The rules (M1–M5)

- **M1 — single-use.** `authorisation_id` ∈ consumption journal ∪
  signing-ledger consume entries → `ceremony_already_consumed`. No
  exception for identical re-presentation, no exception for "the first
  consume's response was lost" (§7.1). The verifier cannot distinguish a
  lost response from a replay, and single-use that makes exceptions for
  plausible stories is not single-use (the `ceremony_authorise`
  identical-re-presentation rule, reused).
- **M2 — issuance precondition.** `authorisation_id` ∉ issuance journal
  → `ceremony_not_issued`.
- **M3 — strict target monotonicity.** When `H` exists, the envelope's
  candidate `C` must satisfy `C.cycle_seq > seq_H`. Otherwise
  `ceremony_head_regression`:
  - `C.cycle_seq < seq_H` → regression (the T8 shape: consumed head seq 6,
    replay candidate seq 4).
  - `C.cycle_seq == seq_H, C.payload_hash != hash_H` → fork at the head
    (a different snapshot at the consumed sequence — a regression in
    disguise).
  - `C.cycle_seq == seq_H, C.payload_hash == hash_H` → **also refused.**
    There is no legitimate second consumption of the head target: the pin
    is already there, the caller should no-op, and admitting a
    same-target consumption under a fresh `authorisation_id` would let
    two distinct envelopes both "succeed" against one head and muddy the
    single-use accounting. The rule is stateable in one sentence —
    **"consumed targets are strictly increasing in `cycle_seq`"** — and
    that simplicity is a feature: it is the property the tests pin.
- **M4 — old_pin irrelevance.** The envelope's `old_pin` plays **no**
  role in M3. This is the rule the task explicitly demands, and the
  reasoning is:
  - `advance_pin` movements bypass the verifier entirely and leave no
    trace in any journal. The verifier *cannot know* the caller's live
    pin, so any rule of the form "old_pin must equal / be ahead of the
    head" would be a rule over a value the verifier cannot ground.
  - The legitimate case that breaks an old_pin-based rule: consume
    seq 1→4 (head = 4); caller advances the live pin 4→5→6 by
    `advance_pin` (head still 4, correctly — the head is a consumption
    head, not a pin head); a gap occurs; a new ceremony is issued with
    `old_pin` = seq 6, candidate seq 9. An old_pin-vs-head rule
    ("old_pin must be the head" or "old_pin must not exceed the head")
    refuses this legitimate ceremony. M3 admits it: 9 > 4. ✓
  - The converse case is also admitted and is safe: an envelope issued
    from `old_pin` seq 1 with candidate seq 9, consumed **after** a
    head of seq 4 exists (parallel issuance — two ceremonies issued from
    the same old pin under different ceremony ids/evidence). M3 admits
    it (9 > 4). The local `reanchor_pin` still enforces, exactly, that
    the envelope's `old_pin` equals the caller's *captured live pin* —
    so if the live pin is seq 6, an envelope bound to old_pin seq 1
    refuses locally. The two layers check different things against
    different state, and neither substitutes for the other.
- **M5 — reason-blindness.** M3 applies identically to all four reasons.
  A no-pin ceremony (`initial_anchor`, `lost_pin`, `corrupted_pin`) after
  any consumption must still strictly advance the head — in practice an
  `initial_anchor` after a consumption is refused unless its candidate
  is ahead of the head, which is the correct shape (a second "initial"
  anchor behind existing work is a regression, not an anchor).

### 3.3 Worked cases (each becomes a test, §8)

| Case | Head before | Envelope | Result |
|---|---|---|---|
| Bootstrap consume | None | seq 1→4 | ok, head = 4 |
| Second ceremony, ahead | 4 | old 4, cand 7 | ok, head = 7 |
| T7 replay (stale history) | 4 | same envelope, seq 1→4 | `ceremony_already_consumed` (M1) — **regardless of history**, because consume never reads history |
| T8 regression (stale history) | 6 (live pin 6, head 6 after a 4→6 ceremony… see note) | old envelope seq 1→4 | `ceremony_already_consumed` (M1 fires first; M3 would also fire: 4 < 6) |
| Fork at head | 7 | cand seq 7, different hash | `ceremony_head_regression` |
| Same target, new envelope | 7 | cand seq 7, same hash, new `authorisation_id` | `ceremony_head_regression` (M3, equal case) |
| Advance-bypass, legitimate | 4 (live pin advanced to 6) | old 6, cand 9 | ok (M4) |
| Parallel issuance, late consume | 4 | old 1, cand 9 | ok (M4) |
| Parallel issuance, regression | 9 (after the 9 consumed first) | old 1, cand 4 | `ceremony_head_regression` |
| Lost-pin after head | 4 | old None, cand 7 | ok |
| Lost-pin behind head | 7 | old None, cand 5 | `ceremony_head_regression` |

Note on the T8 row: in the integrated flow the head reaches 6 only if
the seq-6 state arrived via a *ceremony* (head = 6) or the live pin
advanced to 6 while the head stayed 4. In the latter case the replay
refuses on M1 alone — which is the point: M1 is the primary defence,
M3 is the defence in depth for *distinct* envelopes targeting behind
the head.

### 3.4 What the head is NOT

- Not the live pin (see M4). Do not "fix" the design by syncing the head
  to the caller's pin — that reintroduces caller-asserted state.
- Not a replacement for `reanchor_pin`'s binding checks. Consume
  verifies issuance + freshness + single-use + monotonicity. It does
  **not** verify the candidate against state/calibration bytes, does not
  recompute the strict verification, and does not check the evidence
  hash against anything but the envelope — all of that stays local.
- Not a liveness guarantee. A consumed-but-unadopted envelope (crash
  after commit, §4.1) leaves the pin behind the head; the head does not
  roll back to meet the pin. That asymmetry is deliberate (P3's safe
  direction).

---

## 4. D4 — Crash consistency: guarantees vs caller duties

### 4.1 What the mode guarantees

- **G1 — commit before response.** The consumption append is
  `fsync`ed (file, then directory, via `HashChainJournal._save`'s
  tmp-write → fsync → `os.replace` → dir-fsync) **before** any ok
  response is emitted. There is no code path that returns ok without
  the append.
- **G2 — atomic journal state.** Each append is a single atomic file
  replace. A crash mid-append leaves either the old journal or the new
  one, never a torn one. A leftover `*.tmp` file is ignored by `_load`
  (existing journal behaviour — pinned by a test for the new journal).
  A corrupt journal (bad JSON, broken chain, wrong keys) fails load,
  and consume refuses `ledger_failed` — it never proceeds from a
  partial view (P4).
- **G3 — commit ordering.** Consumption journal (commit) → signing
  ledger mirror → anchor update (§2.5). No successful pin movement can
  exist without the consumption record: the caller is forbidden from
  moving the pin before a consume ok (§4.2), and the mode never emits ok
  before the commit. The failure directions are all safe:
  - crash **before** the commit append → nothing consumed, envelope
    retryable (until TTL expiry).
  - crash **after** the commit, before the mirror → consumed, mirror
    missing (audit gap only; retry refuses already-consumed from the
    primary).
  - crash **after** the mirror, before the anchor → consumed, mirrored,
    anchor stale (staleness is not tampering; next update advances it).
  - crash **after** the response is emitted, before the caller adopts →
    consumed, pin unmoved. Safe direction (P3): the head is ahead of the
    pin, and the next legitimate ceremony must advance past it. Recovery
    is a new ceremony — the burn philosophy, stated in the mode
    docstring and in the caller contract.
- **G4 — no double-commit under concurrency.** The bounded-retry
  `append_consumption` (§2.6) plus `_save`'s under-flock freshness
  check give at-most-one consumption per `authorisation_id`, with the
  loser refused as `ceremony_already_consumed`, not spuriously failed.

### 4.2 What the caller must do (order of operations across the two processes)

The two-process protocol, in order — this is the contract seat C's
integration must implement and the E2E tests must drive:

```
caller:  envelope = client.ceremony_authorise(...)          # issuance (unchanged)
caller:  receipt  = client.ceremony_consume(envelope)       # (1) CONSUME FIRST
           on refusal  -> stop. Do not reanchor, do not adopt.
           on transport loss -> UNKNOWN; retry once; on
             already_consumed -> stop, do not adopt (§7.1).
caller:  (new_pin, record) = reanchor_pin(old_pin, cand,    # (2) LOCAL, pure
                            authorisation=envelope, ...)
caller:  adopt(new_pin, record) atomically                  # (3) ATOMIC-ADOPTION (existing)
```

Rules: consume-before-reanchor (never the reverse — a reanchor that
succeeds locally before the consume commits is exactly the P3
violation); adopt only on consume-ok **and** local success; never adopt
on a refusal; never re-run consume for an envelope whose receipt was
already received (a second consume is a second consumption attempt and
will — correctly — refuse).

### 4.3 How crash boundaries are tested (kill points)

The suite must test the boundaries, not assert them in prose (the
cycle-20 lesson: claims about concurrency must be probed, not read):

- **K1 — kill before append.** A test-only wrapper module (in
  `tests/`, importing `trust.verifier_main` and monkeypatching
  `CeremonyConsumptionLedger.append_consumption` to `os._exit(70)`
  *before* calling the real append) drives the mode in a subprocess;
  assert: process dies, journal length unchanged, envelope still
  consumable afterwards.
- **K2 — kill after append, before response.** Same wrapper, patching
  to append-then-`os._exit(70)` before `_emit`; assert: journal has
  exactly one consume entry, the envelope's next consume refuses
  `ceremony_already_consumed`, and the mirror entry is absent (the
  documented audit gap) — or present, if the patch point is after the
  mirror; the test pins the *ordered* outcome for its patch point.
- **K3 — response lost.** Client-level: call consume, discard the
  result (simulating a lost response — e.g. by killing the transport
  after the child exits, or simply by not reading the receipt), then
  retry consume; assert `ceremony_already_consumed` and assert the
  caller-side rule (no reanchor, no adoption) at the integration level
  — the E2E test must show the pin does **not** move on this path.
- **K4 — torn/corrupt journal.** Truncate the consumption journal
  mid-file / corrupt one entry's hash / delete it and leave the mirror:
  assert consume refuses `ledger_failed` (corrupt) or proceeds from an
  empty head with the mirror still refusing replays of already-mirrored
  envelopes (deleted journal — the mirror cross-check is what saves
  P1 here; pin this).
- **K5 — concurrent consume race.** Two-process barrier probe (the
  cycle-20 `append_authorisation` regression pattern): two processes
  consume the same envelope simultaneously; assert exactly one ok and
  one `ceremony_already_consumed` (not `ledger_failed`), and exactly
  one consumption entry.
- **K6 — crash between commit and mirror.** Fault injection at the
  ledger level: patch `SigningLedger.append_ceremony_consumption` to
  raise after the primary append; assert `ledger_failed`, receipt
  withheld, envelope still refuses as already-consumed on retry, and
  the primary entry exists without a mirror entry (the visible audit
  gap).

No new env var is used as a fault-injection hook (§5 — the hooks are
test-module monkeypatches, not production surface).

### 4.4 D7 — Anchoring decision for the consumption journal: NOT this cycle

**Decision: the consumption journal is NOT anchored via
`trust/anchoring.py` in cycle 21. The residual is named, not hidden —
the same treatment the ceremony authorisation journal already carries.**

Reasons, in order of weight:

1. **The single-use leg — GPT's blocking condition — is already
   anchored via the mirror.** GPT's cycles 14–16 condition is
   "duplicate consumption fails with no/stale history". With the §2.5
   mirror, every consumption fact (`authorisation_id`, `payload_hash`,
   `ceremony_id`, timestamp) lands in the signing ledger, which **is**
   externally anchored in production (`AION_ANCHOR_PATH` is mandatory
   there, and `_update_anchor` runs after the mirror append). A
   rolled-back consumption journal therefore does **not** resurrect a
   consumed envelope: the mirror cross-check (§2.3 step 5) still
   refuses it. The property the external gate actually demands does
   not depend on anchoring the new journal.
2. **Anchoring is not a small change.** `trust/anchoring.py`'s
   `ANCHOR_KINDS` is a closed set (`"signing"`, `"ship"`, `"ship-tx"`)
   with an exact anchor format. A `"ceremony-consumption"` kind means:
   a new anchor path (a **new env var** — breaking D5's zero-new-var
   win and churning all five allowlist copies), a production-mandatory
   decision for that anchor (optional anchoring is decoration;
   mandatory anchoring is a deployment migration), startup
   verification wiring in `_load_config`, and per-append anchor
   updates. That is a cycle of its own, and it applies identically to
   the ceremony journal — doing it for one journal and not the other
   would be incoherent.
3. **Precedent.** The ceremony journal shipped in cycles 19–20
   unanchored with the named follow-up `ceremony-journal-anchoring`
   and an honest residual statement in its docstring. The consumption
   journal follows the same pattern, with a **joint** follow-up:
   `ceremony-journal-anchoring` is extended to cover both
   verifier-home ceremony journals under one anchor design (one kind
   decision, one placement decision, one migration).

**The residual, stated precisely (this wording, or its equivalent,
goes in `CeremonyConsumptionLedger`'s docstring):** the consumption
journal is not externally anchored. Rolling it back **cannot**
resurrect a consumed envelope (the anchored signing-ledger mirror
still refuses it) and **cannot** hide that a consumption happened.
Rolling it back **can** lower the enforced head: after a rollback to
before head H2, target monotonicity (M3) is enforced only from the
rolled-back head, so a *never-consumed* envelope whose candidate sits
between the rolled-back head and H2 would be admitted by consume even
though the system once consumed past it. That envelope still has to
pass `reanchor_pin`'s local binding against the caller's live pin, so
the exploitable window is narrow — but it is a window, and it is why
the joint anchoring follow-up exists. In research mode (anchoring
unconfigured) the mirror itself is unanchored and the residual widens
to the ceremony journal's existing research-mode statement: journals
can be deleted or rolled back undetectably, and research mode must
never be described as rollback-protected.

---

## 5. D5 — Config / startup changes

### 5.1 Decision: zero new env vars

The consumption journal lives under `AION_VERIFIER_HOME`. That variable
is already **required** at startup, already in the wrapper allowlist,
and already the home of the two sibling journals. **No new env var is
introduced by this cycle for the consumption head.** Consequences:

- The deploy wrapper allowlist stays at **17 names** in all five copies
  (the task names five: `deploy/verifier-identity/run-verifier.sh`,
  `deploy/verifier-identity/health_check.py`'s allowlist, the
  `setup.sh` template, `trust/wiring.py`'s env-var inventory, and the
  tests that pin the allowlist — `tests/test_verifier_deploy.py`,
  `tests/test_trust_production_deploy.py`, `tests/test_trust_wiring.py`).
  A build-round change that adds an env var here is a design violation,
  not a detail: the existing tests (`test_every_verifier_main_env_var_
  is_allowlisted`, `test_allowlist_is_the_shipped_17_names`) will catch
  it, and the correct response is to remove the var, not to bump the
  count.
- `_Config` gains **no field** for the consumption journal (a derived
  property `consumption home == home` is the most that is needed, and
  even that is optional — the mode can construct
  `CeremonyConsumptionLedger(config.home)` directly, as
  `ceremony_authorise` constructs `CeremonyAuthorisationLedger(
  config.home)`).
- **Startup behaviour is unchanged** for the consumption journal: it is
  opened lazily, per consume call, like the ceremony journal. A missing
  file is an empty journal (genesis head) — the correct bootstrap.
  A corrupt file is a per-request `ledger_failed`, not a startup
  refusal — consistent with the ceremony journal, which is also not
  pre-opened at startup. (Pre-opening one journal and not the other
  would be an inconsistency with no security gain: a corrupt consumption
  journal blocks only consume, and consume is the only mode that needs
  it.)
- The only `_load_config` changes this cycle are the workstream-A
  derivation-overlap relations (§6.3) — which are checks over secrets
  already loaded, not new configuration.

### 5.2 Deploy / wiring consequences

- `deploy/verifier-identity/README.md`: one paragraph — the verifier
  home now also holds `ceremony-consumptions.json`; the consumption
  journal is verifier-owned, created lazily, and must be backed up /
  restored **together** with `ceremony-authorisations.json` and
  `signing-ledger.json` (restoring one without the others is the
  rollback scenario of §4 — name it in the README so an operator does
  not "fix" a disk problem by restoring a single file).
- `health_check.py`: no allowlist change; a health-check *observation*
  (not a gate) may note whether `ceremony-consumptions.json` exists —
  optional, and explicitly not a refusal (an empty/absent journal is a
  valid bootstrap state).
- No `AION_CONSUMPTION_*` variable, no `AION_ANCHOR_*` variable for
  consumption (§4.4).

---

## 6. D6 — Workstream A: Ed25519 differential validation + seed hygiene

### 6.1 Differential suite composition

**New file: `tests/test_signing_ed25519_differential.py`** (separate from
`tests/test_signing_ed25519.py`, so the core RFC/negative/oracle suite
stays small and the differential suite can carry its own skip logic and
runtime budget). **No production change to `signing/ed25519.py` is
planned** — the suite is a validation instrument. Any failure it finds
is a *finding* for the war room, not a silent fix: the strict profile
(R2) is pinned, and a differential failure means either the profile or
the implementation is wrong, and the room decides which.

**Layer 1 — RFC 8032 KATs (full).** The existing file has TEST 1–3 for
keygen/sign/verify. The differential file adds the RFC §7.1 **1024-byte
message** vector (TEST 4 in the RFC numbering, the long-message case)
and re-asserts TEST 1–3 through the *differential* harness (ours vs
openssl, §6.1 layer 3), not by duplicating the unit assertions. Vector
literals are copied with their RFC section citation in a comment; a
drift test is unnecessary here (they are constants, not derived), but
each literal carries its source line.

**Layer 2 — Wycheproof-style adversarial cases.** Ported by hand from
the Wycheproof `eddsa_test.json` vector set and the C2SP ed25519 test
vectors (each entry annotated with source + the strict-profile reason
it must fail by). The composition, with the existing cycle-20 coverage
noted so the build round does not duplicate it:

| Group | Cases | Expected (our `verify`) | Already in `test_signing_ed25519.py`? |
|---|---|---|---|
| Non-canonical R | `y == p`, `y == p + 1` spellings of R; R with the sign bit flipped on a non-canonical y | `False` (canonical-decode step) | Partial (non-canonical identity spelling) — add the R-side cases |
| Non-canonical A | `y == p` spelling of A; A = `q - 1` encodings | `False` | No — new |
| S boundary | `S = L - 1` (with an honest R — must be `False` by the equation, not by the range check), `S = L`, `S = L + 1`, `S = 2^256 - 1` | `False` | Partial (`S = L`, `L + 1` exist) — add `L - 1` and `2^256 - 1` |
| Small-order A | All 8 small-order encodings as A, with S chosen to satisfy the cofactorless equation where constructible (the equation-satisfying constructions from the cycle-20 vectors) | `False` (blocklist step, before the equation) | Partial (identity/order-2 A) — complete to all 8 |
| Small-order R | All 8 as R, with S chosen to satisfy the equation where constructible | `False` | Partial — complete to all 8 |
| Mixed torsion | A = prime-order point + torsion component; R = prime-order + torsion component (the cycle-20 mixed-torsion constructions, ported) | `False` | Yes (2 vectors) — port into the differential table so the oracle comparison covers them |
| Bit-flips | **Exhaustive single-bit flips**: every bit of every byte of the 64-byte signature (512 cases) and every bit of every byte of the 32-byte public key (256 cases), on one RFC vector (TEST 1, empty message) | `False` for every flip | Partial (4 single flips) — the exhaustive sweep is the new content. Runtime: ~768 verifies at the cycle-20 measured 6.4 ms median / 29.9 ms p95 on this shared-CPU VM ≈ 5–23 s; acceptable for this file, and the file's docstring must record the measured time. If the build round measures >60 s, it may subsample the pubkey flips deterministically (seeded) — but only with the subsampling recorded in the test, never silently. |
| Message flips | Single-bit flips of a 32-byte message, and the empty→1-byte boundary | `False` | Partial — extend to the full 32-byte sweep (256 cases) |

Every case in the table is a `(name, public_key, message, signature,
expected_ours)` row in one literal table, driven by one loop with
`subTest`, so adding a vector is one row, not one test.

**Layer 3 — OpenSSL cross-implementation agreement.** `openssl 3.0.13`
is present on this VM (`openssl version` verified during design).
Mechanics, stdlib only:

- Keys: build PKCS#8 DER for a seed with the fixed prefix
  `302e020100300506032b657004220420 || seed` and SPKI DER for a public
  key with prefix `302a300506032b6570032100 || pubkey`; write to
  `tempfile.TemporaryDirectory` files (never the repo, never the
  verifier home).
- Commands: `openssl pkey -pubin -inform DER` / `openssl pkeyutl
  -verify -pubin -inkey <der> -rawin -in <msg> -sigfile <sig>` and the
  sign direction `openssl pkeyutl -sign -rawin -inkey <der> -in <msg>`
  (Ed25519 is deterministic, so openssl's signature must be
  **byte-equal** to ours on the same seed+message — assert equality,
  not just verify-agreement, on the valid corpus).
- Corpus: RFC vectors (all, incl. the 1024-byte message) + 32 seeded-
  random (seeded `random.Random(0xC21E)` — deterministic) key/message
  pairs.
- Skip discipline: `shutil.which("openssl") is None` → `skipTest`
  (clean skip, not a failure); `openssl version` unparseable → skip;
  any openssl invocation failing on the *valid* corpus is a test
  failure, not a skip (the tool is present and must work).

**The crucial position — partitioned agreement, not identical
semantics.** OpenSSL's Ed25519 verification is not the R2 strict
profile: it is an RFC 8032 verifier with its own choices on
cofactored/torsion edge cases (ZIP-215-style leniency on some
non-canonical and small-order inputs is the known divergence class).
Asserting byte-for-byte agreement on the adversarial corpus would
either red the suite on a legitimate semantic difference or force the
profile to match OpenSSL's leniency. The table is therefore
**partitioned**, and the partition is itself the design:

- **MUST-AGREE set** (valid signatures, bit-flips, wrong message,
  `S >= L`, `S = L - 1` forgeries): both implementations must agree
  (accept the valid, reject the invalid). Any disagreement here is a
  finding.
- **KNOWN-DIVERGENCE set** (small-order A/R with equation-satisfying S,
  non-canonical `y >= p` encodings, mixed torsion): assert **only**
  that our `verify` returns `False`; record openssl's answer (in the
  test output via `subTest` context, not asserted). If openssl also
  rejects, the test notes the agreement in a comment on the next run —
  but the build round must **not** silently promote a divergence row
  into the must-agree set without a war-room note, because the
  promotion would make the suite depend on an OpenSSL version's
  leniency choices.

This partition is the honest answer to "cross-implementation agreement":
agreement where the semantics are shared, and a named, recorded
divergence where they are not — with our strict profile as the
authority for the ceremony, never OpenSSL.

### 6.2 Seed hygiene at verifier startup

**Position on the permission semantics.** The task says "owner-only
perms (0600 or stricter)". The existing loader (`load_ceremony_seed`)
demands **exactly 0600**. I take: **keep exactly-0600 for the seed
file, and make the *check itself* the thing that gets stricter** — for
three reasons: (1) exactly-0600 is the established discipline shared
with `load_signing_key` (`gate_decision.py`); two sibling loaders with
two permission policies is a drift surface, and a 0400 seed is a
provisioning oddity the operator fixes with `chmod`, not a use case to
support; (2) "or stricter" is already discharged by the *directory*
discipline (`_check_key_path` refuses a group/world-writable parent
directory, and the deploy identity runs the keys directory at 0700);
(3) relaxing to "any owner-only mode" would silently accept a
write-only (0200) seed file that the loader then cannot read — a
confusing failure. The decision is pinned by a test asserting 0400
**refuses** (with a comment naming this decision), so a future
relaxation is a deliberate, visible change.

**What actually changes — the loader becomes fd-based** (the gap is not
the mode number, it is check-then-use):

Current `load_ceremony_seed` (and `load_signing_key`) do:
`_check_key_path` (symlink-component refusal) → `target.is_file()` →
`target.stat().st_mode` → `target.read_bytes()`. Between the `stat`
and the `read` there is a TOCTOU window, and the `is_file` check
follows the path it just refused symlinks on — correct in the common
case, fragile in the adversarial one (a FIFO at the path: `is_file`
is False, so it refuses — but only after the check; a swap between
check and read is the named gap).

New `load_ceremony_seed` (this cycle; `load_signing_key` is the same
pattern as a **follow-up, not widened in this cycle** — the HMAC key
loader is shared by every gate path and its change surface is larger):

1. `_check_key_path` unchanged (symlink components, forbidden roots,
   group/world-writable parent).
2. Open with `os.open(path, os.O_RDONLY | os.O_NOFOLLOW |
   os.O_NONBLOCK)` — `O_NOFOLLOW` refuses a symlinked leaf at open
   time (not just at check time); `O_NONBLOCK` means a FIFO leaf
   **cannot hang the verifier** (the cycle-20 FIFO hang lesson, applied
   to the seed path: a FIFO evidence leaf hung the verifier before
   `O_NONBLOCK` was added; a FIFO seed would do the same at startup).
3. `fstat` the **fd** (not the path): refuse unless `S_ISREG` (regular
   file — directory, FIFO, socket, device all refuse), `st_mode &
   0o777 == 0o600` (exactly-0600, per the position above), and
   `st_uid == os.geteuid()` (owner-only in the ownership sense, not
   just the mode-bits sense — the verifier runs as a dedicated OS user,
   and a seed owned by another uid is a misprovisioning even if its
   mode bits look right; `geteuid() == 0` skips the uid check, since
   root reads anything — record that carve-out in the docstring).
4. Read from the fd (size cap 1024 bytes, as now), then the existing
   hex/32-byte validation unchanged.

**Where the checks live.** In `signing/ceremony_authorisation.py`
(`load_ceremony_seed`), **not** in `verifier_main.py`: the loader is
the single discipline point, and `_load_config` already maps any
`SigningError` from it to a startup refusal (`verifier_misconfigured`,
both modes — present-but-unloadable refuses startup in both modes,
cycle 20). The verifier-main side of seed hygiene is only §6.3.

**Tests** (in `tests/test_signing_ceremony_authorisation.py`, loader
tests): 0640 / 0660 / 0604 / 0000 refuse; 0400 refuses (the pinned
decision); symlink leaf refuses; FIFO refuses **without hanging**
(the test asserts it returns promptly — this is the K-style test for
the loader); directory-as-seed refuses; non-regular device refuses
(`/dev/null` — regular-file check, not a read); wrong-owner refuses
(skip unless the test can `chown` — i.e. skip when running as root or
without privilege, with the skip reason recorded); oversize / odd-hex /
uppercase-hex refuse (existing behaviour, re-pinned through the new
fd path).

### 6.3 Derivation-overlap checks vs the HMAC key

**Placement: `_load_config`, immediately after the existing
byte-equality check** — the only place both secrets exist (the module
docstring's own rationale for the byte-equality check: "the only places
both secrets exist"). The loader cannot do it (it never sees the HMAC
key); no other site can.

**Current checks (kept):** `seed == signing_key.key` refuses startup;
`seed ∈ REFUSED_TEST_SEEDS` refuses startup.

**New relations (all four, all startup refusals in both modes, detail
strings naming neither value — the existing discipline):**

| # | Relation refused | Why it matters (not just byte-equality) |
|---|---|---|
| R1 | `seed == sha256(signing_key.key)` | The ceremony seed is the hash of the HMAC key. Anyone who learns the HMAC key (or vice versa — see R2) derives the other. A single-secret compromise becomes a both-secrets compromise. |
| R2 | `signing_key.key == sha256(seed)` | The reverse derivation: the HMAC key is the hash of the ceremony seed. Same compromise propagation, opposite direction. "sha256 both directions" is exactly R1+R2. |
| R3 | `signing_key.key == ceremony_public_key` (i.e. the HMAC key bytes equal `public_key_from_seed(seed)`) | **Public material used as a secret.** The ceremony public key is published (pinned by every ceremony caller). If it is also the HMAC key, the gate signatures are forgeable by anyone holding the pin. This is not a derivation — it is a reuse across the public/secret boundary, and it is the most dangerous relation in the table because it is the easiest to commit by accident (copy-paste the public key into the gate key file). |
| R4 | `seed == sha256(ceremony_public_key)` | The seed is the hash of its own public key. Contrived, but it closes the self-derivation loop an operator might construct when generating material from one value; cheap to check (one more hash), and refusing it costs nothing. |

Implementation: `hashlib` is already imported in `verifier_main.py`.
Compute `sha256(seed)`, `sha256(signing_key.key)` once, compare against
the four relations. **Named limit:** these checks cover direct
sha256-derivation in both directions and the public-as-secret reuse.
They cannot cover KDF-derived overlap (PBKDF2/HKDF/scrypt with unknown
parameters, or a seed derived from the key by any other function) —
that is a provisioning discipline matter, and the docstring must say
so rather than imply general "no derivation" coverage. The checks also
do not cover the HMAC key vs `REFUSED_TEST_SEEDS` (that list is
ceremony seeds; the HMAC key has its own `_REFUSED_TEST_KEYS` list —
kept separate, as now).

**Tests** (in `tests/test_trust_ceremony_mode.py`, config tests):
startup refusal for each of R1–R4 (provision a seed file whose hex is
`sha256(key)`, a key file whose hex is `sha256(seed)`, a key file whose
hex is the ceremony public key, and a seed whose hex is
`sha256(public_key)`), in **both** modes where applicable (production
already refuses missing seed; the overlap refusals must fire in
research too), plus a control (unrelated seed + key passes) and a
drift-style assertion that the relation list in the test matches the
relations in `_load_config` by behaviour (one test per relation is the
drift protection — there is no list to compare, so the tests *are*
the list).

---

## 7. Risks, weakest points, and what this design does not do

### 7.1 Weakest point #1 — the response-lost ambiguity (named, not hidden)

`ceremony_consume` is burn-before-use, and a caller whose ok response
is lost (timeout, crash, killed transport) cannot distinguish "my
consume landed" from "someone else consumed it". The strict rule (§2.7
step 4) converts a transport hiccup into a full new ceremony — new
`ceremony_id`, new evidence bundle — which is a real liveness cost in
exactly the recovery flow where ceremonies are already expensive. The
alternatives were considered and rejected *for this cycle*: a signed
receipt does not solve attribution (a replayed receipt verifies — §2.8);
a read-only `ceremony_consumption_status` query mode would let the
caller see *that* the envelope was consumed and *when*, but not *by
whom*, so it resolves the ambiguity only by reintroducing trust in a
timestamp correlation. A status mode is the right follow-up if the
loop/storage caller turns out to hit lost responses in practice — with
its own threat analysis, not smuggled into this cycle.

### 7.2 Weakest point #2 — the head is a system property, not a library property

A caller that skips `VerifierClient.ceremony_consume` and calls
`reanchor_pin` directly gets **no** protection from this cycle:
T7/T8 as written (in-process, `reanchor_pin` alone) still succeed
until seat C's integration changes the call path. The protection exists
only in the integrated flow (verifier consume → local reanchor →
atomic adopt). If the war room wants library-level enforcement, the
honest options are: (a) a consumption-receipt parameter on
`reanchor_pin` — but an unsigned receipt is forgeable in-process, so
that gate would be theatre, and this design says so rather than
recommending it; (b) moving `reanchor_pin` behind the verifier (a
verifier mode that performs the re-anchor) — a much larger redesign,
out of this cycle's scope, and one that would need its own design
round. The residual is therefore: **the guarantee holds for callers
that follow the contract, and is unenforced for callers that bypass
it** — exactly the same shape as the existing FRESH-PIN /
COMPLETE-HISTORY / ATOMIC-ADOPTION preconditions, which are also
caller obligations the function cannot verify. The design keeps that
shape explicit rather than pretending a local check fixes it.

### 7.3 Weakest point #3 — dual-journal disagreement states

Two journals mean four combinations of (primary, mirror) for each
envelope, and the authority order (primary = head authority, mirror =
single-use backstop, any mirror hit refuses) must be held in every
future reader's head. The mitigation is the ordering rules in §2.5/§2.6
and the K4/K6 tests — but the complexity is real, and it is the price
of getting an anchored single-use trace without a format migration.
If the joint anchoring follow-up (§4.4) lands, the mirror may become
redundant and should be *removed* then, not left as a second source of
truth.

### 7.4 Other risks

- **Flock serialisation (§1.4):** all verifier-home journals share one
  directory lock. Under sustained concurrent ceremony traffic, consume
  and authorise serialise; the bounded retry converts contention into
  latency, not failure — but the retry bound (8) is an engineering
  margin, not a proof (the `ShipLedger.burn` docstring says the same
  about its bound). A sustained-contention load test is a build-round
  measurement, not a design claim.
- **OpenSSL divergence partition (§6.1):** the MUST-AGREE /
  KNOWN-DIVERGENCE split rests on my reading of OpenSSL 3.0.13's
  Ed25519 leniency. If the build round finds openssl rejects *all*
  curated invalids, rows may be promoted — only with a war-room note
  recording the observed outputs, never silently.
- **Seed loader fd rework (§6.2):** `O_NONBLOCK` on a regular file is
  a no-op on Linux, and `O_NOFOLLOW` on the leaf is the point — but
  the rework touches the loader every ceremony path depends on. The
  existing loader tests must all pass unchanged, and the new tests
  must include the FIFO-no-hang case, or the rework has not earned
  its keep.
- **Head rule strictness (M3 equal case):** refusing a same-target
  second envelope could surprise a caller that re-issues a ceremony
  for an already-adopted target as a "confirmation". That caller is
  wrong (the pin is already there; the correct operation is a no-op),
  but the refusal message must say so plainly — the detail string
  should name the head sequence and the candidate sequence so an
  operator can see it is a no-op refusal, not a corruption signal.
- **Same-user attacker (prototype threat model):** a fully malicious
  same-OS-user process can rewrite the consumption journal *and* the
  signing ledger *and* the anchor. The mirror (§2.5) raises the bar
  from one file to three coordinated rewrites under an anchored check,
  and the joint anchoring follow-up (§4.4) is the real answer. This
  design does not claim to stop that attacker — `verifier_main.py`'s
  prototype honesty statement already records the limit.

---

## 8. File-level change list

### Workstream B (lead)

| File | Change |
|---|---|
| `trust/ledger.py` | New `CeremonyConsumptionLedger` (`FILENAME =
  "ceremony-consumptions.json"`, `EXTRA_KEYS` per §2.5,
  `append_consumption` with bounded retry + in-method duplicate and
  head re-checks, `consumed_head()`, `is_consumed()`); new
  `SigningLedger.append_ceremony_consumption` (column reuse, no
  `EXTRA_KEYS` change); new `CeremonyAuthorisationLedger.
  find_by_authorisation_id`. Docstrings carry the commit-point and
  authority-order statements. |
| `trust/verifier_main.py` | New `_mode_ceremony_consume` (§2.3 order, §2.4 codes, §2.5
  commit); `_MODES` entry; `_CONSUME_BODY_KEYS`; module-docstring
  updates (mode list, honest limits: consumption head, receipt
  unsigned, response-lost rule); the `_load_config` overlap
  relations (§6.3) are the only config change. |
| `trust/protocol.py` | Add `"ceremony_consume"` to `MODES`. |
| `trust/client.py` | `VerifierClient.ceremony_consume(envelope_dict) -> receipt`
  (§2.7); docstring carries the unsigned-receipt and
  do-not-adopt-on-refusal rules. |
| `signing/pin_ceremony.py` | **Seat C's file — coordination only from this design:**
  docstring update (consumption contract: consume-before-reanchor;
  T7/T8 status at the integrated level); the caller-precondition
  list gains a fifth entry (CONSUME-FIRST). No signature change
  proposed by this seat. |
| `deploy/verifier-identity/README.md` | One paragraph: `ceremony-consumptions.json` in the verifier
  home; restore-all-three-journals-together rule. No allowlist
  change. |
| `tests/test_trust_ceremony_consume.py` | **New file** — the consume-mode suite (§8.1). |
| `tests/test_trust_ceremony_mode.py` | Additions only where a mode test must see consume: the
  startup overlap refusals (§6.3) live here; consume-specific
  tests live in the new file. |
| `tests/test_signing_pin_ceremony.py` | **Seat C's file.** This design's expectation: T7/T8 are
  *replaced* at the integrated level (new E2E tests in
  `test_trust_ceremony_consume.py` drive authorise → consume →
  reanchor → advance → replay-consume-refuses); the in-process
  T7/T8 tests are either re-pinned as "in-process function alone,
  without the consume step" (documented residual, §7.2) or
  removed by seat C with the removal recorded — not silently
  flipped, and not left asserting the regressed pin as if it were
  still the system's behaviour. |

### Workstream A

| File | Change |
|---|---|
| `tests/test_signing_ed25519_differential.py` | **New file** — RFC KATs (incl. 1024-byte message), the
  Wycheproof-style table (§6.1 layer 2), the exhaustive bit-flip
  sweeps, the OpenSSL cross-check with the partitioned oracle and
  clean skip-when-absent. |
| `signing/ceremony_authorisation.py` | `load_ceremony_seed` fd-based rework (§6.2). No API change. |
| `trust/verifier_main.py` (`_load_config`) | R1–R4 derivation-overlap refusals (§6.3). |
| `tests/test_signing_ceremony_authorisation.py` | Loader hygiene tests (§6.2): perms, symlink, FIFO-no-hang,
  directory, device, owner, 0400-refuses (pinned decision). |
| `tests/test_trust_ceremony_mode.py` | Startup overlap-refusal tests R1–R4 + control (§6.3). |
| `signing/ed25519.py` | **No change planned.** Any differential failure is a finding
  for the war room. |

### Explicitly NOT changed this cycle

- `trust/anchoring.py` (no new anchor kind — §4.4).
- Any deploy wrapper allowlist (17 names stand — §5).
- `signing/pin_ceremony.py` code (seat C).
- Cycles 14–16 (not re-reviewed).
- No env var, no eval/ change, no GitHub push.

---

## 8.1 Test list — consume mode (`tests/test_trust_ceremony_consume.py`, new)

Happy path and refusals (each drives the real mode through
`VerifierClient` + subprocess, on the ceremony fixture pattern of
`test_trust_ceremony_mode.py`):

1. **C1** happy path: authorise → consume → receipt shape
   (`authorisation_id`, `ceremony_id`, `new_pin`, `consumed_at`,
   `consumption_seq`, `consumption_head`); consumption journal has
   exactly one entry with the §2.5 fields; signing ledger has exactly
   one mirror entry (`kind="consume"`, `format="ceremony-consumption"`).
2. **C2** T7-flip (integrated): consume once, then re-present the same
   envelope through consume with a stale/empty history — refuses
   `ceremony_already_consumed` (exit 3); pin unchanged. (The history
   is not even a body field — the test's point is that no history
   value can change the answer.)
3. **C3** T8-flip (integrated): consume seq 1→4, reanchor + adopt,
   advance live pin to 6, replay the original envelope through
   consume — refuses `ceremony_already_consumed`; then a *distinct*
   envelope targeting seq 4 (new ceremony id/evidence, candidate
   seq 4) refuses `ceremony_head_regression` after the head reaches
   6 via a second ceremony — the M3 leg, isolated from M1.
4. **C4** fork at head: candidate seq == head seq, different hash →
   `ceremony_head_regression`.
5. **C5** same target, new envelope: candidate == head exactly →
   `ceremony_head_regression` (M3 equal case, pinned).
6. **C6** advance-bypass legitimate: head 4, live pin advanced to 6,
   new envelope old 6 / candidate 9 → ok (M4).
7. **C7** parallel issuance: two envelopes from old pin 1 (candidates
   4 and 9); consume 9 first, then 4 → `ceremony_head_regression`;
   consume 4 first, then 9 → ok (M4, both orders tested).
8. **C8** no-pin reasons: `lost_pin` candidate ahead of head → ok;
   behind head → `ceremony_head_regression`; `initial_anchor` after
   a consumption with a behind-head candidate → refuses.
9. **C9** never-issued: a validly signed envelope whose
   `authorisation_id` is absent from the issuance journal (construct
   by signing directly with the test seed, bypassing the mode) →
   `ceremony_not_issued`.
10. **C10** forged / tampered envelope: bit-flipped signature,
    wrong signer id, v1 envelope → `ceremony_authorisation_invalid`
    (exit 2); expired envelope → `ceremony_authorisation_expired`
    (exit 3). One code for all non-temporal invalids (the oracle
    rule, §2.4).
11. **C11** malformed bodies: missing/extra keys, envelope as a raw
    string, envelope with wrong key set → `malformed_request`
    (exit 2), journals untouched.
12. **C12** unconfigured seed (research): consume refuses
    `ceremony_seed_unconfigured` before touching any journal.
13. **C13** journal unreadable: corrupt the consumption journal
    (bad JSON / broken chain) → `ledger_failed`; corrupt the
    issuance journal → `ledger_failed`; delete the consumption
    journal while the mirror survives → a replay of the mirrored
    envelope still refuses `ceremony_already_consumed` (K4).
14. **C14** post-commit mirror failure (K6): patch the mirror append
    to raise → `ledger_failed`, receipt withheld, retry refuses
    already-consumed, primary entry present without mirror entry.
15. **C15** concurrent consume (K5): two-process barrier, same
    envelope → exactly one ok, one `ceremony_already_consumed`
    (never `ledger_failed`), exactly one consumption entry.
16. **C16** kill points K1/K2: wrapper-module subprocess kills
    (before append / after append before response) with the
    ordered outcomes of §4.3.
17. **C17** response-lost (K3): consume, discard receipt, retry →
    `ceremony_already_consumed`; integration test asserts the pin
    does not move on this path.
18. **C18** anchor advances: with `AION_ANCHOR_PATH` configured,
    a consume advances the signing anchor over the mirror entry
    (verify via `verify_anchor`); a stale anchor after a
    consume-without-anchor-update is still a valid prefix.
19. **C19** E2E integrated flow: authorise → consume → `reanchor_pin`
    → adopt → advance → second ceremony → consume → reanchor → adopt;
    final pin is the second ceremony's candidate; every intermediate
    refusal in the sequence is asserted absent. (This is the test
    that replaces T7/T8's executable meaning.)
20. **C20** deploy invariant: the shipped 17-name allowlist is
    unchanged and a consume works end-to-end under the wrapper env
    (extends `test_verifier_deploy.py`'s pattern; fails if any new
    env var is introduced).

### Test list — workstream A

- Differential (`tests/test_signing_ed25519_differential.py`): RFC
  KATs incl. 1024-byte message (ours + openssl); the Wycheproof-style
  table (~60 rows, one loop, `subTest`); exhaustive signature bit-flips
  (512) + pubkey bit-flips (256) + message bit-flips (256); openssl
  agreement on the MUST-AGREE set (valid corpus byte-equal signatures
  both directions, 32 seeded-random cases); KNOWN-DIVERGENCE rows
  asserting only our rejection with openssl's answer recorded;
  clean `skipTest` when openssl is absent (forced by hiding it from
  `PATH` in one test).
- Seed hygiene (`tests/test_signing_ceremony_authorisation.py` +
  `tests/test_trust_ceremony_mode.py`): per §6.2/§6.3 — perms matrix,
  symlink, FIFO-no-hang, directory, device, owner, 0400-refuses,
  R1–R4 startup refusals in both modes, unrelated-seed control.

---

## 9. Decision log for the war room (vote these)

1. **Store location (D1):** new `ceremony-consumptions.json` in the
   verifier home. (Alternatives A1–A6 weighed in §1.2.)
2. **Body shape (D2):** exactly `{"signed_authorisation"}` — no
   `current_pin`, no history field.
3. **Dual append (D2):** consumption journal is the commit; signing
   ledger mirror is audit. (Alternative: single journal only — loses
   the anchored single-use trace.)
4. **M3 equal case:** a same-target second envelope refuses
   `ceremony_head_regression`.
5. **M4:** `old_pin` plays no role in the head rule.
6. **Response-lost rule (§2.7 step 4):** strict — never adopt on a
   retry `already_consumed` after a lost response.
7. **Anchoring (D7):** not this cycle; joint follow-up with the
   ceremony journal.
8. **Seed perms (§6.2):** exactly-0600 kept; 0400 refuses (pinned).
9. **Differential oracle (§6.1):** partitioned (MUST-AGREE vs
   KNOWN-DIVERGENCE), our strict profile authoritative.
10. **Overlap relations (§6.3):** R1–R4 as listed; KDF-general coverage
    explicitly not claimed.

---

## 10. Open questions for the coordinator / seat C (not decisions deferred to the owner)

- **Q1 (seat C):** Does `reanchor_pin` gain any consume-awareness in
  code, or does the integration live entirely in the caller (loop/
  storage layer) with `reanchor_pin` unchanged? This design's position
  is caller-only + a fifth caller precondition (CONSUME-FIRST), with
  the §7.2 residual stated — seat C may disagree, but a receipt
  parameter must survive the "unsigned receipt is forgeable
  in-process" objection in §2.8.
- **Q2 (coordinator):** The T7/T8 in-process tests — re-pin as
  documented residual, or remove? Removal must be recorded, not
  silent (§8, `test_signing_pin_ceremony.py` row).
- **Q3 (coordinator):** Is the joint anchoring follow-up
  (`ceremony-journal-anchoring` + `consumption-journal-anchoring`)
  a cycle-22 candidate, or does it wait for the cycles 14–16
  re-review to demand it? This design's position: the mirror makes
  it non-blocking for 14–16 (single-use is anchored; only
  head-regression-after-rollback is residual).
- **Q4 (build round):** Measure the exhaustive bit-flip sweep's
  runtime on the build VM and record it; the design budget is
  ~5–23 s (§6.1) — if it exceeds 60 s, subsample deterministically
  with the subsampling recorded.
