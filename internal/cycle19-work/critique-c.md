# Cycle 19 — Cross-critique, seat C (ceremony integration)

Verdicts first. I concede D1, D2 and D3 to B — in each case
B's position is the one the owner decision and the external
seats actually ordered, and my note was defending test
convenience dressed as compatibility. D4: B wins. D5: B's
design is sufficient in-process; the residual ships only
under two naming conditions.

## D1 — Legacy list: CONCEDE — remove `authorised_operators`, require the envelope

B's strongest argument, engaged directly: Gemini cycle-16's
principle is not "opt-in protection is confusingly labelled"
— it is that a shipped path where the caller supplies the
authority IS the defect, however it is labelled. My §2(c)
defence answered a different charge. My three distinctions
(not silent, both/neither refused, path recorded in the
audit record) show the legacy path is not *deceptive*; they
do not show it is not *circular*. A caller who passes the
list still asserts its own authority, and "production wiring
should simply never pass the list" is an unenforceable
convention of exactly the kind cycle 16 rejected. The
DECISION text ("the gate will hold its own protected
operator-authority list and verify evidence provenance
itself") orders removal, not renaming.

And B's question — who is the legacy path FOR? — has no
answer. Cycles 14–16 are HELD and unshipped; grep confirms
`reanchor_pin` has exactly ONE caller in the repo, the test
file's helper (plus the `signing/__init__` re-export). There
is no production caller, no external consumer, nobody to be
compatible with except held tests whose re-review is
*conditioned* on adopting the envelope path. Keeping the
parameter to spare those tests is protecting the artefact
the hold exists to fix. Remove it; derive
operator/reason/evidence from the verified authorisation
(B §7(ii) signature), including `authorisation_key` as a
required kwarg and — see §7 check below — the verifier
signer pin, once B fixes its own inconsistency there.

**Test conversion count (grepped, not estimated).**
`tests/test_signing_pin_ceremony.py`: 411 lines, 25 test
methods. Breakdown: 1 Classify + 3 Advance (untouched) +
11 ReanchorTests + 10 Cycle16HardeningTests = **21 test
methods exercise `reanchor_pin`**. Crucially, ALL 21 funnel
through the single `reanchor()` helper (lines 56–68), which
is the only direct `reanchor_pin` call in the file
(`kw.setdefault("authorised_operators", AUTH)`, line 62).
Conversion is therefore **one helper rewrite, not 21 call
sites**; most test bodies stay byte-identical. My §6.3
"existing tests touched: NONE" claim dies with the legacy
path — the honest replacement is "one helper + two cases".

**Yes, the envelope path is exercisable in unit tests
without the verifier subprocess.** B's
`sign_ceremony_authorisation` lives in `signing/`; the
helper mints in-process with a test verifier key (distinct
from `KEY` per D2), exactly as B §7(ii) point 2 prescribes,
and `verify_ceremony_authorisation` is in-process. The
subprocess E2E file remains the only place that proves
*authority* (env list, ledger); in-process minting bypasses
both, so the helper must be named/commented as a binding
fixture, never as evidence the authority path works.

Helper conversion specifics the build must not miss:

- Mint inputs replace the deleted params: operator, reason
  and evidence move INTO the mint call; the helper projects
  the full pin from `pin_of()` down to
  `{"cycle_seq", "payload_hash"}` for `old_pin` (B refuses
  extra keys loudly) and builds the 4-field candidate
  projection from the snapshot.
- Mint `now=` MUST be the ceremony's `now=` (default
  `NOW`), not a fixed mint time: cycle-16 tests reanchor at
  `LATER` (13:00) against a 900 s TTL — an envelope minted
  at `NOW` (12:00) is expired by then. One clock per call,
  shared by mint and ceremony.
- Each mint needs a fresh `ceremony_id` (counter suffix is
  fine in-process; uniqueness is ledger-enforced only
  verifier-side).
