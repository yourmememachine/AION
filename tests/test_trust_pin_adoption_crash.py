"""Crash / restart coverage for the pin adopter (cycle 23,
DESIGN-FINAL R4): the seven pinned scenarios.

Method rules (R4): scenarios 1 (death after consumption,
before adoption) and 7 (concurrent adopters) are TRUE
SUBPROCESS tests — a child process (tests/cycle23_crash_child.py)
synchronised by barrier files and, for scenario 1, killed with
SIGKILL. Scenarios 2–4 are STATE SURGERY (journal/side-file
corruption or loss performed directly on files) and are
labelled as such; they are not crash coverage. Scenarios 5–6
use a monkeypatched adopt seam and live in a *SeamTests class;
they pin recovery semantics, not crash coverage.

The adopter under test is constructed around a directly built
VerifierClient in research mode (the R12 pattern, as in
tests/test_trust_pin_adoption.py): crash semantics are
mode-independent verifier/adopter behaviour. Production-mode
composition is covered by tests/test_trust_production_e2e.py.
"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CoreLoop
from eval.registry import EvalRegistry
from signing import generate_key_file, make_signing_key
from signing.ceremony_authorisation import (
    ceremony_public_key_for,
    generate_ceremony_key_file,
)
from signing.pin_store import PinStore
from trust.client import VerifierClient
from trust.ledger import (
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
)
from trust.pin_adoption import (
    PinAdopter,
    PinAdopterConfig,
    PinAdoptionBurned,
    PinAdoptionRefused,
    PinSupersessionPendingApproval,
)
from trust.supersession_approval import (
    supersession_approval_to_json,
)
from trust.supersession_approval_tool import (
    approver_public_key_for,
    build_approval_for_report,
    generate_approver_key_file,
)

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
# Deterministic snapshot key: the crash child reconstructs the
# identical key from the same bytes (see cycle23_crash_child).
SNAP_KEY = make_signing_key(bytes(range(32, 64)))
SNAP_SIGNER = "seat-3"
OPERATOR = "operator-1"
OPERATORS = "operator-1,operator-2"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
CAL = b'{"log":1}'
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 1, "after": 2,
         "evidence_ref": "ev-1", "verifier": "rev-1"}
REPO_ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).resolve().parent / "cycle23_crash_child.py"


class CrashFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.seed_path = base / "ceremony.seed"
        self.seed_key = generate_ceremony_key_file(self.seed_path)
        self.pub = ceremony_public_key_for(self.seed_key)
        self.evidence_dir = base / "evidence"
        self.evidence_dir.mkdir()
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt, expected,
                                     "test-actor")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
            "AION_CEREMONY_OPERATORS": OPERATORS,
            "AION_CEREMONY_EVIDENCE_DIR": str(self.evidence_dir),
            "AION_CEREMONY_SIGNING_SEED_PATH": str(self.seed_path),
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        self.state_dir = base / "state"
        self.loop = CoreLoop(self.state_dir)
        cal_dir = self.state_dir / "calibration"
        cal_dir.mkdir(parents=True, exist_ok=True)
        self.calibration_path = cal_dir / "calibration.json"
        self.calibration_path.write_bytes(CAL)
        self.pin_dir = base / "pins"
        self.store = PinStore(self.pin_dir, state_dir=self.state_dir)
        self.adopter = self.fresh_adopter()
        self.barrier_dir = base / "barriers"
        self.barrier_dir.mkdir()
        self._item_seq = 0
        self._child_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def fresh_adopter(self):
        """A new PinAdopter over the same store/client — the
        in-process stand-in for a process restart (the store
        and verifier are the persistent parties)."""
        config = PinAdopterConfig(
            state_path=self.loop.state_path,
            calibration_path=self.calibration_path,
            pin_dir=self.pin_dir,
            snapshot_signer_id=SNAP_SIGNER,
            expected_snapshot_signer_id=SNAP_SIGNER,
            operator_id=OPERATOR,
            expected_verifier_signer_id=SIGNER,
            evidence_dir=self.evidence_dir)
        return PinAdopter(client=self.client, store=self.store,
                          signing_key=SNAP_KEY, config=config,
                          authorisation_public_key=self.pub)

    def scan_items(self, n):
        start = self._item_seq
        items = [{"id": f"item-{start + i}",
                  "title": f"Crash item {start + i}",
                  "leverage": float(n - i)}
                 for i in range(1, n + 1)]
        self._item_seq = start + n
        self.loop.scan(items)

    def bare_cycle(self):
        return self.loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)

    def genesis(self):
        self.scan_items(1)
        self.bare_cycle()
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "initial_anchor")
        return result

    def consumption_entries(self):
        ledger = CeremonyConsumptionLedger(self.home / "ledger")
        return ledger.entries()

    def read_store(self):
        return self.store.read_all(signing_key=SNAP_KEY)

    def burn_once(self):
        """One ceremony whose consumption commits but whose
        adoption fails (adopt seam); returns the Burned
        exception. The pair it carries is the caller's to keep
        or discard."""
        real_adopt = self.store.adopt
        state = {"armed": True}

        def flaky_adopt(new_pin, record=None, **kw):
            if record is not None and state["armed"]:
                state["armed"] = False
                raise OSError("simulated adopt failure")
            return real_adopt(new_pin, record, **kw)

        self.store.adopt = flaky_adopt
        try:
            with self.assertRaises(PinAdoptionBurned) as cm:
                self.adopter.snapshot_and_adopt()
        finally:
            self.store.adopt = real_adopt
        return cm.exception

    # -- subprocess plumbing ------------------------------------

    def spawn_child(self, mode, *, pair_path=None, tag=""):
        self._child_seq += 1
        stem = f"child-{mode}-{self._child_seq}{tag}"
        result_path = self.base / f"{stem}-result.json"
        config = {
            "mode": mode,
            "env": self.env,
            "state_dir": str(self.state_dir),
            "calibration_path": str(self.calibration_path),
            "pin_dir": str(self.pin_dir),
            "evidence_dir": str(self.evidence_dir),
            "barrier_dir": str(self.barrier_dir),
            "result_path": str(result_path),
            "pair_path": str(pair_path) if pair_path else None,
            "snap_signer": SNAP_SIGNER,
            "operator": OPERATOR,
            "signer": SIGNER,
            "pub_key_hex": self.pub.public_key.hex(),
            "pub_key_id": self.pub.key_id,
        }
        config_path = self.base / f"{stem}-config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(CHILD), str(config_path)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc, result_path

    def wait_barrier(self, name, timeout=180.0):
        deadline = time.monotonic() + timeout
        target = self.barrier_dir / name
        while time.monotonic() < deadline:
            if target.exists():
                return
            time.sleep(0.05)
        self.fail(f"barrier {name} never appeared")

    def wait_child(self, proc, timeout=300.0):
        try:
            _out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            self.fail("child did not exit in time")
        return proc.returncode, err


class CrashSubprocessTests(CrashFixture):
    """R4 scenarios 1 and 7: true subprocess crash coverage."""

    def test_scenario1_kill_after_consume_pair_retained(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.assertEqual(len(self.consumption_entries()), 1)
        pair_path = self.base / "returned-pair.json"
        proc, _result = self.spawn_child("burn", pair_path=pair_path)
        # The child signals strictly after the consumption has
        # committed at the verifier and before adoption.
        self.wait_barrier("consumed")
        self.assertIsNone(proc.poll())
        proc.kill()  # SIGKILL: no cleanup, no finally, no adopt
        proc.wait(timeout=30)
        # The burn is real; the pin never moved.
        self.assertEqual(len(self.consumption_entries()), 2)
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertEqual(len(history), 1)
        # Restart with the retained pair: adopt_returned, in a
        # fresh process, with NO new consumption.
        proc2, result2 = self.spawn_child(
            "adopt-returned", pair_path=pair_path)
        returncode, err = self.wait_child(proc2)
        self.assertEqual(returncode, 0, err.decode("utf-8", "replace"))
        outcome = json.loads(result2.read_text(encoding="utf-8"))
        self.assertEqual(outcome["outcome"], "reanchored")
        self.assertEqual(outcome["pin_seq"], 3)
        self.assertEqual(len(self.consumption_entries()), 2)
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 3)
        self.assertEqual(len(history), 2)

    def test_scenario1_kill_after_consume_pair_discarded(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        proc, _result = self.spawn_child("burn", pair_path=None)
        self.wait_barrier("consumed")
        self.assertIsNone(proc.poll())
        proc.kill()  # SIGKILL; no pair was ever recorded
        proc.wait(timeout=30)
        self.assertEqual(len(self.consumption_entries()), 2)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 1)
        # Restart without the pair: a fresh burned_unadopted
        # recovery ceremony at depth 1, one new consumption.
        restarted = self.fresh_adopter()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "burned_unadopted")
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[-1].get("consumption_kind"),
                         "recovery")
        self.assertEqual(entries[-1].get("recovery_depth"), 1)
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 3)
        self.assertNotIn("lost_pin", [r.reason for r in history])

    def test_scenario7_concurrent_adopters_exactly_one_wins(self):
        self.genesis()
        self.scan_items(1)
        self.bare_cycle()  # seq 2: the dense advance path
        proc1, result1 = self.spawn_child("race", tag="-a")
        proc2, result2 = self.spawn_child("race", tag="-b")
        rc1, err1 = self.wait_child(proc1)
        rc2, err2 = self.wait_child(proc2)
        self.assertEqual(rc1, 0, err1.decode("utf-8", "replace"))
        self.assertEqual(rc2, 0, err2.decode("utf-8", "replace"))
        outcomes = [json.loads(p.read_text(encoding="utf-8"))
                    for p in (result1, result2)]
        advanced = [o for o in outcomes if o.get("outcome") == "advanced"]
        refused = [o for o in outcomes
                   if o.get("exception") == "PinAdoptionRefused"]
        # Exactly one adoption lands; the loser surfaces the
        # store's CAS/busy refusal as PinAdoptionRefused.
        self.assertEqual(len(advanced), 1, outcomes)
        self.assertEqual(len(refused), 1, outcomes)
        # The store verifies afterwards: no corrupt or
        # double-adopted state, pin at seq 2, history untouched.
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 2)
        self.assertEqual(len(history), 1)
        self.assertEqual(len(self.consumption_entries()), 1)


class CrashStateSurgeryTests(CrashFixture):
    """R4 scenarios 2–4: STATE SURGERY on the pending journal /
    candidate side file. These pin degradation behaviour of the
    detection aids; they are not crash coverage (R4 method
    rules). The pinned class throughout: refusal / liveness
    loss only — never an unsafe pin movement."""

    def test_scenario2_torn_pending_journal_tail_skipped(self):
        self.genesis()
        journal = self.adopter.pending_journal_path
        with open(journal, "ab") as fh:
            fh.write(b'{"ceremony_id": "pin-adopt-9-torn", '
                     b'"phase": "authorised", "cand')  # torn tail
        restarted = self.fresh_adopter()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "already_current")
        self.scan_items(1)
        self.bare_cycle()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "advanced")
        self.assertEqual(result.pin["cycle_seq"], 2)
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_scenario2_authorise_pending_only_proceeds_primary(self):
        # A pending line with NO authorised line proves nothing
        # could have consumed (program order in _reanchor), so
        # the next attempt proceeds with a fresh PRIMARY
        # ceremony — the R4 authorise_pending pin.
        self.genesis()
        pin, _history = self.read_store()
        journal = self.adopter.pending_journal_path
        line = {"phase": "authorise_pending",
                "ceremony_id": "pin-adopt-3-deadbeef",
                "candidate_seq": 3, "candidate_hash": "0" * 64,
                "old_cycle_seq": pin["cycle_seq"],
                "old_payload_hash": pin["payload_hash"]}
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        result = self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_scenario3_midfile_corruption_detection_aid_only(self):
        self.genesis()
        journal = self.adopter.pending_journal_path
        lines = journal.read_bytes().splitlines(keepends=True)
        self.assertGreaterEqual(len(lines), 3)
        lines[0] = b"### not json ###\n"  # mid-file garbage
        journal.write_bytes(b"".join(lines))
        restarted = self.fresh_adopter()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "already_current")
        self.scan_items(1)
        self.bare_cycle()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "advanced")
        self.assertEqual(len(self.consumption_entries()), 1)

    def test_scenario3_corruption_loses_detection_not_safety(self):
        # F4.2 class: corrupting the authorised line of an
        # unadopted burn loses DETECTION of the burn. The next
        # attempt cannot re-present the burned candidate, its
        # fresh candidate is refused at the consumption head,
        # and the pin does not move — degradation to refusal,
        # never an unsafe movement.
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.burn_once()
        self.assertEqual(len(self.consumption_entries()), 2)
        journal = self.adopter.pending_journal_path
        raw_lines = journal.read_bytes().splitlines(keepends=True)
        out = []
        for raw in raw_lines:
            if b'"authorised"' in raw and b"authorise_pending" not in raw:
                out.append(b"### corrupted ###\n")
            else:
                out.append(raw)
        journal.write_bytes(b"".join(out))
        with self.assertRaises(PinAdoptionBurned):
            self.fresh_adopter().snapshot_and_adopt()
        pin, history = self.read_store()  # store still verifies
        self.assertEqual(pin["cycle_seq"], 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(len(self.consumption_entries()), 2)

    def test_scenario4_candidate_side_file_loss_refuses_then_unfreezes(self):
        self.genesis()
        self.scan_items(1)
        self.bare_cycle()
        result = self.adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "advanced")
        side_file = self.pin_dir / "snapshot-candidate.json"
        self.assertTrue(side_file.is_file())
        side_file.unlink()
        # Unchanged state: a fresh signing cannot reproduce the
        # pin's hash, so this is an integrity refusal — NOT a
        # lost_pin ceremony, and nothing is consumed.
        with self.assertRaises(PinAdoptionRefused):
            self.fresh_adopter().snapshot_and_adopt()
        pin, history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 2)
        # Explicit (fix round, r5-F4): NO ceremony record in
        # the pin store history carries reason "lost_pin" —
        # the side-file loss was an integrity refusal, not a
        # lost_pin ceremony.
        self.assertNotIn("lost_pin", [r.reason for r in history])
        self.assertEqual(len(self.consumption_entries()), 1)
        # The next cycle unfreezes the pin via the advance path.
        self.scan_items(1)
        self.bare_cycle()
        result = self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(result.outcome, "advanced")
        self.assertEqual(result.pin["cycle_seq"], 3)


class RecoverySeamTests(CrashFixture):
    """R4 scenarios 5–6 via the adopt MONKEYPATCH SEAM
    (flaky adopt). These pin recovery semantics; per R4 they
    may not be cited as crash coverage — scenario 1 above is
    the crash form of the same deaths."""

    def test_scenario5_returned_pair_available_no_new_consumption(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        old_pin, _history = self.read_store()
        burned = self.burn_once()
        self.assertIsNotNone(burned.returned_pin)
        self.assertIsNotNone(burned.returned_record)
        self.assertEqual(len(self.consumption_entries()), 2)
        restarted = self.fresh_adopter()
        result = restarted.adopt_returned(
            burned.returned_pin, burned.returned_record,
            expected_old_pin=old_pin)
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(len(self.consumption_entries()), 2)
        pin, history = self.read_store()
        self.assertEqual(pin, burned.returned_pin)
        self.assertEqual(history[-1], burned.returned_record)

    def test_scenario5_returned_pair_discarded_burned_recovery(self):
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.burn_once()  # pair discarded
        self.assertEqual(len(self.consumption_entries()), 2)
        result = self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "burned_unadopted")
        entries = self.consumption_entries()
        self.assertEqual(len(entries), 3)  # exactly one new
        self.assertEqual(entries[-1].get("recovery_depth"), 1)
        _pin, history = self.read_store()
        self.assertNotIn("lost_pin", [r.reason for r in history])

    def test_scenario6_recovery_chain_cap2_then_terminal(self):
        # Movement to seq 3: primary burn, depth-1 recovery
        # burn, depth-2 recovery LANDS (cap 2, schema v2).
        self.genesis()
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.burn_once()                       # primary consumed
        self.burn_once()                       # depth-1 consumed
        result = self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "burned_unadopted")
        movement = [e for e in self.consumption_entries()
                    if e["new_cycle_seq"] == 3]
        self.assertEqual(
            [(e.get("consumption_kind"), e.get("recovery_depth"))
             for e in movement],
            [("primary", 0), ("recovery", 1), ("recovery", 2)])
        # Movement to seq 5: burn at primary, depth 1 and
        # depth 2 — the movement is then TERMINAL: the next
        # recovery attempt is refused (authorise refuses with
        # ceremony_recovery_unproven, surfaced as
        # PinAdoptionRefused, or the consume refuses as
        # already-consumed, surfaced as PinAdoptionBurned).
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.burn_once()
        self.burn_once()
        depth2_burn = self.burn_once()
        consumed_before = len(self.consumption_entries())
        with self.assertRaises((PinAdoptionRefused, PinAdoptionBurned)):
            self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 3)
        # Liveness at the next snapshot sequence (the shape
        # seat 1's schema-v2 suite pins at the verifier level):
        # the pin is first reconciled TO the consumed head —
        # here via adopt_returned of the retained depth-2
        # pair — after which a primary chain_gap_recovery off
        # the head lands. NOTE (finding, FIXED by the cycle-23
        # fix seat): this scenario originally recorded a
        # deadlock — with the depth-2 pair DISCARDED, no
        # adopter-level primary could ever land again, because
        # check_head refused any primary whose old pin was
        # behind the consumed head and the pin could not
        # advance past the burned sequence. The check_head
        # SUPERSEDE rule closes it: a fresh primary whose
        # candidate is strictly ahead of the head may pass a
        # behind-head old pin. The discarded-pair path is
        # pinned at the end of this scenario.
        restarted = self.fresh_adopter()
        pin3, _history = self.read_store()
        result = restarted.adopt_returned(
            depth2_burn.returned_pin, depth2_burn.returned_record,
            expected_old_pin=pin3)
        self.assertEqual(result.pin["cycle_seq"], 5)
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        result = restarted.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.pin["cycle_seq"], 7)
        # Discarded-pair path (the supersede fix): a SECOND
        # movement, to seq 9, is burned at primary, depth 1
        # and depth 2 with EVERY pair discarded, so the
        # movement is terminal and the pin (seq 7) sits
        # behind the consumed head (seq 9) with no retained
        # pair to reconcile from.
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        self.burn_once()                       # primary, discarded
        self.burn_once()                       # depth-1, discarded
        self.burn_once()                       # depth-2, discarded
        consumed_before = len(self.consumption_entries())
        with self.assertRaises((PinAdoptionRefused, PinAdoptionBurned)):
            self.fresh_adopter().snapshot_and_adopt()
        self.assertEqual(len(self.consumption_entries()),
                         consumed_before)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 7)
        # The next snapshot sequence's primary
        # chain_gap_recovery now LANDS via supersede: the
        # candidate (seq 11) is strictly ahead of the head
        # (seq 9) and the old pin (seq 7) is behind it, so
        # the pin jumps past the burned sequence.
        # Cycle 25 RE-PIN (CROSS-CHECK-18 Q1; supersedes the
        # cycle-24 auto-decision re-pin): the first consume
        # refuses ceremony_supersede_required and the adopter
        # STOPS at PinSupersessionPendingApproval — no
        # decision is requested. The landing happens only on
        # a later attempt presenting an out-of-band approval
        # artefact, genuinely signed by the real approval
        # tool under a dedicated approver key against the
        # pending report completed from the verifier's own
        # consumption journal. Outcome assertions are
        # unchanged; the approval assertions are new.
        self.scan_items(2)
        self.bare_cycle()
        self.bare_cycle()
        approver_key = generate_approver_key_file(
            self.base / "approver.seed")
        approver_pub = approver_public_key_for(approver_key)
        env2 = dict(self.env)
        env2["AION_SUPERSESSION_APPROVER_PUBLIC_KEY"] = \
            approver_pub.public_key.hex()
        client2 = VerifierClient(
            verifier_env=env2, expected_signer_id=SIGNER,
            expected_key_id=self.seed_key.key_id,
            authorisation_public_key=self.pub)
        inbox = self.base / "approval-inbox"
        inbox.mkdir()
        approved_adopter = PinAdopter(
            client=client2, store=self.store,
            signing_key=SNAP_KEY,
            config=PinAdopterConfig(
                state_path=self.loop.state_path,
                calibration_path=self.calibration_path,
                pin_dir=self.pin_dir,
                snapshot_signer_id=SNAP_SIGNER,
                expected_snapshot_signer_id=SNAP_SIGNER,
                operator_id=OPERATOR,
                expected_verifier_signer_id=SIGNER,
                evidence_dir=self.evidence_dir,
                supersession_approval_path=inbox),
            authorisation_public_key=self.pub)
        with self.assertRaises(PinSupersessionPendingApproval):
            approved_adopter.snapshot_and_adopt()
        self.assertEqual(
            CeremonySupersessionLedger(self.home / "ledger")
            .entries(), [])
        report = json.loads(
            approved_adopter.pending_report_path.read_text(
                encoding="utf-8"))
        head = self.consumption_entries()[-1]
        self.assertEqual(report["head"]["authorisation_id"],
                         head["authorisation_id"])
        report["head"]["seq"] = head["seq"]
        report["head"]["entry_hash"] = head["entry_hash"]
        signed_approval = build_approval_for_report(
            approver_key=approver_key, approver_id="approver-1",
            report=report)
        (inbox / f"{signed_approval.approval_id}.json"
         ).write_text(
            supersession_approval_to_json(signed_approval),
            encoding="utf-8")
        result = approved_adopter.snapshot_and_adopt()
        self.assertEqual(result.outcome, "reanchored")
        self.assertEqual(result.record.reason, "chain_gap_recovery")
        self.assertEqual(result.pin["cycle_seq"], 11)
        entries = self.consumption_entries()
        self.assertEqual(entries[-1].get("consumption_kind"),
                         "primary")
        self.assertEqual(entries[-1].get("recovery_depth"), 0)
        self.assertEqual(entries[-1]["old_cycle_seq"], 7)
        self.assertEqual(entries[-1]["new_cycle_seq"], 11)
        pin, _history = self.read_store()
        self.assertEqual(pin["cycle_seq"], 11)
        # Exactly ONE supersession decision was journaled in
        # the verifier home for this landing: it abandons the
        # discarded seq-9 movement and binds the seq-11
        # candidate / the final consumption's authorisation.
        decisions = CeremonySupersessionLedger(
            self.home / "ledger").entries()
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision["approval_id"],
                         signed_approval.approval_id)
        self.assertEqual(decision["abandoned_new_cycle_seq"], 9)
        self.assertEqual(decision["candidate_cycle_seq"], 11)
        self.assertEqual(decision["new_authorisation_id"],
                         entries[-1]["authorisation_id"])
        # The adopter's pending journal carries a
        # "supersede_decided" phase line for that ceremony.
        journal_lines = [
            json.loads(line) for line in
            self.adopter.pending_journal_path.read_text(
                encoding="utf-8").splitlines() if line.strip()]
        decided = [line for line in journal_lines
                   if line.get("phase") == "supersede_decided"]
        self.assertEqual(len(decided), 1)
        self.assertEqual(decided[0]["candidate_seq"], 11)
        self.assertEqual(decided[0]["authorisation_id"],
                         entries[-1]["authorisation_id"])


if __name__ == "__main__":
    unittest.main()
