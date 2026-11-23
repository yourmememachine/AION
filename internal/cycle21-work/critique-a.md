# CRITIQUE A — Cycle 21 cross-critique round (seat A on designs B and C, and on design-a)

Seat A. Design only — no code edited. I re-read design-a,
design-b and design-c in full, and re-checked every contested
claim against the code (`signing/gate_decision.py`,
`signing/ceremony_authorisation.py`, `signing/pin_ceremony.py`,
`trust/ledger.py`, `trust/protocol.py`, `trust/client.py`,
`tests/test_signing_pin_ceremony.py`,
`tests/test_signing_ceremony_authorisation.py`,
`tests/test_signing_gate_decision.py`,
`tests/test_trust_identity.py`, `deploy/verifier-identity/`,
`internal/BUILD-CYCLE-20.md`, `internal/CROSS-CHECK-14.md`).

**Procedural finding first, because it bounds everything
below about C:** `internal/cycle21-work/design-c.md` as it
exists on disk is **truncated**. The file ends mid-sentence
in §2 (the `VerifierClient.ceremony_consume` bullet, at
"exit-2 →"), followed by a literal `...[truncated 15821
chars]` marker as the file's final bytes. C's §§3–8 — crash
contract, T7′/T8′ shapes, workstream-A position, the §7
mirror design, the §8 receipt-binding discussion — are not
in the file. My critique of C beyond §2 therefore rests on
§§0–2 as written plus the coordinator's summary of C's
positions (ceremony-only loader scope, old-pin-not-behind-
head, dual-append mirror, fresh-consumer helper). **C must
re-deliver the complete file before the build round**; a
design the room cannot read in full cannot be ratified in
full, and if the missing sections contradict the summary,
§§3–4 of this critique reopen.

Convergence recorded, not re-litigated: verifier-owned
`CeremonyConsumptionLedger` (`ceremony-consumptions.json`
under `AION_VERIFIER_HOME`), new `ceremony_consume` mode,
zero new env vars, required consume callable in
`reanchor_pin`. Where B or C beat me below, I concede;
where I hold, I give the code evidence.

---

## 1. Seed permissions — I HOLD {0400, 0600}; B's objection is taste, not a repo dependency

B keeps exactly-0600 and proposes a test pinning that 0400
refuses. I checked for any dependency on that refusal:

- **No test pins it.** The ceremony-loader test
  (`test_signing_ceremony_authorisation.py`,
  `test_seed_file_round_trip_and_refusals`) refuses **0644**
  only. The signing-key tests refuse 0644
  (`test_signing_gate_decision.py`,
  `test_load_refuses_broad_permissions`) and 0000
  (`test_trust_identity.py`,
  `test_load_signing_key_refuses_0000_key`). No test
  anywhere chmods 0400 and expects refusal. B's "pinned by
  test" is a test B proposes to *write*, not one that
  exists — a decision looking for a pin, not a pin
  recording a dependency.
- **No deployment depends on it.** Both generators create
  0600 (`gate_decision.py:272`, `ceremony_authorisation.py`
  `os.open(..., 0o600)`), and 0600 remains acceptable under
  my predicate, so generation is untouched.
  `deploy/verifier-identity/setup.sh` chmods 0600 the *env
  file* — a different file, not a key loader input. The
  deploy README (line 19) says `gate.key` is "itself
  exactly 0600 — `load_signing_key` refuses any other
  mode": that is documentation *of* current behaviour, not
  a flow that chmods 0400 and relies on being refused.
  Nothing provisions 0400 today, and nothing breaks if
  0400 becomes acceptable tomorrow.
- **The task text rules against B.** The coordinator's
  task text says "owner-only permissions (0600 or
  stricter)". 0400 is stricter than 0600 on every axis
  (no group/other bits, no owner write). Refusing the
  stricter mode while claiming "0600 or stricter" is a
  contradiction B does not address; CROSS-CHECK-14's
  shorthand "(0600, fail closed)" names the *generated*
  mode and the fail-closed posture, not a refusal of
  read-only files.
