"""The ship check: the only sanctioned path from a signed ship
decision to a recorded cycle.

check_ship is a pure check (no writes): given the live tree, the
manifest, the ship envelope, and optionally the release record, a
presented SignedAttestation, the ship ledger, and an externally
pinned ledger head, it returns the tuple of refusal reasons; ()
means the ship may proceed. It recomputes everything from
primary artefacts — the manifest is rebuilt from the live tree
(a supplied manifest that is merely self-consistent proves
nothing), the envelope is re-verified under the key, and the
review record is re-hashed.

record_ship is the sanctioned caller of CoreLoop.run_one_cycle
for trust-boundary ships. Its order of operations is part of the
design:

1. check_ship — any reason refuses, nothing is burned;
2. pre-burn loop verification — the loop's pickable item must be
   the manifest's item, and when a release record is presented
   the loop's live state (cycle_seq and the state file's sha256)
   must equal the release's pre-ship snapshot, with the expected
   cycle exactly next. A drift discovered here refuses WITHOUT
   spending the decision;
3. burn the decision in the ship ledger (never refunded);
4. record the cycle; re-verify the manifest against the tree —
   drift during recording withholds the finalise and surfaces
   loudly (the cycle is recorded; the audit trail shows a burn
   with no finalise, which is the anomaly signal);
5. finalise the burn with the recorded cycle id.

Replay protection rests on the burn living outside the loop's
state: rolling state.json back cannot un-burn a decision. The
dual limit is stated, not hidden: rolling back or DELETING the
ledger file itself defeats it — a missing journal loads as
empty, indistinguishable from first use. That is detectable
only against an externally pinned ledger head, which is why
check_ship accepts expected_ledger_head and why the cycle
records should pin the head in the build record (the cycle-8
record does).

Every record_ship attempt also drives a durable transaction
state machine (trust.shiptx): a ShipTxJournal living alongside
the ship ledger (ship-tx.json in the ledger's directory)
records PREPARED before the check, AUTHORISATION_VERIFIED once
the check and the pre-burn loop verification pass, BURN_PENDING
immediately before the burn, CYCLE_RECORDED with the recorded
cycle's id, POST_RECORD_VERIFIED after the post-record manifest
re-verification, and COMMITTED after the finalise. Pre-burn
refusals land at REFUSED_PRE_BURN (nothing spent); a loop
refusal after the burn lands at ABORTED_SPENT (spent, never
replayable). Only one ship transaction per item may be in
flight: record_ship refuses to start while a different
non-terminal transaction exists for the manifest's item. A
crash between steps leaves the transaction non-terminal for
recover_ship_tx below, which settles it from ledger + loop
evidence — or parks it at ANOMALY when the evidence is
ambiguous, contradictory, or missing the provenance recovery
would need (see trust.shiptx for the exact rules) — and never
re-burns or re-runs a cycle.

Honest scope: this makes the SANCTIONED path signed-only. It
does not make unsigned shipping impossible for arbitrary
same-user code that calls run_one_cycle directly — nothing
in-process can. The suite's call-graph lint
(tests/test_trust_lint.py) fails the build if non-allowlisted
production code reaches for the unsanctioned entry points; that
is enforcement by test, stated as such.
"""

from __future__ import annotations

import hashlib

from signing.attestation import verify_signed_attestation
from signing.gate_decision import (
    PURPOSE_SHIP,
    SigningError,
    _now,
    _parse_time,
    verify_signed_decision,
)
from trust.anchoring import AnchorError, update_anchor, verify_anchor
from trust.errors import ShipRefused
from trust.ledger import LedgerError
from trust.manifest import ManifestError, verify_manifest
from trust.shiptx import (
    ABORTED_SPENT,
    AUTHORISATION_VERIFIED,
    BURN_PENDING,
    COMMITTED,
    CYCLE_RECORDED,
    POST_RECORD_VERIFIED,
    REFUSED_PRE_BURN,
    TERMINAL_STATES,
    ShipTxJournal,
)


