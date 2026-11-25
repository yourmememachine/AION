# Cycle 30 — coder C (adversarial): can a FRESH wired attempt reach supersession-pending?

**Verdict: NO — not in the sequential wired composition.** Every
candidate geometry is killed at one of three gates, and the two
shapes that pass the reconciliation pure function in isolation
collapse at the wired level (pin-store consistency / resume
interception / authorisation-id binding). One honest residual
remains, outside the sequential model: an interleaved external
burn between reconciliation and consume (§6). It is the designed
pending stop working, not a sequential counterexample.

Scope of "fresh wired attempt" (the cycle-29 follow-up,
`wired-pending-reachability`): one `snapshot_and_adopt` through
`trust/runner.py` — which always supplies both history providers
(`runner._history_providers`; a missing `AION_VERIFIER_HOME`
refuses at config time, so a runner attempt is never unwired) —
that is **not** a resume: no retained
`supersession_pending_approval` journal entry matches its
candidate + old pin (`pin_adoption._find_pending_supersession`).
Reaching pending means `PinSupersessionPendingApproval`
(runner exit 7 for an adopt step; exit 5 via a cycle-step hook,
same adopter logic, no new geometry).

## 1. The conjunction pending requires

A fresh pend happens only in `_reanchor`'s fresh-ceremony
handler (`CeremonySupersedeRequired` → `_stop_at_pending`), so
all three must hold in one attempt:

- **G1 (reconciliation passes)** — step (3b),
  `_reconcile_history` → `history_reconciliation.find_missing_history`:
  every consumption entry relevant to the candidate
  (`E.new_seq < Cs`, or `E.new_seq == Cs` with a different hash)
  is pair-covered, supersede-excused (fully bound, new side
  landed), or head-excused (head entry only, id in
  `known_unadopted_authorisation_ids`, **and** `E.new_seq == Cs`).
- **G2 (verifier supersede geometry)** —
  `ledger.CeremonyConsumptionLedger.supersede_head` /
  `check_head`: candidate **strictly ahead** of the consumption
  head (`Cs > Hs`), old pin **strictly behind** it
  (`Ps < Hs`), reason not `burned_unadopted` / not
  `initial_anchor`, lineage not a recovery, old-pin hash binding
  against the journal-recorded hashes for `Ps` holds.
- **G3 (no decision)** — no journaled supersession decision
  bound to *this* envelope's `authorisation_id` (the verifier
  looks the decision up by that id itself); a decision bound to
  any other envelope is a mismatch → head regression, not a pass.

G1 and G2 pull in opposite directions on the head entry H:
G2 needs H **unadopted** (old pin still behind it), while for a
candidate beyond H, G1's excuses for H are exactly the ones
that require H to have been **accounted for** — see §3.

## 2. Position-by-position sweep (candidate vs head H = (Hs, Hh))

Notation: pin P = (Ps, Ph); store history R; pending journal J.
Non-head entries are disposed of once, in §4: in any coherent
history they are always accounted for, so H is the only entry
that can be both unaccounted and geometrically live.

### 2a. Behind head — `Cs < Hs`
- G1: H is not relevant (`Hs` is neither `< Cs` nor `== Cs`),
  so reconciliation can pass — G1 is not the killer here.
- Classification / verifier: a gap candidate goes to ceremony;
  `check_head` refuses `cand_seq < head_seq` as head regression
  → generic failure in `_reanchor` → `PinAdoptionBurned`
  (exit 4). A dense candidate classifies `ok` only against the
  pin, and the pin cannot be ≥ H while H is unadopted (§3).
- **Outcome: burned / refused. Never pending** (supersede
  requires strictly ahead).

### 2b. At head, exact pair — `Cs == Hs`, `Ch == Hh`
- The only way to *present* the exact pair is the retained
  burned candidate: `payload_hash` covers `signed_at` /
  `expires_at` (`signing/state_snapshot.sign_state_snapshot`),
  so a fresh signing of identical state bytes yields a
  different hash. Exact pair therefore implies a genuine burn
  in J for this candidate + old pin.