- **B's three reasons do not survive contact.** (1) "Two
  sibling loaders, two policies is drift" — my design
  applies the *same* predicate to both loaders via one
  helper (§2 below); there is no inter-loader drift in
  either design, so this argues only against a
  ceremony-only relaxation nobody proposed. (2) "The
  directory discipline discharges 'or stricter'" — the
  0700 directory and `_check_key_path`'s parent check
  (`gate_decision.py:248`, refuses group/world-writable
  parent) govern *other principals' write access to the
  directory*; they say nothing about whether the file
  itself may be read-only. Different property. (3) "Any
  owner-only mode would accept write-only 0200" — a straw
  set. My predicate is exactly {0400, 0600}: it requires
  the owner-read bit (`mode & 0o400 != 0`) and excludes
  owner-execute, so 0200 and 0000 refuse as *permission*
  refusals. B argues against "any owner-only mode"; that
  is not my proposal.

**One genuine concession to B in this section:** his
`geteuid() == 0` carve-out on the `st_uid == euid` check.
Design-a has the uid check with no carve-out; the deploy
health check runs privileged and loads the signing key
(`deploy/verifier-identity/health_check.py:654-665`), and
a root-run loader refusing a correctly provisioned file
is a false refusal with no security content (root reads
the file regardless of mode or owner). I adopt B's
carve-out, recorded in the docstring as he specifies.

**Ruling: {0400, 0600} stands, for both loaders (§2).
Generation stays 0600. B's exactly-0600 is provisioning
uniformity — a legitimate preference, honestly labelled
as such in his §6.2, but it is not a security property
and must not be pinned as one.**

## 2. Loader scope — I HOLD both loaders; it is the same hygiene item, and widening `load_signing_key` breaks nothing

The two loaders are line-for-line the same discipline:
`_check_key_path` is already shared, and the mode line is
duplicated verbatim — `gate_decision.py:297`
(`st_mode & 0o777 != 0o600`) and
`ceremony_authorisation.py:269` (same expression). Gemini's
item names the seed file, but the *defect class* — stat-
then-read TOCTOU, path-based `is_file`, exactly-0600 — is
in the shared pattern, not in one file. Hardening one
copy and leaving the identical copy as a "follow-up" is
how this codebase got a FIFO hang fixed in the evidence
walk (cycle 20) while the same hang sat in the seed
loader until this cycle. C's ceremony-only scope repeats
that pattern; B at least names `load_signing_key` as a
follow-up, but a follow-up for an identical, already-
designed, already-tested-in-one-place change is scope
*deferral*, not scope discipline.

What actually breaks if `load_signing_key`'s semantics
widen to {0400, 0600} — I enumerated its callers:

- `trust/verifier_main.py:521` (`_load_config`, the gate
  key) and `deploy/verifier-identity/health_check.py:660`:
  both load operator-provisioned 0600 files; a superset
  acceptance cannot refuse anything they load today.
- Every test fixture loads files created by
  `generate_key_file` (0600) or explicitly chmodded 0600
  (`test_signing_gate_decision.py:158,686`,
  `test_trust_identity.py` setUp). Widening is acceptance-
  monotonic: **no existing passing load can fail.**
- The only casualties are documentary: deploy README
  line 19's "refuses any other mode" sentence must be
  rewritten, and the new semantics must be pinned by the
  permission matrix in `test_signing_gate_decision.py`
  (design-a already lists this). That is a doc edit, not
  a break.

