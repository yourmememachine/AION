# Design C — Cycle 22, Workstream 3: first production adopter of `reanchor_pin`

Seat C. Design only; no production code in this document's cycle step.
Closes open item **F1** of `BUILD-CYCLE-21.md` ("no production caller of
`reanchor_pin` exists") and discharges the four caller preconditions in
`signing/pin_ceremony.py`'s docstring (FRESH-PIN / COMPLETE-HISTORY /
ATOMIC-ADOPTION / EVIDENCE-INTENT) for one concrete adopter: the
loop/storage layer's snapshot pin. Critiques of WS1 and WS2 are at the end.

Facts grounded in the current tree:

- Live loop state is at `cycle_seq 13`; `pick_next()` returns the
  `ledger-head-anchoring` backlog item first (pending, approved,
  leverage 6.5 — the highest-leverage pending item). Recording cycles
  past 13 in loop state has been blocked because each recorded cycle
  needs a snapshot + pin advance, and no production code did either.
- `CoreLoop.save()` (core/loop.py) is the repo's atomic-write discipline:
  `tempfile.mkstemp` in the target dir → write → flush → `os.fsync` →
  `os.replace` → open dir → `os.fsync` dir → close; temp unlinked on
  failure. The pin store mirrors it exactly.
- `reanchor_pin(..., consume_authorisation=<required kwarg>,
  ceremony_history=<required kwarg>)` returns `(new_pin, record)` and
  persists **nothing itself**. `advance_pin(pin, signed, ())` is the only
  normal movement. `PinCeremonyRecord` has **no serialiser** today —
  the store must add one (fields + `payload()` re-derivation, below).
- `trust/wiring.py::production_client` / `open_production_store`
  (cycle 13) are the established production-factory pattern: validate a
  copied env against an allowlist before constructing anything, pins
  supplied out-of-band and never derived from the env, refusals name the
  variable and never carry its value. The adopter follows it.
- Import direction constrains placement: `trust/client.py` imports
  `signing.*`; nothing in `signing/` may import `trust/`. So the store
  (signing-only) and the flow (needs `VerifierClient`) live in
  different layers.

---

## 1. Module placement

| File | Layer | Contents |
|---|---|---|
| `signing/pin_store.py` (new) | signing | `PinStore`: combined pin+history file, record serialisation, fresh reads, verified load, atomic CAS adopt. Imports only `signing.*` + stdlib. |
| `trust/pin_adoption.py` (new) | trust | `PinAdopter` (the full production flow), `PinAdopterConfig`, `build_pin_adopter(...)` factory in the `production_client` idiom, and the loop driver `run_one_cycle_and_pin(...)`. Imports `signing.*`, `trust.wiring`, `trust.client` types, `core.loop` (type only). No import cycle: `trust` already depends on `signing`; `core` depends on neither. |
| `core/loop.py` | — | **Unchanged in cycle 22.** See §5 for why the call site is a driver next to the loop, not a hook inside it. |
| `tests/test_signing_pin_store.py` (new) | tests | Pin-store unit tests (§7.1). |
| `tests/test_trust_pin_adoption.py` (new) | tests | Full-flow integration against the real verifier subprocess (§7.2). |

Naming: `pin_store` not `pin_ceremony_store` — it also serves the
`advance_pin` path, which is not a ceremony. The flow module is
`pin_adoption`, not `pin_adopter`: the repo names modules for the
operation (`wiring`, `anchoring`), and "adoption" is the
ATOMIC-ADOPTION precondition's own word.

---

## 2. `signing/pin_store.py` — the pin store

### 2.1 One combined file, not two — the ATOMIC-ADOPTION decision

ATOMIC-ADOPTION requires pin + record persisted "as one step". Two
files cannot be replaced in one rename, so a two-file design must pick
a crash ordering. Analysed honestly:

- **History-first, then pin.** Crash residue: a verified ceremony
  record in history whose pin was never adopted. This residue is
  actively hostile, not merely untidy: `_check_ceremony_history`
  refuses any later candidate that "is already a ceremonied target",
  and refuses candidates behind the history head — so the very
  candidate whose adoption crashed becomes **un-ceremoniable** through
  the ceremony path, while the pin still sits behind it. Fail-closed
  to the point of bricking that candidate; recovery would need a
  history edit, which the design forbids everywhere else.
