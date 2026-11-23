# Design — cycle 21, seat C (ceremony-side integration lead)

Date: 2026-11-23. Mandate: internal/CROSS-CHECK-14.md (external
reconciliation of cycle 20). Design only — no code edited this
round. Cycles 14–16 are NOT re-reviewed this cycle; no GitHub
push.

Cycle 20 shipped internally (PROVISIONAL) with the consumption
gate open: duplicate consumption fails on omitted history (T5)
and on updated history (T6), but with a stale or honestly-empty
history the same envelope consumed twice within its TTL still
succeeds and can regress a since-moved pin — pinned executably
by T7/T8, which assert the regressed pin value. Seat-gpt's FIX
0.96 is BLOCKING: that is an active defect in the integrated
system, not a deferrable enhancement, and GPT's cycles 14–16
condition (duplicate consumption fails with no/stale history)
is explicitly not met for the stale-history leg. Seat-gemini's
FIX on item (1) (Ed25519 differential validation + seed
hygiene) is the second workstream. This design covers both;
seat C leads B (the consumption head) and takes a position on A.

## 0. Summary of positions (the room's decision record)

- **D1 — store location: verifier-owned consumption state
  (route-4).** A new sibling hash-chain journal in the
  verifier home, `ceremony-consumptions.json`, owned by a new
  `CeremonyConsumptionLedger` in trust/ledger.py, consumed
  through a new verifier mode `ceremony_consume`. No new env
  var, no wrapper-allowlist change. This is the war room's
  decision, per the standing rule (DECISION-PROTECTED-GATE-
  EXTENSION.md, 2026-11-23: design/store-location decisions
  are made by the war room and recorded; the owner is NOT
  asked — he is informed of the outcome in the normal updates).
- **D2 — integration: option (i).** `reanchor_pin` gains a
  REQUIRED keyword `consume_authorisation` — a callable invoked
  after all local checks and before the record is built. The
  offline property of `reanchor_pin` is surrendered for the
  production path (stated in exact words in §2); the T1-style
  required-keyword discipline from cycle 20 applies verbatim.
