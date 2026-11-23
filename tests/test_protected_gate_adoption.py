"""Negative-integration tests for the Protected Gate adoption
(cycle 13, Dilip's approval of internal/PROTECTED-GATE-PROPOSAL.md).

Both external seats (ChatGPT and Gemini) asked for an end-to-end
negative test of the adopted gate, not only unit pins: an
otherwise-ACCEPTABLE change must be refused solely because a
changed path is a non-canonical spelling of a protected file,
and an uncanonicalisable spelling must produce no decision at
all. This suite drives the real entry points:

* eval.gate.evaluate_self_change with a passing fixture shape
  copied from tests/test_gate.py (valid score maps including a
  sealed gain, a valid non-builder reviewer attestation);
* the REAL verifier subprocess (the tests/test_trust_verifier.py
  fixture pattern, research mode) against a registry.json
  carrying a duplicate key — the P-1 finding's artefact, now
  refused at parse after the cycle-13 duplicate-key fix — plus
  the loader-level legs for eval/registry.py (P-1) and
  eval/calibration.py (P-2);
* fresh-interpreter subprocesses pinning that the gate's
  function-local import of trust.pathpolicy resolves in both
  import orders (the import-cycle guard for the lazy import).
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.calibration import (
    CalibrationLog,
    CorruptCalibrationError,
    make_blind_entry,
)
from eval.gate import (
    GateInputError,
    VerifierAttestation,
    check_protected_paths,
    evaluate_self_change,
)
from oversight.approval import is_protected_path
from trust import pathpolicy
from eval.registry import CorruptRegistryError, EvalRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- Gate fixture: the passing shape from tests/test_gate.py. ---
BUILDERS = ["builder-1", "builder-2", "builder-3"]
REVIEWERS = ["rev-1", "rev-2", "rev-3", "rev-4", "rev-5", "rev-6"]
SEALED_HASH = "a" * 64
PUBLIC_BASE = {"bench-a": 0.5, "bench-b": 0.5}
SEALED_BASE = {"hidden-a": 0.5, "hidden-b": 0.5}
CAP_BASE = {"coding": 0.7, "reasoning": 0.6, "memory-recall": 0.8}


def _evaluate(changed_paths):
    """An otherwise-acceptable change: every suite is flat except
    one sealed gain, and the attestation is a valid approval from
    a reviewer who is not a builder. Only changed_paths varies."""
    sealed = dict(SEALED_BASE)
    sealed["hidden-a"] = 0.7  # the sealed gain acceptance requires
    return evaluate_self_change(
        proposal_id="proposal-adoption",
        builder_ids=BUILDERS,
        reviewer_ids=REVIEWERS,
        baseline_public=dict(PUBLIC_BASE),
        candidate_public=dict(PUBLIC_BASE),
        baseline_sealed=dict(SEALED_BASE),
        candidate_sealed=sealed,
        capability_baseline=dict(CAP_BASE),
        capability_candidate=dict(CAP_BASE),
        attestation=VerifierAttestation(
            verifier_id="rev-1", decision="approve",
            sealed_hash=SEALED_HASH, reward_hacking_checked=True,
            evidence_ref="sealed run 7",
            attested_at="2026-11-19T00:00:00+00:00"),
        expected_sealed_hash=SEALED_HASH,
        changed_paths=changed_paths,
    )


class GateAdoptionIntegrationTests(unittest.TestCase):
    """(a)-(d): the refusal is the path, and only the path."""

    def test_noncanonical_spelling_of_protected_file_refused(self):
        decision = _evaluate(["core//loop.py"])
        self.assertFalse(decision.accepted)
        self.assertIn("protected_path", decision.reasons)
        # Offenders are reported as the canonical spelling.
        self.assertEqual(decision.protected_violations,
                         ("core/loop.py",))

    def test_canonical_spelling_of_protected_file_refused(self):
        decision = _evaluate(["core/loop.py"])
        self.assertFalse(decision.accepted)
        self.assertIn("protected_path", decision.reasons)
        self.assertEqual(decision.protected_violations,
                         ("core/loop.py",))

    def test_unprotected_control_change_accepted(self):
        # The control proves the refusals above are caused by the
        # path: the identical change naming an unprotected file
        # is accepted.
        decision = _evaluate(["src/feature.py"])
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reasons, ())
        self.assertEqual(decision.protected_violations, ())

    def test_uncanonicalisable_spelling_raises_no_decision(self):
        # An escaping ".." spelling has no canonical form: the
        # gate raises GateInputError before any decision exists,
        # rather than returning a (potentially signed) verdict.
        with self.assertRaises(GateInputError):
            _evaluate(["a/../../eval/gate.py"])


class GateClosureNegativeTests(unittest.TestCase):
    """Cycle 19 negative tests (DESIGN-FINAL A5, external seats'
    requirement): the canonicaliser chain is protected by the gate
    itself, so the two-step canonicaliser-poisoning attack is
    broken at step 1.

    The oversight flip is also pinned here (seat A's choice of
    home): because oversight's is_protected_path delegates to the
    gate, trust/pathpolicy.py — previously NOT oversight-protected
    — now reports protected through that delegation too."""

    CANONICALISER_SET = ("trust/pathpolicy.py", "oversight/approval.py",
                         "trust/__init__.py", "oversight/__init__.py")

    def test_oversight_flip_trust_pathpolicy_now_protected(self):
        self.assertTrue(is_protected_path("trust/pathpolicy.py"))
        self.assertTrue(is_protected_path("trust/__init__.py"))

    # N1: a change editing only the canonicaliser is refused by
    # the gate itself, for each file in the canonicaliser set.
    def test_n1_each_canonicaliser_file_flagged_by_gate(self):
        for path in self.CANONICALISER_SET:
            with self.subTest(path=path):
                self.assertEqual(check_protected_paths([path]), (path,))

    def test_n1_each_canonicaliser_file_refused_end_to_end(self):
        for path in self.CANONICALISER_SET:
            with self.subTest(path=path):
                decision = _evaluate([path])
                self.assertFalse(decision.accepted)
                self.assertIn("protected_path", decision.reasons)
                self.assertEqual(decision.protected_violations, (path,))

    def test_n1_noncanonical_variants_flag_with_canonical_spelling(self):
        self.assertEqual(check_protected_paths(["trust//pathpolicy.py"]),
                         ("trust/pathpolicy.py",))
        self.assertEqual(check_protected_paths(["oversight/./approval.py"]),
                         ("oversight/approval.py",))

    def test_n1_policy_classify_reports_gate_and_overlap(self):
        self.assertEqual(
            pathpolicy.classify("trust/pathpolicy.py")["protected_by"],
            ["gate"])
        # The gate/oversight overlap is reported honestly, not hidden.
        self.assertEqual(
            pathpolicy.classify("oversight/approval.py")["protected_by"],
            ["gate", "oversight"])

    # N2 (two-step): step 1 — a change editing only the
    # canonicaliser is refused protected_path, so there is no
    # accepted tree state in which the canonicaliser differs;
    # step 2 — with the canonicaliser unmodified, the former
    # gate-miss spellings that would have been the bypass payload
    # are still refused. No in-process monkeypatch theatre: the
    # gate is a pure function over path strings and never reads
    # the candidate bytes of the canonicaliser, so "modification"
    # is modelled exactly as the threat model poses it — as a
    # proposed change naming the file.
    def test_n2_two_step_canonicaliser_attack_broken_at_step_1(self):
        # Step 1: the poison attempt is itself refused.
        for path in ("trust/pathpolicy.py", "oversight/approval.py"):
            with self.subTest(step=1, path=path):
                decision = _evaluate([path])
                self.assertFalse(decision.accepted)
                self.assertIn("protected_path", decision.reasons)
                self.assertEqual(decision.protected_violations, (path,))
        # Step 2: former gate-miss spellings still refused by the
        # canonicaliser as shipped.
        for raw, canonical in (("core//loop.py", "core/loop.py"),
                               ("eval//gate.py", "eval/gate.py"),
                               ("trust//pathpolicy.py",
                                "trust/pathpolicy.py")):
            with self.subTest(step=2, raw=raw):
                self.assertEqual(check_protected_paths([raw]), (canonical,))
        decision = _evaluate(["core//loop.py"])
        self.assertFalse(decision.accepted)
        self.assertIn("protected_path", decision.reasons)
        self.assertEqual(decision.protected_violations, ("core/loop.py",))


# --- Duplicate-key artefact: P-1 / P-2 after the cycle-13 fix. --
ITEMS = [("sealed-1", "algebra", "2+2?", "4"),
         ("sealed-2", "algebra", "3*3?", "9"),
         ("sealed-3", "geo", "pi~?", "3.14")]
ACTOR = "verifier-actor"
SIGNER = "verifier-svc"


def _duplicate_first(text, key_pattern, bogus_fragment):
    """Return text with a bogus FIRST copy of a key duplicated
    before its real value: a last-wins parser parses the real
    value (and, for the registry, the state digest recomputed
    over that last-wins parse still validates), while a strict
    parser refuses the document at parse time."""
    match = re.search(key_pattern, text)
    assert match, key_pattern
    return text.replace(match.group(0),
                        bogus_fragment + match.group(0), 1)


class DuplicateKeyArtefactTests(unittest.TestCase):
    """A duplicate-key registry must be refused by the loader
    AND by the real verifier, with no signed attestation issued;
    a duplicate-key calibration log must be refused by its
    loader."""

    def setUp(self):
        from signing import generate_key_file
        from trust.client import VerifierClient

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        base.chmod(0o700)
        self.home = base / "verifier-home"
        self.home.mkdir()
        self.home.chmod(0o700)
        self.key = generate_key_file(self.home / "gate.key")
        self.registry_dir = base / "registry"
        registry = EvalRegistry(self.registry_dir)
        for item_id, domain, prompt, expected in ITEMS:
            registry.add_sealed_item(item_id, domain, prompt,
                                     expected, "test-actor")
        self.manifest_hash = registry.sealed_manifest_hash(ACTOR)
        # Plant the P-1 artefact: a valid registry carrying a
        # bogus first "public_version": 999 duplicated before the
        # real value (the exact shape cycle 11 verified loaded
        # last-wins before the fix).
        registry_path = self.registry_dir / "registry.json"
        raw = registry_path.read_text(encoding="utf-8")
        dup = _duplicate_first(raw, r'"public_version":\s*\d+',
                               '"public_version": 999, ')
        assert dup != raw
        registry_path.write_text(dup, encoding="utf-8")
        self.env = {
            "AION_VERIFIER_KEY_PATH": str(self.home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": SIGNER,
            "AION_VERIFIER_ACTOR_ID": ACTOR,
            "AION_REGISTRY_DIR": str(self.registry_dir),
            "AION_VERIFIER_HOME": str(self.home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
        }
        self.client = VerifierClient(
            verifier_env=self.env, expected_signer_id=SIGNER,
            expected_key_id=self.key.key_id)

    def test_registry_loader_refuses_duplicate_key(self):
        with self.assertRaises(CorruptRegistryError):
            EvalRegistry(self.registry_dir)

    def test_verifier_refuses_duplicate_key_registry_unsigned(self):
        from trust.errors import VerifierConfigError
        from trust.ledger import SigningLedger

        # sealed_eval loads the registry inside the verifier: the
        # duplicate-key artefact is a registry error there, not a
        # signed result of any kind.
        with self.assertRaises(VerifierConfigError) as ctx:
            self.client.sealed_eval(
                [expected for *_x, expected in ITEMS])
        self.assertIn("registry_untrusted", str(ctx.exception))
        # No signed attestation was issued: the signing ledger
        # holds no sign entries at all.
        ledger = SigningLedger(self.home / "ledger")
        signs = [e for e in ledger.entries() if e["kind"] == "sign"]
        self.assertEqual(signs, [])

    def test_calibration_loader_refuses_duplicate_key(self):
        cal_dir = Path(self.tmp.name) / "calibration"
        log = CalibrationLog(cal_dir)
        log.record_blind(make_blind_entry(
            entry_id="e1", subject_id="subj-1",
            subject_ref="adoption fixture", reviewer_id="rev-1",
            score=0.5))
        cal_path = cal_dir / "calibration.json"
        raw = cal_path.read_text(encoding="utf-8")
        # The P-2 shape: a bogus first duplicate of an entry's
        # "score", the real value second.
        dup = _duplicate_first(raw, r'"score":\s*[0-9.]+',
                               '"score": 999, ')
        assert dup != raw
        cal_path.write_text(dup, encoding="utf-8")
        with self.assertRaises(CorruptCalibrationError):
            CalibrationLog(cal_dir)


class ImportCycleGuardTests(unittest.TestCase):
    """The gate imports trust.pathpolicy.canonicalise lazily,
    inside check_protected_paths, because a module-level import
    cycles (trust/__init__ -> shipcheck -> signing.gate_decision
    -> eval.gate). These subprocess tests pin that the lazy
    import resolves in a fresh interpreter in both orders."""

    def _run_fresh(self, code):
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_gate_imported_first_then_policy_resolves(self):
        out = self._run_fresh(
            "import eval.gate as gate\n"
            "print(gate.check_protected_paths(['core//loop.py']))\n")
        self.assertEqual(out, "('core/loop.py',)")

    def test_trust_imported_first_then_policy_resolves(self):
        out = self._run_fresh(
            "import trust\n"
            "import eval.gate as gate\n"
            "print(gate.check_protected_paths(['core//loop.py']))\n")
        self.assertEqual(out, "('core/loop.py',)")


if __name__ == "__main__":
    unittest.main()