- **Pin-first, then history.** Crash residue: pin moved, record
  missing. Safe for liveness and for safety-of-movement (the
  verifier's consumption head is authoritative for single-use and
  non-regression since cycle 21; local history "can only refuse,
  never grant"), but it silently violates COMPLETE-HISTORY: the audit
  trail claims no ceremony happened for a jump that did. The next
  reader cannot distinguish "pin advanced normally" from "ceremony
  record lost". An audit falsification by omission — the same class
  of defect WS1 exists to fix on the verifier side.
- **Single combined file.** One JSON document holding pin + full
  history, replaced by one `os.replace`. Pin and record appear
  together or not at all; ATOMIC-ADOPTION is satisfied literally, not
  by ordering argument. Cost is negligible *for this adopter*:
  history grows only on ceremonies (exceptional events), never on
  `advance_pin`; a `PinCeremonyRecord` serialises to ~600 bytes, so
  even hundreds of ceremonies keep the file in the low hundreds of KB,
  rewritten once per cycle at most. Write amplification is a non-issue
  at loop cadence (one cycle per cron run).

**Decision: single combined file.** It eliminates the ordering
dilemma instead of choosing the least-bad residue, at a cost this
workload does not feel. Declared limits, not hidden:

- Joint rollback of the one file (pin + history together, to an older
  consistent generation) is undetectable in-deployment — exactly the
  residual `state_snapshot.py` already states for pin + state. The
  verifier consumption head still bounds the damage: a rolled-back
  pin can re-present a gap candidate, but its envelope cannot be
  re-consumed, and a fresh ceremony against the rolled-back pin is
  refused by the verifier head rules where they apply.
- One file is one corruption point for both pin and history. The
  store therefore refuses on any parse/verification failure and
  **never** overwrites, quarantines-over, or bootstraps over a
  corrupt file (see §2.4); the bytes stay for operator recovery
  (which is a `lost_pin` / `corrupted_pin` ceremony — an existing,
  honest path).

### 2.2 File format

Path: `<pin_dir>/snapshot-pin.json`. `pin_dir` is **outside the state
dir** (the snapshot module's rule: the pin must live outside the
rollback domain); `PinStore.__init__` takes an explicit
`state_dir` argument and refuses if `pin_dir.resolve()` equals or is
inside `state_dir.resolve()`.

```json
{
  "v": "snapshot-pin-store/1",
  "pin": {"cycle_seq": 13, "payload_hash": "<hex64>",
          "key_id": "key-…", "signer_id": "…"} ,
  "history": [ {<record>}, … ]
}
```

`pin` is `null` only in the genesis document (see §2.4). Record
serialisation (new code, in this module — not added to
`pin_ceremony.py` in cycle 22, to keep the ceremony module untouched):

```python
def ceremony_record_to_dict(rec: PinCeremonyRecord) -> dict
def ceremony_record_from_dict(data) -> PinCeremonyRecord
```

`from_dict` is strict: exact key set = the dataclass fields; types
checked (`old_cycle_seq` int-or-None, hex64 fields via the existing
`_check_hex64` conventions); the reconstructed record's `payload()`
must re-derive `payload_hash` (raising `SigningError` otherwise, the
`snapshot_envelope_from_dict` precedent). Verification of the MAC is
**not** done by `from_dict` — it is done by `load_history` /
`read_all`, which hold the signing key (§2.3).

Caps: file ≤ 1 MiB (`MAX_PIN_STORE_BYTES`); history ≤ 1000 records.
Both refuse, never truncate.

### 2.3 API

```python
class PinStoreError(SigningError): …          # store-level refusals
class PinMovedError(PinStoreError): …         # CAS mismatch on adopt
class PinStoreBusy(PinStoreError): …          # lock held elsewhere

class PinStore:
    def __init__(self, pin_dir, *, state_dir): ...
    @property
    def path(self) -> Path: ...               # pin_dir/"snapshot-pin.json"

    def read_pin(self, *, signing_key) -> dict | None
    def load_history(self, *, signing_key) -> tuple[PinCeremonyRecord, ...]
    def read_all(self, *, signing_key) -> tuple[dict | None, tuple[PinCeremonyRecord, ...]]
    def adopt(self, new_pin, record=None, *, expected_old_pin,
              signing_key) -> None
```

Semantics:

- **FRESH-PIN.** Every read goes to disk, every call. No caching, no
  memoised pin, no "last known" fallback. `read_all` parses the file
  **once** and returns pin + history from that single parse, so the
  flow (§3) can never verify against pin generation *n* and pass
  history from generation *n+1*.
- **Verified load.** `read_all` verifies *every* history record with
  `verify_ceremony_record(rec, signing_key=signing_key) == ()`, and
  enforces the store-level consistency `_check_ceremony_history`
  assumes of its input: no duplicate `evidence_hash`, no forked
  targets (two records, same `new_cycle_seq`, different hash), and —
  store-only strengthening — if `pin` is not None, the pin must not
  sit *behind* the history head with a different hash (a combined
  file in that state is internally inconsistent in a way two separate
  files could hide). Any failure → `PinStoreError`, nothing returned.
  An unverifiable history establishes nothing; the adopter stops
  (integrity failure), it does not proceed with a partial history.
- **Atomic CAS adopt.** `adopt` is the only writer:
  1. Acquire an exclusive non-blocking `fcntl.flock` on
     `<pin_dir>/.snapshot-pin.lock` (created 0600). Held → `PinStoreBusy`.
     `flock` is released by the OS on process death, so no stale-lock
     recovery protocol exists or is needed.
  2. Under the lock, re-read and re-verify the current document.
     Compare-and-swap: the current pin must equal `expected_old_pin`
     (the pin the caller captured at flow start; `None` for genesis).
     Mismatch → `PinMovedError`, nothing written. This is the
     pin-store CAS named as open item 6 in BUILD-CYCLE-21, scoped to
     this store: it closes the capture-to-adopt window for *this*
     adopter's writers. (It does not make the verifier's ceremony
     head a pin head; that distinction stands.)
  3. Non-regression guard, local and unconditional: `new_pin.cycle_seq`
     < current seq → refuse; == current seq with a different
     `payload_hash` → refuse; == with same hash and `record is None`
     → idempotent no-op (returns without writing — the `advance_pin`
     same-pin case). If `record` is given, require
     `(record.new_cycle_seq, record.new_payload_hash) ==
     (new_pin.cycle_seq, new_pin.payload_hash)` and
     `verify_ceremony_record(record, …) == ()` *before* writing —
     the store never persists a record it has not itself verified.
  4. Serialise the new document; write with `loop.save()`'s exact
     discipline: `mkstemp(dir=pin_dir, prefix=".snapshot-pin-",
     suffix=".tmp")` → write → flush → fsync → `os.replace` → dir
     fsync. Temp unlinked on any failure; the pre-existing file is
     untouched by every failure before the rename, and the rename is
     the single commit point.
