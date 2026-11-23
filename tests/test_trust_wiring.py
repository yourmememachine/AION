"""Tests for the production signed-path wiring
(trust/wiring.py) — Item B, recorded as STATE CYCLE 13.
(Item A, the gate adoption, was built in the same combined
run but is NOT being recorded — split war room, escalated.)

Pod E (seats 12/13/14) coverage:

* production_client's refusal battery — one test per refusal
  class, each asserting VerifierConfigError AND that the error
  message names the variable (wiring.py's contract: errors name
  the variable, never its value). The fix round adds the FB6
  classes: anchor equal to the key path, anchor equal to or
  inside the registry dir, anchor that is an existing
  directory, relative home / key path / registry dir, and
  whitespace-only required values. The allowlist test also
  parses ALLOWED_KEYS out of the shipped wrapper script at
  test time and asserts set equality with ALLOWED_ENV_KEYS.
* No-value-leak probes: a distinctive sentinel placed in env
  VALUES must not surface in refusals about other variables,
  and the signer-pin-mismatch refusal must carry neither the
  env's signer value nor the presented pin.
* Happy path: a well-formed production env returns a
  VerifierClient holding a COPY of the env, with its
  deployment-mode expectation pinned to "production".
* open_production_store: genesis refusal with constructor
  side-effect absence (tree snapshots before/after), unsigned
  refusal, signed_only success, tampered persisted mode, the
  fix-round swap regression (a file swapped to unsigned
  between inspection and construction is refused via the
  byte-binding, no handle handed out, and — for that VALID
  unsigned swap — nothing is saved or ratcheted over the
  swapped bytes; a CORRUPT swap is a different case, see the
  scope note on that test), and the rev-r2 straddle-ABA
  regression (a swap loaded by construction and restored
  before the byte re-read is refused via the state-binding),
  with a pass-through-subclass positive control.
* commit_production: strong form only — missing attestation
  refused, non-signed_only store refused, happy path with a
  real signed attestation, stale-digest refusal, the
  no-`now`-parameter signature pin, and the fix-round signer
  pin: expected_signer_id is mandatory (omission is a
  TypeError) and a wrong pin refuses with signer_mismatch,
  committing nothing.
* LiveProductionWiringTests: the live deployment, guarded
  exactly like tests/test_trust_production_deploy.py's live
  class (skipUnless provisioned). NOT provisioned on this VM
  at write time, so the class skips; it is written to run
  standalone at cycle close after re-provisioning:
      python3 -m unittest \
          tests.test_trust_wiring.LiveProductionWiringTests

Ground truth used (Pod C, shipped code over design note): the
wrapper allowlist has 19 names (cycle 19 added
AION_CEREMONY_OPERATORS; cycle 20 added
AION_CEREMONY_EVIDENCE_DIR and AION_CEREMONY_SIGNING_SEED_PATH;
cycle 22 added AION_CEREMONY_CONSUMPTION_ANCHOR_PATH and
AION_CEREMONY_CONSUMPTION_ANCHOR_INIT)
— AION_SHIP_ANCHOR_PATH is not among
them and refuses as unknown.
INIT flags refuse for any value other than "" or "0".
"""

