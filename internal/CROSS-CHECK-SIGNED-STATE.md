# Cross-check record — signed-state (external seats)

Brief: `internal/CROSS-CHECK-BRIEF-SIGNED-STATE.md` (blind; no
internal verdicts or scores included). Sessions run 2026-11-20
~12:00 UTC on the user's Google sign-in.

## seat-gpt (ChatGPT) — FIX, confidence 0.86

Reviewed the design description, not the source (its own
qualification). Findings: F1 chain may be descriptive, not
enforced (HIGH); F2 multi-file consistency unresolved at the
module boundary (HIGH); F3 pin is not an independent rollback
authority — pin storage requirements belong in the security
contract (HIGH); F4 structural validation is not provenance
validation (MEDIUM-HIGH); F5 expiration authentication needs an
explicit invariant (MEDIUM — in the code, `expires_at` and
`signed_at` are inside the MACed payload and TTL bounds are
re-derived on verify, so this one is satisfied by construction
and now stated in the record); F6 HMAC identity is group
membership, not individual authorship (MEDIUM). Additional
limits it required: chain completeness is not established by
links alone; clock trust is an external dependency. Both added
to the module docstring.

## seat-gemini (Gemini) — FIX, confidence 0.84

Findings: #1 `prev_snapshot_hash` carried without verification
(HIGH); #2 cross-file TOCTOU, plus empty-bytes vs None ambiguity
(HIGH); #3 canonical serialisation underspecified (MEDIUM — the
code uses one canonical encoder, `sort_keys`, tight separators,
`allow_nan=False`, with domain framing in the MAC input; stated
here for the record); #4 clock-skew boundary semantics
(MEDIUM — sign and verify share the payload builder, so the
anti-backdate rule is identical on both paths); #5 pin advance
only after full verification (MEDIUM — verify returns all
reasons before any success, and the docstring now states the
pin-advance rule); #6 declared limits omit key rotation and
replay-within-TTL (LOW — both added to the docstring; the
envelope does carry `key_id`, and a retired key reports
`unknown_key`).

## Reconciliation

Adopted as code: chain verification (`expected_prev_snapshot_hash`
+ pin-successor rule), `sign_state_files` double-read capture,
empty calibration bytes refused, pin hardening. Adopted as
documentation: pin storage contract, chain completeness, clock
trust, group membership, replay, TTL-vs-provenance. Not adopted:
an atomic generation/manifest protocol for the two files and a
pin persistence ceremony — deployment machinery beyond this
module, recorded as open limits in `BUILD-SIGNED-STATE.md`.
Verdict stays PROVISIONAL until an external re-review of the
fixed code; neither seat has re-reviewed.