def check_ship(root, manifest, signed, *, signing_key, release=None,
               ledger=None, expected_signer_id=None,
               expected_attestation=None, expected_ledger_head=None,
               now=None) -> tuple:
    """All refusal reasons for shipping this manifest under this
    envelope; () authorises record_ship to proceed.

    ``now`` exists for tests only (the module-level rule in
    signing.gate_decision): production callers must not pass it —
    record_ship never does.
    """
    reasons = []
    if manifest.recomputed_hash() != manifest.manifest_hash:
        reasons.append("manifest_hash_mismatch")
    try:
        diff = verify_manifest(root, manifest)
        reasons.extend(diff.summary())
    except ManifestError as exc:
        reasons.append(f"tree_refused:{exc}")
    if release is not None:
        if release.proposal_id != manifest.proposal_id:
            reasons.append("release_proposal_mismatch")
        if release.item_id != manifest.item_id:
            reasons.append("release_item_mismatch")
        if release.manifest_hash != manifest.manifest_hash:
            reasons.append("release_manifest_mismatch")
        if release.decision_id != signed.decision_id:
            reasons.append("release_decision_mismatch")
        if release.payload_hash != signed.payload_hash:
            reasons.append("release_payload_mismatch")
        if release.review_record_hash \
                != manifest.review_record["record_hash"]:
            reasons.append("release_review_record_mismatch")
        if release.stage != manifest.stage:
            reasons.append("release_stage_mismatch")
        if release.status != "prepared":
            reasons.append("release_not_prepared")
        if release.cycle_id:
            reasons.append("release_already_recorded")
    reasons.extend(verify_signed_decision(
        signed, signing_key=signing_key, expected_purpose=PURPOSE_SHIP,
        expected_proposal_id=manifest.proposal_id,
        expected_gate_inputs_hash=manifest.manifest_hash,
        expected_signer_id=expected_signer_id, now=now))
    decision = signed.decision
    if decision.accepted is not True:
        reasons.append("decision_not_accepted")
    elif decision.reasons or decision.regressions \
            or decision.forgetting_failures \
            or decision.protected_violations:
        reasons.append("decision_not_clean")
    note = decision.verifier_note
    first = note.split(";", 1)[0].strip() if isinstance(note, str) else ""
    if first != f"content-hash:{manifest.manifest_hash}":
        reasons.append("note_binding_mismatch")
    if manifest.stage != "final":
        reasons.append("stage_not_final")
    if not signed.attestation_hash:
        # A ship decision must rest on a verifier attestation; the
        # gate never accepts unattested changes, so an accepted
        # ship envelope without one did not come from the gate.
        reasons.append("attestation_missing")
    if expected_attestation is not None:
        att_reasons = verify_signed_attestation(
            expected_attestation, signing_key=signing_key,
            expected_proposal_id=manifest.proposal_id,
            expected_manifest_hash=manifest.manifest_hash, now=now)
        reasons.extend("attestation_" + reason for reason in att_reasons)
        if expected_attestation.payload_hash != signed.attestation_hash:
            reasons.append("attestation_binding_mismatch")
        inner = expected_attestation.attestation
        if inner.decision != "approve" \
                or inner.reward_hacking_checked is not True:
            reasons.append("attestation_not_approving")
        if "malformed_payload" not in att_reasons:
            try:
                if _parse_time(expected_attestation.expires_at,
                               "expires_at") \
                        > _parse_time(signed.expires_at, "expires_at"):
                    reasons.append("attestation_outlives_decision")
            except (SigningError, ValueError):
                reasons.append("attestation_malformed")
    elif signed.attestation_hash:
        reasons.append("attestation_unverifiable")
    if ledger is not None:
        if expected_ledger_head is not None:
            ledger._reload()
            if ledger.head() != expected_ledger_head:
                reasons.append("ledger_head_mismatch")
        if ledger.is_consumed(
                decision_id=signed.decision_id,
                proposal_id=manifest.proposal_id,
                manifest_hash=manifest.manifest_hash):
            reasons.append("decision_already_consumed")
    return tuple(dict.fromkeys(reasons))


