"""Tests for the budgets-anchor INIT guard (Trust Boundary v3,
item 3, workstream B).

The budgets anchor bootstrap (AION_BUDGETS_ANCHOR_INIT=1)
previously pinned the budget store's CURRENT head even for a
non-genesis store, so deleting the anchor and re-running INIT
could launder a rolled-back budget store into a fresh pin. The
guard mirrors trust/anchoring.py initialise_anchor's
established-ledger guard: INIT may pin only the GENESIS head
(empty store); a non-genesis head under INIT-with-missing-anchor
is a refusal (anchor_refused), and recovery of a non-genesis
store goes through an audited path only.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.registry import EvalRegistry
from signing import generate_key_file
from trust.client import VerifierClient
from trust.errors import VerifierConfigError

ACTOR = "verifier-actor"
SIGNER = "verifier-svc"
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
RIGHT = [e for *_x, e in ITEMS]


class BudgetsAnchorGuardFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        base.chmod(0o700)
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
        self.banchor = base / "anchors" / "budgets.anchor"
        self.banchor.parent.mkdir(exist_ok=True)
        self.budgets_file = self.home / "ledger" / "budgets.json"

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, **env_over):
        env = dict(self.env)
        env.update(env_over)
        return VerifierClient(verifier_env=env,
                              expected_signer_id=SIGNER,
                              expected_key_id=self.key.key_id)

    def anchored_env(self):
        return dict(AION_BUDGETS_ANCHOR_PATH=str(self.banchor))


class BudgetsAnchorGuardTests(BudgetsAnchorGuardFixture):

    def test_non_genesis_store_deleted_anchor_init_refuses(self):
        # Establish a non-genesis budget store WITH an anchor,
        # then delete the anchor and re-run INIT: the old code
        # would re-pin the current head; the guard must refuse
        # startup (exit 3 / VerifierConfigError, anchor_refused).
        env = self.anchored_env()
        self.client(AION_BUDGETS_ANCHOR_INIT="1",
                    **env).sealed_eval(RIGHT)
        self.assertTrue(self.budgets_file.exists())
        self.assertTrue(self.banchor.exists())
        self.banchor.unlink()
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(AION_BUDGETS_ANCHOR_INIT="1",
                        **env).sealed_eval(["4", "9", "wrong"])
        self.assertIn("anchor_refused", str(ctx.exception))
        # And no new anchor was written by the refused bootstrap.
        self.assertFalse(self.banchor.exists())

    def test_non_genesis_store_never_anchored_init_refuses(self):
        # Same laundering shape without any prior anchor: an
        # established store, an anchor path that never existed,
        # and INIT=1 must still refuse — INIT is genesis-only.
        self.client().sealed_eval(RIGHT)
        self.assertTrue(self.budgets_file.exists())
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client(AION_BUDGETS_ANCHOR_INIT="1",
                        **self.anchored_env()).sealed_eval(
                            ["4", "9", "wrong"])
        self.assertIn("anchor_refused", str(ctx.exception))

    def test_genesis_store_init_bootstrap_works(self):
        env = self.anchored_env()
        record = self.client(AION_BUDGETS_ANCHOR_INIT="1",
                             **env).sealed_eval(RIGHT)
        self.assertEqual(record["payload"]["score"], 1.0)
        self.assertTrue(self.banchor.exists())

    def test_non_genesis_anchor_present_and_matching_starts(self):
        env = self.anchored_env()
        self.client(AION_BUDGETS_ANCHOR_INIT="1",
                    **env).sealed_eval(RIGHT)
        # Normal startup: anchor present, head matches the store.
        record = self.client(**env).sealed_eval(["4", "9", "wrong"])
        self.assertEqual(record["payload"]["score"], 2 / 3)


if __name__ == "__main__":
    unittest.main()
