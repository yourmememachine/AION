# Cycle 22 — Review rev-r4 (WS3 focus: production adopter)

Seat: rev-r4, blind. Scope read: `internal/cycle22-work/DESIGN-FINAL.md`
(R3), `internal/cycle22-work/design-c.md`, `trust/pin_adoption.py`,
`tests/test_trust_pin_adoption.py`, plus targeted cross-checks in
`signing/state_snapshot.py`, `signing/pin_ceremony.py`,
`trust/wiring.py`, `trust/verifier_main.py`.

**Verdict: SHIP — score 0.92**

Test run by this seat: `python3 -m unittest tests.test_trust_pin_adoption -v`
→ **9 tests, OK, 15.0s** (test_01 … test_08 incl. 05/05b).

---

## (a) Real production caller with full production wiring — PASS

- `build_pin_adopter` builds the client at exactly one site, via
  `trust.wiring.production_client` (`trust/pin_adoption.py:210`); a grep
  of the module finds **no** `VerifierClient(` construction anywhere.
- Consumption is verifier-backed: `reanchor_pin(...,
  consume_authorisation=self._client.ceremony_consumer(), ...)`
  (`trust/pin_adoption.py:696`), never a hand-rolled consumer.
- Adoption is only through `PinStore.adopt` (advance branch, ceremony
  branch `trust/pin_adoption.py:704-713`, and `adopt_returned`).
- Out-of-band pins are enforced: factory refuses when
  `config.expected_verifier_signer_id != expected_signer_id`
  (`trust/pin_adoption.py:184-190`) and on a visible evidence-dir
  mismatch (`:198-208`); the snapshot key is loaded with
  `forbidden_roots=(state_dir, pin_dir)`.
- Adopter env is genuinely separate: `AION_PIN_*` is defined/read only
  in `trust/pin_adoption.py:85-90,146-172`, and wiring's
  `ALLOWED_ENV_KEYS` (`trust/wiring.py:179-199`, 19 names) contains no
  `AION_PIN_*` name — the verifier never sees adopter variables.
- Test-harness honesty matches R3's allowance: the test module
  docstring states plainly that, except for the factory-refusal case,
  the adopter is built around a directly constructed `VerifierClient`
  in research mode (R12 pattern) because `production_client` requires
  production mode + anchors (`tests/test_trust_pin_adoption.py:1-19`).

## (b) Reason is computed, never caller-chosen; `lost_pin` never selected — PASS

- The only reason assignment in the flow is in `_reanchor`
  (`trust/pin_adoption.py:609-627`): `_find_unadopted_burn(...)` must
  match candidate seq **and** hash **and** old pin seq **and** hash
  against an unadopted journal ceremony (`:374-385`); on a match the
  reason is `burned_unadopted` with the caller's strict reasons passed
  through for the with-pin case and `None` for no-pin (`:622-627`),
  otherwise the primary reason. The two call sites pass only
  `initial_anchor` (`:530`) and `chain_gap_recovery` (`:563`).
- Grep proof for `lost_pin`: in `trust/pin_adoption.py` the string
  occurs **only** in prose ("``lost_pin`` is never selected for an
  unmoved pin", `:23`, and the comment at `:616`). There is no
  `REASON_LOST_PIN` constant and no assignment path that can produce
  it. `tests/test_trust_pin_adoption.py:322` additionally asserts
  `"lost_pin" not in [r.reason for r in history]` after a recovery.
- Defence in depth confirmed outside the adopter: even if the
  adopter-side journal were forged to claim a burn, authorise-side
  validation checks `burned_unadopted` against the verifier's own
  consumption journal via `match_head_burn` and refuses with
  `ceremony_recovery_unproven` (`trust/verifier_main.py:2537-2542`).
  The adopter journal is a detection aid, not authority — exactly the
  boundary design C §6 imposed on WS1.

## (c) Mandatory cases — PASS (all exercised, all green in my run)

- Consume-committed / adopt-failed → `PinAdoptionBurned` with the
  returned pair attached: raised at `trust/pin_adoption.py:708-713`
  with `returned_pin=new_pin, returned_record=record`;
  `test_05` asserts the pair is non-None, the pin file is still at
  the old pin, and the consumption count is +1 (the burn is real).
  An exception *inside* `reanchor_pin` is also treated as burned with
  a `None` pair (`:697-703`) — the honest ambiguous-response handling.
- `adopt_returned(...)` completes with **no** new consumption:
  `test_05` asserts the consumption count is unchanged after
  `adopt_returned` and the final pin/record equal the burned pair.
  Implementation is a thin wrapper over `PinStore.adopt` plus an
  `adopted` journal line (`trust/pin_adoption.py:720-740`).
- Discarded-pair variant → fresh ceremony under `burned_unadopted`
  with a second consumption: `test_05b` asserts outcome `reanchored`,
  `record.reason == "burned_unadopted"`, consumption count +2, a new
  evidence artefact, and no `lost_pin` in history.
- `already_current` on repeat with no new consumption: `test_03`
  asserts the second `snapshot_and_adopt()` returns `already_current`
  with the consumption count still 2.

## (d) Scope honesty — PASS

- `git diff HEAD -- core/loop.py` is **empty**; `run_one_cycle_and_pin`
  is a driver in `trust/pin_adoption.py` (end of module) that calls
  `loop.run_one_cycle(...)`, returns `(None, None)` on idle, and on an
  adoption exception attaches `.cycle_entry` and propagates — no loop
  edit, no state rollback, as documented.
- No live run: `state/state.json` does not appear in `git status`;
  every test runs in temp dirs. The module docstring's claim
  (`trust/pin_adoption.py:38-42`: production code exercised end-to-end
  in temp dirs against the real verifier subprocess, first live
  adoption gated on verifier provisioning) matches what the code and
  tests actually do. The F1 wording stays "first production adopter
  built and wired as specified" — nothing in this module overclaims a
  live adoption.

## (e) Evidence bundle authored by the adopter, hash from its own bytes — PASS

- `_evidence_bundle` (`trust/pin_adoption.py:574-607`) is authored
  in-module (adopter/operator ids, reason, old pin, candidate,
  `state_sha256`, `calibration_sha256`, gap range, strict reasons,
  timestamp); it is written atomically to the evidence dir **before**
  authorise, and `evidence_hash = hashlib.sha256(bundle).hexdigest()`
  is computed from those bytes (`:634-642`), never read back from the
  envelope. `test_07` verifies the on-disk artefact hashes to the
  adopted record's `evidence_hash`, that two ceremonies produce
  distinct artefacts/hashes, and that the bundle names `gap_from_seq=2`.

---

## Build seat's three flagged deviations — judged

### Deviation 1: `authorised` journal line carries `candidate_envelope` — SAFE, honestly disclosed

- Disclosed in the module docstring (`trust/pin_adoption.py:25-36`)
  and at the write site (`:674-679`).
- Not a bypass. The retained envelope is a signed snapshot envelope:
  reconstruction is strict (`snapshot_envelope_from_dict`), and on
  every attempt the candidate — retained or fresh — is fully
  re-verified against the *current* state/calibration bytes, signer
  pin, pin, MAC and expiry via `verify_signed_snapshot` /
  `verify_snapshot_for_state` (`signing/state_snapshot.py:539-760`).
  A tampered journal envelope yields `signature_mismatch` /
  `state_mismatch` → integrity failure, nothing persisted. The journal
  also cannot manufacture a `burned_unadopted` reason at the verifier:
  WS1 validation reads the verifier's own consumption journal (see
  (b)). Retention is in fact *necessary*: re-signing the same state
  produces a different hash (new `signed_at`), which the consumption
  head would refuse as a fork against the burned candidate.
