# Cycle 25 — Review, seat rev-r6 (FORCED DISSENT)

**Role:** argue the strongest possible case against shipping. I have tried to be
fair: §7 defends one contested choice, and §8 separates residual risks that
honest documentation can carry from the defects in §§2–5 that, in my judgement,
block. My blind verdict (filed first, `blind-r6.md`) was FIX at 0.35; the full
read below did not move it.

**Scope read:** `internal/cycle25-work/design-approval.md`;
`trust/supersession_approval.py`, `trust/supersession_approval_tool.py`,
`trust/verifier_main.py` (supersede mode, `_load_config`),
`trust/ledger.py` (`CeremonySupersessionLedger`), `trust/client.py`,
`trust/pin_adoption.py`, `trust/runner.py`, and the cycle-25 tests
(`tests/test_trust_supersession_approval.py`,
`tests/test_trust_supersede_adopter.py`).

**What is genuinely good (so the dissent is calibrated):** the artefact
construction is careful — exact key sets, pinned purpose/alg, full binding of
abandoned pair, candidate, both movements and the failed attempt;
verification at verifier step 5b happens *before* any journal read; binding
and single-use failures fold into the single `ceremony_supersede_unproven`
code at step 8b; `burned_unadopted` is un-mintable at the projection, the
tool, and the shape gate (criterion (iv) is, in my view, actually met); the
ledger enforces single-use at append (inside the retry loop) and at load.
None of that saves the cycle, because the cycle does not stand or fall on
cryptography. It stands or falls on criterion (i).

---

## 2. BLOCKER — Criterion (i) is not met: this is invocation separation, not an independent authorisation event

Seat-gpt's wording (CROSS-CHECK-18) was "a **genuinely independent**
authorisation event". What cycle 25 builds is a second command, run by the
same person, as the same OS user, on the same VM, signing with a seed stored
in a file that **any process running as that user can read if it can find
the path** — and finding it requires no import, no cooperation from the
adopter's code, and no vulnerability: a filesystem scan for a 64-hex-char
0600 file outside the repo suffices, and the seed path is also carried in
the tool process's own environment variable
(`AION_SUPERSESSION_APPROVER_SEED_PATH`), visible to same-user processes
via `/proc`.

The design's defence is §1's honesty: independence is claimed "at the
authorisation-event level, and nothing more", and a fully malicious
same-user process is declared out of scope. That labelling is commendable
and satisfies seat-gemini's naming condition. But it concedes the point
that matters: **the criterion as commissioned is not satisfied; a weaker
criterion is satisfied and relabelled.** This is precisely the pattern
seat-gemini rejected in the cycle-15 line of criticism — ceremony whose
form (separate signature, separate journal, separate artefact) exceeds its
enforcement. Cycle 24 was a separately *signed/journaled* decision that
turned out not to be separately *authorised*. Cycle 25 adds a third key
and a second CLI to the same single-actor system. The delta over cycle 24
is real but narrow: it defeats *accidental/automated* self-escalation by
*honest* code. It does not defeat, or even inconvenience, the adopter
itself if the adopter is buggy in a new way (e.g. a future maintenance
change that shells out, or a compromised dependency in the adopter's
process that goes looking for the seed), because the "boundary" is an
import-scan test pin — a property of the source tree at test time, not a
runtime boundary. Tests pin that `pin_adoption.py` does not import the
tool *today*; nothing at runtime prevents the adopter process from
reading the seed file directly.

Ship decision consequence: if the war room ships this, the ship record
must state plainly that criterion (i) is met only in the weakened
"deliberate-act" sense of §1 — i.e. the external re-brief to seat-gpt must
present §1's wording as the claim and ask for ratification of *that*, not
imply the original criterion was met as written. Shipping on the current
framing, where the design simultaneously quotes criterion (i) as "the
spec for this cycle" (§0) and redefines it in §1, repeats the cycle-24
labelling failure one level up.

## 3. BLOCKER — The security binding is completed by hand: the pending report ships with `seq`/`entry_hash` as `null`

This is the most concrete defect in the cycle, and the design does not
disclose it. Design §7 describes the report's `head` block as the
adopter's belief "copied into the signed projection verbatim". The
implementation (`PinAdopter._stop_at_pending`) writes
`"seq": None, "entry_hash": None` — the adopter *cannot know* either
field — and the code comment states the operational truth: "**the approver
completes them from the verifier's consumption journal as part of the
deliberate approval act**". Three problems:

