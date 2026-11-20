"""Differential harness: gate vs path-policy/1 vs oversight
(Trust Boundary v3, CROSS-CHECK-4 item 4).

Both external seats voted FIX on v2 in part because the gate's
protected-path logic has NOT adopted path-policy/1, while v2
wording called the policy canonical/universal. This suite does
not edit the gate (eval/ is protected; adoption is Dilip's
Protected Gate Rule decision — see
internal/PROTECTED-GATE-PROPOSAL.md). It DEMONSTRATES the
equivalence domain and enumerates the divergences outside it
within the corpus (the corpus is not exhaustive: the gate-miss
class in particular is an open family — any separator/dot-
component perturbation of the exact-file entry core/loop.py
derives it — and the bound that actually protects production
is the verifier's canonical-only rule, not corpus
enumeration):

* EQUIVALENCE DOMAIN — canonical spellings. For every spelling
  that IS its own canonical form, the gate's verdict equals the
  policy's "gate" tag, and oversight's verdict equals the
  policy's combined (gate or oversight) verdict. Pinned by
  EquivalenceDomainTests.

* DIVERGENCE TABLE — non-canonical spellings. Every other
  spelling in the corpus is classified into exactly one
  enumerated class (EXPECTED below), and the test rebuilds the
  table from live verdicts and asserts each row matches its
  recorded expectation. Any future change in the divergence
  shape — a gate fix, a policy change, a canonicaliser change —
  fails this suite loudly instead of silently moving the
  boundary.

* VERIFIER DEFENCE — the claim that matters operationally: no
  non-canonical spelling of a protected path can reach the gate
  through the verifier. trust/verifier_main._mode_gate
  canonicalises every changed_paths entry via the policy and
  refuses (malformed request, exit 2, unsigned) any entry whose
  canonical spelling differs from the spelling presented, plus
  any entry whose first component is not lowercase.
  VerifierDefenceTests assert that predicate in-process over the
  whole corpus, and VerifierSubprocessTests drive the REAL
  verifier subprocess (the tests/test_trust_verifier.py fixture
  pattern) for every non-canonical protected spelling.

Three verdicts per spelling:
  (a) gate:      bool(eval.gate.check_protected_paths([s]))
                 ("error" when the gate raises GateInputError)
  (b) policy:    trust.pathpolicy.classify(s) — canonical form
                 plus whether "gate" is in protected_by
  (c) oversight: oversight.approval.is_protected_path(
                     canonicalise_path(s)) when canonicalisable,
                 else "refused"
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval.gate as gate
import oversight.approval as oversight
from trust import pathpolicy

ZWSP = "eval/gate\u200b.py"          # zero-width space inside the name
BOM = "\ufeffeval/gate.py"           # byte-order mark before "eval"
CYRILLIC = "ev\u0430l/gate.py"       # Cyrillic а homoglyph for "a"
NUL = "eval/gate.py\x00"

# Divergence classes for NON-canonical spellings.
CANONICAL = "canonical"  # in the equivalence domain, not a divergence
GATE_MISS = "gate-miss"  # policy gate-protected; gate raw verdict misses
POLICY_CATCHES_OVERSIGHT = "policy-catches-oversight"
#   policy oversight-protected; the gate never protects oversight
#   scope at all (its list is eval/ + core/loop.py only)
GATE_CATCHES_ANYWAY = "gate-catches-anyway"
#   non-canonical, but the gate's prefix/strip rules still flag it
BOTH_REFUSE = "both-refuse"
#   uncanonicalisable: policy and oversight refuse the spelling
#   outright ([] from classify means "unclassifiable", never safe)
GATE_STRICTER = "gate-stricter"
#   gate flags a spelling whose canonical form is unprotected
AGREE_UNPROTECTED = "agree-unprotected-noncanonical"
#   canonicalisable, unprotected under every verdict; only the
#   spelling is non-canonical

# Corpus rows:
#   (spelling, expected class, expected canonical or None,
#    expected protected_by, expected raw gate verdict)
# Gate verdict is True/False, or "error" for GateInputError.
EXPECTED = [
    # --- Canonical spellings: the equivalence domain. -----------
    ("core/loop.py", CANONICAL, "core/loop.py", ["gate"], True),
    ("eval/gate.py", CANONICAL, "eval/gate.py", ["gate"], True),
    ("eval/registry.py", CANONICAL, "eval/registry.py",
     ["gate"], True),
    ("oversight/approval.py", CANONICAL, "oversight/approval.py",
     ["oversight"], False),
    ("oversight", CANONICAL, "oversight", ["oversight"], False),
    ("trust/ledger.py", CANONICAL, "trust/ledger.py", [], False),
    ("docs/ASI-MAP.md", CANONICAL, "docs/ASI-MAP.md", [], False),
    ("core/other.py", CANONICAL, "core/other.py", [], False),
    ("eval", CANONICAL, "eval", [], False),
    # Case variants are canonical spellings of DIFFERENT paths on
    # a case-sensitive filesystem; all three verdicts agree they
    # are unprotected (the verifier is stricter still — see the
    # proposal's remainder section).
    ("EVAL/gate.py", CANONICAL, "EVAL/gate.py", [], False),
    ("eval/GATE.py", CANONICAL, "eval/GATE.py", ["gate"], True),
    ("core/LOOP.py", CANONICAL, "core/LOOP.py", [], False),
    # Further case variants (Round C probes): canonical
    # spellings of different, unprotected paths; the verifier
    # still refuses them on its lowercase-first-component rule
    # (see VerifierDefenceTests).
    ("Eval/gate.py", CANONICAL, "Eval/gate.py", [], False),
    ("CORE/loop.py", CANONICAL, "CORE/loop.py", [], False),
    # Canonical spellings that merely resemble protected paths:
    # _derive_class returns CANONICAL for them (they ARE their
    # own canonical form), and semantically all three verdicts
    # agree they are unprotected — "evalx/..." does not start
    # with the "eval/" prefix, and neither ".bak" nor "/extra"
    # equals the exact file "core/loop.py". (Probed in Round C
    # under the "agree-unprotected" label; the harness class is
    # CANONICAL, not AGREE_UNPROTECTED, which is reserved for
    # NON-canonical spellings.)
    ("evalx/gate.py", CANONICAL, "evalx/gate.py", [], False),
    ("core/loop.py.bak", CANONICAL, "core/loop.py.bak", [], False),
    ("core/loop.py/extra", CANONICAL, "core/loop.py/extra",
     [], False),
    # Invisible/homoglyph spellings that ARE their own canonical
    # form (canonicalisation is byte-preserving here): distinct
    # paths, and the verdicts agree on each.
    (ZWSP, CANONICAL, ZWSP, ["gate"], True),
    (BOM, CANONICAL, BOM, [], False),
    (CYRILLIC, CANONICAL, CYRILLIC, [], False),
    # --- Gate misses: the exact-file check is brittle. ----------
    ("core//loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core/./loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core/loop.py/", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core/loop.py/.", GATE_MISS, "core/loop.py", ["gate"], False),
    # Round C probes: further spellings from the same open
    # family (repeated slashes, backslash separators, dot
    # components in any position, trailing slash/dot).
    ("core///loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core\\\\loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core\\./loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core/././loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core//.//loop.py", GATE_MISS, "core/loop.py", ["gate"], False),
    ("core/loop.py//.", GATE_MISS, "core/loop.py", ["gate"], False),
    # --- Oversight scope the gate does not carry at all. --------
    ("oversight/", POLICY_CATCHES_OVERSIGHT, "oversight",
     ["oversight"], False),
    ("oversight//approval.py", POLICY_CATCHES_OVERSIGHT,
     "oversight/approval.py", ["oversight"], False),
    ("oversight/approval.py/", POLICY_CATCHES_OVERSIGHT,
     "oversight/approval.py", ["oversight"], False),
    ("oversight/approval.py/.", POLICY_CATCHES_OVERSIGHT,
     "oversight/approval.py", ["oversight"], False),
    ("oversight/.", POLICY_CATCHES_OVERSIGHT, "oversight",
     ["oversight"], False),
    ("oversight//", POLICY_CATCHES_OVERSIGHT, "oversight",
     ["oversight"], False),
    # --- Non-canonical, but the gate catches them anyway. -------
    ("./core/loop.py", GATE_CATCHES_ANYWAY, "core/loop.py",
     ["gate"], True),
    ("core\\loop.py", GATE_CATCHES_ANYWAY, "core/loop.py",
     ["gate"], True),
    ("eval//gate.py", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("eval/./gate.py", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("eval/gate.py ", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    (" eval/gate.py", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("eval\\gate.py", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("./eval/gate.py", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("eval/gate.py/", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    ("eval/gate.py/.", GATE_CATCHES_ANYWAY, "eval/gate.py",
     ["gate"], True),
    # --- Uncanonicalisable: every consumer refuses. -------------
    ("eval/../eval/gate.py", BOTH_REFUSE, None, [], True),
    ("a/../../eval/gate.py", BOTH_REFUSE, None, [], False),
    ("/eval/gate.py", BOTH_REFUSE, None, [], False),
    ("C:/eval/gate.py", BOTH_REFUSE, None, [], False),
    ("oversight/../oversight/approval.py", BOTH_REFUSE,
     None, [], False),
    ("trust/../eval/gate.py", BOTH_REFUSE, None, [], False),
    (NUL, BOTH_REFUSE, None, [], True),
    ("eval/gate.py/..", BOTH_REFUSE, None, [], True),
    ("", BOTH_REFUSE, None, [], "error"),
    (".", BOTH_REFUSE, None, [], False),
    ("..", BOTH_REFUSE, None, [], False),
    # --- Gate stricter than the policy (a false positive). ------
    ("eval/", GATE_STRICTER, "eval", [], True),
    # --- Non-canonical spellings of unprotected paths. ----------
    ("....//eval/gate.py", AGREE_UNPROTECTED,
     "..../eval/gate.py", [], False),
    ("trust//ledger.py", AGREE_UNPROTECTED,
     "trust/ledger.py", [], False),
    ("./trust/ledger.py", AGREE_UNPROTECTED,
     "trust/ledger.py", [], False),
    ("trust/./ledger.py", AGREE_UNPROTECTED,
     "trust/ledger.py", [], False),
    ("trust/ledger.py/", AGREE_UNPROTECTED,
     "trust/ledger.py", [], False),
    ("docs//ASI-MAP.md", AGREE_UNPROTECTED,
     "docs/ASI-MAP.md", [], False),
    ("docs/./ASI-MAP.md", AGREE_UNPROTECTED,
     "docs/ASI-MAP.md", [], False),
    ("./docs/ASI-MAP.md", AGREE_UNPROTECTED,
     "docs/ASI-MAP.md", [], False),
]


def _gate_verdict(spelling):
    try:
        return bool(gate.check_protected_paths([spelling]))
    except gate.GateInputError:
        return "error"


def _oversight_verdict(spelling):
    """Oversight's verdict, or "refused" when uncanonicalisable."""
    try:
        canonical = oversight.canonicalise_path(spelling)
    except ValueError:
        return "refused"
    return oversight.is_protected_path(canonical)


