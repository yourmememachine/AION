"""Integration tests for the coordinator wiring of Trust
Boundary v2: query budgets and ledger anchoring enforced inside
the REAL verifier process (trust/verifier_main.py), and the
ship-ledger anchor surface on record_ship.

The unit semantics live in tests/test_trust_budgets.py and
tests/test_trust_anchoring.py; these tests prove the wiring —
env parsing, startup refusal, budget refusal before evaluation,
anchor advance after signatures — end to end.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.client import VerifierClient
from trust.errors import ShipRefused, VerifierConfigError
from trust.ledger import ShipLedger

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]


class WiringFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.base = base
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
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
        }

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, **env_over):
        return VerifierClient(
            verifier_env=dict(self.env, **env_over),
            expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)


class BudgetWiringTests(WiringFixture):
    def test_proposal_budget_enforced_inside_verifier(self):
        client = self.client(AION_VERIFIER_PROPOSAL_BUDGET="2")
        client.sealed_eval(RIGHT, proposal_id="prop-budget")
        client.sealed_eval(["4", "9", "wrong"], proposal_id="prop-budget")
        with self.assertRaises(VerifierConfigError) as ctx:
            client.sealed_eval(["4", "wrong", "3.14"],
                               proposal_id="prop-budget")
        self.assertIn("query_budget_exceeded", str(ctx.exception))
        # A different proposal still has its own budget. The
        # transcript must be a fresh one: replay detection is
        # identity-scoped across proposals, so re-submitting
        # RIGHT under a new label would be a replay, not a new
        # proposal's first query. This transcript differs from
        # every recorded prior at all three positions, so it is
        # neither a replay nor a near-duplicate probe.
        client.sealed_eval(["nope", "nope", "nope"],
                           proposal_id="prop-other")

    def test_replay_refused_inside_verifier(self):
        client = self.client()
        client.sealed_eval(RIGHT, proposal_id="prop-replay")
        with self.assertRaises(VerifierConfigError) as ctx:
            client.sealed_eval(RIGHT, proposal_id="prop-replay")
        self.assertIn("query_budget_exceeded", str(ctx.exception))


class AnchorWiringTests(WiringFixture):
    def setUp(self):
        super().setUp()
        self.anchor = self.base / "anchors" / "signing.anchor"
        self.anchor.parent.mkdir()

    def test_anchor_bootstrap_then_startup_refusals(self):
        # No anchor, no bootstrap permission: refuse to sign.
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(AION_ANCHOR_PATH=str(self.anchor)).sealed_eval(
                RIGHT)
        self.assertIn("anchor_refused", str(ctx.exception))
        # Bootstrap invocation creates the anchor and signs.
        self.client(AION_ANCHOR_PATH=str(self.anchor),
                    AION_ANCHOR_INIT="1").sealed_eval(RIGHT)
        self.assertTrue(self.anchor.exists())
        # Normal invocation now works and advances the anchor.
        self.client(AION_ANCHOR_PATH=str(self.anchor)).sealed_eval(
            ["4", "9", "wrong"])
        # Deleting the anchor of an established ledger refuses.
        self.anchor.unlink()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(AION_ANCHOR_PATH=str(self.anchor)).sealed_eval(
                ["4", "wrong", "3.14"])
        self.assertIn("anchor_missing_established_ledger",
                      str(ctx.exception))

    def test_ledger_rollback_detected_at_startup(self):
        client = self.client(AION_ANCHOR_PATH=str(self.anchor),
                             AION_ANCHOR_INIT="1")
        client.sealed_eval(RIGHT)
        ledger_file = self.home / "ledger" / "signing-ledger.json"
        snapshot = ledger_file.read_bytes()
        client.sealed_eval(["4", "9", "wrong"])
        ledger_file.write_bytes(snapshot)  # roll the ledger back
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(AION_ANCHOR_PATH=str(self.anchor)).sealed_eval(
                ["4", "wrong", "3.14"])
        self.assertIn("anchor_refused", str(ctx.exception))


class BudgetsAnchorWiringTests(WiringFixture):
    """The budget store's hash-chain head is anchored outside the
    verifier home (AION_BUDGETS_ANCHOR_PATH), mirroring the signing
    ledger: deleting or rolling back budgets.json — which would
    silently reset every query budget — refuses startup."""

    def setUp(self):
        super().setUp()
        self.banchor = self.base / "anchors" / "budgets.anchor"
        self.banchor.parent.mkdir(exist_ok=True)
        self.budgets_file = self.home / "ledger" / "budgets.json"

    def test_bootstrap_advance_and_deletion_refusal(self):
        env = dict(AION_BUDGETS_ANCHOR_PATH=str(self.banchor))
        self.client(AION_BUDGETS_ANCHOR_INIT="1",
                    **env).sealed_eval(RIGHT)
        self.assertTrue(self.banchor.exists())
        first_anchor = self.banchor.read_bytes()
        # A normal invocation works and advances the anchor.
        self.client(**env).sealed_eval(["4", "9", "wrong"])
        self.assertNotEqual(self.banchor.read_bytes(), first_anchor)
        # Deleting budgets.json (a budget reset) refuses startup.
        self.budgets_file.unlink()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(**env).sealed_eval(["4", "wrong", "3.14"])
        self.assertIn("anchor_refused", str(ctx.exception))

    def test_rollback_refusal(self):
        env = dict(AION_BUDGETS_ANCHOR_PATH=str(self.banchor))
        client = self.client(AION_BUDGETS_ANCHOR_INIT="1", **env)
        client.sealed_eval(RIGHT)
        snapshot = self.budgets_file.read_bytes()
        client.sealed_eval(["4", "9", "wrong"])
        self.budgets_file.write_bytes(snapshot)  # roll budgets back
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(**env).sealed_eval(["4", "wrong", "3.14"])
        self.assertIn("anchor_refused", str(ctx.exception))

    def test_established_store_without_anchor_or_init_refuses(self):
        self.client().sealed_eval(RIGHT)  # establishes budgets.json
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(
                AION_BUDGETS_ANCHOR_PATH=str(self.banchor)
            ).sealed_eval(["4", "9", "wrong"])
        self.assertIn("anchor_missing_established_budgets",
                      str(ctx.exception))

    def test_combined_deletion_of_store_and_anchor_refuses(self):
        # Deleting budgets.json TOGETHER with its anchor must not
        # silently reset the budgets: a configured-but-missing
        # anchor refuses startup without the INIT ceremony, exactly
        # like the signing-ledger anchor.
        env = dict(AION_BUDGETS_ANCHOR_PATH=str(self.banchor))
        self.client(AION_BUDGETS_ANCHOR_INIT="1",
                    **env).sealed_eval(RIGHT)
        self.budgets_file.unlink()
        self.banchor.unlink()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(**env).sealed_eval(["4", "9", "wrong"])
        self.assertIn("anchor_refused", str(ctx.exception))

    def test_corrupt_budget_store_is_a_clean_refusal(self):
        self.client().sealed_eval(RIGHT)  # establishes budgets.json
        raw = self.budgets_file.read_text(encoding="utf-8")
        self.budgets_file.write_text(raw.replace('"chain_hash"',
                                                 '"chain_hashX"', 1),
                                     encoding="utf-8")
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client().sealed_eval(["4", "9", "wrong"])
        self.assertIn("budget_store_corrupt", str(ctx.exception))
        self.assertNotIn("unhandled", str(ctx.exception))

    def test_adaptive_trip_persists_the_latch(self):
        # Through the two-phase wiring, the tripping (3rd) probe is
        # persisted via record(), so the family latch materialises
        # on disk rather than existing only as a recomputed refusal.
        from trust.budgets import BudgetStore
        client = self.client()
        client.sealed_eval(RIGHT, proposal_id="prop-latch")
        client.sealed_eval(["4", "9", "wrong"], proposal_id="p2")
        client.sealed_eval(["4", "wrong", "3.14"], proposal_id="p3")
        with self.assertRaises(VerifierConfigError) as ctx:
            client.sealed_eval(["wrong", "9", "3.14"],
                               proposal_id="p4")
        self.assertIn("adaptive_query_detected", str(ctx.exception))
        store = BudgetStore(self.budgets_file)
        self.assertTrue(store.is_blocked(ACTOR))
        self.assertGreaterEqual(store.blocked_family_count(ACTOR), 1)

    def test_garbage_transcript_burns_no_budget(self):
        # Proposal budget of 1: a wrong-length transcript is refused
        # as malformed BEFORE any budget is recorded, so the one
        # real query still fits afterwards.
        client = self.client(AION_VERIFIER_PROPOSAL_BUDGET="1")
        from trust.errors import VerifierProtocolError
        with self.assertRaises(VerifierProtocolError):
            client.sealed_eval(["4", "9"], proposal_id="prop-garbage")
        client.sealed_eval(RIGHT, proposal_id="prop-garbage")


class ShipAnchorSurfaceTests(unittest.TestCase):
    def test_anchor_inside_ledger_dir_refuses_pre_burn(self):
        from trust.shipcheck import record_ship
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ShipLedger(Path(tmp) / "ship")
            with self.assertRaises(ShipRefused):
                record_ship(
                    None, root=tmp, manifest=None, signed=None,
                    signing_key=None, ledger=ledger, coders=[],
                    reviewers=[], delta=None, release=object(),
                    expected_ledger_head="0" * 64,
                    anchor_path=str(Path(tmp) / "ship" / "a.anchor"))


if __name__ == "__main__":
    unittest.main()
