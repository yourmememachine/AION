# Cycle 19 — Cross-critique, seat B (verifier authority)

Verdicts first. I concede more than I expected to: C's greps are
correct on D1's cost accounting and D3, and A's production precedent
is stronger than my §1.1 argument on D4. I hold on the substance of
REQUIRE (D1's end state), domain-separated key handling without an
in-process equality refusal (D2), and deferring ceremony-journal
anchoring (D5) — with the honest framing tightened below.

Code checks run this round (not from memory): `authorised_operators`
occurrences, every `reanchor_pin(` call site, every
`PinCeremonyRecord(` construction, `_load_config`'s production
rules, `trust/anchoring.py`'s kind registry.

---

## D1 — Legacy list: CONCEDE the interim, HOLD the end state

**What actually breaks if the parameter is removed — counted.**
C overstates the blast radius and I understated it; the truth:

- `authorised_operators` appears in exactly **3** places:
  `signing/pin_ceremony.py:392,408–409` (the function) and
  `tests/test_signing_pin_ceremony.py:62` — one
  `kw.setdefault("authorised_operators", AUTH)` line in the test
  module's `reanchor()` helper.
- There is exactly **one** direct `reanchor_pin(` call in the whole
  tree: the helper itself (`test_signing_pin_ceremony.py:68`).
  All **43** `reanchor(...)` wrapper calls flow through it.
- My §7(ii) signature also *deletes* `operator_id`, `reason`,
  `evidence_hash` as parameters (derived from the envelope) — the
  helper `setdefault`s all three too, so the helper must stop
  passing them and instead mint an envelope binding them.

So: **a green suite without touching any held test *method* is
achievable** — rewrite only the helper (~one function: second test
key + `sign_ceremony_authorisation` mint per call). C's "forces
rewriting tests/test_signing_pin_ceremony.py NOW" is true of the
*file*, false of its test cases; my "mechanical change" was right
on size, wrong to wave at.

**Why I still concede the interim.** The helper rewrite makes the
held cycles' unit tests mint envelopes *in-process, directly via
the sign function* — they would exercise B's verify path but never
the verifier's list, i.e. the held suite would silently stop
testing the thing 14–16 were reviewed on (list membership) before
their re-review has accepted the replacement. That couples the
re-review's verdict to a test-surface change made under cycle-19
time pressure. C's sequencing (extension lands → re-review adopts
envelope as a *condition*) is the owner decision's own order.

**Exact deprecation contract I accept** (all of it, no subset):

1. C's exactly-one-path resolution, verbatim (§1.3 step 4): both
   supplied ⇒ refuse; neither ⇒ refuse; envelope without key ⇒
   refuse; key without envelope ⇒ refuse. No fallback ladder.
2. The list path is named **UNPROTECTED** in the module docstring,
   `reanchor_pin`'s docstring, and the parameter's own comment —
   C's §5(b) draft wording stands as written.
3. Legacy use is permanently visible: legacy records carry
   `ceremony_id == authorisation_id == ""` (see D3); a record
   reader can never mistake the path taken.
4. **Sunset, dated by event not by vibes:** the parameter is
   *deleted* — not deprecated-forever — in the same change that
   re-reviews cycles 14–16, and that re-review may not ship while
   any production-reachable caller passes the list. Until then no
   NEW caller may use the legacy path; the only sanctioned caller
   is the existing test helper.
