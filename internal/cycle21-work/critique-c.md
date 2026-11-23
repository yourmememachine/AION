# CRITIQUE C — Cycle 21 cross-critique round (seat C)

Seat C critiquing design-a.md and design-b.md, and defending /
revising design-c.md where their arguments beat mine. Design
only — no code edited this round.

## 0. A defect in my own artefact, flagged before anything else

`internal/cycle21-work/design-c.md` as it stands on disk is
**truncated**: the file ends mid-sentence in §2 (the production
callable bullet), with a literal truncation marker as its last
line. Sections §§3–8 exist only as the one-line positions in
the §0 summary (D3–D7). A and B were therefore critiquing —
and I am now defending — a design whose crash table, T7/T8
rewrite detail, and workstream-A section were never fully
written down. That is my error, not theirs, and it matters
for §3 below: where this critique "states my crash table
precisely", it is stating it **for the first time in full**,
not quoting it. The build round must not treat design-c.md's
summary lines as a substitute for the restated text here.
The summary positions themselves (D1–D7) are complete and I
stand by them except where revised below.

Convergence recorded, not re-argued: verifier-owned
`CeremonyConsumptionLedger` (`ceremony-consumptions.json`
under `AION_VERIFIER_HOME`), new `ceremony_consume` mode,
zero new env vars, required consume callable in
`reanchor_pin`. All three designs agree; the divergences
below are the ones that remain.

---

## 1. HEAD RULE FOR `old_pin` — I HOLD against B's M4, with one concession

### 1.1 B attacks a rule nobody in this round holds

B's M4 argument (§3.2) is built against rules of the form
"old_pin must equal the head" or "old_pin must not exceed
the head". My rule is neither. It is **not-behind**:

> Require `old_cycle_seq > head_seq`, OR `old_cycle_seq ==
> head_seq` with the same `payload_hash`. (design-c §1.1)

