# REVIEW CYCLE 25 — war room (independent supersession authorisation)

**Summary (claim scope):** supersession now requires an
independent supersession approval — an out-of-band artefact
under a dedicated approver key that the adopter cannot create
— verified by the verifier before any decision is journaled.
Independence is claimed at the authorisation-event level only
(a deliberate separate act with its own artefact and key), NOT
as a separate human or OS user; the brief to the external
seats presents that claim for ratification rather than
asserting seat-gpt's criterion (i) as written. Verdict:
**SHIP PROVISIONAL** — reconciled unanimous after two fix
rounds; provisional on the parent's external round
(ChatGPT + Gemini) on the focused Q1 brief, per the standing
rule. Cycles 14–16 were not shipped or recorded; loop state
not advanced.

## Blind round (scores locked in internal/cycle25-work/blind-r*.md before discussion)

| seat | scope | blind | final (pre-fix) |
|---|---|---|---|
| rev-r1 | approval artefact + crypto | SHIP 0.86 | SHIP 0.86 |
| rev-r2 | verifier side | SHIP 0.86 | SHIP 0.86 |
| rev-r3 | adopter side | SHIP 0.84 | FIX 0.78 |
| rev-r4 | deploy/allowlist + evidence | SHIP 0.82 | SHIP 0.88 |
| rev-r5 | relabel + Q2/Q4 adds | FIX 0.70 | FIX 0.70 |
| rev-r6 | forced dissent, whole cycle | FIX 0.35 | FIX 0.35 |

rev-r1: binding complete — no bound field swappable,
truncatable or replayable across movements (apparent gaps are
covered transitively via the bound authorisation id and the
journal entry_hash); `burned_unadopted` un-mintable at both
surfaces; canonicalisation matches the repo's envelope
discipline. LOWs: the tool silently CLAMPED an over-cap TTL
where design §3 promised refusal (→ fix round 1); the
"no signing capability" pin is import-level only and evadable
as a source scan — adequate as a regression pin, and the real
barrier is seed absence (recorded; design wording not to be
read as adversarial authorship-proofing).
rev-r2: all five criteria PASS on the verifier path; approval
verified at step 5b before any journal read; binding at 8b
derived solely from the verifier's own journals; single-use
race-probed (exactly one decision lands under concurrent
verifier processes); production gate sound; legacy key-set
rule airtight. The dedicated-authenticity-codes deviation
from a single collapsed code judged acceptable (all such
codes are pre-journal and leak only artefact-local facts).
F1 (minor): the Q4 marker absent from trust/ledger.py, with
the concrete consequence that `append_decision`'s defaulted
approval fields let an in-process caller mint an approval-free
decision `check_head` would honour — inside the stated honesty
boundary, but exactly Q4's target (→ fix round 1). F3 (minor):
approver ≠ snapshot-key claimed but not enforced (→ fix
round 1, enforced).
rev-r3: the negative proven — the cycle-24 auto-request is
deleted, not gated; the sole decision call site is
approval-gated resume; the pending exception carries all
binding facts and the null head fields are sound (uncompleted
reports un-mintable; wrong completions inert at step 8b).
F1 (BLOCKER, availability): a journaled decision whose
outcome is lost to the adopter strands the movement
permanently (→ fix round 1).
rev-r4: allowlist 19→20 verified at every §4.3 site; the seed
path var live-verified refused by `production_client`;
restoration leg 4 and the crash re-point genuinely exercise
the independently authorised route; criterion (iv) proof
complete (counting client, forged/self-signed/wrong-binding/
reuse refusals). Minors: a stale docstring in the restoration
file (→ fix round 1); design §4.1's "discards" understates the
wrapper's hard-fail (→ fix round 1).
rev-r5 (FIX, text-only): F1 the stale cycle-24 paragraph in
client.py's `ceremony_consumer` docstring (coordinator flag
verified); F2 no cycle-25 addendum yet in
DECISION-CONSUMPTION-HEAD (coordinator's item — Addendum 5,
landed with these records); F3 pin_ceremony's module docstring
still framed the deleted two-phase flow; F4 the Q2 disclosure
absent from the operator-facing deploy README; F5 = rev-r2's
ledger marker; F6 the approval tool's CLI help called minting
a "separate authorisation act", violating the naming rule.
All → fix round 1.
rev-r6 (forced dissent): independence is of invocation, not
authority — same human/OS user/VM, seed readable by any
same-user process that finds the path; hand transcription of
head seq/entry_hash inside a cryptographic binding, undisclosed
in the design; production startup coupled to the approver key;
TTL story contradicted by the clamp; the adopter custodies,
selects, times and auto-executes presentation on its next
routine run (more than transport); single-file mode never
moves the artefact aside. Defended seat B's dedicated codes on
oracle grounds (two nits recorded). Minimal flip set: disclose
or eliminate transcription; decouple startup or document;
make TTL behaviour and docs agree; present the §1 claim for
external ratification in the ship record.

