# CRITIQUE B — Cycle 21 cross-critique round (seat B on designs A and C, and on design B)

Seat B, cross-critique round. Design only — no code edited.
Read in full: `internal/cycle21-work/design-a.md`,
`internal/cycle21-work/design-b.md` (my own), and
`internal/cycle21-work/design-c.md` — **with one evidence
caveat that the build round must not lose: design-c.md as
saved on disk is truncated.** The file is 17,409 bytes and
ends mid-sentence in §2, at the production-callable bullet
("exit-2 → …[truncated 15821 chars]" is literally the
file's final bytes). C's §3–§8 — the crash contract, the
FRESH-PIN discussion (§4), the signing-ledger mirror (§7),
and the receipt-binding rejection (§8) — are **not in the
file**. My critique of those parts rests on C's §0 summary
of positions, on §1–§2 as written, and on the coordinator's
task summary of C's positions. That is enough to rule on
the seven divergences below, but the war room should not
record C's unseen sections as "reviewed": either C
re-saves the full text, or the final design states those
positions itself.

Code evidence cited below was re-checked this round:
`signing/pin_ceremony.py` (exact old-pin binding at the
`env_old_pin != expected_old_pin` step; caller
preconditions FRESH-PIN / COMPLETE-HISTORY /
ATOMIC-ADOPTION / EVIDENCE-INTENT in the module
docstring), `signing/ceremony_authorisation.py:142`
(`REFUSED_TEST_SEEDS`), `signing/ceremony_authorisation.py:269`
and `signing/gate_decision.py:297` (both loaders currently
demand exactly 0600), `trust/verifier_main.py:311`
(`_REFUSED_TEST_KEYS`), `trust/verifier_main.py:526/557/563`
(existing startup checks), `tests/test_signing_pin_ceremony.py`
(T7/T8), and `internal/CROSS-CHECK-14.md` item (1)
("seed-file permission enforcement (0600, fail closed)").

---

## 1. Head rule for `old_pin` — M4 defended on the concrete case, conceded as an absolute

### 1.1 The concrete case is not a regression hole

Task case: consumed head target = seq 4; a **fresh**
envelope arrives with `old_pin = seq1`, `candidate = seq9`.

Trace it through the integrated system, both layers:

- **Verifier layer (my M3):** candidate 9 > head 4, so
  consume admits. Correctly — there is nothing at this
  layer to refuse: the envelope is unconsumed (M1 silent),
  issued (M2 silent), and its target advances every
  consumption ever recorded.
- **Caller layer (`reanchor_pin`):** the envelope is
  bound, exactly, to the old pin it was issued against.
  The binding step compares the envelope's `old_pin`
  against the pin dict the caller presents
  (`env_old_pin != expected_old_pin` refuses). So this
  envelope can only complete a ceremony in which the
  caller presents the seq-1 pin as its captured pin.
- **What adoption would do:** if the caller's live pin
  is seq 6 (consumed to 4, then advanced 4→5→6 by
  `advance_pin`, which leaves no trace in any journal),
  adopting this envelope's result moves the pin **6 → 9**.
  That is a forward jump, not a regression. The seq-4
  pin is not restored; no consumed target is re-attested.
  **On the concrete numbers, M4 admits a forward move and
  no pin moves backwards. M4 is not a regression hole
  here.**

What a ceremony "claiming `old_pin = seq1`" *means* when
the live pin is at seq 6 is the sharper question, and it
has exactly two readings:

1. **The caller is honest and its live pin really is
   seq 1** — e.g. the seq-4 consumption burned but was
   never adopted (crash in the burn window), so the pin
   legitimately still sits at 1 and a recovery ceremony
   was issued from it. The envelope is then exactly what
   it claims to be, and refusing it strands recovery.
2. **The caller restaged seq 1** while its live pin is
   seq 6. That is a FRESH-PIN violation — a documented,
   unverifiable caller precondition (`pin_ceremony.py`
   module docstring), of the same class as every design
   in this cycle retains (C §1.1 states this consequence
   plainly for its own rule). A restaging caller can
   equally restage `old_pin = seq4` with the head's hash,
   which no not-behind rule refuses. Restaging is not
   what a head rule over `old_pin` can close.

### 1.2 Where M4 genuinely loses — the variant, and the concession

Change one number: fresh envelope, `old_pin = seq1`,
`candidate = seq5`, head = 4, live pin = 6 (via advances).
M3 admits (5 > 4); a caller presenting seq 1 completes
the ceremony and adopts seq 5 — **the pin regresses
6 → 5 through a fresh envelope**, the T8 shape with M1
unable to fire. My design already named this class as
its honest limit (§3.4 / A states the identical limit as
its weakest point), but M4's wording — "`old_pin` plays
**no** role" — claims more purity than the design
delivers, and it throws away a cheap narrowing: an
envelope whose issuance base is *behind the consumed
head* was issued against a state the system has already
ceremonied past. That is stale issuance, and the
verifier can see it.

**CONCESSION: M4 is revised. `old_pin` gains exactly one
role — a not-behind check at consume time — stated
precisely (this merges A's R3 and C's §1.1 rule, which
agree with each other):**

Let `H = (H_seq, H_hash)` be the consumed head (the last
consumption entry's candidate; no head if the journal is
empty). For an envelope carrying an `old_pin`
`O = (O_seq, O_hash)`:

- `O_seq < H_seq` → refuse (A: `ceremony_old_pin_stale`;
  C: `ceremony_consumption_stale` — one code must win in
  the final design; I have no stake in the spelling).
- `O_seq == H_seq` and `O_hash != H_hash` → refuse
  (the old pin is a fork of the head: a different
  snapshot at the consumed sequence).
- `O_seq == H_seq` and `O_hash == H_hash` → pass (the
  canonical case: the next ceremony is based on exactly
  the pin the last consumption produced).
- `O_seq > H_seq` → pass, unconditionally (the
  `advance_pin` bypass: the live pin legitimately moved
  past the ceremony head with no verifier trace; my
  original M4 worked case — head 4, old 6, candidate 9 —
  still admitted, now by this clause instead of by
  irrelevance).

For an envelope carrying **no** old pin
(`initial_anchor` / `lost_pin` / `corrupted_pin`): the
old-pin check is **exempt** — a missing pin cannot be
behind anything — but (a) the candidate rule
(candidate strictly ahead of the head, equal-seq
equal-hash also refused) applies unchanged, and (b) I
adopt A's additional clause: `initial_anchor`
additionally refuses whenever the consumption journal is
non-empty, since a non-empty head contradicts "no
ceremony precedes this one" more authoritatively than
the caller's empty history does.

**What this concession costs, stated so it is a decision
and not a surprise:**

- My §3.3 worked case "parallel issuance, late consume"
  (two envelopes from old 1, candidates 4 and 9; consume
  9-or-4 second) is **withdrawn as legitimate in its
  second-consumption form**: once the head has moved past
  seq 1, the surviving envelope's base is stale and it
  refuses; re-issuance against the current pin is the
  correct path. Test C7 in my §8.1 must be rewritten to
  assert this refusal in the order where the head passes
  the base.
- Burned-but-unmoved recovery (reading 1 in §1.1) is
  narrowed: a recovery envelope issued from the unmoved
  pin behind the head now refuses at consume. Recovery
  must be issued against a base at or ahead of the head
  — in practice the head pin itself, which the caller
  knows because it presented that candidate in the
  burned envelope. This is a real availability cost in
  exactly the recovery flow; I judge it acceptable
  because the alternative (admitting behind-head bases)
  re-admits the seq-5 variant above, but the final
  design must document the recovery procedure in these
  terms, not discover it in an incident.
- **The concession does not close the general class.**
  An envelope issued from `old = head` (equal seq, equal
  hash) with a candidate ahead of the head but behind a
  silently advanced live pin still passes every layer.
  A says this in its weakest-point section; C says it in
  §1.1; my revised position says it too. The not-behind
  rule is a narrowing (it kills issuance bases the
  verifier can *prove* stale), not a closure, and no
  record in this cycle may describe it as one. Closure
  remains the verifier-owned pin store / loop-layer CAS
  follow-up all three designs name.

**Verdict on the three-way divergence:** A's R3 and C's
not-behind rule beat my M4 as *stated*; M4's underlying
point — the head is a ceremony head, never to be
confused with the live pin, and `O_seq > H_seq` must
never refuse — survives inside the conceded rule.

---

## 2. Library-level enforceability — I concede; C's integration satisfies GPT's condition

This was my weakest point 2 (§7.2), and C's design beats
it. Ruling, as the task demands, yes or no:

**YES — C's integration (required `consume_authorisation`
callable in `reanchor_pin`, production wiring through
`VerifierClient.ceremony_consumer()`, unit tests wiring
real ledger-backed consumers) satisfies GPT's condition
as an integrated-system property.**

