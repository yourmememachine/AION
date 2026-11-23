# CROSS-CHECK BRIEF — Cycle 25: independent supersession authorisation (Q1 only)

You are an external reviewer seat for the AION trust-boundary
work. In the re-review of cycles 14–16 (CROSS-CHECK-18), Q2–Q7
were accepted or ratified by both seats. The ONLY split was
Q1: seat-gemini shipped all three cycles while rejecting the
"separate authorisation" label for cycle 24's supersession
decision; seat-gpt held all three because that decision —
although a separate signed envelope, mode, journal and
receipt — is AUTO-REQUESTED by PinAdopter after a refusal, and
a separately signed decision is not a separately authorised
one. Cycle 25 addresses Q1 and nothing else. An internal war
room (six seats, two fix rounds, three re-reviews) has
reconciled; its verdicts are NOT shown to you. Please answer
the two questions at the end.

## What changed, in one paragraph

Supersession now requires an **independent supersession
approval**: a signed artefact minted out-of-band by a
standalone approval tool under a dedicated **approver key**,
verified by the verifier — signature, expiry, and the full
binding re-derived from the verifier's own journals — BEFORE
any supersession decision is journaled. The adopter's
auto-request is deleted, not gated: on the supersede-required
refusal the adopter stops, records a pending state, writes a
pending-supersession report, and raises a structured
pending-approval outcome (the production runner surfaces it
as its own exit code). Only a later, separately invoked
attempt that finds an approval artefact in the adopter's
inbox presents it — once — and completes the consume.

## The claim we ask you to ratify — stated at its exact strength

Seat-gpt's criterion (i) asked for "a genuinely independent
authorisation event". We do NOT claim that phrase at face
value. The claim as built, which we ask you to ratify or
reject as stated, is:

**Independence is at the authorisation-event level.**
Supersession cannot happen as a side effect of an automated
recovery flow; it requires a deliberate separate act — a
second tool invocation, with its own inputs, producing its
own signed artefact under its own key — that the adopter's
code path cannot perform. It is NOT a claim of a separate
human or a separate OS user: on this same-user machine the
operator and the approver are the same person running a
second command, the approver seed is a file any same-user
process could read if it found the path, and a fully
malicious same-user process is outside the claim. What the
mechanism enforces is that no automated flow — bug, crash
recovery, or retry logic — can cross from a refused consume
to an authorised supersession without that deliberate act
intervening.

## The approval channel

- **Tool:** `trust/supersession_approval_tool.py`, a
  standalone CLI (`generate-key` / `public-key` / `approve`)
  invoked by the operator against the adopter's
  pending-supersession report. It is the only module that
  signs approvals. The verify-side library
  (`trust/supersession_approval.py`) contains no signing
  function, seed type or loader; the adopter contains no
  import of either module and no access to the approver seed
  — its config and env carry no approver material, the seed's
  path variable is absent from the verifier wrapper's
  allowlist (a non-allowlisted env-file key hard-fails the
  launch), and the client wiring refuses that variable as
  unknown.
- **Key:** a third Ed25519 key, distinct from the snapshot
  signing key and the verifier's ceremony seed. The verifier
  holds only its PUBLIC key (one new env var,
  `AION_SUPERSESSION_APPROVER_PUBLIC_KEY`; allowlist 19 → 20
  at every pinned site). Startup refuses an approver key
  equal to the ceremony public key, or to the snapshot
  signing key in raw or derived form. Production with the
  ceremony seed configured refuses startup without the
  approver key (disclosed coupling: the key gates verifier
  startup although only the supersede mode uses it — the
  fail-fast discipline of cycles 22–23, kept deliberately).
- **Artefact:** domain-separated signed payload binding
  (a) the abandoned head movement — authorisation id,
  ceremony id, full old→new pair; (b) the replacement
  candidate — authorisation id, cycle seq, payload hash;
  (c) the exact movement on both sides; and (d) the original
  failed consumption attempt — the attempted authorisation
  id, the refusal code, and the head entry's authorisation
  id, journal seq and entry hash, so any intervening head
  movement stales the approval. TTL 900 s default, hard cap
  3600 s, enforced at verification; the tool REFUSES an
  out-of-window TTL. Note the effective window is bounded in
  practice by the candidate envelope's own remaining TTL.
  `burned_unadopted` approvals are un-mintable.

## The verifier's checks, in order