def _derive_class(spelling):
    """Recompute a row's class from the three live verdicts."""
    result = pathpolicy.classify(spelling)
    if result["canonical_spelling"]:
        return CANONICAL
    if result["canonical"] is None:
        return BOTH_REFUSE
    gate_verdict = _gate_verdict(spelling)
    if "gate" in result["protected_by"]:
        return GATE_CATCHES_ANYWAY if gate_verdict is True \
            else GATE_MISS
    if "oversight" in result["protected_by"]:
        return POLICY_CATCHES_OVERSIGHT
    if gate_verdict is True:
        return GATE_STRICTER
    return AGREE_UNPROTECTED


def _verifier_accepts_spelling(spelling):
    """The exact predicate trust/verifier_main._mode_gate applies
    to each changed_paths entry: policy-canonicalisable, already
    its canonical spelling, and a lowercase first component."""
    if not isinstance(spelling, str):
        return False
    try:
        canonical = pathpolicy.canonicalise(spelling)
    except ValueError:
        return False
    if canonical != spelling:
        return False
    first = spelling.split("/", 1)[0]
    return first == first.lower()


# Spellings of protected paths that are NOT canonical: canonical-
# isable ones whose canonical form is protected, plus the
# uncanonicalisable ones that name a protected target through
# "..", an absolute/drive prefix or a NUL byte.
NONCANONICAL_PROTECTED = [
    spelling for spelling, klass, _c, _p, _g in EXPECTED
    if klass in (GATE_MISS, POLICY_CATCHES_OVERSIGHT,
                 GATE_CATCHES_ANYWAY)
] + [
    "eval/../eval/gate.py", "a/../../eval/gate.py",
    "/eval/gate.py", "C:/eval/gate.py",
    "oversight/../oversight/approval.py",
    "trust/../eval/gate.py", NUL, "eval/gate.py/..",
]


