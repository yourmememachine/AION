# Blind review brief — Cycle 16: pin ceremony hardening

For external seats seat-gpt / seat-gemini. No internal verdicts
or scores are included in this brief.

## What was built (signing/pin_ceremony.py only; no protected
paths touched — eval/, core/, oversight/ unchanged)

Cycle 15 built the snapshot pin ceremony (advance_pin /
reanchor_pin / verify_ceremony_record). The combined external
review of cycles 14+15 returned FIX from both seats, converging
on: (1) operator authority is caller-supplied and circular;
(2) evidence is a bare unequal hash (provenance "theatre");
(3) atomic pin+audit persistence missing; (4) rollback-resistant,
verification-gated ceremony history missing; (5) re-anchor lacks
anti-fork/stale-head constraints; (6) MAC key separation
unspecified; plus classify-vs-reanchor eligibility must share
exact comparison logic, and strict_reasons was trusted, never
recomputed or bound to the pin/candidate.

Cycle 16 builds only what is closable inside the module, and
states the rest as open in the module docstring:

1. Recomputed eligibility: for chain_gap_recovery, reanchor_pin
   now recomputes the strict result itself via
   verify_snapshot_for_state against the captured old pin and
   this candidate, and requires the caller-supplied
   strict_reasons to equal the recomputed ("chain_gap",)
   exactly. Shared sole-chain-gap predicate
   (_is_sole_chain_gap) used by both classify_verification and
   reanchor_pin.
2. _candidate_relation is the only sequence arithmetic;
   a gap-distance candidate whose prev_snapshot_hash names the
   pin itself ("gap_prev_is_pin") is refused as an integrity
   failure.
3. Optional ceremony_history parameter: every record must
   verify under the ceremony key; evidence reuse within the
   history or against this ceremony is refused; a candidate
   already ceremonied as a target is refused (replay); a
   candidate behind the history's attested head, or signed
   before the latest ceremony in it, is refused. History can
   only refuse, never grant. Default None = not supplied,
   checks skipped — stated honestly in the docstring.
4. verify_ceremony_record: a one-step record (new == old+1,
   which reanchor_pin can never issue) now reports
   not_a_gap_reanchor; optional expected_old_pin /
   expected_new_pin context — a record replayed against a
   different pin state reports pin_context_mismatch.
5. Single clock capture: one `moment` feeds both the
   verifier's freshness check and the record's performed_at.

Explicitly NOT claimed as fixed: (1) independent operator
authority (needs a protected source — owner decision pending);
(2) evidence provenance (a bare digest still passes when no
history is supplied); (3) atomic persistence; (6) key
separation (stated as required future work, not enforced).

## Test evidence

- tests/test_signing_pin_ceremony.py: 24 tests (15 prior + 9
  new cycle-16 tests covering forged strict_reasons with a
  wrong pin binding, gap_prev_is_pin, strict_reasons corpus
  never raising TypeError, history evidence reuse / tampered
  history / duplicate evidence / replayed target / behind-head,
  one-step record, pin-context verification).
- Signing suites combined and full suite: see the cycle record
  (internal/BUILD-CYCLE-16.md) for the final totals.

## Questions for the seats

1. Does the recomputation actually bind eligibility to the pin
   and candidate, or is there a remaining path where a caller
   tuple is trusted?
2. Is the history head/staleness logic sound, or can it refuse
   legitimate recoveries / accept stale ones?
3. Does anything in cycle 16 over-claim items (1), (2), (3) or
   (6), which remain open?
