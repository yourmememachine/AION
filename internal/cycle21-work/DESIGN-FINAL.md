# DESIGN-FINAL — Cycle 21 (coordinator rulings)

Three coder seats designed together (design-a/b/c.md), cross-
critiqued (critique-a/b/c.md), and the divergences reconciled
below. These rulings are the build contract. Where a ruling
adopts one seat's position over another's, the losing argument
is on record in the critiques; do not relitigate during the
build — flag genuine evidence against a ruling to the
coordinator instead.

Procedural note: design-c.md on disk was truncated mid-§2 in
its first delivery (flagged independently by seats A and B,
self-flagged by C). Seat C re-saves the full text as the first
step of its build task; §§3–8 positions are as restated in
critique-c.md and C's delivery summary, which the other seats
reviewed.

## R1 — Store location (THE decision; see DECISION-CONSUMPTION-HEAD.md)

Verifier-owned consumption state (route-4), unanimous across
all three designs and unshaken in critique: a new
`CeremonyConsumptionLedger` (HashChainJournal,
`ceremony-consumptions.json`) under the existing
`AION_VERIFIER_HOME`, written only by a new verifier mode
`ceremony_consume`. Zero new env vars; the deploy wrapper
allowlist stays at 17 names. The decision, alternatives and
reasoning are recorded in
internal/DECISION-CONSUMPTION-HEAD.md per the standing rule
(the war room decides; the owner is informed, not asked).

## R2 — Consume protocol

Body is exactly `{"signed_authorisation"}` (B; conceded by A
and C — matches the ceremony_authorise wire precedent in
trust/client.py). The mode is registered in BOTH
trust/verifier_main.py `_MODES` and trust/protocol.py `MODES`
(seat A's catch: design-a's own file list initially omitted
the protocol registration).

Validation order mirrors ceremony_authorise's discipline:
(1) config gate — ceremony seed configured (the mode verifies
envelopes; the operator allowlist and evidence config are
issuance facts and are NOT consumption gates); (2) strict key
set; (3) envelope parse; (4) verifier-side Ed25519 signature
verification + expiry under the verifier's OWN derived public
key; (5) already-consumed check; (6) issuance-presence check;
(7) head rules; (8) commit.

