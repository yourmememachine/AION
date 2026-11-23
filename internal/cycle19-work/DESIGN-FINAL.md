# Cycle 19 — FINAL AGREED DESIGN (coordinator synthesis)

Synthesised from design-a/b/c + critique-a/b/c. Where the seats
disputed, the coordinator ruling is marked RULING with the reason.
Everything below is the implementation contract. Sources:
internal/cycle19-work/design-*.md, critique-*.md.

## Part A — Gate scope extension (seat A owns)

A1. `eval/gate.py`: PROTECTED_PREFIXES unchanged `("eval/",)`.
PROTECTED_FILES becomes exactly:
`("core/loop.py", "oversight/__init__.py", "oversight/approval.py",
"trust/__init__.py", "trust/pathpolicy.py")` (order: keep
core/loop.py first, then alphabetical; the exact tuple is pinned
by tests, so any order is fine as long as gate + mirror agree).
The comment above the constants is extended to name WHY each new
file is protected (the gate judges canonical spellings through
trust/pathpolicy.canonicalise, which delegates to
oversight.approval.canonicalise_path; both package __init__ files
execute on that import path). It must NOT claim unqualified
"dependency closure": it names the closure as the
verdict-defining chain + import-path packages, with the L3
residual pointing at docs/GATE-CLOSURE.md. NO other eval/ change.

A2. `docs/GATE-CLOSURE.md` (NEW): the layered closure analysis
from design-a §2 — L0 verdict logic, L1 canonicaliser chain
(verified to terminate in stdlib + eval.gate), L2 import-path
__init__ files, L3 modules executed via trust/__init__ re-exports
incl. the sys.modules["trust.pathpolicy"] pre-seeding vector.
Residual R-A stated plainly: L3 pre-seeding is NOT closed by
this cycle; the structural fix is follow-up
`gate-import-isolation` (named, not built). Residual R-B: the
lazy import's raw failure stays untyped (out of authorised
eval/ scope). Residual M4: the new ceremony-authorisation code
(signing/ceremony_authorisation.py, the ceremony mode) is itself
outside every protected list — named, not extended this cycle.

A3. `trust/pathpolicy.py`: GATE_PROTECTED_FILES mirror updated
to the same five files + provenance comment; module docstring
updated where it describes the gate's list. The overlap is NOT
hidden: `oversight/approval.py` is now protected by BOTH lists
and classify() must report ["gate", "oversight"] for it.

A4. Test updates (seat A): tests/test_trust_pathpolicy.py
(mirror constants; re-derive the oversight-isolation assertion —
the lists now overlap at oversight/approval.py; do not hide the
overlap), tests/test_trust_pathpolicy_differential.py (EXPECTED
reclassifications per design-a §4.3; corpus grows with the new
trust/oversight rows; gate-miss and gate-stricter stay pinned
EMPTY), tests/test_gate.py (additive cases + exact-file negative
control: trust/manifest.py stays UNPROTECTED — guards prefix
creep), selfmod/canary.py docstring wording only (it does not
mirror the gate; verified), docs/PROVENANCE.md lines ~403-404
(old list quoted — update), oversight flip pinned:
is_protected_path("trust/pathpolicy.py") is now True (assertion
in tests/test_protected_gate_adoption.py or
tests/test_oversight_approval.py — seat A chooses).

