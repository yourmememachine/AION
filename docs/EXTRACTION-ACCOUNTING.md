# Extraction Accounting — Sealed-Eval Oracle (Trust Boundary v3, item 3)

This document states the exact accounting rules for the sealed-eval
oracle, as enforced in code (`trust/budgets.py`,
`trust/verifier_main.py`, `trust/ledger.py`). It answers the v2
cross-check finding F3 (budgets bound queries, not
disclosed information; identity issuance / Sybil unspecified) and
the record-reuse and identity points from external review. The automated
attack harness that demonstrates these rules against the real
verifier subprocess is `tests/test_trust_extraction.py`; the
single-use consumption tests are `tests/test_trust_consumption.py`.

What this document is, stated plainly: an **accounting
mechanism** (the caps, probe rules and information bound of
(i)–(iv), enforced in code) **plus empirical measurements**
against the specific attack strategies the harness implements.
It is never a general confidentiality guarantee: no measured
recovery result in the harness or in this document bounds what
a different strategy, set size, entropy or alphabet would
recover (see the end of (iv)).

## (i) What one response discloses

One `sealed_eval` response discloses exactly **one aggregate**: the
agreement count `correct / n` (returned as the signed record's
`correct`, `n` and `score`) for the submitted positional transcript
against the sealed set. It never discloses per-position results:
no response field, error document, or ledger entry names which
positions matched. The count takes one of `n + 1` values
(`0 … n`), so the information per response is at most
**log2(n + 1) bits** about an n-item sealed set.

**Scope: that bound covers the SCORE channel only.** The same
record also carries `manifest_hash`, `registry_digest`, `n` and
`version`, and the bound above says nothing about them. In
particular the `manifest_hash` is a public commitment elsewhere
in the system (it is the gate's `sealed_hash` /
`expected_sealed_hash`), but for low-entropy answers it is also
an offline guess-verification oracle: a guessed sealed item (or
set) can be hashed offline and checked against the manifest /
content hashes with no query, and therefore no budget burn, at
all. The log2(n + 1) accounting must not be read as covering
that channel.

## (ii) Caps

Enforced inside the verifier (`BudgetStore.check_only` /
`BudgetStore.record`), **before the registry is opened**:

- **25 recorded evaluations per proposal scope**
  (`AION_VERIFIER_PROPOSAL_BUDGET`, default 25).
- **500 recorded evaluations per budget identity**
  (`AION_VERIFIER_IDENTITY_BUDGET`, default 500), spanning all
  proposal scopes.

The gate is two-phase: `check_only` runs before the registry
opens and records nothing; `record` runs only after the verifier
has validated the transcript itself (answer count). A transcript
refused by the verifier's own validation — garbage length, failed
/ garbage transcripts generally — **burns no budget**: failed
attempts are not recorded, do not increment any count, and do not
count as probes. Only a transcript that passes validation and is
actually evaluated is recorded.