- **No other mutation methods.** No append-only history writer, no
  pin-only setter. Splitting adoption into two calls is exactly what
  ATOMIC-ADOPTION forbids, so the API makes it unrepresentable.

### 2.4 Genesis and corruption

- Missing file → `read_all` returns `(None, ())`. That is an
  assertion the flow acts on via an `initial_anchor` ceremony
  (§3.4), never via a silent first-write: `adopt(...,
  expected_old_pin=None)` on a missing file is the only genesis
  write, and it still requires a record (an `initial_anchor` /
  `lost_pin` record) — genesis by bare `advance_pin` is refused,
  because with no pin there is nothing for `advance_pin` to chain
  from.
- Existing but unparsable / unverifiable file → `PinStoreError` on
  every read and every adopt. The store never renames it aside
  (contrast `CoreLoop._quarantine`, which is the *loop's* choice for
  *its* file; silently quarantining the pin would manufacture a
  genesis state and invite a fraudulent `initial_anchor`).

---

## 3. `trust/pin_adoption.py` — the production flow

### 3.1 Config and factory (repo idiom)

```python
@dataclass(frozen=True)
class PinAdopterConfig:
    state_path: Path            # <state_dir>/state.json
    calibration_path: Path      # <state_dir>/calibration/calibration.json
    pin_dir: Path               # outside state_dir (enforced by PinStore)
    snapshot_signer_id: str     # signer_id for sign_state_snapshot
    expected_snapshot_signer_id: str  # pin for verify (== snapshot_signer_id in this deployment; kept as separate fields because verify-side pinning is the wrapper's contract)
    operator_id: str            # presented to ceremony_authorise
    expected_verifier_signer_id: str  # envelope signer pin (== production_client's expected_signer_id)
    evidence_dir: Path          # local shape: == verifier's AION_CEREMONY_EVIDENCE_DIR (§3.5)

def build_pin_adopter(env, *, expected_signer_id, expected_key_id,
                      authorisation_public_key,
                      signing_key_path, config) -> PinAdopter
```

- The verifier client is built **only** via
  `trust.wiring.production_client(env, expected_signer_id=…,
  expected_key_id=…, authorisation_public_key=…)`. The adopter never
  constructs `VerifierClient` directly (the trust lint's spirit; if
  the lint's watched-construction list does not yet cover this file,
  extending it is a named follow-up, not assumed).
- Pins are out-of-band arguments, exactly as in `production_client`:
  `expected_signer_id`, `expected_key_id`, and the ceremony public
  key pin as a `CeremonyPublicKey` object. `build_pin_adopter`
  refuses if `config.expected_verifier_signer_id != expected_signer_id`
  (same check, same reason as wiring: never pin to whatever the env
  asserts).
- The snapshot signing key is loaded with
  `signing.gate_decision.load_signing_key(signing_key_path,
  forbidden_roots=(state_dir, pin_dir))` — the key lives outside both
  the rollback domain and the pin dir, 0600, per the existing loader's
  rules. (Its fd-hardening is the already-named follow-up
  `signing-key-loader-fd-hardening`; not re-scoped here.)
- Adopter-specific env, read by a separate
  `pin_adopter_config_from_env(mapping)` in the wiring idiom (validate
  a copy; refusals name the variable, never its value):
  `AION_PIN_DIR`, `AION_PIN_SIGNING_KEY_PATH`, `AION_PIN_SIGNER_ID`,
  `AION_PIN_OPERATOR_ID`, `AION_PIN_EVIDENCE_DIR`. These are
  **adopter** variables, deliberately *not* added to wiring's
  17-name verifier allowlist — the verifier must never see them.
  `AION_PIN_EVIDENCE_DIR` must resolve equal to the verifier env's
  `AION_CEREMONY_EVIDENCE_DIR` in the local deployment shape; the
  factory refuses a mismatch it can see (both values present and
  unequal) rather than letting issuance fail later with
  `ceremony_evidence_unresolvable`.

### 3.2 Result and refusal types

```python
@dataclass(frozen=True)
class AdoptionResult:
    outcome: str            # "advanced" | "reanchored" | "already_current"
    pin: dict               # the pin now in force
    record: PinCeremonyRecord | None   # set iff outcome == "reanchored"

class PinAdoptionRefused(SigningError): …     # integrity failure / store refusal: nothing persisted
class PinAdoptionBurned(SigningError):        # consume committed, adoption did not complete
    returned_pin: dict | None                 # the pair reanchor_pin returned, if it returned
    returned_record: PinCeremonyRecord | None
```

`PinAdoptionBurned` carrying the returned pair is load-bearing for
WS1 recovery (§6): an in-process adopt failure is *not* a lost
record — the caller still holds it and can retry adoption without a
new ceremony.

### 3.3 The flow: `PinAdopter.snapshot_and_adopt()`

```python
def snapshot_and_adopt(self) -> AdoptionResult
```

One attempt, no internal retries of any verifier call. Steps:

1. **Capture (FRESH-PIN + COMPLETE-HISTORY).**
   `old_pin, history = store.read_all(signing_key=key)` — one parse,
   verified, at the start of *this* attempt. Nothing is reused from a
   previous attempt or from the `PinAdopter`'s construction.
