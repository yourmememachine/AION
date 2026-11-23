# Build record — Cycle 21: Ed25519 differential validation + protected monotonic consumption head

Date: 2026-11-23. Closes the last two external gates from
CROSS-CHECK-14 on the ceremony line: item (1) Ed25519
validation (seat-gpt SHIP-with-qualification 0.91,
seat-gemini FIX blocking) and item (3) consumption
integrity (seat-gpt FIX 0.96 blocking cycle 20,
seat-gemini FIX binding on cycles 14–16). Cycle 19 Part A
+ Item A are shipped and untouched; eval/ is untouched;
cycles 14–16 were NOT re-reviewed in this cycle.

## Headline claim — with its qualifiers, in substance

Item (3) is discharged only as an integrated-system
property under production wiring (authorise via
VerifierClient; re-anchor with the verifier-backed
consumer; adopt the returned pin atomically), against an
intact verifier home. The consumption journal is not
externally anchored — a verifier-home rollback can lower
the enforced head for never-consumed envelopes — until
ceremony-journal-anchoring lands. Research mode is not
rollback-protected and is outside this claim.
Burned-but-unmoved recovery still requires the lost_pin
label (open follow-up burned-but-unmoved-recovery-reason).
Cycle 21 is PROVISIONAL pending external acceptance of
this scoping.

Liveness figures, in numeric form: the envelope TTL is
hard-capped at 900 s, and every ceremony now needs TWO
verifier-availability windows inside that life — one to
authorise, one to consume. A failed or lost consume burns
the issuance pair; recovery needs a new ceremony_id plus
a new evidence artefact; the client never retries a
consume automatically.

## Store-location decision (summary)

Decided by the war room under the standing rule (Dilip is
informed, not asked): the consumption head is
VERIFIER-OWNED — a new hash-chained journal
`ceremony-consumptions.json` (`CeremonyConsumptionLedger`)
under the existing `AION_VERIFIER_HOME`, written only by
a new verifier mode `ceremony_consume`. Caller-supplied
`ceremony_history` stops being authoritative (required
audit/consistency input; can only refuse, never grant).
No new env var; wrapper allowlist unchanged at 17.
Full reasoning, alternatives and residuals:
internal/DECISION-CONSUMPTION-HEAD.md.

## Workstream A — Ed25519 differential validation + seed hygiene

- tests/test_signing_ed25519_differential.py (new, 531
  lines): RFC 8032 §7.1 known-answer vectors as literals
  incl. a 1024-byte long-message vector; a Wycheproof-style
  adversarial table where every row pins a PER-CASE
  expectation PAIR (in-house, openssl) — non-canonical R
  and A (y = q, q+1, 2^255−1; sign-bit and x = −0
  spellings), S ∈ {L−1, L, L+1, 2^256−1} plus S+L
  malleation, all 8 small-order encodings as A and as R
  (incl. the rows where openssl ACCEPTS and we must reject,
  pinned as (False, True)), mixed-torsion A+T / R+T,
  cross-vector signature swaps. The in-house verifier must
  return False for every adversarial row, non-negotiably.
- Bit-flip sweeps against the production verify: every
  single-bit flip of the 64 signature bytes, the 32
  public-key bytes, and the message must verify False.
- Openssl differential (openssl 3.0.13 on this VM; skips
  cleanly when absent): openssl's deterministic signature
  must be BYTE-IDENTICAL to ours and ours must pass
  openssl verification; seeded cross-implementation
  agreement both directions on honest signatures.
- Independent re-probe: rev-r2 (non-builder) re-probed the
  full 51-row adversarial table with its own openssl driver
  — zero mismatches against the pinned pairs (recorded in
  internal/cycle21-work/review-r2.md; a pointer to it is
  the one letter-caveat rev-r6 noted, see REVIEW-CYCLE-21).
- Seed hygiene (signing/gate_decision.py,
  signing/ceremony_authorisation.py): ONE shared
  owner-only permission predicate for both key loaders —
  accept iff no group/world bits (`mode & 0o077 == 0`),
  no setuid/setgid/sticky bits, and the owner-read bit is
  set (in practice {0400, 0600}); the "exactly 0600"
  wording is retired. The ceremony seed loader gains fd
  discipline (O_NOFOLLOW|O_NONBLOCK open, fstat S_ISREG +
  mode, bounded read from the fd) and an owner-uid check
  (when euid != 0, st_uid must equal euid). The signing-key
  loader takes the shared predicate only; its fd rework is
  the named follow-up `signing-key-loader-fd-hardening`.