- G1: H is not relevant (the at-sequence relevance clause
  requires a different hash); the excuse is never consulted.
  (Cycle-29 pinned shape.)
- Verifier: reason is computed `burned_unadopted`
  (`_find_unadopted_burn`); `supersede_head` returns None for
  that reason by construction. Depth < cap 2 → recovery
  **lands** (exit 0). Depth ≥ cap → issuance itself refuses
  (`ceremony_recovery_unproven`, verifier step 5b) →
  `PinAdoptionRefused`. Stacked double burn, same pair
  (depth-1 head): both entries are exact-pair, neither is
  relevant, recovery at depth 2 lands; a third is cap-refused
  at issuance.
- **Outcome: lands or refused. Never pending.**

### 2c. At head, different hash — `Cs == Hs`, `Ch != Hh`
- G1: H **is** relevant. Its one live excuse is the head
  excuse — this is the single case the post-cycle-28 scoping
  (`E.new_seq == candidate_seq`) deliberately retains — and it
  fires only if `Ha ∈ known_unadopted`, i.e. J proves H a
  genuine burn. Pair coverage would need a store record with
  pair `(old, Cs, Ch)`: adopting that record would have set
  the pin to `(Hs, Ch)` (§3), contradicting the fork geometry.
  A supersede decision abandoning H must, by `supersede_head`
  at its own issuance, name a candidate **strictly ahead** of
  H, so its candidate pair can never equal `(Hs, Ch)` for the
  decision-candidate excuse clause.
- Candidate construction defeats the shape anyway: if J holds
  the burn, step (3) re-presents the **retained** envelope
  (exact pair) — the attempt collapses to §2b, never to a
  different hash. If J does not hold it (journal lost / burn
  made by another adopter), `known_unadopted` is empty, the
  excuse fails, and **G1 refuses** (`pin_store_history_incomplete`,
  exit 6) before any ceremony.
- If the excuse did fire (J holds the burn — but then the
  candidate is the retained one, contradiction above), the
  verifier still kills it: `cand_seq == head_seq`,
  `cand_hash != head_hash` → head regression (fork) →
  `PinAdoptionBurned`. Supersede needs strictly ahead.
  Pre-ceremony exits also exist: `Cs == Ps` with `Ch != Ph`
  is a pin-mismatch integrity failure; `Cs == Ps + 1` shapes
  classify integrity failure, not sole `chain_gap`.
- **Outcome: refused at G1, or burned at the fork rule.
  Never pending.**

### 2d. Beyond head — `Cs > Hs` (the only G2 geometry)
Canonical sibling shape (pin 13, head burn 13→15, candidate
16), plus every excuse variant:

- **D1, head unaccounted (canonical):** H relevant
  (`Hs < Cs`). Head excuse fails on its at-sequence scoping —
  the cycle-28 seat-gpt fix removed exactly this reach,
  because beyond-head it would silently excuse an adopted
  record's disappearance (adopted-line loss + store restore
  is indistinguishable from a genuine burn at this layer).
  **G1 refuses, exit 6, before authorisation/consume.** This
  also pre-empts the dense sub-case `Cs == Ps + 1`: step (3b)
  runs before classification, so even an `advance_pin`
  candidate beyond an unaccounted head is refused, never
  advanced and never pended.
- **D2, head pair-covered:** a store record attests H's exact
  pair. Killed by pin-store consistency (§3): that record
  forces `Ps ≥ Hs`, and `Ps == Hs` forces `Ph == Hh` — the
  old pin is **at** the head, not behind it, so G2's
  `Ps < Hs` fails. The consume then either advances
  (`Cs == Ps + 1`, successor) or lands as an ordinary primary
  gap ceremony (old-at-head passes `check_head`). **Lands.**