5. Cycle 19's ship claim is scoped accordingly: the *verifier
   issuance* path is authority-fixed at ship; the *ceremony* is
   authority-fixed only on the envelope path, and no brief may
   describe the ceremony as fixed without that qualifier (my
   original transitional note, now binding on both paths' docs).

What I do not concede: shipping the interim as the end state.
Gemini's "opt-in protection is the defect" is answered by C's
not-silent / not-a-toggle / leaves-a-trace argument for the
*interim*; it is not answered for a permanent dual path, and
item 4 is what keeps that true.

## D2 — Key separation: CONCEDE the in-process refusal, HOLD separation

**C's fixture argument, checked concretely.** No existing fixture
calls `reanchor_pin` with an `authorisation_key` — the parameter
does not exist yet, so *no* fixture breaks today. The real
exposure is prospective, and it is mine as much as C's:

- The only `reanchor_pin` caller, the pin-ceremony test helper,
  uses **one** global key (`KEY = make_signing_key(bytes(range(32,
  64)))`) for snapshots *and* records. Under D1's end state its
  envelope mint would naturally reuse `KEY` as the authorisation
  key too — my refusal would break the helper I just rewrote.
- C's E2E (§6.1) in fact keeps the keys distinct almost by
  accident: `authorisation_key=self.key` (the verifier fixture's
  `generate_key_file` key) vs the snapshot `KEY` above. So C's
  "fixtures legitimately run one key" is weaker than stated for
  its own E2E — but its *principle* is right, for a better reason
  than fixture convenience:

**Why the refusal buys nothing.** The threat it would stop is a
key holder forging an authorisation. Under the prototype's own
honesty (§6.4, and C §3 says the same), anyone holding
`authorisation_key` in-process can forge regardless of whether it
equals `signing_key`; anyone holding only `signing_key` is stopped
not by an equality check but by **domain separation** — the
envelope MAC is under `signed-ceremony-authorisation-v1`, the
record MAC under `snapshot-pin-ceremony-v1`, and cross-verification
fails. An equality refusal therefore only catches *accidental*
key reuse in deployments where the same operator legitimately
holds both keys on one host — a provisioning smell, not an
exploit. GPT cycle-16's "provisioned and enforced" is satisfied
by provisioning + pinning, enforced where enforcement bites:

- **Committed instead:** (a) domain separation (already in both
  designs); (b) `expected_verifier_signer_id` pinning at
  consumption — the envelope's `signer_id`/`key_id` must match the
  pinned verifier identity, which is a real check with real
  refusals (`unknown_key` / binding mismatch); (c) production
  wiring must provision **distinct key files** for verifier and
  snapshot signer, stated as a deployment requirement in both
  modules' docstrings (A's wiring question, §7 answer 9 below).
- If the war room overrules and wants the in-process refusal: it
  is one line in C's step 4 and the D1-end-state helper grows a
  second key constant. I will not split the room over it — but
  the brief must then not claim it stops a forger; it stops a
  typo.

## D3 — Record fields: CONCEDE (trailing, defaulted)

C's verification is exact and I re-ran it: `PinCeremonyRecord(`
is constructed **once** (`pin_ceremony.py:524`, inside
`reanchor_pin`); no test constructs one directly; tests mutate
real records via `dataclasses.replace(...)` (test file lines
162, 215, 221, 224, 287, 320, 372–374), which carries new fields
untouched; no test pins a literal record `payload_hash`.

My "required fields break loudly, defaults are the (ii) defect
in miniature" argument collapses under D1's conceded interim:
on the legacy path there *is* no authorisation, so required
fields would force `reanchor_pin` to fabricate values or pass
`""` explicitly — the sentinel exists either way; a default
merely puts it in one place. And the loud-breakage benefit has
no victim: the sole constructor is the function we are editing
anyway.

**Committed shape:** `ceremony_id: str = ""` and
`authorisation_id: str = ""` appended **after `signature`** (last
two fields, defaults `""`), both included in `payload()` from
birth, both populated non-empty by `reanchor_pin` on the
envelope path. `verify_ceremony_record` invariants per C §4,
with **one shared reason `"invalid_authorisation"`** for a
malformed non-empty value of either field (I drop my split
`invalid_id`/`invalid_authorisation` suggestion — C is right
that the vocabulary stays smaller shared). Empty ⇒ legacy
record, no reason. Post-hoc stripping is caught by
`payload_hash_mismatch` unless re-MACed by the record key
holder, who could forge a record outright anyway — stated so
nobody oversells the sentinel.

## D4 — Production startup refusal: CONCEDE A's condition

A is right, and my §1.1 precedent check was incomplete. I argued
"startup-required breaks gate-only deployments"; but
`_load_config` *already* refuses production startup over config
for capabilities a given request may never use: production
requires `AION_ANCHOR_PATH` (verifier_main.py:329–338) and
`AION_BUDGETS_ANCHOR_PATH` (:384–388) unconditionally, and
refuses the INIT flags outright. Production's established
philosophy is *fail closed at startup about protective config*;
research is where optionality lives. Cycle 11's defect — blank
`AION_DEPLOYMENT_MODE` silently selecting research — is the same
shape as my proposal's failure mode: a production deployment
with the var typo'd/absent would run indefinitely with the
ceremony silently disabled, discovered only when an operator
actually needs a re-anchor (the worst moment to discover it).
Mode-level refusal is fail-closed at *use*; A's condition is
fail-closed at *deployment*, and production is exactly where
that difference matters.