Reasoning, in three steps:

1. **GPT's standard was always the integrated system.**
   CROSS-CHECK-14 frames the blocking item as a defect
   "in the integrated system", and my own design §0
   restated the guarantee as "properties of the
   **integrated system** (verifier + caller), not of any
   one function". I then argued §7.2 as if a
   library-level guarantee were the bar GPT set. It was
   not. Measured against the standard I myself wrote in
   §0, C's integration meets it: in the production path,
   `reanchor_pin` cannot return a pin without the
   callable having committed a verifier-side consumption,
   because the callable is a required keyword, is invoked
   as the last fallible step, and the production caller
   passes exactly one implementation — the verifier-backed
   one.

2. **My "a caller can pass a no-op callable" objection
   proves too much.** It applies, identically, to inputs
   `reanchor_pin` already trusts and always has:
   - `signing_key` — a caller passing the wrong key gets
     refusals, and a caller passing a key of its own
     choosing controls the record MAC entirely;
   - `authorisation_public_key` — the pinned ceremony
     public key is *caller-supplied*; a caller that pins
     an attacker key and presents a matching forged
     envelope passes envelope verification in-process.
     The function's forgery resistance has always rested
     on the production caller pinning the *right* key —
     a wiring property, not a library property;
   - `ceremony_history` — caller-supplied, and its
     staleness is precisely what the function cannot
     detect (the T7/T8 defect itself).
   A callable is not materially different in kind from
   these. If anything it is *stronger* than the history
   input it supplements: history is passive data whose
   defect (staleness) is undetectable in-process, while
   the callable is behaviour whose production instance is
   backed by state the caller cannot write. A's §D2
   makes the architectural point I missed: `signing/`
   must not import `trust/`, so dependency injection is
   not a concession to the caller, it is the only typed
   seam across the module boundary. My §7.2 options
   (a)/(b) — receipt parameter or move `reanchor_pin`
   behind the verifier — were a false pair; the callable
   was the third option and it was already in the room.