1. **A human transcription step sits inside a cryptographic binding.**
   The operator must hand-copy a journal sequence number and a 64-hex
   `entry_hash` into the report before the tool will sign (the projection
   rightly refuses nulls). One mistyped hex digit produces an approval
   that verifies cryptographically and refuses on binding — fail-closed,
   so integrity survives, but the honest path becomes trial-and-error
   with a 3600 s approval clock and a much shorter envelope clock (§5)
   running. There is no checksum, no short confirmation digest, no
   tooling: the tool "performs no journal access" *by design*, so the
   human is the data bus.
2. **The approver must have read access to the verifier home.** The
   fields being copied live only in the verifier's consumption journal.
   The supposedly separate approver act therefore *requires* reaching
   into the most sensitive directory in the system — the same home whose
   write access the ledger docstring admits can forge decisions. The
   design's custody table (§4) never lists "approver reads verifier
   journals" as part of the act; operationally it is mandatory.
3. **The tests conceal the gap.** In
   `tests/test_trust_supersede_adopter.py`, `mint_approval_into_inbox`
   completes the report *programmatically* from the harness's
   consumption entries — the test approver has a capability (direct,
   exact journal access in-process) that the real operator does not.
   Criterion (v) is thus exercised through a completion path that does
   not exist in deployment. A restoration test that hand-completes the
   two fields exactly as an operator must — including a transcription-
   error case — is absent.

Knock-on deviation: design §6 says inbox selection requires the
approval's `failed_attempt.head_entry_hash` to equal the pending report's.
But the pending journal line also persists `head_entry_hash: None`
(`_stop_at_pending`), so in `_resume_pending` the lookup degenerates to
the `authorisation_id`-only fallback the code comments acknowledge. The
hash half of the adopter-side selection check never operates in practice.
The verifier's step-8b check remains authoritative, so this is defence-in-
depth that exists on paper only — but the design claims it as a working
layer.

## 4. BLOCKER — Availability: the rare recovery path now gates the whole verifier, and approver-seed loss is a permanent wedge

`_load_config` refuses **startup of the entire verifier**
(`verifier_misconfigured`) in production whenever the ceremony seed is
configured but `AION_SUPERSESSION_APPROVER_PUBLIC_KEY` is absent — and
likewise if the hex is malformed or equals the ceremony public key. The
design (§4.2(d)) frames this as avoiding "a wedge, not a policy". The
actual trade is the reverse:

- A provisioning error in a key needed *only* for supersession — a rare,
  exceptional recovery — now bricks **every** mode: ordinary authorise,
  consume, and `burned_unadopted` recovery included. The approver public
  key is itself provisioned by hand-copying hex64 output from
  `setup.sh`/`public-key` into an env file (another transcription step,
  cf. §3), so this is not a theoretical misconfiguration.
- **Approver-seed loss is unrecoverable and undocumented.** If the seed
  file is lost or destroyed, no approval can ever be minted again; a
  head that lands in the supersede shape can then never be consumed
  past, and ordinary recovery is forbidden by design from substituting.
  The pin is wedged permanently. There is no rotation procedure in the
  design (rotating the verifier env public key invalidates outstanding
  approvals and requires a verifier restart under the new pin; nothing
  specifies who may do this, when, or how it is recorded), and no
  escape hatch. Cycle 25 thereby converts a rare-but-recoverable state
  (cycle 24: supersede shape) into a state whose recoverability depends
  forever on one 0600 file on one VM.
- The per-request research behaviour (key absent → supersede mode alone
  refuses with `ceremony_supersede_approval_unconfigured`) proves the
  narrower coupling is implementable; production chose the wider one
  without a stated reason that survives §3's transcription reality.

A control that can brick the system it protects needs a stronger
justification than symmetry with the consumption-anchor rule.

## 5. MAJOR — The TTL deviation is worse than disclosed, and the tool does not do what the design says

