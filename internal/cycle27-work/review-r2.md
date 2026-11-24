# Cycle 27 — War-Room Review, Seat rev-r2 (blind, independent)

Reviewer slice: the two commit-order changes in
`trust/verifier_main.py` (`_mode_ceremony_authorise`,
`_mode_ceremony_supersede`) and the helpers
`_update_ceremony_issuance_anchor` /
`_update_ceremony_supersession_anchor` — failure semantics,
the supersede path's later `_update_anchor` wrapping, caller
dependence on the old ordering, and silent-skip paths for the
issuance anchor (all `append_authorisation` sites audited).

Method: read `internal/cycle27-work/design-final.md`, then the
uncommitted `git diff` for `trust/verifier_main.py`, the HEAD
(pre-cycle-27) versions of both modes for comparison, the
`trust/anchoring.py` `update_anchor` / `_write_json_atomic`
internals, and a repo-wide grep for every
`append_authorisation` / `append_decision` call site. Ran
`tests/test_cycle27_journal_anchors.py`: 11 tests, OK.

## Score: 0.92

## Verdict: SHIP

The commit orders match the design exactly, the failure
semantics are fail-closed and correctly coded, and I found no
production append site that can advance either ceremony
journal without its anchor advancing immediately after. The
findings below are minor and non-blocking; none forces a fix
before ship.

## Findings

1. **[OK — commit orders match the design]** Authorise is now:
   issuance append (commit point) →
   `_update_ceremony_issuance_anchor(config)` →
   signing-ledger mirror → `_update_anchor` (signing anchor).
   Supersede is now: decision append (commit point) →
   `_update_ceremony_supersession_anchor(config)` →
   signing-ledger mirror → signing anchor. Both insert the new
   anchor step as step 2 of 4, exactly as design-final.md
   specifies and exactly mirroring the cycle-22 consumption
   order in `_mode_ceremony_consume` (append → consumption
   anchor → mirror → signing anchor), which I compared
   line-by-line.

2. **[OK — anchor-update failure semantics]** Both helpers are
   called bare, outside any surrounding try/except: in
   authorise the call sits between the closed append
   try/except and the mirror try block; in supersede it sits
   between the closed append try/except and the mirror try
   block. A helper failure therefore cannot be swallowed or
   relabelled by a neighbouring handler. Each helper converts
   `AnchorError` from `update_anchor` into
   `_config("ledger_failed", …)` — a `_Refuse` with exit code
   3 — so the artefact/receipt is withheld (the mode function
   returns nothing), the journal entry stands (no rollback is
   attempted anywhere), and the wire code is `ledger_failed`,
   as the design requires. The detail strings are accurate:
   authorise says the pair stays burned and retry needs a new
   ceremony_id + new evidence bundle; supersede says the
   decision stands and consumption may proceed against the
   journaled decision (true — consume reads the supersession
   journal directly). The cycle-27 failure tests confirm the
   observable behaviour: exit 3, `ledger_failed`, journal entry
   present (+1), signing mirror absent, envelope withheld.

