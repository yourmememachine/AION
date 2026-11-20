"""Ship crash laboratory (Trust Boundary v3, mandate item 2;
CROSS-CHECK-4 seat-gpt F2).

The v2 recovery tests hand-constructed crash states. This lab
does not: every crash state is produced by a REAL process kill
(os._exit(99) inside tests/fixtures/ship_crash_runner.py) at a
named durable side-effect boundary of record_ship, after the
side effect landed and before the next step. Recovery is then
run twice from fresh objects and the settlement is checked for
exactly-once semantics: one burn iff the burn landed, at most
one loop cycle for the item, a COMMITTED finalise naming exactly
that cycle, no AUTHORISATION_VERIFIED journaled by recovery, and
a settled decision that can never ship again.

Crash coverage claim (Trust Boundary v3 fix round B, narrowed
— this wording replaces any broader "every boundary" phrasing):
"Fault injection covers every durable side-effect boundary of
record_ship — the tx-journal transitions, the ship-ledger burn
and finalise saves, the loop cycle save, the COMMITTED
transition and, in the anchored variant, the anchor update —
either directly, by a real process kill at that boundary (the
after-* points and the during_burn_save / during_tx_save /
during_finalise_save / during_anchor_save points), or, for the
remaining during-save windows, by the state-equivalence
argument below, which shows each such window leaves a disk
state equivalent in every file recovery reads to an adjacent
directly-tested after-point. No durable side-effect boundary
of record_ship beyond those named here is claimed."

State-equivalence argument: every save in the ship path is
atomic tmp + fsync + replace + dir-fsync — HashChainJournal
._save (ship ledger), ShipTxJournal._write_locked (tx
journal), CoreLoop.save (loop state) and
trust.anchoring._write_json_atomic (anchor). A kill inside
such a save before its os.replace lands therefore leaves the
previous version of the target file byte-for-byte intact (the
only extra artefact is an orphaned tmp file, which no loader
reads), so the disk state recovery sees is the state the
PREVIOUS step left — exactly an adjacent tested after-point:

    during-loop-save     ≡ after_burn
        (the loop state file is unchanged, so no cycle is
        recorded; the burn has landed and the tx sits at
        BURN_PENDING — the after_burn disk state)
    during-finalise-save ≡ after_post_record_verified
        (the ship-ledger file is unchanged, so no finalise is
        recorded; the tx sits at POST_RECORD_VERIFIED — the
        after_post_record_verified disk state; this window is
        ALSO killed directly, as during_finalise_save, and the
        direct test pins the equivalence)
    during-commit-save   ≡ after_finalise
        (the tx-journal file is unchanged, so COMMITTED is not
        journaled; the finalise has landed and the tx sits at
        POST_RECORD_VERIFIED — the after_finalise disk state)

The same argument covers a kill during any other single
tx-journal transition save (one is killed directly, as
during_tx_save at BURN_PENDING): the journal still shows the
previous transition, which is the preceding after-point. The
one exception is the begin save itself: a kill before its
replace leaves no journal file at all — no transaction, no
burn, nothing for recovery to settle, and a retry begins
fresh. That state is strictly safer than any after-point,
but it is not an equivalence, and it is not claimed as one.

Also here: cross-process concurrency (two shippers racing one
item, two recoveries racing one crashed transaction, and
concurrent ShipLedger burns — the last of which exposed a real
freshness-check race, fixed in trust/ledger.py with a bounded
reload-and-retry in ShipLedger.burn/finalise) and the
duplicate-value attacks (another ship's cycle must never be
attributed to a crashed transaction, two different items with
byte-identical value payloads commit independently, and the
hand-duplicated loop history case — re-labelled in fix round
B as a recovery-LOGIC unit test via a StubLoop, with a
companion test pinning the production behaviour: CoreLoop
loading the duplicated state raises CorruptStateError, so in
production the transaction is left non-terminal and
fail-closed rather than ANOMALY-parked by recovery).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.loop import CorruptStateError, CoreLoop
from trust.anchoring import load_anchor, verify_anchor
from trust.ledger import GENESIS_HASH, ShipLedger
from trust.shipcheck import recover_ship_tx
from trust.shiptx import (
    ABORTED_SPENT,
    ANOMALY,
    AUTHORISATION_VERIFIED,
    BURN_PENDING,
    COMMITTED,
    CYCLE_RECORDED,
    POST_RECORD_VERIFIED,
    PREPARED,
    REFUSED_PRE_BURN,
    ShipTxJournal,
)

RUNNER = Path(__file__).resolve().parent / "fixtures" \
    / "ship_crash_runner.py"
ITEM = "store-enforced-signed-commits"
HAPPY_WALK = [PREPARED, AUTHORISATION_VERIFIED, BURN_PENDING,
              CYCLE_RECORDED, POST_RECORD_VERIFIED, COMMITTED]

# crash point -> (tx state the kill leaves on disk,
#                 burn landed?, loop history entries for item,
#                 terminal state recovery must settle at)
CRASH_TABLE = {
    "after_begin": (PREPARED, False, 0, REFUSED_PRE_BURN),
    "after_auth_verified": (AUTHORISATION_VERIFIED, False, 0,
                            REFUSED_PRE_BURN),
    "after_burn_pending": (BURN_PENDING, False, 0,
                           REFUSED_PRE_BURN),
    "after_burn": (BURN_PENDING, True, 0, ABORTED_SPENT),
    "after_cycle": (BURN_PENDING, True, 1, COMMITTED),
    "after_cycle_journaled": (CYCLE_RECORDED, True, 1, COMMITTED),
    "after_post_record_verified": (POST_RECORD_VERIFIED, True, 1,
                                   COMMITTED),
    "after_finalise": (POST_RECORD_VERIFIED, True, 1, COMMITTED),
    "during_burn_save": (BURN_PENDING, False, 0, REFUSED_PRE_BURN),
    "during_tx_save": (AUTHORISATION_VERIFIED, False, 0,
                       REFUSED_PRE_BURN),
    # during_finalise_save leaves exactly the
    # after_post_record_verified disk state (see the module
    # docstring's state-equivalence argument, which this direct
    # kill now also pins): finalise tmp written, never replaced.
    "during_finalise_save": (POST_RECORD_VERIFIED, True, 1,
                             COMMITTED),
}

# Anchored-variant crash points (AION_ANCHORED=1 in the runner:
# record_ship and recovery both receive the scenario's
# ship-anchor.json anchor_path). All three land AFTER the
# COMMITTED journal transition, so the transaction is already
# terminal on disk; what differs is the anchor.
# crash point -> (anchor seq the kill leaves, anchor is current?)
# A current anchor has seq == number of ship-ledger entries and
# head == the ledger head. A seq-0 anchor is the pre-ship
# genesis anchor: stale (the ledger has 2 entries) but VALID —
# verify_anchor accepts any anchor naming a prefix of the chain.
ANCHORED_CRASH_TABLE = {
    "after_commit": (0, False),
    "after_anchor": (2, True),
    "during_anchor_save": (0, False),
}


def run_runner(scenario_dir, *, crash=None, variant="1", env=None,
               popen=False):
    full_env = dict(os.environ)
    if crash:
        full_env["AION_CRASH_POINT"] = crash
    full_env["AION_VARIANT"] = variant
    if env:
        full_env.update(env)
    cmd = [sys.executable, str(RUNNER), str(scenario_dir)]
    if popen:
        return subprocess.Popen(
            cmd, env=full_env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, env=full_env, capture_output=True,
                          text=True, timeout=120)


def read_scenario(scenario_dir, variant="1"):
    return json.loads(
        (Path(scenario_dir) / f"scenario-{variant}.json")
        .read_text())


class CrashLabFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # -- fresh-object views over a scenario tree -------------------

    def ledger(self, scenario):
        return ShipLedger(Path(scenario) / "verifier-home")

    def journal(self, scenario):
        return ShipTxJournal(Path(scenario) / "verifier-home")

    def loop(self, scenario, subdir="loop-state"):
        return CoreLoop(Path(scenario) / subdir)

    def burns(self, scenario, decision_id=None):
        out = [e for e in self.ledger(scenario).entries()
               if e["kind"] == "burn"]
        if decision_id is not None:
            out = [e for e in out
                   if e["decision_id"] == decision_id]
        return out

    def finalises(self, scenario, decision_id=None):
        out = [e for e in self.ledger(scenario).entries()
               if e["kind"] == "finalise"]
        if decision_id is not None:
            out = [e for e in out
                   if e["decision_id"] == decision_id]
        return out

    def tx_states(self, scenario, tx_id):
        return [e["to_state"] for e in self.journal(scenario).entries()
                if e["tx_id"] == tx_id]

    def anchor_path(self, scenario):
        return Path(scenario) / "ship-anchor.json"

    def recover_twice(self, scenario, *, root=None, loop=None,
                      anchor_path=None):
        """recover_ship_tx twice, each time from fresh objects.
        Returns (first_outcomes, second_outcomes)."""
        root = Path(scenario) / "repo" if root is None else root
        first = recover_ship_tx(
            self.ledger(scenario), loop or self.loop(scenario),
            root=root, anchor_path=anchor_path)
        second = recover_ship_tx(
            self.ledger(scenario), loop or self.loop(scenario),
            root=root, anchor_path=anchor_path)
        return first, second


class CrashPointTests(CrashLabFixture):
    def test_every_crash_point_settles_exactly_once(self):
        for point, (left_state, burn_landed, history_len,
                    terminal) in CRASH_TABLE.items():
            with self.subTest(crash_point=point):
                self._run_point(point, left_state, burn_landed,
                                history_len, terminal)

    def _run_point(self, point, left_state, burn_landed,
                   history_len, terminal):
        scenario = self.base / point
        proc = run_runner(scenario, crash=point)
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info = read_scenario(scenario)
        tx_id, decision_id = info["tx_id"], info["decision_id"]

        # The kill left exactly the state the point names.
        self.assertEqual(self.journal(scenario).state(tx_id),
                         left_state)
        self.assertEqual(len(self.burns(scenario, decision_id)),
                         1 if burn_landed else 0)
        history = [e for e in self.loop(scenario).state["history"]
                   if e["item_id"] == info["item_id"]]
        self.assertEqual(len(history), history_len)
        if point in ("during_burn_save", "during_finalise_save"):
            # Evidence the kill was DURING the save: the tmp file
            # was written but never replaced over the journal.
            self.assertTrue(
                (scenario / "verifier-home"
                 / "ship-ledger.json.tmp").exists())
        if point == "during_tx_save":
            self.assertTrue(
                (scenario / "verifier-home"
                 / "ship-tx.json.tmp").exists())

        # Snapshot the tx journal before recovery: recovery must
        # never journal AUTHORISATION_VERIFIED.
        auth_before = self.tx_states(scenario, tx_id).count(
            AUTHORISATION_VERIFIED)
        tx_entries_before = len(self.journal(scenario).entries())

        first, second = self.recover_twice(scenario)
        self.assertEqual([o["to_state"] for o in first], [terminal])
        # Second recovery changes nothing: no outcomes, identical
        # journal heads and entry counts.
        self.assertEqual(second, [])
        heads_after_first = (
            self.journal(scenario).head(),
            self.ledger(scenario).head(),
            len(self.journal(scenario).entries()),
            len(self.ledger(scenario).entries()))
        third = recover_ship_tx(
            self.ledger(scenario), self.loop(scenario),
            root=scenario / "repo")
        self.assertEqual(third, [])
        self.assertEqual(
            heads_after_first,
            (self.journal(scenario).head(),
             self.ledger(scenario).head(),
             len(self.journal(scenario).entries()),
             len(self.ledger(scenario).entries())))
        self.assertGreater(len(self.journal(scenario).entries()),
                           0)
        self.assertGreaterEqual(len(self.journal(scenario).entries()),
                                tx_entries_before)

        # Exactly-once settlement.
        self.assertEqual(self.journal(scenario).state(tx_id),
                         terminal)
        self.assertEqual(len(self.burns(scenario, decision_id)),
                         1 if burn_landed else 0)
        self.assertTrue(self.ledger(scenario).is_consumed(
            decision_id=decision_id,
            proposal_id=info["proposal_id"],
            manifest_hash=info["manifest_hash"]) == burn_landed)
        history = [e for e in self.loop(scenario).state["history"]
                   if e["item_id"] == info["item_id"]]
        self.assertLessEqual(len(history), 1)
        self.assertEqual(len(history), history_len)
        if terminal == COMMITTED:
            fins = self.finalises(scenario, decision_id)
            self.assertEqual(len(fins), 1)
            self.assertEqual(fins[0]["cycle_id"],
                             history[0]["cycle_id"])
            self.assertEqual(self.tx_states(scenario, tx_id),
                             HAPPY_WALK)
        else:
            self.assertEqual(self.finalises(scenario, decision_id),
                             [])
        # Recovery journaled no AUTHORISATION_VERIFIED.
        self.assertEqual(
            self.tx_states(scenario, tx_id).count(
                AUTHORISATION_VERIFIED), auth_before)

        # A settled burn-landed decision can never ship again.
        if burn_landed:
            again = run_runner(scenario)
            self.assertEqual(again.returncode, 3, again.stderr)
            self.assertIn("already_consumed", again.stderr)
            self.assertEqual(
                len(self.burns(scenario, decision_id)), 1)
            self.assertEqual(self.journal(scenario).state(tx_id),
                             terminal)


class AnchoredCrashPointTests(CrashLabFixture):
    """Crash coverage for record_ship's anchor write (fix round
    B, FIX 1): the anchored variant the unanchored lab never
    exercised — record_ship's final step, update_anchor, after
    the COMMITTED journal transition.

    Stale-but-valid prefix behaviour, asserted explicitly:
    recovery (recover_ship_tx with anchor_path) VERIFIES the
    ship-ledger anchor but never ADVANCES it — update_anchor is
    record_ship's step, not recovery's. So for after_commit and
    during_anchor_save, where the kill prevented the anchor
    update, the anchor stays at its pre-ship genesis value
    (seq 0) after recovery: stale, because the ledger has since
    grown to 2 entries, but valid, because verify_anchor
    accepts any anchor naming a prefix of the chain (() — the
    genesis prefix). That is the designed behaviour, not a
    failure: the remedy for a stale anchor is a later
    update_anchor by an operator / the next anchored ship, and
    recovery settling COMMITTED does not depend on the anchor
    being current, only on it not contradicting the chain.
    """

    def test_anchored_crash_points_settle_committed(self):
        for point, (anchor_seq, anchor_current) \
                in ANCHORED_CRASH_TABLE.items():
            with self.subTest(crash_point=point):
                self._run_anchored_point(point, anchor_seq,
                                         anchor_current)

    def _run_anchored_point(self, point, anchor_seq,
                            anchor_current):
        scenario = self.base / f"anchored-{point}"
        proc = run_runner(scenario, crash=point,
                          env={"AION_ANCHORED": "1"})
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info = read_scenario(scenario)
        self.assertTrue(info["anchored"])
        tx_id, decision_id = info["tx_id"], info["decision_id"]
        anchor_path = self.anchor_path(scenario)

        # The kill left a fully committed ship: COMMITTED
        # journaled, one burn, one finalise, one loop cycle.
        self.assertEqual(self.journal(scenario).state(tx_id),
                         COMMITTED)
        self.assertEqual(self.tx_states(scenario, tx_id),
                         HAPPY_WALK)
        self.assertEqual(len(self.burns(scenario, decision_id)), 1)
        fins = self.finalises(scenario, decision_id)
        self.assertEqual(len(fins), 1)
        history = [e for e in self.loop(scenario).state["history"]
                   if e["item_id"] == info["item_id"]]
        self.assertEqual(len(history), 1)
        self.assertEqual(fins[0]["cycle_id"],
                         history[0]["cycle_id"])
        if point == "during_anchor_save":
            # Evidence the kill was DURING the anchor write: the
            # anchor's tmp file was written but never replaced
            # over the anchor (anchoring's tmp naming is
            # ".<name>.tmp-<pid>" alongside the anchor).
            self.assertTrue(list(scenario.glob(
                ".ship-anchor.json.tmp-*")))

        # The anchor the kill left, before any recovery.
        anchor = load_anchor(anchor_path)
        self.assertIsNotNone(anchor)
        self.assertEqual(anchor["seq"], anchor_seq)
        self.assertEqual(anchor["kind"], "ship")
        self.assertEqual(
            verify_anchor(self.ledger(scenario), anchor_path,
                          kind="ship"), ())
        if anchor_current:
            self.assertEqual(anchor["seq"],
                             len(self.ledger(scenario).entries()))
            self.assertEqual(anchor["head"],
                             self.ledger(scenario).head())
        else:
            self.assertEqual(anchor["head"], GENESIS_HASH)
            self.assertLess(anchor["seq"],
                            len(self.ledger(scenario).entries()))

        # Recovery twice, fresh objects, WITH the anchor: the
        # transaction is already terminal, so both runs are
        # no-ops — recovery must never re-finalise, never move
        # the journal or ledger, and (per the class docstring)
        # never advance the anchor.
        heads_before = (self.journal(scenario).head(),
                        self.ledger(scenario).head(),
                        len(self.journal(scenario).entries()),
                        len(self.ledger(scenario).entries()))
        first, second = self.recover_twice(
            scenario, anchor_path=anchor_path)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertEqual(
            heads_before,
            (self.journal(scenario).head(),
             self.ledger(scenario).head(),
             len(self.journal(scenario).entries()),
             len(self.ledger(scenario).entries())))
        self.assertEqual(self.journal(scenario).state(tx_id),
                         COMMITTED)
        self.assertEqual(
            len(self.finalises(scenario, decision_id)), 1)

        # The anchor ends consistent with the ship ledger:
        # verify_anchor passes in both cases. For after_anchor
        # it is current; for the other two it is the explicit
        # stale-but-valid prefix asserted above — recovery did
        # not advance it (same seq/head as before recovery).
        anchor_after = load_anchor(anchor_path)
        self.assertEqual(anchor_after["seq"], anchor_seq)
        self.assertEqual(anchor_after["head"], anchor["head"])
        self.assertEqual(
            verify_anchor(self.ledger(scenario), anchor_path,
                          kind="ship"), ())
        if anchor_current:
            self.assertEqual(anchor_after["head"],
                             self.ledger(scenario).head())
        else:
            # Stale-but-valid, stated plainly: seq 0 / genesis
            # head against a 2-entry ledger still verifies,
            # because the genesis state is a prefix of the chain.
            self.assertEqual(anchor_after["seq"], 0)
            self.assertEqual(anchor_after["head"], GENESIS_HASH)


class ConcurrencyTests(CrashLabFixture):
    def test_two_shippers_same_item_exactly_one_burn(self):
        scenario = self.base / "race-ship"
        barrier = self.base / "barrier-a"
        for variant in ("1", "2"):
            proc = run_runner(scenario, variant=variant,
                              env={"AION_SETUP_ONLY": "1"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
        procs = [
            run_runner(scenario, variant=v, popen=True, env={
                "AION_BARRIER_DIR": str(barrier),
                "AION_BARRIER_COUNT": "2"})
            for v in ("1", "2")]
        codes = []
        for proc in procs:
            _, stderr = proc.communicate(timeout=120)
            codes.append((proc.returncode, stderr))
        self.assertEqual(sorted(c[0] for c in codes), [0, 3],
                         codes)
        infos = [read_scenario(scenario, v) for v in ("1", "2")]
        # Exactly one burn total across both decisions, one cycle
        # for the item, one finalise naming that cycle; both
        # journals load cleanly (construction validates the hash
        # chains) and exactly one transaction committed.
        self.assertEqual(len(self.burns(scenario)), 1)
        history = self.loop(scenario).state["history"]
        self.assertEqual(len(history), 1)
        fins = self.finalises(scenario)
        self.assertEqual(len(fins), 1)
        self.assertEqual(fins[0]["cycle_id"], history[0]["cycle_id"])
        states = {info["tx_id"]: self.journal(scenario)
                  .state(info["tx_id"]) for info in infos}
        self.assertEqual(list(states.values()).count(COMMITTED), 1)
        for state in states.values():
            self.assertIn(state, (COMMITTED, REFUSED_PRE_BURN, None))

    def test_two_recoveries_concurrently_settle_exactly_once(self):
        scenario = self.base / "race-recover"
        proc = run_runner(scenario, crash="after_cycle")
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info = read_scenario(scenario)
        barrier = self.base / "barrier-b"
        procs = [
            run_runner(scenario, popen=True, env={
                "AION_MODE": "recover",
                "AION_BARRIER_DIR": str(barrier),
                "AION_BARRIER_COUNT": "2"})
            for _ in range(2)]
        for proc in procs:
            _, stderr = proc.communicate(timeout=120)
            self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(self.journal(scenario).state(info["tx_id"]),
                         COMMITTED)
        self.assertEqual(self.tx_states(scenario, info["tx_id"]),
                         HAPPY_WALK)
        self.assertEqual(
            [e["kind"] for e in self.ledger(scenario).entries()],
            ["burn", "finalise"])
        self.assertEqual(len(self.loop(scenario).state["history"]), 1)
        # And a further recovery is a no-op.
        self.assertEqual(recover_ship_tx(
            self.ledger(scenario), self.loop(scenario),
            root=scenario / "repo"), [])

    def test_concurrent_burns_of_different_decisions_both_land(self):
        # Ledger-level race, several rounds, processes lined up
        # on a barrier so their saves genuinely collide. Before
        # the trust/ledger.py fix, HashChainJournal._save's
        # freshness check made one legitimate burn fail with
        # CorruptLedgerError ("journal changed on disk since
        # load"); the bounded reload-and-retry in
        # ShipLedger.burn must land both, exactly once each.
        for round_no in range(5):
            with self.subTest(round=round_no):
                home = self.base / f"burn-home-{round_no}"
                barrier = self.base / f"barrier-c{round_no}"
                decisions = [f"d-r{round_no}-a", f"d-r{round_no}-b"]
                procs = [
                    run_runner(home, popen=True, env={
                        "AION_MODE": "burn",
                        "AION_BURN_DECISION_ID": decision,
                        "AION_BARRIER_DIR": str(barrier),
                        "AION_BARRIER_COUNT": "2"})
                    for decision in decisions]
                for proc in procs:
                    _, stderr = proc.communicate(timeout=120)
                    self.assertEqual(proc.returncode, 0, stderr)
                ledger = ShipLedger(home)  # chain validates on load
                burns = [e for e in ledger.entries()
                         if e["kind"] == "burn"]
                self.assertEqual(
                    sorted(e["decision_id"] for e in burns),
                    decisions)

    def test_concurrent_duplicate_burn_still_refused(self):
        # The retry fix must not weaken the duplicate refusal:
        # two processes burning the SAME decision concurrently
        # land exactly one burn; the loser is refused.
        home = self.base / "burn-dup-home"
        barrier = self.base / "barrier-dup"
        procs = [
            run_runner(home, popen=True, env={
                "AION_MODE": "burn",
                "AION_BURN_DECISION_ID": "d-same",
                "AION_BARRIER_DIR": str(barrier),
                "AION_BARRIER_COUNT": "2"})
            for _ in range(2)]
        codes = []
        for proc in procs:
            _, stderr = proc.communicate(timeout=120)
            codes.append(proc.returncode)
        self.assertEqual(sorted(codes), [0, 4])
        burns = [e for e in ShipLedger(home).entries()
                 if e["kind"] == "burn"]
        self.assertEqual(len(burns), 1)
        self.assertEqual(burns[0]["decision_id"], "d-same")

    def test_concurrent_pair_only_burns_exactly_one_lands(self):
        # Pair-only race for the ledger retry fix (fix round B,
        # optional): two processes burn DIFFERENT decision ids
        # claiming the SAME (proposal_id, manifest_hash) pair.
        # The bounded reload-and-retry in ShipLedger.burn must
        # re-validate the pair against the fresh entries on
        # retry, so exactly one burn lands and the loser is
        # refused with LedgerError (runner exit 4) — the retry
        # must not launder the second decision through the pair
        # check it passed against a stale snapshot.
        home = self.base / "burn-pair-home"
        barrier = self.base / "barrier-pair"
        decisions = ["d-pair-a", "d-pair-b"]
        procs = [
            run_runner(home, popen=True, env={
                "AION_MODE": "burn",
                "AION_BURN_DECISION_ID": decision,
                "AION_BURN_PROPOSAL_ID": "p-pair-race",
                "AION_BURN_MANIFEST_HASH": "a" * 64,
                "AION_BARRIER_DIR": str(barrier),
                "AION_BARRIER_COUNT": "2"})
            for decision in decisions]
        codes = []
        for proc in procs:
            _, stderr = proc.communicate(timeout=120)
            codes.append((proc.returncode, stderr))
        self.assertEqual(sorted(c[0] for c in codes), [0, 4],
                         codes)
        burns = [e for e in ShipLedger(home).entries()
                 if e["kind"] == "burn"]
        self.assertEqual(len(burns), 1)
        self.assertIn(burns[0]["decision_id"], decisions)
        self.assertEqual(burns[0]["proposal_id"], "p-pair-race")
        self.assertEqual(burns[0]["manifest_hash"], "a" * 64)


class DuplicateValueAttackTests(CrashLabFixture):
    def test_other_ships_cycle_never_attributed_to_crashed_tx(self):
        # tx1 ships item X and commits cycle 1 in the shared
        # ledgers + main loop.
        scenario = self.base / "dup-attribution"
        proc = run_runner(scenario, variant="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        info1 = read_scenario(scenario, "1")
        self.assertEqual(
            self.journal(scenario).state(info1["tx_id"]), COMMITTED)
        cycle_n = self.loop(scenario).state["history"][0]["cycle_id"]

        # tx2: a FRESH decision for the same item X (different
        # proposal/manifest, so its burn is not a pair replay),
        # presented against a rolled-back loop where the item is
        # pickable again. It crashes after its burn lands.
        proc = run_runner(scenario, variant="2", crash="after_burn",
                          env={"AION_LOOP_SUBDIR": "loop-state-2"})
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info2 = read_scenario(scenario, "2")
        self.assertNotEqual(info1["decision_id"],
                            info2["decision_id"])
        self.assertEqual(info1["item_id"], info2["item_id"])
        self.assertEqual(
            len(self.burns(scenario, info2["decision_id"])), 1)

        # Recovery against the REAL loop (which holds cycle N):
        # cycle N is already claimed by tx1's journal + finalise,
        # so attributing it to tx2 is ambiguous by construction
        # and the designed fail-closed outcome is ANOMALY —
        # never COMMITTED with cycle N.
        first, second = self.recover_twice(scenario)
        self.assertEqual(
            [(o["tx_id"], o["to_state"]) for o in first],
            [(info2["tx_id"], ANOMALY)])
        self.assertEqual(second, [])
        self.assertEqual(
            self.journal(scenario).state(info2["tx_id"]), ANOMALY)
        self.assertEqual(
            self.journal(scenario).state(info1["tx_id"]), COMMITTED)
        fins_n = [e for e in self.finalises(scenario)
                  if e["cycle_id"] == cycle_n]
        self.assertEqual([e["decision_id"] for e in fins_n],
                         [info1["decision_id"]])
        self.assertEqual(
            self.finalises(scenario, info2["decision_id"]), [])

    def test_hand_duplicated_history_parks_anomaly_recovery_logic_unit(self):
        """Recovery-LOGIC unit test (re-labelled, fix round B,
        FIX 3) — NOT a production end-to-end behaviour test.

        Hand-duplicate the loop history entry (same cycle_id +
        item_id twice) in the raw state file, simulating a
        tampered/duplicated loop state. That file no longer
        passes CoreLoop validation, so production recovery
        cannot even load the loop (see the companion test below:
        CorruptStateError, transaction left non-terminal and
        fail-closed). This test therefore drives recovery
        through a StubLoop carrying the raw state, bypassing
        CoreLoop validation on purpose: what it proves is only
        the recovery LOGIC's ambiguity branch — given duplicated
        history evidence, recover_ship_tx parks ANOMALY and
        finalises nothing — not that production ever reaches
        that branch through a real CoreLoop."""
        scenario = self.base / "dup-history"
        proc = run_runner(scenario, crash="after_cycle")
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info = read_scenario(scenario)
        state_path = scenario / "loop-state" / "state.json"
        raw = json.loads(state_path.read_text())
        raw["history"].append(dict(raw["history"][0]))
        state_path.write_text(json.dumps(raw))

        class StubLoop:
            def __init__(self, state):
                self.state = state

        outcomes = recover_ship_tx(
            self.ledger(scenario), StubLoop(raw),
            root=scenario / "repo")
        self.assertEqual([o["to_state"] for o in outcomes],
                         [ANOMALY])
        self.assertEqual(
            self.journal(scenario).state(info["tx_id"]), ANOMALY)
        # Nothing was finalised on the duplicated evidence.
        self.assertEqual(self.finalises(scenario), [])
        self.assertEqual(
            len(self.burns(scenario, info["decision_id"])), 1)

    def test_hand_duplicated_history_production_load_fails_closed(self):
        """Production behaviour for the SAME duplicated state
        file as the recovery-logic unit test above (fix round B,
        FIX 3 companion): a real CoreLoop refuses to load it.

        CoreLoop._validate rejects a history whose cycle_ids are
        not strictly increasing (and, independently, an item
        credited with more than one cycle), raising
        CorruptStateError. Production recovery takes a CoreLoop,
        so it cannot even be constructed over this state:
        recover_ship_tx is never reached, nothing is parked,
        finalised or settled, and the transaction is left
        exactly where the crash left it — BURN_PENDING,
        non-terminal — fail-closed for a human to reconcile,
        rather than ANOMALY-parked by recovery as in the
        StubLoop unit test."""
        scenario = self.base / "dup-history-prod"
        proc = run_runner(scenario, crash="after_cycle")
        self.assertEqual(proc.returncode, 99, proc.stderr)
        info = read_scenario(scenario)
        state_path = scenario / "loop-state" / "state.json"
        raw = json.loads(state_path.read_text())
        raw["history"].append(dict(raw["history"][0]))
        state_path.write_text(json.dumps(raw))

        with self.assertRaises(CorruptStateError):
            self.loop(scenario)
        # The failed load changed nothing durable: the tx is
        # still non-terminal at its post-crash state, the burn
        # stands, and no finalise was fabricated.
        self.assertEqual(self.journal(scenario).state(info["tx_id"]),
                         BURN_PENDING)
        self.assertNotIn(self.journal(scenario).state(info["tx_id"]),
                         (COMMITTED, ANOMALY, ABORTED_SPENT,
                          REFUSED_PRE_BURN))
        self.assertEqual(self.finalises(scenario), [])
        self.assertEqual(
            len(self.burns(scenario, info["decision_id"])), 1)

    def test_identical_value_payloads_two_items_both_commit(self):
        scenario = self.base / "dup-values"
        infos = {}
        for variant, item, proposal in (
                ("a1", "item-alpha", "prop-alpha"),
                ("b1", "item-beta", "prop-beta")):
            proc = run_runner(
                scenario, variant=variant,
                env={"AION_ITEM_ID": item,
                     "AION_PROPOSAL_ID": proposal})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            infos[item] = read_scenario(scenario, variant)
        history = self.loop(scenario).state["history"]
        self.assertEqual(
            [(e["cycle_id"], e["item_id"]) for e in history],
            [(1, "item-alpha"), (2, "item-beta")])
        # Byte-identical value payloads: same coders, reviewers,
        # verdict and delta (metric/before/after) on both cycles.
        self.assertEqual(history[0]["coders"], history[1]["coders"])
        self.assertEqual(history[0]["reviewers"],
                         history[1]["reviewers"])
        deltas = self.loop(scenario).state["deltas"]
        self.assertEqual(
            [(d["metric"], d["before"], d["after"])
             for d in deltas],
            [("tests_passing", 1, 2)] * 2)
        # No cross-attribution: each transaction committed with
        # its OWN cycle id, and each finalise names its own.
        for item, cycle_id in (("item-alpha", 1), ("item-beta", 2)):
            info = infos[item]
            self.assertEqual(
                self.journal(scenario).state(info["tx_id"]),
                COMMITTED)
            fins = self.finalises(scenario, info["decision_id"])
            self.assertEqual(len(fins), 1)
            self.assertEqual(fins[0]["cycle_id"], cycle_id)


if __name__ == "__main__":
    unittest.main()
