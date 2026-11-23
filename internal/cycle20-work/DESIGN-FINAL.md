# Cycle 20 — DESIGN-FINAL (coordinator rulings)

Designs: design-a.md (key boundary), design-b.md (evidence +
operator auth + deploy), design-c.md (consumption). Critiques:
critique-a/b/c.md. Where a critique amended its own seat's
design, the amendment stands unless a ruling below says
otherwise. Baseline: 1322 tests OK (skipped=26).

## R1 — Key boundary: Route 1, pure-Python Ed25519. ADOPTED.

design-a §2/§3 as written: new module signing/ed25519.py
(extended twisted-Edwards coordinates; affine code is a
TEST-ONLY oracle), domain signed-ceremony-authorisation-v2,
payload "v" …/2, "alg" "ed25519", signature hex128, key_id
"pub-" + sha256(public_key)[:16], authorisation_id_for formula
unchanged in shape, signed blob unchanged (domain\n alg\n
key_id\n payload_hash) as the Ed25519 message. Flag-day
cutover, NO dual-verify window (a dual window is the silent
fallback). Runner-up route 4 (delegated consumption) is NOT
built; it remains the named route for the cycles 14–16
consumption head.

## R2 — Strict verification profile. PINNED VERBATIM.

verify() in signing/ed25519.py, checks in this order, never
raises on bad input (returns False / the caller maps to
signature_mismatch): (1) exact lengths (pubkey 32, signature
64); (2) canonical decode of A and R — y < q and re-encoding
the decoded point reproduces the input bytes exactly; (3)
small-order blocklist: A and R rejected if their encodings are
any of the 8 small-order encodings, carried as LITERAL
constants in code and mirrored in tests; (4) S < L (S ≥ L
rejected); (5) cofactorless equation [S]B = R + [H(R‖A‖M)]A.
This is the strict profile (critique-a/c "ZIP-215-minus" made
exact): one signer, ours, so permissive-verification
interoperability is irrelevant and malleability is the enemy.

## R3 — The key-id tripwire is DELETED.

All three critiques converge: the retained id-inequality check
(authorisation key id != snapshot key id) can never fire —
"pub-…" and "key-…" ids are disjoint namespaces over different
hash inputs, including for identical underlying bytes. It is
removed from reanchor_pin and from the design. Separation is:
type separation (CeremonyPublicKey cannot hold secret
material; a SigningKey passed as the verify key is a type
refusal) + role separation (minting material absent from the
ceremony process). The real seed-reuse defence is
provisioning-side (R4). Any wording describing the deleted
check as a "derivation-regression guard" is also dropped — it
guards nothing.

## R4 — Verifier config: TWO new env vars, allowlist 15 → 17.

One atomic pass, owned by seat B, across all five copies
(run-verifier.sh ALLOWED_KEYS, trust/wiring.py, health_check.py,
setup.sh template, tests/test_trust_production_deploy.py
literal):
- AION_CEREMONY_EVIDENCE_DIR (design-b §1): absolute path;
  malformed spelling refuses startup in both modes; production
  + absent refuses startup; research + absent loads None and
  the mode refuses per-request (exit-3
  ceremony_evidence_unconfigured). Filesystem existence is a
  per-request check, not startup.
- AION_CEREMONY_SIGNING_SEED_PATH (critique-b §3.5): the seed
  does NOT ride AION_VERIFIER_KEY_PATH. Malformed value
  refuses startup in both modes; production + absent refuses
  startup (verifier_misconfigured); research + absent loads
  None and the mode refuses per-request (exit-3
  ceremony_seed_unconfigured); present-but-unloadable refuses
  startup. _load_config refuses a seed BYTE-EQUAL to the HMAC
  verifier key (an id comparison cannot catch it — R3). The
  refused-seed list includes the RFC 8032 §7.1 vector seeds
  used as test fixtures. Seed path scrubbed from env after
  load, like the key path. setup.sh templates BOTH variables;
  health_check verifies presence/consistency but NEVER reads
  seed bytes. Combined migration note (production must set
  AION_CEREMONY_OPERATORS + AION_CEREMONY_EVIDENCE_DIR +
  AION_CEREMONY_SIGNING_SEED_PATH or the verifier refuses to
  start) goes in setup.sh comments and the deploy README.
- Flag-day drain procedure (critique-b A-2, five steps) is
  written into the deploy README: a stranded in-flight
  ceremony's (ceremony_id, evidence_hash) pair stays burned;
  recovery is a new ceremony_id with a new evidence bundle
  under v2.