def record_ship(loop, *, root, manifest, signed, signing_key, ledger,
                coders, reviewers, delta, release=None,
                expected_signer_id=None, expected_attestation=None,
                expected_ledger_head=None, recorded_at="",
                anchor_path=None) -> dict:
    """Check, verify the loop, burn, record, re-verify, finalise.

    Freshness verdicts use the host clock — this is an
    authorising path and accepts no caller-supplied ``now`` (the
    optional recorded_at only stamps the ledger entries; it
    cannot move a freshness verdict). Returns the loop's
    history entry. If the loop refuses after the burn, the
    decision is spent (ShipRefused says so): re-shipping the same
    artifact needs a fresh decision. That asymmetry is deliberate.
    Refusals BEFORE the burn (check failures, loop-state drift)
    spend nothing.

    expected_ledger_head is REQUIRED on this path (unlike the
    pure check, where it is optional): the sanctioned ship must
    pin the ledger head it audited against, or ledger rollback
    is undetectable exactly when it matters. A release record is
    likewise REQUIRED: it is the document that ties the ship to
    the loop's pre-ship state, and shipping without one skips
    every pre-burn state check.
    """
    if expected_ledger_head is None:
        raise ShipRefused(
            "record_ship requires an externally pinned ledger "
            "head (expected_ledger_head); refusing to ship "
            "against an unpinned ledger")
    if release is None:
        raise ShipRefused(
            "record_ship requires a release record; refusing to "
            "ship without the pre-ship state binding")
    if anchor_path is not None:
        # Pre-burn anchor verification: a rolled-back, deleted or
        # mismatched ship ledger spends nothing.
        try:
            anchor_reasons = verify_anchor(
                ledger, anchor_path, kind="ship")
        except AnchorError as exc:
            raise ShipRefused(
                f"ship ledger anchor refused: {exc}") from exc
        if anchor_reasons:
            raise ShipRefused(
                "ship ledger anchor refused: "
                + ", ".join(anchor_reasons), anchor_reasons)
    # The transaction opens BEFORE the check: even a refused
    # attempt is a durable fact (REFUSED_PRE_BURN), and a crash
    # anywhere below leaves a recoverable state. begin is
    # idempotent, so a retried attempt rejoins its transaction.
    # The two precondition refusals above precede the transaction:
    # no decision was ever presented to the state machine there.
    stamp = recorded_at or _now()
    tx_journal = ShipTxJournal(ledger.journal_dir)
    try:
        tx_id = tx_journal.begin(
            decision_id=signed.decision_id,
            proposal_id=manifest.proposal_id,
            manifest_hash=manifest.manifest_hash, recorded_at=stamp,
            item_id=manifest.item_id)
    except LedgerError as exc:
        # Includes the one-in-flight-per-item refusal: another
        # non-terminal ship transaction for this item exists, so
        # this attempt does not start (and burns nothing).
        raise ShipRefused(
            f"ship transaction refused: {exc}") from exc

    def _mark_refused_pre_burn():
        """Land the tx at REFUSED_PRE_BURN — only when that is
        still true: the tx must be non-terminal AND the ship
        ledger must show no burn for this decision. If a burn
        exists (a post-burn crash being retried, a replay of a
        committed ship), the tx is left exactly as it is for
        recovery / as its terminal record."""
        current = tx_journal.state(tx_id)
        if current is None or current in TERMINAL_STATES:
            return
        if current not in ("PREPARED", AUTHORISATION_VERIFIED,
                           BURN_PENDING):
            return
        ledger._reload()
        burned = any(
            entry["kind"] == "burn"
            and entry["decision_id"] == signed.decision_id
            for entry in ledger.entries())
        if not burned:
            tx_journal.transition(tx_id, REFUSED_PRE_BURN, stamp)

    def _mark_aborted_spent():
        current = tx_journal.state(tx_id)
        if current is not None and current not in TERMINAL_STATES:
            tx_journal.transition(tx_id, ABORTED_SPENT, stamp)

    reasons = check_ship(
        root, manifest, signed, signing_key=signing_key,
        release=release, ledger=ledger,
        expected_signer_id=expected_signer_id,
        expected_attestation=expected_attestation,
        expected_ledger_head=expected_ledger_head)
    if reasons:
        _mark_refused_pre_burn()
        raise ShipRefused(
            "ship check failed: " + ", ".join(reasons), reasons)
    item = loop.pick_next()
    if item is None:
        _mark_refused_pre_burn()
        raise ShipRefused(
            "loop has no pickable item; nothing was burned")
    if item["id"] != manifest.item_id:
        _mark_refused_pre_burn()
        raise ShipRefused(
            f"loop would record item {item['id']!r}, not the "
            f"manifest's {manifest.item_id!r}; nothing was burned")
    if release is not None:
        if loop.state["cycle_seq"] != release.pre_ship_cycle_seq:
            _mark_refused_pre_burn()
            raise ShipRefused(
                "loop cycle_seq moved since the release was "
                "prepared; nothing was burned")
        state_hash = hashlib.sha256(
            loop.state_path.read_bytes()).hexdigest()
        if state_hash != release.pre_ship_state_sha256:
            _mark_refused_pre_burn()
            raise ShipRefused(
                "loop state file changed since the release was "
                "prepared; nothing was burned")
        if loop.state["cycle_seq"] + 1 != release.expected_cycle_id:
            _mark_refused_pre_burn()
            raise ShipRefused(
                "the release's expected cycle is not the loop's "
                "next cycle; nothing was burned")
    tx_journal.transition(tx_id, AUTHORISATION_VERIFIED, stamp)
    tx_journal.transition(tx_id, BURN_PENDING, stamp)
    try:
        ledger.burn(decision_id=signed.decision_id,
                    proposal_id=manifest.proposal_id,
                    manifest_hash=manifest.manifest_hash,
                    payload_hash=signed.payload_hash, recorded_at=stamp)
    except LedgerError as exc:
        # A refused burn landed nothing (the ledger validates
        # before it appends), so this is still pre-burn — unless
        # the ledger shows a burn did land, in which case the tx
        # stays at BURN_PENDING for recovery to settle.
        _mark_refused_pre_burn()
        raise ShipRefused(f"ship ledger refused the burn: {exc}") from exc
    from core.loop import InvalidTransition
    try:
        entry = loop.run_one_cycle(coders, reviewers, "reconciled",
                                   True, delta)
    except InvalidTransition as exc:
        _mark_aborted_spent()
        raise ShipRefused(
            f"loop refused after the burn; decision "
            f"{signed.decision_id} is spent and the artifact needs a "
            f"fresh decision: {exc}") from exc
    if entry is None:
        _mark_aborted_spent()
        raise ShipRefused(
            f"loop recorded nothing after the burn; decision "
            f"{signed.decision_id} is spent")
    if entry["item_id"] != manifest.item_id \
            or (release is not None
                and entry["cycle_id"] != release.expected_cycle_id):
        _mark_aborted_spent()
        raise ShipRefused(
            f"loop recorded item {entry['item_id']!r} as cycle "
            f"{entry['cycle_id']}, which is not what the release "
            f"authorised; decision {signed.decision_id} is spent")
    tx_journal.transition(tx_id, CYCLE_RECORDED, stamp,
                          cycle_id=entry["cycle_id"],
                          item_id=entry["item_id"])
    try:
        drift = verify_manifest(root, manifest)
        drift_reasons = drift.summary()
    except ManifestError as exc:
        drift_reasons = (f"tree_refused:{exc}",)
    if drift_reasons:
        # The tx deliberately stays at CYCLE_RECORDED: the cycle
        # IS recorded, so this is not ABORTED_SPENT, and the burn
        # stays unfinalised as the anomaly signal, exactly as
        # before. recover_ship_tx settles it ONLY by re-verifying
        # the tree (recover_ship_tx(..., root=<tree>)): with no
        # root, or a tree that no longer rebuilds to the tx's
        # manifest_hash, recovery parks it at ANOMALY and never
        # finalises the burn blind.
        raise ShipRefused(
            "cycle recorded, but the tree drifted during "
            "recording; the burn is deliberately left unfinalised "
            "as the anomaly signal: " + ", ".join(drift_reasons))
    tx_journal.transition(tx_id, POST_RECORD_VERIFIED, stamp)
    ledger.finalise(decision_id=signed.decision_id,
                    cycle_id=entry["cycle_id"], recorded_at=stamp)
    tx_journal.transition(tx_id, COMMITTED, stamp)
    if anchor_path is not None:
        try:
            update_anchor(ledger, anchor_path, kind="ship",
                          recorded_at=stamp)
        except AnchorError as exc:
            raise ShipRefused(
                f"cycle {entry['cycle_id']} recorded and decision "
                f"{signed.decision_id} finalised, but the "
                f"ship-ledger anchor update failed: {exc}") from exc
    return entry