class EquivalenceDomainTests(unittest.TestCase):
    """(i) On canonical spellings the three verdicts agree with
    the policy exactly — this is the demonstrated equivalence
    domain of path-policy/1 today."""

    def test_corpus_has_canonical_rows(self):
        canonical_rows = [r for r in EXPECTED if r[1] == CANONICAL]
        self.assertGreaterEqual(len(canonical_rows), 10)

    def test_gate_agrees_with_policy_on_canonical_spellings(self):
        for spelling, _k, _c, _p, _g in EXPECTED:
            result = pathpolicy.classify(spelling)
            if not result["canonical_spelling"]:
                continue
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    _gate_verdict(spelling),
                    "gate" in result["protected_by"])

    def test_oversight_agrees_with_policy_on_canonical(self):
        for spelling, _k, _c, _p, _g in EXPECTED:
            result = pathpolicy.classify(spelling)
            if not result["canonical_spelling"]:
                continue
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    _oversight_verdict(spelling),
                    bool(result["protected_by"]))

    def test_policy_agrees_with_oversight_canonicaliser(self):
        # The policy delegates spelling rules to oversight's
        # canonicaliser; on canonicalisable spellings they must
        # produce the identical canonical form.
        for spelling, _k, canonical, _p, _g in EXPECTED:
            if canonical is None:
                continue
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    oversight.canonicalise_path(spelling), canonical)
                self.assertEqual(
                    pathpolicy.canonicalise(spelling), canonical)


