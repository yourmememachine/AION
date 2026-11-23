# Cycle 25 war-room review — seat rev-r1

**Scope:** the approval artefact and its cryptography —
`trust/supersession_approval.py`, `trust/supersession_approval_tool.py`,
`internal/cycle25-work/design-approval.md`. Blind score/verdict filed
first in `internal/cycle25-work/blind-r1.md` (0.86, SHIP), before
reading any other seat's output. Tests run by this seat:
`python3 -m unittest tests.test_trust_supersession_approval` —
**22 tests, all OK** (pytest is not installed on this VM; unittest is
the working route).

Reviewed adversarially against seat-gpt's five criteria in
`internal/CROSS-CHECK-18.md`.

---

## Criterion-by-criterion

**(i) Genuinely independent authorisation event binding abandoned
head + replacement candidate + exact movement + original failed
attempt — PASS.**
The signed projection binds all four, in full:
- abandoned: authorisation id, ceremony id, and the complete
  (old → new) pair, including the genesis shape (old pin as
  `(null, "")` or `(seq, hash)` — the pair-consistency check in
  `_project_abandoned` refuses a mixed null/hash truncation);
- replacement candidate: candidate seq + payload hash, plus the
  replacement envelope's authorisation/ceremony ids, reason and
  operator;
- exact movement on *both* sides: the abandoned pair above and
  `superseding_old_* → candidate_*`, with candidate strictly ahead
  of the superseding old pin enforced in the projection;
- failed attempt: attempted authorisation id, the refusal code
  (pinned to the single constant `ceremony_supersede_required` —
  no other value is mintable or verifiable), and the head's
  authorisation id + journal seq + entry hash.

Cross-consistency is enforced *inside* the projection, not left to
callers: attempted id must equal the replacement envelope's id, and
the failed attempt's head id must equal the abandoned id. Two
apparent gaps close on inspection: the candidate's `signer_id`/
`key_id` are not approval fields, but they are inside the envelope
payload whose hash feeds the bound `authorisation_id`, so swapping
them changes the bound id and fails `replacement_mismatch`; and
head-entry fields the approval omits (operator, evidence hash) are
covered by the bound journal `entry_hash`. No bound field I probed
can be swapped, truncated, or replayed across movements: exact
key sets at every level, hex64/hex128 format pins, duplicate JSON
keys and non-finite numbers rejected at parse, and
`approval_binding_mismatches` compares every bound field against
verifier-derived facts. Replay of the *same* approval for the
*same* movement is bounded by expiry + head staleness (any head
movement changes seq/hash) at the artefact level; the decision-side
single-use rule is seat B's wiring, specified in design §6/§8.

**(ii) Independently recorded and verified BEFORE the envelope
(decision) issues — PASS at the artefact level.**
`verify_supersession_approval` is a pure, complete check the
verifier can (and per design §8 step 5b must) run before any
journal read or decision commit; the artefact carries the three
fields §6 requires to be recorded in the decision entry
(`approval_id`, `payload_hash`, `key_id` — exposed via
`approval_id_for`, the payload projection, and the pin type).
Ordering and journaling themselves are seat B's code, outside my
scope; nothing in the artefact obstructs them.

**(iii) Verifier refuses issuance on adopter auto-request alone —
PASS at the artefact level.**
There is no request shape in this artefact family that substitutes
for an approval: the projection cannot be produced without the
approver seed, the seed type/loader exist only in the tool module,
and the verify module exposes no minting path (see Finding 2 for
the precise strength of that statement). The adopter-side deletion
of the auto-request call is seat C's contract (§8); the artefact
makes it enforceable rather than voluntary, which is what
criterion (iii) lacked in cycle 24.

**(iv) Regression proof an ordinary recovery cannot self-escalate
— PASS at the artefact level.**
Three layers, each present in my scope: the projection refuses a
`burned_unadopted` replacement outright (un-mintable *and*
un-verifiable, not merely unusable — `test_recovery_replacement_unmintable`);
the tool refuses a `burned_unadopted` report envelope
(`test_report_recovery_envelope_refused`); and the envelope's
reason is inside the signed binding, so an approval minted for a
primary cannot be re-bound to a recovery envelope. The
adopter/verifier-side regression tests (call-count, valid-approval-
on-recovery-envelope) belong to seats B/C per design §8.

