# Cycle 24, Part 1 — Design A (Design Seat A)

Scope: Item 2 (ceremony public key MANDATORY in
`trust.wiring.production_client`) and Item 1 (a real non-test
production entry point). Mandate: `internal/CROSS-CHECK-17.md`
— both external seats converge on these two items; seat-gpt
lists both as minimum conditions, seat-gemini names both as
the strongest defect. This seat designs only; no production
code is written here.

Order of work for the build: Item 2 first (it is a prerequisite
of Item 1 — the runner passes a ceremony key, and Item 2 is
what makes that pass load-bearing rather than decorative),
then Item 1, then the Item-2/Item-1 test work in the same
cycle.

---

# ITEM 2 — `authorisation_public_key` mandatory in `production_client`

## 2.1 The defect, stated exactly

`trust/wiring.py:244-246` today:

```python
def production_client(verifier_env, *, expected_signer_id,
                      expected_key_id, authorisation_public_key=None,
                      launch=_LAUNCH_SAME_USER):
```

A client built without the pin constructs successfully, serves
every non-ceremony mode, and refuses only at the first
`ceremony_authorise` call — locally, in `trust/client.py`
(`ceremony_authorise`, ~line 472ff: `VerifierConfigError` when
`self._authorisation_public_key is None`), and again at the pin
layer in `_check_ceremony_pins` (`trust/client.py:280-300`).
That is a fail-silent wedge: the misconfiguration is
discoverable only at ceremony time, which is exactly the
moment the pin adopter needs the ceremony to work (genesis,
gap recovery, burned recovery). Both external seats demand
the pinless production client be *impossible to construct*,
not merely unusable for ceremonies.

## 2.2 The change

### Signature

```python
def production_client(verifier_env, *, expected_signer_id,
                      expected_key_id, authorisation_public_key,
                      launch=_LAUNCH_SAME_USER):
```

- `authorisation_public_key` becomes a **required keyword
  argument with no default**, in its current position (before
  `launch`, which keeps its default). Omitting it is a
  `TypeError` at call time, before the function body runs —
  the same mandatory-pin idiom `commit_production` already
  uses for `expected_signer_id` (pinned by
  `test_expected_signer_id_omitted_is_type_error`).
- No other parameter changes. `launch` semantics unchanged.

### Refusal behaviour (inside the body)