3. **The threat model resolves the residual.** The
   demonstrated attacker is the *honest-but-stale or
   rolled-back* caller (T7/T8 restage history and pin,
   but they run the real ceremony code). That caller,
   under C's integration, runs the production wiring and
   is stopped. A caller that *deliberately* wires a no-op
   consumer is not stale — it is a caller dismantling its
   own ceremony path, in the same class as a caller that
   pins its own authorisation key or skips `reanchor_pin`
   entirely and writes the pin store directly. No design
   in this cycle (mine included — my caller contract in
   §2.7/§4.2 is exactly as bypassable) defends against
   that caller, and pretending otherwise was the flaw in
   my §7.2 framing.

**Exact wording the records must use, so the claim is
exactly true** (this wording discipline is the part of
my §7.2 that survives):

> "In the integrated production path, a pin returned by
> `reanchor_pin` is always preceded by a committed
> verifier-side consumption, because the production
> caller passes the `VerifierClient`-backed
> `consume_authorisation` and `reanchor_pin` invokes it
> as its last fallible step. Single-use is therefore a
> property of the integrated system under its production
> wiring. It is not a property of `reanchor_pin` for an
> arbitrary caller-supplied callable, and no record
> claims library-level enforcement."

Two build requirements follow from the concession:

- **The flipped T7′/T8′ must wire a real consumer.** A
  test whose fake is an in-memory set proves the fake.
  At the `reanchor_pin` level, at least one T7′/T8′
  variant must pass a consumer backed by a real
  `CeremonyConsumptionLedger` over a temp verifier home
  (the honest consumer), so the flip is a property of
  the ledger's refusal, not of a test double's bookkeeping.
  A's test list gestures at this ("verifier-backed (or
  fake-backed, per test layer)"); the final design must
  pin which layer is real, and the reanchor-level flip
  must be the real one.
- **My §8 expectation for T7/T8 is withdrawn.** I
  proposed re-pinning the in-process tests as a
  documented residual or removing them. C's flip at the
  `reanchor_pin` level — shapes kept, assertions reversed
  to refusal — is strictly better: it keeps the attack
  scenarios executable *as attacks that fail*, which is
  what GPT's condition asks the suite to show.

**Related concession — invocation point.** A and C both
place consumption *inside* `reanchor_pin`, after every
local check, as the last fallible step. My design placed
consume *before* `reanchor_pin` in the caller (§2.7,
§4.2). Their placement beats mine on two counts A states
correctly (§D2.1): caller orchestration is forgettable
in a way a required parameter is not, and my ordering
burns an envelope on any local refusal that consume
cannot foresee (bare-verifier failure, binding mismatch)
— a wasted single-use authorisation and an invitation to
"retry with the same envelope". Under A/C's ordering, a
locally refused ceremony burns nothing (their
zero-calls-on-refusal spy test pins it), and the only
burn window is commit-to-adoption, which all three
designs share. **I adopt the A/C invocation point and
withdraw my §4.2 two-process protocol in its
consume-first form**; the protocol becomes: local checks
→ consume commit (inside `reanchor_pin`, via the
callable) → return → atomic adoption. My §7.1
response-lost analysis survives unchanged in substance —
a callable whose response is lost still leaves
consumption state unknown-to-the-caller and the
fail-closed rule (treat as burned, never adopt on a
retry's `already_consumed`) still applies — but it now
applies at the callable boundary, not at a caller-managed
step.

One point where I prefer C's contract over A's: A's
callable takes `(authorisation, new_pin)`; C's takes
`(authorisation)` only. The candidate is inside the
signed envelope; a second, caller-side projection of it
is a redundant argument that can only agree (it is
derived in-process) or introduce a mismatch path with no
security content. **C's one-argument protocol should win.**
A's receipt-echo validation in the client (authorisation
id, candidate echo, consumption seq) recovers the same
assurance on the transport side, where it belongs.