class DivergenceTableTests(unittest.TestCase):
    """(ii) Every non-canonical spelling sits in exactly the
    recorded divergence class; the table is rebuilt from live
    verdicts, so any change in divergence shape fails loudly."""

    def test_every_row_matches_recorded_expectation(self):
        for spelling, klass, canonical, protected_by, gv in EXPECTED:
            with self.subTest(spelling=spelling):
                result = pathpolicy.classify(spelling)
                self.assertEqual(result["canonical"], canonical)
                self.assertEqual(result["protected_by"], protected_by)
                self.assertEqual(result["canonical_spelling"],
                                 klass == CANONICAL)
                self.assertEqual(_gate_verdict(spelling), gv)
                self.assertEqual(_derive_class(spelling), klass)

    def test_oversight_verdicts_across_the_table(self):
        for spelling, _k, canonical, protected_by, _g in EXPECTED:
            with self.subTest(spelling=spelling):
                if canonical is None:
                    self.assertEqual(
                        _oversight_verdict(spelling), "refused")
                else:
                    self.assertEqual(
                        _oversight_verdict(spelling),
                        bool(protected_by))

    def test_gate_miss_list_within_corpus_is_exactly_these(self):
        # Bounded to the corpus: gate-miss is an open family
        # (any separator/dot-component perturbation of the
        # exact-file entry core/loop.py), NOT exhausted by the
        # spellings below; the bound that protects production
        # is the verifier's canonical-only rule.
        misses = [s for s, k, _c, _p, _g in EXPECTED if k == GATE_MISS]
        self.assertEqual(
            sorted(misses),
            sorted(["core//loop.py", "core/./loop.py",
                    "core/loop.py/", "core/loop.py/.",
                    "core///loop.py", "core\\\\loop.py",
                    "core\\./loop.py", "core/././loop.py",
                    "core//.//loop.py", "core/loop.py//."]))
        for spelling in misses:
            with self.subTest(spelling=spelling):
                # The miss is real: raw gate verdict is a pass,
                # the policy (on the canonical spelling) flags it.
                self.assertEqual(gate.check_protected_paths(
                    [spelling]), ())
                self.assertEqual(
                    pathpolicy.classify(spelling)["protected_by"],
                    ["gate"])

    def test_class_counts(self):
        counts = {}
        for _s, klass, _c, _p, _g in EXPECTED:
            counts[klass] = counts.get(klass, 0) + 1
        self.assertEqual(counts, {
            CANONICAL: 20,
            GATE_MISS: 10,
            POLICY_CATCHES_OVERSIGHT: 6,
            GATE_CATCHES_ANYWAY: 10,
            BOTH_REFUSE: 11,
            GATE_STRICTER: 1,
            AGREE_UNPROTECTED: 8,
        })
        self.assertEqual(len(EXPECTED), 66)