- Derivation-overlap refusals in the verifier config pair
  block (closed set, both secrets present): seed == key;
  seed == sha256(key); key == sha256(seed); key ==
  ceremony public key; seed == sha256(ceremony public
  key); key == sha256(ceremony public key); seed ==
  sha256(own public key); key ∈ REFUSED_TEST_SEEDS; plus
  (ratified deviation, rev-r1 LOW-1) relation (7) read both
  ways — the HMAC key treated as an Ed25519 seed deriving
  the ceremony public key also refuses. Wording carried in
  code: these relations catch accidents and known
  derivations, not arbitrary KDF overlap; no stronger
  claim is made.
- tests/test_signing_ceremony_seed_hygiene.py (new).

## Workstream B — the protected monotonic consumption head

- trust/ledger.py: `CeremonyConsumptionLedger`
  (HashChainJournal) with `append_consumption` — the
  commit point — which re-checks single-use AND the head
  rules against freshly reloaded entries inside the append
  (bounded reload-retry, the cycle-20 issuance-race
  lesson); typed refusals `AlreadyConsumedError` /
  `HeadRegressionError`. `head_target()` is the only
  target read (the base `head()` chain-hash trap found in
  review is closed and pinned by a polymorphic contract
  test across all ledger classes). SigningLedger gains
  `append_ceremony_consumption`: kind "consume", format
  "ceremony-consumption", existing EXTRA_KEYS — the
  anchored mirror, written ONLY after a successful
  consumption append; mirror failure after commit →
  `ledger_failed`, envelope stays burned.
- Head rules (DESIGN-FINAL R3): single-use by
  authorisation_id regardless of caller history; issuance
  presence with field match, else `ceremony_not_issued`;
  candidate behind the head → `ceremony_head_regression`;
  candidate == head target under a fresh envelope →
  `ceremony_already_consumed` (re-mint laundering closed);
  fork at the head → regression; old-pin not-behind rule
  (o_seq < H_seq refuses; o_seq == H_seq requires hash
  equality; o_seq > H_seq passes — advance_pin movements
  the verifier never saw are legitimate); initial_anchor
  against a non-empty consumption journal → regression.
- trust/verifier_main.py: new mode `ceremony_consume`
  (registered also in trust/protocol.py MODES). Body is
  exactly `{"signed_authorisation"}`. Validation order:
  config gate (ceremony seed only — allowlist and evidence
  config are issuance facts, NOT consumption gates) →
  strict key set → envelope parse → verifier-side Ed25519
  verification + expiry under the verifier's OWN derived
  public key → already-consumed → issuance-presence →
  head rules → commit. ONE refusal code
  (`ceremony_authorisation_invalid`) for all non-temporal
  verification failures — no forger oracle, on stdout or
  stderr. Response carries authorisation_id / ceremony_id
  echoes, the consumed head, and consumption_seq.
