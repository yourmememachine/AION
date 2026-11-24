"""Production entry point end-to-end (cycle 24, DESIGN-FINAL
R2 / design A item 1): ``python3 -m trust.runner`` driven as a
subprocess against a BYTE COPY of the real ``state/`` under the
cycle-23 harness production home. The real state directory is
never written: its state.json sha256 is asserted identical
before and after.

Sequence mirrors tests/test_cycle23_live_run.py:
  invocation 1 [adopt, cycle] -> genesis initial_anchor @13
    (exactly 1 consumption), then a hooked cycle recording the
    copy's pick_next item and advancing the pin to 14;
  two test-side hookless cycles open the gap (15, 16);
  invocation 2 [adopt, adopt] -> chain_gap_recovery ceremony
    to 16, then already_current. Exactly 2 consumptions total.
Plus design A's negative tests.
"""

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cycle23_harness import OPERATOR, SIGNER, SNAP_SIGNER, \
    provision_production_home
from core.loop import CoreLoop
from signing.pin_store import PinStore
from trust.ledger import (
    CeremonyConsumptionLedger,
    CeremonySupersessionLedger,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_STATE_DIR = REPO_ROOT / "state"
CODERS = ["coder-1", "coder-2", "coder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
DELTA = {"metric": "tests", "before": 13, "after": 14,
         "evidence_ref": "cycle24-runner", "verifier": "rev-1"}
CYCLE_STEP = {"cycle": {"coders": CODERS, "reviewers": REVIEWERS,
                        "verdict": "reconciled",
                        "verify_passed": True, "delta": DELTA}}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.real_hash_before = _sha256(REAL_STATE_DIR / "state.json")
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.state_dir = base / "state"
        shutil.copytree(REAL_STATE_DIR, self.state_dir)
        self.home = provision_production_home(base / "prod-home")
        self.pin_dir = base / "pins"
        self._plan_counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers -----------------------------------------------------

    def base_env(self):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
               "PYTHONPATH": str(REPO_ROOT)}
        env.update(self.home.env)
        env.update({
            "AION_PIN_DIR": str(self.pin_dir),
            "AION_PIN_SIGNING_KEY_PATH":
                str(self.home.snapshot_key_path),
            "AION_PIN_SIGNER_ID": SNAP_SIGNER,
            "AION_PIN_OPERATOR_ID": OPERATOR,
            "AION_PIN_EVIDENCE_DIR": str(self.home.evidence_dir),
            "AION_RUNNER_STATE_DIR": str(self.state_dir),
            "AION_RUNNER_EXPECTED_SIGNER_ID": SIGNER,
            "AION_RUNNER_EXPECTED_KEY_ID": self.home.verifier_key_id,
            "AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX":
                self.home.pub.public_key.hex(),
        })
        return env

    def run_runner(self, plan_steps, *, extra_args=(),
                   env_mutate=None):
        self._plan_counter += 1
        plan_path = self.base / f"plan-{self._plan_counter}.json"
        plan_path.write_text(
            json.dumps({"steps": plan_steps}), encoding="utf-8")
        env = self.base_env()
        env["AION_RUNNER_PLAN_PATH"] = str(plan_path)
        if env_mutate is not None:
            env_mutate(env)
        return subprocess.run(
            [sys.executable, "-m", "trust.runner", *extra_args],
            capture_output=True, timeout=120, cwd=str(REPO_ROOT),
            env=env)

    @staticmethod
    def parse_lines(proc):
        return [json.loads(line) for line in
                proc.stdout.decode("utf-8").splitlines()
                if line.strip()]

    def consumption_count(self):
        ledger = CeremonyConsumptionLedger(self.home.verifier_home)
        return len(ledger.entries())

    def read_pin(self):
        store = PinStore(self.pin_dir, state_dir=self.state_dir)
        pin, _history = store.read_all(
            signing_key=self.home.snapshot_key)
        return pin

    def run_runner_holding_pin_lock(self, plan_steps):
        """Run the runner while this process holds the pin
        store's adopt flock: the adopter's ceremony consumes,
        then PinStore.adopt fails (PinStoreBusy) — a genuine
        post-consumption burn, induced purely through the
        filesystem, the only seam a subprocess test has."""
        self.pin_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.pin_dir / ".snapshot-pin.lock",
                     os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return self.run_runner(plan_steps)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def assert_real_state_untouched(self):
        self.assertEqual(
            _sha256(REAL_STATE_DIR / "state.json"),
            self.real_hash_before)

    # -- main sequence -------------------------------------------------

    def test_runner_replays_cycle23_live_run_shape(self):
        expected_item = CoreLoop(self.state_dir).pick_next()
        self.assertIsNotNone(expected_item)

        # Invocation 1: [adopt, cycle].
        proc = self.run_runner([{"adopt": True}, CYCLE_STEP])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["kind"], "adopt")
        self.assertEqual(lines[0]["outcome"], "reanchored")
        self.assertEqual(lines[0]["pin_seq"], 13)
        self.assertEqual(lines[0]["record_reason"], "initial_anchor")
        self.assertEqual(lines[1]["kind"], "cycle")
        self.assertEqual(lines[1]["outcome"], "recorded")
        self.assertEqual(lines[1]["cycle_id"], 14)
        self.assertEqual(lines[1]["item_id"], expected_item["id"])
        pin = self.read_pin()
        self.assertEqual(pin["cycle_seq"], 14)
        self.assertEqual(self.consumption_count(), 1)

        # Gap, test-side only: two hookless cycles -> 15, 16.
        for expected_seq in (15, 16):
            loop = CoreLoop(self.state_dir)
            entry = loop.run_one_cycle(
                CODERS, REVIEWERS, "reconciled", True, DELTA)
            self.assertEqual(entry["cycle_id"], expected_seq)
        self.assertEqual(self.read_pin()["cycle_seq"], 14)
        self.assertEqual(self.consumption_count(), 1)

        # Invocation 2: [adopt, adopt].
        proc = self.run_runner([{"adopt": True}, {"adopt": True}])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["outcome"], "reanchored")
        self.assertEqual(lines[0]["pin_seq"], 16)
        self.assertEqual(lines[0]["record_reason"],
                         "chain_gap_recovery")
        self.assertEqual(lines[1]["outcome"], "already_current")
        self.assertEqual(lines[1]["pin_seq"], 16)
        self.assertIsNone(lines[1]["record_reason"])

        # The copy's pin store verifies at seq 16, history 2.
        store = PinStore(self.pin_dir, state_dir=self.state_dir)
        pin, history = store.read_all(
            signing_key=self.home.snapshot_key)
        self.assertEqual(pin["cycle_seq"], 16)
        self.assertEqual(len(history), 2)
        self.assertEqual(self.consumption_count(), 2)
        self.assert_real_state_untouched()

    # -- exit paths 3 / 4 / 5 and idle (r2-F3) -------------------------
    # PinAdoptionRefused and PinAdoptionBurned both subclass
    # SigningError, so exits 3/4/5 vs 6 rest entirely on the
    # runner's except-clause ordering; these tests pin it.

    def test_adopt_step_refused_is_exit_3(self):
        # A pin store file that fails verified capture makes
        # the adopt step raise PinAdoptionRefused before any
        # ceremony: nothing consumed, nothing persisted.
        self.pin_dir.mkdir(parents=True, exist_ok=True)
        (self.pin_dir / "snapshot-pin.json").write_bytes(
            b"### not a pin store ###")
        proc = self.run_runner([{"adopt": True}])
        self.assertEqual(proc.returncode, 3, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["kind"], "adopt")
        self.assertEqual(lines[0]["outcome"], "adoption_refused")
        self.assertEqual(lines[0]["error"], "PinAdoptionRefused")
        self.assertEqual(self.consumption_count(), 0)
        self.assertEqual(
            CoreLoop(self.state_dir).state["cycle_seq"], 13)
        self.assert_real_state_untouched()

    def test_adopt_step_burned_is_exit_4(self):
        # Adopt lock held: the genesis ceremony consumes, the
        # adoption then fails — PinAdoptionBurned, exit 4 (not
        # 6: the typed adoption errors precede SigningError).
        proc = self.run_runner_holding_pin_lock([{"adopt": True}])
        self.assertEqual(proc.returncode, 4, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["kind"], "adopt")
        self.assertEqual(lines[0]["outcome"], "adoption_burned")
        self.assertEqual(lines[0]["error"], "PinAdoptionBurned")
        # The burn is real: exactly one consumption, no pin.
        self.assertEqual(self.consumption_count(), 1)
        self.assertFalse(
            (self.pin_dir / "snapshot-pin.json").exists())
        self.assertEqual(
            CoreLoop(self.state_dir).state["cycle_seq"], 13)
        self.assert_real_state_untouched()

    def test_cycle_step_hook_burn_is_exit_5_cycle_recorded(self):
        # Same held lock, but through a cycle step: the cycle
        # records (seq 14) and persists BEFORE the hook fires;
        # the hook's ceremony consumes and its adoption burns.
        expected_item = CoreLoop(self.state_dir).pick_next()
        self.assertIsNotNone(expected_item)
        proc = self.run_runner_holding_pin_lock([CYCLE_STEP])
        self.assertEqual(proc.returncode, 5, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["kind"], "cycle")
        self.assertEqual(
            lines[0]["outcome"], "cycle_recorded_pin_pending")
        self.assertEqual(lines[0]["cycle_id"], 14)
        self.assertEqual(lines[0]["item_id"], expected_item["id"])
        self.assertEqual(
            lines[0]["adoption_error"], "PinAdoptionBurned")
        # The cycle IS recorded in the copy's state; the pin
        # did not move (no pin file) though one consumption
        # committed.
        loop = CoreLoop(self.state_dir)
        self.assertEqual(loop.state["cycle_seq"], 14)
        self.assertEqual(loop.state["history"][-1]["cycle_id"], 14)
        self.assertEqual(self.consumption_count(), 1)
        self.assertFalse(
            (self.pin_dir / "snapshot-pin.json").exists())
        self.assert_real_state_untouched()

    def test_adopt_step_beyond_head_burn_refuses_incomplete_is_exit_6(self):
        # CHANGED in the cycle-28 external fix round (seat-gpt
        # FIX 0.91) — previously this shape expected exit 7
        # (supersession pending). The known-unadopted head
        # excuse in history reconciliation no longer reaches a
        # candidate strictly BEYOND the head burn: that reach
        # silently excused an ADOPTED record's disappearance in
        # the compound adopted-line-loss + store-restore state,
        # which is indistinguishable from a genuine burn at the
        # reconciliation layer. Claim narrowing, recorded in
        # internal/cycle28-work/fix-round-gpt.md: the wired
        # adopt step now refuses pin_store_history_incomplete
        # (a SigningError — runner exit 6, step_refused) BEFORE
        # any ceremony, so this shape no longer reaches the
        # supersession-pending stop. The pending flow remains
        # reachable for a candidate AT the head burn's own
        # sequence: the at-sequence excuse is unit-pinned by
        # cycle-28 test_09/test_10 and the pending flow itself
        # is covered by the supersession suites on the unwired
        # adopter — a wired at-sequence pending composition
        # test is a named follow-up (re-review seat, fix
        # round), not existing coverage. A beyond-head genuine
        # burn is an operator-reconciliation residual, named
        # in internal/BUILD-CYCLE-28.md.
        # Shape: genesis adopt @13; two test-side hookless
        # cycles open state to 15; a held-lock adopt burns the
        # 13->15 ceremony movement (pin stays 13, head 15);
        # one more hookless cycle opens state to 16, so the
        # next adopt's fresh primary (candidate 16, old pin 13
        # behind head 15) is beyond the head burn.
        proc = self.run_runner([{"adopt": True}])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(self.read_pin()["cycle_seq"], 13)
        for expected_seq in (14, 15):
            loop = CoreLoop(self.state_dir)
            entry = loop.run_one_cycle(
                CODERS, REVIEWERS, "reconciled", True, DELTA)
            self.assertEqual(entry["cycle_id"], expected_seq)
        proc = self.run_runner_holding_pin_lock([{"adopt": True}])
        self.assertEqual(proc.returncode, 4, proc.stderr.decode())
        self.assertEqual(self.read_pin()["cycle_seq"], 13)
        self.assertEqual(self.consumption_count(), 2)
        loop = CoreLoop(self.state_dir)
        entry = loop.run_one_cycle(
            CODERS, REVIEWERS, "reconciled", True, DELTA)
        self.assertEqual(entry["cycle_id"], 16)

        proc = self.run_runner([{"adopt": True}])
        self.assertEqual(proc.returncode, 6, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["kind"], "adopt")
        self.assertEqual(line["outcome"], "step_refused")
        self.assertEqual(
            line["error"], "HistoryReconciliationRefused")
        # Nothing decided, nothing more consumed, pin unmoved.
        self.assertEqual(self.consumption_count(), 2)
        self.assertEqual(
            CeremonySupersessionLedger(
                self.home.verifier_home).entries(), [])
        self.assertEqual(self.read_pin()["cycle_seq"], 13)
        self.assert_real_state_untouched()

    def test_idle_cycle_step_is_exit_0(self):
        # Idle is a cycle step with no pickable backlog item
        # (a literally empty steps list is a plan refusal —
        # the schema requires 1..100 steps). Exhaust the copy's
        # backlog test-side; the hook never fires for idle.
        state_path = self.state_dir / "state.json"
        doc = json.loads(state_path.read_text(encoding="utf-8"))
        for item in doc["backlog"]:
            if item["status"] == "pending":
                # "blocked", not "done": the loop's state
                # validation requires done <=> a history entry.
                item["status"] = "blocked"
        state_path.write_text(json.dumps(doc), encoding="utf-8")
        copy_hash = _sha256(state_path)
        proc = self.run_runner([CYCLE_STEP])
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(
            lines, [{"step": 0, "kind": "cycle", "outcome": "idle"}])
        # No cycle recorded, no pin movement, no consumption.
        self.assertEqual(_sha256(state_path), copy_hash)
        self.assertEqual(self.consumption_count(), 0)
        self.assertFalse(
            (self.pin_dir / "snapshot-pin.json").exists())
        self.assert_real_state_untouched()

    # -- negatives -------------------------------------------------------

    def test_huge_integer_delta_is_plan_refusal_no_traceback(self):
        # r2-F1: 10**400 is a valid JSON integer but overflows
        # float conversion in math.isfinite; it must be a
        # structured exit-2 plan refusal, not an exit-1 crash.
        copy_hash = _sha256(self.state_dir / "state.json")
        delta = dict(DELTA, before=10**400)
        step = {"cycle": {"coders": CODERS, "reviewers": REVIEWERS,
                          "verdict": "reconciled",
                          "verify_passed": True, "delta": delta}}
        proc = self.run_runner([step])
        self.assertEqual(proc.returncode, 2, proc.stderr.decode())
        self.assertEqual(proc.stdout, b"")
        stderr = proc.stderr.decode()
        self.assertNotIn("Traceback", stderr)
        # The refusal value is never echoed.
        self.assertNotIn(str(10**400), stderr)
        line = json.loads(stderr.strip())
        self.assertEqual(line["error"], "config_refusal")
        self.assertEqual(line["variable"], "AION_RUNNER_PLAN_PATH")
        self.assertIn("finite", line["detail"])
        # State untouched: no step executed, no pin, no burn.
        self.assertEqual(
            _sha256(self.state_dir / "state.json"), copy_hash)
        self.assertFalse(self.pin_dir.exists())
        self.assertEqual(self.consumption_count(), 0)
        self.assert_real_state_untouched()

    def test_missing_ceremony_key_hex_is_config_refusal(self):
        copy_hash = _sha256(self.state_dir / "state.json")

        def drop(env):
            del env["AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX"]

        proc = self.run_runner([{"adopt": True}], env_mutate=drop)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertIn("AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX",
                      proc.stderr.decode())
        self.assertEqual(
            _sha256(self.state_dir / "state.json"), copy_hash)
        self.assertFalse(self.pin_dir.exists())

    def test_malformed_ceremony_key_hex_is_config_refusal(self):
        good = self.home.pub.public_key.hex()
        cases = {
            "63 chars": good[:-1],
            "66 chars": good + "ab",
            "non-hex char": good[:-1] + "g",
            "uppercase": "A" * 64,
        }
        for label, bad in cases.items():
            with self.subTest(case=label):
                def set_bad(env, bad=bad):
                    env["AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX"] = bad

                proc = self.run_runner(
                    [{"adopt": True}], env_mutate=set_bad)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(proc.stdout, b"")
                self.assertIn(
                    "AION_RUNNER_CEREMONY_PUBLIC_KEY_HEX",
                    proc.stderr.decode())
        self.assertFalse(self.pin_dir.exists())

    def test_missing_state_json_is_config_refusal_no_bootstrap(self):
        empty = self.base / "empty-state"
        empty.mkdir()

        def point_elsewhere(env):
            env["AION_RUNNER_STATE_DIR"] = str(empty)

        proc = self.run_runner(
            [{"adopt": True}], env_mutate=point_elsewhere)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertIn("AION_RUNNER_STATE_DIR", proc.stderr.decode())
        # No CoreLoop fresh-state bootstrap happened.
        self.assertFalse((empty / "state.json").exists())
        self.assertEqual(list(empty.iterdir()), [])

    def test_malformed_plan_refuses_before_any_step(self):
        proc = self.run_runner([{"adopt": True}, {"bogus": 1}])
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertIn("AION_RUNNER_PLAN_PATH", proc.stderr.decode())
        # Whole-plan validation precedes execution: the adopt
        # step never ran.
        self.assertFalse(self.pin_dir.exists())
        self.assertEqual(self.consumption_count(), 0)

    def test_split_verdict_cycle_step_is_step_refused(self):
        step = {"cycle": {"coders": CODERS, "reviewers": REVIEWERS,
                          "verdict": "split", "verify_passed": True,
                          "delta": DELTA}}
        proc = self.run_runner([step])
        self.assertEqual(proc.returncode, 6, proc.stderr.decode())
        lines = self.parse_lines(proc)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["outcome"], "step_refused")
        self.assertEqual(
            CoreLoop(self.state_dir).state["cycle_seq"], 13)
        self.assert_real_state_untouched()

    def test_extra_argv_is_config_refusal(self):
        proc = self.run_runner(
            [{"adopt": True}], extra_args=("extra",))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b"")
        self.assertFalse(self.pin_dir.exists())


if __name__ == "__main__":
    unittest.main()
