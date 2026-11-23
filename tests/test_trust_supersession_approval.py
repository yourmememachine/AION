"""Tests for cycle-25 supersession approvals (seat A).

Covered:

* Artefact round-trip (dict + JSON) and verification under the
  pinned approver public key; wrong key, tampered binding
  fields, expiry and signed-in-future reasons.
* Projection refusals: a burned_unadopted (ordinary recovery)
  replacement is un-mintable; a refusal code other than
  ceremony_supersede_required is un-mintable.
* The binding helper against verifier-derived facts: fully
  bound -> (); mutations of the abandoned pair, the candidate /
  movement, and the failed-attempt head seq/hash each refuse
  with their own mismatch name.
* The approval tool: report -> signed approval end-to-end
  (in-process and through the real CLI), report refusals
  (wrong refusal code, recovery envelope), seed file
  generate/load discipline and test-seed refusal.
* Auditability pins (design-approval.md section 3): the tool
  module is imported by NO running-system module; the verify
  module contains no signing call; the approver seed-path env
  var is absent from the verifier wiring allowlist.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing.ceremony_authorisation import (
    _make_ceremony_signing_key,
    ceremony_authorisation_envelope_to_dict,
    sign_ceremony_authorisation,
)
from signing.gate_decision import SigningError
from trust.supersession_approval import (
    REFUSAL_CODE_SUPERSESSION_REQUIRED,
    approval_binding_mismatches,
    approver_public_key_from_hex,
    supersession_approval_from_dict,
    supersession_approval_from_json,
    supersession_approval_to_dict,
    supersession_approval_to_json,
    verify_supersession_approval,
)
from trust.supersession_approval_tool import (
    _make_approver_key,
    approver_public_key_for,
    build_approval_for_report,
    generate_approver_key_file,
    load_approver_seed,
    main as tool_main,
    sign_supersession_approval,
)

NOW = "2026-11-20T12:00:00+00:00"

CEREMONY_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle25 approval test ceremony seed").digest())
APPROVER_KEY = _make_approver_key(
    hashlib.sha256(b"cycle25 approval test approver seed").digest())
OTHER_KEY = _make_approver_key(
    hashlib.sha256(b"cycle25 approval test other seed").digest())
APPROVER_PIN = approver_public_key_for(APPROVER_KEY)

_counter = [0]


def mint_envelope(reason="chain_gap_recovery", **over):
    _counter[0] += 1
    kwargs = dict(
        signing_key=CEREMONY_KEY, signer_id="verifier-svc",
        operator_id="operator-1",
        ceremony_id=f"ceremony-c25-{_counter[0]}",
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
    """A consumption-journal head entry dict for the movement
    41/'a' -> 47/'b' consumed under head_env."""
    return {"authorisation_id": head_env.authorisation_id,
            "ceremony_id": head_env.ceremony_id,
            "operator_id": head_env.operator_id,
            "old_cycle_seq": 41, "old_payload_hash": "a" * 64,
            "new_cycle_seq": 47, "new_payload_hash": "b" * 64,
            "evidence_hash": "e" * 64, "consumed_at": NOW,
            "seq": 3, "entry_hash": "f" * 64}


def bindings_for(env, head):
    abandoned = {
        "authorisation_id": head["authorisation_id"],
        "ceremony_id": head["ceremony_id"],
        "old_cycle_seq": head["old_cycle_seq"],
        "old_payload_hash": head["old_payload_hash"],
        "new_cycle_seq": head["new_cycle_seq"],
        "new_payload_hash": head["new_payload_hash"]}
    replacement = {
        "authorisation_id": env.authorisation_id,
        "ceremony_id": env.ceremony_id,
        "reason": env.reason,
        "operator_id": env.operator_id,
        "superseding_old_cycle_seq": env.old_pin["cycle_seq"],
        "superseding_old_payload_hash": env.old_pin["payload_hash"],
        "candidate_cycle_seq": env.candidate["cycle_seq"],
        "candidate_payload_hash": env.candidate["payload_hash"]}
    failed_attempt = {
        "attempted_authorisation_id": env.authorisation_id,
        "refusal_code": REFUSAL_CODE_SUPERSESSION_REQUIRED,
        "head_authorisation_id": head["authorisation_id"],
        "head_entry_seq": head["seq"],
        "head_entry_hash": head["entry_hash"]}
    return abandoned, replacement, failed_attempt


def sign_approval(env, head, **over):
    abandoned, replacement, failed_attempt = bindings_for(env, head)
    kwargs = dict(approver_key=APPROVER_KEY, approver_id="approver-1",
                  abandoned=abandoned, replacement=replacement,
                  failed_attempt=failed_attempt, now=NOW)
    kwargs.update(over)
    return sign_supersession_approval(**kwargs)


class ArtefactTests(unittest.TestCase):

    def setUp(self):
        self.env = mint_envelope()
        self.head_env = mint_envelope(
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        self.head = head_entry_for(self.head_env)
        self.approval = sign_approval(self.env, self.head)

    def test_roundtrip_dict_and_json_verify_clean(self):
        via_dict = supersession_approval_from_dict(
            supersession_approval_to_dict(self.approval))
        via_json = supersession_approval_from_json(
            supersession_approval_to_json(self.approval))
        for artefact in (via_dict, via_json):
            self.assertEqual(
                verify_supersession_approval(
                    artefact, public_key=APPROVER_PIN, now=NOW), ())
            self.assertEqual(artefact, self.approval)

    def test_fully_bound_against_verifier_facts(self):
        self.assertEqual(
            approval_binding_mismatches(
                self.approval, abandoned_entry=self.head,
                head_entry_seq=self.head["seq"],
                head_entry_hash=self.head["entry_hash"],
                signed=self.env), ())

    def test_wrong_approver_key_refused(self):
        reasons = verify_supersession_approval(
            self.approval,
            public_key=approver_public_key_for(OTHER_KEY), now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_tampered_candidate_hash_refused(self):
        data = supersession_approval_to_dict(self.approval)
        data["replacement"]["candidate_payload_hash"] = "d" * 64
        tampered = supersession_approval_from_dict(data)
        reasons = verify_supersession_approval(
            tampered, public_key=APPROVER_PIN, now=NOW)
        self.assertIn("payload_hash_mismatch", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_expired_and_signed_in_future(self):
        short = sign_approval(self.env, self.head, ttl_seconds=60)
        self.assertIn(
            "expired",
            verify_supersession_approval(
                short, public_key=APPROVER_PIN,
                now="2026-11-20T12:02:00+00:00"))
        future = sign_supersession_approval(
            approver_key=APPROVER_KEY, approver_id="approver-1",
            abandoned=self.approval.abandoned,
            replacement=self.approval.replacement,
            failed_attempt=self.approval.failed_attempt,
            now="2026-11-20T13:00:00+00:00")
        self.assertIn(
            "signed_in_future",
            verify_supersession_approval(
                future, public_key=APPROVER_PIN, now=NOW))

    def test_approver_id_expectation(self):
        self.assertEqual(
            verify_supersession_approval(
                self.approval, public_key=APPROVER_PIN,
                expected_approver_id="approver-2", now=NOW),
            ("approver_mismatch",))

    def test_from_dict_strict_keys_and_formats(self):
        data = supersession_approval_to_dict(self.approval)
        data["extra"] = 1
        with self.assertRaises(SigningError):
            supersession_approval_from_dict(data)
        data = supersession_approval_to_dict(self.approval)
        data["signature"] = "zz" * 64
        with self.assertRaises(SigningError):
            supersession_approval_from_dict(data)

    def test_public_key_pin_from_hex(self):
        pin = approver_public_key_from_hex(APPROVER_KEY.public_key.hex())
        self.assertEqual(pin, APPROVER_PIN)
        with self.assertRaises(SigningError):
            approver_public_key_from_hex("not hex")


class ProjectionRefusalTests(unittest.TestCase):

    def setUp(self):
        self.env = mint_envelope()
        self.head = head_entry_for(mint_envelope())

    def test_recovery_replacement_unmintable(self):
        recovery = mint_envelope(reason="burned_unadopted")
        abandoned, replacement, failed_attempt = bindings_for(
            recovery, self.head)
        with self.assertRaises(SigningError):
            sign_supersession_approval(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                abandoned=abandoned, replacement=replacement,
                failed_attempt=failed_attempt, now=NOW)

    def test_other_refusal_code_unmintable(self):
        abandoned, replacement, failed_attempt = bindings_for(
            self.env, self.head)
        failed_attempt["refusal_code"] = "ceremony_head_regression"
        with self.assertRaises(SigningError):
            sign_supersession_approval(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                abandoned=abandoned, replacement=replacement,
                failed_attempt=failed_attempt, now=NOW)

    def test_ttl_bounds(self):
        abandoned, replacement, failed_attempt = bindings_for(
            self.env, self.head)
        with self.assertRaises(SigningError):
            sign_supersession_approval(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                abandoned=abandoned, replacement=replacement,
                failed_attempt=failed_attempt, ttl_seconds=30, now=NOW)
        # Above the 3600 s cap REFUSES (design §3) — never a
        # silent clamp to 3600.
        with self.assertRaises(SigningError):
            sign_supersession_approval(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                abandoned=abandoned, replacement=replacement,
                failed_attempt=failed_attempt, ttl_seconds=99999,
                now=NOW)
        with self.assertRaises(SigningError):
            sign_supersession_approval(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                abandoned=abandoned, replacement=replacement,
                failed_attempt=failed_attempt, ttl_seconds=3601,
                now=NOW)
        # The cap itself is mintable and verifiable.
        at_cap = sign_supersession_approval(
            approver_key=APPROVER_KEY, approver_id="approver-1",
            abandoned=abandoned, replacement=replacement,
            failed_attempt=failed_attempt, ttl_seconds=3600, now=NOW)
        self.assertEqual(
            verify_supersession_approval(
                at_cap, public_key=APPROVER_PIN,
                now="2026-11-20T12:59:00+00:00"), ())


class BindingMismatchTests(unittest.TestCase):

    def setUp(self):
        self.env = mint_envelope()
        self.head_env = mint_envelope(
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        self.head = head_entry_for(self.head_env)
        self.approval = sign_approval(self.env, self.head)

    def _mismatches(self, approval=None, **over):
        kwargs = dict(abandoned_entry=self.head,
                      head_entry_seq=self.head["seq"],
                      head_entry_hash=self.head["entry_hash"],
                      signed=self.env)
        kwargs.update(over)
        return approval_binding_mismatches(
            approval or self.approval, **kwargs)

    def test_abandoned_pair_mutation(self):
        other_head = dict(self.head)
        other_head["new_payload_hash"] = "9" * 64
        self.assertIn("abandoned_mismatch",
                      self._mismatches(abandoned_entry=other_head))

    def test_movement_mutation_other_envelope(self):
        other_env = mint_envelope(
            candidate={"cycle_seq": 55, "payload_hash": "d" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        mismatches = self._mismatches(signed=other_env)
        self.assertIn("movement_mismatch", mismatches)
        self.assertIn("replacement_mismatch", mismatches)

    def test_failed_attempt_head_moved(self):
        # Head moved after the refusal: seq/hash no longer match.
        mismatches = self._mismatches(head_entry_seq=4,
                                      head_entry_hash="8" * 64)
        self.assertIn("failed_attempt_mismatch", mismatches)


class ToolTests(unittest.TestCase):

    def _report(self, env, head):
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

    def setUp(self):
        self.env = mint_envelope()
        self.head_env = mint_envelope(
            candidate={"cycle_seq": 47, "payload_hash": "b" * 64,
                       "signer_id": "snapshot-svc",
                       "key_id": "key-0123456789abcdef"})
        self.head = head_entry_for(self.head_env)

    def test_report_to_approval_end_to_end(self):
        approval = build_approval_for_report(
            approver_key=APPROVER_KEY, approver_id="approver-1",
            report=self._report(self.env, self.head), now=NOW)
        self.assertEqual(
            verify_supersession_approval(
                approval, public_key=APPROVER_PIN, now=NOW), ())
        self.assertEqual(
            approval_binding_mismatches(
                approval, abandoned_entry=self.head,
                head_entry_seq=self.head["seq"],
                head_entry_hash=self.head["entry_hash"],
                signed=self.env), ())

    def test_report_wrong_refusal_code_refused(self):
        report = self._report(self.env, self.head)
        report["refusal_code"] = "ceremony_already_consumed"
        with self.assertRaises(SigningError):
            build_approval_for_report(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                report=report, now=NOW)

    def test_report_recovery_envelope_refused(self):
        recovery = mint_envelope(reason="burned_unadopted")
        with self.assertRaises(SigningError):
            build_approval_for_report(
                approver_key=APPROVER_KEY, approver_id="approver-1",
                report=self._report(recovery, self.head), now=NOW)

    def test_seed_file_generate_load_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "approver.seed"
            self.assertEqual(
                tool_main(["generate-key", "--seed-path",
                           str(seed_path)]), 0)
            self.assertEqual(
                tool_main(["generate-key", "--seed-path",
                           str(seed_path)]), 2)  # no overwrite
            loaded = load_approver_seed(seed_path)
            self.assertEqual(
                tool_main(["public-key", "--seed-path",
                           str(seed_path)]), 0)
            report_path = Path(tmp) / "pending.json"
            report_path.write_text(
                __import__("json").dumps(
                    self._report(self.env, self.head)),
                encoding="utf-8")
            out_path = Path(tmp) / "approval.json"
            self.assertEqual(
                tool_main(["approve", "--seed-path", str(seed_path),
                           "--approver-id", "approver-1",
                           "--pending-report", str(report_path),
                           "--out", str(out_path)]), 0)
            artefact = supersession_approval_from_json(
                out_path.read_text(encoding="utf-8"))
            # The CLI signs on the host clock, so verify on the
            # host clock too (now=None), not the fixture NOW.
            self.assertEqual(
                verify_supersession_approval(
                    artefact,
                    public_key=approver_public_key_for(loaded)), ())

    def test_test_seed_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "bad.seed"
            seed_path.write_text(bytes(range(32)).hex() + "\n",
                                 encoding="ascii")
            seed_path.chmod(0o600)
            with self.assertRaises(SigningError):
                load_approver_seed(seed_path)


class AuditabilityTests(unittest.TestCase):
    """The adopter-cannot-mint property, pinned by source scan
    (design-approval.md section 3)."""

    ROOT = Path(__file__).resolve().parents[1]

    def _source(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def test_tool_module_not_imported_by_running_system(self):
        # Import-level scan: a prose MENTION of the tool (e.g. a
        # docstring explaining that the module is never imported)
        # is fine and expected; an import statement, a dynamic
        # import, or a subprocess reference is the minting route
        # this pin exists to exclude.
        import re
        import_pattern = re.compile(
            r"(^\s*(from|import)\s+\S*supersession_approval_tool"
            r"|__import__\([^)]*supersession_approval_tool"
            r"|importlib[^\n]*supersession_approval_tool"
            r"|supersession_approval_tool\s*\()", re.M)
        for rel in ("trust/pin_adoption.py", "trust/client.py",
                    "trust/verifier_main.py", "trust/wiring.py"):
            self.assertIsNone(
                import_pattern.search(self._source(rel)), rel)

    def test_verify_module_has_no_signing_path(self):
        source = self._source("trust/supersession_approval.py")
        self.assertNotIn("ed25519.sign(", source)
        self.assertNotIn("load_approver_seed", source)
        self.assertNotIn("token_bytes", source)

    def test_approver_seed_var_absent_from_verifier_allowlist(self):
        from trust.wiring import ALLOWED_ENV_KEYS
        self.assertNotIn("AION_SUPERSESSION_APPROVER_SEED_PATH",
                         ALLOWED_ENV_KEYS)
        self.assertNotIn("AION_SUPERSESSION_APPROVER_SEED_PATH",
                         self._source("trust/wiring.py"))


if __name__ == "__main__":
    unittest.main()