---

## 3. Seed permissions — CONCEDED: {0400, 0600}; exactly-0600 was a spelling preference

I searched for the evidence my §6.2 position would need.
There is none:

- **No test** references 0400 anywhere in `tests/`,
  `signing/`, `trust/`, or `deploy/` (grep this round:
  zero hits for `0400`/`0o400` outside this cycle's
  design files).
- **No loader or doc** depends on refusing 0400. Both
  loaders currently demand exactly 0600
  (`ceremony_authorisation.py:269`, `gate_decision.py:297`)
  — that is the *status quo*, not a *dependence*: nothing
  downstream reads the mode again or assumes writability
  of the seed file (the loader only reads; generation
  writes a fresh file at 0600 via `O_EXCL`).
- The only 0600-exact expectations in deployment are
  `deploy/verifier-identity/health_check.py`'s
  provisioning checks (installed key files expected at
  0600). Those check the *generated* state an installer
  produces; they are not a reason the *loader* must
  refuse a more restrictive file an operator deliberately
  installed, and if the room wants 0400 deployments the
  health check is a one-line provisioning-expectation
  update, not a security argument.

My §6.2 supporting arguments also fail on inspection:

- "Relaxing would accept a write-only 0200 file the
  loader cannot read" — A's predicate does not accept
  0200: it requires the owner-read bit and zero
  group/other bits, i.e. exactly {0400, 0600}. The
  confusing-failure scenario I cited is excluded by the
  very rule I was arguing against.
- "Two loaders, two policies is a drift surface" — A
  eliminates the drift with a shared predicate helper
  applied to both loaders (§5 below refines the scope).
  Exactly-0600 in both loaders is *also* two copies of a
  policy today; sameness was never an argument for
  *this* policy.
- "The directory discipline already discharges
  'or stricter'" — a non-sequitur: directory mode says
  nothing about whether a 0400 seed file should load.

The security property is the one A and C state:
**no principal other than the owner can read the seed,
and the owner can.** 0400 satisfies it strictly better
than 0600. Refusing 0400 pushes a hardening operator
toward the *more* permissive mode — the opposite of the
rule's intent — and CROSS-CHECK-14's own shorthand
("(0600, fail closed)") names the floor of the property,
not an exact-mode requirement; the coordinator's task
text ("0600 or stricter") reads it correctly.

**Revised position:** the loader predicate is
`(mode & 0o077) == 0 and (mode & 0o400) != 0`
(equivalently mode ∈ {0400, 0600} for a regular file),
checked on the `fstat` of the opened fd. Generation
still creates 0600. My proposed test "0400 refuses
(pinned decision)" is replaced by "0400 and 0600 accept;
0640 / 0604 / 0700 / 0200 / 0000 refuse". Exactly-0600
was a spelling preference dressed as a discipline, and
I withdraw it.

---

## 4. Derivation-overlap relations — merge; each set catches one the other misses

The two sets, over raw bytes at `_load_config` (the only
place both secrets exist — all three designs agree on
placement). Notation: `S` = ceremony seed, `K` = HMAC
signing key, `P` = ceremony public key
(`public_key_from_seed(S)`, public by design — it is the
pinned `authorisation_public_key` every caller holds).

| Relation | Mine (B) | A's | Verdict |
|---|---|---|---|
| `S == K` | existing check, kept | R1 | agree |
| `K == sha256(S)` | R2 | R2 | agree (same relation) |
| `S == sha256(K)` | R1 | R3 | agree (same relation) |
| `K == P` | **R3** | — | **mine catches, A misses** |
| `S == sha256(P)` | **R4** | — | mine catches, A misses (contrived, cheap) |
| `S in REFUSED_TEST_KEYS` | — | R4 | **redundant today** (see below) |
| `K in REFUSED_TEST_SEEDS` | — | R5 | **A catches, mine misses** |

**A's R4 is redundant on today's lists — check the code.**
`_REFUSED_TEST_KEYS` (`verifier_main.py:311`) is exactly
{`bytes(range(32))`, `bytes(range(32,64))`, `0x00*32`,
`0xff*32`}. `REFUSED_TEST_SEEDS`
(`ceremony_authorisation.py:142`) is those same four
**plus** the RFC 8032 TEST 1–3 seeds. The existing
startup check (`verifier_main.py:563`) already refuses
any `S in REFUSED_TEST_SEEDS`, which is a superset — so
`S in _REFUSED_TEST_KEYS` can never fire first. It is
harmless as belt-and-braces against future list
divergence, but the final design must not count it as a
new relation.