Refusal codes (B's table, adopted):
- `malformed_request` (exit 2) — bad key set / unparseable body.
- `ceremony_authorisation_invalid` (exit 2) — ONE code for all
  non-temporal verification failures (signature, binding,
  structural): no forger oracle.
- `ceremony_authorisation_expired` (exit 3).
- `ceremony_already_consumed` (exit 3) — authorisation_id in
  the consumption journal; checked BEFORE the issuance check.
  Also the code for a candidate target already consumed under
  a different envelope (the movement is consumed).
- `ceremony_not_issued` (exit 3) — authorisation_id absent
  from the issuance journal, or present with mismatching
  payload/ceremony/evidence fields.
- `ceremony_head_regression` (exit 3) — any head-rule refusal
  (R3), including initial_anchor against a non-empty
  consumption journal.
- `ledger_failed` (exit 3) — either journal unreadable/
  corrupt, or the mirror append failed after the commit.
- `ceremony_seed_unconfigured` (exit 3) — research mode with
  no seed configured.

Response result: exact key set carrying the authorisation_id
and ceremony_id echoes, the consumed head
(new_cycle_seq / new_payload_hash — by construction the sent
envelope's candidate), and consumption_seq (the consumption
journal's entry seq, ≥ 1). The client asserts the echoes equal
what it sent (C's strengthening).

Explicitly NOT re-checked at consumption: operator allowlist
membership (an issuance fact), evidence resolution (retention
is not a consumption input — cycle-20 wording stands).

## R3 — Head rules (merged final form)

Let H = the consumption journal's head target: the
(new_cycle_seq, new_payload_hash) of its latest entry, or
absent when the journal is empty. For an envelope with
candidate target T = (t_seq, t_hash) and old pin O =
(o_seq, o_hash) or None:

- M1 single-use: authorisation_id already consumed →
  `ceremony_already_consumed`, regardless of any caller
  history. (Flips T7.)
- Issuance precondition: not in the issuance journal (or
  field mismatch) → `ceremony_not_issued`.
- Candidate rule: t_seq < H_seq → `ceremony_head_regression`;
  t_seq == H_seq and t_hash == H_hash →
  `ceremony_already_consumed` (same target, fresh envelope —
  the re-mint laundering route is closed); t_seq == H_seq and
  t_hash != H_hash → `ceremony_head_regression` (fork at the
  head); t_seq > H_seq → passes this rule.
- Old-pin rule (the merged not-behind rule; B's M4 conceded
  to it in critique-b, A's R3 conceded to its precise form in
  critique-a): if O is not None — o_seq < H_seq →
  `ceremony_head_regression`; o_seq == H_seq requires
  o_hash == H_hash, else `ceremony_head_regression`;
  o_seq > H_seq → passes (advance_pin movements the verifier
  never saw are legitimate). O is None (no-pin reasons) → no
  old-pin check; the candidate rule applies in full.
- initial_anchor against a non-empty consumption journal →
  `ceremony_head_regression` (a first-ever anchor claim after
  recorded consumptions is a contradiction).

Recovery story under these rules, stated for the records:
after a burned-but-unmoved crash (consumption committed, pin
not adopted), the consumed target is permanently spent. The
operator's recovery is a no-pin lost_pin ceremony whose
candidate is AHEAD of the head (the state has moved on; the
skipped target is never re-anchorable). This narrowing is
accepted and recorded — it is the price of a head that cannot
be restaged.

The head is a CEREMONY head, not a pin head: it sees only
consumptions. The residual class — a fresh envelope whose
candidate is ahead of the ceremony head but behind a live pin
silently advanced by advance_pin — is narrowed by the old-pin
rule (such an envelope's O would have to be at or ahead of
the head while the caller's real pin state contradicts it at
binding time in reanchor_pin), and its full closure remains
the future loop/storage pin-store CAS, as all three designs
state. Do not claim otherwise anywhere.

## R4 — Commit point, mirror, ordering

The consumption-journal append is THE commit point.
`CeremonyConsumptionLedger.append_consumption` re-checks
single-use AND the head rules against freshly reloaded
entries inside the append (bounded reload-retry, the cycle-20
issuance-race lesson); the concurrent loser surfaces as
`ceremony_already_consumed`, not ledger_failed.

Order after the checks: (1) consumption-journal append
(commit); (2) signing-ledger mirror via a new
`SigningLedger.append_ceremony_consumption` — kind
"consume", format "ceremony-consumption", EXISTING
EXTRA_KEYS, no format migration (precedent:
try_consume_eval_records' eval-consumption entries);
(3) `_update_anchor(config)`. Mirror failure after the commit
→ `ledger_failed`, the envelope stays burned, no success
response. The mirror is invoked ONLY on a successful
consumption append (mirror-before-commit would invert the
commit and is a review refusal).

TRAP (seat A, adopted): the issuance mirror already writes
signing-ledger entries with decision_id = authorisation_id
under kind "sign". Any cross-check or audit query for
consumptions MUST scope to kind="consume" +
format="ceremony-consumption", or every consume self-refuses.

The shared directory flock serialises the three steps across
verifier-home journals but is NOT cross-ledger atomicity;
the benign-interleaving statement goes in the mode docstring
(B's hazard note).

## R5 — Ceremony-side integration

`reanchor_pin` gains a REQUIRED keyword `consume_authorisation`:
a ONE-argument callable taking the SignedCeremonyAuthorisation,
returning None on success and raising SigningError on any
refusal (C's one-arg form; A's two-arg form rejected — the
new pin is a dead caller-computed duplicate at that point).

- No default: omission is a TypeError at the call site (the
  cycle-20 T1 discipline). Explicit None or a non-callable
  refuses EARLY — before envelope verification — mirroring
  the ceremony_history=None ordering (new test T1b).
- Invoked EXACTLY ONCE, after ALL local checks (type gates,
  history presence + content, envelope verification, exact
  binding, relation gates, strict-reason recomputation, bare
  attestation verification) and BEFORE the ceremony record is
  constructed. Zero invocations on any local refusal (pinned
  by spy/counting-consumer tests). A consumer exception —
  including one raised after the verifier committed (lost
  response) — propagates as a refusal: nothing is returned,
  no record exists.
- signing/ imports nothing from trust/. The transport lives
  in trust/client.py: `VerifierClient.ceremony_consume(envelope)`
  (validates the response's exact key set and echoes) and
  `VerifierClient.ceremony_consumer()` returning the adapter
  callable (translates Verifier* errors to SigningError).
- OFFLINE TRADE-OFF, verbatim for the pin_ceremony docstring
  and the build record (C's words): reanchor_pin is no longer
  an offline function — a successful ceremony requires a live
  verifier round-trip inside the envelope's TTL and fails
  closed when the verifier is unreachable; every existing
  direct caller breaks with TypeError until it supplies the
  keyword, and that flag-day breakage is intended.

CLAIM WORDING (B/C merged, mandatory in docstrings, the
build record and the external brief): single-use consumption
and pin non-regression are properties of the INTEGRATED
SYSTEM under its production wiring — authorise via
VerifierClient, re-anchor with the verifier-backed consumer,
adopt the returned pin atomically — not properties of
reanchor_pin for an arbitrary caller-supplied callable. A
no-op callable gets no protection, exactly as a caller
supplying its own signing key or a wrong public-key pin gets
none; the callable is not materially different from the
inputs reanchor_pin already trusts.

## R6 — ceremony_history after the head

Unchanged in code and requiredness: still a required keyword,
explicit None still refuses before envelope verification,
`_check_ceremony_history` and the per-reason admissibility
table are untouched. Its AUTHORITY is removed in wording
only: docstrings stop describing it as replay protection; it
is an audit/consistency input that can only refuse, never
grant, and the verifier's consumption head is authoritative
on any discrepancy. The COMPLETE-HISTORY caller precondition
is demoted from a security precondition to an audit
obligation; FRESH-PIN and ATOMIC-ADOPTION remain caller
obligations with their (now smaller) failure modes stated.

## R7 — Crash-consistency contract

Exact words for the mode docstring, the pin_ceremony
docstring and the build record (A's draft as amended):

"Consumption is committed at the verifier — a fsync'd
consumption-journal append — before reanchor_pin returns
anything. There is no execution path in the integrated
system in which a pin movement succeeds without its
consumption record durably committed first. A crash after
the commit but before adoption leaves the authorisation
burned and the pin unmoved; a lost or ambiguous response is
treated as burned; the client never retries a consume
automatically. Recovery is a new ceremony (new ceremony_id,
new evidence), never an un-consume."

Tests: B's verifier-side kill points K1–K6 (wrapper-module
os._exit patches — no env fault hooks; torn/corrupt journal
fails closed; two-process barrier race for concurrent
double-consume with exactly one winner; post-commit mirror
failure = ledger_failed + burned) and C's T-Cc (a fake
consumer that commits to a real ledger then raises:
reanchor_pin returns nothing, a second attempt refuses
already-consumed, exactly one consumption entry exists).

## R8 — Workstream A: differential suite

New file tests/test_signing_ed25519_differential.py (the
cycle-20 test file is not extended; fixtures re-declared).

- RFC 8032 §7.1 known-answer vectors as literals, including
  a long-message (1024-byte) vector. GUARD: a KAT literal
  that disagrees with BOTH the in-house implementation and
  openssl is a build blocker to report to the coordinator,
  never a reason to edit the implementation to fit it.
- Wycheproof-style adversarial table. Every row pins a
  PER-CASE expectation PAIR (ours, openssl): ours must be
  False for every adversarial row (non-negotiable); the
  openssl expectation is probed at build time and pinned
  with the probe recorded — an un-pinned "divergence allowed"
  bucket is vacuous and can ratify a bug (C's §6 finding,
  adopted). Rows: non-canonical R and A (y = q, q+1,
  2^255−1; sign-bit variants; the x = −0 spellings); S ∈
  {L−1, L, L+1, 2^256−1} and S+L malleation (C's probe:
  openssl AGREE-REJECTs the malleation); all 8 small-order
  encodings as A and as R (C's probe: openssl ACCEPTS the
  identity A and the non-canonical y=1+q spelling of A —
  those rows pin (False, True) and are exactly why the pairs
  are pinned); mixed torsion A+T and R+T (order 2/4/8
  constructions); identity/zero constructions; cross-vector
  signature swaps.
- Bit-flip sweeps against OUR verify only: every single-bit
  flip of the 64 signature bytes (512), the 32 public-key
  bytes (256) and the message (B's extension) must verify
  False. Runtime re-measured at build and recorded; the
  subsample fallback triggers only above 60 s (cycle-20
  timings price the full sweep at ≈5–7 s).
- Openssl differential (openssl 3.0.13 present on this VM;
  skip cleanly via shutil.which + a setUpClass probe when
  absent, per the repo's skipUnless pattern): keys wrapped
  with the fixed DER prefixes — PKCS#8
  302e020100300506032b657004220420 + seed, SPKI
  302a300506032b6570032100 + public key. Sign direction:
  openssl's deterministic signature must be BYTE-IDENTICAL
  to ours, and ours must pass openssl verification. Verify
  direction: the pinned pairs above. Empty-message case:
  openssl pkeyutl cannot process 0-byte messages (C's probe)
  — openssl directions use messages of length ≥ 1; the
  empty message is covered by KAT + the affine oracle.
- Seeded cross-implementation agreement: random keys/messages
  signed by each side, verified by the other (valid
  signatures only — agreement is asserted on acceptance of
  honest signatures both ways).

## R9 — Seed hygiene

- Permission predicate, SHARED by both loaders
  (load_ceremony_seed and load_signing_key) via one helper:
  accept iff the fstat mode has NO group/world bits
  (mode & 0o077 == 0) AND the owner-read bit is set — in
  practice {0400, 0600}. The "exactly 0600" wording is
  retired in both loaders and their tests. (B conceded on
  evidence: nothing in tests/deploy depends on refusing
  0400; C verified no gate-loader test pins exactly-0600.)
- fd discipline (open with O_NOFOLLOW|O_NONBLOCK, fstat for
  S_ISREG + mode, bounded read from the fd): the CEREMONY
  SEED loader this cycle. The signing-key loader's fd rework
  is the named follow-up `signing-key-loader-fd-hardening`,
  recorded in the gate_decision docstring — while its
  permission PREDICATE widens this cycle with the shared
  helper (B's split ruling). The two changes land as separate
  bisectable commits within the cycle.
- Owner-uid check: seed loader only — when euid != 0,
  require st_uid == euid; as root the check is vacuous and
  skipped (B's carve-out). NOT applied to the gate loader
  (deploy health_check.py is a second, differently-identified
  reader of the gate key — C's catch).
- Derivation overlap, checked in _load_config's pair block
  (the one place both secrets exist), closed set:
  (1) seed == key (existing byte-equality);
  (2) seed == sha256(key); (3) key == sha256(seed);
  (4) key == ceremony public key (public material as the
  HMAC secret — B's catch, the most dangerous relation);
  (5) seed == sha256(ceremony public key);
  (6) key == sha256(ceremony public key);
  (7) seed == sha256(own public key) — a publicly derivable
  seed; (8) key ∈ REFUSED_TEST_SEEDS (A's R5 — live exactly
  for the RFC vector seeds). A's R4 (seed ∈
  REFUSED_TEST_KEYS) is DEAD — that set is a strict subset
  of REFUSED_TEST_SEEDS, already refused — and is not
  implemented. Existing independent refusals (seed ∈
  REFUSED_TEST_SEEDS, key ∈ REFUSED_TEST_KEYS) stand.
  Wording (A's residual, mandatory): these relations catch
  accidents and known derivations, not arbitrary KDF
  overlap; no stronger claim is made.

## R10 — Anchoring

The consumption journal is NOT externally anchored this
cycle (unanimous). Its docstring carries the precise
residual (B's wording): a rollback of the verifier home
cannot resurrect a consumed envelope whose consumption is
mirrored in the anchored signing ledger (production), but
can lower the enforced head for never-consumed envelopes.
The follow-up `ceremony-journal-anchoring` is extended to
cover BOTH journals (issuance + consumption) jointly.

## R11 — Build file ownership (disjoint)

- Seat A: signing/gate_decision.py (shared perm helper +
  predicate widening in load_signing_key + follow-up note),
  signing/ceremony_authorisation.py (seed-loader fd
  discipline + predicate + uid check),
  tests/test_signing_ed25519_differential.py (new),
  tests/test_signing_ceremony_seed_hygiene.py (new,
  loader-level tests). Commit 1 = gate_decision predicate;
  commit order within the cycle per R9 sequencing.
- Seat B: trust/ledger.py (CeremonyConsumptionLedger +
  SigningLedger.append_ceremony_consumption),
  trust/verifier_main.py (ceremony_consume mode + R9
  derivation-overlap pair block + _MODES),
  trust/protocol.py (MODES registration),
  tests/test_trust_ceremony_consume.py (new: mode suite,
  K1–K6 crash tests, startup overlap tests),
  deploy/verifier-identity/README.md (consumption mode +
  recovery note, if modes are documented there).
- Seat C: FIRST re-save internal/cycle21-work/design-c.md in
  full (repairing the truncation), then:
  signing/pin_ceremony.py (consume_authorisation integration
  + R5/R6 docstring wording), trust/client.py
  (ceremony_consume + ceremony_consumer),
  tests/test_signing_pin_ceremony.py (helper rewire per R12,
  T1b, T7′/T8′ flips, T-Cc, spy tests),
  tests/test_trust_ceremony_authorisation.py (E2E helper
  switch to the client-backed consumer),
  tests/test_trust_ceremony_consumption.py (new: subprocess
  integration — replay across fresh clients, never-issued,
  expired, verifier-down fail-closed, mirror scoping).

No other files change. eval/ is untouched. Part A / Item A
are untouched. Cycles 14–16 are not re-reviewed.

## R12 — Test-helper discipline

The test reanchor() helper's DEFAULT consumer is a real
CeremonyConsumptionLedger-backed consumer over a
FIXTURE-scoped temp dir (one ledger per test class/module
fixture, NOT per call — a per-call fresh dir would silently
re-pin the cycle-20 history-leg semantics, A's catch), never
an always-succeed fake. Tests that need continuity share one
consumer explicitly. Fakes are allowed only where the test's
subject is the fake itself (spy/counting consumers, T-Cc's
commit-then-raise consumer). At least one of T7′/T8′ wires a
real ledger-backed consumer (B's build requirement); the
subprocess suite wires the real verifier.

Seat C greps for every reanchor_pin caller in the tree at
build start and fixes all call sites; any caller outside its
owned files is reported to the coordinator before editing.
---

# ADDENDUM — War-room reconciliation (post-review rulings, coordinator)

Blind scores (locked, subject cycle-21-review): rev-r1 FIX 0.87, rev-r2 SHIP
0.93, rev-r3 FIX 0.78, rev-r4 SHIP 0.90, rev-r5 FIX 0.80 (wording only),
rev-r6 dissent FIX 0.58. Fix round dispatched; dispositions below are final
for this cycle unless a re-review overturns them.

**Fixed in code (fix round):** r3 HIGH-1 stderr oracle (B1); r3 MEDIUM-1 /
r6 F2 head() rename to head_target() + polymorphic contract test (B2, C6);
r1 MEDIUM-2 / r3 MEDIUM-2 crash/race test traceability + forced interleave +
post-mirror kill point + missing old_pin==head mode test (B3); r1 MEDIUM-1 /
r5 F2 deploy README (B4); r5 F5 + r6 F7 docstring narrowing + liveness
figures (B5, C3); r2 LOW-1 setuid/sticky predicate tightening (A1); r2 LOW-4
openssl capability probe (A2); r2 LOW-3 message-flip extension (A3); r5 F3
ceremony_authorisation.py stale text (A4); r5 F1 stale pin_ceremony
paragraph (C1); r5 F4 residual labelling (C2); r4 MEDIUM-1 spy coverage (C4);
r4 LOW-2 T8-prime message precision (C5).

**Ratified deviation (rev-r1 LOW-1):** seat B's second reading of R9
relation (7) — refusing when the HMAC key, treated as an Ed25519 seed,
derives the ceremony public key — is RATIFIED. It adds refusals only, is
disclosed in a code comment, and carries its own test. The R9 closed set is
now (1)-(7) with (7) read both ways.

**Recorded interpretations (no code):** (a) rev-r1 LOW-4 — the temporal
verify reasons (expired / signed_in_future) map to
ceremony_authorisation_expired; all other verify failures to
ceremony_authorisation_invalid. R2's "temporal" wording covers both.
(b) rev-r3 LOW — consumption retry exhaustion (8 attempts under continuing
contention) surfaces ledger_failed, matching the issuance bounded-retry
precedent; fail-closed either way. (c) rev-r2 note — openssl pairs were
probed by the BUILDER on this VM; rev-r2 (non-builder) independently
re-probed the full adversarial table with zero mismatches, which discharges
rev-r6 flip condition (6).

**Dissent dispositions (rev-r6, preserved verbatim in REVIEW-CYCLE-21.md):**
F1 (no production caller of reanchor_pin exists) — NOT closable by code
inside this cycle's scope; the claim is scoped instead: the integrated path
(library + VerifierClient + verifier mode) is built and exercised
end-to-end in tests; no loop/storage adopter calls reanchor_pin in
production yet, and the single-use/non-regression guarantee binds the first
adopter that wires as specified. Put to the external seats explicitly.
F4 (burned-but-unmoved recovery requires the lost_pin label) — named
follow-up `burned-but-unmoved-recovery-reason` (dedicated reason or a
journal-proven old-pin exception); the reason grammar is shared with the
issuance side and is not changed inside a fix round. Put to the external
seats in the brief as an open item. F3 — the qualifiers (production wiring /
intact verifier home / consumption journal unanchored) travel with every
item-(3) summary: brief headline + BUILD record (flip condition 4). F6 —
recorded: rev-r6 itself found no cycle-21 dependency on provisional
cycle-17/18 behaviour; the dependency runs the other way.