class VerifierDefenceTests(unittest.TestCase):
    """(iii, in-process) The verifier's gate path refuses every
    non-canonical spelling of a protected path as malformed, so
    the gate-miss class above is unreachable through the
    verifier — the only production path that signs gate
    decisions."""

    def test_verifier_refuses_every_noncanonical_protected(self):
        self.assertEqual(len(NONCANONICAL_PROTECTED), 34)
        for spelling in NONCANONICAL_PROTECTED:
            with self.subTest(spelling=spelling):
                self.assertFalse(_verifier_accepts_spelling(spelling))

    def test_verifier_refuses_every_noncanonical_spelling_at_all(self):
        # Stronger than the protected claim: the verifier accepts
        # ONLY canonical spellings, protected or not.
        for spelling, klass, _c, _p, _g in EXPECTED:
            if klass == CANONICAL:
                continue
            with self.subTest(spelling=spelling):
                self.assertFalse(_verifier_accepts_spelling(spelling))

    def test_verifier_accepts_canonical_spellings(self):
        for spelling, klass, _c, _p, _g in EXPECTED:
            if klass != CANONICAL:
                continue
            with self.subTest(spelling=spelling):
                # Canonical spellings whose first component is
                # not lowercase ("EVAL/gate.py", "Eval/gate.py",
                # "CORE/loop.py") are the ones the verifier still
                # refuses: its lowercase-first-component rule is
                # a verifier-local strictness on top of the
                # policy (see the proposal).
                first = spelling.split("/", 1)[0]
                self.assertEqual(
                    _verifier_accepts_spelling(spelling),
                    first == first.lower())


class VerifierSubprocessTests(unittest.TestCase):
    """(iii, end-to-end) The same claim driven through the REAL
    verifier subprocess, reusing the fixture pattern of
    tests/test_trust_verifier.py: each non-canonical protected
    spelling is a protocol error (unsigned refusal), never a
    signed decision; a canonical protected spelling reaches the
    gate and comes back as a signed rejection."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        from datetime import datetime, timedelta, timezone

        from eval.registry import EvalRegistry
        from signing import generate_key_file
        from trust.client import VerifierClient

        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        base.chmod(0o700)
        home = base / "verifier-home"
        home.mkdir()
        home.chmod(0o700)
        cls._key = generate_key_file(home / "gate.key")
        registry_dir = base / "registry"
        registry = EvalRegistry(registry_dir)
        items = [("sealed-1", "algebra", "2+2?", "4"),
                 ("sealed-2", "algebra", "3*3?", "9"),
                 ("sealed-3", "geo", "pi~?", "3.14")]
        for item_id, domain, prompt, expected in items:
            registry.add_sealed_item(item_id, domain, prompt,
                                     expected, "test-actor")
        cls._manifest_hash = registry.sealed_manifest_hash(
            "verifier-actor")
        cls._recent = (datetime.now(timezone.utc)
                       - timedelta(minutes=5)).isoformat()
        env = {
            "AION_VERIFIER_KEY_PATH": str(home / "gate.key"),
            "AION_VERIFIER_SIGNER_ID": "verifier-svc",
            "AION_VERIFIER_ACTOR_ID": "verifier-actor",
            "AION_REGISTRY_DIR": str(registry_dir),
            "AION_VERIFIER_HOME": str(home / "ledger"),
            "AION_DEPLOYMENT_MODE": "research",
        }
        cls._client = VerifierClient(
            verifier_env=env, expected_signer_id="verifier-svc",
            expected_key_id=cls._key.key_id)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _gate_body(self, changed_paths):
        return {
            "proposal_id": "prop-diff",
            "builder_ids": ["seat-9", "seat-10", "seat-11"],
            "reviewer_ids": ["seat-1", "seat-2", "seat-3",
                             "seat-4", "seat-5", "seat-6"],
            "baseline_public": {"bench-a": 0.5},
            "candidate_public": {"bench-a": 0.6},
            "baseline_sealed": {"bench-s": 0.5},
            "candidate_sealed": {"bench-s": 0.7},
            "capability_baseline": {"cap-a": 0.5},
            "capability_candidate": {"cap-a": 0.5},
            "attestation": {
                "verifier_id": "seat-3", "decision": "approve",
                "sealed_hash": self._manifest_hash,
                "reward_hacking_checked": True,
                "evidence_ref": "sealed-run-1",
                "attested_at": self._recent},
            "changed_paths": changed_paths,
            "verifier_note": "",
        }

    def test_noncanonical_protected_spellings_refused_unsigned(self):
        from trust.errors import VerifierProtocolError
        for spelling in NONCANONICAL_PROTECTED:
            with self.subTest(spelling=spelling):
                with self.assertRaises(VerifierProtocolError):
                    self._client.gate(
                        self._gate_body([spelling]))

    def test_canonical_protected_spelling_reaches_gate(self):
        outcome = self._client.gate(self._gate_body(["eval/gate.py"]))
        self.assertFalse(outcome.accepted)
        self.assertTrue(outcome.envelope.decision.protected_violations)


if __name__ == "__main__":
    unittest.main()