B's counter — the HMAC loader "is shared by every gate
path and its change surface is larger" — is true of the
*fd rework's blast radius* and false of the *predicate*.
**Split ruling I now adopt (a refinement of design-a,
borrowing B's caution without his deferral):** the mode
predicate widens in both loaders this cycle through the
one shared helper, with the full matrix pinned for both;
the fd rework lands for both loaders in this cycle too,
but as a separate commit for `load_signing_key` with its
own test pass, so a regression in the gate path is
bisectable to the signing-key commit and not entangled
with the ceremony work. Ceremony-only as the *final*
state of the cycle: rejected.

## 3. The head rule for `old_pin` — I CONCEDE R3 as a verifier-side refusal; B's M4 wins, with one case split out

The concrete case the room posed: head target = seq 4;
a **fresh** envelope, `old_pin` = seq 1, candidate = seq 9.

- Design-a R3: refuse (`old_pin.cycle_seq < H_seq`,
  `ceremony_old_pin_stale`).
- C §1.1: refuse (`old_cycle_seq > head_seq` required, or
  `==` with same hash; 1 satisfies neither →
  `ceremony_consumption_stale`).
- B M4: **admit** — candidate 9 > head 4; `old_pin` plays
  no role.

Trace it through `reanchor_pin` on the caller side.
Step (4) exact binding (`pin_ceremony.py`, env_old_pin vs
the captured caller argument) means the caller must
present the seq-1 pin dict as `old_pin`. When is that
presentation legitimate, given a head of 4?

**Legitimate — and it is the case that breaks R3.** A
consumption reached seq 4 and the caller crashed after
the verifier commit but before adopting the pin: burned-
but-unmoved, the crash state *all three designs*
prescribe, whose stated recovery is "a new ceremony_id
with a new evidence bundle". That caller's live pin is
truthfully seq 1. Its recovery envelope is necessarily
bound to old_pin seq 1, with a candidate ahead of the
head (seq 9 here). R3 (mine) and C's rule refuse exactly
this envelope. The caller's remaining options are to
fabricate a seq-4 pin dict it never adopted — a direct
violation of the FRESH-PIN precondition the whole
ceremony rests on, and one the strict recomputation
(step (7), against the captured pin) is not designed to
bless — or to be permanently stuck. **A head rule that
makes the prescribed crash recovery impossible, and
whose only workaround is lying about the live pin, is
wrong.** B's parallel-issuance case (two envelopes minted
from seq 1, candidates 4 and 9, consumed in that order)
is the same shape in milder form: issuance legitimately
precedes consumption, so a truthful old pin can be behind
the head through no restaging at all.

**Illegitimate — the case R3 was built for.** Live pin
silently advanced to seq 6 by `advance_pin`; a restaged
envelope bound to seq 1 with candidate seq 5 (> head 4,
< live 6) would pass B's M3 and return a regressed pin.
But note: design-a's own §D3 honest-limit paragraph
already concedes this exact class — fresh envelope,
candidate behind the live pin but ahead of the ceremony
head — as **not closed by this cycle**, because no layer
can see the live pin. R3 does not close it either (it
fires only when old_pin is behind the head; a restaged
envelope bound to old_pin seq 4, candidate 5, sails past
R3 while the live pin sits at 6). R3 thus buys a partial,
easily-routed-around slice of a class I elsewhere
concede is unclosable this cycle, at the price of
breaking crash recovery. That is an inconsistency inside
design-a, and B found its edge. **I concede R3 as a
refusal rule.**

**Precise ruling (replacing R3):**

- Verifier head rule = B's M1 + M3 only: `authorisation_id`
  single-use; candidate strictly ahead of the head
  (`> H_seq`; `== H_seq` refuses for both hash-equal —
  replayed target under a fresh id — and hash-different —
  fork at the head). Design-a's R2 already agreed with M3
  including the equal cases; that part holds.
- `old_pin` is **recorded, never consulted** by the head
  rule (B's entry-shape position: audit field, not a
  check input). Detection of restaging stays where the
  code actually puts it: `reanchor_pin`'s binding of the
  envelope to the caller-presented pin, the candidate-
  relation refusals, and the strict recomputation — all
  caller-side, all honestly bounded by FRESH-PIN.
- `old_pin == head`, hash equal: admit (the ordinary
  sequential ceremony; all three designs agree).