2. **Consistent byte pair.** Read state bytes, read calibration
   bytes, re-read state bytes, refuse (`PinAdoptionRefused`) if the
   two state reads differ — the `sign_state_files` protocol, inlined
   as a private `_read_consistent_pair()` because `sign_state_files`
   returns the snapshot, not the bytes `reanchor_pin` needs.
   *Flagged drift risk:* this duplicates ~6 lines of a protocol owned
   by `state_snapshot.py`. Preferred long-term shape is a
   `sign_state_files`-sibling returning `(signed, state_bytes,
   calibration_bytes)`; cycle 22 takes the duplication with a comment
   naming it, rather than widening the signing API in the same cycle
   that adopts it.
3. **Sign the candidate.**
   `signed = sign_state_snapshot(state_bytes, signing_key=key,
   signer_id=cfg.snapshot_signer_id, calibration_bytes=calibration_bytes,
   prev_snapshot_hash=old_pin["payload_hash"] if old_pin is not None
   and facts.cycle_seq == old_pin["cycle_seq"] + 1 else "")`.
   The `prev` rule matters: for a gap candidate the immediate
   predecessor is *unobserved*, so its hash is unknown; writing the
   pin's hash there would fabricate a chain link the snapshot does
   not have. `""` (unbound link) is the honest spelling; strict
   verification reports `chain_gap` for a gap candidate regardless of
   the link value, and `reanchor_pin`'s recomputation uses the same
   wrapper, so eligibility is unaffected.
4. **Classify.** If `old_pin is not None`:
   `reasons = verify_snapshot_for_state(signed, signing_key=key,
   state_bytes=…, calibration_bytes=…, expected_pin=old_pin,
   expected_signer_id=cfg.expected_snapshot_signer_id)`;
   `cls = classify_verification(reasons)`. If `old_pin is None` there
   is no strict verification to classify (the wrapper requires a
   pin) — go directly to the initial-anchor ceremony (§3.4) with
   `reason="initial_anchor"` after the bare attestation check
   `verify_signed_snapshot(..., require_calibration=True,
   expected_signer_id=…) == ()`; anything else is integrity failure.
5. **Branch:**
   - `cls == "ok"` → `new_pin = advance_pin(old_pin, signed, ())` →
     `store.adopt(new_pin, record=None, expected_old_pin=old_pin, …)`
     → `AdoptionResult("advanced", new_pin, None)`. (Same-seq
     same-hash lands here too and returns `"already_current"` via the
     store's idempotent no-op; the flow distinguishes it by comparing
     `new_pin` to `old_pin` before adopting.)
   - `cls == "reanchor_required"` (sole `chain_gap`) → ceremony,
     §3.4, with `reason="chain_gap_recovery"`,
     `strict_reasons=reasons`.
   - `cls == "integrity_failure"` → raise `PinAdoptionRefused`.
     **Persist nothing.** No pin write, no history write, no evidence
     artefact is even created (artefact creation is inside the
     ceremony branch, after classification). The refusal message
     carries the reason tuple; alerting is the driver's job (§5).