- **D3, head supersede-excused:** three clauses, all collapse.
  (i) Replacement record in R → its adoption set the pin to
  the decision's candidate, which was strictly ahead of H;
  H is then non-head and the live head is that landed consume
  — the attempt is at/ahead-of-pin, §2a/§2b territory.
  (ii) Decision's candidate pair pair-covered in R → same
  collapse as D2 via §3. (iii) Decision's candidate pair ==
  candidate under attempt → at the pure-function level this
  **passes G1** (see §5), but wired: the decision binds
  `new_authorisation_id` to a *prior* envelope, while a fresh
  attempt's envelope is authorised only **after** step (3b)
  with a new id — G3's verifier lookup by the fresh id finds
  no decision (good for pending) but the candidate *hash*
  can only equal the decision's candidate hash if it is the
  retained superseding candidate, and a movement holding
  that retained envelope + a journaled decision is, by
  `_find_pending_supersession` / `_pending_phases`,
  intercepted as a **resume** (`supersede_decided`
  consume-first, or approval presentation) before any fresh
  ceremony is contemplated. Fresh-signing a new hash breaks
  the pair equality and G1 refuses. **Resume or refused —
  not fresh.**
- **D4, old pin not behind head:** `Ps == Hs` (hash must equal
  Hh or the store document itself is inconsistent, §3) →
  ordinary advance/primary, lands. `Ps > Hs` (pin legitimately
  ahead via `advance_pin` movements the journal never sees) →
  `check_head` old-ahead passes, candidate ahead passes,
  **lands** — no supersession is needed, so none is requested.
  `Ps < Hs` with a fabricated old hash → `supersede_head`
  hash binding fails → head regression → burned (binding is
  not the canonical blocker; in the coherent shape Ph *is*
  journal-recorded, as H's old side / the genesis target).
- **D5, genesis (`old_pin is None`):** the one beyond-head
  shape that **passes G1 unconditionally**
  (`genesis_baseline = (old_pin is None)`). Killed at G2:
  the reason is `initial_anchor` and there is no old pin —
  `supersede_head` excludes both, and `check_head` refuses
  `initial_anchor` against a non-empty journal as head
  regression → burned. (Empty journal: no head, no supersede,
  genesis lands.)
- **D6, reason manipulation:** unavailable. The reason is
  computed in `_reanchor`, never caller-chosen: fresh
  beyond-head ⇒ `chain_gap_recovery`, which satisfies G2's
  reason conditions — reason is honestly **not** a blocker;
  G1 is. `burned_unadopted` is reachable only via the
  exact-pair burn match (§2b), which fails G2's geometry.

### 2e. Resume re-pend (not fresh, for completeness)
`_resume_pending` with no inbox approval re-raises pending
with **no new ceremony and no fresh verifier refusal** — the
only wired exit-7 path that survives cycle 28. But its entry
condition is a pre-existing pending entry, which could only
have been created by `_stop_at_pending` after a verifier
supersede-required — i.e. by an attempt that itself passed
G1+G2+G3 (an unwired attempt, a pre-cycle-28 attempt, or the
§6 interleaving), never by a fresh wired attempt in a
composition that was wired from genesis. Within one
continuously wired composition the pending state has no
seed. `adopt_returned` likewise cannot pend: no consume, no
reconciliation, only `PinStore.adopt`.

## 3. Structural lemma — pin-store consistency closes D2/D3

`signing/pin_store._check_consistency` runs on every verified
load (`read_all`, the adopter's step (1) capture): if the
history's maximum-`new_cycle_seq` record is at seq S, a pin
with `seq < S` — or `seq == S` with a different hash — makes
the combined document **internally inconsistent** and the
capture refuses. Pin and history are one document, restored
together. Hence "history accounts for H" (a record whose new
side is H's target, at seq Hs) and "pin behind H"
(`Ps < Hs`) cannot coexist in any store the wired adopter
will even read. Pair coverage of the head and a behind-head
pin are mutually exclusive **by the store's own load rules**,
not by reconciliation policy. The same argument covers the
supersede-excuse clauses (i)/(ii): a landed replacement is a
record, and a record moves the pin.

## 4. Why non-head entries never rescue or block independently

A consumption entry becomes non-head only when a later
consume lands on top of it, and that landing is exactly one
of: a recovery (same pair — the adopted recovery record
pair-covers both entries), a supersede (a bound decision
whose new side landed — the supersede excuse, fully bound),
or an ordinary primary adopted on top (the entry's own record
was adopted for the head to have been reachable in a coherent
store). So in every reachable coherent journal, all non-head
relevant entries are already accounted for; the head is the
sole entry that can be consumed-but-unadopted, and §§2–3
dispose of it at every candidate position. Conversely a
tampered journal (duplicate `authorisation_id` / duplicate
`seq`) is refused by reconciliation's input validation, and
the wired providers load the real anchored ledgers fresh per
call — fabricated entry/decision lists exist only at the
pure-function level, where the module docstring already
scopes the excuse list as caller-attested.

## 5. Pure-function near-misses (pass `find_missing_history`, dead when wired)

1. Beyond-head + decision whose candidate pair == the
   candidate under attempt → excused. Wired-dead by §2d-D3:
   hash equality forces the retained envelope, retention
   forces resume interception, and the decision's
   authorisation binding cannot name a not-yet-issued fresh
   envelope.
2. Beyond-head + pair-covering record present → excused.
   Wired-dead by §3: the same document cannot hold that
   record and a behind-head pin.
3. Beyond-head + `genesis_baseline=True` → nothing missing.
   Wired-dead: the flag is not caller-set; the adopter passes
   exactly `old_pin is None`, and that shape fails G2 (§2d-D5).
4. Beyond-head + head id in a fabricated
   `known_unadopted_authorisation_ids` → still **refused**
   even at the pure-function level (at-sequence scoping);
   and wired, the list is derived solely from the adopter's
   own pending journal (`_known_unadopted_authorisation_ids`
   ← `_genuine_burn_entries`), never supplied.

## 6. Residual — interleaving, outside the sequential model

No lock spans steps (3b)→consume: reconciliation loads the
journals fresh, and the verifier reloads them at consume, but
a **second ceremony actor** (another adopter / direct client
with operator + evidence access) that burns a movement
`(Ps → X)`, `Hs_accounted < X < Cs`, *between* a fresh wired
attempt's reconciliation and its consume would present that
attempt's consume with a genuinely unaccounted head, old pin
behind it, old-hash binding satisfied via the previously
accounted head — and the verifier would correctly answer
supersede-required, pending the attempt. This does not
contradict the verdict: it breaks the sequential,
single-adopter assumption every wired test and the runner's
own step loop are built on (the runner returns on the first
non-zero step outcome, so no plan step compounds a burn into
a later step of the same invocation), and the pend it
produces is the mechanism's designed response to a head that
really did appear unaccounted mid-flight. Closing even this
would need a reconciliation-to-consume atomicity guarantee
across two processes — a design change, recorded here as the
adversarial seat's one open note, not as a sequential
counterexample.

## 7. Conclusion

Fresh wired pending is unreachable for a structural reason,
not a missing test: **the verifier's supersede geometry
requires an unadopted head with the pin behind it, and
reconciliation — backed by the pin store's own consistency
rule — admits a beyond-head candidate only when the head is
accounted for, which (pair coverage, landed supersession, or
a pin at/ahead of the head) destroys that geometry; at the
head's own sequence the candidate is either the retained
exact pair (recovery, never supersede) or a fork (regression,
never supersede); behind the head is regression; genesis is
excluded from supersede by reason and by the missing old
pin.** Pending in the wired composition is therefore
resume-only, reached by re-presenting a movement pended
under conditions the current wired gates no longer create —
which is the precise form the cycle-29 open follow-up
`wired-pending-reachability` should be closed in, unless the
war room *wants* a fresh reach and is willing to change
reconciliation's beyond-head scoping (a design change, with
the adopted-line-loss compound state as its stated cost).
