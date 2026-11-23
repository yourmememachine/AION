"""Tests for the cycle-26 interactive confirmation gate on the
supersession approval tool's `approve` subcommand (seat B).

Covered:

* Non-TTY stdin (a plain io.StringIO) -> approve refuses with
  exit code 2 and creates NO output file.
* Fake-TTY stdin with the WRONG confirmation token -> refuses,
  no output file.
* Fake-TTY stdin at EOF (empty readline) -> refuses, no output.
* Fake-TTY stdin with the CORRECT token (the first 12 hex
  characters of the candidate payload hash) -> the approval is
  written and verifies under the approver public key.
* generate-key / public-key are unaffected by the gate: they
  succeed with non-TTY stdin.

Fixtures mirror tests/test_trust_supersession_approval.py
(same envelope/head/report construction).
"""

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing.ceremony_authorisation import (
    _make_ceremony_signing_key,
    ceremony_authorisation_envelope_to_dict,
    sign_ceremony_authorisation,
)
from trust.supersession_approval import (
    REFUSAL_CODE_SUPERSESSION_REQUIRED,
    supersession_approval_from_json,
    verify_supersession_approval,
)
from trust.supersession_approval_tool import (
    _make_approver_key,
    approver_public_key_for,
    main as tool_main,
)

NOW = "2026-11-20T12:00:00+00:00"

CEREMONY_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle26 gate test ceremony seed").digest())
APPROVER_KEY = _make_approver_key(
    hashlib.sha256(b"cycle26 gate test approver seed").digest())
APPROVER_PIN = approver_public_key_for(APPROVER_KEY)

# mint_envelope's default candidate: cycle 52, payload "c"*64,
# so the confirmation token is "c"*12.
CORRECT_TOKEN = "c" * 12
WRONG_TOKEN = "d" * 12

_counter = [0]


def mint_envelope(reason="chain_gap_recovery", **over):
    _counter[0] += 1
    kwargs = dict(
        signing_key=CEREMONY_KEY, signer_id="verifier-svc",
        operator_id="operator-1",
        ceremony_id=f"ceremony-c26-{_counter[0]}",
        reason=reason,
        old_pin={"cycle_seq": 41, "payload_hash": "a" * 64},
        candidate={"cycle_seq": 52, "payload_hash": "c" * 64,
                   "signer_id": "snapshot-svc",
                   "key_id": "key-0123456789abcdef"},
        evidence_hash="e" * 64, evidence_ref="evidence-bundle-1",
        now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def head_entry_for(head_env):
    return {"authorisation_id": head_env.authorisation_id,
            "ceremony_id": head_env.ceremony_id,
            "operator_id": head_env.operator_id,
            "old_cycle_seq": 41, "old_payload_hash": "a" * 64,
            "new_cycle_seq": 47, "new_payload_hash": "b" * 64,
            "evidence_hash": "e" * 64, "consumed_at": NOW,
            "seq": 3, "entry_hash": "f" * 64}


def report_for(env, head):
    return {
        "report": "pending-supersession/1",
        "refusal_code": REFUSAL_CODE_SUPERSESSION_REQUIRED,
        "envelope": ceremony_authorisation_envelope_to_dict(env),
        "operator_id": env.operator_id,
        "head": {"authorisation_id": head["authorisation_id"],
                 "ceremony_id": head["ceremony_id"],
                 "old_cycle_seq": head["old_cycle_seq"],
                 "old_payload_hash": head["old_payload_hash"],
                 "new_cycle_seq": head["new_cycle_seq"],
                 "new_payload_hash": head["new_payload_hash"],
                 "seq": head["seq"],
                 "entry_hash": head["entry_hash"]},
        "reported_at": NOW}


class FakeTTY:
    """A stdin stand-in that reports isatty() -> True and serves
    readline() from a wrapped StringIO (the testability seam:
    the gate resolves sys.stdin at call time)."""

    def __init__(self, text=""):
        self._buffer = io.StringIO(text)

    def isatty(self):
        return True

    def readline(self):
        return self._buffer.readline()


class InteractiveGateTests(unittest.TestCase):

    def setUp(self):
        self.env = mint_envelope()
        self.head_env = mint_envelope(
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        self.head = head_entry_for(self.head_env)
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.seed_path = tmp / "approver.seed"
        self.seed_path.write_text(
            APPROVER_KEY.seed.hex() + "\n", encoding="ascii")
        self.seed_path.chmod(0o600)
        self.report_path = tmp / "pending.json"
        self.report_path.write_text(
            json.dumps(report_for(self.env, self.head)),
            encoding="utf-8")
        self.out_path = tmp / "approval.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _approve(self, stdin):
        argv = ["approve", "--seed-path", str(self.seed_path),
                "--approver-id", "approver-1",
                "--pending-report", str(self.report_path),
                "--out", str(self.out_path)]
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), \
                contextlib.redirect_stdout(stdout):
            rc = tool_main(argv)
        return rc, stdout.getvalue()

    def test_non_tty_stdin_refuses_and_writes_nothing(self):
        rc, _ = self._approve(io.StringIO(CORRECT_TOKEN + "\n"))
        self.assertEqual(rc, 2)
        self.assertFalse(self.out_path.exists())

    def test_fake_tty_wrong_token_refuses_and_writes_nothing(self):
        rc, _ = self._approve(FakeTTY(WRONG_TOKEN + "\n"))
        self.assertEqual(rc, 2)
        self.assertFalse(self.out_path.exists())

    def test_fake_tty_eof_refuses_and_writes_nothing(self):
        rc, _ = self._approve(FakeTTY(""))
        self.assertEqual(rc, 2)
        self.assertFalse(self.out_path.exists())

    def test_fake_tty_correct_token_writes_verifiable_approval(self):
        rc, stdout = self._approve(FakeTTY(CORRECT_TOKEN + "\n"))
        self.assertEqual(rc, 0)
        self.assertTrue(self.out_path.exists())
        # The binding summary was printed before signing and
        # displays the confirmation code.
        self.assertIn(CORRECT_TOKEN, stdout)
        self.assertIn("cycle 41 -> 47", stdout)
        self.assertIn("cycle 52", stdout)
        artefact = supersession_approval_from_json(
            self.out_path.read_text(encoding="utf-8"))
        # The CLI signs on the host clock: verify with now=None.
        self.assertEqual(
            verify_supersession_approval(
                artefact, public_key=APPROVER_PIN), ())

    def test_generate_key_and_public_key_need_no_tty(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "approver.seed"
            stdout = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO("")), \
                    contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    tool_main(["generate-key", "--seed-path",
                               str(seed_path)]), 0)
                self.assertEqual(
                    tool_main(["public-key", "--seed-path",
                               str(seed_path)]), 0)


if __name__ == "__main__":
    unittest.main()