## Fix round 1 (all items landed; suite 1752 OK)

r3 F1 consume-first resume (+ regression tests pinning the
ambiguous-response shape); TTL refusal replacing the clamp;
the full text set (client docstring, pin_ceremony docstring,
ledger Q4 markers, CLI relabel, design §4.1/§6/§7
corrections, restoration docstring); approver ≠ snapshot-key
enforced at startup; single-file asymmetry documented.

Re-reviews: rev-r5 → **SHIP 0.92** (every text item verified
in-tree; Addendum 5 noted as the coordinator's outstanding
item, landed with these records). rev-r6 → **SHIP 0.72** —
transcription accepted once disclosed + proven inert (the hand
proposes, the verifier adjudicates); TTL fully satisfied;
startup non-decoupling accepted under the cycles 22–23
fail-fast precedent; one correction of fact: the
rotation/seed-loss note the fix seat reported was NOT in the
README — the coordinator has since written it (rotation +
seed-loss paragraphs in the supersession section), so the
claim in this record is that it is present NOW. rev-r6's
remaining objections are explicitly claim-framing positions
for the external seats, not code defects.

## Fix round 2 (rev-r3 re-review: F1 fixed, two adjacent windows)

rev-r3's re-review confirmed F1 genuinely fixed (probes P3/P4
clean; case (b) cannot consume against another envelope's
decision) but reproduced two adjacent availability strandings:
F2 — head moves after a decision: the consume refuses
`ceremony_head_regression` (not supersede-required), was
misclassified Burned, and the consume-first short-circuit made
a fresh approval unreachable; F3 — a resume consume that
commits but loses its response loops on already-consumed,
with the genuine-burn exclusion blocking standard recovery.
Both fixed adopter/client-side (structured translations for
head-regression and already-consumed; same-attempt fall-through
to the approval path on pre-commit refusals; `consumed` phase
appended on the certified already-consumed refusal). Final
re-review (fresh seat, adversarial probes incl. double head
move, stale-approval presentation, spoofed-code probes,
already-consumed on a fresh consume): **SHIP 0.89** — no path
burns a pre-commit refusal for a decided movement; the F3
append cannot misclassify (both verifier sources certify the
movement's own consumption) and does not leak into the fresh
path. Two non-blocking observations recorded: the no-approval
fall-through re-pend does not refresh the on-disk report (a
stale-report approval is safely refused, costing one
presentation, self-correcting); a presented stale approval is
moved aside locally although the verifier never spent it (the
approver must re-mint rather than re-drop).

## Reconciled verdict

Blind: three SHIP, one SHIP→FIX (r3), two FIX (r5 text, r6
dissent). After two fix rounds and three re-reviews:
r1 0.86 SHIP, r2 0.86 SHIP, r3 0.89 SHIP, r4 0.88 SHIP,
r5 0.92 SHIP, r6 0.72 SHIP (dissent seat flips; its residual
positions are preserved above and carried into the external
brief as framing questions, per its own closing line that no
remaining objection is a code defect). **Reconciled unanimous
SHIP, provisional on the external seats.** Full suite on the
final tree: 1756 tests OK (skipped=28), coordinator-run.
