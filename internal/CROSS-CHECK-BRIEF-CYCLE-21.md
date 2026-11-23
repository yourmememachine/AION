# Blind review brief — Cycle 21: Ed25519 differential validation + protected monotonic consumption head

For external seats seat-gpt / seat-gemini. No internal
verdicts or scores are included in this brief.

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
Cycle 21 is PROVISIONAL pending your acceptance of this
scoping.

Liveness figures, in numeric form: the envelope TTL is
hard-capped at 900 s, and every ceremony now needs TWO
verifier-availability windows inside that life — one to
authorise, one to consume. A failed or lost consume burns
the issuance pair; recovery needs a new ceremony_id plus
a new evidence artefact; the client never retries a
consume automatically.

## Context

Cycle 20 closed your items (2) evidence provenance and
(4) operator claim (both SHIP from both seats) and built
the Ed25519 authorisation boundary. CROSS-CHECK-14 left
two gates: item (1) — the in-house Ed25519 needed
independent differential validation plus seed hygiene
(seat-gpt SHIP-with-qualification 0.91; seat-gemini FIX
blocking); item (3) — consumption integrity: a consumed
envelope replayed under a stale caller-supplied history
could still regress the pin (seat-gpt FIX 0.96, blocking
cycle 20 as an integrated system; seat-gemini FIX binding
on cycles 14–16). The store location for the consumption
head was decided by the internal war room under the
owner's standing rule (design decisions are the room's;
the owner is informed, not asked): VERIFIER-OWNED.
Cycles 14–16 remain HELD and are not re-reviewed here.

## What was built — Workstream A (item 1)

- A differential suite exercising the PRODUCTION verify
  in signing/ed25519.py: RFC 8032 §7.1 known-answer
  vectors as literals incl. a 1024-byte long-message
  vector; a Wycheproof-style adversarial table where every
  row pins a PER-CASE expectation PAIR (in-house,
  openssl): non-canonical R and A (y = q, q+1, 2^255−1;
  sign-bit and x = −0 spellings), S ∈ {L−1, L, L+1,
  2^256−1} and S+L malleation, all 8 small-order encodings
  as A and as R — including rows where openssl ACCEPTS
  (identity A; the non-canonical y = 1+q spelling of A)
  pinned as (False, True), which is exactly why the pairs
  are pinned rather than a blanket agreement claim —
  mixed-torsion A+T / R+T, cross-vector signature swaps.
  The in-house verifier must return False on every
  adversarial row.
- Bit-flip sweeps against the production verify: every
  single-bit flip of the 64 signature bytes, the 32
  public-key bytes, and the message must verify False.
- Openssl differential (skips cleanly when openssl is
  absent): openssl's deterministic signature must be
  BYTE-IDENTICAL to ours, and ours must pass openssl
  verification; seeded cross-implementation agreement both
  directions on honest signatures. A non-builder reviewer
  independently re-probed the full 51-row adversarial
  table with separately written openssl driver code: zero
  mismatches against the pinned pairs.
- Seed hygiene: ONE shared owner-only permission
  predicate for both key loaders — accept iff no
  group/world bits (mode & 0o077 == 0), no
  setuid/setgid/sticky bits, owner-read bit set (in
  practice {0400, 0600}); fail closed otherwise. The
  ceremony seed loader adds fd discipline
  (O_NOFOLLOW|O_NONBLOCK, fstat, bounded read from the
  fd) and an owner-uid check (non-root: st_uid == euid).
  Derivation-overlap refusals where both secrets exist,
  closed set: seed == key; seed == sha256(key);
  key == sha256(seed); key == ceremony public key;
  seed == sha256(ceremony public key);
  key == sha256(ceremony public key);
  seed == sha256(own public key); key ∈ refused test
  seeds; and the HMAC key treated as an Ed25519 seed
  deriving the ceremony public key. Carried wording:
  these relations catch accidents and known derivations,
  not arbitrary KDF overlap; no stronger claim is made.

## What was built — Workstream B (item 3)

- The consumption head lives in the verifier's store: a
  hash-chained journal `ceremony-consumptions.json` under
  the existing verifier home, written only by a new
  verifier mode `ceremony_consume`. No new env var.
  Caller-supplied `ceremony_history` is demoted to a
  required audit/consistency input that can only refuse,
  never grant; the verifier's head is authoritative on
  any discrepancy.
- Consume protocol: body exactly
  `{"signed_authorisation"}`. The verifier re-verifies
  the envelope's Ed25519 signature and expiry under its
  OWN derived public key, checks single-use, checks the
  authorisation is present in the issuance journal with
  matching fields, applies the head rules, then commits.
  Head rules: candidate behind the head refuses; a fresh
  envelope whose candidate equals the head target refuses
  as already-consumed (re-mint laundering closed); a fork
  at the head refuses; the old pin must not be behind the
  head (equal-seq requires hash equality; ahead passes —
  advance_pin movements never pass through the verifier);
  initial_anchor against a non-empty consumption journal
  refuses. All non-temporal verification failures share
  ONE refusal code, byte-identical on stdout and stderr —
  no forger oracle.
