# CROSS-CHECK 29 — external war-room seats

Blind brief: internal/CROSS-CHECK-BRIEF-CYCLE-29.md (no
internal verdicts included). Both services reachable and
signed in; brief pasted verbatim in new conversations.

- seat-gpt (ChatGPT) — SHIP 0.94. Pinning observed recovery
  behaviour + correcting the cycle-28 claim is the correct
  closure; changing production code to make the claimed
  pending transition reachable would invent a guarantee the
  design does not establish. Caveat: this does not establish
  pending is unreachable for every candidate/state; keep
  reachability claims scoped to the tested composition.
- seat-gemini (Gemini) — SHIP 0.88. Same closure, conditional
  on burned_unadopted recovery at the head sequence being
  intended design rather than a silent bypass (disposition:
  the recovery mechanism predates cycle 28, is bounded and
  lineage-bound, and is pinned by the crash/recovery suites;
  recorded in BUILD-CYCLE-29.md). Rated the refusal
  distinction partial: the new test contrasts refusal via
  the sibling beyond-head exit-6 test in the same file.

Reconciliation: both SHIP; their scoping caveats match the
fix-round narrowing of the test comment. No external finding
required a production change.