## R5 — Evidence resolution: design-b §1 with three amendments.

(a) RETENTION MOVES BEFORE the ceremony-journal append
(critique-a B-2): order becomes config gates → cheap
validation (incl. ref grammar) → membership → evidence
resolution + retention write → anti-replay scan → sign →
journal append (COMMIT POINT) → signing-ledger append →
anchor. Invariant: every committed ceremony has its evidence
retained. Retention is idempotent: an existing retained file
under the same authorisation_id with byte-identical content
(re-hash compare) is treated as already-retained and the flow
proceeds; different bytes under a derived id is a payload
collision and refuses pre-commit as ledger_failed-class.
A retention write failure refuses pre-commit — nothing is
burned, the request is retryable.
(b) Root scoping (critique-b B2 / critique-c B2): the evidence
root is resolved ONCE at config load; the fd-walk with
O_NOFOLLOW on every component applies BELOW the resolved
root; ancestors of the root (e.g. /var/lib canonicalisation)
may be symlinks. The resolve→walk residual window at the root
itself is named in the docstring, not hidden.
(c) Diagnosability (critique-c B3): the caller-visible refusal
stays the single exit-3 ceremony_evidence_unresolvable for all
existence/type/symlink sub-cases (no enumeration oracle), but
the verifier logs the specific sub-case on its own side; a
test asserts caller-visible bytes are identical across
sub-cases. The hash-mismatch (exit-2) and too-large (exit-3)
codes stay as design-b specified: they concern the
presenter's OWN named artifact, whose existence the presenter
already knows; the anti-oracle rule covers only what a
presenter could enumerate about artifacts they did not name.
Body stays 7 keys; the supplied evidence_hash is a cross-check
against the verifier-computed hash (mismatch = exit-2
ceremony_evidence_hash_mismatch, before any ledger write);
the COMPUTED hash is signed and is what the anti-replay scan
keys on. Size cap 1 MiB. Retention is NOT a consumption input:
an explicit non-goal sentence ("no consumption path reads
retained copies") goes in the mode docstring and in
pin_ceremony's limits (critique-c B4); the signed envelope
hash is the commitment to the retained bytes.

## R6 — Consumption: design-c as self-amended in critique-c.

- ceremony_history becomes a REQUIRED keyword of reanchor_pin
  (no default); explicit None refuses EARLY (before envelope
  verification) for every reason. Per-reason: chain_gap_recovery
  — non-None, empty allowed; initial_anchor — non-None AND
  empty only; lost_pin / corrupted_pin — non-None, empty or
  populated. _check_ceremony_history is unchanged; only the
  opt-in guard is deleted.
- Wording discipline (binding on BUILD-CYCLE-20, the brief,
  and all docstrings): the phrase is "fail-closed ON OMISSION",
  never bare "fail-closed"; F1 is "narrowed, still open" —
  the stale-history leg is conceded in full (critique-c point
  6): with a stale or honestly-empty history the replay still
  succeeds within TTL and can regress a since-moved pin; the
  protected monotonic consumption head remains the fix and an
  owner-level store decision. GPT's cycles 14–16 conditions
  (duplicate consumption fails with stale history) are
  explicitly NOT met by this cycle.
- Caller preconditions FRESH-PIN / COMPLETE-HISTORY /
  ATOMIC-ADOPTION / EVIDENCE-INTENT are documented in
  reanchor_pin's docstring AS caller obligations the function
  cannot verify (documentation, not mechanism — critique-b
  C-5 labelling).
- Verify-key API (resolving critique-a C-1/C-2 vs design-c
  §4.3): reanchor_pin takes authorisation_public_key=
  (a CeremonyPublicKey, defined in
  signing/ceremony_authorisation.py) — design-a's shape.
  design-c's expected_authorisation_key_id parameter is
  DROPPED (the object's key_id is derived from its bytes;
  re-pointing the object already refuses). expected_verifier_
  signer_id stays a separate pin. verify_ceremony_authorisation
  takes public_key=; key_id_inconsistent means the verify
  object lies about its own derived id (critique-c A1).
- v1 refusal is EXPLICIT (critique-c point 4):
  ceremony_authorisation_envelope_from_dict raises a
  SigningError NAMING the superseded version, checked before
  the hex128 format check; the golden v1 fixture test asserts
  the version wording, and a reanchor_pin-level test pins the
  refusal surface.
- There is NO verifier-side role in consumption and
  VerifierClient grows NO consume-side helper (critique-b C-1).

## R7 — Operator authentication: claim narrowed, no token.

design-b §2 decision stands (the appendix token scheme is NOT
built). The fused canonical sentence from critique-c §3 is
adopted VERBATIM in every location design-b §2.3 and design-c
§7 list (no per-file voice adaptation):

"Operator identity is operator-id allowlist eligibility via
the verifier's launch channel, not authentication: the
verifier checks that the presented operator_id was on its
configured allowlist at issuance; it does not and cannot
verify that the presenter *is* that operator — no
per-operator credential exists in this system, and any caller
able to launch the verifier can present any listed id. The
envelope proves a presentation under an allowlisted id,
ledgered at issuance and bound to this event — workflow
provenance, not cryptographic attribution: nothing in the
envelope is evidence *by* the operator, only *about* them,
and it does not prove which human or process made the
presentation."

Mechanical replacements ("operator authority" → "operator-id
allowlist eligibility", "authorised operator" → "allowlisted
operator id") per design-b §2.3. Grep gates after build:
"operator authority" zero hits in trust/ signing/ deploy/
outside internal/; "authentication of a human" zero hits in
signing/ trust/. Follow-up recorded: operator-authentication-
channel. Dilip's ratification (2026-11-23) covers the
verifier-env authority MODEL; this narrowing is the honest
statement of what that model proves, and the brief carries it.

## R8 — Client-side signature verification: ADOPTED.

VerifierClient.ceremony_authorise verifies the Ed25519
signature with the pinned CeremonyPublicKey in addition to
cycle 19's structural checks (payload/authorisation-id
re-derivation, pins, expiry, echo binding): it is the same
verify_ceremony_authorisation call, not a second verify path,
and it makes the client's key pin cryptographic at the
earliest point (GPT's key-distribution-boundary gate).
VerifierClient gains the public-key pin beside its existing
signer/key pins; trust/wiring.py's production_client pins are
updated by seat B. (design-a §3 lean + §6 Q8; critique-b A-6
decision request.)

## R9 — Timing: documented limit, not a blocker.

Pure-Python scalar multiplication is not constant-time; the
secret-dependent multiplications (secret scalar AND
deterministic-nonce scalar) happen only inside the verifier
process, which deployment runs as a dedicated OS user. Both
are named in signing/ed25519.py's and
ceremony_authorisation.py's honest limits. Verification
multiplies only public values.

## R10 — Claims sweep (GPT wording), full scope.

Adopted everywhere touched: dependency COVERAGE not complete
closure (any gate-closure phrasing in touched docs);
workflow provenance vs cryptographic attribution (R7 sentence
carries it); issuance accounting != consumption enforcement
!= anchored provenance as three separate claims. Single-use
scoping fixes (critique-b C-2 verified list):
ceremony_authorisation.py "burned on use" → "burned at
issuance"; verifier_main.py's two live refusal strings
("ceremony ids are single-use" / "evidence is single-use per
event") gain issuance scoping; trust/ledger.py is already
issuance-scoped (design-c overstated it — no change);
client.py has no single-use text (no change). Performance
wording: "≈10 ms class"; the build re-measures median + p95
for verify on this VM and records actuals in BUILD-CYCLE-20.

## R11 — Process rulings.

No pre-build re-poll of rev-r6 or the external seats
(critique-c decision 8): rooms review built code; the
external brief states the two-of-three-legs basis plainly.
File ownership for the build (single editor per file):
seat A — signing/ed25519.py (new), signing/ceremony_
authorisation.py, tests/test_signing_ed25519.py,
tests/test_signing_ceremony_authorisation.py;
seat B — trust/verifier_main.py, trust/client.py,
trust/wiring.py, deploy/verifier-identity/{run-verifier.sh,
setup.sh, health_check.py, README.md}, tests/
test_trust_ceremony_mode.py, tests/test_trust_ceremony_
authorisation.py (E2E), tests/test_trust_wiring.py,
tests/test_verifier_deploy.py,
tests/test_trust_production_deploy.py;
seat C — signing/pin_ceremony.py,
tests/test_signing_pin_ceremony.py.
Interfaces between files are exactly as ruled above; a seat
that finds a ruling unbuildable stops and reports rather than
improvising a new interface.