3. **[OK — supersede's later `_update_anchor` try/except still
   behaves]** That wrapping is pre-existing (verified identical
   in HEAD) and unchanged by this diff. `_update_anchor` itself
   raises `_config("ledger_failed", …)`; the supersede wrapper
   catches `_Refuse` and re-raises `_config("ledger_failed", …)`
   with a more specific detail ("journaled and mirrored … but
   the signing anchor update failed; the decision stands").
   Code and exit code are unchanged by the re-raise; only the
   detail improves. Critically, the new supersession-anchor
   call is placed BEFORE and OUTSIDE that try block, so a
   supersession-anchor failure is never caught by it and never
   misreported as a signing-anchor failure — its own detail
   reaches the wire. No double-wrap, no masking.

4. **[OK — no caller depends on the old ordering]** The only
   callers of the two modes are the `_MODES` dispatch in
   `main()`, which maps `_Refuse` to (exit code, error code)
   generically. Success-path return values are unchanged
   (authorise returns the envelope dict; supersede returns the
   same receipt dict). The new intermediate failure produces
   `ledger_failed` / exit 3 — a code both modes already
   produced for post-commit mirror failures, so any client
   handling the old post-commit failures already handles this
   one. On the success path the reordering is externally
   invisible except for the anchor files' timing, which is the
   intended protection. On the mirror-failure path the journal
   anchor is now already advanced when the mirror fails; that
   state is self-consistent (startup verification compares the
   anchor against the journal, which does contain the entry),
   so a subsequent consume/supersede startup is not refused
   spuriously.

5. **[OK — no silent skip of the issuance anchor in any
   production path]** Repo-wide grep for `append_authorisation`
   outside tests returns exactly one call site:
   `trust/verifier_main.py` in `_mode_ceremony_authorise`, and
   `_update_ceremony_issuance_anchor(config)` follows it
   unconditionally on the next statement. There is no separate
   recovery-issuance call site to miss: recovery issuance is
   the same function — `recovery_of` is computed in
   `_mode_ceremony_authorise` and passed to that single append,
   so recovery appends get the anchor advance too. Likewise
   `append_decision` has exactly one production call site, in
   `_mode_ceremony_supersede`, followed unconditionally by
   `_update_ceremony_supersession_anchor(config)`. All other
   constructions of `CeremonyAuthorisationLedger` /
   `CeremonySupersessionLedger` in `verifier_main.py` are
   reads (`find_by_*`, `entries()`), and `signing/pin_ceremony.py`
   contains no append to either journal. Direct `append_*`
   calls elsewhere are test fixtures only — not the verifier
   process, so no anchor obligation attaches. The helpers'
   only early return is the unconfigured-anchor no-op
   (`path is None`); in production with the ceremony seed
   configured, `_load_config` requires both anchor paths and
   refuses both INIT flags, and with no seed the authorise
   mode itself is disabled — so the no-op is reachable only in
   research mode, which is the design's stated residual, not a
   silent skip. Both helpers also re-open the ledger on the
   same `config.home` the append used, so the anchor advances
   over the journal that was actually appended to. A deleted
   anchor file at update time raises `AnchorError` inside
   `update_anchor` ("no anchor exists") → `ledger_failed`:
   fail-closed, not skipped.

6. **[Minor, non-blocking — non-`AnchorError` escapes keep the
   safety properties but lose the `ledger_failed` code]** The
   helpers catch only `AnchorError`, mirroring the cycle-22
   consumption helper and `_update_anchor` exactly. But
   `update_anchor` can also raise non-`AnchorError` failures:
   `_write_json_atomic` re-raises raw `OSError` (e.g. anchor
   directory unwritable, disk full), and re-opening the
   journal in the helper can raise ledger/OSError on a journal
   corrupted mid-invocation. Those propagate to `main()`'s
   generic handler and surface as `verifier_failure` instead
   of `ledger_failed`. The safety invariants still hold — the
   exception escapes before any return, so the artefact is
   withheld and the journal entry stands — only the error code
   and detail are less precise. This is a pre-existing pattern
   shared by every anchor helper in the file, not a cycle-27
   regression; recorded for a future consistency pass, not a
   ship blocker for this cycle.

7. **[Minor, non-blocking — docstring lag in the supersede
   mode]** The `_mode_ceremony_supersede` docstring's
   validation-order list still describes step (10) as only
   "signing-ledger mirror plus the signing-anchor update" and
   never mentions the supersession-anchor update that now
   precedes the mirror; the inline code comment at step (10)
   is correct and complete. The module header docstring was
   updated for cycle 27. Worth a one-line docstring touch-up
   so a future reader is not misled about the order, but the
   code, comments, and design record all agree, so this does
   not block.

## Summary

Both commit-order changes implement the design faithfully:
journal append remains the commit point, the journal's own
anchor advances before the signing mirror, an anchor-update
failure is `ledger_failed` with the artefact withheld and the
journal entry standing, the supersede signing-anchor wrapper
is undisturbed and cannot mask the new step, no caller depends
on the old order, and the append-site audit shows no path —
recovery issuance included — that can advance a ceremony
journal without its anchor following. SHIP, with findings 6
and 7 recorded as minor follow-ups.