A5. Negative tests (external seats' requirement), NEW class in
tests/test_protected_gate_adoption.py:
- N1: for EACH of trust/pathpolicy.py, oversight/approval.py,
  trust/__init__.py, oversight/__init__.py: check_protected_paths
  flags it; an otherwise-acceptable evaluate_self_change carrying
  only it is refused with reason protected_path and the violation
  in canonical spelling; non-canonical variants
  (trust//pathpolicy.py, oversight/./approval.py) flag with the
  canonical spelling reported.
- N2 (two-step): step 1 — a change editing only the canonicaliser
  (trust/pathpolicy.py) is refused protected_path; step 2 — with
  the canonicaliser unmodified, former gate-miss spellings
  (core//loop.py, eval//gate.py, trust//pathpolicy.py) are still
  refused. No in-process monkeypatch theatre (design-a §5).

## Part B — Verifier-side authority + provenance (seat B owns)

B1. Config: `AION_CEREMONY_OPERATORS` parsed ONLY in
_load_config (comma-separated ids; each must match the verifier
id grammar; duplicates/whitespace/empty entries/>64 entries are
malformed). Semantics (RULING on D4 — A's condition + B's final
position): production mode + absent/empty ⇒ startup refusal
verifier_misconfigured (exit 3), mirroring the anchor rule;
malformed ⇒ startup refusal in BOTH modes; research mode +
absent/empty ⇒ config loads with ceremony_operators=() and the
MODE refuses (below). _Config gains ceremony_operators.
Allowlist step (14→15 names) in ALL FOUR live copies:
deploy/verifier-identity/run-verifier.sh ALLOWED_KEYS,
trust/wiring.py ALLOWED_ENV_KEYS (+ its count comments),
deploy/verifier-identity/health_check.py's replicated tuple,
deploy/verifier-identity/setup.sh template; count-pinning tests
updated in tests/test_trust_wiring.py, tests/test_verifier_deploy.py,
tests/test_trust_production_deploy.py (test_31's hardcoded set);
a drift test pinning health_check.py's copy (critique-b missed
item). NOT added to wiring REQUIRED_ENV_KEYS.

B2. `signing/ceremony_authorisation.py` (NEW), modelled on
signing/attestation.py. Canonical literals (RULING M3 — B's
spellings): DOMAIN = "signed-ceremony-authorisation-v1";
payload "v": "signed-ceremony-authorisation/1"; purpose =
"pin-ceremony-authorisation"; alg = signing.gate_decision.ALG.
Payload fields exactly: v, alg, purpose, signer_id, key_id,
operator_id, ceremony_id, reason, old_pin (exactly
{cycle_seq, payload_hash} or null — never omitted), candidate
(exactly {cycle_seq, payload_hash, signer_id, key_id}),
evidence_hash, evidence_ref, signed_at, expires_at.
Divergence from attestation stated in the docstring: signer
(the verifier) != operator — the verifier signs ABOUT the
operator's presentation. The reason allowlist is a LOCAL mirror
of pin_ceremony's REASONS (this module must NOT import
pin_ceremony — import cycle, critique-c catch); a drift test
pins mirror == signing.pin_ceremony.REASONS. Payload projection
enforces: reason in allowlist; reason/pin coherence
(chain_gap_recovery requires old_pin non-null; the three no-pin
reasons require old_pin null); when old_pin present,
candidate.cycle_seq >= old_pin.cycle_seq + 2 (gap-only; the full
relation incl. prev-hash is the ceremony's check, verifier
cannot see prev). TTL: default 900s AND hard cap — effective
ttl = min(requested/config ttl, 900). Functions:
ceremony_authorisation_payload(...), sign_ceremony_authorisation(...),
verify_ceremony_authorisation(signed, *, signing_key,
expected_signer_id=None, expected_purpose=..., now=None) -> tuple
of reasons (16-term vocabulary from critique-b, incl.
signer_mismatch), authorisation_id_for(payload_hash, key_id),
SignedCeremonyAuthorisation dataclass with .payload() and
.authorisation_id, serialisation:
ceremony_authorisation_envelope_to_dict / _from_dict / _to_json /
_from_json. signing/__init__.py re-exports (seat B owns).

B3. SigningLedger addition (trust/ledger.py): append method for
the authorisation envelope with the EXISTING entry shape
unchanged (EXTRA_KEYS untouched — critique-b finding);
ceremony_id is documented into the proposal_id column.
NEW sibling store: CeremonyAuthorisationLedger(HashChainJournal)
in trust/ledger.py (or a small new module — seat B chooses;
budgets.json precedent), own file in the verifier home,
recording per issuance: ceremony_id, evidence_hash,
authorisation_id, payload_hash, operator_id, issued_at. It is
the single-use store of record.

B4. Verifier mode `ceremony_authorise` (trust/verifier_main.py;
add "ceremony_authorise" to trust/protocol.py MODES — seat B
owns protocol.py). Strict body key set exactly {operator_id,
ceremony_id, reason, old_pin, candidate, evidence_hash,
evidence_ref}. Order (issue_attestation discipline):
(1) config gate: ceremony_operators empty ⇒ _config refusal
ceremony_operators_unconfigured (exit 3, unsigned, unledgered);
(2) strict key set + cheap field validation ⇒ malformed (exit
2), NO ledger touched — ceremony_id grammar = signing _check_id
intersected with the verifier's stricter first-char rule;
evidence_hash hex64; evidence_hash == candidate.payload_hash ⇒
malformed (non-equality mirrored verifier-side);
(3) operator membership: operator_id not in config list ⇒
_config refusal ceremony_operator_not_authorised (exit 3,
unsigned, unledgered — no signed-reject artefact exists for
this mode);
(4) anti-replay scan of CeremonyAuthorisationLedger: same
ceremony_id with ANY differing bound field ⇒ refusal
ceremony_id_reused; same evidence_hash under a different
ceremony_id/event ⇒ refusal ceremony_evidence_reused (both
exit 3). An IDENTICAL re-presentation (same ceremony_id AND
all bound fields equal) is also refused (no idempotent
re-issue — critique-b: failures after commit burn the pair);
(5) sign with effective ttl min(config.ttl_seconds, 900);
(6) commit: ceremony-journal append FIRST (the commit point),
then SigningLedger.append_ceremony_authorisation, then
_update_anchor(config) per the existing pattern; any failure
after the ceremony-journal append ⇒ ledger_failed (exit 3) and
the (ceremony_id, evidence_hash) pair stays burned — recovery
is a NEW ceremony_id + NEW evidence bundle (documented in the
mode docstring + module docstring config section; the verifier
module docstring's config list gains AION_CEREMONY_OPERATORS).
Return {"signed_authorisation": <envelope dict>}.
Race honesty in comments: one process per request;
check-then-append is not atomic, but HashChainJournal._save's
under-flock freshness check guarantees at most one handed-out
authorisation per pair; the loser gets ledger_failed.

B5. Client (trust/client.py): ceremony_authorise(*, operator_id,
ceremony_id, reason, old_pin, candidate, evidence_hash,
evidence_ref) -> envelope dict, following VerifierClient
patterns (signer/key pin checks via the returned envelope,
expiry check). Exit-3 refusals surface as VerifierConfigError;
exit-2 as the existing malformed mapping. Returns the envelope
dict only.

B6. Honest limits (docstrings + brief), B §6.2 formulation
(RULING M2 — C's stronger draft wording is REJECTED): the
verifier never inspects the evidence artefact; a random hex64
from a LISTED operator is still issuable. What the envelope
proves: a listed operator presented this evidence hash bound to
this exact event, the presentation was ledgered single-use at
issuance, and the binding is signed by the verifier's key.
Operator identity = list membership via the launch channel,
not authentication of a human. HMAC symmetry + same-OS-user
prototype honesty carried over.

B7. Seat B tests: tests/test_signing_ceremony_authorisation.py
(envelope unit: payload projection refusals incl. coherence and
gap relation, mirror drift vs pin_ceremony.REASONS, sign/verify
round trip, each verify reason, serialisation strictness,
authorisation_id derivation); tests/test_trust_ceremony_mode.py
(real subprocess, following test_trust_verifier.py fixtures):
unconfigured refusal (research), production startup refusal
without the env var, malformed bodies burn nothing (ledger
untouched), invented operator refused unsigned + unledgered,
listed operator issued + ledgered in BOTH stores, ceremony_id
reuse refused, evidence reuse across events refused, identical
re-presentation refused, dual-append burn (simulate post-commit
failure if a clean injection point exists; otherwise test the
documented refusal surface), config grammar refusals (duplicates,
whitespace, >64). Plus the allowlist count updates in B1.

## Part C — Ceremony integration (seat C owns)

C1. `signing/pin_ceremony.py` — RULING on D1 (A + C-final over
B's interim concession; B's end-state adopted): REMOVE the
`authorised_operators` parameter entirely. reanchor_pin gains
REQUIRED keyword parameters: authorisation (a
SignedCeremonyAuthorisation object — a raw dict is refused),
authorisation_key (SigningKey), expected_verifier_signer_id
(str). operator_id / reason / evidence_hash stay as parameters
and must EQUAL the envelope's bound values exactly.
Verification order inside reanchor_pin:
(1) authorisation is a SignedCeremonyAuthorisation and
authorisation_key a SigningKey, else SigningError;
(2) KEY SEPARATION (RULING on D2 — A + C-final): if
authorisation_key.key_id == signing_key.key_id ⇒ SigningError,
checked BEFORE envelope verification;
(3) verify_ceremony_authorisation(authorisation,
signing_key=authorisation_key,
expected_signer_id=expected_verifier_signer_id, now=moment)
with the ceremony's single captured clock — non-() ⇒
SigningError naming the reasons;
(4) EXACT binding equality vs captured actuals: envelope
operator_id == operator_id arg; envelope reason == reason;
envelope old_pin == captured old pin {cycle_seq, payload_hash}
(or both null); envelope candidate == {signed.cycle_seq,
signed.payload_hash, signed.signer_id, signed.key_id};
envelope evidence_hash == evidence_hash arg. Each mismatch its
own SigningError. evidence_ref is NOT equality-checked
in-process (no ceremony-side counterpart) — bound transitively
via the record (C2).
(5) The existing evidence non-equality check (vs candidate's
four hashes) still runs — defence in depth.
No fallback: envelope failure never falls back to anything;
there is no other path. All other ceremony logic (relation,
recomputation, history, bare-verifier candidate check) is
unchanged.

C2. PinCeremonyRecord: ceremony_id and authorisation_id become
REQUIRED fields (RULING on D3 — A + C-final), appended after
signature with NO defaults; payload() includes both; the single
constructor call in reanchor_pin passes authorisation.ceremony_id
and authorisation.authorisation_id. verify_ceremony_record
gains invariant checks under the single shared reason
"invalid_authorisation": ceremony_id must satisfy _check_id,
authorisation_id must be hex64. (No legacy records exist to
migrate: no persisted record store; tests only replace() real
records.)

C3. Docstring honesty rewrite in pin_ceremony.py (seat C drafts,
B §6.2 formulation for evidence): the caller-supplied-authority
bullet and the evidence bullet are rewritten — authority now
comes from a verifier-issued, event-bound authorisation whose
operator list lives in the verifier's protected config; evidence
provenance = attribution + event binding + issuance-side
single-use + signed binding (NOT artefact inspection). The
cycle-16 "does NOT fix" paragraph is amended: items (1) and (2)
are now addressed via the protected path, with these REMAINING
limits named: consumption-side replay — the ledger burns at
issuance, not consumption; the same envelope presented to
reanchor_pin twice within its TTL succeeds if ceremony_history
is omitted (history stays optional this cycle; making it
mandatory belongs to the held cycles' re-review); no
consumption-side ledger-presence check exists in-process
(limit M5); the ceremony journal's reuse memory is
rollback-vulnerable until follow-up ceremony-journal-anchoring
(prevented against an intact journal, audit-detectable after
rollback); the record MAC still uses the snapshot signing key
(key separation for the AUTHORISATION is enforced in C1(2);
the record's own key is unchanged).

C4. tests/test_signing_pin_ceremony.py conversion (seat C owns):
the single reanchor() helper (lines ~56-68) is rewritten to mint
an in-process envelope via sign_ceremony_authorisation with a
DISTINCT test verifier key (key separation), passing
authorisation/authorisation_key/expected_verifier_signer_id.
Conversion traps (critique-c): mint now= must equal the
ceremony's now= (cycle-16 tests run at LATER — the 900s TTL
makes clock discipline load-bearing); old_pin projected to
{cycle_seq, payload_hash}; the operator-9 refusal case becomes
a binding-mismatch refusal (or moves to B's mode tests); the
malformed evidence_hash="xyz" case is rewritten as a tampered
envelope. Plus NEW unit tests: same-key refusal
(test_same_key_as_snapshot_refused), envelope-for-other-event
binding refusals (operator/reason/pin/candidate/evidence each),
expired envelope, wrong-key envelope, dict-not-object refusal,
record carries ceremony_id + authorisation_id and
verify_ceremony_record accepts it / refuses a tampered one with
invalid_authorisation.

C5. E2E (seat C owns): NEW tests/test_trust_ceremony_authorisation.py
following test_trust_verifier.py fixture discipline, real
verifier subprocess WITH AION_CEREMONY_OPERATORS set: happy
path — client.ceremony_authorise for a listed operator →
envelope → reanchor_pin succeeds with NO caller list anywhere;
invented operator ⇒ VerifierConfigError and no envelope exists;
replay of the issued envelope against a different candidate and
against a different old pin ⇒ SigningError at binding; evidence
swap ⇒ refused; the SAME envelope consumed twice succeeds
within TTL without history (pins the C3 documented limit —
test named for the limit, not as a feature); happy path omits
now= on the live-clock side (critique-c clock catch) or uses
one captured now consistently.

## Cross-cutting

X1. Full suite must be green at the end (baseline 1245 OK,
skipped=26). No state.json edits; no loop-state advance.
X2. Follow-ups named (recorded in BUILD-CYCLE-19.md, NOT built):
gate-import-isolation (R-A), ceremony-journal-anchoring (D5),
consumption-side ledger check (M5).
X3. Item A is in scope for the war room: verify intact
(tests/test_protected_gate_adoption.py existing legs +
eval/registry.py + eval/calibration.py duplicate-key hooks).
X4. Commit order within the implementation: gate + mirror land
together (drift tests make a split tree red).
