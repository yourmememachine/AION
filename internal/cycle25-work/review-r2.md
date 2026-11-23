# Cycle 25 — Review, seat rev-r2 (VERIFIER side)

Scope: `trust/verifier_main.py` (`_mode_ceremony_supersede`, `_load_config`
approver-key handling), `trust/ledger.py` (`CeremonySupersessionLedger`),
`trust/client.py` (`ceremony_supersede`). Blind score/verdict were written
to `internal/cycle25-work/blind-r2.md` before reading any other seat's
cycle-25 output: **0.86 / SHIP**. This review confirms it after running
the tests.

Tests run by this seat (unittest; pytest is not installed on this VM):
`tests.test_trust_ceremony_supersede` + `tests.test_trust_ceremony_consume`
— **99 tests, OK** (~100 s).

## Verdict against seat-gpt's five criteria (CROSS-CHECK-18)

- **(i) Independent authorisation event, fully bound — PASS.** The mode
  issues only against a `SignedSupersessionApproval` under a dedicated
  approver key; `approval_binding_mismatches` binds the abandoned pair,
  replacement ids/ceremony/reason/operator, the exact movement on both
  sides (superseding old pin → candidate, abandoned old → new), and the
  failed attempt (attempted id, pinned refusal code, head id + seq +
  entry_hash).
- **(ii) Verified BEFORE issuance — PASS (see Order probe).**
- **(iii) Refusal on auto-request alone — PASS.** No approval field →
  strict body key set refuses (`malformed_request`); null/malformed
  approval → `malformed_request` at parse; forged/wrong-key approval →
  `ceremony_supersede_approval_invalid`. All before any journal opens.
  Client-side, `ceremony_supersede(operator_id, envelope_dict,
  approval_dict)` makes the approval a required parameter with no
  default — there is no approval-free call shape.
- **(iv) No self-escalation — PASS on the verifier path.** Three layers
  hold: `supersede_head` returns None for `burned_unadopted`; the
  approval projection (`_project_replacement`) refuses a
  `burned_unadopted` replacement as un-mintable/un-verifiable; the
  approval binds the envelope's reason, so a primary approval cannot
  be re-bound to a recovery envelope. The supersede test presenting a
  validly signed approval for a recovery envelope still refuses
  `ceremony_supersede_unproven`, and it passes. (In-process direct
  ledger composition is a separate, lesser surface — finding F1.)
- **(v) Restoration via the new route — PASS within verifier scope.**
  The passing supersede suite exercises refusal → genuine tool-signed
  approval → `ceremony_supersede` decision → consume, including the
  client route landing the consume. Adopter-side restoration is seat
  C's scope.

## Specific probes