- Commit point: the consumption-journal append, which
  re-checks single-use and the head rules against freshly
  reloaded entries inside the append (concurrent
  double-consume has exactly one winner — two-process
  barrier-race tested). After the commit, the consumption
  is mirrored into the anchored signing ledger (kind
  "consume"); mirror failure leaves the envelope burned
  and returns failure — no success response.
- Ceremony side: reanchor_pin now REQUIRES the callable
  `consume_authorisation` keyword (omission = TypeError;
  None / non-callable refuses before envelope
  verification), invoked exactly once after all local
  checks and before the ceremony record exists. A
  consumer exception — including a lost response after
  the verifier committed — propagates as a refusal.
  Trade-off, stated in the docstring: reanchor_pin is no
  longer an offline function; a successful ceremony needs
  a live verifier round-trip inside the envelope's TTL
  and fails closed when the verifier is unreachable.
- Crash-consistency contract: consumption is committed
  (fsync'd journal append) before reanchor_pin returns
  anything; there is no execution path in the integrated
  system where a pin movement succeeds without its
  consumption record durably committed first; a crash
  after commit but before adoption leaves the
  authorisation burned and the pin unmoved; recovery is a
  new ceremony, never an un-consume. Crash kill-point
  tests (K1–K6) and a commit-then-raise consumer test pin
  this.
- The cycle-20 regression tests (stale-history replay
  regressing the pin) now assert REFUSAL, wired to a real
  ledger-backed consumer; a subprocess suite wires the
  real verifier (replay across fresh clients, never-
  issued, expired, verifier-down fail-closed, mirror
  scoping).
- Claim wording: single-use consumption and pin
  non-regression are properties of the INTEGRATED SYSTEM
  under production wiring, not of reanchor_pin for an
  arbitrary caller-supplied callable (a no-op callable
  gets no protection — as with a self-supplied signing
  key or a wrong public-key pin).

## Test evidence

Full suite: 1472 tests OK (skipped=28), baseline 1406.
New suites: Ed25519 differential (KAT, adversarial pairs,
bit-flip sweeps, openssl differential), ceremony seed
hygiene, ceremony_consume mode (incl. crash kill points
and the concurrent double-consume race), ceremony
consumption subprocess integration; pin ceremony suite
rewired so the default test consumer is a real
ledger-backed consumer, never an always-succeed fake.

## Open items — stated plainly

1. **No production caller of reanchor_pin exists.** The
   integrated path (library + VerifierClient + verifier
   mode) is built and exercised end-to-end in tests; no
   loop/storage adopter calls reanchor_pin in production
   yet. The single-use / non-regression guarantee binds
   the first adopter that wires as specified. We ask you
   to judge the item-(3) claim in exactly that scope.
2. **Burned-but-unmoved recovery (F4).** After a consume
   commits but the pin is not adopted, recovery today
   still requires recording reason=lost_pin for a pin
   that is not lost — the label is untruthful. The named
   follow-up `burned-but-unmoved-recovery-reason` (a
   dedicated reason or a journal-proven old-pin
   exception) is NOT built; the reason grammar is shared
   with the issuance side. We ask whether you accept this
   as a deferred residual under the provisional scoping,
   or require it built before item (3) counts as closed.
3. **The consumption journal is not externally
   anchored** (nor is the issuance journal): follow-up
   `ceremony-journal-anchoring` now covers both jointly.
   A verifier-home rollback cannot resurrect a consumed
   envelope whose consumption reached the anchored
   signing-ledger mirror (production), but can lower the
   enforced head for never-consumed envelopes.
4. **The head is a ceremony head, not a pin head.**
   advance_pin movements never pass through the verifier;
   the old-pin not-behind rule narrows the fresh-envelope
   regression class, and full closure belongs to a future
   loop/storage pin-store compare-and-swap.
5. The gate signing-key loader's fd rework is a named
   follow-up (`signing-key-loader-fd-hardening`); its
   permission predicate was widened this cycle.

## Questions for the seats

1. Is item (1) — Ed25519 validation — now CLOSED
   (differential pairs, bit-flip sweeps, openssl
   cross-check, seed hygiene incl. derivation overlap)?
2. Is item (3) — consumption integrity — now CLOSED in
   the scoped form stated in the headline (integrated
   system, production wiring, intact verifier home,
   unanchored consumption journal), including explicit
   acceptance or rejection of the F4 deferral (open
   item 2) and the no-production-caller scope (open
   item 1)?
3. May cycles 14–16 now proceed to re-review on the
   strength of this head — the precondition they were
   held on — or do you require anything further first?
4. Does anything over-claim what this cycle proves?
