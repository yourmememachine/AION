# Cycle 31 — War-room review R4 (safety / limits)

Scope: blind review of `docs/RECOVERY-CONTRACT.md`, "Limits and
non-claims" section (lines 108–132), checked against the honest-scope
comments in `trust/anchoring.py` and `trust/shiptx.py`. No other
internal cycle-31 material was read.

**Score: 0.6 / 1.0**
**Verdict: FIX**

What the section states is accurate — every bullet present was
verified against the code (unkeyed anchor, prefix-only protection,
rollback to the anchored prefix erasing settlements, one trust
location for two anchors in one directory, nonempty-ceremony
blessing, point-in-time same-file guard / no lock, silent-`[]`
holes). No bullet was found to be false. The verdict is FIX because
the section is materially incomplete and, in one place, understated:
several limits the source modules state explicitly appear nowhere
in the contract (a word search of the contract for `force_reanchor`,
`reanchor`, `by-value`, `rebuild`, and `grants no` returns zero
hits).

## Gaps

1. **`force_reanchor` and the reanchor audit are omitted entirely —
   and recovery never checks the audit.** `trust/anchoring.py:52–60`
   and `force_reanchor` at `trust/anchoring.py:667` document a
   sanctioned API that overwrites the anchor with the journal's
   current head — i.e. a legitimate-looking re-pin over a
   rolled-back journal, not only the attacker rewrite the contract's
   first bullet describes. Its only safeguard is the audit chain,
   which lives alongside the anchor (`reanchor_audit_path`,
   `trust/anchoring.py`) — the same trust location the contract
   itself says is one location, not two. Worse, recovery provides
   no check at all: `verify_anchor` defaults to
   `check_reanchor_audit=False` (`trust/anchoring.py:703–704`), a
   missing audit file adds no reason (`trust/anchoring.py:714–742`,
   "the anchor alone cannot prove one did not"), and every
   `verify_anchor` call inside `ShipTxJournal.recover` —
   pre-settlement (`trust/shiptx.py:817–825`) and post-settlement
   (`trust/shiptx.py:999`, `:1013`) — omits the flag. So a re-pin
   passes recovery undetected, and deleting the audit file with it
   is also undetected. The Limits section must state this; as
   written it implies the ceremony (bullet 3, "no in-anchor record")
   is the only unrecorded re-pin path, which understates the risk.

2. **The Limits section never states that all anchor protection is
   opt-in and currently unwired on the recovery path.** The limits
   are written as properties of the system, but they apply only
   when a caller passes `anchor_path` / `tx_anchor_path`; both
   default to `None` in `recover()` (contract entry points, and
   `trust/shiptx.py` `recover` signature). The contract's own
   "Anchor advancement" section admits no non-test caller passes
   `tx_anchor_path` to recovery, yet the Limits section does not
   carry the consequence: on the default path there is no anchor
   verification at all, and per `trust/shiptx.py:161–162` a deleted
   tx journal "loads as empty; only an externally pinned head
   detects that" — so deletion/rollback is undetectable in the
   configuration that actually runs. A limits section that omits
   "protection is not in force by default" overstates the deployed
   posture.

3. **The by-value tx↔loop binding limit is absent.**
   `trust/shiptx.py:79` onwards states it exactly: the loop's
   history entry cannot carry the `tx_id`, "nothing inside the
   loop's state file proves a history entry belongs to this
   transaction rather than to another ship of the same item," and
   recovery attributes by item alone only when unambiguous,
   otherwise parking at ANOMALY. This is a core recovery-safety
   limit — attribution is inferential, not proven — and the
   contract, which is the recovery contract, never mentions it.

4. **The manifest-rebuild limit is absent.** `trust/shiptx.py:276`
   ("Rebuild limit, stated"): re-verification assumes stage
   `"final"` and no superseded manifest, and a manifest that does
   not rebuild to an equal hash "for ANY reason (tree drift, a
   superseding manifest, a review record outside internal/)" parks
   at ANOMALY. A reader of the contract cannot learn that recovery's
   verification is this narrow, or that ordinary tree drift — not
   tampering — produces a park.

5. **Consequences and the false-park direction are understated.**
   (a) The contract says park reasons "park ALL non-terminal
   transactions at ANOMALY" but never states what ANOMALY costs:
   per `trust/shiptx.py`'s state definitions it is terminal and
   "NEVER auto-resolved: a human operator must reconcile the stores
   by hand." (b) Symmetrically, the Limits section covers only the
   undetected direction (older anchor restored). It omits the
   documented spurious-park direction at `trust/shiptx.py:222–228`:
   restoring this journal and its anchor from different backup
   points, or restoring the journal without a `force_reanchor`,
   parks live transactions at ANOMALY. Backup restore is the most
   likely real-world trigger of a park, and the contract is silent
   on it.

6. **Minor: "grants no authority" is dropped.** The honest-scope
   close in `trust/anchoring.py:96–105` states the anchor "detects
   rollback by disagreement, it grants no authority," and that an
   anchor in a directory the same attacker can write "is a second
   copy of the journal's own claim, not a pin." The contract's
   "unkeyed plain JSON" bullet approximates the first half, but the
   explicit no-authority non-claim should be carried verbatim into
   a section titled "non-claims" rather than left to inference.

## Required fix

Add bullets to "Limits and non-claims" covering gaps 1–5 (gap 6 may
ride with gap 1's bullet), each pinned to the code locations cited
above. No existing bullet needs correction — this is an omission
fix, not a retraction.
