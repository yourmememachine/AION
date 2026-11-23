# War-room review record — Cycle 23

Date: 2026-11-23. Subject: cycle-23 working tree (loop pin
hook; production-mode e2e; consumption schema v2 with
bounded recovery cap 2 + supersede rule; crash/restart
coverage; anchored ship recording + real anchors). Build
record: BUILD-CYCLE-23.md. Design contract:
internal/cycle23-work/DESIGN-FINAL.md (R1–R5), plus the
fix-round rulings and DECISION-CONSUMPTION-HEAD.md
Addendum 3. Seat notes: internal/cycle23-work/review-r{1..6}.md
and review-r{1..6}-rereview.md.

## Staffing

3 coder seats designed together (design-a/b/c +
coordinator rulings R1–R5), then built in disjoint file
ownership (3 seats) plus a coordinator-commissioned fix
seat for the two build-phase findings (the ceremony
key-pin namespace collision in trust/client.py — reported
as a finding by build seat 3 per R2's rule, fixed by the
fix seat, NOT silently patched by its finder and NOT part
of DESIGN-FINAL's original build scope; and the supersede
rule in check_head, commissioned after seat 3's
scenario-6 deadlock trace). 6 reviewer seats from other
pods, blind scores locked in state/calibration/
calibration.json (subject `cycle-23-review`) BEFORE
reconciliation; one forced-dissent seat (rev-r6).
External seats seat-gpt / seat-gemini: VACANT at internal
close — the cycle verdict is PROVISIONAL until they are
seated on CROSS-CHECK-BRIEF-CYCLE-23.md.

## Protected file — core/loop.py

`core/loop.py` is in the Protected Gate's PROTECTED_FILES
(cycle 19 Part A). It was changed deliberately this cycle:
the change is minimal (34 diff lines: a keyword-only
`cycle_hook=None`, a read-only property, one post-save
call), was ruled in DESIGN-FINAL R1 from three converging
design seats, and was reviewed specifically by rev-r3.
The gate protects against UNAUTHORISED self-modification
of oversight; this is reviewed integration work — the loop
gains no imports and no trust/signing knowledge, and the
hook is an opaque callable. Standing obligation (rev-r3):
when cycle 23 is eventually recorded in loop state,
`core/loop.py` must appear in its changed paths as a
protected-path item. The diff:

```diff
--- a/core/loop.py
+++ b/core/loop.py
@@ module docstring @@
+An optional constructor-injected ``cycle_hook`` is called once per
+recorded cycle, after the cycle has been persisted: the contract is
+"cycle recorded, pin pending, alert" — a hook failure never
+un-records the cycle and never corrupts state; it propagates to the
+caller, who owns whatever the hook was pending on.
@@ class CoreLoop @@
-    """One state file, sequential gated cycles, atomic persistence."""
+    """One state file, sequential gated cycles, atomic persistence.
+
+    ``cycle_hook`` (keyword-only, default None) is an opaque
+    callable invoked by run_one_cycle once per recorded cycle,
+    after persistence — see run_one_cycle for the contract. The
+    loop neither knows nor cares what the hook does; integrations
+    that must react to a recorded cycle (e.g. pinning its
+    snapshot) inject one instead of wrapping the loop.
+    """
-    def __init__(self, state_dir):
+    def __init__(self, state_dir, *, cycle_hook=None):
         self.state_dir = Path(state_dir)
         self.state_dir.mkdir(parents=True, exist_ok=True)
         self.state_path = self.state_dir / "state.json"
+        self._cycle_hook = cycle_hook
         self.state = self._load()
+
+    @property
+    def cycle_hook(self):
+        """The constructor-injected cycle hook, or None (read-only)."""
+        return self._cycle_hook
@@ run_one_cycle @@
+        When a cycle_hook was injected, it is called exactly once
+        with the recorded entry, AFTER the persistence above has
+        completed — the snapshot-restore path does not run for hook
+        failures. The contract is "cycle recorded, pin pending,
+        alert": a hook exception propagates unwrapped, the cycle
+        stays recorded, and stored state is exactly what the save
+        wrote. Idle cycles (no pickable item) never fire the hook.
         ...
         except BaseException:
             self.state = snapshot
             raise
+        if self._cycle_hook is not None:
+            self._cycle_hook(copy.deepcopy(entry))
         return copy.deepcopy(entry)
```

## Blind scores (locked, subject `cycle-23-review`)

| seat | verdict | score | headline |
|---|---|---|---|
| rev-r1 | FIX | 0.76 | schema v2 mechanics sound; cross-entry lineage incoherence loads; supersede broader than its docstring (fabricated old-pin hash lands) |
| rev-r2 | FIX | 0.78 | supersede rule SOUND (all attacks failed); T8′ defence misattributed for its shape; "race" test was sequential, not concurrent |
| rev-r3 | SHIP | 0.92 | loop diff clean + protected-file reasoning sound; anchored path + real anchors verified independently |
| rev-r4 | SHIP | 0.92 | pin fix weakens nothing; bootstrap sound; claim scope matches evidence; e2e seam correction legitimate |
| rev-r5 | FIX | 0.78 | crash coverage verified genuine; stale docstring claim (pin_adoption), records missing, README wording |
| rev-r6 (dissent) | FIX | 0.64 | supersede is an undesigned verifier-side relaxation; client fix provenance; recovery_of=None sentinel fails open |