**(v) Restoration tests exercise the independently authorised
route — SUPPORTED.**
Seat A's own tests drive the real tool signing function
in-process *and* through the real CLI (`generate-key` →
`public-key` → `approve` → parse → verify clean), so the artefact
used in tests is genuinely signed, not stubbed — the precondition
design §8 sets for seat C's restoration tests.

---

## Cryptography and construction probes

- **Signature construction:** Ed25519 over
  `domain \n alg \n key_id \n payload_hash` under domain
  `signed-supersession-approval-v1`, disjoint from the ceremony
  domain; `approval_id` derived from (domain, payload hash,
  key id) with no secret participating. Verification recomputes
  the payload from the re-derived projection and checks the
  signature against the *recomputed* hash — a swapped
  `payload_hash`/`approval_id` field fails independently
  (`payload_hash_mismatch`, `approval_id_mismatch`,
  `signature_mismatch`), as the tampered-candidate test confirms.
- **Canonicalisation:** identical discipline to the repo's
  existing envelopes — `signing.gate_decision._canonical`
  (sort_keys, tight separators, `ensure_ascii=False`,
  `allow_nan=False`), sha256 payload hash, times normalised to
  UTC in the projection via `_normalise_time`. No new
  canonicalisation surface was invented. One cosmetic note: the
  artefact's stored `approved_at` is the signer's raw string
  while the payload carries the normalised form; re-derivation
  normalises again, so hashes are stable across spellings
  (mirrors the ceremony pattern; not a defect).
- **Alg pinning:** the projection emits `ed25519` only and a
  hand-constructed typed artefact claiming another alg dies as
  `malformed_payload` — the ceremony v2 discipline, correctly
  copied.
- **Key boundary:** `SupersessionApproverPublicKey` holds public
  bytes only and is deliberately *not* a `CeremonyPublicKey`
  (type refusal, never silent cross-use); the pin's key id is
  derived from the public bytes, never caller-supplied;
  `approver_public_key_from_hex` refuses anything but hex64.
  Tool-side, `SupersessionApproverKey` is disjoint from
  `CeremonySigningKey`, its repr leaks only key id + public
  fingerprint, the seed loader mirrors the ceremony loader's
  single-fd O_NOFOLLOW / owner-only / owner-uid / size-cap /
  not-in-repo discipline, `generate-key` is O_EXCL 0600 with an
  independent `secrets.token_bytes` draw, and `REFUSED_TEST_SEEDS`
  is refused. No notes.
- **Key separation check:** the verifier-side startup refusal if
  approver public key == ceremony public key is seat B's (§4.2(c));
  the artefact supplies both pins as comparable byte strings.
  Correctly, no stronger claim is made (design §4.1).

## TTL / expiry semantics

Default 900 s, projection-enforced window [60, 3600] s,
`signed_in_future` beyond the shared 300 s clock skew and
`expired` at `now >= expires_at` — the ceremony temporal
discipline, reused rather than reinvented. The deviation from
the envelope's 900 s hard cap is justified in design §6 and in
the module docstring (human-paced act; exposure bounded by
single-use, full binding, and head staleness), and the bound is
honest: the *cap* is enforced by the verify-side projection, so
no signer — including a compromised or careless tool invocation —
can mint a verifiable approval outside [60, 3600]. See Finding 1
for the one inconsistency in how the cap is reached.

---

## Findings

### Finding 1 — LOW: tool silently clamps over-cap TTL instead of refusing, contradicting design §3
Design §3 lists "TTL outside [60, 3600]" among the tool's
*refusals*, and the tool's own module docstring repeats that.
`sign_supersession_approval` instead does
`effective_ttl = min(ttl_seconds, APPROVAL_TTL_MAX_SECONDS)`:
`--ttl-seconds 99999` silently mints a 3600 s approval (enshrined
by `test_ttl_bounds`). This fails safe — the verify-side
projection enforces the cap regardless — so no criterion is
weakened, but an operator who asked for a longer window is not
told they didn't get it, and the design/code/test triangle
disagrees. Fix in one direction: refuse above the cap in the
tool (matching §3), or amend §3 and the docstring to say
"clamped". I recommend refusing: a deliberate act should not
silently differ from what was requested.