No `now=` parameter anywhere in the production flow: freshness stays
on the host clock (the `commit_production` precedent — "production
wrappers must never accept one"). Tests use the live clock and fresh
snapshots, as the cycle-21 consumption harness does.

### 3.4 The ceremony sub-flow

```python
def _reanchor(self, *, old_pin, history, signed, state_bytes,
              calibration_bytes, reason, strict_reasons) -> AdoptionResult
```

1. **Evidence artefact first** (§3.5): write the bundle, compute
   `evidence_hash = sha256(bundle_bytes)` from the adopter's own
   bytes (EVIDENCE-INTENT: the hash comes from the artefact the
   adopter itself authored and placed — never from the envelope,
   which is only checked against it downstream by the client and by
   `reanchor_pin`'s exact binding).
2. **Authorise.**
   ```python
   envelope_dict = client.ceremony_authorise(
       operator_id=cfg.operator_id,
       ceremony_id=ceremony_id,                 # fresh per attempt, §3.5
       reason=reason,
       old_pin=None if old_pin is None else
           {"cycle_seq": old_pin["cycle_seq"],
            "payload_hash": old_pin["payload_hash"]},
       candidate={"cycle_seq": signed.cycle_seq,
                  "payload_hash": signed.payload_hash,
                  "signer_id": signed.signer_id,
                  "key_id": signed.key_id},
       evidence_hash=evidence_hash,
       evidence_ref=evidence_ref)
   signed_env = ceremony_authorisation_envelope_from_dict(envelope_dict)
   ```
   The `old_pin` projection is exactly the two-field shape
   `reanchor_pin` binds against (its captured `expected_old_pin`);
   passing the four-field store pin would fail exact binding — the
   harness's `project_old_pin` precedent.
3. **Pending-adoption journal** (WS1 hook, §6): append + fsync a
   one-line JSON note to `<pin_dir>/adoption-pending.jsonl`:
   `{ceremony_id, authorisation_id, candidate_seq, candidate_hash,
   phase: "authorised"}`. Cheap, non-authoritative, outside the
   combined file (it must survive — and be distinguishable from —
   an adopt crash; it is never read as history).
4. **Re-anchor.**
   ```python
   new_pin, record = reanchor_pin(
       old_pin, signed, signing_key=key,
       state_bytes=state_bytes, calibration_bytes=calibration_bytes,
       expected_signer_id=cfg.expected_snapshot_signer_id,
       operator_id=cfg.operator_id, reason=reason,
       evidence_hash=evidence_hash,
       authorisation=signed_env,
       authorisation_public_key=cfg_public_key,
       expected_verifier_signer_id=cfg.expected_verifier_signer_id,
       ceremony_history=history,
       consume_authorisation=client.ceremony_consumer(),
       strict_reasons=strict_reasons)   # None for initial_anchor
   ```
   Consumption commits at the verifier inside this call. Any
   exception from here on is treated as **burned** (§6): if
   `reanchor_pin` itself raised, the adopter cannot know whether the
   consumer committed before the failure (a lost consume response is
   indistinguishable from a refused one at this layer) — raise
   `PinAdoptionBurned(returned_pin=None, returned_record=None)`.
5. **Adopt atomically.** Update the pending note to
   `phase: "consumed"` (append line, fsync), then
   `store.adopt(new_pin, record, expected_old_pin=old_pin, …)`.
   On success append `phase: "adopted"` and return
   `AdoptionResult("reanchored", new_pin, record)`.
   On *any* adopt exception → `PinAdoptionBurned(new_pin, record)`
   with the returned pair attached. On `PinMovedError` specifically,
   the pair is still attached but the docstring must say plainly:
   retrying adoption of this pair will keep failing CAS until an
   operator reconciles — the burn is real, the movement belongs to
   whoever moved the pin first.

Timing budget, stated: the envelope TTL is hard-capped at 900 s and
the flow needs authorise → consume inside it, plus a snapshot whose
own TTL (≤ 48 h) must cover sign → verify. Steps 2–5 are two local
subprocess round-trips and file writes; the budget is ample locally,
and there is no step at which the flow waits on a human. If any step
fails on expiry, the attempt is over; a *new* attempt re-signs,
re-authorises (new ceremony_id, new evidence), re-consumes.

### 3.5 The evidence artefact — concrete local/test shape

What the evidence *is* for this adopter: an operator-review bundle
for the gap, authored by the adopter process itself at ceremony
time. That is weaker than an independent human case file, and the
design says so: in the local/single-host deployment the adopter and
the operator tooling are the same user's processes, so the bundle is
workflow provenance (exactly what cycle 19–20 claim for evidence —
attribution + event binding, not proof of independent review).
Deployments wanting independent evidence replace step 1 with an
operator step that places the bundle before invoking the flow; the
flow's contract (bundle exists under the evidence root at issuance,
hash computed from the placed bytes) is unchanged.

- **Placement:** written by the adopter, before `ceremony_authorise`,
  to `<evidence_dir>/<evidence_ref>` with the same write-temp + fsync
  + replace discipline (a half-written artefact must never be the
  bytes the verifier hashes). `evidence_dir` is the verifier's
  `AION_CEREMONY_EVIDENCE_DIR`; on this VM's deployment shape both
  processes are the same user on the same host, so direct placement
  is the honest mechanism. Split-host / split-user placement is an
  operator channel that does not exist yet — out of scope, named.
- **`evidence_ref`:** `pin-evidence-<ceremony_id>` — a bare relative
  filename (the verifier's grammar: a relative path under the
  evidence root), no directories, no collision with prior bundles.
- **`ceremony_id`:** `pin-adopt-<state_cycle_seq>-<uuid4hex12>`,
  generated per attempt. Freshness of the pair is what issuance
  single-use burns: a retry with the same `ceremony_id` or the same
  bundle bytes is refused at issuance, by design.
- **Bundle content** (UTF-8 text, deterministic field order):
  adopter id, operator id, reason, old pin (seq + hash, or
  `genesis`), candidate (seq, hash, signer, key), `state_sha256`,
  `calibration_sha256`, the unobserved range
  (`gap_from_seq`/`gap_to_seq` spellings from the record's own
  properties, or `initial anchor — no prior pin`), the strict
  reasons tuple that triggered the ceremony, and an ISO timestamp.
  Including the timestamp + ceremony_id makes every bundle's hash
  unique even for an identical gap, so a recovery ceremony never
  needs to invent different *content* to get a fresh hash.
- **Independence check:** the bundle hash is over bundle bytes that
  are not the candidate, its payload, or either file hash, so
  `reanchor_pin`'s evidence non-equality defence passes structurally,
  not by luck.

### 3.6 What the flow never does

- Never retries a consume, an authorise, or an adopt automatically
  (the cycle-21 R7 rule, inherited verbatim).
- Never calls `reanchor_pin` with a hand-rolled consumer — the only
  consumer is `client.ceremony_consumer()` (test discipline R12
  applies to tests, §7.2).
- Never writes the pin store except through `PinStore.adopt`.
- Never touches `state/state.json` or the calibration log: it reads
  bytes and attests them. State mutation stays the loop's.

---

## 4. Honest scope vs. the live state

The first adoption against the **live** deployment is an
`initial_anchor` ceremony: live state is at seq 13 and no production
pin file exists. That ceremony requires a provisioned production
verifier (`AION_CEREMONY_OPERATORS` + `AION_CEREMONY_EVIDENCE_DIR` +
`AION_CEREMONY_SIGNING_SEED_PATH`), and BUILD-CYCLE-21 item 7 records
the `aion-verifier` deployment on this VM as **not currently
provisioned**. Cycle 22 therefore delivers the adopter as production
code exercised end-to-end in temp dirs against the real verifier
subprocess; running it against live `state/state.json` is a
coordinator/operator act after provisioning, explicitly out of this
cycle's tests and out of this design's claims.

---

## 5. Loop call site

`core/loop.py` stays untouched, deliberately: its module docstring
promises "Standard library only. No network access", and the adopter
is neither (it spawns a verifier subprocess). Putting the hook inside
`CoreLoop` would break the loop's own stated contract to serve a
caller that can equally well wrap it. The call site is a driver
function in `trust/pin_adoption.py`:

```python
def run_one_cycle_and_pin(loop, adopter, *, coders, reviewers,
                          verdict, verify_passed, delta
                          ) -> tuple[dict | None, AdoptionResult | None]
    entry = loop.run_one_cycle(coders, reviewers, verdict,
                               verify_passed, delta)
    if entry is None:
        return None, None            # idle: no state change, no snapshot
    return entry, adopter.snapshot_and_adopt()
```

Semantics and the honest edges:

- **Ordering is forced and acknowledged:** `run_one_cycle` persists
  the cycle in `state.json` (its own atomic save) *before* the pin
  can move — a snapshot attests bytes that exist. There is no
  interleaving in which the pin leads the state. A crash between the
  two leaves state at seq *n*, pin at *n−1*: precisely the dense
  one-step case the *next* invocation heals via `advance_pin`, and if
  more cycles accrue first, via one ceremony. The wrapper does not
  roll back loop state on adoption failure — un-saving a shipped
  cycle would falsify the loop's history; instead it propagates the
  adoption exception with the entry attached
  (`PinAdoptionBurned` / `PinAdoptionRefused` propagate after
  `entry` is returned via an exception attribute — concretely:
  raise, with `entry` on the exception as `.cycle_entry`; the driver
  contract is "cycle recorded, pin pending, alert").
- **Steady state is the advance path.** If the runner calls this
  wrapper for every cycle, the pin stays dense (one snapshot per
  cycle — the dense-emission assumption, now actually implemented by
  the caller that was always supposed to own it), and ceremonies
  occur only after real disruptions (missed runs, expired snapshots,
  pin-store loss).
- **What this unblocks, precisely:** cycles past 13 can be recorded
  in loop state *with* their pin advances, which is the precondition
  that has kept loop state frozen. It does **not** complete the
  `ledger-head-anchoring` backlog item itself — that item is about
  anchoring the ship/signing ledger heads, different work; the
  adopter removes the pin-adoption blocker that was queued in front
  of recording further cycles, including that one. `pick_next` order
  is unaffected.
- **What remains, precisely:** (a) no in-repo production runner
  currently constructs `CoreLoop` against the live state dir —
  switching whatever external/cron runner exists to call
  `run_one_cycle_and_pin` is a deployment step, not code this cycle
  can land blind; (b) the live initial-anchor ceremony (§4);
  (c) alerting on `PinAdoptionRefused` — the wrapper raises, a
  runner must surface it; no alerting channel is designed here.

---

## 6. Critique — WS1 (F4: `burned_unadopted` recovery reason)

**The adopter is the caller WS1 exists for, and its crash shape is
more specific than "consume committed, adopt failed".** Split it:

1. **Adopt fails in-process** (exception from `store.adopt` after
   `reanchor_pin` returned): *the record is not lost.* The adopter
   holds `(new_pin, record)` in memory. Correct behaviour today,
   with no WS1 dependency: retry `adopt` with the same pair (CAS +
   idempotence make this safe), or hand the pair to the operator via
   `PinAdoptionBurned.returned_*`. Cycle 22 therefore **does** need a
   recovery entry point, and it is this cheap one:
   `PinAdopter.adopt_returned(new_pin, record, *, expected_old_pin)`
   — a thin, audited wrapper over `store.adopt` for exactly a pair
   some earlier `snapshot_and_adopt` returned. No new ceremony, no
   new reason, no burn wasted. Omitting it would force a fresh
   ceremony (and a second burn) for a transient fsync failure, which
   is how honest systems train their operators to bypass them.
2. **Process dies between consume-commit and adopt:** the record
   dies with the process. It is *not* reconstructible — its MAC
   covers `performed_at`, which was captured inside `reanchor_pin`
   and never persisted. On restart the adopter knows: pin unmoved
   (fresh read), and — via the §3.4 pending-adoption journal — that
   a consumption for `(ceremony_id, authorisation_id, candidate)`
   reached at least `authorised`, and if the `consumed` line was
   written, definitely burned. Without the journal it would know
   nothing at all, which is why the journal is in this design and
   not optional garnish.
3. **Behaviour today vs. with WS1:** Today, recovery is a fresh
   ceremony. For this adopter's gap case its reason is honestly
   `chain_gap_recovery` again — the gap still exists, the pin still
   exists; **no false `lost_pin` label is needed for the new
   ceremony itself**, and the design forbids using one. Where the
   falsification F4 names actually bites is the *accounting* of the
   first burn: any recovery record/runbook that must name why the
   first authorisation died has only `lost_pin` to reach for, for a
   pin that was never lost. With WS1's `burned_unadopted` (validated
   against a recorded burn), the recovery ceremony can carry the
   true reason and the pending-journal line + verifier consumption
   record give WS1's validation something real to check against —
   this adopter supplies both halves of that evidence. Adopter-side
   change when WS1 lands: one reason-selection branch in `_reanchor`
   (if the pending journal shows an unadopted burn for this same
   candidate, the recovery ceremony uses `burned_unadopted` instead
   of `chain_gap_recovery`), plus passing the burn reference. Design
   `_reanchor`'s reason as a computed value from the start so this
   is a branch, not a refactor.