**A's R5 is a real catch mine misses.** `K in
_REFUSED_TEST_KEYS` (existing, line 526) refuses only
the four predictable keys. `K` equal to an RFC 8032 TEST
seed is a *publicly known* 32-byte value sitting in every
Ed25519 test fixture — an operator (or a provisioning
script) that reaches for a "known-good 32 bytes" example
can land exactly there, and the HMAC key being public
knowledge means forgeable gate signatures. My set has no
relation that fires on it.

**My R3 is the most dangerous catch A misses.**
`K == P`: the ceremony public key is *published* — pinned
in every ceremony caller. If it is also the HMAC key,
anyone holding the pin (i.e. anyone) can forge gate
decisions. This is not a derivation, it is public
material reused as a secret, and it is the easiest
relation in either table to commit by accident
(copy the public key file's contents into the key file —
the files are both 32-byte hex). Neither A's sha256
relations nor its refused-set relations fire on it:
`P` is not `S`, not `sha256` of either secret in
general, and not a test value.

**One relation neither design has, which the comparison
exposes:** `K == sha256(P)`. Anyone can compute
`sha256` of the published public key; if that value is
the HMAC key, the key is publicly derivable — the same
severity as R3, one hash removed. It costs one
comparison. A closed set that refuses `K == P` but
admits `K == sha256(P)` is not closed.

**Proposed final closed set** (all refused at
`_load_config`, both modes, detail naming neither value;
`P` computed once from `S`):

1. `S == K` (existing)
2. `K == sha256(S)`
3. `S == sha256(K)`
4. `K == P` — public material as the secret
5. `K == sha256(P)` — publicly derivable secret (new,
   from this critique)
6. `S == sha256(P)` — self-derivation loop (my R4, kept:
   one hash, closes the symmetric slot to 5)
7. `K in REFUSED_TEST_SEEDS` (A's R5)
8. `S in _REFUSED_TEST_KEYS` (A's R4 — kept explicitly
   as a divergence guard, recorded as redundant against
   today's superset check, not counted as coverage)

Explicitly **not** in the set, with the reason recorded
(all three designs agree on the limit): hex-encoding
variants, and any KDF/HKDF/XOR-mask relation — a finite
startup check catches copy-paste and single-hash
derivations, not arbitrary derivation; provisioning
discipline (independent random draws) remains the real
defence, and the docstring must say so.

---

## 5. fd-hardened loader scope — split ruling: predicate both loaders, fd rework ceremony-only

A hardens **both** loaders (seed and HMAC key) with the
fd discipline and proposes a shared mode helper in
`gate_decision.py`. My design and C's scope the fd
rework to the ceremony seed loader only.

**Ruling: A wins on the permission predicate, B/C win
on the fd rework — and the two must not be conflated.**

- **Predicate (the {0400, 0600} semantics of §3): apply
  to both loaders this cycle.** After the §3 concession,
  leaving `load_signing_key` at exactly-0600 while the
  seed loader accepts 0400 would create precisely the
  two-policies drift my §6.2 claimed to fear — same
  key-file discipline, two spellings, diverging by
  accident of scope. The predicate change is one
  comparison per loader plus a pinned test matrix in
  both test files (A's change list has this right,
  including pinning 0400-acceptance for `load_signing_key`
  as a deliberate behaviour change). A's shared helper is
  the right mechanism.
- **fd rework (`O_NOFOLLOW | O_NONBLOCK` open, `fstat`
  `S_ISREG` + mode + uid, bounded fd read): ceremony
  loader only this cycle.** The external item names the
  ceremony seed path (`AION_CEREMONY_SIGNING_SEED_PATH`
  is the env var in the mandate; CROSS-CHECK-14 item (1)
  says "seed-file permission enforcement"). The
  check-then-read gap in `load_signing_key` is real —
  the code has the identical `stat()`-then-`read_bytes()`
  shape — but `load_signing_key` is on every gate path,
  its change surface is larger, and no external item
  names it. Scope discipline cuts both ways: I argued
  scope against A's anchoring-adjacent expansions
  elsewhere and cannot expand here because the expansion
  is mine-adjacent. **Named follow-up, recorded in the
  final design and in `gate_decision.py`'s docstring:
  `signing-key-loader-fd-hardening`** — the HMAC loader
  gets the identical fd discipline, as its own reviewed
  change. A's fallback wording ("if the war room rules
  this out of scope, the divergence must be recorded as
  a named follow-up, not left silent") is adopted
  verbatim as the mechanism.
- A's `st_uid == euid` check: my ceremony-loader design
  has the same check (with a root carve-out A does not
  state; A's Q3 defends keeping it in research mode).
  Keep it for the ceremony loader; the carve-out
  question (`geteuid() == 0` skips) should be settled in
  the final design — I note root-running tests will trip
  A's version and skip in mine, and the build must not
  discover this by a red suite.

---

## 6. The openssl oracle — per-direction ruling: A and B converge more than the framing suggests

The divergence as posed (A: byte-identity; B: partition)
dissolves once the directions are separated, because the
two designs were talking about different directions.

**Sign direction (and key derivation): byte-identity is
the correct assertion — A is right, and B already
agrees.** RFC 8032 signing is deterministic: same seed,
same message ⇒ same 64-byte signature, in any conforming
implementation. My §6.1 layer 3 already asserts
byte-equality on the valid corpus ("openssl's signature
must be **byte-equal** to ours … assert equality, not
just verify-agreement"). A's formulation is the cleaner
statement of the same position, including its reason:
acceptance-only would pass a probabilistic signer, and
Ed25519 is not one. **Rule: `public_key_from_seed` and
`sign` MUST be byte-identical to openssl's outputs on
the shared corpus (RFC vectors incl. the 1024-byte
message, plus seeded-random pairs). Any byte difference
is a finding, never a bucket.**

**Verify direction, valid signatures: agree-accept is
mandatory** (both designs): our signature verifies under
openssl, openssl's under ours.

**Verify direction, adversarial signatures: divergence
legitimately appears here and only here.** Verification
is where implementations make *acceptance* choices the
RFC leaves room for — cofactored vs cofactorless
equation, non-canonical encodings, small-order
components (the ZIP-215 leniency class). Our strict
profile rejects inputs a laxer verifier accepts; that
is the profile working as designed, not an
implementation disagreement. So for adversarial cases
neither byte-identity nor outcome-identity may be
asserted against openssl. **Rule: our rejection is
asserted; openssl's outcome is classified, never
equated.**

On the classification mechanism, **A's bucket taxonomy
beats my partition's bookkeeping, and I adopt it**: my
MUST-AGREE / KNOWN-DIVERGENCE split and A's
AGREE-REJECT / AGREE-ACCEPT / DIVERGE-EXPECTED are the
same partition, but A adds the discipline mine lacked —
each case carries an *allowed set* for openssl's
outcome, an outcome outside the allowed set is a failure
to investigate (not a re-bucketing), and the build must
report actual bucket counts. My version recorded
openssl's answer "not asserted", which would let a
genuine surprise (openssl rejecting a case both designs
predicted it accepts, suggesting *our* construction of
the case is wrong) pass silently. The merged rule:

- MUST-AGREE-REJECT keeps one carve-out from my table:
  `S = L−1` equation-satisfying constructions sit in
  AGREE-ACCEPT-if-openssl-accepts territory per A's
  table; the final suite must place that case by
  *measured* openssl behaviour at build time and record
  the placement, per A's "predicted bucket ≠ measured
  bucket is a finding" rule.
- Promotion of any case between buckets requires a
  war-room note with the observed openssl output (my
  §7.4 condition, which A's reporting rule now makes
  enforceable).

**Net verdict:** no remaining disagreement on substance.
The final design should write the oracle as three
per-direction rules (derive: identical; sign: identical;
verify-adversarial: partitioned with allowed sets), not
as either design's single slogan.

---

## 7. Signing-ledger mirror — semantics agree; required order stated

**Confirm: C's signing-ledger mirror and my dual-append
agree on commit-point semantics.**

- The **consumption-journal append is the commit**. Before
  it lands, nothing is consumed and any refusal is
  retryable; after it lands, the `authorisation_id` is
  spent whether or not anything else succeeds.
- **Mirror failure after the commit ⇒ `ledger_failed`,
  receipt withheld, envelope burned.** A retry refuses
  `already_consumed` — and it can refuse from *either*
  store, because the already-consumed check consults the
  primary journal and the mirror's consume entries. The
  primary entry without a mirror entry is a visible audit
  gap, not an ambiguity: single-use does not depend on
  the mirror landing.
- The mirror's purpose is identical in both designs:
  it is an **audit/anchoring trace, not a second
  commit** — it puts the consumption fact into the one
  journal that is externally anchored in production, so
  a consumption-journal rollback cannot resurrect a
  consumed envelope (the mirror cross-check still
  refuses it), while it cannot reconstruct the head
  (it carries no candidate sequence), leaving
  head-regression-after-rollback as the named residual
  both designs carry into the joint anchoring follow-up.

**Composition with `append_consumption`'s in-loop
re-check:** my ledger method re-validates, inside its
bounded reload→validate→append loop (8 attempts,
fresh entries each time), both the duplicate check and
the head check, before `_append`. This composes with
the mirror ordering without hazard, provided one rule
is observed: **the mirror append is invoked only on the
successful return of `append_consumption`.** The in-loop
re-check is entirely inside the primary append; if it
raises (duplicate found on reload, head not advanced,
retries exhausted), no consumption exists and no mirror
entry may be written. The mode-level pre-scan
(already-consumed / never-issued / head) remains what it
was in my design — an early, friendly refusal — with the
commit-point re-check as the authoritative one, per the
cycle-20 issuance lesson both designs cite.

**The ordering hazard, stated as the required order.**
The appends and the anchor update have exactly one
correct sequence:

1. `CeremonyConsumptionLedger.append_consumption(...)`
   — **the commit**;
2. `SigningLedger.append_ceremony_consumption(...)`
   — the mirror;
3. `_update_anchor(config)` — advances the signing
   anchor over the mirror entry.

**Mirror-before-consumption would invert the commit, and
must be refused in review if the build produces it:** if
step 2 landed and step 1 then failed (head refusal on
reload, journal error), the envelope would carry a
mirror consume entry — so every retry refuses
`already_consumed` via the cross-check — while the
consumption journal holds no entry and **the head never
advanced**. That state is strictly worse than either
design's failure modes: the envelope is burned, the
head is unmoved, the audit trail asserts a consumption
the authoritative journal denies, and the
rollback-detection story inverts (the mirror would now
be the store that *creates* consumptions rather than
the store that *detects their erasure*). The asymmetry —
primary = authority, mirror = audit — must be stated in
both ledgers' docstrings (my §2.5 requirement, which I
hold), precisely so a future reader does not "fix" the
order. The anchor update's place is last and is not
optional to reason about: the anchor covers the signing
ledger, so it can only advance over the mirror entry
after that entry exists; a crash between steps 2 and 3
leaves a stale anchor, which `verify_anchor` already
treats as a valid prefix (staleness is not tampering),
and the next append's update advances it — the
established behaviour for every signing mode.

One hazard neither design stated, surfaced by putting
the orders side by side: because all verifier-home
journals share the directory flock (my §1.4), steps 1–3
serialise against other modes but are **not** one atomic
unit — a concurrent `ceremony_authorise` can interleave
between steps 1 and 2. That interleaving is benign
(the journals are independent chains; the mirror entry's
content does not depend on issuance state), but the
final design should say so explicitly, since a reader
could otherwise mistake the shared flock for
cross-ledger atomicity.

---

## 8. Further critiques, briefly

**Of A:**

- **A's callable signature** `(authorisation, new_pin)`:
  redundant second argument — see §2; C's one-argument
  protocol should win.
- **A's startup pre-open of the consumption journal**
  (`_load_config` opens it, fail-closed at startup)
  diverges from the ceremony journal's lazy per-request
  opening, which my design follows. A's version is
  defensible (fail earlier) but the inconsistency should
  be a stated choice, not an accident: either both
  ceremony journals pre-open or neither does. I mildly
  prefer lazy (a corrupt consumption journal blocks
  consume only, not every verifier mode at startup), but
  this is a build-level decision, not a blocking one.
- **A's R3 `initial_anchor` clause** (non-empty journal
  refuses an initial anchor regardless of history):
  adopted in §1.2 — a genuinely better use of the head
  than either B or C proposed.
- **A's adversarial-suite cost honesty** (measured
  bit-flip budget with a recorded fallback, never a
  silent reduction): adopted; it matches my §6.1
  subsampling condition and states it better.

**Of C:**

- **Body key naming.** C's client sends
  `{"authorisation": ...}`; A and B both specify
  `{"signed_authorisation"}`. One key either way (the
  converged shape is not in dispute), but the final
  design must pick one spelling — `signed_authorisation`
  matches the envelope type name and the issuance mode's
  vocabulary.
- **C's head rule as written in §1.1 is the not-behind
  rule I concede in §1** — but C states it as two
  separate refusal codes (stale vs regression) where A's
  R2/R3 split the candidate and old-pin checks into
  separately testable rules. The final design should
  follow A's rule decomposition (R1 id / R2 candidate /
  R3 old-pin) with C's codes or A's, not C's intertwined
  formulation, because the T-series tests map one-to-one
  onto A's decomposition.
- **C's surrender of `reanchor_pin`'s offline property**
  is stated in exact words in its §0/§2 (per its summary)
  — the right honesty, and the final design's docstring
  must keep that sentence. My design's caller-contract
  framing obscured the same fact; C's framing wins.
- **The truncation caveat of §0 applies to C's §7
  mirror and §8 receipt positions**: my §7 confirmation
  is a confirmation that the *summarised* positions
  agree with mine, not a review of text I could not read.

**Where all three converged and no critique is needed:**
verifier-owned `CeremonyConsumptionLedger`
(`ceremony-consumptions.json` under `AION_VERIFIER_HOME`),
new `ceremony_consume` mode, zero new env vars (allowlist
stays 17), `ceremony_history` required but demoted to
audit/consistency (A's D4 wording is the best of the
three and should be adopted verbatim), issuance-presence
cross-check at consume time, anchoring deferred to the
joint follow-up, differential suite as a new test file
with no planned `ed25519.py` change.

---

## 9. Concessions and holds

### Concessions (design B revised)

1. **M4 revised (§1):** `old_pin` gains a not-behind
   role at consume time — `O_seq < H_seq` refuses;
   `O_seq == H_seq` requires `O_hash == H_hash`;
   `O_seq > H_seq` passes; no-pin reasons exempt from
   the old-pin check but not from the candidate rule;
   `initial_anchor` refuses on a non-empty journal
   (A's clause). My "parallel issuance, late consume"
   worked case is withdrawn in its second-consumption
   form. The rule is recorded as a narrowing, not a
   closure of fresh-envelope regression.
2. **Library-level enforceability objection withdrawn
   (§2):** C's required-callable integration satisfies
   GPT's condition as an integrated-system property
   (ruling: **yes**), under the exact claim wording in
   §2. The no-op-callable objection applies equally to
   `signing_key`, `authorisation_public_key`, and
   `ceremony_history`, and is not materially different
   for the callable.
3. **Invocation point (§2):** consumption moves inside
   `reanchor_pin` as the last fallible step (A/C),
   replacing my consume-before-reanchor caller protocol
   (§4.2 withdrawn in that form). Locally refused
   ceremonies burn nothing.
4. **T7/T8 handling (§2):** flipped at the `reanchor_pin`
   level with a real ledger-backed consumer (A/C),
   replacing my re-pin-or-remove proposal.
5. **Seed permissions (§3):** exactly-0600 withdrawn as
   a spelling preference with no supporting evidence;
   the predicate is {0400, 0600} (owner-read set, no
   group/other bits), on the fstat of the opened fd.
6. **Overlap relations (§4):** merged into the final
   closed set of §4 — A's R5 (`K in REFUSED_TEST_SEEDS`)
   adopted; A's R4 recorded as redundant-today; my R3/R4
   retained; `K == sha256(P)` added as a new relation
   neither design had.
7. **Oracle bookkeeping (§6):** A's bucket taxonomy
   (allowed sets, measured bucket counts, no silent
   re-bucketing) adopted over my record-but-don't-assert
   partition.

### Holds (design B stands)

1. **Store, mode, and body shape:** verifier-owned
   sibling journal, `ceremony_consume`, body exactly one
   key — converged with A and C; held against all
   alternatives in my §1.2 table (unchallenged this
   round).
2. **Commit-point semantics (§7):** consumption append
   is the commit; mirror failure after commit ⇒
   `ledger_failed`, envelope burned; required order is
   consumption → mirror → anchor; mirror-before-
   consumption inverts the commit and is a review
   refusal.
3. **Candidate rule in full:** strictly increasing
   consumed targets, including the equal-seq/equal-hash
   refusal (same target under a fresh `authorisation_id`
   refuses) — A R2 and C agree; held.
4. **Refusal-code discipline:** one caller-visible code
   for all non-temporal signature failures (no per-reason
   oracle), already-consumed checked before never-issued,
   and the concurrent-consume loser surfaces as
   `already_consumed`, never `ledger_failed` (§2.4/§2.6
   of design B — unchallenged this round).
5. **fd rework scope (§5):** ceremony seed loader this
   cycle; the HMAC loader gets the shared permission
   *predicate* this cycle but its fd rework is the named
   follow-up `signing-key-loader-fd-hardening`, recorded
   in the final design and the `gate_decision.py`
   docstring, not left silent.
6. **Sign-direction byte-identity (§6):** held — and
   shown to be A's position too; divergence is a
   verify-direction phenomenon only.
7. **Response-lost rule (§7.1 of design B):** an
   ambiguous consume outcome is treated as burned, never
   as unconsumed, and a retry's `already_consumed` never
   licenses silent adoption — now applied at the
   callable boundary per concession 3.
8. **Anchoring deferred:** no new anchor kind this
   cycle; the mirror provides the anchored single-use
   trace; head-regression-after-rollback is the named
   residual of the joint `ceremony-journal-anchoring`
   follow-up — converged with A (D7) and C (D7).
9. **Zero new env vars:** the deploy allowlist stays at
   17 names in all five copies; any build-round addition
   is a design violation.