- `old_pin == head`, hash different: this is the one
  sub-case where I do not follow B all the way in spirit,
  though I accept his rule. A forked old pin *at* the head
  sequence is not explicable by crash recovery or
  parallel issuance (both produce old < head), so a
  refusal here would break no legitimate flow I can
  construct. But it also protects nothing the local layer
  doesn't: the candidate must still be > head, and
  `reanchor_pin` judges the candidate against the
  presented pin. **Ruling: no verifier refusal (M4 pure),
  for rule simplicity — "consumed targets strictly
  increase; old_pin is not a head input" must stay a
  one-sentence rule — with the fork-at-head old pin
  visible in the consumption entry for audit.** If the
  room wants the equal-seq/different-hash old-pin refusal
  as belt-and-braces, it is the only old-pin refusal that
  survives scrutiny, and I will not block it; I withdraw
  only the `< H_seq` leg, unconditionally.
- `old_pin is None`: no old-pin check is possible and
  none of the three designs invents one — a missing pin
  cannot be stale. Candidate rule applies alone (B's M5,
  my R3 no-pin clause, C's explicit candidate check all
  converge). Design-a's extra clause — `initial_anchor`
  refuses whenever the journal is non-empty — I **hold**
  against B's M5 reason-blindness: `initial_anchor`
  *asserts* no prior ceremony exists; a non-empty
  consumption journal is verifier-side proof the
  assertion is false, independent of where the candidate
  sits. B's counter-case does not exist: there is no
  legitimate second initial anchor ahead of the head,
  because the reason's meaning, not its target, is what
  refuses. This is a reason-semantics check (the local
  layer already refuses `initial_anchor` on a non-empty
  *history*, cycle-20 T4 leg 1); extending it to the
  authoritative journal is the head doing its job.

## 4. The signing-ledger mirror — I CONCEDE it; it is not the half-measure design-a rejected, and design-a's D1 table was wrong about it

Design-a §D5 step 7 said "no signing-ledger append", and
alternative C in my D1 table rejected "columns in
`SigningLedger`" outright. B and C both dual-append.
Checking the code, they are right and my table conflated
two different uses:

- **What I rejected, correctly:** the signing ledger as
  the *primary* store. Its `EXTRA_KEYS` (`trust/ledger.py`
  `SigningLedger`: `{decision_id, payload_hash, purpose,
  proposal_id, accepted, signer_id, format}`) carry no
  candidate sequence/hash, so the head rule is
  uncomputable from it. That stands.