4. **Is "record the burn + refuse to proceed" enough for cycle 22?**
   Recording: yes — pending journal + `PinAdoptionBurned` is the
   recording. **Refusing to proceed: no.** Refusal deadlocks the gap
   permanently (strict verification will report `chain_gap` forever;
   nothing else can move the pin), converting a recoverable burn
   into exactly the liveness trap the ceremony was built to escape.
   The sanctioned recovery — new ceremony, new ceremony_id, new
   evidence — is already the cycle-21 contract; the adopter follows
   it and proceeds. What the adopter must refuse is only *silent*
   proceeding: a pending-journal residue at startup is surfaced in
   the next `AdoptionResult`/exception, never quietly overwritten.

One WS1 requirement this design imposes back: WS1's validation
("honest reason validated against a recorded burn") must accept the
verifier's consumption journal as the recorded burn and must not
require the *adopter's* pending journal as authority — the adopter
journal is same-user, unauthenticated, and crash-truncated by
construction; it is a detection aid, not evidence.

## 7. Critique — WS2 (mirror gap: anchor the ceremony journals vs. restructure the commit)

Adopter-side implications are small, and the design keeps them that
way on purpose:

- **No adopter code change under either WS2 outcome.** The adopter's
  contract surface is `ceremony_authorise` / `ceremony_consumer()` /
  the `SigningError` refusal vocabulary. Anchoring the journals is
  verifier-home + anchor-path configuration; restructuring the
  commit (e.g. mirror-before-response) changes verifier internals
  and response timing, not the client's validated response shape.
  If a WS2 restructure *did* change the `ceremony_consume` response
  key set or echoes, `VerifierClient.ceremony_consume` would refuse
  — correctly, and that would be a WS2 breaking change to flag in
  its own review, not something the adopter should pre-adapt to.
