# Cycle 27 — War-room fix round: documentation re-review (docs seat)

Scope: ONLY whether the documentation findings were closed in the
current uncommitted tree. No other slice re-reviewed. Method:
direct reads of the four named surfaces plus a programmatic
allowlist count/set comparison across the three live copies.

## Score: 0.88

## Verdict: FIX

Seven of the eight items are fully closed. Item (5) is only
partially closed: one stale count that r5-2 named explicitly
survives in `trust/wiring.py`. It is a one-line fix, but this
seat cannot call the sweep closed while the exact flagged text
is still in the tree.

## Item-by-item

1. **r4-1 — CLOSED.** `internal/DECISION-CONSUMPTION-HEAD.md`
   gained "Addendum 7 — 2026-11-23 (cycle 27): both remaining
   ceremony journals anchored". It anchors both journals
   (anchor kinds `ceremony-issuance` / `ceremony-supersession`,
   the four new env vars, allowlist 20 → 24, shared loader,
   both commit orders, the append→anchor-update window caveat)
   and states verbatim: "This discharges Addendum 4's
   conditional closure of the supersede item: the
   unanchored-journal residual it was conditioned on no longer
   exists for either journal."

2. **r4-2 — CLOSED.** The production bullet in
   `deploy/verifier-identity/README.md` ("Production mode")
   now lists all five INIT flags: `AION_ANCHOR_INIT`,
   `AION_BUDGETS_ANCHOR_INIT`,
   `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`,
   `AION_CEREMONY_ISSUANCE_ANCHOR_INIT`, and
   `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT`.

3. **r4-3 — CLOSED.** The header catalogue in
   `trust/verifier_main.py` documents all four new env vars —
   `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`,
   `AION_CEREMONY_ISSUANCE_ANCHOR_INIT`,
   `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`,
   `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT` — including INIT
   bootstrap semantics: INIT creates the anchor for an EMPTY
   journal only, a non-empty journal with a missing anchor is
   NOT silently blessed (`anchor_refused`), and first-pin of
   an established journal is the operator ceremony in the
   deploy README (the supersession INIT entry incorporates
   the issuance entry's semantics by explicit reference).

4. **r5-1 — CLOSED, verified programmatically.** The cycle-27
   paragraph in `deploy/verifier-identity/README.md` now
   reads "(allowlist 20 → 24)" (the erroneous "19 → 23" is
   gone). Ground-truth counts, computed this review:
   `trust/wiring.py` `ALLOWED_ENV_KEYS` = 24;
   `deploy/verifier-identity/run-verifier.sh` `ALLOWED_KEYS`
   = 24; `deploy/verifier-identity/health_check.py`
   `ALLOWED_KEYS` = 24; all three sets are exactly equal.

5. **r5-2 / r6-5 — PARTIALLY CLOSED (the FIX).**
   Closed parts: the `trust/wiring.py` module docstring now
   reads "(ALLOWED_KEYS, 24 names — the shipped wrapper
   governs)", "all five anchor paths are required non-empty",
   and "All anchor paths must be absolute, distinct from each
   other…"; the comment above `REQUIRED_ENV_KEYS` now reads
   "all five anchor paths" and carries the recorded rationale
   for the anchor-path exception — the ceremony anchor paths
   are "the standing exception to the not-wiring-required
   treatment below", wiring-required since cycle 22 for
   consumption and added on the same terms in cycle 27 for
   issuance/supersession, because "an anchor path is
   client-construction configuration, not ceremony capability,
   and a production client built without one could never start
   its verifier", with the fail-closed consequence for existing
   production envs and a pointer to the cycle-27 migration note.
   **Not closed:** the comment directly above `ALLOWED_ENV_KEYS`
   itself still reads "copied from ALLOWED_KEYS in
   deploy/verifier-identity/run-verifier.sh as shipped (20
   names)". r5-2 named this exact comment ("the comment above
   `ALLOWED_ENV_KEYS` repeats '(20 names)'"), and r6-5 demanded
   a sweep of `trust/wiring.py` to the 24-name ground truth.
   The docstring was swept; this comment was not. Fix: change
   "(20 names)" to "(24 names)" in that comment.
   (Not counted against this item: the "two anchor paths"
   wording in the Declared-residuals "Anchor placement" bullet
   was not named by r5-2/r6-5 and is not treated as part of
   this finding.)

6. **r6-1 / r6-2 / r6-3 / r6-4 — CLOSED.** The "**Cycle-27
   migration (established deployments)**" note in
   `deploy/verifier-identity/README.md` covers all four:
   (r6-1) the established-journal first-pin ceremony — INIT
   pins only an empty journal by design, first-pinning is an
   operator ceremony outside the verifier calling
   `trust.anchoring.initialise_anchor` with
   `allow_nonempty_ceremony=True`, "the same
   first-initialisation ceremony the ship-tx journal used in
   cycle 17", and "The first pin blesses the journal's current
   history: it cannot detect a rollback that happened before
   it", with intact-home verification as the operator's duty;
   (r6-2) the deliberate wiring-required break — both changes
   are introduced as "fail-closed breaks for an existing
   production deployment, both deliberate", item (1) being the
   two new required env keys refused at client construction;
   (r6-3) the availability coupling — "all five anchors are
   verified at startup on EVERY verifier invocation, so a
   fault in any one anchor or journal refuses every mode
   until repaired — fail-closed", noted as carried by the
   consumption anchor since cycle 22; (r6-4) multi-anchor
   bootstrap repeatability — "Bootstrapping several anchors
   in one research-mode INIT invocation is safe to repeat:
   each anchor is verified independently, and an invocation
   that stops halfway leaves the remaining anchors missing,
   which refuses startup until the ceremony is completed."

7. **r2-7 — CLOSED.** The `ceremony_supersede` mode docstring
   step list in `trust/verifier_main.py` now includes
   "(10) supersession-anchor update (cycle 27; failure is
   ledger_failed, the decision stands, no receipt)", with the
   signing-ledger mirror renumbered to (11); the code comment
   at the commit site matches ("(10) Supersession anchor
   (cycle 27), then the signing-ledger mirror…").

8. **Health-check parity decision — CLOSED.** Addendum 7
   ruling (d) records it verbatim: "`health_check.py` keeps
   the consumption-parity treatment (list membership + env
   validation) for the new anchors; extending its direct
   anchor-vs-journal verification to the three ceremony
   anchors is a follow-up, not a hold — the verifier's own
   startup verification is the enforcement."

## Required fix (one line)

- `trust/wiring.py`, comment above `ALLOWED_ENV_KEYS`:
  "(20 names)" → "(24 names)".

On that single change, items (1)–(8) are all closed and this
seat's verdict converts to SHIP without further re-review of
the other items.