### Finding 2 — LOW: the "no signing capability" claim is import-level only, and the audit pins are evadable source scans
Two related precision points, neither exploitable without the
approver seed (which is the real barrier, and is genuinely
absent from the verify side):
(a) `trust/supersession_approval.py` does
`from signing import ed25519`, so the signing *function* is
reachable as `trust.supersession_approval.ed25519.sign`
(verified by probe). The docstring claim "NO signing function …
so importing it confers no minting capability" is true only in
the operative sense — no seed type, no seed loader, no seed in
scope — not literally at the import level. The same pattern
exists in the ceremony modules, but this module's docstring
states the stronger form; it should say capability is absent
because no seed material or loader is reachable, not because
the sign primitive is.
(b) The audit tests pin the property with a literal substring
(`ed25519.sign(` absent) and an import-regex over four files.
Probes confirm both are evadable by a determined in-repo author:
`getattr(ed25519, "si"+"gn")` defeats the substring pin, and a
`subprocess.run(["python", "-m", "trust.supersession_approval_tool", …])`
route in an adopter file defeats the import regex (the test's
comment claims a subprocess reference is excluded; the regex
does not in fact match that form). These pins are adequate as
*regression* pins against accidental erosion — which is what a
test suite can honestly provide — but design §3's phrasing
("checkable by import and source scan") should not be read as
adversarial authorship-proofing. Recommend: extend the
import-pattern to also match a bare `supersession_approval_tool`
string literal in the four running-system files (prose mentions
live in docstrings there, so this needs a docstring-aware scan
or a move of those mentions), or soften §3's wording. Not a
blocker: seat-gpt's criterion (iii) is about the *code path as
built*, and as built, grep confirms the tool module is imported
by nothing outside tests (remaining hits are docstring prose).

### Finding 3 — INFO: `public-key` CLI output differs from design §3
§3 specifies `public-key` prints "hex64 pubkey + key_id"; the
implementation prints only the hex64 public key (key id is
printed by `generate-key`). Harmless — the key id is derivable
and `generate-key` shows it — but provisioning runbooks written
against §3 will look for a second field that isn't there. Align
either side.

### Finding 4 — INFO: replacement `reason` is free text in the projection
`_project_replacement` accepts any non-empty reason string
except `burned_unadopted`, rather than the ceremony envelope's
allowlist (`REASONS`), and does not apply `_check_text`. This is
not exploitable in the composed system — `approval_binding_mismatches`
requires exact equality with the presented envelope's reason,
and the envelope projection enforces the allowlist — but the
verify-side artefact is marginally more permissive than the
pattern it mirrors. An allowlist check here would make the
projection self-contained. Optional hardening, no action
required for this cycle.

### Finding 5 — INFO: trust claim wording is precise everywhere checked
Design §1's claim (authorisation-event independence; explicitly
*not* a separate human or OS user; fully malicious same-user
process out of scope) is reproduced in substance in both module
docstrings, and grep finds "independent approver" / "second
operator" / "four-eyes" only inside §1's instruction not to use
them. The artefact is consistently called an *approval*, never
an authorisation, in the new code — §9's relabelling holds
within my scope. No overclaim found.

---

## Final verdict

The artefact discharges seat-gpt's criteria (i) and (iv) in
full, and supplies everything (ii), (iii) and (v) require from
the artefact layer; the binding is complete against swap,
truncation and cross-movement replay, the cryptography reuses
the repo's proven envelope discipline without deviation, and
the trust claim is stated precisely and nowhere upgraded.
Findings 1–4 are LOW/INFO and none weakens a criterion; Finding 1
should be reconciled before the external Q1 re-brief so the
design, code and tests tell one story.

**FINAL VERDICT: SHIP — score 0.86**