- **One behavioural rule the adopter must already obey** (and this
  design does, §3.4/§3.6): a consume that fails *after* the request
  was sent — including the mirror-failure case, where the burn
  committed and the mirror write failed (`ledger_failed`) — is
  treated as burned. Never retry the envelope; recovery is a new
  ceremony. The mirror gap is precisely a machine for producing
  such ambiguous failures, so this rule is the adopter's whole
  exposure to it.
- **Deployment config only:** the adopter factory builds its client
  exclusively through `production_client`, which already requires
  both anchor paths outside the verifier home and mode exactly
  `production`. If WS2 adds a *ceremony-journal* anchor path to the
  verifier env, it lands in wiring's allowlist/required set, and
  the adopter inherits the requirement by construction — one more
  reason not to hand-roll client construction here. Adopter config
  validation must **not** grow its own opinion about verifier-home
  anchoring; duplicating wiring's checks in `pin_adoption.py` would
  create two sources of truth that can drift apart.
- **One thing the adopter must not do in response to WS2:** treat a
  locally missing ceremony record as evidence a ceremony "didn't
  happen" and re-drive it. Local history is refuse-only; the
  verifier head is authoritative (cycle 21). The pending journal
  (§6) is for detecting *burned-and-unmoved*, never for asserting
  *unburned*.

---

## 8. Tests

### 8.1 `tests/test_signing_pin_store.py` (unit, temp dirs only)

Store (fixture: temp `pin_dir` + temp `state_dir`, generated
signing key via `generate_key_file`, records minted through the
real `reanchor_pin` with the R12 ledger-backed test consumer — or,
for pure-store tests, records constructed and MACed with the
fixture key through `reanchor_pin` only; **no hand-MACed records**):

1. Round-trip: adopt genesis (with record) → fresh `PinStore`
   instance → `read_all` returns identical pin + history; record
   verifies.
2. Fresh-pin: two `read_pin` calls with an external adopt between
   them return the two different pins (no caching).
3. Advance adopt (`record=None`) preserves history byte-for-byte in
   the history field; ceremony adopt appends exactly one record.
4. CAS: adopt with stale `expected_old_pin` → `PinMovedError`, file
   bytes unchanged. Genesis adopt when a file already exists →
   refused.
5. Non-regression: lower seq refused; same seq different hash
   refused; same seq same hash, no record → no-op (file mtime/bytes
   unchanged).
6. Record binding: adopt with a record whose target ≠ `new_pin` →
   refused, nothing written; record with a bad MAC → refused.
7. Verified load: tamper one history record's field on disk →
   `read_all` raises, file bytes left exactly as tampered (no
   quarantine, no overwrite). Tamper the pin → same. Duplicate
   evidence hash / forked targets spliced on disk → refused.
8. Corrupt file (truncated JSON, wrong `v`, oversize) → refused on
   read and on adopt; bytes untouched.
9. `pin_dir` inside `state_dir` (and equal to it) → constructor
   refusal.
10. **Crash points** (monkeypatched failures, one test each):
    failure inside temp write; fsync failure; `os.replace` raising;
    dir-fsync raising after replace. For the first three: original
    file intact, no temp files left in `pin_dir`. For dir-fsync
    failure: the rename already committed — assert the *new*
    document is what a fresh read returns (the honest outcome:
    replace is the commit point; a post-commit fsync failure is
    reported but not rolled back — document this in the test name).
    Invariant asserted in every crash test: pin and history are
    never observed from different generations.
11. Lock: hold the flock from a second fd → adopt raises
    `PinStoreBusy`; after release, adopt succeeds.

### 8.2 `tests/test_trust_pin_adoption.py` (integration, real verifier)