- The 3600 s cap is defended (design §6) as necessary because "an
  approval is a human-paced act" and 900 s "would make the honest path
  racy". But the binding constraint on the honest path is not the
  approval: it is the **ceremony envelope**, whose TTL remains hard-
  capped at 900 s (`CEREMONY_AUTHORISATION_TTL_MAX_SECONDS`) from
  issuance — issuance that precedes the failed consume, the report, the
  hand completion (§3), the tool run, and the adopter re-run. By the
  time an approval exists, the envelope it authorises may have minutes
  left, or none. The 3600 s window is therefore largely illusory as
  usability, while being entirely real as exposure: a signed, fully
  bound approval artefact sitting in an adopter-writable inbox
  directory for up to an hour, four times the envelope discipline every
  other artefact in this system obeys.
- **Design/code mismatch:** design §3 states the tool "refuses … TTL
  outside [60, 3600]", and the tool's own module docstring repeats that
  its refusals include "a TTL outside [60, 3600]". The code does no such
  thing: `sign_supersession_approval` silently **clamps**
  (`effective_ttl = min(ttl_seconds, APPROVAL_TTL_MAX_SECONDS)`), and
  `tests/test_trust_supersession_approval.py::test_ttl_bounds` pins the
  clamp by signing with `ttl_seconds=99999` and expecting success. An
  operator who asks for a week gets an hour, silently; an operator who
  fat-fingers a huge TTL is never told. Either the design or the code is
  wrong; shipping with them disagreeing — in a cycle whose external
  condition is literally "names must match what is enforced" — should
  not happen. (The ceremony signer uses the same clamp pattern, which
  explains the choice; it does not reconcile it with this cycle's own
  design text.)

## 6. MAJOR — The adopter is not "merely transport": it selects, times, stockpiles, and auto-executes

Seat-gpt's criterion (iii) — the verifier must not issue "merely because
the adopter auto-requests" — is formally satisfied: no approval, no
decision, and the cycle-24 auto-request call is deleted. But the adopter's
remaining role is larger than the "presentation/transport" framing in
`client.py`'s docstring ("This client merely CARRIES the artefact"):

- **Selection is a decision.** `_find_supersession_approval` scans the
  inbox and picks the *first* artefact (sorted filename order) matching
  the retained envelope id (hash check inoperative, §3). Whoever or
  whatever writes into that inbox directory — a directory in the
  *adopter's own* config space — controls which approvals exist to be
  selected. The adopter is the custodian of the approval channel end to
  end.
- **Purpose confusion is mostly, not fully, excluded.** Cross-envelope
  replay is genuinely impossible (full binding, verified). But per-
  abandoned uniqueness is deliberately *not* enforced in the ledger:
  multiple approvals can mint multiple live decisions abandoning the
  same head in favour of different envelopes. Consume-side binding makes
  the losers inert, which the ledger docstring argues honestly — yet
  combined with the 3600 s window this means approvals/decisions can be
  **stockpiled** in parallel during a window, with the adopter's next
  routine run determining which one is actually exercised first.
- **Execution is automatic.** The human act ends at minting. On the
  adopter's next ordinary `snapshot_and_adopt()` — e.g. a scheduled
  runner invocation — the approval is presented, the decision obtained,
  the consume re-run, and the pin adopted, with no human confirmation
  at presentation time and no check that the world still matches what
  the approver believed beyond the head binding itself. "Deliberate
  act" upstream, unattended execution downstream.
- **Design §6 deviation (minor):** in single-file inbox mode the
  presented artefact is *not* moved aside (`move_aside=False`), contrary
  to §6's "moved aside regardless of outcome"; it remains in place to
  be re-presented on later runs (verifier single-use blocks a second
  decision, so this is noise and confusion, not a bypass — but again a
  paper/implementation gap). Stale and unparseable inbox files are
  never cleaned up by anything.

None of these alone blocks. Together they mean the honest summary is
"the adopter cannot *mint*, but it curates, holds, times and executes" —
which should be the documented claim, not "merely carries".

## 7. DEFENDED — Seat B's dedicated approval refusal codes are correct on oracle grounds