### Order in `_mode_ceremony_supersede` — correct
Step (0) approver-config gate → (1) operator/seed config gates → (2)
strict body keys → (3) operator-id shape → (4) operator membership →
(5) envelope verification → **(5b) approval parse + verification** →
(6) first journal reads. Approval authenticity is therefore established
before ANY journal is opened and long before the only journaling step,
(9) `append_decision`. Binding checks at (8b) are derived from the
verifier's OWN journals: `head_entry = CeremonyConsumptionLedger
.supersede_head(consumption_entries, signed)` over the verifier's own
consumption entries, and the helper receives `head_entry["seq"]` /
`head_entry["entry_hash"]` from that entry — the request names no
abandoned-movement or head field at all (the body key set forbids it).
No request-supplied value participates in the binding derivation.

### Refusal-code discipline — deviation ACCEPTABLE
Seat B deviated from a single collapsed code: authenticity failures use
dedicated codes (`ceremony_supersede_approval_unconfigured` at step 0,
`_invalid`/`_expired` at step 5b), binding/single-use failures fold into
`ceremony_supersede_unproven` at step 8/8b. I judge this sound, for one
decisive reason: **every dedicated code is emitted before any journal
read**, so none of them can certify or leak journal state — they depend
only on configuration and on the presented artefact itself. The
invalid/expired split mirrors the long-standing envelope carve-out
(temporal-only reasons → expired) and reveals only a fact about the
caller's own artefact. Once journal state is in play (steps 8/8b),
shape failure, prior decision, binding mismatch and spent approval are
indistinguishable on the wire — no shape oracle. No per-reason output
anywhere, stderr included. One lesser ordering observation (not a
finding against the deviation): steps (6)/(7) return the pre-existing
distinct codes `ceremony_already_consumed` / `ceremony_not_issued`
after 5b but before 8b, so a presenter holding an authentic approval
whose *binding* is wrong can still learn those two envelope facts
before reaching `unproven`. Both facts are independently learnable via
the consume mode, and neither reveals anything about the approval's
binding or spent status; acceptable, recorded for completeness.

### Single-use — actually impossible on the verifier path
Triple enforcement, each layer checked in code: (a) mode step 8b
pre-check via `find_by_approval_id`; (b) `append_decision` re-checks
`approval_id` against freshly reloaded entries **inside** its bounded
retry loop, on every attempt; (c) `_load` refuses a journal containing
a duplicate non-empty `approval_id`. Race probe: the verifier is
one-process-per-request, so two concurrent supersede processes can
both pass the (stale) step-8b pre-check — but they cannot both commit.
Each `append_decision` attempt reloads, re-checks, then `_append` →
`_save`, which takes the directory flock and re-validates freshness
under it; the loser gets `CorruptLedgerError`, the loop retries,
reloads, now sees the winner's `approval_id`, and raises `LedgerError`
(surfaced by the mode as `ledger_failed`). Exactly one decision lands.
Replay against a *different* envelope is additionally impossible by
binding (the approval names one authorisation id and one candidate).
The mode pre-check is a fast path; the append recheck is the authority,
and it is correctly placed.

### Production gate — sound
`_load_config`: present-but-not-hex64 approver key refuses startup in
BOTH modes; production with the ceremony seed configured requires the
key (and production independently requires the ceremony seed earlier
in the same function, so the `and ceremony_seed_raw` condition never
weakens the requirement in practice); approver public key equal to the
ceremony public key refuses startup once both keys are loaded, with a
detail naming neither value. Research + absent loads `None` and the
mode refuses per-request at step (0) — no fallback path exists. One
defence-in-depth gap, minor: **F3** below.

### Legacy ledger entries — all-empty-or-all-present rule is airtight
Two independent layers. Key-set layer: `_allowed_entry_key_sets`
returns exactly the current set and the legacy set (current minus the
three approval keys); the base `_load` rejects any entry whose
frozenset is in neither — so an entry carrying only one or two of the
three approval keys is corrupt before value checks run. Value layer
(in both `_load` and `append_decision`): the three fields must be all
`""` or all non-empty strings, and a non-empty `approval_id` requires
hex64 `approval_id` and `approval_payload_hash`; legacy entries read
via `.get(..., "")` land in the all-empty branch and skip duplicate
tracking. Pre-cycle-25 journals load; partial-approval journals do
not. Nit (not a finding): `approver_key_id` form is checked only as a
non-empty string — no `pub-…` format or equality-with-configured-key
check at load. Entries are written only by the verifier from a verified
approval (whose `key_id` already matched the pin at step 5b) or by
direct appends, so this is record hygiene, not a bypass.

## Findings

- **F1 (minor, non-blocking; COORDINATOR FLAG — confirmed absent):**
  The CROSS-CHECK-18 Q4 precaution was not implemented in
  `trust/ledger.py`. Neither `CeremonyConsumptionLedger` nor
  `CeremonySupersessionLedger` carries any marker documenting or
  naming its direct-ledger APIs as internal/test-only: class
  docstrings, `append_consumption` and `append_decision` are all
  silent on it (grep for internal/test-only naming across
  `trust/ledger.py` finds nothing). This matters concretely, not
  just cosmetically: `append_decision` defaults the three approval
  fields to `""`, and `CeremonyConsumptionLedger.check_head`'s
  decision binding never inspects the approval fields — so an
  in-process caller with verifier-home access can mint an
  approval-free decision that consume will honour. That composition
  sits inside the prototype's stated honesty boundary (verifier-home
  write access is already game over, and the supersession journal
  itself claims no forgery resistance), so it is **not** a verifier
  mode bypass and does not break criteria (i)–(v) — but Q4's
  precaution existed precisely to make this composition hard to
  invoke *accidentally*, and cycle 25 was supposed to add it.
  Follow-up: add the internal/test-only marker to both ledgers'
  docstrings and append methods (or rename the direct appends),
  and consider a consume-side refusal of empty-approval decisions
  if a post-cycle-25 journal marker ever makes legacy
  distinguishable from direct appends.
- **F3 (minor, non-blocking):** The verifier docstring claims the
  approver key is "distinct from the snapshot signing key and from
  the verifier's ceremony seed", but startup enforces only the
  ceremony equality. The verifier holds the HMAC signing key bytes
  and already derives an Ed25519 public key from them for the
  cycle-21 overlap checks; extending that one comparison to the
  approver public key would close the accidental-reuse case
  (approver seed provisioned equal to the HMAC key) that the
  wording currently over-claims. Provisioning is independent random
  draws and the approver seed never enters this process, so this is
  a wording-vs-enforcement gap, not an exploitable path.

## Client (`trust/client.py`)
Required `approval_dict`, pre-send echo check on replacement
authorisation id + candidate seq/hash (full binding correctly left to
the verifier), exact receipt key set and echo validation, and
docstring code classification matching the mode's actual codes —
including the statement that binding/single-use failures collapse to
`ceremony_supersede_unproven` while authenticity failures refuse
earlier under the dedicated codes. No issues found.

## Final verdict

**Verdict: SHIP (score 0.86)** — the verifier side satisfies all five
of seat-gpt's CROSS-CHECK-18 criteria in code and in passing tests;
F1 (missing Q4 internal/test-only marker on the direct-ledger APIs)
and F3 (approver-vs-snapshot-key equality unenforced) are recorded
as minor, non-blocking follow-ups.
