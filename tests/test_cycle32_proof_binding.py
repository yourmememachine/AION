"""Cycle 32-PROOF binding round — hash-chained proof bindings
with a fail-closed pre-burn gate.

Before this round the proof binding was a plain JSON line
appended to proof-bindings.jsonl AFTER the ship committed:
an author in the journal's trust domain could rewrite any
line undetectably, and an append failure left a shipped,
finalised cycle with no binding at all (the old
test_proof_binding_failure_ship_stands pinned that).

This round pins:
- every binding record is hash-chained (prev_binding_hash,
  binding_hash self-hash; genesis prev is 64 zeroes);
- verify_proof_bindings detects an edited or malformed
  record;
- record_ship_with_proof verifies the existing chain and
  preflights appendability BEFORE delegating, so a corrupt
  or unwritable bindings file refuses the ship before any
  burn — the delegate is never called.

Honest limit (not pinned as caught): deleting the TAIL of
the chain is indistinguishable from a shorter history to
this check alone; that needs the non-author anchor, which
remains a separate follow-up.
"""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trust.proofcarry as pc
import trust.shipcheck
from signing.gate_decision import _canonical, _sha256
from trust.errors import ShipRefused
from trust.proofcarry import build_proof_artefact, record_ship_with_proof

from tests.test_trust_proofcarry import (  # noqa: E402
    SCOPE,
    invariant,
    make_tree,
)

GENESIS = "0" * 64


class BindingChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name) / "base"
        post = Path(self.tmp.name) / "post"
        self.base = make_tree(base, "VALUE = 'bad'\n")
        self.post = make_tree(post, "VALUE = 'good'\n")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **over):
        kw = dict(change_id="change-1", base_root=self.base,
                  post_root=self.post, scope_paths=SCOPE,
                  invariants=[invariant()],
                  created_at="2026-11-26T00:00:00+00:00")
        kw.update(over)
        return build_proof_artefact(**kw)

    def _fake_ship(self, delegate=None):
        journal = Path(self.tmp.name) / "journal"
        journal.mkdir(parents=True, exist_ok=True)
        manifest = types.SimpleNamespace(manifest_hash="f" * 64)
        ledger = types.SimpleNamespace(journal_dir=journal)
        captured = {}
        if delegate is None:
            def delegate(loop, *, root, **kw):
                captured["root"] = Path(root)
                return {"cycle_id": 7, "item_id": "item-9"}
        return manifest, ledger, captured, delegate

    def _call(self, artefact, delegate, manifest, ledger):
        with mock.patch.object(trust.shipcheck, "record_ship",
                               delegate):
            return record_ship_with_proof(
                object(), base_root=self.base, post_root=self.post,
                artefact=artefact, manifest=manifest, ledger=ledger,
                signed=object(), signing_key=object(), coders=(),
                reviewers=(), delta={})

    def _bindings(self, ledger):
        path = ledger.journal_dir / "proof-bindings.jsonl"
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines()]

    def test_verify_missing_or_empty_bindings_ok(self):
        journal = Path(self.tmp.name) / "empty-journal"
        journal.mkdir()
        self.assertEqual(pc.verify_proof_bindings(journal), ())
        (journal / "proof-bindings.jsonl").write_text("")
        self.assertEqual(pc.verify_proof_bindings(journal), ())

    def test_first_binding_is_genesis_chained_and_self_hashed(self):
        artefact = self.build()
        manifest, ledger, _captured, delegate = self._fake_ship()
        self._call(artefact, delegate, manifest, ledger)
        (record,) = self._bindings(ledger)
        self.assertEqual(record["prev_binding_hash"], GENESIS)
        core = {k: v for k, v in record.items()
                if k != "binding_hash"}
        self.assertEqual(record["binding_hash"],
                         _sha256(_canonical(core)))
        self.assertEqual(
            pc.verify_proof_bindings(ledger.journal_dir), ())

    def test_second_binding_chains_to_first(self):
        artefact = self.build()
        manifest, ledger, _c, delegate = self._fake_ship()
        self._call(artefact, delegate, manifest, ledger)

        def delegate_next(loop, *, root, **kw):
            return {"cycle_id": 8, "item_id": "item-9"}

        self._call(artefact, delegate_next, manifest, ledger)
        first, second = self._bindings(ledger)
        self.assertEqual(second["prev_binding_hash"],
                         first["binding_hash"])
        self.assertEqual(
            pc.verify_proof_bindings(ledger.journal_dir), ())

    def test_edited_record_breaks_verification(self):
        artefact = self.build()
        manifest, ledger, _c, delegate = self._fake_ship()
        self._call(artefact, delegate, manifest, ledger)
        path = ledger.journal_dir / "proof-bindings.jsonl"
        record = json.loads(path.read_text().splitlines()[0])
        record["artefact_hash"] = "a" * 64
        path.write_text(json.dumps(record, sort_keys=True) + "\n")
        self.assertTrue(pc.verify_proof_bindings(
            ledger.journal_dir))

    def test_corrupt_chain_refuses_before_delegation(self):
        artefact = self.build()
        manifest, ledger, _c, delegate = self._fake_ship()
        self._call(artefact, delegate, manifest, ledger)
        path = ledger.journal_dir / "proof-bindings.jsonl"
        path.write_text("not json\n")
        captured2 = {}

        def delegate2(loop, *, root, **kw):
            captured2["root"] = Path(root)
            return {"cycle_id": 8, "item_id": "item-9"}

        with self.assertRaises(ShipRefused) as ctx:
            self._call(artefact, delegate2, manifest, ledger)
        self.assertNotIn("root", captured2)
        self.assertIn("proof_binding", str(ctx.exception))

    def test_unwritable_bindings_refuse_before_delegation(self):
        artefact = self.build()
        manifest, ledger, captured, delegate = self._fake_ship()
        # A directory where the bindings file must be makes
        # any append fail — preflight must refuse pre-burn.
        (ledger.journal_dir / "proof-bindings.jsonl").mkdir()
        with self.assertRaises(ShipRefused) as ctx:
            self._call(artefact, delegate, manifest, ledger)
        self.assertNotIn("root", captured)
        self.assertIn("proof_binding", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