One such refusal itself discloses something, stated plainly:
`answer_count_mismatch` discloses the exact sealed count `n` to
an unauthenticated caller with no budget burn — its error detail
states how many sealed items the transcript was checked against.
That is a real, if small, disclosure; it is not treated as a
secret here because `n` also ships in every legitimate record
(the payload's `n`, alongside `correct` and `score`).

## (iii) Probe rules

All detection is **identity-scoped**: a new transcript is compared
against **every** prior transcript recorded for the identity,
across all proposal labels (the proposal label is caller-chosen
and scopes only its own cap).

- **Replay refused.** A byte-identical resubmission of a prior
  transcript by the same identity, under any proposal label, is
  refused (`transcript_replay`). It is not recorded again.
- **Near-duplicate definition.** A transcript is a near-duplicate
  probe when, against **any** prior transcript of the identity
  (across labels), **either** its positional similarity is
  **≥ 0.8**, **or** the absolute number of differing positions is
  **≤ 2**. (The absolute rule exists because the fraction rule is
  blind exactly where extraction is cheapest: for small n a
  one-position probe has similarity below any sane fraction
  threshold.)
- **Tolerance and latch.** The **first 2 probes are tolerated**:
  they are counted (identity-wide) and recorded as spent
  evaluations. The **3rd probe latches the probed transcript
  family** — the prior transcript the tripping probe matched is
  recorded as a blocked family anchor for the identity — and the
  tripping probe itself is refused (`adaptive_query_detected`)
  and not recorded as an evaluation. Every further near-duplicate
  of a latched family from that identity is refused, under any
  proposal label.
- **Limit reached.** Once an identity's probe count has reached
  the limit (3), **any** further near-duplicate — of any family —
  is likewise refused and latches its own family.
- **Persistence.** The probe count and the family latch are
  persisted in the budget store on disk (hash-chained; see
  `trust/budgets.py`). Restarting the verifier does not clear
  them. Transcripts that are not near-duplicates of a latched
  family remain allowed, subject to the caps in (ii).

## (iv) The resulting bound

Per budget identity:

- at most **500 aggregate disclosures** in total, and
- totalling at most **500 · log2(n + 1) bits** of information
  about an n-item sealed set (25 disclosures per proposal scope).

Adaptive refinement — each refinement step must stay within 2
differing positions (or ≥ 0.8 similarity) of a prior transcript
to learn from the score delta — is capped at **2 tolerated
probes per identity**: the 3rd near-duplicate latches its family
and is refused, and no further near-duplicate of that family is
ever evaluated for that identity.

The measured results behind this section are empirical, and
their scope is exactly the fixture that produced them: a
sealed set of **n = 8** items whose answers come from a known
**4-token alphabet given to the attacker**, attacked with the
harness's three implemented strategies — coordinate descent
recovered **2 of 8** positions before the latch stopped it,
label rotation recovered **2 of 8** (identical outcome, as
(iii) predicts), and group testing recovered **4 of 8**
positions in 20 attempted queries (19 evaluated) under a
60-query allowance — with the attribution stated exactly:
the non-adaptive block-pool phase alone recovers **0 of 8**
(16 consistent assignments remain, none forced); the measured
4/8 comes from group testing **plus** the tolerated
near-duplicate refinement probes (the size-2 pool refinements,
which differ from their parent pools in exactly 2 positions:
2 tolerated, the 3rd latches and is refused, resolving the
first block's 4 positions and leaving the remaining block
unresolved). "At most 4/8 recovered" is a
measurement of those strategies against that set; it must not
be read as a guarantee for other set sizes, other entropies
or alphabets, or adaptive strategies the harness does not
implement (for example cross-proposal reconstruction that
combines aggregates across scopes in ways the implemented
attackers do not). For regimes the measurements do not cover,
only the accounting bound above applies — and, as the next
paragraph states, for small-n / low-entropy sets that bound
can guarantee nothing.

That latch is not a bound on extraction in general.
Non-adaptive multi-partition designs are bounded only by the
aggregate cap above — 500 disclosures totalling at most
500 · log2(n + 1) bits — and for small-n / low-entropy sealed
sets the cap can exceed the set's total entropy, in which case
the bound guarantees nothing: an attacker whose query budget
buys more bits than the sealed set contains is not constrained
by the accounting, whatever the probe latch does. Non-adaptive
queries (≥ 3 differing positions from every prior) remain
possible within the caps, each disclosing only the single
aggregate of (i) — the group-testing attacker's block-pool
phase in `tests/test_trust_extraction.py` is exactly such a
design (and, as (iv) states, that phase alone recovers 0/8;
its 4/8 total additionally required the tolerated
near-duplicate refinement probes, which the latch bounds) — so
for those regimes the concrete-attacker measurements are the
operative evidence there, not the cap.

## (v) Identity

The budget identity is the verifier deployment's **configured
registry actor**: `AION_VERIFIER_ACTOR_ID`, set by the operator
in the root-owned verifier environment file at deployment time.
It is configuration, not a request field.

- **The wire protocol has no identity field.** Request bodies for
  every mode have strict key sets; a `sealed_eval` body carrying
  an `identity`, `actor`, `actor_id`, `signer_id`, or any other
  extra field is a **protocol error (exit 2)** and burns no
  budget. Callers therefore cannot select, rotate, or multiply
  identities: there is nothing on the wire to rotate.
- A second budget identity exists **only if the operator
  provisions a second verifier configuration** (a second
  deployment with its own `AION_VERIFIER_ACTOR_ID`, key, and
  verifier home). Identity issuance is an operator provisioning
  act, not something a caller can do.
- Proposal labels are not identities: rotating `proposal_id`
  resets only the per-proposal cap's label accounting, never the
  identity-scoped detection or the 500 per-identity cap (see
  (iii)).

**Residual, stated honestly.** All callers of one verifier
deployment share that deployment's single actor budget. A noisy
(or hostile) caller who can reach the deployment can exhaust the
shared 500 evaluations and the shared probe tolerance, denying
the oracle to the deployment's other callers. That is an
**availability** limit, not a confidentiality one: sharing the
budget never lets a caller exceed the bounds in (iv), attribute
queries to a fresh identity, or learn anything beyond the
aggregates the shared budget allows.

`BudgetStore`'s API takes the identity from its caller
(`check_only(identity, …)`, `record(identity, …)`). That is safe
exactly because its only production caller is the verifier,
which always passes its configured `AION_VERIFIER_ACTOR_ID`;
nothing else in production constructs a `BudgetStore` over the
verifier's budget file.

## Single-use consumption of eval records (companion rule)

Eval records are also single-use **at attestation issuance**:
`issue_attestation` consumes both records in the signing ledger
(`SigningLedger.try_consume_eval_records`, kind `consume`,
format `eval-consumption`) atomically with the check, before
signing, and even when the derived decision is `reject`. Reusing
a consumed record — in the same pair, or in a different pair —
refuses the issuance (`eval_evidence_consumed`), and concurrent
issuance processes racing the same pair produce exactly one
attestation. The gate path does not consume (see
`trust/verifier_main.py`): the attestation's `evidence_ref` flow
legitimately re-presents the records, bound to the single
attestation by `evidence_ref` + scope + signer checks.