The design instruction was a single collapsed refusal code; seat B shipped
three dedicated codes (`ceremony_supersede_approval_unconfigured`,
`_expired`, `_invalid`) for step 5b, reserving the collapsed
`ceremony_supersede_unproven` for step 8/8b. I attack much of this cycle,
but I **defend** this deviation: step 5b runs *before any journal read*,
so the dedicated codes leak information only about the artefact the
presenter itself supplied (its authenticity, its expiry) and about
static configuration — never about journal state, head position, or
whether a decision exists. Collapsing authenticity failures into
`_unproven` would not reduce any oracle; it would conflate "your artefact
is forged/expired" with "your movement is unproven", degrading the
operator's ability to distinguish a minting error from a state refusal —
the exact diagnostic confusion §3's transcription step will generate in
practice. The oracle-sensitive boundary (state-dependent facts) is where
the collapse belongs, and there seat B kept it. Two nits, neither
blocking: (a) the `_expired` code is also returned for
`signed_in_future` approvals — a not-yet-valid artefact labelled
"expired" is a name/enforcement mismatch of exactly the kind
seat-gemini's condition targets, and should be renamed or the carve-out
documented as "temporal"; (b) `_unconfigured` confirms verifier
configuration to any caller who can reach the mode — low-value
information, acceptable, but it should be a conscious, recorded choice.

## 8. Residual risks honest documentation can carry (not blockers)

- Criterion (ii)'s "independently recorded": the record is three fields
  (`approval_id`, `approval_payload_hash`, `approver_key_id`) inside the
  decision entry itself, written at decision time, in the supersession
  journal — which the ledger's own docstring admits is **not externally
  anchored** and is forgeable/rollback-able by anyone with verifier-home
  write access. "Independent" here means "a distinct field set in the
  same unanchored journal, recorded simultaneously with the decision it
  enables", and the full artefact is retained by nobody (the adopter
  renames its copy to `.presented`). Document exactly that; do not let
  the addendum say "independently recorded" unqualified.
- `approver_id` is self-asserted free text: the verifier passes
  `expected_approver_id=None`, so identity is purely the key pin. Fine —
  provided no prose implies named-person accountability.
- The pending report is a single fixed file beside the pin, atomically
  overwritten: only one outstanding supersession can be in the approval
  pipeline at a time, and a second stop overwrites the first report.
  Acceptable for a single-adopter prototype; document the serialisation.
- Same-user honesty (§1 of the design) is, as prose, exemplary. My
  objection in §2 is not to the prose but to shipping a cycle whose
  commissioning criterion it concedes.

## 9. Minimal change set that would flip me to SHIP

1. **Eliminate hand transcription (§3).** Either (a) the verifier's
   `ceremony_supersede_required` refusal carries a signed refusal
   receipt containing the head `seq`/`entry_hash`, which the adopter
   attaches to the report verbatim; or (b) the approval tool gains an
   explicit read-only completion step that reads the consumption
   journal, fills the two fields, and shows the operator a short
   confirmation summary before signing. Whichever is chosen, the
   approver's journal access (if any) must appear in the design's
   custody table, and a restoration test must exercise the completion
   exactly as an operator performs it, including a corrupted-field case.
   Persist the real `head_entry_hash` in the pending journal so inbox
   selection's hash check (design §6) actually operates.
2. **Decouple startup (§4).** Production verifier starts without the
   approver public key; only `ceremony_supersede` refuses per-request
   (`_unconfigured`), as research already does. Plus a documented
   approver-key rotation and seed-loss recovery procedure, tested once.
3. **Make TTL honest (§5).** Tool refuses TTL > 3600 as design §3 and
   its own docstring claim (fix the clamp and the pinning test), or the
   design and docstring are amended to say "clamped" — one story,
   everywhere. Operator docs must state the effective window is the
   *envelope's* remaining TTL, not the approval's.
4. **Ship-record wording (§§2, 6, 8).** The cycle-25 addendum and the
   external re-brief present the claim as deliberate-act separation
   under a single operator (design §1 verbatim), describe the adopter
   as custodian/presenter rather than mere transport, and qualify
   "independently recorded" per §8. If seat-gpt ratifies *that* claim,
   criterion (i) is honestly closed; if it does not, no code in this
   cycle closes it either.

Items 1–3 are small, local changes. Item 4 is prose. Until at least
1–3 land, this cycle ships a hand-transcribed binding, a new
startup-wide single point of failure, and a TTL story its own code
contradicts — in service of an independence claim its own design
concedes is weaker than the criterion that commissioned it.

**Final verdict: FIX — score 0.35. Do not ship cycle 25 as-is; the minimal flip set is §9, items 1–3 in code and item 4 in the ship record.**