- **What B/C propose, which I failed to separate:** a
  *mirror* carrying only the consumption fact, in the
  **existing** key set. This needs no format migration,
  and the precedent is already in the file, twice over:
  `append_ceremony_authorisation` reuses the columns for
  ceremony issuance ("EXTRA_KEYS is untouched, so no
  journal format migration" — its docstring says so), and
  `try_consume_eval_records` already writes
  `kind="consume"`, `format="eval-consumption"` entries
  with exactly B's proposed shape (`decision_id =
  payload_hash =` the consumed hash, `accepted=False`).
  B's mirror (`kind="consume"`,
  `format="ceremony-consumption"`,
  `decision_id=authorisation_id`,
  `proposal_id=ceremony_id`, `accepted=False`) is the
  eval-consumption entry shape with ceremony values. No
  migration, no new keys. Confirmed.
- **It is also not the thing my D7 rejected.** D7 point 3
  rejected writing the consumption *head hash* into the
  *signing anchor* — a hash pin with no entries behind
  it, whose meaning ("head of which journal?") is
  ambiguous and which the verifier never verifies against
  the consumption journal. The mirror is the opposite
  construction: full entries in an already-anchored
  journal, advanced by the existing `_update_anchor`.
  Different mechanism, different failure modes. My D5's
  silence on it was an omission, not a ruling.

**The mirror buys something real that design-a's residual
statement priced at zero:** after a rollback of
`ceremony-consumptions.json`, my design resurrects a
consumed envelope outright (the journal *is* the memory).
With the mirror cross-check, single-use survives the
rollback — only head monotonicity degrades (B §4.4 states
this residual precisely, and more honestly than design-a
stated its own). GPT's blocking condition is the
duplicate-consumption leg; the mirror anchors exactly
that leg. **Conceded, and design-a's D7 wording must be
corrected: the unanchored residual narrows to
head-regression-after-rollback of a never-consumed
envelope, as B states it.**

**Rulings on the details:**

- **Commit point: the consumption-journal append, full
  stop** (B §2.5 and design-a agree once the mirror
  exists). Mirror failure after commit ⇒ `ledger_failed`,
  receipt withheld, envelope burned, retry refuses
  already-consumed *from the primary*. Mirror-first
  ordering would be a defect: a mirror entry for an
  unconsumed envelope would refuse a legitimate consume
  forever.
- **One trap both B and C must pin in tests, which
  neither names explicitly:** the issuance mirror already
  writes `decision_id = authorisation_id` into the same
  ledger at issuance time (`append_ceremony_authorisation`,
  `kind="sign"`, `format="ceremony-authorisation"`). The
  already-consumed cross-check against the signing ledger
  must therefore be scoped to `kind="consume"` **and**
  `format="ceremony-consumption"` — exactly as
  `try_consume_eval_records` scopes its consumed-set scan
  by kind *and* format. A scan over `decision_id` alone
  would find the issuance entry and refuse **every**
  consume as already-consumed. B's §2.3 step 5 says "the
  signing ledger's consume entries", which is the right
  scoping in words; the build must pin it with a test
  whose envelope *has* an issuance mirror entry (i.e.
  every real envelope) and consumes successfully.
- The `SigningLedger` class docstring's core inference
  ("a signature with no ledger entry is evidence of a
  second signer") is not polluted: consume entries are
  `kind="consume"`, never `"sign"`, and `append_claim`
  already established non-sign entries in this ledger.
  Readers that count signatures already filter by kind.

## 5. B's protocol detail — substantially right; two corrections, and one concession about my own file list

- **Body exactly `{"signed_authorisation"}`: B is right,
  and C is wrong.** `signed_authorisation` is the repo's
  established key for a ceremony envelope on this channel:
  the issuance response carries it
  (`trust/verifier_main.py`, `{"signed_authorisation": ...}`)
  and the client requires exactly that key set
  (`trust/client.py:487`). C's §2 production callable
  instead sends `{"authorisation": ...}` — a second key
  name for the same object on the same channel, inviting
  exactly the strict-key-set confusion both designs
  otherwise police. Adopt B's body verbatim.
- **Already-consumed before not-issued: B is right.**
  In an intact system consumed ⊆ issued and the order is
  unobservable; under an issuance-journal rollback,
  already-consumed is both the true answer (the
  consumption record and the anchored mirror say so) and
  the safe one (it refuses). Not-issued in that state
  would invite the operator to "fix" the wrong journal.
  The information leak is negligible: the caller must
  already possess a valid `authorisation_id` (a hash
  output, unguessable) to observe the distinction.
  Design-a's D5 had issuance presence at step 5 with the
  monotonic checks after — I adopt B's order
  (already-consumed, then not-issued, then head).
- **Single code `ceremony_authorisation_invalid` for all
  non-temporal verify failures: B is right, and design-a
  was internally inconsistent.** My D5 step 4 named two
  caller-visible codes and then claimed "caller-visible
  bytes identical across sub-cases, the cycle-20
  evidence-sub-case precedent" — the precedent is a
  *single* code with the sub-reason logged verifier-side
  only; two codes with different names are not identical
  bytes. B's table (one code, reason tuple on stderr
  only) is the precedent applied correctly. Adopted,
  including B's exit split: invalid = exit 2, expired /
  signed-in-future = exit 3 (temporal is state, not form).
  One addition B should accept: design-a's step-1 code
  for an unopenable consumption journal,
  `ceremony_consumption_unavailable`, collapses into B's
  `ledger_failed` without loss — I withdraw it; fewer
  codes, same fail-closed behaviour.
- **Concession — my file list omits `trust/protocol.py`.**
  B §2.1 is right to call this out as the cheapest
  possible regression: `trust/protocol.py:28-29` defines
  `MODES = ("gate", "sealed_eval", "verify_envelope",
  "submit_claim", "issue_attestation",
  "ceremony_authorise")` and the protocol layer refuses
  any mode not in `MODES` before verifier_main's `_MODES`
  dispatch is ever reached. Design-a's file list registers
  the mode in `_MODES` only — as written, my consume mode
  would be dead on arrival, refused as a protocol error on
  every call. **Conceded in full: `trust/protocol.py`
  gains `"ceremony_consume"`, and a test must pin that the
  protocol `MODES` and the verifier `_MODES` agree (the
  drift class, not just this instance).**

**Where B's own protocol design fails — the
enforceability flag cuts against B, not against me.**
The coordinator notes B flags enforceability of the
required callable. B's §7.2 is candid that *his* design
has no library-level enforcement at all: `reanchor_pin`'s
signature is unchanged in design-b (§8: "No signature
change proposed by this seat"), and consumption lives
entirely in a caller contract — consume-before-reanchor
as a fifth caller precondition. That is precisely the
caller-orchestration design design-a §D2.1 rejected, and
B's own §7.2 concedes its shape ("the guarantee holds for
callers that follow the contract, and is unenforced for
callers that bypass it"). Worse, his ordering burns
envelopes design-a/C never burn: consume-first means a
ceremony that would refuse *locally* (binding mismatch,
failed attestation, history refusal — checks
`reanchor_pin` runs before any consumption in my/C's
placement) has already spent its envelope at the
verifier, converting a correctable local refusal into a
new-ceremony recovery. His §2.8 objection to receipt
parameters (an unsigned receipt is forgeable in-process)
is sound — against a design nobody in this round
proposed. The required callable is not a receipt: it is
live verifier state consulted at the last fallible step,
and its enforceability is the cycle-20 `ceremony_history`
discipline verbatim — no default (omission is a
`TypeError`), explicit `None` refuses before envelope
verification. What B's flag legitimately demands, and I
accept, is the residual stated plainly: a production
caller that deliberately installs a no-op callable gets
no protection — but that is installing a lie, in the same
class as restaging `old_pin` under FRESH-PIN, and the
defence is that the production adapter in
`trust/client.py` is the only shipped implementation,
pinned by the mode-level E2E tests. **Integration ruling:
A/C's required callable, invoked inside `reanchor_pin`
after all local checks, stands; B's caller-only contract
is rejected.**

Two smaller adoptions from B/C on the callable itself:
(a) **C's one-argument callable beats my two-argument
one.** Design-a passes `(authorisation, new_pin)`; but
the candidate inside the envelope *is* the new pin's
source, already binding-checked at step (4) before the
consume call at step (9), so `new_pin` is redundant
surface a callable could disagree with. C's
`consume_authorisation(authorisation) -> None` matches
B's envelope-only body. I concede the signature.
(b) **B's lazy journal opening beats my startup open.**
Design-a's D6-B has `_load_config` pre-open the
consumption journal and refuse startup if corrupt; B
§5.1 opens lazily per consume, like the ceremony journal.
A corrupt consumption journal refuses consume either way
— the fail-closed property lives at the mode, not at
startup — and my version additionally takes every *gate*
mode down for a ceremony-only corruption. Conceded:
lazy open, per-request `ledger_failed`.

## 6. C's integration — the placement is right (it is also mine); the helper default needs one pin C doesn't state

C's callable placement — after all local checks, before
record construction, zero calls on any local refusal,
exactly one on success, spy/counting-fake tests pinning
both — is design-a's step (9) placement stated from the
ceremony side. No dispute; the convergence is real and
the spy tests (zero-call on refusal) are the correct way
to pin "consumption is never recorded for a refused
ceremony" (my D2.4 clause (d)) at the unit layer.

**The fresh-consumer-per-call helper.** C's unit
`reanchor()` helper defaults to a *fresh* real-ledger
consumer per call. Does that break T6-style continuity
semantics? Not by itself — but the answer splits on a
distinction C's summary does not state, and the build
must pin it:

- Fresh **instance**, shared **backing store**: semantics
  preserved, and in one respect strengthened. The current
  helper already plays this game with `ceremony_history`
  (helper supplies a default, the function has none —
  `tests/test_signing_pin_ceremony.py:206ff`), and a
  consumer that reloads from the same on-disk journal on
  every call is *more* faithful to production (one
  verifier process per request, no in-memory head carried
  between ceremonies) than a long-lived in-memory fake.
  T6's meaning — the second presentation of the same
  envelope refuses — survives intact, with the refusal
  now sourced from the ledger instead of the history,
  which is the cycle's whole point.
- Fresh **state** per call (a consumer over a fresh temp
  dir, or a fresh in-memory set, constructed inside the
  helper on each invocation): continuity is destroyed.
  The second call's consume sees an empty journal,
  succeeds, and T7′ either fails outright or — worse —
  T6-style tests keep passing *for the cycle-20 reason*
  (the history check), silently re-pinning the residual
  as if the head had closed it. This is the exact
  failure mode the flipped tests exist to prevent.

**Ruling: fresh instance per call is accepted only if
the journal directory is fixture-scoped (one temp dir
per test, shared across the test's calls), never
call-scoped — and one test must assert the second call's
refusal names the consumption source (already-consumed
from the ledger), not the history's "already a
ceremonied target", so the test cannot pass on the old
leg.** C's helper default must be reviewed against that
pin when the full design-c file is re-delivered (§0).

**C's T7′ construction — fresh ledger instance over the
same temp dir:** yes, it proves on-disk authority at the
ledger layer, and it is the right construction. A second
`CeremonyConsumptionLedger` instance over the same
directory carries no in-memory state from the first;
its refusal can only come from what `_save` persisted
and `_reload` re-read — the hash-chained file, not an
object graph. That is a genuine proof, not a restaging.
Its limit, stated so nobody over-claims it: it does
**not** prove verifier-process separation — the test
process can write that temp dir, so caller-unwritability
is established by the mode-level tests (real subprocess,
verifier home) and the deploy identity, not by T7′.
T7′ proves persistence; the E2E proves protection. Both
are needed; C has the first, B's C1–C20 suite has the
second, design-a's T19–T21 overlap it.

## 7. The bit-flip sweep — the cycle-20 timing evidence changes nothing; both budgets stand

Design-a budgets 768 exhaustive single-bit verifies
(512 signature + 256 public key); B budgets the same
768 and adds a 256-case message sweep (1024 total). The
cycle-20 record (BUILD-CYCLE-20.md: median 6.4 ms,
p95 29.9 ms, n=60, on this shared-CPU VM) prices them:

- Mine: 768 × 6.4 ms ≈ **4.9 s** at the median; even the
  absurd bound of every call at p95 is ≈ 23 s.
- B's: 1024 × 6.4 ms ≈ **6.6 s**; p95 bound ≈ 31 s.

Both sit comfortably inside either design's 60 s
fallback trigger, on the *measured* numbers rather than
estimates. **No change of plan: the exhaustive sweep
stays exhaustive, B's message-flip extension is adopted
(it is cheap and the message is the one input neither
design's sweep otherwise touches), and both designs'
subsample fallbacks (my byte-mask reduction, B's seeded
pubkey subsample) stay untriggered unless the build
measures > 60 s — in which case the reduction is
recorded in BUILD-CYCLE-21, never taken silently.**
Two caveats the build must honour: the 6.4/29.9 figures
are n=60 on a throttled shared-CPU VM, so the build
re-measures the sweep's actual wall time and records it
in the suite docstring (B requires this; I agree); and
p95 is not a max — a loaded-VM outlier run is a reason
to re-measure, not to subsample.

---

## Concessions and holds

### Conceded to B

1. **R3 (stale old-pin refusal) withdrawn** as a
   verifier-side head rule (§3): it breaks the
   burned-but-unmoved crash recovery all three designs
   prescribe, and closes no class design-a doesn't
   elsewhere concede is open. Head rule is B's M1 + M3;
   `old_pin` is recorded, not consulted. (The
   equal-seq/different-hash old-pin refusal is the only
   fragment I leave on the table for the room, without
   blocking M4-pure.)
2. **The signing-ledger mirror** (§4): dual append
   adopted, consumption journal as sole commit point,
   mirror failure = `ledger_failed` with the envelope
   burned. Design-a's D1 alternative-C rejection and D7
   residual wording are corrected per B §4.4. Build must
   pin the `kind="consume"` + `format="ceremony-
   consumption"` scoping of the mirror cross-check
   against the issuance mirror's shared `decision_id`.
3. **B's refusal-code table** (§5): single
   `ceremony_authorisation_invalid` for non-temporal
   failures; already-consumed checked before not-issued;
   body exactly `{"signed_authorisation"}`. My
   `ceremony_consumption_unavailable` code withdrawn
   into `ledger_failed`.
4. **`trust/protocol.py` `MODES` registration** (§5):
   design-a's file list omitted it; the mode would have
   been protocol-refused on every call. Added, with a
   protocol/verifier mode-agreement test.
5. **Root carve-out** on the loader uid check (§1), and
   **lazy opening** of the consumption journal in place
   of design-a's startup open (§5).

### Conceded to C

6. **One-argument consume callable**
   `consume_authorisation(authorisation)` (§5): design-
   a's `new_pin` parameter was redundant surface.
7. C's spy-test pinning of the invocation placement
   (zero calls on local refusal, exactly one on success)
   adopted as the unit-layer statement of the crash
   contract's clause (d) (§6).

### Held from design-a

1. **Seed perms {0400, 0600}** (§1): no test and no
   deployment depends on refusing 0400; the task text
   says "0600 or stricter"; B's objections are taste and
   a straw predicate. Generation stays 0600.
2. **Both loaders hardened this cycle** (§2): shared
   predicate + fd discipline for `load_ceremony_seed`
   *and* `load_signing_key` (the latter as a separate,
   bisectable commit). Widening is acceptance-monotonic;
   nothing that loads today can break. Ceremony-only
   scope (C) and follow-up deferral (B) both rejected.
3. **Required callable inside `reanchor_pin`, invoked
   after all local checks as the last fallible step**
   (§5): B's caller-only consume-first contract is
   unenforced by his own §7.2 admission and burns
   envelopes on purely local refusals. The crash-
   consistency contract wording (design-a §D2.4) stands
   as the text both docstrings carry.
4. **`ceremony_history` stays required, demoted to
   audit/consistency-only** (design-a D4): B keeps it
   too; C keeps it too. The head is the sole single-use
   authority; the history can refuse, never grant.
5. **`initial_anchor` refuses on a non-empty consumption
   journal** (§3), against B's reason-blind M5: the
   reason asserts a fact the journal can falsify.
6. **Exhaustive bit-flip sweep, no subsampling** (§7),
   extended by B's message flips: measured cost ≈5–7 s
   at the cycle-20 median, far under the 60 s trigger.
7. **No anchoring of the consumption journal this
   cycle**, with the residual *as narrowed by the
   mirror* (§4): single-use is anchored via the signing
   ledger; head-regression-after-rollback of a
   never-consumed envelope is the named remainder,
   folded into the joint `ceremony-journal-anchoring`
   follow-up (B and design-a agree here; C's §7, per the
   coordinator's summary, concurs).

### Blocking item for the coordinator

Design-c.md on disk is truncated at §2 (§0 above). C
must re-deliver the full file; items 6–7 and §6 of this
critique are provisional on the re-delivered §§3–8
matching the coordinator's summary of them.
