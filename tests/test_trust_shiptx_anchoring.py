"""Ship-tx journal anchoring (cycle 17): kind="ship-tx" in
trust.anchoring, and ShipTxJournal.recover(tx_anchor_path=...)
under the same classification as the ship-ledger anchor.

Pins: the anchor ceremony over a ShipTxJournal, kind mismatch
in both directions, rollback by truncation / deletion /
replacement, the outside-the-journal-dir placement rule (the tx
journal shares the ship ledger's directory), recovery parks on
tx chain mismatch, non-destructive operator errors (missing /
malformed / inside-dir / same-path-as-ship-anchor), the
deleted-journal AnchorError surface, back-compat when
tx_anchor_path is omitted, and the park-beats-error combination
when both anchors are supplied.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_trust_shiptx_recovery as _rec

from trust.anchoring import (
    AnchorError,
    initialise_anchor,
    load_anchor,
    update_anchor,
    verify_anchor,
)
from trust.ledger import GENESIS_HASH, ShipLedger
from trust.shipcheck import recover_ship_tx
from trust.shiptx import (
    ANOMALY,
    AUTHORISATION_VERIFIED,
    BURN_PENDING,
    COMMITTED,
    CYCLE_RECORDED,
    POST_RECORD_VERIFIED,
    ShipTxJournal,
)

NOW = _rec.NOW
StubLoop = _rec.StubLoop
JournalRecoveryFixture = _rec.JournalRecoveryFixture


class TxAnchorFixture(JournalRecoveryFixture):
    def tx_anchor_path(self):
        return Path(self.tmp.name) / "anchors" / "ship-tx.anchor.json"

    def ship_anchor_path(self):
        return Path(self.tmp.name) / "anchors" / "ship.anchor.json"

    def init_tx_anchor(self, **kw):
        kw.setdefault("allow_nonempty_ceremony", True)
        return initialise_anchor(self.journal, self.tx_anchor_path(),
                                 kind="ship-tx", recorded_at=NOW, **kw)

    def post_record_tx(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        return tx_id

    def loop3(self):
        return StubLoop([{"cycle_id": 3, "item_id": "item-1"}])


class CeremonyTests(TxAnchorFixture):
    def test_initialise_empty_tx_journal_pins_genesis(self):
        anchor = initialise_anchor(self.journal, self.tx_anchor_path(),
                                   kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["kind"], "ship-tx")
        self.assertEqual(anchor["head"], GENESIS_HASH)
        self.assertEqual(anchor["seq"], 0)
        self.assertEqual(load_anchor(self.tx_anchor_path()), anchor)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_initialise_nonempty_refused_by_default(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, self.tx_anchor_path(),
                              kind="ship-tx", recorded_at=NOW)
        self.assertFalse(self.tx_anchor_path().exists())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"),
            ("anchor_missing_established_ledger",))

    def test_nonempty_ceremony_flag_pins_current_head(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        anchor = self.init_tx_anchor()
        self.assertEqual(anchor["seq"], len(self.journal.entries()))
        self.assertEqual(anchor["head"], self.journal.head())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_double_init_refused_and_anchor_unchanged(self):
        self.init_tx_anchor()
        before = self.tx_anchor_path().read_bytes()
        with self.assertRaises(AnchorError):
            self.init_tx_anchor()
        self.assertEqual(self.tx_anchor_path().read_bytes(), before)

    def test_update_advances_monotonically(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        anchor = update_anchor(self.journal, self.tx_anchor_path(),
                               kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["seq"], 1)
        self.assertEqual(anchor["head"], self.journal.head())
        self.journal.transition(
            self.journal.transactions()[0]["tx_id"],
            AUTHORISATION_VERIFIED, NOW)
        anchor = update_anchor(self.journal, self.tx_anchor_path(),
                               kind="ship-tx", recorded_at=NOW)
        self.assertEqual(anchor["seq"], 2)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_update_without_appends_or_anchor_refused(self):
        self.init_tx_anchor()
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        other = Path(self.tmp.name) / "anchors" / "never.anchor.json"
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, other, kind="ship-tx",
                          recorded_at=NOW)

    def test_stale_tx_anchor_still_verifies(self):
        self.init_tx_anchor()
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_missing_anchor_empty_journal(self):
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ("anchor_missing",))

    def test_bad_kind_still_refused(self):
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, self.tx_anchor_path(),
                              kind="other", recorded_at=NOW)


class KindMismatchTests(TxAnchorFixture):
    def test_ship_anchor_used_as_ship_tx_refuses(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship", recorded_at=NOW)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ("anchor_kind_mismatch",))
        with self.assertRaises(AnchorError):
            update_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)

    def test_ship_tx_anchor_used_as_ship_refuses(self):
        self.init_tx_anchor()
        self.assertEqual(
            verify_anchor(self.ledger, self.tx_anchor_path(),
                          kind="ship"), ("anchor_kind_mismatch",))


class RollbackTests(TxAnchorFixture):
    def test_truncation_refuses_anchor_ahead_of_journal(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        snapshot = (self.home / "ship-tx.json").read_bytes()
        tx_id = self.journal.transactions()[0]["tx_id"]
        self.journal.transition(tx_id, AUTHORISATION_VERIFIED, NOW)
        self.init_tx_anchor()
        (self.home / "ship-tx.json").write_bytes(snapshot)
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_ahead_of_journal",))
        with self.assertRaises(AnchorError):
            update_anchor(fresh, self.tx_anchor_path(), kind="ship-tx",
                          recorded_at=NOW)

    def test_deleted_tx_journal_refuses_ahead_of_journal(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_ahead_of_journal",))

    def test_replaced_tx_journal_refuses_head_not_in_chain(self):
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.init_tx_anchor()
        other_home = Path(self.tmp.name) / "other-home"
        other = ShipTxJournal(other_home)
        other.begin("d-9", "p-1", "b" * 64, NOW, item_id="item-9")
        (self.home / "ship-tx.json").write_bytes(
            (other_home / "ship-tx.json").read_bytes())
        fresh = ShipTxJournal(self.home)
        self.assertEqual(
            verify_anchor(fresh, self.tx_anchor_path(), kind="ship-tx"),
            ("anchor_head_not_in_chain",))


class PlacementTests(TxAnchorFixture):
    def test_tx_anchor_inside_journal_dir_refused(self):
        inside = self.home / "ship-tx.anchor.json"
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, inside, kind="ship-tx",
                              recorded_at=NOW)
        with self.assertRaises(AnchorError):
            verify_anchor(self.journal, inside, kind="ship-tx")
        nested = self.home / "sub" / "ship-tx.anchor.json"
        with self.assertRaises(AnchorError):
            initialise_anchor(self.journal, nested, kind="ship-tx",
                              recorded_at=NOW)


class RecoveryParkTests(TxAnchorFixture):
    def test_recovery_parks_on_tx_head_not_in_chain(self):
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship-tx: anchor_head_not_in_chain"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        # A second run with the SAME still-mismatched anchor
        # raises: the park landed, but the anchor still
        # disagrees and there is no non-terminal transaction
        # left to park (fix round, rev-r1/r2/r3).
        with self.assertRaises(AnchorError):
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())

    def test_recovery_parks_on_tx_kind_mismatch(self):
        # A DIFFERENT file with the wrong kind is indistinguishable
        # from a substituted anchor: park, not operator error.
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.ship_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_kind_mismatch", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_deleted_tx_journal_raises_instead_of_empty_recovery(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        fresh = ShipTxJournal(self.home)
        with self.assertRaises(AnchorError) as ctx:
            fresh.recover(self.ledger, self.loop3(), recorded_at=NOW,
                          tx_anchor_path=self.tx_anchor_path())
        self.assertIn("anchor_ahead_of_journal", str(ctx.exception))


class RecoveryErrorTests(TxAnchorFixture):
    def test_missing_tx_anchor_is_error_and_retry_succeeds(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("ship-tx: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(outcomes[0]["to_state"], POST_RECORD_VERIFIED)
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_malformed_tx_anchor_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text("this is not an anchor\n")
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("anchor_malformed", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_inside_dir_tx_anchor_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.home / "ship-tx.anchor.json")
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_error:", outcomes[0]["error"])
        self.assertIn("OUTSIDE", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_same_path_for_both_anchors_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.ship_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])


class RecoveryProceedTests(TxAnchorFixture):
    def test_recovery_proceeds_with_valid_tx_anchor(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_recovery_proceeds_with_stale_valid_tx_anchor(self):
        initialise_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx", recorded_at=NOW)
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])

    def test_recovery_unchanged_when_tx_anchor_omitted(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW)
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertFalse(self.tx_anchor_path().exists())

    def test_recover_ship_tx_wrapper_passes_tx_anchor(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = recover_ship_tx(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.journal.state(tx_id), COMMITTED)


class CombinedAnchorTests(TxAnchorFixture):
    def _both_valid(self):
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.init_tx_anchor()

    def test_combined_both_valid_proceeds(self):
        self.post_record_tx()
        self._both_valid()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self.assertEqual(self.ledger_kinds(), ["burn", "finalise"])

    def test_combined_ship_valid_tx_park_parks(self):
        self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_combined_park_beats_operator_error(self):
        # Ship anchor missing (operator error) + tx anchor chain
        # mismatch (park): park wins, as with the single anchor.
        tx_id = self.post_record_tx()
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship-tx",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_head_not_in_chain", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_combined_ship_valid_tx_operator_error_is_nondestructive(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)


class FixRoundTests(TxAnchorFixture):
    """War-room fix round (rev-r1/r2/r3/r5): the same-file
    guard in both directions and under aliasing, the
    all-terminal raise, the discriminating wrapper cases, the
    never-advances claim, force_reanchor/audit for the new
    kind, the ahead-of-journal park, and the combined matrix."""

    def _forge_tx_anchor(self, head="f" * 64, seq=1, kind="ship-tx"):
        self.tx_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.tx_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": kind,
            "head": head, "seq": seq, "anchored_at": NOW}))

    def test_same_file_tx_anchor_shared_is_error_not_anomaly(self):
        # The shared file IS the tx anchor: the ship-side check
        # must be suppressed too (rev-r2 F1 / rev-r3 F1).
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.tx_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("error", outcomes[0])
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)
        self.assertEqual(self.ledger_kinds(), ["burn"])

    def test_same_file_symlink_alias_is_error_not_anomaly(self):
        tx_id = self.post_record_tx()
        initialise_anchor(self.ledger, self.ship_anchor_path(),
                          kind="ship", recorded_at=NOW,
                          allow_nonempty_ceremony=True)
        alias = Path(self.tmp.name) / "anchors" / "alias.anchor.json"
        alias.symlink_to(self.ship_anchor_path())
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=alias)
        self.assertEqual(len(outcomes), 1)
        self.assertIn("same file", outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)

    def test_all_terminal_journal_with_forged_tx_anchor_raises(self):
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        self._forge_tx_anchor()
        with self.assertRaises(AnchorError) as ctx:
            self.journal.recover(
                self.ledger, self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())
        self.assertIn("anchor_head_not_in_chain", str(ctx.exception))
        self.assertEqual(self.journal.state(tx_id), COMMITTED)

    def test_wrapper_discriminates_bogus_tx_anchor(self):
        # Deleting the shipcheck pass-through must fail this:
        # a valid-anchor wrapper call commits (other tests),
        # a forged one parks.
        tx_id = self.post_record_tx()
        self._forge_tx_anchor()
        outcomes = recover_ship_tx(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_wrapper_deleted_journal_raises(self):
        self.post_record_tx()
        self.init_tx_anchor()
        (self.home / "ship-tx.json").unlink()
        with self.assertRaises(AnchorError):
            recover_ship_tx(
                ShipLedger(self.home), self.loop3(), recorded_at=NOW,
                tx_anchor_path=self.tx_anchor_path())

    def test_recovery_never_advances_tx_anchor_then_caller_does(self):
        self.post_record_tx()
        self.init_tx_anchor()
        before = self.tx_anchor_path().read_bytes()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [COMMITTED])
        # Recovery appended a COMMITTED transition but the
        # anchor file is byte-identical: it never advances it.
        self.assertEqual(self.tx_anchor_path().read_bytes(), before)
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())
        advanced = update_anchor(self.journal, self.tx_anchor_path(),
                                 kind="ship-tx", recorded_at=NOW)
        self.assertEqual(advanced["head"], self.journal.head())
        self.assertEqual(
            verify_anchor(self.journal, self.tx_anchor_path(),
                          kind="ship-tx"), ())

    def test_force_reanchor_and_audit_for_ship_tx(self):
        from trust.anchoring import (
            force_reanchor,
            verify_anchor as va,
            verify_reanchor_audit,
        )
        self.journal.begin("d-1", "p-1", "a" * 64, NOW, item_id="item-1")
        self.init_tx_anchor()
        old = force_reanchor(self.journal, self.tx_anchor_path(),
                             kind="ship-tx",
                             reason="operator restore drill",
                             recorded_at=NOW)
        self.assertIsNotNone(old)
        self.assertEqual(old["kind"], "ship-tx")
        self.assertEqual(verify_reanchor_audit(self.tx_anchor_path()), ())
        self.assertEqual(va(self.journal, self.tx_anchor_path(),
                            kind="ship-tx",
                            check_reanchor_audit=True), ())

    def test_truncated_journal_with_live_tx_parks_ahead_of_journal(self):
        tx_id = self.journal.begin("d-1", "p-1", "a" * 64, NOW,
                                   item_id="item-1")
        snapshot = (self.home / "ship-tx.json").read_bytes()
        self.walk(tx_id, AUTHORISATION_VERIFIED, BURN_PENDING)
        self.burn("d-1", "a" * 64)
        self.walk(tx_id, CYCLE_RECORDED, cycle_id=3)
        self.journal.transition(tx_id, POST_RECORD_VERIFIED, NOW)
        self.init_tx_anchor()
        (self.home / "ship-tx.json").write_bytes(snapshot)
        fresh = ShipTxJournal(self.home)
        outcomes = fresh.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_ahead_of_journal", outcomes[0]["reasons"])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship-tx: anchor_ahead_of_journal"])

    def test_ship_tx_file_passed_as_ship_anchor_parks(self):
        # Reverse direction of the kind-mismatch park: a
        # ship-tx anchor supplied as the SHIP anchor_path.
        tx_id = self.post_record_tx()
        self.init_tx_anchor()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.tx_anchor_path())
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertIn("anchor_kind_mismatch", outcomes[0]["reasons"])
        self.assertEqual(self.journal.state(tx_id), ANOMALY)

    def test_combined_both_operator_errors_labelled(self):
        tx_id = self.post_record_tx()
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=self.tx_anchor_path())
        self.assertEqual(len(outcomes), 1)
        self.assertIn("ship: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertIn("ship-tx: anchor_missing_established_ledger",
                      outcomes[0]["error"])
        self.assertEqual(self.journal.state(tx_id), POST_RECORD_VERIFIED)

    def test_combined_ship_park_tx_error_parks_with_source(self):
        self.post_record_tx()
        self.ship_anchor_path().parent.mkdir(parents=True, exist_ok=True)
        self.ship_anchor_path().write_text(json.dumps({
            "v": "ledger-anchor/1", "kind": "ship",
            "head": "f" * 64, "seq": 1, "anchored_at": NOW}))
        outcomes = self.journal.recover(
            self.ledger, self.loop3(), recorded_at=NOW,
            anchor_path=self.ship_anchor_path(),
            tx_anchor_path=Path(self.tmp.name) / "anchors"
            / "missing.anchor.json")
        self.assertEqual([o["to_state"] for o in outcomes], [ANOMALY])
        self.assertNotIn("error", outcomes[0])
        self.assertEqual(outcomes[0]["anchor_sources"],
                         ["ship: anchor_head_not_in_chain"])


if __name__ == "__main__":
    unittest.main()