## Fix round

All findings addressed (detail in BUILD-CYCLE-23.md):
cross-entry lineage validation at load (rev-r1 F1);
supersede narrowed — never for `burned_unadopted`,
journal-known old-pin seqs hash-bound in both journal
roles (rev-r1 F2, rev-r5 F3); v1 pair cap at load
(rev-r1 F3); authorisation `recovery_of` shape (rev-r1
F4); composed supersede→adopt-refusal test for the ahead
variant, mutation-verified by rev-r2 (rev-r2 F1); TRUE
multiprocess race test — exactly one consumption lands
(rev-r2 F2); both supersede residuals enumerated in the
docstring (rev-r2 F3/F4); pin_adoption docstring scope
rewritten (rev-r5 F1); scenario-4 `lost_pin`-absence
assertion (rev-r5 F4); README updates (rev-r5 F6/F7);
`authorise_pending` append wrapped to PinAdoptionRefused
(rev-r6 F6i). Three test re-pins from the build/fix phase
were ratified by the room: the fix seat's two supersede
re-pins and the coordinator's T8′ third leg, plus the
production-e2e seam correction (patch target moved to the
adopter's own store instance; no assertion changed).

Coordinator rulings inside the fix round:

- **Supersede kept BROAD for primary reasons** (rev-r6's
  branch (ii)): narrowing to depth == MAX was rejected —
  depth measures the recovery chain, not artefact
  retention, which the verifier cannot observe; a depth-0
  head with a discarded pair is the proven deadlock. The
  rule is recorded as a designed ruling in Addendum 3 in
  plain words (not euphemised as merely "narrowed") and
  put to the external seats as its own numbered question.
- **Client pin fix provenance**: recorded in
  BUILD-CYCLE-23 as a coordinator-commissioned fix on
  seat 3's reported finding, latent since cycle 22 — not
  retroactively placed inside DESIGN-FINAL's scope.

## Re-review scores (subject `cycle-23-rereview`)

| seat | verdict | score |
|---|---|---|
| rev-r1 | SHIP | 0.95 (after two targeted strengthenings, below) |
| rev-r2 | SHIP | 0.92 |
| rev-r3 | SHIP | 0.92 |
| rev-r4 | SHIP | 0.92 |
| rev-r5 | SHIP | 0.90 (conditional on the records — met by this commit) |
| rev-r6 (dissent) | SHIP | 0.78 (conditional on the records — met by this commit; dissent preserved below) |

rev-r1 held FIX twice more on the same bounded class
(load coherence): first, grounding accepted ANY earlier
same-pair entry (branched lineages loaded) → strengthened
to immediate-predecessor grounding + duplicate
authorisation_id refusal + the append-side kind guard
(rev-r6 N1); second, a v2 primary could re-root an
already-consumed pair → refused at load. Both fixes are
one-condition strengthenings with the append-reachability
argument recorded; rev-r1's final probes (9-case battery)
confirm no append-reachable history is refused.

## Verdict

**SHIP (internal, reconciled unanimous) — PROVISIONAL**
on the external seats. Full suite at commit: 1620 tests
OK (skipped=28). Cycles 14–16 remain HELD: this verdict
does not release them; only external reconciliation on
CROSS-CHECK-BRIEF-CYCLE-23.md can do that.

## Dissent preserved — rev-r6 (forced dissent)

First round FIX 0.64; re-review SHIP 0.78, expressly
conditional on the records landing (Addendum 3 + this
build/review record in the commit, the brief posing
supersede as its own question) — the condition is met by
the commit that contains this record, and rev-r6's SHIP
is void if it were not. Preserved positions:

- The broad supersede rule's remaining cost is
  liveness/fairness (an authorised primary can abandon a
  retained, adoptable burn), accepted by the room as a
  designed ruling for the external seats to judge.
- The `recovery_of=None` sentinel (F3): NOT discharged —
  accepted as a non-blocking residual. Correction to the
  coordinator's framing, recorded: `verifier_main` threads
  `issued.get("recovery_of")`, which yields None (the
  sentinel) for v1 issuance entries; non-blocking because
  authorise now always writes v2 and ceremony TTLs have
  expired any real v1 envelope, and the sentinel can only
  bind to the exact current head burn.
- T8′ raw-library non-regression still lives only in
  `PinStore.adopt`'s context binding; nothing at the
  `reanchor_pin` library level prevents returning a
  regressed pin to a caller that adopts it blindly.
- N2 (low): cross-entry load validation is coherence, not
  provenance — it validates the lineage graph, not
  head-at-write; future lineage changes must migrate the
  loader first.