`ceremony_supersede` now: (0) refuses if no approver key is
configured; (5b) parses and verifies the presented approval —
signature, key id, temporal validity — BEFORE any journal is
read (authenticity failures carry dedicated codes emitted at
this pre-journal step; they can leak only artefact-local
facts); (8b) re-derives the binding from its OWN journals —
the abandoned movement from its consumption head, head seq /
entry hash from its own head entry, the request naming no
head field — and checks the approval is unspent, folding
every binding or single-use failure into the single existing
code `ceremony_supersede_unproven`; (9) journals the decision
recording the approval's id, payload hash and approver key
id. An adopter auto-request alone (no artefact, a forged
artefact, or one signed with the ceremony seed or the
snapshot key) refuses pre-journal. Approval single-use is
enforced at ledger load (duplicate id = corrupt), at the
mode, and inside the ledger's append retry loop; two
concurrent verifier processes produce exactly one decision.
The decision is "independently recorded" in this qualified
sense: it is journaled in the verifier's own supersession
journal only after the independent approval verifies — the
journal itself remains unanchored (the tracked follow-up
`ceremony-journal-anchoring`, accepted as a disclosed deferred
risk under Q6 of the re-review, is unchanged).

## The adopter's role — custodian and presenter, not merely transport

We state this at its full strength, not minimised: the
adopter holds the approval inbox, selects the artefact whose
replacement binding matches its retained envelope, decides
when to present it (on its next invocation), and on success
completes the consume and the adoption in the same run. What
it cannot do is create, alter, or validly re-bind an
approval: selection is by exact binding match, the client
echo-checks the artefact against the envelope before sending,
and the verifier re-derives everything from its own journals.
In directory mode a presented artefact is moved aside on any
outcome; in single-file mode it is not moved, and
presented-once there rests entirely on verifier single-use
(documented). The pending report's head `seq` / `entry_hash`
are written null by the adopter — it cannot read the
verifier's journals — and are completed by the approver FROM
the consumption journal: a hand-transcription step inside the
deliberate act, disclosed here plainly. A wrong transcription
is inert: the verifier compares the approval against its own
head entry and refuses rather than misapproving.

## Regression evidence (seat-gpt's criteria iv and v)

- **No self-escalation:** counting-client tests pin the
  adopter-only flow at supersede_calls == 0, exactly one
  consume, zero decision entries, pin unmoved; a second
  approval-less attempt makes zero verifier calls of any
  kind. Forged approvals, approvals self-signed with the
  ceremony seed, and approvals signed with the snapshot key
  all refuse; approvals bound to a different candidate,
  movement, or failed attempt refuse; a spent approval
  refuses with exactly one decision journaled.
- **Restoration through the new route:** the restoration
  regression (verifier-home rollback recovery) now runs
  pending stop → approver completes the null head block from
  the verifier's journal → tool-signed approval → completion,
  asserting the decision's recorded approval id equals the
  artefact's. The crash suite's supersede landing is
  re-pointed identically.
- **Ambiguity windows found in internal review and closed:**
  a decision journaled but lost to the adopter (mirror
  failure after commit, crash, journal-append failure) no
  longer strands the movement — resume is consume-first
  against the standing decision; a decision staled by a
  concurrent head move refuses head-regression, which resume
  treats as pre-commit (falling through to the approval path
  in the same attempt, or re-pending), never as a burn; a
  resume consume that commits but loses its response is
  journaled `consumed` adopter-side, releasing the movement
  to the ordinary `burned_unadopted` recovery. All three are
  pinned by tests against the real verifier with exact call
  counts.

## Relabel (seat-gemini's condition)

Stage names now match what each stage enforces, in code,
docstrings, CLI help and operator docs: the consumption
**authorisation** (the cycle-19/20 envelope); the supersession
**decision** (the verifier-journaled record); the supersession
**approval** (the out-of-band artefact that alone authorises
a decision). The stale cycle-24 descriptions of the deleted
auto-flow were rewritten wherever they survived (client,
pin_ceremony, design record addendum). The decision record
carries a new Addendum 5 superseding Addendum 4's
"separately authorised" reading; Addendum 4 itself is
unedited history. Two settled adds from the re-review also
landed: the Q2 disclosure (operator removal prevents future
issuance; it does NOT revoke authorisations already issued —
now in both the ceremony docstring and the operator-facing
deployment README, which also documents approver-key rotation
and seed-loss recovery: rotation invalidates unspent approvals
only, and a lost approver seed wedges supersession alone,
recovered by reprovisioning) and the Q4 precaution
(internal/test-only seam markers on the fabricated-consumer
callable and both direct-ledger APIs).

## Suite

1756 tests OK (skipped=28, deployment-gated) on the final
tree, independently re-run by the coordinator; the real loop
state was not advanced and its hash is unchanged.

## Questions

**Q1.** Is Q1 now resolved — does the approval mechanism
above constitute the independent authorisation event your
criteria required, at the claim strength stated? If not,
which criterion remains unmet, and is the gap in the mechanism
or in the claim?

**Q2.** With Q1 resolved (or not), do cycles 14–16 ship?
(Their Q2–Q7 positions from the re-review stand as previously
ruled; this brief changes nothing about them except removing
the Q1 hold.)