Replace the current check block (wiring.py, the "Ceremony
public-key pin (cycle 20)" comment + `if ... is not None and
not isinstance(...)`) with two explicit branches, in this
order, at the **same position** in the function — after the
signer/key pin checks, immediately before the
`return VerifierClient(...)`:

```python
if authorisation_public_key is None:
    raise VerifierConfigError(
        "authorisation_public_key: a ceremony public-key pin "
        "is mandatory for a production client; refusing None "
        "rather than constructing a client that would refuse "
        "every ceremony at first use")
if not isinstance(authorisation_public_key, CeremonyPublicKey):
    raise VerifierConfigError(
        "authorisation_public_key: must be a CeremonyPublicKey "
        "supplied out-of-band")
```

Rules pinned by this design:

- `None` and wrong-type are **distinct refusals with distinct
  messages**, both `VerifierConfigError`, both naming the
  parameter and never carrying its value (wiring's standing
  contract).
- Wrong type explicitly includes `CeremonySigningKey`: the
  factory takes the *public* pin only. A caller holding the
  signing key derives the pin via
  `signing.ceremony_authorisation.ceremony_public_key_for`.
  Accepting the secret-bearing type here would blur the v2
  key separation `CeremonyPublicKey` exists to enforce
  ("This type cannot hold secret material").
- Refusal **precedence is unchanged** for every existing
  refusal class: launch routing first, then env shape /
  allowlist / required keys / mode / INIT flags / anchor
  geometry, then signer pin, then key pin, then the ceremony
  pin. The existing refusal battery in
  `tests/test_trust_wiring.py` therefore keeps failing on the
  variable each test names — provided those calls are updated
  to pass a key (§2.4), because otherwise they would die with
  `TypeError` before reaching the body. That update is part of
  the build, not an afterthought.
- The returned construction is unchanged in form:
  `authorisation_public_key=authorisation_public_key` is
  passed through to the single allowlisted `VerifierClient`
  construction. The trust lint count for
  `("trust/wiring.py", "verifier_client_ctor")` stays 1.

## 2.3 Docstring / comment rewrites (the rationale dies)

1. **wiring.py, the pin comment block** (currently: "Optional
   at THIS factory because ceremony use is optional for a
   production client; a client without it refuses
   ceremony_authorise locally rather than accepting an
   unverified envelope"). Replace with wording to the effect:
   the ceremony pin is the **third mandatory pin**, beside the
   signer and key pins, supplied out-of-band the same way as
   a `CeremonyPublicKey` object (its `key_id` is derived from
   its bytes); it is mandatory at this factory since cycle 24
   because a pinless production client constructs fine and
   wedges only at first ceremony use — construction-time
   refusal is the only honest place for the refusal. Cycle-20
   optionality and its cycle-24 reversal are both named, with
   the CROSS-CHECK-17 mandate cited.
2. **wiring.py module docstring**, "Production client rules"
   paragraph: the sentence "The pins are mandatory: the signer
   pin must equal…, and the key pin must be…" gains the third
   pin: the ceremony public-key pin is mandatory and must be
   a `CeremonyPublicKey`; `None` refuses. No other module-
   docstring claim changes (the declared residuals are
   untouched — this change does not claim a capability
   boundary the docstring disclaims).
3. **`production_client` function docstring**: add one
   sentence — all three pins (signer, key, ceremony public
   key) are mandatory keyword arguments; omitting any is a
   `TypeError`, passing `None` for the ceremony pin is a
   `VerifierConfigError`.
4. **`deploy/verifier-identity/README.md`**, the "Production
   client pin warning" section (~line 392: "A production
   client built without the ceremony pin … fails only at
   first ceremony use… If the client will ever authorise
   ceremonies, set the pin at construction time"). This is
   live operator documentation and its warning is now false:
   rewrite it to state that a pinless `production_client`
   call cannot construct at all (omission `TypeError`, `None`
   refused), so there is no discover-at-ceremony-time failure
   mode left to warn about.
5. Historical records (`internal/BUILD-CYCLE-20.md`,
   `internal/REVIEW-CYCLE-20.md`, `internal/BUILD-CYCLE-23.md`,
   briefs) are **not** edited; they record what was true then.
   The cycle-24 build note records the reversal and its
   reason (§2.6).

## 2.4 Complete call-site inventory

Repo-wide grep for `production_client(` over `*.py`
(2026-11-23, this design pass). Production code has exactly
**one** caller; the rest are tests.

| # | Site | Passes key today? | Change |
|---|------|-------------------|--------|
| 1 | `trust/pin_adoption.py:220` — inside `build_pin_adopter` | **Yes** — `authorisation_public_key=authorisation_public_key`; `build_pin_adopter`'s own parameter is already a required keyword with no default, and `PinAdopter.__init__` already type-mandates `CeremonyPublicKey` | **None.** This is why Item 2 is cheap in production: the only production consumer already satisfies the new contract. |
| 2 | `trust/wiring.py:244` | — | The definition itself (§2.2, §2.3). |
| 3 | `tests/test_trust_wiring.py:149` — `ProductionClientRefusalTests.assert_refused` helper, `production_client(env, **pins)`; drives ~25 refusal tests | **No** — helper `setdefault`s only `expected_signer_id` / `expected_key_id` | Add `pins.setdefault("authorisation_public_key", CEREMONY_PUB)` (fixture in §2.5). Without this, every refusal test errors with `TypeError` instead of asserting its named-variable `VerifierConfigError`. |
| 4 | `tests/test_trust_wiring.py:375, 388, 400` — `ProductionClientNoLeakTests` (three direct calls) | **No** | Add `authorisation_public_key=CEREMONY_PUB` to all three. (Their refusals fire earlier — mode / unknown key / signer mismatch — so behaviour is unchanged once the call is well-formed.) |
| 5 | `tests/test_trust_wiring.py:422, 438, 456` — `ProductionClientHappyPathTests` (three direct calls) | **No** | Add `authorisation_public_key=CEREMONY_PUB` to all three; in `test_well_formed_env_returns_production_pinned_client` additionally assert `client._authorisation_public_key is CEREMONY_PUB` (the file's established private-field assertion style). |
| 6 | `tests/test_trust_wiring.py:911` — `LiveProductionWiringTests.test_production_client_against_live_deployment` (skipUnless-provisioned) | **No** | Must still be updated even though it skips on this VM: it builds its pins operator-side from the live env file + key file. It should pass the live deployment's ceremony pin, derived test-side from the provisioned ceremony seed the same way the deploy suite obtains key identity. If the live provisioning exposes no ceremony seed path to the test, pass a fixture `CeremonyPublicKey` — the test's only verifier call is a junk `verify_envelope({})`, which never touches the ceremony pin — and say so in a comment. Leaving it pinless would make the standalone cycle-close live run fail with `TypeError` the first time it is provisioned. |
| 7 | `tests/test_trust_production_e2e.py:194, 210` — the two negative tests calling `production_client` directly | **Yes** — both already pass `authorisation_public_key=self.home.pub` | **None.** |
| 8 | `tests/test_trust_pin_adoption.py` | No direct `production_client` calls; its three `build_pin_adopter(...)` calls (lines 374, 399, 409) already pass `authorisation_public_key=self.pub` | **None.** |
| 9 | `tests/test_cycle23_live_run.py` | No direct calls (goes through `build_pin_adopter`, key passed) | **None.** |

Non-call mentions (grep over the whole repo): `trust/__init__.py`
re-export (no signature, no change); `tests/test_trust_lint.py`
allowlist prose (no change); `deploy/verifier-identity/README.md`
(§2.3 item 4); everything under `internal/` is historical or
brief text (no change, §2.3 item 5).

## 2.5 Do the tests already have a ceremony key?

**No — `tests/test_trust_wiring.py` has none.** Its only key
fixture is the HMAC gate key (`KEY = make_signing_key(bytes(
range(32, 64)))`, `KEY_ID = "key-0123456789abcdef"`), and the
file imports nothing from `signing.ceremony_authorisation`.
The production e2e and pin-adoption suites do have keys
(`provision_production_home(...).pub`,
`ceremony_public_key_for(...)` fixtures), but the wiring suite
needs its own module-level fixture. Prescribed addition,
following the exact precedent in
`test_trust_production_e2e.CeremonyPinNamespaceTests`:

```python
import hashlib
from signing.ceremony_authorisation import (
    _make_ceremony_signing_key,
    ceremony_public_key_for,
)

CEREMONY_PUB = ceremony_public_key_for(
    _make_ceremony_signing_key(
        hashlib.sha256(b"trust-wiring ceremony pin fixture").digest()))
```

Notes: the seed is sha256-derived, deliberately **not** one of
the predictable seeds in `REFUSED_TEST_SEEDS`
(`signing/ceremony_authorisation.py`) — that refusal list binds
verifier provisioning, not a client-side pin object, but there
is no reason to normalise a refused seed as a fixture. The pin
is never used to verify a real envelope in the wiring suite;
it only has to be a genuine `CeremonyPublicKey` so construction
and refusal precedence are exercised honestly.

## 2.6 Client-side consequences — what does NOT change

- **`trust/client.py` is not modified.** `VerifierClient.__init__`
  keeps `authorisation_public_key=None` as its default:
  direct constructions remain legitimate for research-mode and
  test clients (e.g. `CeremonyPinNamespaceTests` constructs
  `VerifierClient` directly, with a pin; many other suites
  construct gate-only clients directly). The mandate is about
  the *production factory*, not about every client object in
  the repo.
- Consequently, for a client obtained from `production_client`,
  `self._authorisation_public_key` is now **always** a
  `CeremonyPublicKey`. Two existing refusal paths become
  unreachable *via that factory* and stay in place, reachable
  via direct construction, as defence in depth — do not delete
  or "clean up" either:
  - the local refusal at the top of `ceremony_authorise`
    ("ceremony_authorise requires a pinned ceremony public
    key… refusing to request an envelope this client cannot
    verify");
  - the `None` branch of `_check_ceremony_pins`
    ("ceremony response cannot be pin-checked: no ceremony
    public key is pinned on this client").
- Nothing else in the client changes behaviour: gate,
  sealed_eval, submit_claim and issue_attestation never read
  the ceremony pin (`_check_pins` is untouched); ceremony
  envelopes were already verified against the pin when one was
  supplied, so a correctly pinned production client behaves
  bit-for-bit as before. The only behaviour change in the
  system is at `production_client` construction time.
- **Deliberate breaking change, recorded:** a hypothetical
  gate-only production client via `production_client` can no
  longer be constructed. There is no such caller in production
  code (inventory §2.4: the adopter is the only one, and it
  already mandates the key). This reverses the cycle-20
  decision (`internal/BUILD-CYCLE-20.md`: mandatory attempted,
  reverted on evidence — 39 test errors, "all legitimate
  non-ceremony production clients"). The cycle-24 position:
  those 39 errors were *test* constructions, not production
  callers; the intervening cycles made the pin adopter the
  sole production consumer; and both cycle-23 external seats
  ruled the fail-at-first-ceremony wedge the worse defect.
  The build note for cycle 24 must state this reversal and
  cite CROSS-CHECK-17, so the paper trail the cycle-20
  re-review asked for exists this time.

## 2.7 Item-2 test additions (in `tests/test_trust_wiring.py`)

New tests in `ProductionClientRefusalTests` (or a small new
class `ProductionClientCeremonyPinTests`):

- `test_ceremony_pin_omitted_is_type_error` — call with only
  signer/key pins; `assertRaises(TypeError)` (mirrors
  `commit_production`'s omission pin).
- `test_ceremony_pin_none_refused` — `authorisation_public_key=None`
  → `VerifierConfigError`, message contains
  `authorisation_public_key`.
- `test_ceremony_pin_wrong_type_refused` — subTests over a
  hex string, raw `bytes(32)`, and a `CeremonySigningKey`
  (from the §2.5 fixture's signing key): each →
  `VerifierConfigError` naming `authorisation_public_key`.
- Happy-path assertion (§2.4 row 5):
  `client._authorisation_public_key is CEREMONY_PUB`.

---

# ITEM 1 — Production entry point: `trust/runner.py`

## 1.1 Module and invocation

- **Path:** `trust/runner.py`, run as
  `python3 -m trust.runner` from the repo root. Pattern
  precedent: `trust/verifier_main.py` (`main() -> int` +
  `if __name__ == "__main__": sys.exit(main())`).
- **No command-line arguments.** All configuration comes from
  the environment (§1.2). `main()` takes no argv; if
  `sys.argv[1:]` is non-empty that is a configuration refusal
  (exit 2) — an entry point that silently ignores arguments
  invites operator error about which plan ran.
- **Not** added to `trust/__init__.py` exports (avoids any
  import-cycle question and keeps `import trust` from pulling
  the runner in; `python3 -m trust.runner` does not need it).
- Stdout discipline: **stdout carries only the per-step JSON
  summary lines** (§1.5), one per executed step, nothing else.
  All diagnostics go to stderr as single JSON lines. (The
  verifier subprocesses the client spawns capture their own
  output, so nothing else can pollute stdout.)

## 1.2 Configuration surface (all from `os.environ`)

Three disjoint families. The runner reads `os.environ` once,
then works only from the extracted pieces.

### (a) Verifier env — restricted subset

```python
verifier_env = {k: v for k, v in os.environ.items()
                if k in ALLOWED_ENV_KEYS}
```

`ALLOWED_ENV_KEYS` is imported from `trust.wiring` — never
re-listed in the runner (a second copy is a drift surface;
the wiring suite already pins the set against the shipped
wrapper script). This subset — and only this subset — is what
is passed as the `env` argument to `build_pin_adopter` (which
forwards it to `production_client`). In particular the
`AION_PIN_*` and `AION_RUNNER_*` variables present in the
process environment must never reach `production_client`:
it refuses non-allowlisted keys, and the cycle-23 e2e pins
exactly that refusal for `AION_PIN_DIR`. Presence/validity of
the verifier keys is **not** re-validated in the runner:
`production_client`'s validation is the single source, and it
runs inside `build_pin_adopter` before any `PinStore` or key
load (§1.4 ordering).

### (b) Adopter env — `AION_PIN_*`

Read **only** via the existing
`pin_adopter_config_from_env(os.environ)` →
`PinAdopterEnv(pin_dir, signing_key_path, snapshot_signer_id,
operator_id, evidence_dir)`, which already validates presence,
non-emptiness and absolute paths, naming the variable and
never its value. Variables (existing, unchanged):
`AION_PIN_DIR`, `AION_PIN_SIGNING_KEY_PATH`, `AION_PIN_SIGNER_ID`,
`AION_PIN_OPERATOR_ID`, `AION_PIN_EVIDENCE_DIR`.

### (c) Runner env — `AION_RUNNER_*` (new, this design)

| Variable | Required | Form | Meaning |
|---|---|---|---|
| `AION_RUNNER_STATE_DIR` | yes | absolute path | The loop state dir: contains `state.json` and `calibration/calibration.json` (the real `state/` layout). |
| `AION_RUNNER_PLAN_PATH` | yes | absolute path | The JSON plan file (§1.3). |
| `AION_RUNNER_EXPECTED_SIGNER_ID` | yes | non-empty text | Out-of-band signer pin → `expected_signer_id` for `build_pin_adopter`, and `expected_verifier_signer_id` in the `PinAdopterConfig`. |
| `AION_RUNNER_EXPECTED_KEY_ID` | yes | non-empty text (form `key-<16 lowercase hex>` enforced by `production_client`, not re-checked here) | Out-of-band gate key pin → `expected_key_id`. |
| `AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX` | yes | exactly 64 lowercase hex chars = 32 raw bytes | Out-of-band ceremony pin, hex encoding (§1.2.1). |

No other `AION_RUNNER_*` variables are defined; unknown ones
are ignored (the runner cannot enumerate an operator's whole
environment, and refusing unknown names in *its own* prefix
was considered and rejected — see §1.8).

### 1.2.1 Ceremony key encoding

```python
# in runner config validation:
if not re.fullmatch(r"[0-9a-f]{64}", hex_text):
    refuse("AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX", ...)
raw = bytes.fromhex(hex_text)            # exactly 32 bytes
pub = CeremonyPublicKey(public_key=raw,
                        key_id=public_key_id_for(raw))
```

`CeremonyPublicKey` and `public_key_id_for` are imported from
`signing.ceremony_authorisation`. The `key_id` is **derived**,
never read from the environment: a separately supplied key id
would be a second pin that could disagree with the bytes.
Uppercase hex refuses (the regex is lowercase-only) — one
canonical spelling for a pin, matching the codebase's
lowercase-hex idiom (`key-<16 lowercase hex>`, digest forms).

## 1.3 The plan file

```json
{"steps": [
  {"adopt": true},
  {"cycle": {"coders": ["coder-1", "coder-2", "coder-3"],
             "reviewers": ["rev-1", "rev-2", "rev-3",
                           "rev-4", "rev-5", "rev-6"],
             "verdict": "reconciled",
             "verify_passed": true,
             "delta": {"metric": "tests", "before": 13,
                       "after": 14, "evidence_ref": "ev-1",
                       "verifier": "rev-1"}}}
]}
```

Schema (validated **in full, before anything is constructed**,
§1.4):

- File: UTF-8 JSON, at most 256 KiB, top level an object with
  exactly the key `steps`; `steps` a list of 1–100 step
  objects. (Empty plan refuses: a production invocation that
  does nothing is an operator error, not a no-op success.)
- Each step object has **exactly one** key:
  - `{"adopt": true}` — the value must be exactly `true`
    (`false`, `1`, `"true"` refuse). No other form.
  - `{"cycle": {...}}` — an object with exactly the keys
    `coders`, `reviewers`, `verdict`, `verify_passed`,
    `delta`. Types checked here: `coders`/`reviewers` lists
    of strings; `verdict` a string; `verify_passed` a bool;
    `delta` an object with exactly `metric`, `before`,
    `after`, `evidence_ref`, `verifier` (metric/evidence_ref/
    verifier strings, before/after numbers, bool excluded).
    *Semantic* gate checks (≥3 distinct coders, ≥6 distinct
    reviewers, no overlap, `verdict == "reconciled"`,
    `verify_passed is True`, delta improvement, verifier ∈
    reviewers) are **not** duplicated in the runner — they are
    `CoreLoop.run_one_cycle`'s, and a failure there is a step
    refusal (exit 6, §1.6), not a config refusal. Duplicating
    them would create a second, driftable gate.
- Any deviation — unreadable file, malformed JSON, unknown
  step key, extra key anywhere, wrong type — is a
  configuration refusal (exit 2) naming the plan path variable
  (`AION_RUNNER_PLAN_PATH`) and the step index, never echoing
  plan contents. Because the whole plan is validated up front,
  a malformed step 5 cannot be discovered after steps 1–4 have
  mutated state.

## 1.4 Construction and execution order (fail-fast)

`main() -> int` performs, strictly in order:

1. **Argv check** (§1.1).
2. **Runner-env validation** → frozen `RunnerConfig` dataclass
   (`state_dir: Path`, `plan_path: Path`, `expected_signer_id:
   str`, `expected_key_id: str`, `ceremony_public_key:
   CeremonyPublicKey`). Every refusal names the variable,
   never its value, and exits 2 before anything else happens.
3. **Plan load + full validation** (§1.3) → list of step dicts.
4. **State-layout pre-checks** (existence only, no parsing, no
   construction): `state_dir / "state.json"` is a file and
   `state_dir / "calibration" / "calibration.json"` is a file;
   otherwise config refusal naming `AION_RUNNER_STATE_DIR`.
   This pre-check is load-bearing: `CoreLoop.__init__` creates
   a missing state dir and silently starts from fresh state —
   acceptable for tests, unacceptable for a production entry
   point pointed at the wrong directory. The runner never
   bootstraps state.
5. **Adopter-env validation**: `pin_env =
   pin_adopter_config_from_env(os.environ)`.
6. **Adopter construction — the only adopter construction**:
   ```python
   config = PinAdopterConfig(
       state_path=state_dir / "state.json",
       calibration_path=state_dir / "calibration" / "calibration.json",
       pin_dir=pin_env.pin_dir,
       snapshot_signer_id=pin_env.snapshot_signer_id,
       expected_snapshot_signer_id=pin_env.snapshot_signer_id,
       operator_id=pin_env.operator_id,
       expected_verifier_signer_id=rc.expected_signer_id,
       evidence_dir=pin_env.evidence_dir)
   adopter = build_pin_adopter(
       verifier_env,
       expected_signer_id=rc.expected_signer_id,
       expected_key_id=rc.expected_key_id,
       authorisation_public_key=rc.ceremony_public_key,
       signing_key_path=pin_env.signing_key_path,
       config=config)
   ```
   (`expected_snapshot_signer_id` = `snapshot_signer_id`: the
   `PinAdopterConfig` field comment records that they are equal
   in this deployment and kept separate only because verify-side
   pinning is the wrapper's contract.) Any exception from
   steps 5–6 is a configuration refusal (exit 2): these are
   factories validating configuration — `production_client`'s
   `VerifierConfigError`, `pin_adopter_config_from_env`'s and
   `build_pin_adopter`'s `SigningError`s — and nothing has been
   constructed that can mutate loop state or consume an
   authorisation. (A `PinStore` object and a loaded signing key
   may exist by then; neither writes anything at construction
   in a way the plan depends on, and no cycle has run.)
7. **Loop construction — the only loop construction**, exactly:
   ```python
   loop = CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))
   ```
   A `CorruptStateError` here is a step-0 refusal: exit 6 with
   a stderr line naming the state dir variable — state exists
   but cannot be trusted, which is not a config typo.
8. **Steps execute in order** (§1.5). First failure stops the
   run; later steps never execute.

The runner contains **no** `VerifierClient(...)` and **no**
`MemoryStore(...)` construction, in any form — and also no
`PinStore(...)` and no direct `VerifierClient` import. Its
only constructions are `CoreLoop` (not a lint-watched class),
`PinAdopterConfig`, `CeremonyPublicKey`, and its own
`RunnerConfig`.

### Trust-lint consequence (must land with the runner)

`tests/test_trust_lint.py` scans production roots including
`trust/`, counting attribute calls by name. The runner's cycle
step is an attribute call `loop.run_one_cycle(...)` — kind
`run_one_cycle` — so the build must add exactly one allowlist
entry:

```python
("trust/runner.py", "run_one_cycle"): (
    1, "cycle 24: THE production entry point — its plan cycle "
       "steps run through the hooked CoreLoop it constructs "
       "(cycle_hook=pin_cycle_hook(adopter)); the hook, not "
       "this call, performs adoption. It constructs no client "
       "or store itself"),