**Committed contract:**

- `deployment_mode == "production"` and
  `AION_CEREMONY_OPERATORS` absent/empty ⇒ startup refusal
  `_config("verifier_misconfigured", "production mode requires
  AION_CEREMONY_OPERATORS")`, exit 3 — mirroring the anchor
  rules' wording and placement in `_load_config`.
- Research mode: my original design stands — absent/empty ⇒
  `ceremony_operators = ()`, mode-level
  `ceremony_operators_unconfigured` refusal. Every existing
  fixture is research, so the suite is untouched.
- Malformed value ⇒ startup refusal in **both** modes (unchanged
  from my §1.1: a malformed protected list is a deployment
  error, never a per-request event).
- My §1.2 allowlist steps are unchanged; the var stays out of
  `wiring.REQUIRED_ENV_KEYS` (that file builds a *gate client*;
  the production requirement is enforced verifier-side at
  startup, which is where AION_DEPLOYMENT_MODE's own
  requirements live too).

## D5 — Anti-replay residual: framing for the brief, and deferral DEFENDED

**Strongest honest framing (use this text in the brief):**

> Single-use is enforced against the ceremony journal as it
> stands. Rolling back `ceremony-authorisations.json` alone
> does not trip any startup check (the external anchor covers
> only the signing ledger), and erases the verifier's
> evidence-reuse memory: a **listed** operator could then
> obtain a second authorisation for the same evidence under a
> new ceremony_id. Rollback grants nothing else — no unlisted
> operator is admitted, no envelope is forged, issuance still
> requires the verifier key and the env list — and the
> duplicate issuance is **detectable, not preventable**: both
> issuances appear as `ceremony-authorisation` sign entries in
> the anchored signing ledger, so an auditor holding the issued
> envelopes can prove the same `evidence_hash` was authorised
> twice. Until `ceremony-journal-anchoring` lands, the
> evidence-reuse guarantee is: *prevented against an intact
> journal, audit-detectable after a journal rollback.* Do not
> shorten this to "rollback-resistant" anywhere.

Note the qualifier I am adding to my own §4.5: detection needs
the envelopes retained (the signing ledger stores
`payload_hash`, not the payload) — "visible in the ledger"
alone overclaims; the sentence above is the corrected claim.

**Feasibility this cycle: correctly deferred, and it is not a
one-line wire-up.** The existing anchor mechanism does not
accept a new journal by configuration: `trust/anchoring.py`
pins `ANCHOR_KINDS = ("signing", "ship", "ship-tx")` and
`_check_kind`/`verify_anchor` refuse anything else; the budgets
anchor is *bespoke* code in `verifier_main.py`, not a reusable
instance of the generic mechanism. Wiring the ceremony journal
in means: a new anchor kind in anchoring + its tests, **two new
env vars** (`AION_CEREMONY_ANCHOR_PATH`/`_INIT`) — which
reopens my §1.2 allowlist migration (15 → 17 names, four
mirrors, every pinned count), `_Config` fields, startup
verification + production rules for a third anchor,
outside-home placement checks (budgets precedent), and an
update call on every issuance. That is a seat-A-sized change
stacked on this cycle's already-three-seat surface. Defer as
the named follow-up `ceremony-journal-anchoring`, gated on the
framing above appearing in the cycle-19 record and in
`verifier_main`'s docstring honesty statement.

---

## C's §7 asks — committed answers (superseding my note where they differ)

1. **Payload keys:** mine, as in my §7(i) — nested `old_pin`
   (exactly `{cycle_seq, payload_hash}`), nested `candidate`
   (exactly `{cycle_seq, payload_hash, signer_id, key_id}`),
   no flat spellings. C's binding code is written against this.