B's own worked legitimate case — head target = 4, live pin
advanced to 6 via `advance_pin`, legitimate ceremony
`old_pin = 6 / candidate = 9` — is **admitted by my rule**
(6 > 4), exactly as B says both designs admit it. M4's
central example therefore does not discriminate between
M4 and not-behind. A arrived at the same rule independently
(A's R3), so this is 2–1, and B's argument as written does
not engage the rule actually on the table.

### 1.2 The hard case, and why not-behind earns its keep

Fresh envelope, `old_pin = seq1`, `candidate = seq9`,
head = 4:

- **Under B (M4):** admitted (9 > 4). B's safety story is
  that `reanchor_pin`'s local exact-binding refuses it if
  the live pin is not seq1.
- **Under mine (and A's R3):** refused at consume,
  `ceremony_old_pin_stale` / my `ceremony_consumption_stale`.

B's charge — "old_pin is caller-staged anyway" — is half
true and the wrong half. The envelope's `old_pin` was
caller-asserted **at issuance**, yes. But the consume step
is the only point in the system where a value is compared
against the verifier-owned head, and that comparison
catches the exact caller the whole cycle exists for: the
**stale / rolled-back caller**, who is not lying
strategically but is operating from restaged state — T8's
caller. Make the candidate concrete and B's gap is a
regression, not a curiosity: head = 4, live pin at seq6
(via `advance_pin`), a **fresh** envelope (new
ceremony_id, new evidence — authorisation_id uniqueness
cannot see it) bound to `old_pin = seq1`, `candidate =
seq5`. B admits it (5 > 4); the stale caller restages its
`old_pin` argument to seq1, local binding passes
(envelope-old == argument-old, both staged), and
`reanchor_pin` returns the seq-5 pin — **behind the live
seq-6 pin**. That is T8's regression with a fresh envelope,
admitted by M4. My rule refuses it at the verifier
(1 < 4) before any pin exists to adopt. B's §3.3 table
even lists this shape ("Parallel issuance, late consume:
old 1, cand 9 → ok") as a feature; with cand 5 instead of
9 it is the defect. A rule that cannot distinguish those
two rows is not finished.

**Concession to B (the limit of my rule):** not-behind
protects only when the restaged old pin is *behind* the
head. A restaged old pin *ahead* of the head (old = seq8
fabricated, candidate = seq9, head = 4, live pin = seq6)
is admitted by my rule too — the verifier has no record
of seq8's hash to check against. That is the FRESH-PIN
residual my design already concedes (§1.1, final
paragraph): the head closes replay and regression
*relative to consumed ceremonies*, not arbitrary caller
claims about the live pin. B is right that old_pin is
ultimately caller-asserted; he is wrong that this makes
the not-behind comparison worthless — it converts an
unbounded restaging (any old pin) into a bounded one
(old pin must be ≥ head), and the bounded remainder is
already a named, shared residual.

### 1.3 The final rule, stated precisely

Let `H = (H_seq, H_hash)` be the candidate of the last
consumption-journal entry; empty journal ⇒ no head, no
check (bootstrap). For an envelope carrying `old_pin`:

| Case | Result |
|---|---|
| `old_seq < H_seq` | **Refuse** — `ceremony_consumption_stale` (A: `ceremony_old_pin_stale`), exit 3 |
| `old_seq == H_seq`, `old_hash == H_hash` | Admit (predecessor is exactly the last consumed target — the normal next ceremony) |
| `old_seq == H_seq`, `old_hash != H_hash` | **Refuse** — fork of the head (a different snapshot at the consumed sequence) |
| `old_seq > H_seq` | Admit (the `advance_pin` case; hash unverifiable verifier-side — FRESH-PIN residual) |
| `old_pin is None` | No old-pin check. Candidate rule still applies in full (`candidate_seq > H_seq`, with the equal-seq fork/same-target refusals all three designs share) |

Plus A's `initial_anchor` refinement, which I **adopt**
over my own text: an `initial_anchor` envelope refuses
whenever the consumption journal is non-empty, even if
its candidate is ahead of the head. Mine admitted it
(candidate rule only); A's is right — a second "initial"
anchor after consumed ceremonies is a false lineage
claim whatever its target, and refusing costs no
legitimate flow (see §1.4).

### 1.4 The backup-restore recovery case — yes, my rule refuses it, and that refusal is correct

Scenario: pin genuinely restored from an old backup at
seq1, after ceremonies already consumed targets at seq4
(head = 4). An old-pin-bearing envelope (`old = seq1`,
candidate ahead) is refused under §1.3. **That is correct
behaviour for this system**, for two reasons:

1. The envelope's claim — "my predecessor is the seq-1
   pin" — is false as a statement about the system's
   lineage. A ceremony at seq4 was consumed, with
   evidence, by this verifier. A re-anchor that silently
   jumps 1 → candidate rewrites that lineage; the
   consumed seq-4 target does not stop having happened
   because the caller lost its copy of the pin.
2. **The recovery path exists and is the honest one:**
   the no-pin reasons. `lost_pin` / `corrupted_pin`
   envelopes carry `old_pin = None` — which is the
   *true* statement about a restored-from-backup pin
   whose continuity is broken — and are admitted under
   §1.3 provided the candidate is ahead of the head.
   The operator's recovery is: new ceremony under
   `lost_pin`, candidate_seq > 4, new evidence bundle.
   What the operator may not do is re-anchor *as if*
   the seq-4 consumption never happened, and the
   not-behind rule is precisely what stops the
   as-if path while leaving the honest path open.

If the war room finds a legitimate flow that *requires*
an old-bearing envelope from behind the head, it has not
been named in any of the three designs; B's M4 cannot
claim it as a casualty of my rule without naming it.

---

## 2. B'S PROTOCOL — body shape conceded to B; response shape and taxonomy settled

### 2.1 Body: B is right, my client text is wrong — CONCEDE

B: body exactly `{"signed_authorisation"}` — the mode
derives old/candidate/everything from the envelope
itself; nothing caller-asserted rides along. My
design-c §2 instead had the client call
`_run("ceremony_consume", {"authorisation": ...})` — a
different key name, chosen by me without a precedent
check. The precedent is against me: `VerifierClient.
ceremony_authorise` already validates its result as
exactly `{"signed_authorisation"}` (trust/client.py,
the `set(result) != {"signed_authorisation"}` check) —
`signed_authorisation` is this codebase's name for the
envelope dict on the wire. **Revision to design-c:
the consume body is exactly `{"signed_authorisation":
<envelope dict>}`, B's §2.2 verbatim.** I also concede
the general principle B states and my one-argument
callable already embodies: A's two-argument callable
(`consume_authorisation(authorisation, new_pin)`) sends
a caller-computed duplicate of the envelope's candidate
toward the consume path. The verifier never sees it
(A's own mode body is envelope-only), so `new_pin` is
dead weight at the seam — and worse, it creates an
unspecified mismatch case (callable receives a `new_pin`
that disagrees with the envelope candidate: refuse?
trust which?). The adapter can derive the candidate
from the envelope it already holds. **A's callable
should drop the second argument; mine (one argument,
the typed envelope) stands.**

### 2.2 Response shape — what the client must verify

With the body carrying only the envelope, the client's
binding checks are entirely on the **response**. The
receipt must let the client confirm the verifier
consumed *the envelope it sent* — not a consumption, not
some envelope. Required response shape (merging B's
§2.7 receipt with A's D5 step-7 response, neither of
which is sufficient alone):

```json
{"authorisation_id": "<echo>",
 "ceremony_id": "<echo>",
 "consumption_seq": <int ≥ 1>,
 "new_pin": {"cycle_seq": <candidate seq>,
             "payload_hash": "<candidate hash>"},
 "consumed_head": {"cycle_seq": <candidate seq>,
                   "payload_hash": "<candidate hash>"},
 "journal_head": "<hex64>"}
```

Client checks, all mandatory, any failure ⇒
`VerifierProtocolError` (a malformed/unbound receipt is
a protocol failure, and the adapter converts it to a
`SigningError` refusal — the envelope is treated as
burned, §3):

1. **Exact key set** — no missing, no extra keys (the
   `ceremony_authorise` result discipline).
2. `authorisation_id` **== the sent envelope's**
   `authorisation_id`. This is the binding that answers
   "did it consume *my* envelope".
3. `ceremony_id` == the sent envelope's.
4. `new_pin` == the sent envelope's candidate projected
   to pin shape.
5. `consumed_head` == the envelope's candidate. This is
   the strongest check available and both A and B
   under-use it: because consumptions are strictly
   increasing, the head *after this append is this
   candidate by construction*. A response whose
   `consumed_head` is anything else did not commit
   this consumption (stale replay of an earlier
   receipt, a racing consumption, a confused verifier)
   and must refuse. (A includes `consumed_head` in its
   response but its client text does not assert it
   against the candidate; B's receipt has
   `consumption_head` as an "audit aid" with no
   asserted equality. Assert it.)
6. `consumption_seq` is an `int` ≥ 1.
7. `journal_head` is hex64 — audit only, not bound to
   anything the client can recompute; its presence
   pins the journal state for later reconciliation.

The receipt stays **unsigned** (B §2.8 is right, and
my design already agreed): a signature would prove
the verifier *said* it consumed, and a replayed
receipt for the same authorisation_id would verify
cleanly. Checks 2–5 are echo/binding checks over the
launch channel, not cryptographic proof, and the
docstring must say so.

### 2.3 Does B's refusal table break the client's error taxonomy? No — B matches the codebase precedent; A is the deviation

`VerifierClient._run` maps mechanically: exit 2 ⇒
`VerifierProtocolError`, exit 3 ⇒ `VerifierConfigError`,
anything else ⇒ `VerifierUnavailable`, timeout ⇒
`VerifierTimeout` (a `VerifierUnavailable` subclass,
trust/errors.py). Nothing in B's table breaks that
mapping — every B code is exit 2 or exit 3 and surfaces
as a named exception, and my adapter converts **any**
`VerifierError` into a `SigningError` refusal, so
`reanchor_pin`'s contract is taxonomy-independent.

More than that: B's controversial-looking choices —
`ceremony_already_consumed`, `ceremony_head_regression`,
`ceremony_not_issued`, `ceremony_authorisation_expired`
all at **exit 3** — follow the existing `ceremony_
authorise` convention in this codebase. The client
docstring for `ceremony_authorise` lists its exit-3
refusals as including *replay* and *evidence reuse* —
state refusals about a specific request, at exit 3,
already. It is **A's** table that deviates: A puts
R1/R2/R3 state refusals at exit 2, which would surface
a replay as `VerifierProtocolError` ("your request was
malformed") — the misleading direction. One genuine
wrinkle in B's table, worth a build-round note rather
than a redesign: exit-3 refusals surface as
`VerifierConfigError`, whose name invites callers to
treat them as deployment faults (alert-the-operator)
rather than ceremony refusals (start-a-new-ceremony).
The consume adapter's docstring must state explicitly
that for this mode, `VerifierConfigError` carries the
state refusals and the correct operator response is a
new ceremony, not a config fix. With that sentence,
**B's table ships as-is.**

---

## 3. CRASH BOUNDARIES — B's K1–K6 cover the verifier side; the decisive test is mine, and one boundary is unowned by all three

### 3.1 My crash table, stated in full (see §0 for why it is stated here first)

| # | Crash point | Consumption state | Pin state | Recovery |
|---|---|---|---|---|
| C-a | Before the verifier's journal commit | Not consumed | Unmoved | Retry the same envelope |
| C-b | During the journal write | Old journal **or** new journal, never torn (`HashChainJournal._save`: tmp + fsync + `os.replace` + dir fsync) | Unmoved | Re-read decides: retry (C-a) or refuse already-consumed (C-c) |
| C-c | **After the consume commit, before `reanchor_pin` returns** (response lost, client timeout, adapter raises) | **Consumed (burned)** | **Unmoved** | **No retry with this envelope. New ceremony_id + new evidence bundle.** |
| C-d | After `reanchor_pin` returns, before the caller adopts pin+record | Consumed (burned) | Unmoved | New ceremony (the ATOMIC-ADOPTION failure mode, now safe: adoption failure can no longer enable replay) |
| C-e | Any local refusal before the consume call | Not consumed — callable invoked **zero** times | Unmoved | Fix the cause, retry the same envelope |

### 3.2 What B's K1–K6 do and do not cover

- **K1** (wrapper patches `append_consumption` to
  `os._exit(70)` before the real append) covers **C-a**
  at the verifier. ✓
- **K2** (append, then `_exit` before `_emit`) covers
  the verifier half of **C-c**: journal committed,
  receipt never sent, retry refuses
  `ceremony_already_consumed`. ✓ — but only the
  verifier half.
- **K3** (response lost; retry; assert already-consumed
  and, at integration level, pin does not move) is the
  closest B comes to C-c's caller half.
- **K4** covers corrupt/deleted journal (C-b's load
  side, plus the mirror backstop). **K5** covers the
  concurrent double-consume race. **K6** covers
  commit→mirror failure (a boundary my design's mirror
  shares with B's dual append).
- **No K test covers C-d** (crash after `reanchor_pin`
  *returns*, before adoption). B §4.1 G3 lists the
  state in prose; no kill point exercises the caller
  there. A lists the same boundary as its T20 third
  case. It needs a caller-side kill test, not a
  verifier wrapper. **Unowned — I take it** (below).

The wrapper-module `os._exit` technique itself is
sound and I adopt it over any env fault hook: it adds
zero production surface (consistent with the zero-new-
env-vars convergence), it kills at exactly the patched
point rather than at a hook the production code must
cooperate with, and it follows the `test_trust_
crashlab.py` precedent A cites. No objection.

### 3.3 The test B cannot own, stated precisely — seat C owns it

B's architecture is caller-orchestrated consume
(§2.7: consume *before* `reanchor_pin`), so in B's
world there is no moment at which a consumer raises
*inside* `reanchor_pin` after the verifier committed.
That moment exists only in the callable integration
(A's and mine). The test that proves the C-c contract
at the seam where it can actually fail is therefore
**mine**:

> **T-Cc (test_signing_pin_ceremony.py).** Install a
> fake `consume_authorisation` that (i) records the
> envelope's `authorisation_id` in a fake consumed set
> — simulating the verifier's durable commit — and
> then (ii) **raises** `SigningError("verifier timeout
> after commit")`, simulating the lost response.
> Assert: (1) `reanchor_pin` raises `SigningError` and
> **returns nothing** — no `(new_pin, record)` tuple
> exists to adopt (assert on the exception, and assert
> the caller's pin variable is untouched); (2) a
> second `reanchor_pin` attempt with the same envelope
> and the same fake now refuses `already consumed`
> from the fake's set — the envelope is burned, the
> pin never moved, and no code path converts the
> ambiguous first failure into a success on retry;
> (3) the fake recorded **exactly one** commit across
> both attempts (the second attempt's refusal happens
> at the consume call, not before it — `reanchor_pin`
> does not cache, pre-check, or retry around the
> callable).

And the caller-side companion I take from §3.2:

> **T-Cd.** Drive the integrated path with the
> verifier-backed callable; kill the *caller* process
> after `reanchor_pin` returns and before adoption
> (wrapper around the adoption step, `os._exit`).
> Assert on restart: the envelope refuses
> already-consumed, the on-disk pin is the pre-ceremony
> pin, and a fresh ceremony (new ceremony_id, candidate
> ahead of the head) succeeds — C-d's recovery, proven,
> not just tabulated.

### 3.4 A structural attack on B's ordering that B must answer

B's §2.7/§4.2 protocol consumes **before** the local
`reanchor_pin` runs. Every local refusal — binding
mismatch, failed bare-verifier attestation, history
refusal, strict-recomputation failure — therefore
**burns the envelope** under B's ordering: the consume
committed, then the local check refused, and recovery
is a whole new ceremony with new evidence. That
violates A's contract clause (d) ("consumption is
never recorded for a refused ceremony") and my C-e,
both of which are achievable *by construction* in the
callable design (consume is the last fallible step;
zero calls on any local refusal — a spy-consumer test
pins it). B's ordering buys nothing for this cost:
his own §4.2 rule "never adopt on a refusal" already
requires the caller to run the local checks and honour
their result, so moving the consume call to after
those checks — i.e. inside `reanchor_pin`, i.e. the
callable — changes no safety property and eliminates
the burn-on-local-refusal class entirely. **B should
concede the integration point to the callable design**
(his §7.2 already half-concedes it: his guarantee
needs the caller to follow a contract the type system
does not enforce; the required keyword enforces the
one part that can be enforced — that consumption is
consulted at all, exactly once, at the pinned point).

---

## 4. A'S SEED LOADER — shared helper: CONCEDE on mode parity; HOLD on the uid check's scope

A applies one predicate — mode ∈ {0400, 0600}, via a
shared `_check_owner_only_mode` helper — to **both**
`load_ceremony_seed` and `gate_decision.load_signing_
key`. My design scoped hygiene to the ceremony loader
and deferred gate parity to a follow-up. I checked the
tests before answering:

**What the existing tests actually pin (verified this
round):**

- `tests/test_signing_ceremony_authorisation.py`: a
  seed at **0644 refuses** (chmod 0644 case); generated
  seed files are asserted 0600. No test asserts that
  0400 refuses for either loader.
- `tests/test_signing_gate_decision.py`: the only mode
  assertions are that `generate_key_file` *creates*
  0600. **No test pins an exactly-0600 refusal for
  `load_signing_key`** — the exactly-0600 contract for
  the gate key lives only in `load_signing_key`'s
  docstring and its `st_mode & 0o777 != 0o600` check
  (signing/gate_decision.py:297–298).
- The two loaders already share discipline: the
  ceremony loader's docstring notes `_check_key_path`
  is shared with `gate_decision.load_signing_key`
  (signing/ceremony_authorisation.py:261). Parity is
  the existing direction of the codebase, not A's
  invention.

**Concession:** A's shared-helper approach breaks **no
existing test**, and my "gate parity as follow-up" was
the weaker position — two loaders guarding two secrets
of the same system, sharing a path checker but not a
mode predicate, is exactly the drift surface I accused
other designs of creating. A 0400 gate key is not a
deploy contract anyone is relying on (the *deploy*
ceremony generates 0600 and nothing in the tests or
the health check requires refusing 0400). **Ship the
shared mode helper in this cycle, both loaders,
{0400, 0600}, with A's deliberate test updates** (0400
accepted for both, pinned — a behaviour change
recorded, not discovered). B's exactly-0600 position
loses on the same evidence: his strongest argument was
"established discipline shared with load_signing_key",
but that discipline turns out to be one docstring and
one comparison, not a tested contract, and his
0200-write-only objection is already handled by A's
predicate requiring the owner-read bit.

**Hold (one scoping point against A):** A's
`st_uid == os.geteuid()` check must **not** ride along
into the gate loader via the shared helper this cycle.
The mode predicate is the shared part; the uid check
is a separate, stricter claim, and the gate key has a
reader the seed does not: `deploy/verifier-identity/
health_check.py` loads the signing key through
`load_signing_key` (health_check.py:654–660) as a
diagnostic, in a process whose euid is a deployment
choice, not a ceremony invariant. A uid mismatch there
converts a health check into a hard failure for a
reason unrelated to the key's safety. A also specifies
the uid check with **no root carve-out**; B's version
(`geteuid() == 0` skips) is the safer form. **Ruling I
propose: uid == euid ships for `load_ceremony_seed`
only, with B's root carve-out recorded in the
docstring; gate-loader uid is a named follow-up, to be
decided with the health check's execution identity in
view.** A's Q3 (research-mode uid strictness) is
answered the same way: keep it for the seed, where the
verifier's dedicated OS user is the whole point.

A's fd discipline itself (`O_NOFOLLOW | O_NONBLOCK`,
fstat `S_ISREG`, bounded fd read) I adopt without
amendment — it is the cycle-20 evidence-walk lesson
applied to the seed path, and B converged on the same
rework independently.

---

## 5. DERIVATION SETS — ship the union, minus one dead relation (A's R4)

The two sets, over `seed` (ceremony seed bytes), `key`
(snapshot HMAC key bytes), `pub = public_key_from_seed
(seed)`:

| Relation | A | B | Verdict |
|---|---|---|---|
| `seed == key` | R1 (existing) | (existing) | Ship (already in `_load_config`) |
| `sha256(seed) == key` | R2 | R1 | Ship |
| `sha256(key) == seed` | R3 | R2 | Ship |
| `key == pub` (HMAC key reused **as** the ceremony public key bytes) | — | **R3** | **Ship — B's best catch of the round** |
| `seed == sha256(pub)` | — | R4 | Ship (cheap; closes the self-derivation loop) |
| `seed ∈ _REFUSED_TEST_KEYS` | R4 | — | **DROP — dead code (proof below)** |
| `key ∈ REFUSED_TEST_SEEDS` | R5 | explicitly rejected | **Ship — partially live (proof below); B's dismissal is wrong** |

**B's R3 is the most dangerous relation in either set
and A (and I) missed it.** The ceremony public key is
*public material* — pinned by every ceremony caller,
printed in pins. If those 32 bytes are also the HMAC
signing key, every gate signature is forgeable by
anyone holding the pin. It is not a derivation, it is
a public/secret boundary crossing, and it is the
easiest relation to commit by accident (copy the
public key into the key file). Any set without it is
incomplete in the place it matters most. **Concede
to B; R3 ships.**

**A's R4 is dead code — proof from the lists
themselves.** `trust/verifier_main.py` defines
`_REFUSED_TEST_KEYS = (bytes(range(32)), bytes(range
(32,64)), b"\x00"*32, b"\xff"*32)`. `signing/
ceremony_authorisation.py`'s `REFUSED_TEST_SEEDS`
contains **those same four values plus** the three
RFC 8032 TEST 1–3 seeds. And `_load_config` already
refuses any seed in `REFUSED_TEST_SEEDS`
(verifier_main.py, the `seed_bytes in
_REFUSED_TEST_SEEDS` check). Therefore every value
A's R4 would catch is already refused by the existing
check: R4 can never be the relation that fires. It is
not defence in depth, it is a subset wearing a second
name, and keeping it would let a future reader believe
cross-membership is covered in both directions when
only one direction is. **Drop R4; the docstring should
state the subset fact instead.**

**A's R5 is partially live — B's "kept separate, as
now" dismissal is wrong for the same list-arithmetic
reason.** `key ∈ REFUSED_TEST_SEEDS`: the four shared
values are already refused for the key (they are in
`_REFUSED_TEST_KEYS`), but the three **RFC 8032 vector
seeds are in `REFUSED_TEST_SEEDS` only**. An HMAC key
provisioned equal to the RFC TEST 1 seed — public
knowledge, pinned in our own test file — passes every
current `_load_config` check. R5 catches exactly those
three values and nothing else; narrow, but they are
the worst three values a key could take. **Ship R5,
with the docstring naming its effective coverage (the
RFC vector seeds), so nobody over-claims it.**

**Final set to ship:** existing `seed == key`; both
sha256 directions; B's `key == pub`; B's `seed ==
sha256(pub)`; A's R5 (key ∈ REFUSED_TEST_SEEDS,
coverage annotated). All in `_load_config` only, via
a unit-testable helper (A's `_check_seed_key_
separation` shape — B computes inline; the helper is
better, because the R-tests need a seam that does not
boot a verifier). Both designs' stated limit stands
and must be in the docstring: no finite relation list
detects an arbitrary KDF overlap; provisioning
discipline (independent random draws) is the real
defence.

---

## 6. A'S OPENSSL ORACLE — bucket discipline has two holes; one is empirical, found this round

A's design: openssl-signs direction asserted
**byte-identical**; verification direction bucketed
AGREE-REJECT / AGREE-ACCEPT / DIVERGE-EXPECTED, with
DIVERGE-EXPECTED asserting *our* rejection plus the
openssl outcome being "in the allowed set (accept or
reject)". I probed openssl 3.0.13 on this VM this
round (RFC 8032 TEST 1/2 literals, DER SPKI wrapping
per A's prefixes). Findings:

### 6.1 S+L malleation: openssl REJECTS — AGREE-REJECT, and A's table invites the wrong bucket

For TEST 2's valid signature with `S` replaced by
`S + L`: **openssl exits 1 (reject)**; our verifier
also rejects (step 4). So S+L is **AGREE-REJECT**, full
agreement, real differential signal. The risk is in
A's framing: A2 lists "S+L malleation of a valid
signature" inside the S-boundary group without a
predicted bucket, and the surrounding text primes the
reader to expect ZIP-215-style leniency from openssl
on S. A build-round author who pre-buckets S+L as
DIVERGE-EXPECTED — plausible, given that priming —
creates the hole in §6.3. **The build must bucket
from measured openssl output, case by case, and the
S+L case must land in AGREE-REJECT; if it lands
anywhere else, that is a finding about the test, not
a reclassification.**

### 6.2 Non-canonical / small-order A: openssl ACCEPTS — DIVERGE-EXPECTED is real, and it is wider than A predicts

Two measured acceptances (openssl exit 0), both
rejected by our strict verifier:

- **A = identity, canonical encoding, R = identity,
  S = 0** (equation holds trivially: `[0]B = I`,
  `R + [k]A = I`): openssl **accepts**. Our verifier
  rejects at the small-order blocklist (step 3).
- **A = identity under its non-canonical spelling**
  (y = 1 + q, sign 0), same R/S: openssl **accepts** —
  i.e. openssl's A-decode is ZIP-215-lenient
  (non-canonical y reduced mod q), exactly the
  leniency A hypothesised. Our verifier rejects at
  canonical decode (step 2).

And one measured rejection, for calibration: the same
non-canonical spelling applied to **R** (R = identity
spelled y = 1 + q, A = identity canonical, S = 0):
openssl **rejects**. The leniency is asymmetric —
A-side lenient, R-side strict in this construction —
which no amount of reading A's buckets would have
predicted. This is the differential suite working as
intended, and it cuts both ways: **bucket assignments
made at design time (mine included) are hypotheses;
the suite must record measured outcomes and fail on
unpredicted ones, per-case, not per-group.**

### 6.3 Can a genuine in-house bug hide inside DIVERGE-EXPECTED? Yes — one specific shape

A's DIVERGE-EXPECTED assertion, as written, is: *we
reject* + *openssl's outcome ∈ {accept, reject}*.
The openssl half of that assertion is **vacuous** — a
set containing both outcomes excludes nothing. So for
every DIVERGE-EXPECTED case, the entire differential
signal reduces to "we reject", which is asserted by
the in-house A2 table anyway. Concretely, the hiding
shape: suppose a future (or present) bug makes our
verifier **accept** small-order or non-canonical A.
Under §6.2, openssl accepts those too — so the case
presents as "both accept", and if the build round
re-buckets it (A forbids *silent* re-bucketing, but
the failure mode is a *reasoned* one: "openssl agrees
with us, so AGREE-ACCEPT") the bug is not merely
hidden, it is **ratified by the independent oracle**.
A's own guard — "any case other than the valid
signatures and the S = L−1 construction landing in
AGREE-ACCEPT is a test failure" — is the only thing
standing in that path, and it is a prose rule in the
design, not a mechanism in the suite.

**Fix I require (applies to B's partitioned oracle
identically — B's KNOWN-DIVERGENCE set has the same
vacuity, asserting only our rejection with openssl's
answer "recorded"):** the bucket table must be a
**literal, pinned expectation per case** — `(our:
reject, openssl: accept)` as data, asserted in full —
so that *either* side changing its answer fails the
test. DIVERGE-EXPECTED then means "this exact pair of
outcomes, measured and pinned at build, reviewed by
the war room", and a change in our verifier's answer
on a divergence case is a test failure that no
re-bucketing can absorb without a war-room-visible
diff to the pinned table. With that change, the
bucket discipline catches in-house bugs; without it,
it catches only bugs on the AGREE-* side.

Two smaller A-oracle defects, both from the probe:

- **Empty message breaks the openssl harness, not
  the signature.** `openssl pkeyutl -verify` on a
  0-byte message file fails with "Could not allocate
  0 bytes for oneshot sign/verify buffer" (exit 1) —
  a tooling failure that presents exactly like a
  verification rejection. A's corpus includes the
  empty-message edge and TEST 1 (empty message) in
  the openssl directions; naively driven, every
  empty-message case would be misread as AGREE-REJECT
  or as an openssl failure. The suite must special-
  case it: assert the stderr pattern for the 0-byte
  tooling failure and mark the openssl direction
  *not-run* for empty messages (our in-house
  empty-message cases still run), or drive openssl
  via a non-`pkeyutl` path. B's corpus has the same
  exposure ("RFC vectors, all").
- **A's A2 header contradicts its own bucket text.**
  A2 states every adversarial case asserts `verify
  is False`, then the bucket section allows the
  S = L−1 equation-satisfying construction into
  AGREE-ACCEPT. Both cannot hold for the same case:
  an S = L−1 signature whose equation genuinely
  satisfies (with a non-blocklisted R) is a *valid*
  signature under our profile and our verifier
  accepts it. The table must split it out as its own
  row (expected: accept, by construction, with the
  constructing equation stated — the cycle-20 F3
  discipline), not sit inside an "all REJECT" group
  with an asterisk in a later section.

The byte-identical assertion for the openssl **sign**
direction I endorse without amendment — it is the
strongest claim in either workstream-A design, and
B converged on it (byte-equality, not mere verify-
agreement, on the valid corpus).

---

## 7. THE CLAIM WORDING — my no-op callable is the weakest point; here is the sentence all three seats can sign

B presses the objection (§7.2) and he is right to:
`reanchor_pin` with a no-op `consume_authorisation`
callable is exactly as replayable as cycle 20. A
presses it too, in different words (his guarantee
runs through "the production callable"). **All three
designs place the guarantee in the wiring, none in
the library function** — B's caller contract, A's
adapter, my callable are the same shape: a caller
who does not install the verifier-backed consume
gets no protection, and no design in this round can
change that without moving `reanchor_pin` behind the
verifier (B's option (b), correctly out of scope).
The difference the callable makes — and it is the
only difference, but it is real — is that omission
is *loud*: a missing keyword is a `TypeError`, an
explicit `None` is a refusal, whereas B's orchestration
omission is silent (the caller simply never calls
consume, and nothing anywhere notices). The claim
must therefore be scoped to the integrated path,
must name the wiring, and must state the library-
level non-guarantee in the same breath. Exact wording
I propose all three seats sign, for the `reanchor_
pin` docstring, the verifier module docstring, and
BUILD-CYCLE-21:

> **Cycle 21's guarantee.** For a ceremony performed
> through the integrated production path — the
> envelope obtained via `VerifierClient.ceremony_
> authorise`, and `reanchor_pin` invoked with the
> verifier-backed `consume_authorisation` callable
> supplied by `trust/client.py`'s adapter, with the
> returned pin and record adopted atomically — cycle
> 21 guarantees: (1) each `authorisation_id` is
> consumed at most once, regardless of the
> `ceremony_history` supplied (stale, empty, or
> complete); (2) no candidate at or behind the
> verifier's consumed head is consumed, and no
> envelope whose `old_pin` is behind that head is
> consumed; (3) `reanchor_pin` returns a pin only
> after the consumption has been durably committed
> in the verifier's consumption journal — a crash
> after that commit leaves the envelope burned and
> the pin unmoved, and recovery is a new ceremony.
> **This is a property of the integrated path, not
> of `reanchor_pin` in the abstract.** A caller that
> invokes `reanchor_pin` with any other callable —
> including a no-op — or that does not adopt its
> result atomically, receives no consumption
> guarantee; for such a caller the function's
> behaviour is cycle 20's, including the stale-
> history replay pinned by the original T7/T8. The
> guarantee is pinned executably at the integrated
> level (the flipped T7′/T8′ and the end-to-end
> consume suite driving the real client and
> verifier), not by unit tests of `reanchor_pin`
> with fake consumers, which pin only the seam
> (required keyword, single invocation, no return
> on consumer failure).

That wording meets seat-gpt's "integrated system"
standard — his FIX was always stated against the
integrated system (T7/T8 as the *system's* behaviour)
— without claiming a library property none of us
built. If any seat cannot sign the second paragraph,
that seat is claiming more than its design delivers,
and the disagreement should be recorded rather than
the paragraph softened.

---

## Concessions and holds

**Concessions (revisions to design-c):**

1. **Protocol body key (§2.1):** my client's
   `{"authorisation": ...}` is wrong; B's
   `{"signed_authorisation"}` ships, per the
   `ceremony_authorise` wire precedent.
2. **A's callable signature (§2.1):** not a concession
   *by* me but a revision I join against A — the
   `new_pin` second argument should be dropped;
   my one-argument callable stands.
3. **`initial_anchor` (§1.3):** A's non-empty-journal
   refusal adopted over my candidate-only rule.
4. **Response binding (§2.2):** `consumed_head` must
   be asserted equal to the sent candidate — stronger
   than my design-c receipt checks (which echoed
   authorisation/candidate/seq but did not bind the
   head). Adopted from A's response shape, asserted
   harder than A asserts it.
5. **Gate-loader parity (§4):** A's shared
   {0400, 0600} mode helper applies to
   `load_signing_key` in this cycle; my
   ceremony-only scoping with parity-as-follow-up is
   withdrawn. No existing test breaks (verified).
6. **Derivation set (§5):** B's `key == pub` and
   `seed == sha256(pub)` relations adopted — my set
   (and A's) missed the round's most dangerous
   relation.
7. **Oracle buckets (§6.3):** the vacuity defect is
   in the bucket *idea* my design shared with A and
   B; pinned per-case `(ours, openssl)` expectation
   pairs replace allowed-set assertions in my
   workstream-A position too.
8. **Artefact (§0):** design-c.md is truncated on
   disk at §2; §§3–8 positions exist only as summary
   lines plus the restatements in this critique.

**Holds (positions I defend against A and/or B):**

1. **Not-behind head rule for `old_pin` (§1):** held
   against B's M4. B's worked case is admitted by my
   rule; the fresh-envelope restaged-old-pin case
   (old 1 / cand 5 / head 4 / live 6) is a regression
   under M4 and a refusal under mine. Final rule
   table in §1.3, including `old_pin = None` (no
   check, candidate rule in full) and the
   backup-restore case (refusal correct; recovery is
   a no-pin `lost_pin` ceremony ahead of the head).
2. **Consume inside `reanchor_pin`, last fallible
   step (§3.4):** held against B's consume-before-
   reanchor orchestration, which burns envelopes on
   purely local refusals. Zero consume calls on any
   local refusal is a property worth the seam.
3. **B's exit-code table (§2.3):** held *for* B
   against A's deviation — exit-3 state refusals
   match the `ceremony_authorise` precedent in
   client.py; nothing in B's table breaks `_run`'s
   taxonomy.
4. **Uid check scope (§4):** held against A's
   shared-helper maximalism — `st_uid == euid`
   ships for the ceremony seed only, with B's root
   carve-out; the gate loader's uid check is a
   follow-up, because `health_check.py` is a second,
   differently-identified reader of the gate key.
5. **A's R4 is dead code (§5):** held against A —
   `_REFUSED_TEST_KEYS ⊊ REFUSED_TEST_SEEDS` and the
   superset check already fires in `_load_config`;
   R4 can never be the catching relation. Conversely
   held *for* A's R5 against B's dismissal: it is
   live for exactly the three RFC vector seeds.
6. **Crash-test ownership (§3.3):** B's K1–K6 cover
   the verifier-side boundaries (C-a, C-b, the
   verifier half of C-c, mirror, race) and the
   `os._exit` wrapper technique is adopted; the
   reanchor-returns-nothing test (T-Cc) and the
   caller-kill-after-return test (T-Cd, boundary
   C-d, unowned by all three designs) are seat C's,
   stated precisely in §3.3.
7. **Claim scope (§7):** the guarantee is the
   integrated path's, stated in the signed wording
   in §7 — including the no-op-callable non-guarantee
   in the same paragraph, not a footnote.