- **Finding F1 (Low, non-blocking):** `_retained_candidate`
  (`trust/pin_adoption.py:387-408`) checks `signed.cycle_seq` but not
  `signed.payload_hash == entry["candidate_hash"]` before returning
  the envelope. Consequence is fail-closed only: a mismatched envelope
  cannot match `_find_unadopted_burn`'s exact hash check, falls back
  to the primary reason, and the verifier head rules refuse a fork.
  Worth a one-line tightening in a later cycle; not a hole.

### Deviation 2: `snapshot-candidate.json` side file for `already_current` — SAFE, honestly disclosed

- Written only after a successful advance adopt
  (`trust/pin_adoption.py:556`, `_retain_candidate` at `:421-427`),
  via the same atomic write discipline; read at `:428-436` with all
  errors swallowed to `None`.
- Not a bypass: the caller accepts the side-file envelope only when
  its seq equals the state seq **and** its hash equals the current
  pin's hash (`:497-505`), and it then goes through the same full
  verification as any candidate. A planted or stale envelope that
  does not attest the current bytes fails verification and the flow
  refuses; it is a cache of a signed artefact, never an authority —
  as its own comment block states (`:411-417`).
- **Finding F2 (Low, non-blocking, liveness only):** `already_current`
  is reachable only while the retained envelope is unexpired. After
  the snapshot TTL, a repeat attempt on unchanged state classifies
  the expired retained envelope as an integrity failure and raises
  `PinAdoptionRefused` rather than reporting `already_current`. This
  is fail-closed and arguably inherent (a fresh signing at the pinned
  seq would be `pin_mismatch` by design), but the TTL bound on the
  `already_current` outcome is not stated in the module docstring and
  should be, so an operator is not surprised by a refusal on an
  unmoved pin.

### Deviation 3: test_04 asserts byte-identical journal instead of absent journal — SAFE, honestly disclosed

- The design's "journal absent" wording assumed a fixture with no
  prior ceremony; `test_04` runs after `genesis()`, which legitimately
  wrote journal lines, so absence would be a false premise. The test
  captures the journal bytes before the attempt and asserts byte
  equality after (`tests/test_trust_pin_adoption.py:253-275`) — a
  *stronger* statement (no line appended, none rewritten) for this
  sequencing, with the pin bytes, evidence dir listing and consumption
  count asserted unchanged alongside it.
- **Finding F3 (Info):** coverage nit only — no case exercises an
  integrity failure on a virgin adopter where the journal is truly
  absent. The byte-identical assertion subsumes the property that
  matters (no ceremony was started); not a hole.

---

## Minor finding

- **F4 (Low):** In `_reanchor`, the `phase: "adopted"` journal append
  (`trust/pin_adoption.py:713`) sits after the successful
  `store.adopt` and outside any guard: if that append raises, the
  caller sees a raw `OSError` even though the pin *did* adopt. The
  next attempt self-heals (retained-current candidate →
  `already_current`), so this is an exception-type wart, not a
  correctness or safety defect. Same pattern in `adopt_returned`
  (`:730-739`).

## Summary

WS3 is a real production adopter wired exactly as R3 specifies:
production-only client construction, verifier-backed consumption,
atomic store adoption, computed reason with `lost_pin` unreachable,
all mandatory burn/recovery/`already_current` cases proven against
the real verifier subprocess, and scope claims that match the tree
(`core/loop.py` untouched, no live state run). All three flagged
deviations are safe and disclosed in-code; the retained-envelope
mechanisms re-verify fully on every attempt and cannot bypass the
verifier's own burn validation. Remaining items are Low/Info
liveness and documentation nits (F1–F4).

**Verdict: SHIP — 0.92**