2. **Verify function — committed, and my note had a bug:** my
   §2.3 signature omitted `expected_signer_id` while my §7(ii)
   call site passes it. The committed signature is:
   `verify_ceremony_authorisation(signed, *, signing_key,
   expected_signer_id=None, expected_operator_id=None,
   expected_ceremony_id=None, expected_reason=None,
   expected_old_pin=_CONTEXT_UNSPECIFIED, expected_candidate=None,
   expected_evidence_hash=None, expected_evidence_ref=None,
   now=None) -> tuple`. **Reason vocabulary — committed, final:**
   `key_id_inconsistent`, `unknown_key`, `malformed_payload`,
   `payload_hash_mismatch`, `authorisation_id_mismatch`,
   `signature_mismatch`, `signer_mismatch`, `operator_mismatch`,
   `ceremony_mismatch`, `reason_mismatch`, `old_pin_mismatch`,
   `candidate_mismatch`, `evidence_mismatch`,
   `evidence_ref_mismatch`, `signed_in_future`, `expired`.
   (`signer_mismatch` is the one addition, forced by the
   `expected_signer_id` pin.) Expiry semantics: `now >=
   expires_at` ⇒ `expired`; `now=` is a test seam only.
3. **`authorisation_id`:** dataclass field **and** a derivation
   function — committed as `authorisation_id_for(payload_hash,
   key_id)` (C's ask; `snapshot_id_for` precedent beats
   attestation's private `_attestation_id` here because C's
   client-side re-derivation needs it).
4. **`ceremony_id` grammar:** yes, it is signing's `_check_id`
   at consumption — `^[a-z0-9_-]{1,64}$` (`gate_decision.py:115`).
   But issuance is stricter: the verifier's `_ID_RE` is
   `^[a-z0-9][a-z0-9_-]{0,63}$` (first char alphanumeric).
   **Effective minting grammar is the intersection — must start
   `[a-z0-9]`.** And on minting itself C and I contradict each
   other (see Missed-1): **the caller mints it** (my §9(e)
   stands). It is a field of the issuance *request*; a
   verifier-generated id could not be ledger-burned against the
   request that carries the evidence, and C's own client helper
   passes it in. C's `"cer-" + token_hex(8)` string is a fine
   *caller-side* convention and satisfies the grammar.
5. **TTL:** committed in my §2.4 — default 900 s, hard cap
   900 s for this envelope type; verifier passes
   `min(config.ttl_seconds, 900)`.
6. **Serialisation names — committed (mine, not C's assumed
   short forms):** `ceremony_authorisation_envelope_to_dict` /
   `ceremony_authorisation_envelope_from_dict` /
   `ceremony_authorisation_envelope_to_json` /
   `ceremony_authorisation_envelope_from_json`, strict key sets
   per my §2.3. `reanchor_pin` takes the **object**, never a
   dict — agreed with C §7.6.
7. **Client refusal surface — committed:** `VerifierClient.
   ceremony_authorise(...)` returns the **envelope dict only**.
   Unlisted operator, replay, evidence reuse, unconfigured list
   ⇒ exit 3 ⇒ **`VerifierConfigError`** (unsigned refusals; there
   is no signed refusal envelope — my §3.2 step 3 reasoning
   stands). Malformed requests ⇒ exit 2 ⇒
   `VerifierProtocolError`. This answers C's test 2: it asserts
   `VerifierConfigError`.
8. **C's §5(c) claim is false for my design and must be
   weakened before the build:** the verifier does **not**
   source or check the evidence artefact (my §6.2 — it never
   opens it; a random hex64 from a *listed* operator is
   issuable, attributable, single-use). C's draft sentence
   "evidence it has itself sourced/checked in its protected
   store" describes a store neither A nor B designed. Replace
   with B §6.2's provenance definition (authenticated,
   event-bound, attributable, single-use — not
   artefact-verified). This was A's ask-8 too; B's answer
   settles it against the stronger claim.
9. **Single-use (C ask 10):** issuance-side ledgering is in my
   design (§4.2/§4.3 — both journals, commit point first).
   Consumption-side identical-envelope re-presentation without
   `ceremony_history` remains a stated residual — agreed, it
   goes in the docstring, not just this critique.

## A's closure design — assessment from B's surface

