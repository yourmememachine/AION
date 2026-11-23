# Cycle 19 — Design note, seat B: protected operator authority + evidence provenance, verifier-side

Status: DESIGN ONLY. No production code in this note's round.
Baseline: 1245 tests OK (skipped=26). Scope: implement the owner decision in
`internal/DECISION-PROTECTED-GATE-EXTENSION.md` (EXTEND) for the two P0 gates
both external seats set in CROSS-CHECK-9/10:

- P0: operator authority from a separately protected boundary — never from
  the caller (the caller-supplied `authorised_operators` list in
  `signing/pin_ceremony.py` is the circularity being removed).
- P0: evidence provenance AUTHENTICATED and bound to the recovery event
  (old pin, candidate, reason, operator, ceremony id); evidence reuse
  across events refused. Named adversarial tests: invented operator list,
  random evidence hash, evidence reuse across events.

Design rule throughout: existing machinery only, no new dependencies, every
pattern copied from a named existing pattern (attestation envelope,
`issue_attestation` validation order, ledger-before-return, strict body
key sets, config-only-from-env).

---

## 1. New protected config: `AION_CEREMONY_OPERATORS`

### 1.1 Semantics

- New optional env var `AION_CEREMONY_OPERATORS`: comma-separated operator
  ids, each matching the verifier's existing id grammar
  `_ID_RE = ^[a-z0-9][a-z0-9_-]{0,63}$` (`trust/verifier_main.py`).
- Loaded ONLY in `_load_config()` from `os.environ` — never from the
  request. A request body that carries an operator list (e.g. a stray
  `authorised_operators` key) is a strict-key-set violation (§3.1), which
  is exactly how the "invented operator list" adversarial test dies: there
  is no field for it to arrive in.
- **Fail-closed, scoped to the new mode.** The var is NOT added to the
  required-config check in `_load_config` and startup does NOT refuse when
  it is absent: gate / sealed_eval / verify_envelope / submit_claim /
  issue_attestation deployments (including every existing test fixture)
  must be unaffected. Absent or empty value ⇒ `ceremony_operators = ()`
  on `_Config`, and mode `ceremony_authorise` refuses every request with
  the config-class refusal in §3.3. Making it startup-required was
  considered and rejected: it would break gate-only production deployments
  and the entire existing verifier test surface for a mode they never call.