- trust/client.py: `VerifierClient.ceremony_consume`
  (validates the response's exact key set and echoes) and
  `VerifierClient.ceremony_consumer()` — the adapter
  callable translating verifier errors to SigningError.
- signing/pin_ceremony.py: `reanchor_pin` gains the
  REQUIRED keyword `consume_authorisation` (one-argument
  callable). Omission is a TypeError; explicit None or a
  non-callable refuses BEFORE envelope verification. It is
  invoked EXACTLY ONCE, after all local checks and before
  the ceremony record is constructed; zero invocations on
  any local refusal (spy/counting-consumer tests); a
  consumer exception — including one raised after the
  verifier committed (lost response) — propagates as a
  refusal: nothing returned, no record exists.
  OFFLINE TRADE-OFF, stated in the docstring: reanchor_pin
  is no longer an offline function — a successful ceremony
  requires a live verifier round-trip inside the
  envelope's TTL and fails closed when the verifier is
  unreachable; the flag-day breakage of existing direct
  callers is intended.
- Crash-consistency contract (verbatim in the mode and
  pin_ceremony docstrings): "Consumption is committed at
  the verifier — a fsync'd consumption-journal append —
  before reanchor_pin returns anything. There is no
  execution path in the integrated system in which a pin
  movement succeeds without its consumption record durably
  committed first. A crash after the commit but before
  adoption leaves the authorisation burned and the pin
  unmoved; a lost or ambiguous response is treated as
  burned; the client never retries a consume automatically.
  Recovery is a new ceremony (new ceremony_id, new
  evidence), never an un-consume."
- The cycle-20 regression tests T7/T8 (stale-history
  replay regressing the pin) FLIP to refusals; at least
  one wires a real ledger-backed consumer, and the new
  subprocess suite (tests/test_trust_ceremony_consumption.py)
  wires the real verifier: replay across fresh clients,
  never-issued, expired, verifier-down fail-closed, mirror
  scoping. Test-helper discipline (R12): the default test
  consumer is a real ledger-backed consumer over a
  fixture-scoped temp dir, never an always-succeed fake.
- Claim wording (mandatory form, in docstrings and this
  record): single-use consumption and pin non-regression
  are properties of the INTEGRATED SYSTEM under its
  production wiring — authorise via VerifierClient,
  re-anchor with the verifier-backed consumer, adopt the
  returned pin atomically — not properties of
  reanchor_pin for an arbitrary caller-supplied callable.
  A no-op callable gets no protection, exactly as a caller
  supplying its own signing key or a wrong public-key pin
  gets none.

## Fix round (war-room reconciliation)

Blind: rev-r1 FIX 0.87, rev-r2 SHIP 0.93, rev-r3 FIX
0.78, rev-r4 SHIP 0.90, rev-r5 FIX 0.80 (wording only),
rev-r6 dissent FIX 0.58. Fixed in code: the stderr oracle
(rev-r3 HIGH-1 — per-reason detail leaked on stderr at the
consume mode; now byte-identical stdout AND stderr across
verification-failure classes, regression-tested);
head() → head_target() rename + polymorphic contract test
(rev-r3 MEDIUM-1 / rev-r6 F2); crash/race test
traceability — forced interleave, post-mirror kill point,
missing old_pin == head mode test (rev-r1/r3 MEDIUM-2);
deploy README (rev-r1 MEDIUM-1 / rev-r5 F2); docstring
narrowing + numeric liveness figures (rev-r5 F5 / rev-r6
F7); setuid/sticky predicate tightening (rev-r2 LOW-1);
openssl capability probe (rev-r2 LOW-4); message-flip
extension (rev-r2 LOW-3); stale-text cleanups (rev-r5 F1/
F3/F4, rev-r6 F7); spy coverage (rev-r4 MEDIUM-1);
T8-prime message precision (rev-r4 LOW-2).
Re-reviews: rev-r1 0.94 SHIP, rev-r2 0.95 SHIP, rev-r3
0.92 SHIP, rev-r4 0.92 SHIP, rev-r5 0.94 SHIP, rev-r6
0.72 FIX narrowed (dissent preserved in
REVIEW-CYCLE-21.md — a claim gate, not a code rejection).

## Tests

Full suite, coordinator-verified at this commit:
**1472 tests OK (skipped=28)**, up from 1406 at cycle 20
(+66 net). New suites: Ed25519 differential, ceremony
seed hygiene, ceremony_consume mode (incl. K1–K6 crash
kill points and the two-process concurrent double-consume
race with exactly one winner), ceremony consumption
subprocess integration; pin ceremony suite rewired per
R12 with T1b, T7′/T8′ flips, T-Cc commit-then-raise.

## Open items (named, not buried)

1. **External reconciliation** — seat-gpt / seat-gemini
   have not seen cycle 21; the cycle is PROVISIONAL until
   they accept the item-(3) scoping (rev-r6 flip
   condition 1). Brief: CROSS-CHECK-BRIEF-CYCLE-21.md.
2. **F1 — no production caller of reanchor_pin exists.**
   The integrated path (library + VerifierClient +
   verifier mode) is built and exercised end-to-end in
   tests; no loop/storage adopter calls reanchor_pin in
   production yet, and the single-use / non-regression
   guarantee binds the first adopter that wires as
   specified. Put to the external seats explicitly.
3. **F4 — burned-but-unmoved recovery** still requires
   recording reason=lost_pin for a pin that is not lost.
   Named follow-up `burned-but-unmoved-recovery-reason`;
   put to the external seats as an open item.
4. **ceremony-journal-anchoring** — extended by this
   cycle's decision to cover BOTH journals (issuance +
   consumption) jointly.
5. **signing-key-loader-fd-hardening** — the gate signing
   loader's fd rework (its permission predicate already
   widened this cycle).
6. **Pin-store compare-and-swap** (future loop/storage):
   full closure of the fresh-envelope regression class —
   the head is a ceremony head, not a pin head;
   advance_pin movements never pass through the verifier.
7. **Deployment note:** production verifiers must set
   AION_CEREMONY_OPERATORS + AION_CEREMONY_EVIDENCE_DIR +
   AION_CEREMONY_SIGNING_SEED_PATH or refuse to start;
   the `aion-verifier` deployment on this VM is currently
   not provisioned (OS resets wipe it), so the
   deployment-gated tests skip by design (suite skipped=28 total).
8. Cycles 14–16 remain HELD; their re-review is the next
   step after this cycle reconciles externally.