import inspect
import json
import os
import pwd
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.gate import VerifierAttestation
from memory.store import MemoryError, MemoryStore, decide_write
from signing import (
    SigningError,
    load_signing_key,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
from trust import wiring
from trust.client import VerifierClient
from trust.errors import VerifierConfigError
from trust.wiring import (
    ALLOWED_ENV_KEYS,
    commit_production,
    open_production_store,
    production_client,
)

KEY = make_signing_key(bytes(range(32, 64)))
KEY_ID = "key-0123456789abcdef"
SIGNER_ID = "verifier-main"
SEALED = "b" * 64

BUILDERS = ["seat-9", "seat-10", "seat-11"]
REVIEWERS = ["seat-1", "seat-2", "seat-3", "seat-4", "seat-5",
             "seat-6"]


def production_env(base, **over):
    """A well-formed production env over a temp layout shaped
    like the deployment's: verifier home, anchors, key path and
    registry in separate directories, anchors outside the home."""
    env = {
        "AION_VERIFIER_KEY_PATH": str(base / "keys" / "gate.key"),
        "AION_VERIFIER_SIGNER_ID": SIGNER_ID,
        "AION_VERIFIER_ACTOR_ID": "verifier-actor",
        "AION_REGISTRY_DIR": str(base / "registry"),
        "AION_VERIFIER_HOME": str(base / "verifier-home"),
        "AION_DEPLOYMENT_MODE": "production",
        "AION_ANCHOR_PATH":
            str(base / "anchors" / "signing.anchor.json"),
        "AION_BUDGETS_ANCHOR_PATH":
            str(base / "anchors" / "budgets.anchor.json"),
        "AION_CEREMONY_CONSUMPTION_ANCHOR_PATH":
            str(base / "anchors"
                / "ceremony-consumption.anchor.json"),
        # The verifier's explicit-off spelling: allowed.
        "AION_ANCHOR_INIT": "0",
    }
    env.update(over)
    return env


# ---------------------------------------------------------------------
# production_client — refusal battery
# ---------------------------------------------------------------------

class ProductionClientRefusalTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def env(self, **over):
        return production_env(self.base, **over)

    def assert_refused(self, env, variable, **pins):
        pins.setdefault("expected_signer_id", SIGNER_ID)
        pins.setdefault("expected_key_id", KEY_ID)
        with self.assertRaises(VerifierConfigError) as ctx:
            production_client(env, **pins)
        message = str(ctx.exception)
        self.assertIn(variable, message)
        return message

    def test_allowlist_is_the_shipped_19_names(self):
        # Pod C ground truth: the shipped wrapper's ALLOWED_KEYS
        # has 19 names (cycle 19 added AION_CEREMONY_OPERATORS
        # as the 15th; cycle 20 added AION_CEREMONY_EVIDENCE_DIR
        # and AION_CEREMONY_SIGNING_SEED_PATH; cycle 22 added
        # AION_CEREMONY_CONSUMPTION_ANCHOR_PATH and
        # AION_CEREMONY_CONSUMPTION_ANCHOR_INIT);
        # AION_SHIP_ANCHOR_PATH is not among them.
        self.assertEqual(len(ALLOWED_ENV_KEYS), 19)
        self.assertIn("AION_CEREMONY_OPERATORS", ALLOWED_ENV_KEYS)
        self.assertIn("AION_CEREMONY_EVIDENCE_DIR", ALLOWED_ENV_KEYS)
        self.assertIn("AION_CEREMONY_SIGNING_SEED_PATH", ALLOWED_ENV_KEYS)
        self.assertIn("AION_CEREMONY_CONSUMPTION_ANCHOR_PATH",
                      ALLOWED_ENV_KEYS)
        self.assertIn("AION_CEREMONY_CONSUMPTION_ANCHOR_INIT",
                      ALLOWED_ENV_KEYS)
        self.assertNotIn("AION_SHIP_ANCHOR_PATH", ALLOWED_ENV_KEYS)

    def test_allowlist_matches_wrapper_script_at_test_time(self):
        # rev-r6's ask: do not trust the copied frozenset alone —
        # parse the ALLOWED_KEYS array out of the shipped
        # wrapper script at test time and assert set equality,
        # so a wrapper-side rename or addition fails here even
        # if the 19-count pin above still passes by accident.
        script = (Path(__file__).resolve().parents[1]
                  / "deploy" / "verifier-identity"
                  / "run-verifier.sh")
        text = script.read_text(encoding="utf-8")
        match = re.search(r"ALLOWED_KEYS=\((.*?)\)", text,
                          re.DOTALL)
        self.assertIsNotNone(match)
        wrapper_keys = set(re.findall(r"AION_[A-Z_]+",
                                      match.group(1)))
        self.assertEqual(wrapper_keys, set(ALLOWED_ENV_KEYS))
        self.assertEqual(len(wrapper_keys), 19)

    def test_unknown_ship_anchor_path_refused(self):
        env = self.env(AION_SHIP_ANCHOR_PATH="/tmp/ship.anchor.json")
        self.assert_refused(env, "AION_SHIP_ANCHOR_PATH")

    def test_unknown_random_key_refused(self):
        env = self.env(ZZZ_TOTALLY_UNKNOWN="anything")
        self.assert_refused(env, "ZZZ_TOTALLY_UNKNOWN")

    def test_missing_core_name_refused(self):
        env = self.env()
        del env["AION_VERIFIER_ACTOR_ID"]
        self.assert_refused(env, "AION_VERIFIER_ACTOR_ID")

    def test_empty_core_name_refused(self):
        env = self.env(AION_REGISTRY_DIR="")
        self.assert_refused(env, "AION_REGISTRY_DIR")

    def test_missing_deployment_mode_refused(self):
        env = self.env()
        del env["AION_DEPLOYMENT_MODE"]
        self.assert_refused(env, "AION_DEPLOYMENT_MODE")

    def test_research_mode_refused(self):
        env = self.env(AION_DEPLOYMENT_MODE="research")
        self.assert_refused(env, "AION_DEPLOYMENT_MODE")

    def test_garbage_mode_refused(self):
        env = self.env(AION_DEPLOYMENT_MODE="prod-ish")
        self.assert_refused(env, "AION_DEPLOYMENT_MODE")

    def test_init_flag_one_refused(self):
        for flag in ("AION_ANCHOR_INIT", "AION_BUDGETS_ANCHOR_INIT",
                     "AION_CEREMONY_CONSUMPTION_ANCHOR_INIT"):
            with self.subTest(flag=flag):
                env = self.env(**{flag: "1"})
                self.assert_refused(env, flag)

    def test_relative_anchor_path_refused(self):
        env = self.env(AION_ANCHOR_PATH="anchors/signing.anchor.json")
        self.assert_refused(env, "AION_ANCHOR_PATH")

    def test_anchors_equal_after_resolution_refused(self):
        # Different spellings, same resolved file: the budgets
        # anchor walks through a (non-existent) subdir and back.
        budgets = str(self.base / "anchors" / "nested" / ".."
                      / "signing.anchor.json")
        env = self.env(AION_BUDGETS_ANCHOR_PATH=budgets)
        self.assert_refused(env, "AION_ANCHOR_PATH")

    def test_consumption_anchor_equal_to_signing_refused(self):
        # Cycle 22: the ceremony consumption anchor must be
        # distinct from the signing (and budgets) anchors.
        env = self.env(
            AION_CEREMONY_CONSUMPTION_ANCHOR_PATH=str(
                self.base / "anchors" / "signing.anchor.json"))
        self.assert_refused(env, "AION_ANCHOR_PATH")

    def test_anchor_inside_verifier_home_refused(self):
        inside = str(self.base / "verifier-home"
                     / "signing.anchor.json")
        env = self.env(AION_ANCHOR_PATH=inside)
        self.assert_refused(env, "AION_ANCHOR_PATH")

    def test_anchor_equal_to_verifier_home_refused(self):
        env = self.env(
            AION_ANCHOR_PATH=str(self.base / "verifier-home"))
        self.assert_refused(env, "AION_ANCHOR_PATH")

    # -- Fix round, FB6 classes --------------------------------

    def test_anchor_equal_to_key_path_refused(self):
        # An anchor that IS the key file is overwritten or
        # rolled back with it. The refusal names the anchor
        # variable (and its text also names the key variable).
        key_path = str(self.base / "keys" / "gate.key")
        for anchor_name in ("AION_ANCHOR_PATH",
                            "AION_BUDGETS_ANCHOR_PATH"):
            with self.subTest(anchor=anchor_name):
                env = self.env(**{anchor_name: key_path})
                message = self.assert_refused(env, anchor_name)
                self.assertIn("AION_VERIFIER_KEY_PATH", message)

    def test_anchor_inside_registry_dir_refused(self):
        registry = self.base / "registry"
        cases = {
            "equal": str(registry),
            "inside": str(registry / "signing.anchor.json"),
        }
        for label, anchor in cases.items():
            with self.subTest(case=label):
                env = self.env(AION_ANCHOR_PATH=anchor)
                message = self.assert_refused(
                    env, "AION_ANCHOR_PATH")
                self.assertIn("AION_REGISTRY_DIR", message)

    def test_anchor_that_is_existing_directory_refused(self):
        # A real directory outside home, registry and key path:
        # an anchor must name a file, not a directory.
        anchor_dir = self.base / "anchors" / "dir-anchor"
        anchor_dir.mkdir(parents=True)
        env = self.env(AION_ANCHOR_PATH=str(anchor_dir))
        self.assert_refused(env, "AION_ANCHOR_PATH")

    def test_relative_verifier_home_refused(self):
        env = self.env(AION_VERIFIER_HOME="relative/verifier-home")
        self.assert_refused(env, "AION_VERIFIER_HOME")

    def test_relative_key_path_refused(self):
        env = self.env(AION_VERIFIER_KEY_PATH="keys/gate.key")
        self.assert_refused(env, "AION_VERIFIER_KEY_PATH")

    def test_relative_registry_dir_refused(self):
        env = self.env(AION_REGISTRY_DIR="relative/registry")
        self.assert_refused(env, "AION_REGISTRY_DIR")

    def test_whitespace_only_required_value_refused(self):
        # A whitespace-only value is not "non-empty": the
        # required check strips, so " " refuses and names the
        # variable, exactly like the empty string.
        env = self.env(AION_VERIFIER_ACTOR_ID=" ")
        self.assert_refused(env, "AION_VERIFIER_ACTOR_ID")

    def test_signer_pin_mismatch_refused(self):
        self.assert_refused(self.env(), "AION_VERIFIER_SIGNER_ID",
                            expected_signer_id="someone-else")

    def test_signer_pin_missing_refused(self):
        for pin in (None, ""):
            with self.subTest(pin=pin):
                self.assert_refused(
                    self.env(), "AION_VERIFIER_SIGNER_ID",
                    expected_signer_id=pin)

    def test_key_pin_malformed_refused(self):
        for bad in ("not-a-key-id", "key-123",
                    "key-0123456789ABCDEF", "key-0123456789abcdef0"):
            with self.subTest(bad=bad):
                self.assert_refused(self.env(), "expected_key_id",
                                    expected_key_id=bad)

    def test_key_pin_missing_refused(self):
        for pin in (None, ""):
            with self.subTest(pin=pin):
                self.assert_refused(self.env(), "expected_key_id",
                                    expected_key_id=pin)

    def test_launch_wrapper_refused(self):
        message = self.assert_refused(
            self.env(), "launch", launch="wrapper")
        self.assertIn("wrapper", message)

    def test_launch_bogus_refused(self):
        self.assert_refused(self.env(), "launch", launch="bogus")


# ---------------------------------------------------------------------
# production_client — no value leak
# ---------------------------------------------------------------------

class ProductionClientNoLeakTests(unittest.TestCase):
    """wiring.py's contract: every error names the variable and
    never carries its value. The probes pin exactly that — a
    sentinel living in env VALUES must not appear in refusals,
    including refusals about a different variable, and the
    signer-pin-mismatch refusal must carry neither side's value."""

    SENTINEL = "sentinel-value-9f27c1-must-not-leak"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_refusal_about_other_variable_leaks_no_env_value(self):
        env = production_env(
            self.base,
            # The sentinel lives in two VALUES: the key path and
            # an optional allowlisted variable.
            AION_VERIFIER_KEY_PATH=str(
                self.base / "keys" / f"{self.SENTINEL}-gate.key"),
            AION_VERIFIER_PURPOSE=self.SENTINEL,
            # The refusal is about THIS variable, not either of
            # the sentinel carriers.
            AION_DEPLOYMENT_MODE="research")
        with self.assertRaises(VerifierConfigError) as ctx:
            production_client(env, expected_signer_id=SIGNER_ID,
                              expected_key_id=KEY_ID)
        message = str(ctx.exception)
        self.assertIn("AION_DEPLOYMENT_MODE", message)
        self.assertNotIn(self.SENTINEL, message)

    def test_unknown_key_refusal_leaks_no_other_value(self):
        env = production_env(
            self.base,
            AION_VERIFIER_KEY_PATH=str(
                self.base / "keys" / f"{self.SENTINEL}-gate.key"),
            AION_SHIP_ANCHOR_PATH="/tmp/ship.anchor.json")
        with self.assertRaises(VerifierConfigError) as ctx:
            production_client(env, expected_signer_id=SIGNER_ID,
                              expected_key_id=KEY_ID)
        message = str(ctx.exception)
        self.assertIn("AION_SHIP_ANCHOR_PATH", message)
        self.assertNotIn(self.SENTINEL, message)

    def test_signer_pin_mismatch_leaks_neither_value(self):
        env_signer = f"env-signer-{self.SENTINEL}"
        presented_pin = f"pin-{self.SENTINEL}-other"
        env = production_env(self.base,
                             AION_VERIFIER_SIGNER_ID=env_signer)
        with self.assertRaises(VerifierConfigError) as ctx:
            production_client(env, expected_signer_id=presented_pin,
                              expected_key_id=KEY_ID)
        message = str(ctx.exception)
        self.assertIn("AION_VERIFIER_SIGNER_ID", message)
        self.assertNotIn(env_signer, message)
        self.assertNotIn(presented_pin, message)
        self.assertNotIn(self.SENTINEL, message)


# ---------------------------------------------------------------------
# production_client — happy path
# ---------------------------------------------------------------------

class ProductionClientHappyPathTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_well_formed_env_returns_production_pinned_client(self):
        env = production_env(self.base)
        client = production_client(
            env, expected_signer_id=SIGNER_ID,
            expected_key_id=KEY_ID)
        self.assertIsInstance(client, VerifierClient)
        # VerifierClient exposes no public accessors for its
        # pins/env; the test reads the private fields the
        # constructor sets, which is the only observable surface.
        self.assertEqual(client._expected_deployment_mode,
                         "production")
        self.assertEqual(client._expected_signer_id, SIGNER_ID)
        self.assertEqual(client._expected_key_id, KEY_ID)
        self.assertEqual(client._verifier_env, env)

    def test_client_env_is_a_copy(self):
        env = production_env(self.base)
        snapshot = dict(env)
        client = production_client(
            env, expected_signer_id=SIGNER_ID,
            expected_key_id=KEY_ID)
        # Mutating the caller's dict afterwards — downgrade,
        # addition, deletion — must not reach the client.
        env["AION_DEPLOYMENT_MODE"] = "research"
        env["AION_SHIP_ANCHOR_PATH"] = "/tmp/evil"
        del env["AION_ANCHOR_PATH"]
        self.assertIsNot(client._verifier_env, env)
        self.assertEqual(client._verifier_env, snapshot)
        self.assertEqual(
            client._verifier_env["AION_DEPLOYMENT_MODE"],
            "production")

    def test_init_flags_absent_or_empty_also_accepted(self):
        env = production_env(self.base)
        del env["AION_ANCHOR_INIT"]
        env["AION_BUDGETS_ANCHOR_INIT"] = ""
        client = production_client(
            env, expected_signer_id=SIGNER_ID,
            expected_key_id=KEY_ID)
        self.assertIsInstance(client, VerifierClient)


# ---------------------------------------------------------------------
# open_production_store
# ---------------------------------------------------------------------

def _snapshot_tree(root):
    """Map of relative path -> file bytes (None for directories)
    for everything under root; None if root itself is absent."""
    root = Path(root)
    if not root.exists():
        return None
    out = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        out[rel] = path.read_bytes() if path.is_file() else None
    return out


class OpenProductionStoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def _persist(self, name, *, signed_only):
        directory = self.base / name
        store = MemoryStore(directory, signed_only=signed_only)
        store.save()
        return directory

    def test_missing_directory_refused_and_not_created(self):
        target = self.base / "no-such-store"
        self.assertIsNone(_snapshot_tree(target))
        with self.assertRaises(MemoryError):
            open_production_store(target)
        # Refused inspection has no constructor side effects:
        # the directory was not created and nothing appeared.
        self.assertIsNone(_snapshot_tree(target))
        self.assertFalse(target.exists())

    def test_missing_memory_file_refused_and_no_files_appear(self):
        target = self.base / "empty-store"
        target.mkdir()
        before = _snapshot_tree(target)
        with self.assertRaises(MemoryError):
            open_production_store(target)
        self.assertEqual(_snapshot_tree(target), before)
        self.assertEqual(list(target.iterdir()), [])

    def test_unsigned_store_refused_without_mutation(self):
        directory = self._persist("unsigned-store",
                                  signed_only=False)
        before = _snapshot_tree(directory)
        with self.assertRaises(MemoryError):
            open_production_store(directory)
        # The read-only inspection must not ratchet or rewrite.
        self.assertEqual(_snapshot_tree(directory), before)

    def test_signed_only_store_opens(self):
        directory = self._persist("signed-store", signed_only=True)
        store = open_production_store(directory)
        self.assertIs(store.signed_only, True)
        self.assertEqual(store.security_mode, "signed_only")

    def test_tampered_persisted_mode_refused(self):
        # Flip the persisted mode field by hand, leaving the
        # recorded digest stale. Following the shipped code:
        # _persisted_security_mode parses WITHOUT verifying the
        # digest, so the refusal pinned here is the persisted-
        # mode check ("not signed_only"), not a digest refusal.
        directory = self._persist("tampered-store",
                                  signed_only=True)
        memory_file = directory / "memory.json"
        doc = json.loads(memory_file.read_text(encoding="utf-8"))
        doc["security_mode"] = "unsigned"
        memory_file.write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(MemoryError) as ctx:
            open_production_store(directory)
        self.assertIn("signed_only", str(ctx.exception))

    def test_swapped_file_between_inspection_and_construction_refused(self):
        # rev-r2's technique, against the landed byte-binding:
        # patch the module's inspection helper so that AFTER it
        # has inspected the signed_only file (capturing the
        # inspected bytes' digest for the return value), the
        # file on disk is replaced by a valid UNSIGNED store
        # file. open_production_store must refuse and must not
        # return a handle; and, for this VALID unsigned swap, no
        # save/ratchet may be persisted over the swap — the file
        # on disk afterwards is exactly the unsigned bytes the
        # swap wrote. Scope note (rev-r2 P5): "no save" here is
        # scoped to this valid swap only. A CORRUPT swap is
        # quarantined by the store's constructor — it writes a
        # memory.corrupt-<stamp>.json copy — before wiring's
        # byte/state checks ever run, so this test does not
        # claim a corrupt swap leaves the directory untouched;
        # it claims only that wiring hands out no handle and
        # persists no save/ratchet over a valid swapped file.
        directory = self._persist("swap-store", signed_only=True)
        memory_file = directory / "memory.json"
        unsigned_dir = self._persist("swap-source-unsigned",
                                     signed_only=False)
        unsigned_bytes = (unsigned_dir / "memory.json").read_bytes()
        self.assertNotEqual(unsigned_bytes,
                            memory_file.read_bytes())

        original = wiring._persisted_security_mode

        def swapping_inspection(path):
            result = original(path)
            Path(path).write_bytes(unsigned_bytes)
            return result

        wiring._persisted_security_mode = swapping_inspection
        try:
            with self.assertRaises(MemoryError) as ctx:
                open_production_store(directory)
        finally:
            wiring._persisted_security_mode = original
        self.assertIn("changed underfoot", str(ctx.exception))
        self.assertEqual(memory_file.read_bytes(), unsigned_bytes)

    def test_straddle_swap_between_load_and_reread_refused(self):
        # rev-r2 F1' (straddle-ABA), against the landed
        # state-binding: the swap happens INSIDE construction.
        # wiring imports MemoryStore into its own namespace, so
        # wiring.MemoryStore is the reference
        # open_production_store constructs through; patch it
        # with a subclass whose __init__ first swaps memory.json
        # to a valid UNSIGNED store file's bytes, then calls
        # super().__init__ (which loads the UNSIGNED state and
        # ratchets it in memory), then restores the signed
        # bytes. The byte re-read after construction therefore
        # matches the inspected bytes again, so byte-binding
        # alone would hand the handle out; the state-binding
        # must refuse instead: the constructed store's
        # state_digest() (the unsigned file's digest, still
        # carried after the in-memory ratchet) differs from the
        # inspected document's state_digest field. The raise is
        # the assertion that no handle was handed out.
        directory = self._persist("straddle-store",
                                  signed_only=True)
        memory_file = directory / "memory.json"
        signed_bytes = memory_file.read_bytes()
        unsigned_dir = self._persist("straddle-source-unsigned",
                                     signed_only=False)
        unsigned_bytes = (unsigned_dir / "memory.json").read_bytes()
        self.assertNotEqual(unsigned_bytes, signed_bytes)
        # The probe is only meaningful if the two files' own
        # state_digest fields differ — pin that, so a future
        # change that made them collide fails here as a broken
        # probe rather than passing silently.
        signed_digest = json.loads(
            signed_bytes.decode("utf-8"))["state_digest"]
        unsigned_digest = json.loads(
            unsigned_bytes.decode("utf-8"))["state_digest"]
        self.assertNotEqual(unsigned_digest, signed_digest)
        before = _snapshot_tree(directory)
        save_calls = []

        original_store = wiring.MemoryStore

        class StraddleSwapStore(original_store):
            def __init__(self, memory_dir, *args, **kwargs):
                target = Path(memory_dir) / "memory.json"
                target.write_bytes(unsigned_bytes)
                try:
                    super().__init__(memory_dir, *args, **kwargs)
                finally:
                    target.write_bytes(signed_bytes)

            def save(self):
                save_calls.append(True)
                return super().save()

        wiring.MemoryStore = StraddleSwapStore
        try:
            with self.assertRaises(MemoryError) as ctx:
                open_production_store(directory)
        finally:
            wiring.MemoryStore = original_store
        # The refusal is the state-binding's, not the
        # byte-binding's: its message names the state digest.
        self.assertIn("changed underfoot", str(ctx.exception))
        self.assertIn("state digest", str(ctx.exception))
        # The restore stands: the file on disk afterwards is
        # exactly the signed bytes, the tree is otherwise
        # untouched, and no save occurred on the constructed
        # (but never handed out) instance.
        self.assertEqual(memory_file.read_bytes(), signed_bytes)
        self.assertEqual(_snapshot_tree(directory), before)
        self.assertEqual(save_calls, [])

    def test_passthrough_memory_store_subclass_still_opens(self):
        # Positive control for the state-binding: a MemoryStore
        # subclass that does nothing at all (pure pass-through)
        # still opens successfully — on the normal path the
        # constructed store's state_digest() equals the
        # inspected document's state_digest field, so the new
        # binding does not false-refuse.
        directory = self._persist("passthrough-store",
                                  signed_only=True)
        before = _snapshot_tree(directory)
        original_store = wiring.MemoryStore

        class PassThroughStore(original_store):
            pass

        wiring.MemoryStore = PassThroughStore
        try:
            store = open_production_store(directory)
        finally:
            wiring.MemoryStore = original_store
        self.assertIsInstance(store, PassThroughStore)
        self.assertIs(store.signed_only, True)
        self.assertEqual(store.security_mode, "signed_only")
        self.assertEqual(
            store.state_digest(),
            json.loads((directory / "memory.json").read_text(
                encoding="utf-8"))["state_digest"])
        self.assertEqual(_snapshot_tree(directory), before)


# ---------------------------------------------------------------------
# commit_production
# ---------------------------------------------------------------------

def _attestation(**over):
    base = dict(
        verifier_id="seat-3", decision="approve",
        sealed_hash=SEALED, reward_hacking_checked=True,
        evidence_ref="sealed-run-1",
        attested_at=datetime.now(timezone.utc).isoformat())
    base.update(over)
    return VerifierAttestation(**base)


def _fields(**over):
    base = {
        "id": "lesson-reverse", "domain": "factory-reverse",
        "kind": "strategy", "content": "full-reverse",
        "author": "seat-11",
        "source": "derivation:public-practice-gen1",
        "evidence_ref": "derive:abc:reverse",
        "proposal_id": "prop-1", "verifier_id": "seat-3",
        "supersedes": None,
    }
    base.update(over)
    return base


def _gate_kwargs(**over):
    base = dict(
        builder_ids=BUILDERS, reviewer_ids=REVIEWERS,
        baseline_public={"bench-a": 0.5},
        candidate_public={"bench-a": 0.6},
        baseline_sealed={"bench-s": 0.5},
        candidate_sealed={"bench-s": 0.7},
        capability_baseline={"cap-a": 0.5},
        capability_candidate={"cap-a": 0.5},
        attestation=_attestation(), expected_sealed_hash=SEALED)
    base.update(over)
    return base


def _commit_bundle():
    """A real signed gate envelope + signed attestation pair,
    minted on the host clock (commit_production accepts no time
    override, so freshness must be genuine). The attestation is
    signed FIRST so it cannot outlive the decision envelope."""
    attestation = _attestation()
    signed_att = sign_attestation(
        attestation, signing_key=KEY, signer_id="seat-3",
        proposal_id="prop-1")
    decision = decide_write(entry_fields=_fields(),
                            **_gate_kwargs(attestation=attestation))
    envelope = sign_gate_decision(
        decision, signing_key=KEY, signer_id="gate-signer",
        attestation=attestation, signed_attestation=signed_att)
    return _fields(), envelope, signed_att


class CommitProductionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        store_dir = self.base / "prod-store"
        MemoryStore(store_dir, signed_only=True).save()
        self.store = open_production_store(store_dir)
        self.store_dir = store_dir

    def test_missing_signed_attestation_refused(self):
        fields, envelope, _sa = _commit_bundle()
        with self.assertRaises(SigningError):
            commit_production(
                self.store, fields, envelope, signing_key=KEY,
                signed_attestation=None,
                expected_signer_id="gate-signer")
        self.assertEqual(self.store.retrieve(), [])

    def test_non_signed_only_store_refused(self):
        unsigned = MemoryStore(self.base / "plain-store")
        fields, envelope, signed_att = _commit_bundle()
        with self.assertRaises(SigningError):
            commit_production(
                unsigned, fields, envelope, signing_key=KEY,
                signed_attestation=signed_att,
                expected_signer_id="gate-signer")
        self.assertEqual(unsigned.retrieve(), [])

    def test_happy_path_commit_lands(self):
        fields, envelope, signed_att = _commit_bundle()
        # expected_state_digest omitted: commit_production must
        # default it to the store's current digest for this to
        # succeed against the store's gated commit.
        entry = commit_production(
            self.store, fields, envelope, signing_key=KEY,
            signed_attestation=signed_att,
            expected_signer_id="gate-signer")
        self.assertEqual(entry["id"], "lesson-reverse")
        self.assertEqual(
            [e["id"] for e in self.store.retrieve()],
            ["lesson-reverse"])
        self.assertEqual(self.store.get("lesson-reverse")["id"],
                         "lesson-reverse")
        # And it persisted: a freshly opened production store
        # over the same directory sees the entry.
        reopened = open_production_store(self.store_dir)
        self.assertEqual(
            [e["id"] for e in reopened.retrieve()],
            ["lesson-reverse"])

    def test_stale_expected_state_digest_refused(self):
        fields, envelope, signed_att = _commit_bundle()
        with self.assertRaises(MemoryError):
            commit_production(
                self.store, fields, envelope, signing_key=KEY,
                signed_attestation=signed_att,
                expected_signer_id="gate-signer",
                expected_state_digest="0" * 64)
        self.assertEqual(self.store.retrieve(), [])

    def test_expected_signer_id_omitted_is_type_error(self):
        # The pin is mandatory in the landed signature (no
        # default): omitting it is a TypeError at call time,
        # before anything can be committed.
        fields, envelope, signed_att = _commit_bundle()
        with self.assertRaises(TypeError):
            commit_production(
                self.store, fields, envelope, signing_key=KEY,
                signed_attestation=signed_att)
        self.assertEqual(self.store.retrieve(), [])

    def test_wrong_signer_pin_refused_nothing_committed(self):
        # rev-r4 probed signer_mismatch at the underlying
        # verifier; pin it at this surface: a pin that is not
        # the gate decision's signer refuses the commit and
        # nothing lands.
        fields, envelope, signed_att = _commit_bundle()
        with self.assertRaises(SigningError) as ctx:
            commit_production(
                self.store, fields, envelope, signing_key=KEY,
                signed_attestation=signed_att,
                expected_signer_id="not-the-gate-signer")
        self.assertIn("signer_mismatch", str(ctx.exception))
        self.assertEqual(self.store.retrieve(), [])

    def test_no_now_parameter_anywhere(self):
        # Freshness verdicts stay on the host clock inside the
        # verification path: no public function in wiring.py may
        # accept a caller-supplied time.
        for fn in (production_client, open_production_store,
                   commit_production):
            with self.subTest(fn=fn.__name__):
                self.assertNotIn(
                    "now", inspect.signature(fn).parameters)


# ---------------------------------------------------------------------
# Live deployment (provisioned by the coordinator; skips until then)
# ---------------------------------------------------------------------

LIVE_ENV_FILE = Path("/etc/aion-verifier/verifier.env")
LIVE_BASE = Path("/var/lib/aion-verifier")
LIVE_KEY = LIVE_BASE / "keys" / "gate.key"


def _parse_env_file(path):
    env = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return env
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _aion_verifier():
    try:
        return pwd.getpwnam("aion-verifier")
    except KeyError:
        return None


def _live_provisioned():
    # The deploy suite's detection pattern, verbatim in shape:
    # root, the aion-verifier user, runuser, non-empty signer/
    # actor ids in the real env file, and the provisioned key.
    if os.geteuid() != 0 or _aion_verifier() is None:
        return False
    if not shutil.which("runuser"):
        return False
    env = _parse_env_file(LIVE_ENV_FILE)
    return bool(env.get("AION_VERIFIER_SIGNER_ID")
                and env.get("AION_VERIFIER_ACTOR_ID")
                and LIVE_KEY.is_file())


LIVE = _live_provisioned()
LIVE_ENV = _parse_env_file(LIVE_ENV_FILE) if LIVE else {}


@unittest.skipUnless(
    LIVE,
    "live deployment not provisioned (root + non-empty signer/"
    "actor ids in /etc/aion-verifier/verifier.env + "
    "/var/lib/aion-verifier/keys/gate.key required)")
class LiveProductionWiringTests(unittest.TestCase):
    """Run standalone at cycle close, after re-provisioning:
        python3 -m unittest \
            tests.test_trust_wiring.LiveProductionWiringTests
    """

    def test_production_client_against_live_deployment(self):
        # Pins obtained operator-side the same way the deploy
        # suite obtains key identity: the signer id from the
        # real env file, and the key id by reading the
        # provisioned key file test-side (root is outside the
        # threat model; a key-holding consumer does the same).
        env = dict(LIVE_ENV)
        key = load_signing_key(
            Path(env.get("AION_VERIFIER_KEY_PATH", str(LIVE_KEY))))
        client = production_client(
            env,
            expected_signer_id=env["AION_VERIFIER_SIGNER_ID"],
            expected_key_id=key.key_id)
        self.assertIsInstance(client, VerifierClient)
        # The least-budget-consuming real call, mirroring the
        # deploy suite's own live probe (its test_14): a junk
        # verify_envelope signs nothing and spends no proposal
        # or identity budget, yet the response is produced
        # INSIDE the verifier — so the deployment mode it
        # reports is the mode the process actually loaded, and
        # the client's production pin enforces it at response
        # time (any other reported mode would raise).
        verdict = client.verify_envelope({})
        self.assertFalse(verdict.valid)
        self.assertEqual(client.observed_deployment_mode,
                         "production")


if __name__ == "__main__":
    unittest.main()