- **Malformed value ⇒ startup refusal** (`_config("verifier_misconfigured",
  …)`, exit 3), consistent with how bad TTL / bad budgets are treated —
  the env file is the operator's own protected configuration, so a
  malformed list is a deployment error, not a per-request event. Malformed
  means: any comma segment that does not fullmatch `_ID_RE` (this refuses
  whitespace-padded spellings — no stripping, mirroring the
  `AION_DEPLOYMENT_MODE` no-strip/no-case-fold philosophy), an empty
  segment (`a,,b`, trailing comma), a duplicate id, or more than 64
  entries. Detail strings name the variable, never echo the value
  (wiring.py's convention).
- Stored on `_Config` as a new keyword field `ceremony_operators: tuple`
  (default `()`), populated in the `_Config(...)` return of `_load_config`.
- Production note: do NOT add the var to `trust/wiring.py`'s
  `REQUIRED_ENV_KEYS` — `production_client` builds a *gate* client;
  requiring ceremony config there would be the same over-reach as
  startup-required. Mode-level refusal is the scoped fail-closed point.

### 1.2 Every place that must change, in step (14 → 15)

The allowlist currently exists in **four** live copies plus pinned tests.
All must move together; the tests below are the tripwires that enforce it.

| # | File | Change |
|---|------|--------|
| 1 | `deploy/verifier-identity/run-verifier.sh` | Append `AION_CEREMONY_OPERATORS` to `ALLOWED_KEYS` (14→15). This is the shipped ground truth all mirrors parse or copy. |
| 2 | `trust/wiring.py` | Add the name to `ALLOWED_ENV_KEYS`; fix the two count mentions (module docstring "ALLOWED_KEYS, 14 names" and the comment above `ALLOWED_ENV_KEYS`) to 15. Do NOT add to `REQUIRED_ENV_KEYS`. |
| 3 | `deploy/verifier-identity/health_check.py` | Add the name to its replicated `ALLOWED_KEYS` tuple (lines ~79–92). Do NOT add to its `REQUIRED_KEYS` — a gate-only deployment must still pass health check. |
| 4 | `deploy/verifier-identity/setup.sh` | Add `AION_CEREMONY_OPERATORS=` (empty, with an explanatory comment) to the `verifier.env` template heredoc, so a fresh deployment can see and fill the knob. Empty in the template = unset semantics (§1.1). |
| 5 | `deploy/verifier-identity/README.md` | Mention the new var in the env-file description (docs only; no test pins it). |
| 6 | `trust/verifier_main.py` | Docstring config list gains the var (optional; absence disables only `ceremony_authorise`); `_load_config` parses it per §1.1; `_Config` gains the field. NOTE: `tests/test_verifier_deploy.py::test_every_verifier_main_env_var_is_allowlisted` regex-extracts every `AION_[A-Z_]+` token from this file and asserts ⊆ wrapper allowlist — step 1 must land before/with this or that test goes red. |

Test updates that pin the count (expected red until updated, update in the
same commit):

- `tests/test_trust_wiring.py::test_allowlist_is_the_shipped_14_names` →
  rename to `…_15_names`, assert `len(ALLOWED_ENV_KEYS) == 15`, keep the
  `AION_SHIP_ANCHOR_PATH` negative assertion.
- `tests/test_trust_wiring.py::test_allowlist_matches_wrapper_script_at_test_time`
  → `len(wrapper_keys) == 15` (the set-equality half already self-updates
  from the wrapper script).
- `tests/test_verifier_deploy.py` → add `test_ceremony_operators_key_allowlisted`
  mirroring `test_budget_keys_allowlisted`; the two invariant tests
  (every-verifier-main-var, template-keys) then cover steps 4/6 automatically.
- `tests/test_trust_production_deploy.py` test_31
  (`test_31_wrapper_probe_sees_only_allowlisted_environment`) hardcodes the
  14-name allowlisted set for its `assertLessEqual` — add the new name for
  parity so a probe env file carrying it is judged correctly.

Friction flag (seat A): whoever owns deploy/health-check should confirm
health_check.py's `ALLOWED_KEYS` is a *mirror by copy*, not parsed from the
wrapper — from the source it is a literal tuple, so it silently drifts if
step 3 is skipped; no test I found cross-checks it against the wrapper.

---

## 2. New signing module: `signing/ceremony_authorisation.py`

Modelled line-for-line on `signing/attestation.py` (same helpers imported
from `signing/gate_decision.py`: `ALG`, `CLOCK_SKEW_SECONDS`,
`TTL_MIN_SECONDS`, `TTL_MAX_SECONDS`, `SigningKey`, `_canonical`,
`_check_hex64`, `_check_id`, `_check_text`, `_normalise_time`, `_now`,
`_parse_time`, `_sha256`, `key_id_for`). No new crypto, no new deps.

### 2.1 Constants

```python
CEREMONY_AUTHORISATION_DOMAIN = "signed-ceremony-authorisation-v1"
PURPOSE_CEREMONY_AUTHORISATION = "pin-ceremony-authorisation"
CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS = 900
CEREMONY_AUTHORISATION_TTL_MAX_SECONDS = 900   # hard cap, see §2.4
```

Domain separation: a distinct domain string means a gate decision or an
attestation MAC can never be reinterpreted as a ceremony authorisation
(the blob MACed is `DOMAIN + "\n" + ALG + "\n" + key_id + "\n" +
payload_hash`, exactly as in attestation.py's `_mac`).

### 2.2 Payload (the exact allowlisted projection that gets MACed)

```python
def ceremony_authorisation_payload(
        *, signer_id, key_id, operator_id, ceremony_id, reason,
        old_pin, candidate, evidence_hash, evidence_ref,
        signed_at, expires_at) -> dict
```

Returns:

```python
{
  "v": "signed-ceremony-authorisation/1",
  "alg": ALG,                                   # "hmac-sha256"
  "purpose": PURPOSE_CEREMONY_AUTHORISATION,
  "signer_id": signer_id,                       # the VERIFIER's signer id
  "key_id": key_id,                             # the VERIFIER's key id
  "operator_id": operator_id,
  "ceremony_id": ceremony_id,
  "reason": reason,
  "old_pin": {"cycle_seq": int, "payload_hash": hex64} | None,
  "candidate": {"cycle_seq": int, "payload_hash": hex64,
                "signer_id": id, "key_id": id},
  "evidence_hash": hex64,
  "evidence_ref": str,
  "signed_at": iso, "expires_at": iso,
}
```

Validation inside the payload projection (raise `SigningError`; this is
the defence-in-depth copy of the mode's pre-checks, §3.2 — same split as
attestation_payload re-validating what the verifier already checked):

- `_check_id` on signer_id, key_id, operator_id, ceremony_id,
  candidate["signer_id"], candidate["key_id"].
- `reason` must be a member of `signing.pin_ceremony.REASONS` — import
  `REASONS` and `_NO_PIN_REASONS` from `signing/pin_ceremony.py` (single
  source of truth for the 4 reasons: `initial_anchor`,
  `chain_gap_recovery`, `lost_pin`, `corrupted_pin`). No second copy of
  the allowlist may exist verifier-side.
- Reason/pin coherence, mirroring `reanchor_pin`'s gate-on-state rule:
  `old_pin is None` ⇒ reason ∈ `_NO_PIN_REASONS`;
  `old_pin` present ⇒ reason == `chain_gap_recovery`. Anything else
  refuses.
- Pin shapes: `old_pin` is `None` or a dict with EXACTLY
  `{"cycle_seq", "payload_hash"}`; `candidate` is a dict with EXACTLY
  `{"cycle_seq", "payload_hash", "signer_id", "key_id"}`. Sequences are
  `int`, not `bool`, ≥ 0 (pin_ceremony's `_is_seq` rule); hashes via
  `_check_hex64`.
- Sequence relation (when old_pin present):
  `candidate.cycle_seq >= old_pin.cycle_seq + 2`. Equal (same-seq fork),
  backwards, and +1 (chained successor belongs to `advance_pin`, unchained
  +1 is an integrity failure) all refuse — the same relations
  `reanchor_pin` refuses, checked here so an authorisation for a
  non-ceremony movement is un-issuable, not merely unusable.
- `_check_hex64(evidence_hash)`; `evidence_hash != candidate["payload_hash"]`
  and, when old_pin present, `evidence_hash != old_pin["payload_hash"]`
  (verifier-side mirror of pin_ceremony's non-equality rule — see §6.3
  for why only these two comparisons are possible at this layer).
- `_check_text(evidence_ref, …, 2000)` (attestation's evidence_ref cap).
- TTL window: `TTL_MIN_SECONDS <= expires_at - signed_at <=
  CEREMONY_AUTHORISATION_TTL_MAX_SECONDS` (tighter than the global
  `TTL_MAX_SECONDS`; see §2.4).
- Deliberate NON-rule: signer_id need NOT equal operator_id. This is the
  one structural divergence from attestation.py's signer==attester
  discipline, and it is the point of the design: the attester is the
  *verifier*, attesting that a listed operator presented this evidence
  for this event. The operator holds no key and signs nothing.

### 2.3 Dataclass, sign, verify, serialisation

```python
@dataclass(frozen=True)
class SignedCeremonyAuthorisation:
    operator_id: str; ceremony_id: str; reason: str
    old_pin: dict | None; candidate: dict
    evidence_hash: str; evidence_ref: str
    signer_id: str; key_id: str
    signed_at: str; expires_at: str
    payload_hash: str; authorisation_id: str; signature: str
    def payload(self) -> dict: ...

def sign_ceremony_authorisation(
        *, signing_key: SigningKey, signer_id, operator_id, ceremony_id,
        reason, old_pin, candidate, evidence_hash, evidence_ref,
        ttl_seconds=CEREMONY_AUTHORISATION_TTL_DEFAULT_SECONDS,
        now=None) -> SignedCeremonyAuthorisation

def verify_ceremony_authorisation(
        signed, *, signing_key: SigningKey,
        expected_operator_id=None, expected_ceremony_id=None,
        expected_reason=None,
        expected_old_pin=_CONTEXT_UNSPECIFIED,
        expected_candidate=None,
        expected_evidence_hash=None, expected_evidence_ref=None,
        now=None) -> tuple   # () == authentic, unexpired, bound as expected
```

- `sign_…` mirrors `sign_attestation`: key-id consistency check
  (`signing_key.key_id != key_id_for(signing_key.key)` refuses), ttl must
  be a non-bool `int` in `[TTL_MIN_SECONDS,
  CEREMONY_AUTHORISATION_TTL_MAX_SECONDS]`, `now=` is a test seam only
  (same warning as gate_decision's docstring; the verifier mode never
  passes it).
- `authorisation_id = _sha256(_canonical({"v": DOMAIN, "payload_hash":
  payload_hash, "key_id": key_id}))` — the `_attestation_id` pattern.
- `verify_…` mirrors `verify_signed_attestation`'s contract: malformed
  envelope raises `SigningError`; authentic-but-failing returns reasons
  from exactly this vocabulary: `key_id_inconsistent`, `unknown_key`,
  `malformed_payload`, `payload_hash_mismatch`,
  `authorisation_id_mismatch`, `signature_mismatch`, `operator_mismatch`,
  `ceremony_mismatch`, `reason_mismatch`, `old_pin_mismatch`,
  `candidate_mismatch`, `evidence_mismatch`, `evidence_ref_mismatch`,
  `signed_in_future`, `expired`. `expected_old_pin` uses pin_ceremony's
  `_CONTEXT_UNSPECIFIED` sentinel pattern: omitted = asserts nothing;
  explicit `None` = asserts the authorisation is a no-pin authorisation;
  a dict = asserts exact (seq, hash) equality. `expected_candidate`
  asserts exact dict equality of the 4-field candidate projection.
  A `()` result proves issuance + binding; it does NOT prove the
  operator should have been authorised (that was decided at issuance
  against the env list) nor that the evidence artefact is genuine (§6).
- Serialisation mirrors attestation exactly:
  `ceremony_authorisation_envelope_to_dict` /
  `ceremony_authorisation_envelope_from_dict` with strict key sets
  (outer: `{"operator_id","ceremony_id","reason","old_pin","candidate",
  "evidence_hash","evidence_ref","signer_id","key_id","signed_at",
  "expires_at","payload_hash","authorisation_id","signature"}`;
  candidate inner exactly its 4 keys; old_pin `None` or exactly its 2
  keys), hex64 checks on payload_hash/authorisation_id/signature, and a
  closing `signed.payload()` re-validation in `from_dict`; plus
  `…_to_json` / `…_from_json` reusing attestation's duplicate-key /
  non-finite-number parser hooks pattern.

### 2.4 TTL choice

900 s default, 900 s hard cap for this envelope type (within the global
`[60, 172800]` bounds, deliberately far under the 48 h ceiling).
Rationale: an authorisation is a *live operator act* — the operator is
present, the re-anchor is the next step, and nothing in the flow has the
approval-workflow latency that justifies gate decisions' 48 h bound.
A short window shrinks the replay surface to minutes; the ledger
single-use (§4) is the primary anti-replay control and the TTL is the
bound on how long a withheld/leaked envelope stays live. The verifier
mode passes `ttl_seconds=min(config.ttl_seconds,
CEREMONY_AUTHORISATION_TTL_MAX_SECONDS)`, so an operator who configured
a shorter verifier TTL keeps it, and one who configured 48 h does not
silently get 48 h ceremony authorisations.

---

## 3. New verifier mode: `ceremony_authorise`

### 3.0 Plumbing

- `trust/protocol.py`: add `"ceremony_authorise"` to `MODES` (currently
  the 5-tuple `gate, sealed_eval, verify_envelope, submit_claim,
  issue_attestation`). Without this the request is refused by the
  protocol layer before the verifier sees it. (Shared file — seat A
  coordination, §7.)
- `trust/verifier_main.py`: `_mode_ceremony_authorise(config, body)`
  added to `_MODES`; module docstring gains the mode + the
  `AION_CEREMONY_OPERATORS` config line; the docstring's honesty
  statement gains one sentence (§6.4 wording).

### 3.1 Strict body key set

```python
_CEREMONY_BODY_KEYS = {"operator_id", "ceremony_id", "reason",
                       "old_pin", "candidate",
                       "evidence_hash", "evidence_ref"}
```

`set(body) != _CEREMONY_BODY_KEYS` ⇒ `_malformed("malformed_request", …)`
(exit 2). All seven keys required (old_pin's VALUE may be null; the key
may not be absent — absent-vs-null is exactly the ambiguity the strict
set exists to kill). Success result: `{"authorisation":
ceremony_authorisation_envelope_to_dict(signed)}` — the single key,
mirroring issue_attestation's `{"signed_attestation": …}`.

### 3.2 Validation order (cheap first, ledger last — the issue_attestation lesson)

`_mode_issue_attestation`'s documented discipline is copied verbatim in
spirit: deterministic input validation runs BEFORE anything is consumed
or ledgered, so a bad spelling can never burn a single-use asset. Order:

0. **Config gate (before body validation).** If
   `not config.ceremony_operators`: raise
   `_config("ceremony_operators_unconfigured", "…")` (exit 3, unsigned).
   A deployment that never configured ceremony operators refuses the
   mode wholesale, whatever the body says.
1. **Strict key set** (§3.1) ⇒ `malformed_request` (exit 2).
2. **Cheap field validation** ⇒ all `malformed_request` (exit 2), no
   ledger touched, in this order:
   a. `operator_id`, `ceremony_id`: `_check_id` (via try/except
      `SigningError` → malformed, as `_mode_issue_attestation` does for
      proposal_id).
   b. `reason`: must be `str` and ∈ `pin_ceremony.REASONS`.
   c. `evidence_hash`: `_check_hex64`.
   d. `evidence_ref`: `_check_text(…, 2000)` equivalent — non-empty
      text, no control/invisible chars (reuse signing's `_check_text`
      via a local try/except, as the verifier already imports signing
      helpers).
   e. Pin shapes: `old_pin` is `None` or a dict with exactly
      `{"cycle_seq","payload_hash"}`; `candidate` a dict with exactly
      `{"cycle_seq","payload_hash","signer_id","key_id"}`; sequences
      non-bool `int` ≥ 0; hashes hex64; candidate ids `_check_id`.
      (Capture each field once via `.get`, pin_ceremony's cycle-14 rule.)
   f. Reason/pin coherence (§2.2): old None ⇔ no-pin reason; old
      present ⇔ `chain_gap_recovery`.
   g. Sequence relation: old present ⇒
      `candidate.cycle_seq >= old.cycle_seq + 2`.
   h. Evidence non-equality: `evidence_hash != candidate.payload_hash`;
      old present ⇒ `evidence_hash != old_pin.payload_hash`.
3. **Operator membership** (first non-malformed refusal):
   `operator_id not in config.ceremony_operators` ⇒
   `_config("ceremony_operator_not_authorised", …)` (exit 3, UNSIGNED).
   This is a config-class refusal by deliberate design: there is no
   signed-reject artefact for this mode at all. Signing a rejection
   would (i) mint verifier artefacts at the request of a non-operator,
   (ii) imply the request reached a decision stage it never reached,
   and (iii) break the ledger inference (a "sign" entry for something
   that authorised nothing). Precedent: unverifiable eval evidence in
   gate/issue_attestation is likewise an unsigned `_config` refusal,
   never a signed reject built on it. The refusal is NOT ledgered
   (nothing was signed; appends record issuances and claims, and this
   is neither) — see §6.5 for the stated cost.
4. **Anti-replay scan** (§4.2) against the ceremony journal: ceremony_id
   already present ⇒ `_config("ceremony_replay_refused", …)`;
   evidence_hash already present (necessarily under a different
   ceremony_id/event, since step order checks ceremony first) ⇒
   `_config("evidence_reuse_refused", …)`. Both exit 3, unsigned,
   nothing written. A journal that cannot be read ⇒
   `_config("ledger_failed", …)` — never scan a partial history and
   proceed.
5. **Sign**: `sign_ceremony_authorisation(signing_key=config.signing_key,
   signer_id=config.signer_id, ttl_seconds=min(config.ttl_seconds, 900),
   …)`. A `SigningError` here after steps 2–4 passed is an internal
   inconsistency ⇒ map to `_malformed("signing_input_error", …)` (the
   issue_attestation precedent for signer-raised SigningError).
6. **Ledger BEFORE return** (§4.3), then `_update_anchor(config)`, then
   return `{"authorisation": …}`.

No step before 6 writes anything. Steps 0–4 are pure reads/checks.

### 3.3 Refusal-code summary

| Code | Exit | When |
|------|------|------|
| `ceremony_operators_unconfigured` | 3 | env list unset/empty (mode disabled) |
| `verifier_misconfigured` | 3 | env list malformed (at startup, `_load_config`) |
| `malformed_request` | 2 | key set, field forms, coherence, sequence, non-equality |
| `ceremony_operator_not_authorised` | 3 | operator_id not on the env list (unsigned, unledgered) |
| `ceremony_replay_refused` | 3 | ceremony_id already authorised (any event) |
| `evidence_reuse_refused` | 3 | evidence_hash already authorised for another event |
| `ledger_failed` | 3 | journal/ledger unreadable or append failed; envelope withheld |
| `signing_input_error` | 2 | signer refused after validation (defence-in-depth trip) |

---

## 4. Single-use / anti-replay: ledger design

### 4.1 Why `SigningLedger.entries()` scanning alone cannot work

Checked against the actual entry shape: `SigningLedger.EXTRA_KEYS` is
the fixed frozenset `{decision_id, payload_hash, purpose, proposal_id,
accepted, signer_id, format}`, and `HashChainJournal._load` requires
EVERY entry's key set to equal `_ENTRY_KEYS | EXTRA_KEYS` exactly. Two
consequences:

1. The existing entries carry neither `ceremony_id` nor `evidence_hash`,
   so scanning `entries()` cannot detect evidence reuse — the data is
   not there. (Ceremony_id could be smuggled into `proposal_id`, see
   §4.3, but evidence_hash has no field at all.)
2. Widening `EXTRA_KEYS` is a journal FORMAT migration: every historical
   entry would fail the exact-key-set load check. Rejected — do not
   touch `SigningLedger`'s shape.

### 4.2 The anti-replay store of record: a sibling journal

New class in `trust/ledger.py`, a `HashChainJournal` subclass living in
the SAME verifier home (precedent: `BudgetStore` keeps its own file,
`budgets.json`, in the verifier home; `ShipLedger`/`SigningLedger` are
sibling files already):

```python
class CeremonyAuthorisationLedger(HashChainJournal):
    FILENAME = "ceremony-authorisations.json"
    EXTRA_KEYS = frozenset({
        "authorisation_id", "payload_hash", "ceremony_id",
        "evidence_hash", "operator_id", "reason",
        "candidate_payload_hash", "signer_id", "format"})

    def find_by_ceremony(self, ceremony_id) -> dict | None
    def find_by_evidence(self, evidence_hash) -> dict | None
    def append_authorisation(self, signed, *, recorded_at) -> dict
        # kind="authorise", format="ceremony-authorisation",
        # signer_id=signed.signer_id; reloads first (self._reload(),
        # the SigningLedger append pattern)
```

Entries are kind `"authorise"` — never `"sign"` — in THIS journal; the
signature inference lives in the signing ledger (§4.3). The scan in
§3.2 step 4 is two linear scans over `entries()` via the finders.
Journal size is bounded by ceremony frequency (rare, human-paced), so
linear scan is proportionate; no index.

### 4.3 Dual append, commit point, ordering

The verifier's core inference — "a signature with no ledger entry is
evidence of a second signer" — requires every issued envelope to appear
in the SIGNING ledger too. So issuance appends to both, in this order:

1. `CeremonyAuthorisationLedger.append_authorisation(...)` —
   **THE COMMIT POINT for single-use.** After this append lands, the
   (ceremony_id, evidence_hash) pair is spent, whether or not anything
   else succeeds.
2. `SigningLedger.append_ceremony_authorisation(signed, *,
   recorded_at)` — a new method on the UNCHANGED entry shape:
   kind `"sign"`, format `"ceremony-authorisation"`,
   purpose `"pin-ceremony"`, `decision_id=signed.authorisation_id`,
   `payload_hash=signed.payload_hash`,
   `proposal_id=signed.ceremony_id` (documented column reuse: the
   proposal_id column holds the authorisation's scope id — precedent:
   `append_claim` stores the claimant in `signer_id`, and
   `append_eval_attestation` stores `proposal_id=""`),
   `accepted=True`, `signer_id=signed.signer_id`.
3. `_update_anchor(config)` (advances the signing-ledger anchor, as
   every signing mode does).
4. Return the envelope.

Any exception in steps 1–3 ⇒ `_config("ledger_failed", "the ceremony
authorisation could not be ledgered; refusing to return it")` — the
issue_attestation / gate wording pattern. Failure AFTER the commit
point leaves the ceremony_id and evidence_hash spent with no envelope
returned: fail-closed, and the honest operational consequence is that
the operator retries the ceremony under a NEW ceremony_id with a NEW
evidence bundle (a re-issued evidence artefact, hence a new hash).
There is deliberately NO idempotent re-issue of an identical request:
"same ceremony_id, identical everything" is refused by
`ceremony_replay_refused` exactly like a hostile replay — the verifier
cannot distinguish a lost response from a replay, and single-use that
makes exceptions for plausible stories is not single-use. (Compare
`try_consume_eval_records`: consumed-on-reject, never refunded.)

### 4.4 Race / atomicity expectations, stated honestly

- One process per request (the verifier's standing model): there is no
  in-process concurrency; the race is between concurrent verifier
  PROCESSES sharing one home.
- The check-then-append in §3.2 step 4 → §4.3 step 1 is NOT atomic as a
  pair: two processes can both scan clean, both sign, and both attempt
  the commit append. What saves single-use is
  `HashChainJournal._save`'s under-flock freshness check: the loser's
  `_save` raises `CorruptLedgerError` having written NOTHING (the
  verified property the sealed_eval ledger-retry comment relies on).
  The loser therefore returns `ledger_failed`, its envelope is never
  returned, and exactly one authorisation for the ceremony_id is ever
  handed out. Residual, stated plainly: the loser's SIGNING-ledger
  step never runs, so no orphan sign entry exists; but if the race is
  between two DIFFERENT ceremony_ids presenting the SAME evidence_hash,
  the same mechanism applies — first commit wins, second gets
  `ledger_failed` (not the prettier `evidence_reuse_refused`, which is
  what a sequential retry gets). Acceptable: fail-closed either way,
  and the refusal code difference is diagnostic only.
- No retry loop in v1 (contrast sealed_eval's `_LEDGER_ATTEMPTS`):
  ceremonies are human-paced and operator-retried; a bounded reload-
  and-rescan retry (8 attempts, ShipLedger-style) is a named follow-up
  if contention ever appears in practice, not a v1 feature.
- Crash between commit point and return: pair spent, no envelope —
  §4.3's operator-recovery story applies. Crash DURING `_save` is the
  journal's existing tmp+replace+fsync discipline; unchanged.

### 4.5 Rollback residual (named, not hidden)

`AION_ANCHOR_PATH`'s anchor (kind `"signing"`) covers the SIGNING
ledger only. Rolling back `ceremony-authorisations.json` alone does
not trip startup anchor verification, and would erase the evidence-
reuse memory — while the signing ledger (anchored) still shows an
authorisation was issued under that authorisation_id/payload_hash.
Bounded consequence: a rolled-back ceremony journal lets a listed
operator obtain a SECOND authorisation for the same evidence under a
new ceremony_id; it does not let an unlisted operator in, does not
forge an envelope, and the duplicate issuance is visible in the
anchored signing ledger (two `ceremony-authorisation` sign entries
whose payloads bind the same evidence_hash — detectable by audit,
not preventable at issuance). Full closure = a third anchor for the
ceremony journal, budgets-anchor style. Named follow-up:
`ceremony-journal-anchoring` (seat A territory). Do not claim
rollback resistance for the ceremony journal in any doc until it lands.

---

## 5. Client: `VerifierClient.ceremony_authorise`

In `trust/client.py`, following `issue_attestation`'s pattern exactly
(the client is key-free; it checks structure, pins, expiry and echo
binding — MAC verification happens at key-holding consumers):

```python
def ceremony_authorise(self, *, operator_id, ceremony_id, reason,
                       old_pin, candidate, evidence_hash,
                       evidence_ref) -> dict
```

- Body = exactly the §3.1 key set, built from the keyword args.
- `result = self._run("ceremony_authorise", body)`;
  `set(result) != {"authorisation"}` ⇒ `VerifierProtocolError`.
- Parse via `ceremony_authorisation_envelope_from_dict`
  (`SigningError` ⇒ protocol error); re-derive `signed.payload()`,
  check `signed.payload_hash == _sha256(_canonical(payload))` and the
  authorisation_id re-derivation — mirroring issue_attestation's
  payload-hash check (add `authorisation_id` re-derivation via the
  signing module's helper, as `_check_envelope` does for decision_id).
- `self._check_pins(signed.signer_id, signed.key_id)`;
  `self._check_not_expired(signed.expires_at)`.
- **Echo binding** (the sealed_eval answers-hash precedent — the client
  must verify the envelope is bound to the event IT sent, not merely
  well-formed): `signed.operator_id == operator_id`,
  `signed.ceremony_id == ceremony_id`, `signed.reason == reason`,
  `signed.old_pin == old_pin`, `signed.candidate == candidate`,
  `signed.evidence_hash == evidence_hash`,
  `signed.evidence_ref == evidence_ref`; any mismatch ⇒
  `VerifierProtocolError("ceremony authorisation is bound to a
  different event than requested")`.
- Returns the envelope DICT (`result["authorisation"]`), as
  `issue_attestation` returns the dict — seat C's code converts with
  `ceremony_authorisation_envelope_from_dict` where it consumes it.
- Refusals propagate as today: exit 2 ⇒ `VerifierProtocolError`,
  exit 3 ⇒ `VerifierConfigError` (so `ceremony_operator_not_authorised`
  and the replay refusals surface as config errors carrying the code —
  callers must not parse the detail text as evidence, per the client
  docstring's existing warning).

---

## 6. Honest limits (to be carried into the code docstrings verbatim in substance)

### 6.1 What the verifier attests — and what it does not

A valid envelope proves: a process holding the verifier key was
presented, through the verifier's launch channel, with a request
naming an operator who IS on the verifier's own protected
(env-configured) list, and that request bound `evidence_hash` +
`evidence_ref` to exactly this event (old pin, candidate, reason,
ceremony_id); the authorisation was ledgered single-use before it was
returned. The circularity is broken at the LIST: authority now comes
from the protected env file, not from the same caller who supplies the
evidence.

### 6.2 What the verifier does NOT know about the evidence

The verifier never opens, fetches or inspects the artefact
`evidence_hash` names. It does not know the artefact exists, what it
contains, or that the hash was computed over it. `evidence_ref` is an
opaque, caller-supplied locator string (≤2000 chars, form-checked
only). Provenance here means: authenticated (MAC-bound by the
verifier), event-bound, attributable to a listed operator, and
single-use — NOT artefact-verified. The "random evidence hash"
adversarial case is therefore answered honestly: a random hex64 is
still *issuable* if a LISTED operator presents it — what changed is
that it is now attributable to that operator, bound to one event,
burned on use, and preserved in two journals for audit. An operator
willing to attest garbage under their own name was never stoppable
by hash checks; the pre-cycle-19 defect was that ANY caller could do
it under an invented list with no durable record. Do not let any doc
claim more than this.

### 6.3 Non-equality is only partially checkable verifier-side

`pin_ceremony.reanchor_pin` refuses evidence equal to any of
`payload_hash`, `snapshot_id`, `state_sha256`, `calibration_sha256`
of the candidate snapshot. The verifier body carries only the pin-
shape projection (`payload_hash`), so the mode checks equality
against candidate/old `payload_hash` only. The full four-way check
remains seat C's, inside `reanchor_pin`, which sees the real
snapshot. Neither layer may drop its half.

### 6.4 Operator identity is list membership, not authentication

The request channel is unauthenticated JSON on stdin to a spawned
process (the standing prototype model): the verifier cannot prove
the named operator personally sent the request — only that the
request arrived through the orchestrator's launch path naming a
listed operator. Under the deployment wrapper (dedicated OS user,
root-owned env file) that path is the boundary, exactly as for every
other mode. Same-OS-user honesty from verifier_main's docstring
applies unchanged: any code running as the verifier's OS user can
read the key and the env file and bypass all of this; the prototype
stops evolved/convenience code paths, not a malicious same-user
process. HMAC symmetry likewise unchanged: anyone holding the
verifier key (including any verify-only consumer seat C runs) can
forge an authorisation envelope; the ledgers are what make a forged
envelope *detectable* (an unledgered authorisation_id), provided
consumers check ledger presence — see §7(ii) for the consumption-side
obligation this creates.

### 6.5 Refusals are unledgered

Non-operator probes and replay attempts leave no journal entry
(nothing was signed; the journals record issuances). A flood of
refused ceremony requests is visible only in process logs, not in
the audit journals. Accepted for v1 (consistent with eval-evidence
refusals); a claim-style refusal journal is a possible follow-up,
explicitly out of scope here.

---

## 7. Shared interface questions — seat B's answers

### (i) The exact envelope dict seat C consumes

`ceremony_authorisation_envelope_to_dict(signed)` — this exact shape,
no more, no less (strict key sets enforced by `…_from_dict`):

```json
{
  "operator_id": "operator-uma",
  "ceremony_id": "ceremony-2026-11-28-001",
  "reason": "chain_gap_recovery",
  "old_pin": {"cycle_seq": 41, "payload_hash": "<hex64>"},
  "candidate": {"cycle_seq": 47, "payload_hash": "<hex64>",
                "signer_id": "<snapshot signer id>",
                "key_id": "key-<16 hex>"},
  "evidence_hash": "<hex64>",
  "evidence_ref": "<opaque locator, ≤2000 chars>",
  "signer_id": "<VERIFIER signer id>",
  "key_id": "key-<16 hex>",
  "signed_at": "<ISO-8601 UTC>",
  "expires_at": "<ISO-8601 UTC>",
  "payload_hash": "<hex64>",
  "authorisation_id": "<hex64>",
  "signature": "<hex64>"
}
```

Field-name commitments: `authorisation_id` (not `envelope_id`);
`old_pin` is JSON `null` (Python `None`) for the three no-pin reasons,
never omitted, never `{}`; pin sub-objects use `cycle_seq` /
`payload_hash` (the pin shape's own names); candidate uses
`signer_id` / `key_id` for the SNAPSHOT's signer/key, while the
envelope's top-level `signer_id` / `key_id` are the VERIFIER's — seat
C must not conflate them (see (ii) on the two keys). The verifier mode
returns `{"authorisation": <this dict>}` and the client returns this
dict directly.

### (ii) Should `reanchor_pin` REQUIRE the envelope?

**Recommendation: REQUIRE it in the shipped form. Remove
`authorised_operators`; do not ship an optional/alternative path.**

Signature seat C should target:

```python
def reanchor_pin(old_pin, signed, *, signing_key,          # snapshot key (existing)
                 authorisation_key: SigningKey,            # NEW: verifier key
                 ceremony_authorisation,                   # NEW: SignedCeremonyAuthorisation, required kwarg
                 state_bytes, calibration_bytes, expected_signer_id,
                 expected_verifier_signer_id,              # NEW pin
                 strict_reasons=None, now=None,
                 ceremony_history=None) -> tuple[dict, PinCeremonyRecord]
```

with `operator_id`, `reason`, `evidence_hash` DERIVED from the
verified authorisation (parameters deleted) and these checks inside,
before any pin movement:

- `verify_ceremony_authorisation(ceremony_authorisation,
  signing_key=authorisation_key,
  expected_signer_id=expected_verifier_signer_id,
  expected_operator_id=None,  # any listed operator; list membership was the verifier's call
  expected_reason=<the reason flow>, expected_old_pin=<captured old pin
  or None>, expected_candidate={"cycle_seq": signed.cycle_seq,
  "payload_hash": signed.payload_hash, "signer_id": signed.signer_id,
  "key_id": signed.key_id}, expected_evidence_hash=<derived>) == ()`,
  else `SigningError`. Expiry is judged on the ceremony's single
  captured `moment` (cycle-16's one-clock rule) via `now=moment`.
- **Key separation check** (answers CROSS-CHECK-9/10's MAC-separation
  gate for this artefact pair): `authorisation_key.key_id !=
  signing_key.key_id` required — an authorisation under the snapshot
  key defeats the boundary's point, and the ceremony record stays
  under the snapshot key while the authorisation is under the
  verifier key, so the two artefacts are independently forgeable
  only by their own key holders.
- The existing in-ceremony checks (eligibility recomputation, bare-
  verifier candidate verification, history checks, four-way evidence
  non-equality) all stay; the envelope ADDS authority/provenance, it
  replaces none of the local validation.

Reasoning for REQUIRE over optional-alternative:

1. Gemini's cycle-16 verdict names the principle: "opt-in protection
   is the defect." An `authorisation=None` default, or an
   either/or with the legacy list, leaves a shipped path where the
   caller still supplies the authority — the exact circularity the
   owner decision orders removed. A dual path also doubles seat C's
   test matrix and invites the convenience caller (the threat model
   in every signing docstring) to pick the weaker branch.
2. The cost of breaking the held cycles' tests is LOW and bounded:
   cycles 14–16 are HELD and unshipped, `pin_ceremony`'s own
   docstring states it was built "BEFORE any production caller
   depends on the wrapper" — there is no production caller to break.
   The breakage is test call-sites passing `authorised_operators=[…]`
   / `operator_id=` / `evidence_hash=` to `reanchor_pin`, which seat
   C rewrites to mint a test authorisation under a test verifier key
   (a fixture helper in the test module, signing with
   `sign_ceremony_authorisation`). That is a mechanical change, and
   it makes the held cycles' tests exercise the real authority path
   at their re-review — which is the point of holding them.
3. The one legitimate legacy need — no-pin bootstrap reasons
   (`initial_anchor` etc.) — is NOT an exception: the verifier mode
   authorises no-pin events too (old_pin null), so REQUIRE covers
   bootstrap uniformly. There is no flow left that needs the list.

Transitional note: during the build (before seat C lands), landing
the verifier mode first with `reanchor_pin` untouched is fine as an
intermediate commit — but the cycle does not SHIP in that state, and
no war-room brief may describe the ceremony as authority-fixed until
the REQUIRE change lands.

Consumption-side obligation created by §6.4: because HMAC verify-only
holders can forge, seat C's strongest consumption form should also
check the authorisation was ledgered — in the prototype the loop
cannot read the verifier's signing ledger (different home), so v1
relies on: envelope MAC + expiry + exact binding + the verifier
having ledgered before return (an unledgered envelope could only
come from a key holder bypassing the verifier process — the
docstring threat model). Stated here so the war room judges it
knowingly, not by omission.

### (iii) Does `PinCeremonyRecord` need ceremony_id / authorisation_id bound in?

**Yes — add both. It is cheap now and expensive later.**

- Add fields `ceremony_id: str` and `authorisation_id: str` to
  `PinCeremonyRecord` and to its `payload()` (keys `"ceremony_id"`,
  `"authorisation_id"`), populated from the verified authorisation
  (`record.operator_id` / `record.evidence_hash` already duplicate
  authorisation fields — precedent for binding-by-copy exists).
  `verify_ceremony_record` gains: `_check_id` on ceremony_id,
  `_check_hex64` on authorisation_id, reported as `invalid_id` /
  a new `invalid_authorisation` reason respectively (seat C picks
  the reason names; flagging here so the vocabulary is decided
  once). This closes the audit loop: record → authorisation_id →
  signing-ledger sign entry + ceremony-journal entry → env-listed
  operator + evidence. Without it, joining a ceremony record to its
  authorisation requires matching on (operator, evidence_hash,
  timestamps) — forensic glue, not a binding.
  `_check_ceremony_history` can then also refuse a history whose
  records repeat an authorisation_id (defence in depth; optional).
- What breaks if the payload gains fields — enumerated, all bounded:
  1. `payload_hash` values change for any given field set: records
     are minted and verified in the same code version, and NO
     persisted record store exists yet (records are returned, not
     journalled by pin_ceremony), so there is no on-disk migration.
     Any record minted by pre-cycle-19 code and verified by
     post-cycle-19 code (or vice versa) fails `payload_hash_mismatch`
     — acceptable for held, unshipped cycles; must be stated in the
     cycle-19 change note so the 14–16 re-review expects it.
  2. The frozen dataclass gains two REQUIRED constructor fields:
     every direct `PinCeremonyRecord(...)` construction site breaks
     loudly (TypeError) — `reanchor_pin` itself plus test sites.
     Loud breakage is the safe kind; do NOT give the fields defaults
     to soften it (a defaulted `""` would let a record exist that
     claims no authorisation — the (ii) defect in miniature).
  3. `record.payload()` consumers that re-derive the hash (only
     `verify_ceremony_record` and tests) follow automatically.
  4. Nothing serialises `PinCeremonyRecord` to dict/JSON in the
     current module (no to_dict/from_dict exists), so no wire
     format breaks. If seat C adds serialisation in this cycle, it
     must include the two fields from birth.

---

## 8. Test plan (seat B's half; adversarial names from CROSS-CHECK-9/10)

Verifier mode (`tests/test_trust_ceremony_authorise.py`, new):
- Happy path for `chain_gap_recovery` and for `initial_anchor`
  (old_pin null); envelope verifies under the verifier key with all
  expected bindings; signing-ledger entry (format
  `ceremony-authorisation`) and ceremony-journal entry both exist
  BEFORE the client returns (assert by reading both journals in the
  fixture home after the call).
- **Invented operator list**: body carrying an extra
  `authorised_operators` key ⇒ exit 2 `malformed_request`; operator
  not on the env list ⇒ exit 3 `ceremony_operator_not_authorised`,
  and assert NO envelope, NO journal entries in either ledger.
- Env list unset ⇒ exit 3 `ceremony_operators_unconfigured` for the
  new mode AND gate/sealed_eval still work in the same deployment
  (mode-scoped fail-closed).
- Malformed env list (bad id, duplicate, empty segment) ⇒ startup
  exit 3 `verifier_misconfigured`.
- **Random evidence hash**: a well-formed random hex64 from a LISTED
  operator IS issued (pins the §6.2 honesty — the test name should
  say what it proves: `test_random_evidence_is_attributable_and_single_use`),
  and its second use ⇒ `evidence_reuse_refused`.
- **Evidence reuse across events**: same evidence_hash, different
  ceremony_id/candidate ⇒ `evidence_reuse_refused`; same ceremony_id,
  different candidate ⇒ `ceremony_replay_refused`; exact duplicate
  request ⇒ `ceremony_replay_refused`.
- Evidence == candidate payload_hash ⇒ malformed; == old pin hash ⇒
  malformed; one-step candidate (old+1) ⇒ malformed; same-seq and
  backwards ⇒ malformed; no-pin reason with a pin (and vice versa) ⇒
  malformed.
- Ledger failure injection (journal dir made unwritable / corrupt
  ceremony journal) ⇒ exit 3 `ledger_failed`, no envelope returned,
  and (corrupt-journal case) refusal happens at scan time.
- TTL: envelope `expires_at - signed_at == min(configured TTL, 900)`;
  configured TTL 172800 still yields 900.

Signing module (`tests/test_signing_ceremony_authorisation.py`, new):
payload projection refusals (each §2.2 rule), MAC/domain separation
(an attestation envelope's signature never verifies here and vice
versa), verify reason vocabulary incl. sentinel semantics for
`expected_old_pin` (omitted vs explicit None vs dict), expiry/skew,
strict serialisation key sets, tamper cases per field.

Allowlist step (§1.2): the updated wiring/deploy tests listed there.

Client: echo-binding mismatch (fixture verifier returning a
well-formed envelope for a different candidate) ⇒
`VerifierProtocolError`; pins and expiry reuse existing client test
patterns.

Concurrency (honest, small): two simultaneous client calls, same
ceremony_id, barrier-synchronised — exactly one returns an envelope,
the other raises (config or protocol error); both journals contain
exactly one authorisation. Model on
`tests/test_trust_sealed_eval_contention.py` at reduced width (2–4).

---

## 9. Interface friction summary (for the design reconciliation)

- **Seat A (gate/ledger/anchoring)**: (a) `trust/protocol.py` MODES is
  shared — one-line addition, but it is A's file surface; (b) the new
  `CeremonyAuthorisationLedger` lives in `trust/ledger.py` beside A's
  journals — EXTRA_KEYS/key-set discipline per §4.1 must be respected
  by both seats (do NOT widen SigningLedger); (c) §4.5's anchoring gap
  needs A's call: third anchor now, or named follow-up (my
  recommendation: follow-up, cycle ships without claiming rollback
  resistance for the ceremony journal); (d) health_check.py's copied
  allowlist (§1.2 #3) — consider whether A wants a drift test.
- **Seat C (pin_ceremony integration)**: (a) body/payload old_pin is
  projected to exactly `{cycle_seq, payload_hash}` — C must project
  the full pin (which may carry key_id/signer_id) before calling;
  nothing is silently dropped verifier-side because extra keys
  REFUSE, so C will find out loudly if it forgets; (b) `reanchor_pin`
  gains a second key parameter (`authorisation_key`) and a verifier
  signer pin (`expected_verifier_signer_id`) — C's callers must
  source the verifier key for verification; under the prototype's
  same-user honesty that is a key-file read, and C should say so in
  pin_ceremony's docstring rather than imply a new boundary; (c) the
  key-separation refusal (`authorisation_key.key_id ==
  signing_key.key_id` ⇒ refuse) will break any C test that reuses
  one key for both — deliberately; (d) `PinCeremonyRecord` gains two
  required fields (§7(iii)) — C owns the constructor fallout;
  (e) ceremony_id minting is the CALLER's duty (id grammar
  `^[a-z0-9][a-z0-9_-]{0,63}$`); the verifier binds and burns it,
  never invents it — C's loop code needs a minting convention
  (recommendation: `<date>-<seq>` human-readable ids, uniqueness
  enforced by the ledger, not by the format).
- **Open question for the room**: `evidence_ref` format. B leaves it
  opaque text (form-checked only). If C wants machine-checkable
  provenance later (e.g. a scheme prefix registry), that is a new
  allowlist and a new cycle — do not grow it inside cycle 19.