- **D3 — crash contract:** local checks → consume commit
  (durable, fsync'd journal append) → return pin/record. A
  crash after the commit and before adoption leaves a
  **burned-but-unmoved** authorisation — the fail-closed
  outcome, mirroring the issuance burn. Recovery is a new
  ceremony_id + new evidence bundle.
- **D4 — ceremony_history: kept REQUIRED, authority removed.**
  The history checks stay, unchanged in code, as
  defence-in-depth and caller-coherence checks; they stop
  being described as replay defence. The per-reason
  admissibility table from cycle 20 is unchanged.
- **D5 — T7 and T8 are rewritten to assert REFUSAL** (shapes
  kept), with a second head-staleness leg added to T8.
- **D6 — workstream A:** differential suite is test-only
  (no ed25519.py code change in the plan); seed hygiene is a
  loader predicate change plus a derivation-overlap check in
  `_load_config`.
- **D7 — anchoring: NOT now; named residual.**
  The consumption journal is anchored only indirectly this
  cycle, by mirroring each consumption into the (already
  anchored, in production) signing ledger. A dedicated anchor
  kind + env var is the named follow-up
  `ceremony-consumption-journal-anchoring`, bundled with the
  existing `ceremony-journal-anchoring` residual.

---

## 1. D1 — Store location: verifier-owned consumption state

### 1.1 Decision

The authoritative consumption record lives in the verifier
process's home (`AION_VERIFIER_HOME`), as a new
`HashChainJournal` subclass:

```text
CeremonyConsumptionLedger  —  trust/ledger.py
FILENAME = "ceremony-consumptions.json"
EXTRA_KEYS = {authorisation_id, ceremony_id, operator_id,
              evidence_hash, old_cycle_seq, old_payload_hash,
              new_cycle_seq, new_payload_hash, consumed_at}
```

One entry per consumed authorisation, kind `"consume"`.
The journal is consulted and appended by a new verifier mode,
`ceremony_consume` (trust/verifier_main.py), reached from the
ceremony process through `VerifierClient.ceremony_consume` /
the `ceremony_consumer(client)` adapter (trust/client.py).
The caller supplies no history and no store to this path: the
verifier checks its own journal against a fresh reload, and
the append is the commit point.

The ledger enforces two invariants at the commit point, in
one reload → validate → append cycle with the bounded retry
of `ShipLedger.burn` (8 attempts on the `_save` freshness
`CorruptLedgerError`; every retry re-validates against fresh
entries, so a concurrent append of the SAME authorisation is
still refused, never silently landed twice):

1. **Single-use by authorisation_id.** An
   `authorisation_id` already present refuses
   (`LedgerError` → mode maps to exit 3
   `ceremony_already_consumed`). This alone closes T7/T8.
2. **Monotonic head.** The journal's head is the new pin of
   its last entry (entries are append-only and consumption
   enforces strict increase, so the last entry IS the max —
   no scan is needed, though `consume` validates against a
   fresh reload). A consume request is refused when it would
   move the head backwards:
   - if the envelope carries an old pin, require
     `old_cycle_seq > head_seq`, or `old_cycle_seq ==
     head_seq` with the same `payload_hash` (a different
     hash at the same sequence is a fork/stale pin);
   - require `candidate_cycle_seq > head_seq` (a candidate
     at or behind the head is a regression — for
     `chain_gap_recovery` this is implied by the gap rule
     plus the old-pin rule, but it is checked explicitly so
     the no-pin reasons get the same protection).
   - Empty journal: genesis head, no check (bootstrap).
   Refusals: `ceremony_consumption_stale` (old pin behind
   the head) / `ceremony_consumption_regression` (candidate
   behind the head), exit 3.

   The head check is the second leg, not the first: it
   closes the *fresh-envelope* regression shape (a NEW
   ceremony_id + new evidence restaging an old pin after
   the head moved — authorisation_id uniqueness cannot see
   it). It is deliberately weaker than "old pin must equal
   the head": `advance_pin` moves the real pin without any
   verifier involvement and leaves no trace in any journal,
   so the verifier's head is a **ceremony head, not the pin
   head** — it always lags a pin that advanced normally.
   Requiring equality would refuse every legitimate
   ceremony after ordinary advances. The head rule is
   therefore "not behind", never "equal". (This is the same
   structural fact that made cycle 16's history a ceremony
   head, not a pin head — now made explicit in the verifier
   instead of the caller.)

   Consequence to state plainly: a fresh envelope whose old
   pin is *ahead* of the verifier head is accepted even if
   the caller's real pin is behind that old pin — that is
   still FRESH-PIN, the caller's unverifiable obligation
   (§4). The head closes replay and regression *relative
   to consumed ceremonies*, not arbitrary caller lies about
   the live pin. No design in this cycle can do the latter
   without a verifier-owned pin store, which is a different
   (much larger) change — see §1.3 alternative (g).

The consumption entry records the full event (old pin,
new pin, operator, evidence hash, authorisation id,
consumed_at) so a later audit can reconstruct the head and
its lineage from the journal alone.

### 1.2 Why this location wins

- It is the **only existing protected store** (CROSS-CHECK-14
  reconciliation): the verifier home is already the one
  directory the ceremony caller cannot rewrite — the
  issuance journal, the signing ledger, and the retained
  evidence all live there, under the verifier's process and
  (in deployment) its OS user. Every caller-side store
  fails the exact attack T7/T8 demonstrate: the caller
  restages its own history, so any store the caller can
  roll back is not authoritative.
- It reuses the **proven mechanism**: `HashChainJournal`
  (flock on the journal directory, tmp-write + fsync +
  atomic replace + dir fsync, under-flock freshness
  re-check, strict parse, hash chain) with the
  post-reload duplicate re-check lesson of the cycle-20
  fix round (a competitor commit between scan and append
  must be caught at the commit point). No new persistence
  technology, no new dependency (stdlib only).
- It needs **no new env var and no wrapper change**: the
  store lives under the existing `AION_VERIFIER_HOME`.
  `run-verifier.sh`'s allowlist stays at 17; wiring's
  allowlist copy is untouched. The deploy surface does not
  grow — a real advantage over any location that needs a
  new path or credential.
- It composes with the existing issuance accounting: the
  mode additionally requires the `authorisation_id` to be
  present in `CeremonyAuthorisationLedger` with matching
  `ceremony_id` / `evidence_hash` / `operator_id` /
  `payload_hash` (exit 3 `ceremony_authorisation_unknown`
  otherwise). A consumed envelope is therefore always one
  *this* verifier issued — a forged or relabelled envelope
  cannot be consumed even by a caller who minted it
  elsewhere. (The verifier's seed must be configured for
  the mode to run — exit 3 `ceremony_seed_unconfigured`,
  mirroring `ceremony_authorise` — because the mode also
  re-verifies the envelope signature and expiry on its own
  clock; operator list and evidence dir are NOT required
  at consume time, they are issuance inputs.)
- The mode is one process per request (existing verifier
  architecture), so no daemon, no session, no new
  concurrency model: cross-process serialisation is the
  journal flock, exactly as for issuance.

### 1.3 Alternatives weighed and rejected

| Alternative | Why rejected |
|---|---|
| (a) Caller-side protected pin store / loop state dir | Fails the attack by construction: the store is in the caller's rollback domain. T7/T8 *are* the demonstration. Any "caller persists atomically" design is a promise the caller makes to itself. |
| (b) Extend `CeremonyAuthorisationLedger` with consume entries | Its `EXTRA_KEYS` are an exact-set load contract; a consume entry needs different fields (old/new pin, consumed_at), so widening it is a journal format migration over every historical entry. It also conflates two commit points (issuance burn vs consumption burn) in one file, so a bug in one path corrupts the other's audit story. Sibling journal keeps issuance untouched. |
| (c) In-process monotonic counter / `pin_ceremony` module state | No persistence: a process restart resets it, and the ceremony process is spawned per call. Also the ceremony process is the untrusted side of this boundary. |
| (d) The signing ledger as the primary consumption store | Shape mismatch (its `EXTRA_KEYS` carry neither ceremony_id nor evidence_hash, and widening them is again a migration) and it would pollute the ledger's core inference ("a signature with no ledger entry is evidence of a second signer") with non-signature entries. Adopted instead as a *mirror* for anchoring (§7), not as the authority. |
| (e) SQLite / a new store technology | Stdlib has sqlite3, but it breaks the `HashChainJournal` audit pattern (hash-chained, human-inspectable JSON, one mechanism for all journals) and adds a second persistence story the war room would have to review from scratch. |
| (f) Anchor file as the head (store the head pin in an external anchor) | Conflates anchoring (a rollback-evidence pin, §7) with state (per-authorisation uniqueness). An anchor names one head hash; it cannot record *which* authorisations were consumed, so a replay after an anchor re-pin would be invisible. |
| (g) Verifier-owned **pin store** (verifier tracks the live pin; `advance_pin` reports to it) | Closes FRESH-PIN too — the only alternative that does. Rejected for cycle 21 as scope: it makes every normal advance a verifier round-trip, turns the verifier into the pin's system of record, and needs a migration story for pins that predate it. Named as the follow-up `verifier-owned-pin-store`, to be judged on its own, not smuggled in here. |

### 1.4 What this does NOT close (honest scope)

- Verifier-home rollback: someone with write access to the
  verifier home can roll back `ceremony-consumptions.json`
  and re-enable a replay — exactly the residual already
  carried by the issuance journal, now extended to the
  consumption journal. Mitigated in production by the
  signing-ledger mirror (§7) and named as the residual
  `ceremony-consumption-journal-anchoring`. The design's
  threat model is the *caller* (including a caller whose
  own state was rolled back), not an attacker with
  verifier-home write access — that attacker can already
  roll back issuance and mint with the seed.
- A compromised verifier can fabricate consumption
  receipts or refuse arbitrarily. Consumption moves trust
  from caller history to verifier availability and honesty
  — the same launch-channel trust every other verifier mode
  already rests on. This is the design's weakest point;
  see §8.
- Liveness: a ceremony now *requires* the verifier to be
  up. Verifier down = no recovery, exactly when recovery is
  needed most. That is the fail-closed price, and it is
  deliberate: the alternative (a ceremony that proceeds
  without the head) is the T7/T8 defect.

---

## 2. D2 — The `reanchor_pin` integration contract: option (i)

### Decision

**Option (i): `reanchor_pin` gains a REQUIRED keyword
`consume_authorisation`, invoked after all local checks and
before the record is built/returned.** The signature gains
exactly one parameter; transport stays outside `signing/`
(the module imports nothing from `trust/` — the callable is
duck-typed, and `trust/client.py` supplies the production
implementation).

```python
reanchor_pin(old_pin, signed, *, signing_key, state_bytes,
             calibration_bytes, expected_signer_id, operator_id,
             reason, evidence_hash, authorisation,
             authorisation_public_key, expected_verifier_signer_id,
             ceremony_history, consume_authorisation,
             strict_reasons=None, now=None)
```

**Callable contract** (pinned in the `reanchor_pin`
docstring and by tests):

- `consume_authorisation(authorisation)` — positional,
  one argument, the `SignedCeremonyAuthorisation` object.
- Returns `None` on committed consumption. (The verifier
  receipt is *not* returned into `reanchor_pin` and is *not*
  bound into the record this cycle — see §8 for the
  considered-and-rejected receipt-binding variant.)
- Raises `SigningError` on any refusal or unavailability:
  already-consumed, stale, regression, unknown
  authorisation, expired, verifier unreachable, verifier
  timeout, malformed receipt. `reanchor_pin` converts any
  exception from the callable into a `SigningError` refusal
  naming the consumption failure — no success path exists
  around a callable that failed, and a callable that raises
  a non-`SigningError` is still a refusal (the callable's
  own exception type is preserved as the cause, never
  swallowed silently).
- The callable is invoked **exactly once per successful
  ceremony**, and **zero times on any refusal**: it is the
  last gate, placed after the bare attestation verification
  (the current step after `_check_ceremony_history`), and
  immediately before `performed_at` is computed and the
  record payload is built. Nothing after the call can
  refuse: record construction from already-validated values
  is pure. A test pins this ordering twice: (a) a ceremony
  refused for any local reason (expired envelope, binding
  mismatch, history refusal, failed attestation) leaves the
  consumption journal untouched — a counting fake/spy
  consumer records zero calls; (b) a spy consumer records
  exactly one call on a successful ceremony.
- **Early refusal, T1/T2 discipline:** omitting the keyword
  is a `TypeError` (no default — pinned by a signature
  inspection test, the T1 analogue, named T1b); an explicit
  `None` refuses with a `SigningError` naming
  fail-closed-on-omission, **before envelope verification**,
  alongside the `ceremony_history is None` check (step 2 in
  the current numbering — the two presence checks sit
  together, and the ordering test mirrors T2: an expired
  envelope plus `consume_authorisation=None` still reports
  the omission, never the expiry). A non-callable value
  refuses at the same early point. This is the cycle-20
  R6 discipline applied verbatim: the parameter has no
  default, and omission is a refusal, not a fallback to a
  history-only ceremony — a "convenience" default that
  skipped consumption would silently resurrect T7/T8.

**Production callable** — `trust/client.py` supplies it:

- `VerifierClient.ceremony_consume(authorisation)`:
  serialises the envelope with
  `ceremony_authorisation_envelope_to_dict`, calls
  `_run("ceremony_consume", {"authorisation": ...})`,
  and validates the receipt: exact result key set,
  `authorisation_id` / `ceremony_id` echo against the
  envelope, `new_cycle_seq` / `new_payload_hash` echo
  against the envelope's candidate, `consumption_seq`
  an int ≥ 1. Any mismatch or transport/config/protocol
  failure raises the usual `Verifier*` error (exit-3
  refusals → `VerifierConfigError`; exit-2 →
  `VerifierProtocolError`; transport failure →
  `VerifierUnavailable` / `VerifierTimeout`).
  [Record note, added at build: the body key in this bullet
  as originally drafted — `{"authorisation": ...}` — was
  WRONG and is conceded to seat B in critique-c §2.1: the
  wire key is `signed_authorisation`, per the
  `ceremony_authorise` precedent. The build ships B's body,
  exactly `{"signed_authorisation": <envelope dict>}`.]
- `VerifierClient.ceremony_consumer()`: returns the
  production callable for `reanchor_pin` — a one-argument
  callable taking the `SignedCeremonyAuthorisation`,
  converting it via
  `ceremony_authorisation_envelope_to_dict`, calling
  `ceremony_consume`, translating any `Verifier*` exception
  into `SigningError` (cause chained), returning `None` on
  success. The callable never retries a consume
  automatically: a lost or ambiguous response is treated
  as burned (see §3).
- The receipt is UNSIGNED and is not returned into
  `reanchor_pin` or bound into the ceremony record this
  cycle (see §8). The client's checks are echo/binding
  checks over the launch channel — exact key set,
  `authorisation_id` and `ceremony_id` echoing the sent
  envelope, candidate seq/hash echoing the sent candidate,
  `consumption_seq` an int ≥ 1 — not cryptographic proof.

**Offline trade-off, in exact words (carried into the
`pin_ceremony` docstring at build):** reanchor_pin is no
longer an offline function — a successful ceremony
requires a live verifier round-trip inside the envelope's
TTL and fails closed when the verifier is unreachable;
every existing direct caller breaks with TypeError until
it supplies the keyword, and that flag-day breakage is
intended.

---

## 3. D3 — Crash-consistency contract

Local checks → consume commit (durable, fsync'd journal
append at the verifier) → return pin/record. Consumption
is committed at the verifier before `reanchor_pin`
returns anything. There is no execution path in the
integrated system in which a pin movement succeeds
without its consumption record durably committed first.

| # | Crash point | Consumption | Pin | Recovery |
|---|---|---|---|---|
| C-a | Before the verifier's journal commit | Not consumed | Unmoved | Retry the same envelope |
| C-b | During the journal write | Old journal or new journal, never torn (`HashChainJournal._save`: tmp + fsync + `os.replace` + dir fsync) | Unmoved | Re-read decides: retry (C-a) or refuse already-consumed (C-c) |
| C-c | After the consume commit, before `reanchor_pin` returns (response lost, client timeout, adapter raises) | Consumed (burned) | Unmoved | No retry with this envelope. New ceremony_id + new evidence bundle. |
| C-d | After `reanchor_pin` returns, before the caller adopts pin+record | Consumed (burned) | Unmoved | New ceremony (the ATOMIC-ADOPTION failure mode, now safe: adoption failure can no longer enable replay) |
| C-e | Any local refusal before the consume call | Not consumed — callable invoked zero times | Unmoved | Fix the cause, retry the same envelope |

A lost or ambiguous response is treated as burned; the
client never retries a consume automatically. Recovery
is a new ceremony (new ceremony_id, new evidence), never
an un-consume.

Tests owned by this seat (stated in full in critique-c
§3.3): **T-Cc** — a fake consumer that commits to a real
ledger then raises: `reanchor_pin` returns nothing, a
second attempt refuses already-consumed, exactly one
consumption entry exists. **T-Cd** — caller killed after
`reanchor_pin` returns, before adoption: on restart the
envelope refuses already-consumed, the on-disk pin is the
pre-ceremony pin, and a fresh ceremony ahead of the head
succeeds. Seat B's K1–K6 cover the verifier-side
boundaries (C-a, C-b, the verifier half of C-c, mirror
failure, concurrent race) via wrapper-module `os._exit`
patches — adopted over any env fault hook, as it adds
zero production surface.

Ordering note (critique-c §3.4, held against B's
consume-before-reanchor orchestration): consumption
inside `reanchor_pin`, as the last fallible step, means
a locally refused ceremony burns nothing. Consuming
before the local checks would burn the envelope on every
binding mismatch, history refusal and attestation
failure, converting correctable local refusals into
new-ceremony recoveries, and buys no safety property.

---

## 4. D4 — `ceremony_history` after the head, and caller preconditions

`ceremony_history` stays REQUIRED and unchanged in code:
explicit `None` still refuses before envelope
verification, `_check_ceremony_history` and the
per-reason admissibility table are untouched. Its
AUTHORITY is removed in wording only: it is an
audit/consistency input that can only refuse, never
grant, and the verifier's consumption head is
authoritative on any discrepancy. Docstrings stop
describing it as replay protection.

The COMPLETE-HISTORY caller precondition is demoted
from a security precondition to an audit obligation.
FRESH-PIN and ATOMIC-ADOPTION remain caller obligations
with their (now smaller) failure modes stated: a
restaged old pin ahead of the head is still admitted
verifier-side (the head closes replay and regression
relative to consumed ceremonies, not arbitrary caller
claims about the live pin — §1.1), and a crash after
return but before adoption is C-d (§3), now safe
against replay. EVIDENCE-INTENT is unchanged.

---

## 5. D5 — T7′ and T8′: the residual pins flip to refusal

T7 and T8 keep their scenario shapes; their assertions
reverse. They are no longer residual pins — the residual
is CLOSED by the head, and the test names/docstrings say
so, with a comment recording that they were the cycle-20
residual pins.

- **T7′** (`test_consumption_replay_with_stale_history_
  succeeds_named_residual_protected_head`, renamed in
  substance): the same envelope twice; the second call
  supplies the STALE `()` history AND goes through a
  FRESH `CeremonyConsumptionLedger` instance over the
  same fixture directory — proving the refusal comes
  from on-disk authority, not in-memory state — and
  refuses already-consumed.
- **T8′**: consume seq1→seq4, `advance_pin` to seq6,
  replay with the restaged seq-1 pin. Updated-history
  presentation refuses as before (history leg).
  Stale-history presentation NOW refuses via the
  consumer (already-consumed) and NO regressed pin is
  returned. Added leg: a NEW envelope for old=seq1 /
  candidate=seq5 (head=4, live pin 6) refuses at the
  consumer with the head-regression refusal (the
  not-behind old-pin rule, §1.1 / critique-c §1.3).

Test-helper discipline: the `reanchor()` helper's
DEFAULT consumer is a real `CeremonyConsumptionLedger`-
backed consumer over a FIXTURE-scoped temp dir (one
ledger per test class/module fixture, NOT per call — a
per-call fresh dir would silently re-pin the cycle-20
history-leg semantics). Tests needing continuity share
one consumer explicitly. The helper never defaults to
an always-succeed fake; fakes are allowed only where
the test's subject is the fake itself (spy/counting
consumers, T-Cc's commit-then-raise consumer).

---

## 6. D6 — Workstream A: differential suite and seed hygiene

Differential suite (test-only; no `ed25519.py` change
planned): a NEW file (the cycle-20 test file is not
extended; fixtures re-declared) with RFC 8032 §7.1
known-answer vectors as literals (including a long-
message vector), a Wycheproof-style adversarial table,
bit-flip sweeps, and an openssl differential (openssl
3.0.13 on this VM; skip cleanly when absent).

Positions held in critique-c §6, restated:

- Every adversarial row pins a PER-CASE expectation
  PAIR `(ours, openssl)` as literal data, asserted in
  full. Ours must be False for every adversarial row.
  An un-pinned "divergence allowed" bucket is vacuous
  (it asserts only our rejection, which the in-house
  table already asserts) and can ratify a bug: if our
  verifier wrongly accepted a small-order/non-canonical
  A that openssl also accepts, an allowed-set bucket
  would present it as agreement. Pinned pairs make
  either side changing its answer a test failure.
- Measured probe results (openssl 3.0.13, this round):
  S+L malleation is AGREE-REJECT (openssl rejects);
  openssl ACCEPTS A = identity (canonical) and A =
  identity under its non-canonical y = 1+q spelling —
  those rows pin `(False, True)`; the same non-canonical
  spelling applied to R is rejected by openssl (the
  leniency is asymmetric).
- Sign direction: openssl's deterministic signature
  must be BYTE-IDENTICAL to ours, and ours must pass
  openssl verification. Verify direction: the pinned
  pairs above.
- Empty message: `openssl pkeyutl` cannot process
  0-byte messages (a tooling failure that presents like
  a rejection) — openssl directions use messages of
  length ≥ 1; the empty message is covered by KAT plus
  the affine oracle.
- Bit-flip sweeps against OUR verify only: every
  single-bit flip of the 64 signature bytes, the 32
  public-key bytes and the message must verify False;
  runtime re-measured at build (cycle-20 timings price
  the full sweep at ≈5–7 s; subsample fallback only
  above 60 s).

Seed hygiene: a loader predicate change plus a
derivation-overlap check in `_load_config` (the one
place both secrets exist). Positions as revised in
critique-c §§4–5:

- Permission predicate, SHARED by both loaders via one
  helper: accept iff the fstat mode has NO group/world
  bits AND the owner-read bit is set — in practice
  {0400, 0600}. The "exactly 0600" wording is retired
  in both loaders and their tests. (Conceded to A in
  critique-c §4: no existing test pins exactly-0600 for
  either loader, and gate parity ships this cycle, not
  as a follow-up.)
- fd discipline for the CEREMONY SEED loader this
  cycle: open with `O_NOFOLLOW | O_NONBLOCK`, fstat for
  `S_ISREG` + mode, bounded read from the fd. The
  signing-key loader's fd rework is the named follow-up
  `signing-key-loader-fd-hardening`; its permission
  PREDICATE widens this cycle with the shared helper.
- Owner-uid check: seed loader only — when euid != 0,
  require `st_uid == euid`; as root the check is
  vacuous and skipped (B's carve-out, adopted). NOT
  applied to the gate loader (`deploy/verifier-identity/
  health_check.py` is a second, differently-identified
  reader of the gate key — critique-c §4).
- Derivation overlap, closed set in `_load_config`:
  (1) seed == key (existing); (2) seed == sha256(key);
  (3) key == sha256(seed); (4) key == ceremony public
  key (public material as the HMAC secret — B's catch,
  the most dangerous relation); (5) seed ==
  sha256(ceremony public key); (6) key ==
  sha256(ceremony public key); (7) seed == sha256(own
  public key); (8) key ∈ REFUSED_TEST_SEEDS (live
  exactly for the RFC vector seeds). A's R4 (seed ∈
  REFUSED_TEST_KEYS) is DEAD — that set is a strict
  subset of REFUSED_TEST_SEEDS, already refused — and
  is not implemented. Wording: these relations catch
  accidents and known derivations, not arbitrary KDF
  overlap; no stronger claim is made.

---

## 7. D7 — Anchoring and the signing-ledger mirror

The consumption journal is NOT externally anchored
this cycle. Each successful consumption is MIRRORED
into the signing ledger — `SigningLedger.
append_ceremony_consumption`, kind `"consume"`, format
`"ceremony-consumption"`, EXISTING `EXTRA_KEYS`, no
format migration (precedent: `try_consume_eval_records`'
eval-consumption entries) — after the consumption-
journal append, which is THE commit point, and before
`_update_anchor(config)`. Mirror failure after the
commit → `ledger_failed`, the envelope stays burned,
no success response. The mirror is invoked ONLY on a
successful consumption append (mirror-before-commit
would invert the commit and is a review refusal).

TRAP (seat A, adopted): the issuance mirror already
writes signing-ledger entries with decision_id =
authorisation_id under kind `"sign"`. Any cross-check
or audit query for consumptions MUST scope to
kind="consume" + format="ceremony-consumption", or
every consume self-refuses.

Precise residual (B's wording): a rollback of the
verifier home cannot resurrect a consumed envelope
whose consumption is mirrored in the anchored signing
ledger (production), but can lower the enforced head
for never-consumed envelopes. The follow-up
`ceremony-journal-anchoring` covers BOTH journals
(issuance + consumption) jointly.

The shared directory flock serialises the three steps
across verifier-home journals but is NOT cross-ledger
atomicity; the benign-interleaving statement goes in
the mode docstring.

---

## 8. Claim wording, receipt binding, and the weakest point

**Claim wording (critique-c §7, the sentence all three
seats can sign; mandatory in docstrings and the build
record):** single-use consumption and pin non-regression
are properties of the INTEGRATED SYSTEM under its
production wiring — authorise via `VerifierClient`,
re-anchor with the verifier-backed consumer, adopt the
returned pin atomically — not properties of
`reanchor_pin` for an arbitrary caller-supplied
callable. A no-op callable gets no protection, exactly
as a caller supplying its own signing key or a wrong
public-key pin gets none; the callable is not materially
different from the inputs `reanchor_pin` already trusts.
The difference the callable makes is that omission is
LOUD: a missing keyword is a `TypeError`, an explicit
`None` is a refusal, whereas orchestration omission
(consume as a caller contract step) is silent.

**Receipt binding — considered and rejected.** Binding
the verifier's consumption receipt into the ceremony
record (or returning it from the callable) was
considered: the receipt is unsigned, so a signature-
style binding would prove only that the verifier *said*
it consumed, and a replayed receipt for the same
authorisation_id would verify cleanly. The client's
echo/binding checks (§2) recover the assurance on the
transport side, where it belongs. The record's existing
`authorisation_id` binding is unchanged.

**Weakest point (unchanged from §1.4):** consumption
moves trust from caller history to verifier
availability and honesty. A compromised verifier can
fabricate consumptions or refuse arbitrarily; verifier
down = no recovery, exactly when recovery is needed
most. That is the fail-closed price, and it is
deliberate: the alternative (a ceremony that proceeds
without the head) is the T7/T8 defect.