Harness copied in shape from `tests/test_trust_ceremony_consumption.py`
(fixtures re-declared, standalone): temp verifier home (0700),
generated verifier key, `generate_ceremony_key_file` seed, real
evidence dir, `EvalRegistry` items, live clock. State side: a real
`CoreLoop` in a temp state dir driven through `scan`/`approve`/
`run_one_cycle_and_pin`, plus a real calibration file at
`<state_dir>/calibration/calibration.json`. Client built via
`build_pin_adopter` with a *research*-mode env — noted honestly in
the module docstring: `production_client` requires mode
`production` + anchors, the harness env is the consumption suite's
research env; the factory therefore takes the wiring-built client
in production and the harness builds the adopter around a directly
constructed `VerifierClient` in tests (the R12 pattern: real
verifier subprocess, real consumer, fixture wiring). If the war
room prefers, add one production-mode + anchored fixture variant
mirroring the wiring tests — listed as an option, not smuggled in.

Cases:

1. **Genesis → initial anchor:** no pin file, loop at seq 1 after
   one wrapped cycle → outcome `reanchored` with reason
   `initial_anchor`; pin file exists outside the state dir; history
   has exactly 1 record, which verifies with pin context; verifier
   consumption journal has exactly 1 entry.
2. **Advance path:** three further wrapped cycles → three
   `advanced` outcomes, pin seq tracks state seq, history still
   length 1, consumption journal still length 1 (no ceremony burn
   for normal movement).
3. **Gap → ceremony path:** run two cycles via bare
   `loop.run_one_cycle` (pin not advanced), then
   `snapshot_and_adopt()` → sole `chain_gap` → outcome `reanchored`,
   `chain_gap_recovery`; pin + record adopted in one file
   generation; record's `gap_from_seq`/`gap_to_seq` name the missed
   sequence; a second `snapshot_and_adopt()` on unchanged state →
   `already_current`, no new consumption.
4. **Integrity failure persists nothing:** corrupt the calibration
   file between cycles (bytes no longer match what the next
   snapshot would attest is *not* the failure — instead: tamper
   state bytes on disk after signing is not reachable through the
   flow, so use the reachable case: point the adopter at a state
   whose signer differs — `expected_snapshot_signer_id` mismatch —
   and separately a state file that fails `parse_state_bytes`) →
   `PinAdoptionRefused`; pin file bytes identical before/after;
   pending journal absent (no ceremony was started); consumption
   journal unchanged.
5. **Consume-committed, adopt-failed (the WS1 case):** monkeypatch
   `PinStore.adopt` to raise after `reanchor_pin` returns →
   `PinAdoptionBurned` with the returned pair attached; pin file
   still at the old pin; consumption journal length +1 (burn is
   real); then `adopt_returned(pair…)` succeeds with **no** new
   consumption; final pin/record equal the burned attempt's.
   Variant: adopt patched to raise and pair discarded → next
   `snapshot_and_adopt()` performs a *new* ceremony (new
   ceremony_id, new evidence artefact on disk, second consumption)
   and succeeds — recovery without `lost_pin` anywhere.
6. **Verifier down:** env pointed at an unspawnable verifier →
   ceremony path raises, pin file unchanged, evidence artefact may
   exist (harmless, unburned pair is an issuance-side fact) but no
   history/pin write occurs.
7. **Evidence independence/intent:** the artefact on disk under the
   evidence root hashes to the `evidence_hash` in the adopted
   record; artefact content names the gap range; two ceremonies
   produce two distinct artefacts and hashes.
8. **Config refusals:** `build_pin_adopter` with
   `AION_PIN_EVIDENCE_DIR` ≠ verifier evidence dir → refusal naming
   the variable; signing key path inside the state dir → loader
   refusal; missing operator id → refusal.

### 8.3 Not tested, by scope

No test touches the real `state/state.json`, the real pin dir, or a
provisioned verifier (§4). No test passes a `now=` into the flow
(there is none to pass).

---

## 9. Risks and open questions, flagged honestly

- **R1 — Combined-file growth** is bounded by ceremony count, not
  cycle count; if a future deployment ceremonies routinely, the
  file rewrites grow. Acceptable for cycle 22; a two-file split
  would re-open §2.1's dilemma and needs its own design.
- **R2 — `flock` is POSIX-only**, as is the rest of this deployment
  (fsync/dir-fsync discipline). No portability claim.
- **R3 — The `_read_consistent_pair` duplication** (§3.3 step 2) can
  drift from `sign_state_files`. Mitigation now: the integration
  tests exercise the flow against files the loop actually wrote;
  follow-up named above.
- **R4 — Evidence is self-authored** in the local shape (§3.5). The
  ceremony's evidence claim for this adopter is workflow provenance,
  full stop. If the war room wants the first production adopter to
  demonstrate *independent* evidence, the operator-placed variant
  must be built before the live initial anchor, and §3.5's contract
  already accommodates it — but it is not in cycle 22 scope as
  designed here.
- **R5 — CAS scope:** `PinStore.adopt`'s CAS serialises *this
  store's* writers. A second process holding its own `PinStore` on
  the same dir is handled (flock + CAS). A writer that ignores the
  store entirely is not — same-user honesty, as in `wiring.py`.
- **R6 — First live use is a ceremony, not an advance** (§4), and it
  is gated on verifier provisioning that does not currently exist
  on this VM. Cycle 22's deliverable is code + temp-dir proof, and
  the F1 closure claim must be worded that way ("first production
  adopter *built and wired as specified*"), not as "live pin
  adopted", until the coordinator runs it post-provisioning.
