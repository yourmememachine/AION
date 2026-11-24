# Review seat rev-r6 (FORCED DISSENT) — cycle 28, blind

VERDICT: FIX 0.42

The strongest honest case is FIX, not SHIP. The pure function is
carefully written, but the shipped production system detects nothing,
the one excuse claimed to be head-scoped is demonstrably not, and the
detection primitive trusts its decisive input completely.

1. Claim theatre — no production path enables it (holds completely):
   defaults None everywhere; trust/runner.py:321 passes no providers;
   zero non-test callers. Deployed behaviour is byte-for-byte cycle 27.
   The cycle-21 defence fails: there the consumer WAS wired.
2. The known-unadopted excuse is NOT head-scoped — reproducible:
   head_id = entries[-1].authorisation_id compared by id, never entry
   identity/seq. Journal e1(seq1, auth A), e2(seq2, auth A), empty
   store, candidate seq 3, known_unadopted=(A,) returns () — BOTH
   entries excused, including non-head e1. Test_09 cannot catch it
   (distinct ids). Duplicate journal authorisation ids nowhere refused.
   This alone is a FIX.
3. Detection-shaped seam: the pure function verifies nothing about the
   journal — no duplicate/monotonic seq, no chain integrity, no
   anchored head. Provider returning () or a truncated journal passes
   silently. from_home inherits chain verification from the ledger
   load, but the adopter accepts any callable and nothing at the call
   site requires the from-home helper.
4. Pending-journal excuse depends on restore granularity: (a)
   file-granularity restore leaves the excuse alive indefinitely
   (combined with 2, same-id earlier gaps excused too); (b)
   directory-granularity restore after a genuine burn deadlocks —
   refusal at (3b) before the recovery branches can run, and cycle 28
   ships NO reconciliation/repair procedure, so "an operator must
   reconcile" names an act the system provides no way to perform.
5. Genesis baseline is an unbounded, unbound bypass: old_pin None ⇒
   no check ever, no bound on entries baselined away, no record it
   happened. Deserves a bound or an attested reason.
6. Same-seq fork clause hole at pair-coverage layer (partially holds):
   pair equality is the whole evidence; relevance ignores old side.
7. Anchoring was the honest mechanism (judgement): the design's two
   rejection reasons are weak — detecting any rollback is the point
   of an anchor, and diagnosis is convenience, not correctness.
8. Tests pin less than the claims; failing-first.md misdescribes
   test_17 (claims "successful re-anchor"; the test expects
   PinSupersessionPendingApproval).

What would change this verdict: wire providers in trust/runner.py (or
rename the cycle honestly and keep the follow-up open); fix the head
excuse to compare the head entry and refuse duplicate journal ids/seqs;
give genesis baselining a bound or attested reason; add the finding-2
and truncated-journal tests.