def recover_ship_tx(ledger, loop, *, recorded_at="", root=None,
                    anchor_path=None) -> list:
    """Settle every non-terminal ship transaction in the ship
    ledger's tx journal (see trust.shiptx for the full design).

    Evidence only: the ship ledger (was there a burn? a
    finalise?) and the loop's history (was the authorised cycle
    recorded?). No burn and no recorded cycle ->
    REFUSED_PRE_BURN; burn + unambiguously recorded cycle +
    journaled authorisation -> the remaining transitions are
    completed and the burn finalised, landing at COMMITTED;
    burn + no recorded cycle -> ABORTED_SPENT, and the decision
    stays spent. Ambiguous, contradictory or
    provenance-missing evidence -> ANOMALY (terminal, never
    auto-resolved).

    Recovery NEVER journals AUTHORISATION_VERIFIED, and it
    journals POST_RECORD_VERIFIED only after re-verifying:
    ``root``, when provided, is the build tree the manifest is
    rebuilt from, and the rebuilt hash must equal the
    transaction's manifest_hash. With ``root=None`` an
    unfinalised burn past CYCLE_RECORDED parks at ANOMALY
    rather than finalising blind. The already-finalised
    exception applies ONLY to a transaction already at
    POST_RECORD_VERIFIED (the real crash window: finalise
    done, COMMITTED not yet journaled): below that state a
    present-but-unjournaled finalise is contradictory evidence
    and parks at ANOMALY, unless ``root`` is provided and
    re-verification passes — then recovery journals
    POST_RECORD_VERIFIED itself, having performed the
    verification (see trust.shiptx). ``anchor_path``, when
    provided, is verified against the ship ledger first
    (kind="ship"); its failure kind decides the outcome and it
    is never proceeded past silently: operator-error failures
    (anchor_missing, anchor_missing_established_ledger,
    anchor_malformed) produce a non-destructive per-transaction
    error outcome with the transaction left in place for a
    later run, and only chain-mismatch reasons
    (anchor_head_not_in_chain, anchor_ahead_of_journal,
    anchor_kind_mismatch) park the transactions at ANOMALY.
    Recovery NEVER re-burns and NEVER re-runs a cycle, and it
    is idempotent for settled transactions: a second run
    changes nothing for them. One transaction's failure is
    reported in its outcome dict and does not block the others.
    Returns the list of outcome dicts.
    """
    journal = ShipTxJournal(ledger.journal_dir)
    return journal.recover(ledger, loop,
                           recorded_at=recorded_at or _now(),
                           root=root, anchor_path=anchor_path)