- **Two cases change semantics, not just plumbing:**
  (1) `test_refusals`' `operator_id="operator-9"` case —
  there is no longer an in-ceremony "unauthorised operator"
  refusal to test in this file; minting for operator-9
  in-process succeeds, so the case becomes a *binding*
  mismatch case (envelope for operator-9, ceremony derived
  from a different envelope) or moves to B's mode tests,
  where unlisted-operator refusal actually lives. It must
  not silently become a mint-time success.
  (2) `evidence_hash="xyz"` — the mint function itself
  refuses malformed hex64, so the `SigningError` would be
  raised by the helper, not by `reanchor_pin`. Rewrite as a
  tampered-envelope case (mint valid, `replace()` the
  evidence, re-MAC failure / binding refusal) so the
  assertion still targets the ceremony.

## D2 — Key separation: CONCEDE — refuse same-key in-process

My "deployment property" argument does not survive GPT
cycle-16's wording: key separation is a mandatory gate,
"provisioned **and enforced**". Enforcement that lives in
deployment convention is the D1 error again. My fixture
objection was also weaker than I stated: the one-key
discipline I cited is `test_trust_verifier.py`'s verifier
home, not the pin-ceremony unit fixture, and two keys in
unit tests cost one `make_signing_key(b"\xff"*32)` — a
pattern the existing test file already uses. The E2E fixture
already has distinct keys by construction (verifier-home key
vs the snapshot helpers' `KEY`).

**Exact refusal condition** (in contract resolution, BEFORE
envelope verification, so the refusal is unambiguous):

```python
if authorisation_key.key_id == signing_key.key_id:
    raise SigningError(
        "ceremony authorisation key must differ from the "
        "snapshot signing key (key separation)")
```

Comparison by `key_id` (B's formulation): `key_id` is the
pinning identity every other check in `signing/` uses; two
`SigningKey` objects with the same id are the same key for
every purpose this module recognises. A key whose `key_id`
field is inconsistent with its bytes is still caught by B's
verify (`key_id_inconsistent`) on the envelope path.

**Planned tests that change:** (a) the unit helper (D1)
grows a module-level verifier test key distinct from `KEY`;
(b) E2E test 9 (`test_wrong_authorisation_key_refused`) is
unchanged — a *different* wrong key still fails in verify;
(c) ADD `test_same_key_as_snapshot_refused`: genuine
envelope under `KEY` itself, `authorisation_key=KEY` →
the separation `SigningError` above (this is the only new
ceremony test D2 costs); (d) my §5 docstring clause
"the war room may overrule me" is deleted — separation is
now stated as enforced in-process, record MAC still under
the snapshot key, unchanged.

## D3 — Record fields: CONCEDE — `ceremony_id` + `authorisation_id` REQUIRED, no defaults

B is right on the facts and on the principle. Facts
(verified by grep): `PinCeremonyRecord(` has exactly one
construction site, `pin_ceremony.py:524`, all-keyword; the
dataclass currently has NO defaulted fields at all; no test
constructs a record directly (`replace()` carries new
fields); and there is no persisted record store — records
are returned, not journalled — so there is nothing to
migrate. My trailing-defaults proposal was source-compat
for a hypothetical positional caller that does not exist.
Principle: a defaulted `""` makes "a record that claims no
authorisation" representable, and my own §4 verify plan
would have accepted `""` as a legitimate legacy record —
that is the D1 defect in miniature, surviving inside the
audit artefact after the parameter is gone. Under D1's
removal there IS no legacy path, so empty must be
unrepresentable, not merely unusual.

Adopt B §7(iii) wholesale: both fields required, in
`payload()`, populated from the verified authorisation;
`verify_ceremony_record` gains `_check_id` on `ceremony_id`
and `_check_hex64` on `authorisation_id`. On B's open
reason-name point: use the single shared
`"invalid_authorisation"` for both (my §4 preference) —
one reason, small vocabulary, and no consumer parses them
separately. My §4 breakage assessment otherwise stands and
now reads better: loud TypeError at the one constructor if
the build forgets a field is a feature. B's corollary —
pre/post-cycle-19 records cross-verify as
`payload_hash_mismatch` — must go in the cycle-19 change
note for the 14–16 re-review; agreed.

## D4 — Operator config: B's mode-level refusal wins

From the ceremony side, the fail-closed property the
ceremony actually needs is narrow: **no envelope can be
issued when the list is absent/empty** — because the
envelope is now the ONLY authority path (D1), issuance is
the single choke point, and `reanchor_pin` never sees the
list at all. Both designs deliver that for production. B's
delivers it everywhere, and that difference matters:

- A's condition as stated (startup refusal *in production
  mode*) leaves research mode — the only mode any current
  deployment or fixture actually runs — unspecified. If a
  research verifier without the var still issued envelopes,
  the ceremony's posture would depend on deployment mode,
  which is precisely the kind of modal gap fail-closed
  design exists to eliminate. B's mode-level refusal
  (`ceremony_operators_unconfigured`, exit 3, unsigned,
  every request, every mode) is strictly stronger where it
  counts.
- Startup refusal also punishes unrelated modes: a
  gate-only production verifier that never ceremonies would
  fail to start over config it does not use. That is A's
  own purity argument (§6(i): the gate must stay env-free
  and scoped) turned against A's condition.
- The only thing B loses is deploy-time loudness (a missing
  var is discovered at first ceremony, not at boot). That is
  a health-check warning follow-up, not a startup gate.

**E2E impact: neither breaks my test plan; B fits it.**
My fixture runs `AION_DEPLOYMENT_MODE=research` and sets
the operators env for happy-path tests — under B, the
unconfigured case is directly testable in the same fixture
(unset var → mode refusal, other modes still work, which is
also B's own planned test). Under A's production-startup
rule, testing the unconfigured case would need a separate
production-mode fixture whose verifier refuses to start at
all — more machinery to prove less. Note for A: B's §1.1
also satisfies A's condition (1) in substance — in
production the mode refuses with a config error, unsigned,
non-zero exit; the refusal is per-request rather than at
startup. I read that as A's condition met by a better
mechanism, not defied.

## D5 — Anti-replay ledger: envelope + binding is sufficient in-process; residual ships with two naming conditions

`reanchor_pin` must NOT check the ledger, for reasons of
layering, not convenience: (i) the ledger lives in the
verifier home under `trust/`; `signing/` must not import
`trust.*` (dependency runs the other way) and an in-process
ceremony has no legitimate path to that home; (ii) a ledger
parameter would recreate an opt-in check — supplied, it
protects; omitted, it doesn't — the cycle-16 defect in its
third costume; (iii) the unit-test surface (D1) has no
verifier home, so a mandatory check would make the pure
unit tests un-runnable. The ledger's single-use job is at
ISSUANCE: (ceremony_id, evidence_hash) burned before the
envelope is returned (B §4.3 commit point) means no second
envelope for the same event or evidence can be minted
through the verifier. What the ceremony checks — MAC under
a separated key, expiry on its single captured moment,
EXACT binding to captured pin/candidate/operator/reason/
evidence — is the complete in-process claim, and B's dual
append keeps the anchored signing ledger as the audit trail
that makes a forged-but-unledgered envelope detectable.

**The residual is acceptable to ship this cycle**, because
B §4.5 bounds it honestly: rolling back
`ceremony-authorisations.json` alone lets a *listed*
operator obtain a second authorisation for the same
evidence under a new ceremony_id; it admits no unlisted
operator, forges nothing, and the duplicate issuance is
visible in the anchored signing ledger. Conditions:
(1) the follow-up is filed this cycle under B's name,
`ceremony-journal-anchoring` (A's territory), and no doc,
docstring or war-room brief claims rollback resistance for
the ceremony journal until it lands; (2) my §5 docstring
draft gains one sentence naming this residual next to the
protected-path bullet — the honesty bullets are where a
future reader will look, and B's §4.5 alone is not enough.

## B §7 envelope vs my §7 asks — field-by-field

| Item | Verdict |
|---|---|
| Nested `old_pin` = `{"cycle_seq","payload_hash"}` \| null | MATCH, exactly as asked. |
| Nested `candidate` = `{"cycle_seq","payload_hash","signer_id","key_id"}` | MATCH, exactly as asked. |
| Top-level `signer_id`/`key_id` = verifier's; candidate's = snapshot's | MATCH; B's warning not to conflate them is correct and goes into my binding code comments. |
| `authorisation_id` derivation | MATCH in pattern (`_sha256(_canonical({"v": DOMAIN, "payload_hash", "key_id"}))`, field exposed). GAP: B never names the `authorisation_id_for(payload_hash, key_id)` helper my §7 asked for — §2.3 derives it inline, §5 implies a helper exists. Non-breaking for C (I consume the field), but B must pin the helper's existence/name before build; the client needs it too. |
| Serialisation names | MISMATCH (names only): B ships `ceremony_authorisation_envelope_to_dict` / `_from_dict` (+ `_to_json`/`_from_json`); I asked for `ceremony_authorisation_to_dict` / `_from_dict`. Adopt B's — his module, attestation-style naming. Breaks my draft imports if unflagged; one-line fix now it's pinned. |
| Payload `v` / `alg` / `purpose` / DOMAIN | MISMATCH (my guesses wrong): B has `v="signed-ceremony-authorisation/1"`, `alg="hmac-sha256"`, `purpose="pin-ceremony-authorisation"`, `DOMAIN="signed-ceremony-authorisation-v1"`; I assumed `"ceremony-authorisation/1"`, `"HMAC-SHA256"`, `"ceremony-authorisation"`, `"ceremony-authorisation-v1"`. Not breaking — these live inside B's payload projection, and the §7 *envelope dict* correctly omits them (they are not wire keys; my §1.1 conflated payload with envelope). No C code or test may assert my spellings. |
| `ceremony_id` generation | **BREAKING MISMATCH.** I required verifier-generated ("a caller-proposed id defeats its purpose"); B §3.1/§9(e) makes it caller-minted, a REQUIRED body key, verifier binds and burns it. Consequence: my §6.1 E2E helper as drafted calls `client.ceremony_authorise(...)` WITHOUT a `ceremony_id` argument that B's client signature requires — TypeError as written. **Ruling: adopt B.** On reflection the nonce property I wanted is delivered by ledger-burning + the derived `authorisation_id`, not by who mints the string; verifier-generation would also complicate the client's echo-binding. C's caller side adopts a minting convention (B's `<date>-<seq>` suggestion is fine; uniqueness is the ledger's job). Grammar nit: B's mode checks ids with signing's `_check_id` (`^[a-z0-9_-]{1,64}$`) while the env list uses verifier `_ID_RE` (leading alnum required) — a caller-minted id with a leading `-`/`_` would pass the mode and fail nothing, but pin the stricter grammar in the client helper to avoid a third spelling. |
| TTL | MATCH, tighter than asked: 900 s default AND 900 s hard cap, mode passes `min(config.ttl_seconds, 900)`. Meets my freshness expectation; my proposed global `TTL_MAX_SECONDS` bound is superseded by the cap. Expiry/skew vocabulary (`expired`, `signed_in_future`, 300 s skew) as expected, judged on my single captured `moment` via `now=`. |
| Verify signature / vocabulary | COMPATIBLE SUPERSET, one B-internal break. B's verify adds `expected_*` binding kwargs (all defaulted) — my simple call `verify_ceremony_authorisation(signed, signing_key=…, now=moment)` still works, and I will ALSO pass the `expected_*` bindings and keep my step-7b field reads (defence in depth, cheap). Vocabulary is a superset of my ask: adds `authorisation_id_mismatch` and the binding reasons (`operator_mismatch`, `ceremony_mismatch`, `reason_mismatch`, `old_pin_mismatch`, `candidate_mismatch`, `evidence_mismatch`, `evidence_ref_mismatch`). Non-breaking ONLY because C converts any non-`()` to `SigningError` without parsing; my E2E tests must assert `expired` and nothing more specific. **B-internal inconsistency:** B §7(ii)'s call passes `expected_signer_id=` and adds an `expected_verifier_signer_id` parameter to `reanchor_pin`, but §2.3's verify signature declares NO `expected_signer_id`. Resolve before build: my preference is add the parameter to verify AND the pin to `reanchor_pin` (a named verifier identity is part of the authority claim; the key alone does not name who should have issued it). |
| Client return shape / refusal surface | MATCH: client returns the envelope dict directly; unlisted operator → unsigned `VerifierConfigError` (exit 3), as my test 2 expects. |
| Issuance-side extra refusals | COMPATIBLE: B refuses at issuance for reason/pin incoherence and `candidate.cycle_seq < old+2` — relations `reanchor_pin` already refuses, so no issuable-but-unusable or usable-but-unissuable gap opens. My E2E test 13 (reason mismatch) still constructs: a `lost_pin` envelope (old_pin null) presented to a `chain_gap_recovery` ceremony refuses on old-pin binding. |

## A's closure — effect on `pin_ceremony`

**None, and that is correct.** A's only production changes
are `eval/gate.py` (constants + header), the
`trust/pathpolicy.py` mirror, tests, and two docstrings.
`signing/` is explicitly OUT in A's §1.1
(`signing/gate_decision.py` named as a consumer, not a
dependency definer) and §4.8 confirms no change; A never
proposes touching `pin_ceremony.py`, and the gate list does
NOT gain any `signing/` file. My ceremony work is purely a
B↔C interface. Two interactions worth recording, neither a
change: (i) A §6(i)'s demand that the env list be "injected
at the verifier boundary and the parameter must stop being
reachable from the request payload" is exactly what B §3.1
(strict key set — an `authorised_operators` body key is a
malformed request) plus D1's removal deliver; A, B and C
are aligned once D1 falls. (ii) A flag for the room, not a
disagreement: the NEW `signing/ceremony_authorisation.py`
will sit outside the gate's protected list, like
`pin_ceremony.py` today (A's L3 residual R-A covers the
class). Accept consciously; do not let the cycle record
imply the authority module is gate-protected.

## Agreements (brief)

With B: nested pin projections; record binding of both ids;
unsigned, unledgered refusals; ledger-before-return with
the ceremony journal as commit point; four-way evidence
non-equality stays in `reanchor_pin` (B §6.3 — neither
layer drops its half); `evidence_ref` stays opaque this
cycle. With A: exact-files closure (both `__init__` files
IN, no `trust/` prefix), mirror-in-the-same-commit
discipline, N1/N2 mutation-checked, R-A named rather than
absorbed, and the operator list living verifier-side in env
— never in `eval/gate.py`, never in-process.

## Missed by all three notes

1. **Import cycle between B's module and mine.** B §2.2 has
   `signing/ceremony_authorisation.py` import `REASONS` /
   `_NO_PIN_REASONS` from `signing/pin_ceremony.py`; my
   design has `pin_ceremony.py` import the envelope type and
   verify function from `ceremony_authorisation.py`. Loaded
   in either order, one module finds the other partially
   initialised. Nobody named this. Fix before build: move
   `REASONS`/`_NO_PIN_REASONS` DOWN into
   `signing/gate_decision.py` (the shared low-level module
   both already import) with `pin_ceremony` re-exporting
   them for compatibility — B's "no second copy of the
   allowlist" rule is preserved and the cycle is gone.
2. **Consumption-side replay of one envelope.** The ledger
   burns (ceremony_id, evidence_hash) at ISSUANCE; nothing
   burns the envelope at CONSUMPTION. The same envelope
   presented to `reanchor_pin` twice for the identical
   ceremony succeeds twice within its TTL whenever
   `ceremony_history` is not supplied — and history is
   still optional. My §7.10 flagged the shape, B's §7(ii)
   consumption note circles it, A is silent; no design
   closes or docstrings it. Ship condition: the residual is
   named in the §5 honesty bullets alongside D5's, or the
   room makes history mandatory for the envelope path —
   decide explicitly, not by omission.
3. **Clock basis mismatch in my own E2E plan.** B's mode
   signs with the verifier's real clock (900 s TTL); my
   §6.1 fixture builds snapshots at fixed `NOW`
   (2026-11-20). If the E2E reanchor passes `now=NOW`, a
   live-issued envelope reads as `signed_in_future`/
   `expired` against that moment. The E2E happy path must
   omit `now=` (real clock end-to-end); the `now=` seam is
   for the expired-envelope test only, computed from the
   envelope's own `expires_at`. (Same rule already applied
   to the unit helper in D1.)
4. **`signing/__init__.py` exports.** The new module's names
   (envelope type, sign/verify, serialisation) need
   re-export entries alongside attestation's; no note —
   mine included — assigns this file. One-line build task;
   unassigned one-line tasks are how surfaces drift.