**Agreements, briefly:** exact files, no `trust/`/`oversight/`
prefix (§1/§2.3 — the prefix-creep argument is decisive);
L1+L2 closure is exact because the canonicaliser chain
terminates in stdlib + already-protected code; R-A named and
backlogged as `gate-import-isolation` rather than absorbed;
N2's refusal to fake an in-process monkeypatch test; the
`classify()` overlap reported truthfully (`["gate",
"oversight"]`), including re-deriving the oversight-isolation
test rather than re-tabling it. No gate-side API for ceremony
authority (§6(ii)) — agreed in full; a list constant inside
`eval/gate.py` would be presentable by any caller and verifies
nothing.

**What changes my surface:**

- **`trust/protocol.py` `MODES` addition is B's to own.** A
  treats protocol as outside its surface and my §3.0/§9 flagged
  it as "seat A coordination" — that was me mis-assigning my
  own plumbing. `protocol.py` is verifier transport, not gate
  code; B lands the one-line `MODES` addition with the mode,
  and A's §4.8 confirmation (no protected-list pin in
  `verifier_main`) means nothing else of A's moves.
- **A's §4.5 consequence touches nothing of mine:** oversight's
  `is_protected_path` becoming True for the two trust files
  changes ceremony-*authorisability* through the approval
  workflow, not verifier issuance. Noted, no action.
- A's build sequencing (gate + pathpolicy mirror in one commit)
  is independent of B's allowlist sequencing (§1.2 steps 1+6
  together) — the two same-commit constraints do not interact;
  either order lands green provided each pair is atomic.

## Missed by all three notes

1. **Who mints `ceremony_id` — B and C flatly contradict.**
   B §9(e): caller's duty, verifier binds and burns. C §1.1:
   "The verifier generates it… a caller-proposed id defeats
   its purpose." Neither note flags the other's position; A's
   is silent. Resolved in my §7-answer-4 above (caller mints),
   but the room should ratify it explicitly — it changes the
   client signature C builds against. (C's stated reason is
   also weak: the id's anti-replay force comes from the
   ledger burn, not from who chose the string.)
2. **The envelope's identity strings diverge between B and C.**
   B: `v = "signed-ceremony-authorisation/1"`, domain
   `"signed-ceremony-authorisation-v1"`, purpose
   `"pin-ceremony-authorisation"`. C §1.1: `v =
   "ceremony-authorisation/1"`, domain
   `"ceremony-authorisation-v1"`, purpose
   `"ceremony-authorisation"`, and `alg` spelled
   `"HMAC-SHA256"` vs the codebase's `"hmac-sha256"`. These
   strings are MAC inputs — if each seat builds to its own
   note, nothing cross-verifies and the failure looks like a
   signature bug. **Committed: B's spellings** (the MAC owner
   pins them; they follow attestation's `signed-attestation/1`
   pattern). C's payload *shape* otherwise matches mine.
3. **My own §2.3/§7(ii) signature inconsistency** (above,
   §7-answer-2) — neither A nor C caught that the verify
   function I specified cannot accept the call I prescribed.
4. **The dual-append recovery story has no runbook.** My §4.3
   makes the ceremony journal the commit point and withholds
   the envelope on any later failure — so a transient signing-
   ledger failure permanently burns a (ceremony_id,
   evidence_hash) pair, and recovery requires a *new evidence
   bundle* (new hash), not a retry. No note (mine included)
   writes the operator-facing recovery procedure, and C's E2E
   has no test for "burned pair, fresh bundle succeeds."
   Add the test; the runbook line goes in `verifier_main`'s
   docstring with the mode.
5. **Health-check allowlist drift (I flagged it, nobody
   picked it up):** `health_check.py`'s `ALLOWED_KEYS` is a
   literal copy with no cross-check test against the wrapper.
   Cycle 19 is exactly the change that drifts it. Whoever
   lands §1.2 should add the drift test in the same commit —
   cheap, and it retires a whole class of future silent
   divergence. (A §9(d) was asked; no answer landed in A's
   note.)

---

*Summary of movement: D1 concede-interim (contract above, sunset
at 14–16 re-review), D2 concede in-process refusal (separation =
domain + signer pin + distinct production key files), D3 concede
(trailing defaulted fields, shared `invalid_authorisation`), D4
concede (production startup refusal; research keeps mode-level),
D5 defend deferral with the tightened brief framing. All C §7
names committed above; B owns `protocol.py`.*