```

and the runner source must contain **exactly one**
`run_one_cycle` call node (route every cycle step through the
single call site in the step executor; do not add a second
convenience call in a helper). Verified against the scanner:
`snapshot_and_adopt`, `build_pin_adopter`, `pin_cycle_hook`,
`production_client`, `pin_adopter_config_from_env` are not
watched names; `CoreLoop` is not a watched construction;
`test_production_constructions_confined_to_wiring` is
unaffected. Calling `run_one_cycle_and_pin` instead was
rejected: it refuses a hooked loop by design (double wiring),
and the task fixes the hooked form as the only form.

## 1.5 Step execution and summary lines

One JSON object per executed step, printed to stdout,
`json.dumps(..., sort_keys=True)`, flushed per line:

- Adopt step → `result = adopter.snapshot_and_adopt()`:
  ```json
  {"step": 0, "kind": "adopt", "outcome": "advanced",
   "pin_seq": 14, "pin_hash": "<64 hex>",
   "record_reason": null}
  ```
  `outcome` ∈ `advanced | reanchored | already_current`
  (from `AdoptionResult.outcome`); `pin_seq`/`pin_hash` from
  `result.pin["cycle_seq"]` / `result.pin["payload_hash"]`;
  `record_reason` is `result.record.reason` when a record
  exists (`reanchored`), else `null`.
- Cycle step → `entry = loop.run_one_cycle(coders, reviewers,
  verdict, verify_passed, delta)` (the single call site):
  - recorded: `{"step": i, "kind": "cycle", "outcome":
    "recorded", "cycle_id": entry["cycle_id"], "item_id":
    entry["item_id"]}`.
  - idle (`entry is None`, no pickable backlog item):
    `{"step": i, "kind": "cycle", "outcome": "idle"}` — not an
    error; execution continues, exit code unaffected. The hook
    does not fire for idle cycles (loop contract), so no pin
    movement is implied or claimed.
  - **Known limitation, stated in the module docstring:**
    `CoreLoop.run_one_cycle` invokes the hook and discards its
    return value, so a cycle step's summary cannot report the
    hook's `AdoptionResult`. The line claims the cycle was
    recorded and the hook fired without raising — nothing
    more. (Changing `CoreLoop` to surface the hook result is
    out of scope for cycle 24; the subsequent adopt step, or
    the next run, reports pin state authoritatively.)

## 1.6 Exit codes

| Code | Meaning |
|---|---|
| 0 | Every step executed; every summary line printed. (Idle cycle steps included.) |
| 2 | **Configuration refusal** — argv present; runner env missing/empty/relative/malformed (incl. ceremony hex); plan unreadable/malformed/schema-invalid; state layout pre-check failed; adopter-env or factory refusal in steps 5–6 of §1.4. Nothing constructed that mutates state; no step executed; nothing on stdout; one stderr JSON line `{"error": "config_refusal", "variable": "<name>", "detail": "<problem>"}` (for plan errors, `variable` is `AION_RUNNER_PLAN_PATH` and `detail` names the step index / structural problem, never plan values). |
| 3 | **Adoption refused** — a `{"adopt": …}` step raised `PinAdoptionRefused`: integrity refusal, nothing persisted by the adopter. Summary line for the failed step printed with `"outcome": "adoption_refused"` and `"error": "<exception class name>"`; run stops. |
| 4 | **Adoption burned** — an adopt step raised `PinAdoptionBurned`: a consumption committed (or may have committed) and adoption did not complete. Summary line `"outcome": "adoption_burned"`. Distinct from 3 because operator response differs (recovery is a `burned_unadopted` ceremony / `adopt_returned`, not a fresh retry). Run stops. |
| 5 | **Cycle recorded, pin pending, alert** — a `{"cycle": …}` step's hook raised `PinAdoptionBurned` or `PinAdoptionRefused`. The cycle **is** persisted in state; the pin did not move. Summary line: `{"step": i, "kind": "cycle", "outcome": "cycle_recorded_pin_pending", "cycle_id": <from exc.cycle_entry>, "item_id": <from exc.cycle_entry>, "adoption_error": "PinAdoptionBurned"|"PinAdoptionRefused"}`. This is the `pin_cycle_hook` contract surfaced distinctly, per the mandate — it must not be folded into 3/4, because the state of the world differs (a cycle exists that no pin attests). Run stops. |
| 6 | **Step refused** — any other step-time refusal: `InvalidTransition` from the loop's gates, `CorruptStateError` (including at loop construction, step 0), `SigningError`/`PinStoreError` escaping an adopt step outside the two typed adoption exceptions. Summary line `"outcome": "step_refused"`, `"error": "<class name>"`. Run stops. |
| 1 | Anything else (unexpected exception): traceback to stderr, no summary line for the failed step. Reserved so 2–6 keep precise meanings. |

Error lines never carry env values, plan values, or key
material — class names and variable names only (exception
*messages* from the adopter/loop are not echoed: several embed
operational detail, and stdout/stderr of a production entry
point is a log surface).

## 1.7 Demonstration test — `tests/test_trust_runner.py`

Subprocess end-to-end, mirroring `tests/test_cycle23_live_run.py`'s
shape but driving **the entry point itself**, never the
in-process factories, for the production path. Constants
(`CODERS`, `REVIEWERS`, `DELTA` with before 13 / after 14,
`OPERATOR`, `SIGNER`, `SNAP_SIGNER`) are taken from the
cycle-23 suites / harness, not re-invented.

### Fixture (`RunnerFixture.setUp`)

- `real_hash_before = sha256(REPO_ROOT / "state" / "state.json")`.
- Temp base (chmod 0o700, harness idiom); **byte copy** of the
  real state dir: `shutil.copytree(REPO_ROOT / "state",
  base / "state")` — the runner is pointed at the copy only.
- `home = provision_production_home(base / "prod-home")`
  (the cycle-23 harness: research-INIT bootstrap, then
  production env, INIT stripped).
- Base subprocess env: `{"PATH": "/usr/bin:/bin", "HOME":
  str(Path.home()), "PYTHONPATH": str(REPO_ROOT)}` plus
  `home.env` (verifier family) plus:
  - `AION_PIN_DIR = base / "pins"`,
    `AION_PIN_SIGNING_KEY_PATH = home.snapshot_key_path`,
    `AION_PIN_SIGNER_ID = SNAP_SIGNER`,
    `AION_PIN_OPERATOR_ID = OPERATOR`,
    `AION_PIN_EVIDENCE_DIR = home.evidence_dir`;
  - `AION_RUNNER_STATE_DIR = base / "state"`,
    `AION_RUNNER_EXPECTED_SIGNER_ID = SIGNER`,
    `AION_RUNNER_EXPECTED_KEY_ID = home.verifier_key_id`,
    `AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX =
    home.pub.public_key.hex()`,
    `AION_RUNNER_PLAN_PATH` set per invocation.
  Note the env deliberately contains all three families at
  once: a green run also proves the §1.2(a) subset restriction
  works (the `AION_PIN_*`/`AION_RUNNER_*` names in the process
  env do not reach `production_client`).
- Helper `_run_runner(plan_steps) -> CompletedProcess`: writes
  the plan JSON to a fresh file under base, runs
  `[sys.executable, "-m", "trust.runner"]` with `cwd=REPO_ROOT`,
  `capture_output=True`, `timeout=120`.
- Helper `_parse_lines(proc)`: `[json.loads(l) for l in
  proc.stdout.decode().splitlines()]`.
- Test-side helpers for assertions only (never the production
  path): `PinStore(base / "pins", state_dir=copy).read_all(
  signing_key=home.snapshot_key)`,
  `CeremonyConsumptionLedger(home.verifier_home).entries()`.

### Main test — `test_runner_replays_cycle23_live_run_shape`

1. **Invocation 1**, plan `[{"adopt": true}, {"cycle": {...}}]`
   (cycle fields = the live-run constants):
   exit 0; exactly 2 stdout lines:
   line 0 `outcome == "reanchored"`, `pin_seq == 13`,
   `record_reason == "initial_anchor"` (genesis adopt @13);
   line 1 `outcome == "recorded"`, `cycle_id == 14`,
   `item_id` equals `CoreLoop(copy).pick_next()["id"]` probed
   test-side before the invocation (asserted, never assumed —
   the live-run precedent). Afterwards: pin seq 14 (dense
   advance via the hook, no new record), consumptions == 1.
2. **Gap, test-side only:** two hookless cycles on the copy via
   a plain test-side `CoreLoop(copy)` (seq 15, 16 unpinned) —
   exactly as the live-run test does; the runner has no
   hookless mode and must not grow one. Pin still 14,
   consumptions still 1.
3. **Invocation 2**, plan `[{"adopt": true}, {"adopt": true}]`:
   exit 0; line 0 `outcome == "reanchored"`, `pin_seq == 16`,
   `record_reason == "chain_gap_recovery"`; line 1 `outcome ==
   "already_current"`, `pin_seq == 16`, `record_reason is
   null`. Consumptions == **exactly 2** in total. Pin store:
   pin seq 16, history length 2.
4. **Real state untouched:**
   `sha256(REPO_ROOT / "state" / "state.json") ==
   real_hash_before`.

### Negative tests (same file)

- `test_runner_missing_ceremony_key_hex_is_config_refusal` —
  env without `AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX`: exit 2,
  stdout empty, stderr names the variable; the state copy's
  sha256 unchanged and `base / "pins"` was never created
  (proves refusal precedes construction).
- `test_runner_malformed_ceremony_key_hex_is_config_refusal` —
  subTests: 63 chars, 66 chars, 64 chars with a non-hex char,
  uppercase spelling: each exit 2 naming the variable.
- `test_runner_missing_state_json_is_config_refusal` —
  `AION_RUNNER_STATE_DIR` pointing at an empty dir: exit 2
  naming `AION_RUNNER_STATE_DIR`, and the dir is still empty
  afterwards (no `CoreLoop` fresh-state bootstrap happened).
- `test_runner_malformed_plan_refuses_before_any_step` — plan
  `[{"adopt": true}, {"bogus": 1}]`: exit 2, stdout empty, pin
  store absent / consumptions 0 (proves whole-plan validation
  precedes step 1's execution — the adopt never ran).
- `test_runner_cycle_gate_refusal_is_step_refused` — plan with
  one cycle step whose `verdict` is `"split"`: exit 6, line 0
  `outcome == "step_refused"`; state copy seq unchanged.
- `test_runner_extra_argv_is_config_refusal` —
  `python3 -m trust.runner extra`: exit 2, stdout empty.

(Item-2's unit tests live in the wiring suite, §2.7; the
runner tests exercise the mandatory pin only through the
hex-config surface above.)

## 1.8 Risks, and alternatives rejected

- **Risk — hook result invisibility (§1.5).** Accepted and
  documented rather than fixed by changing `CoreLoop` in this
  cycle; the alternative (runner re-reads the pin store after
  each cycle step) was rejected: the runner holds no signing
  key handle of its own (the adopter loads it internally and
  does not expose it), and adding a second `PinStore`
  construction + key load to the runner duplicates the
  adopter's custody surface for a cosmetic summary field.
- **Risk — exit-code collision with the verifier's.** The
  runner's 2/3 are its own (verifier subprocess exit codes are
  captured by the client and surfaced as exceptions, never as
  the runner's exit). Documented in the module docstring to
  prevent operator confusion.
- **Risk — plan as code execution surface.** The plan names
  coders/reviewers/verdict/delta only; it cannot name paths,
  keys, operators or env. All authority stays in env +
  out-of-band pins. A plan file is therefore not a credential
  and needs no signature — stated in the docstring so nobody
  "fixes" it later by signing plans while leaving env unsigned.
- **Rejected — CLI arguments / config file for runner vars.**
  The mandate says environment-only, fail-fast; a second
  config channel is a second place for pins to disagree.
- **Rejected — ceremony key from a file path variable**
  (`AION_RUNNER_CEREMONY_PUBLIC_KEY_PATH`). Adds a file-read
  surface (which loader? which forbidden roots? the seed
  loader refuses repo-internal paths and demands owner-only
  modes — wrong discipline for public material) to deliver 32
  public bytes that hex env carries exactly. Hex also matches
  the codebase's key-file text idiom.
- **Rejected — runner derives the ceremony pin from
  `AION_CEREMONY_SIGNING_SEED_PATH`.** That would hand the
  entry point secret material to derive a public pin,
  collapsing the client-side key separation. Never.
- **Rejected — long-running daemon / plan-watching runner.**
  One invocation = one validated plan = one process exit;
  supervision belongs to the operator's tooling, and a daemon
  would hold a constructed adopter across state changes it
  cannot re-validate.
- **Rejected — refusing unknown `AION_RUNNER_*` variables.**
  Tempting typo-catcher, but the runner cannot distinguish a
  typo from a future variable set by a newer wrapper for an
  older binary; the required-variable checks already catch
  the harmful typos (a misspelled required name is a missing
  required name, exit 2).
- **Rejected — `deploy/` placement for the module.** `deploy`
  is a lint production root and a deployment-artefact tree;
  the entry point is production *code* and belongs with the
  trust package it composes. `python3 -m trust.runner` also
  matches the `trust.verifier_main` precedent operators
  already know.
- **Honesty qualifier (unchanged from cycle 23):** the runner
  proves production *mode* end-to-end under same-user spawn on
  this VM. It is not production *deployment* evidence: no
  separate OS user exists here, `launch="wrapper"` remains
  refused by design, and the runner's docstring must say so in
  the same terms `trust/pin_adoption.py`'s module docstring
  uses. Item 1 closes the "no non-test entry point" defect;
  it does not close the deployment gate.

---

## Build checklist implied by this design (for the build seats)

1. `trust/wiring.py`: signature, two-branch refusal, comment +
   docstring rewrites (§2.2–2.3). Lint counts unchanged.
2. `deploy/verifier-identity/README.md`: pin-warning rewrite
   (§2.3 item 4).
3. `tests/test_trust_wiring.py`: `CEREMONY_PUB` fixture; update
   call sites at lines 149 (helper), 375, 388, 400, 422, 438,
   456, 911; new Item-2 tests (§2.7).
4. `trust/runner.py`: new module per §1.1–1.6.
5. `tests/test_trust_lint.py`: one allowlist entry
   `("trust/runner.py", "run_one_cycle"): 1` (§1.4).
6. `tests/test_trust_runner.py`: new suite per §1.7.
7. No changes to `trust/client.py`, `trust/pin_adoption.py`,
   `core/loop.py`, `tests/test_trust_production_e2e.py`,
   `tests/test_trust_pin_adoption.py`,
   `tests/test_cycle23_live_run.py`.
