# REVIEW — Cycle 32 war room (proof-carrying self-improvement prototype)

NOTE on numbering: a concurrent scheduled-build cycle is also
using the number 32 (ship-tx post-settlement re-verification;
its brief is internal/CROSS-CHECK-BRIEF-CYCLE-32.md and its work
files design-a/b/c + review-r1..r6 in internal/cycle32-work/).
This record covers ONLY the proof-carrying cycle commissioned
directly by Dilip. The two cycles' files were kept disjoint;
renumbering one of them is a follow-up for the coordinator.

Six internal seats, blind, scores locked before discussion;
R6 forced dissent. External seats: brief prepared
(internal/CROSS-CHECK-BRIEF-CYCLE-32-PROOF.md); verdict
PROVISIONAL until the parent seats ChatGPT/Gemini — under the
2026-11-26 rule the external review runs at least 2 rounds.

## First round — FIX (no SHIP)
- R1 correctness FIX 0.92: checker executed argv even for
  artefacts that failed binding (design §6 early-stop not
  implemented); changed_files never re-derived; post/base
  probes ran on live trees with no re-hash; tree-hash format
  diverged from §4 (no proof-tree/1 wrapper, no scope dedup);
  mutation validation late, no-op undetected; schema laxness;
  symlink prefix gap.
- R2 adversarial FIX 0.90: harness-presence gaming (a check
  whose harness is itself new "discriminates" by absence alone
  — undisclosed); execution-before-binding reproduced with a
  marker file; live-tree runs reproduced (verify returned ()
  on a dirtied tree); changed_files truncated to [] verified
  (); NUL argv crashed verify with ValueError, breaking the
  never-raises contract. Forged-evidence, path-traversal and
  duplicate-key attacks FAILED (evidence is genuinely a
  prediction; traversal refused).
- R3 claim FIX 0.82: "shown to fail" overstated the
  timeout/cannot-run probe path (mechanism showed "not pass");
  module docstring misattributed evidence to the checker
  (evidence is builder-run); design-final claimed checker
  behaviours the code did not have; claim pin covered one file
  and five spellings only.
- R4 integration SHIP 0.93: no protected file touched; seam
  delegation correct; refusal provably before burn; lint
  green. Nit: root= kwarg collision raised TypeError.
- R5 tests/evidence FIX 0.80: demo script unrunnable as
  shipped (sys.path off by one, stale docstring path);
  real-change artefact had no in-repo generator; missing
  base-tamper coverage. All required refusal cases otherwise
  genuinely tested and non-vacuous; demo artefact's hashes
  independently re-verified.
- R6 forced dissent FIX 0.88: the name "proof-carrying"
  over-claims (this is test re-execution with hashing, not
  Necula-style proof); unkeyed hash + author-chosen checks =
  a valid artefact for a bad change is constructible;
  implementation contradicted the design's execution ordering
  and scratch-copy rules; demo artefact's only invariant was
  substring presence. Set explicit withdrawal conditions
  (1)–(4) + (5a rename or 5b keyed authenticity/manifest
  binding).

## Fix round — F1–F17 (one coder seat, reconciled list)
Execution ordering restored (malformed and hash-mismatch
return alone; steps 3–5 accumulate and return before ANY
execution); all probes in scratch copies with uniform basename
"tree"; record_ship_with_proof re-hashes the post tree after
verification; changed_files re-derived and compared exactly;
tree hash per §4 (proof-tree/1 wrapper, path dedup, reusing
signing.gate_decision canonicalisation); mutation pre-validated
(no-op -> mutation_invalid; mutation path referenced by argv ->
mutation_invalid); schema tightened; symlink prefixes refused;
probes require an OBSERVED non-zero exit (design §6 erratum
recorded, original text retained); NUL argv refused, verify
never raises; builder gains optional target + _now() stamping;
root= kwarg guard; demo fixed and given an in-repo generator;
the demo artefact gains a real invariant executing the cycle-32
test suites through an output-normalising check
(tests/cycle32_suite_check.py); claim pin extended to 9 phrases
and extended to design-final.md; terminology + harness-presence
limits disclosed in design §7. One deviation, recorded: the
builder's default-mutation fallback (first changed file) is
retained where design §5's letter would refuse — follow-up.

## Re-review — SHIP
- RR1 correctness SHIP ~0.9: every fix verified in code and
  by ad-hoc probes (incl. a third pre-execution gate case);
  remaining notes cosmetic (changed_files divergence reported
  as post_tree_mismatch; builder runs checks on the live post
  tree by design §5, fails closed on cwd-dependent output;
  residual TOCTOU is architectural).
- RR2 claim SHIP (high): CLAIM now literally accurate;
  docstring attribution corrected; §6 erratum + §7 additions
  present with originals retained; pin genuinely pins.
  Non-blocking prose notes only.
- RR3 dissent seat: conditions (1)–(4) MET item by item;
  dissent held on (5) alone with a stated minimal flip:
  a required hash-bound "mechanism": "check-carrying/1"
  artefact field (or a FORMAT rename). The coordinator landed
  the field (builder emits it, schema requires the exact value,
  regression test test_mechanism_field_required_and_exact,
  design §11) — the dissent's own stated condition for
  withdrawal, so the dissent is withdrawn on its terms.

## Final verdict
SHIP (internal, reconciled unanimous after the fix round and
the mechanism-field landing) — PROVISIONAL pending the
external seats (2 rounds per the 2026-11-26 rule). Full suite
and demo evidence: internal/BUILD-CYCLE-32-PROOF.md.
