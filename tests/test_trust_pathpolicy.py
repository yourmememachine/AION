"""Drift-detector tests for trust.pathpolicy (Trust Boundary v2,
item 6).

The policy MIRRORS eval/gate.py's and oversight/approval.py's
protected lists instead of importing them, so these tests compare
the mirror against the live modules — by constant and by
behaviour over a corpus of path spellings. If either source
module's list changes without trust/pathpolicy.py following,
this suite fails loudly. That failure is the point.

The corpus formerly also pinned a known divergence: the gate
fed a RAW non-canonical spelling could miss a protected file,
while the policy — judging the canonical spelling — caught it.
That divergence is CLOSED: in cycle 13, under Dilip's approval
of the Protected Gate proposal, eval/gate.py adopted the policy
(its check_protected_paths now judges the canonical spelling
and raises GateInputError for spellings that cannot be
canonicalised). The corpus asserts agreement with the gate's
verdict on the CANONICAL spelling, and AdoptionTests below
record the adopted behaviour on raw spellings — the divergence
is recorded as closed here, not silently edited away.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval.gate as gate
import oversight.approval as oversight
from trust import pathpolicy
from trust.manifest import ManifestError
from trust.manifest import canonicalise_path as manifest_canonicalise

# Corpus entries:
#   (raw spelling,
#    expected canonical spelling or None when uncanonicalisable,
#    expected protected_by,
#    manifest behaviour: "same" = manifest canonicalises to the
#    same spelling, "refuses" = manifest refuses the spelling
#    outright (its one-spelling-per-file strictness), "policy-only"
#    = entry is not used for the manifest comparison)
CORPUS = [
    # Canonical spellings.
    ("eval/gate.py", "eval/gate.py", ["gate"], "same"),
    ("eval/registry.py", "eval/registry.py", ["gate"], "same"),
    ("core/loop.py", "core/loop.py", ["gate"], "same"),
    ("oversight/approval.py", "oversight/approval.py",
     ["oversight"], "same"),
    ("oversight", "oversight", ["oversight"], "same"),
    ("core/other.py", "core/other.py", [], "same"),
    ("trust/manifest.py", "trust/manifest.py", [], "same"),
    ("machine/notes.md", "machine/notes.md", [], "same"),
    # Case variants: both source lists are case-sensitive, so an
    # uppercase spelling is a different (unprotected) path.
    ("EVAL/gate.py", "EVAL/gate.py", [], "same"),
    ("Eval/gate.py", "Eval/gate.py", [], "same"),
    ("CORE/LOOP.PY", "CORE/LOOP.PY", [], "same"),
    ("Oversight/approval.py", "Oversight/approval.py", [], "same"),
    # Non-canonical spellings the policy canonicalises; the
    # manifest refuses these spellings outright.
    ("./eval/gate.py", "eval/gate.py", ["gate"], "refuses"),
    ("eval//gate.py", "eval/gate.py", ["gate"], "refuses"),
    ("eval/./gate.py", "eval/gate.py", ["gate"], "refuses"),
    ("eval/gate.py/", "eval/gate.py", ["gate"], "refuses"),
    ("eval\\gate.py", "eval/gate.py", ["gate"], "refuses"),
    ("core//loop.py", "core/loop.py", ["gate"], "refuses"),
    ("core/./loop.py", "core/loop.py", ["gate"], "refuses"),
    ("./core/loop.py", "core/loop.py", ["gate"], "refuses"),
    ("oversight//approval.py", "oversight/approval.py",
     ["oversight"], "refuses"),
    ("oversight/./approval.py", "oversight/approval.py",
     ["oversight"], "refuses"),
    ("core//other.py", "core/other.py", [], "refuses"),
    # Prefix lookalikes that are NOT protected: the prefixes end
    # in "/", and the bare gate file match is exact.
    ("evaluate/gate.py", "evaluate/gate.py", [], "same"),
    ("evalx", "evalx", [], "same"),
    ("core/loop.py.bak", "core/loop.py.bak", [], "same"),
    ("core/loop2.py", "core/loop2.py", [], "same"),
    ("myoversight/approval.py", "myoversight/approval.py", [], "same"),
    # Uncanonicalisable spellings: refused by the policy, the
    # oversight canonicaliser and the manifest alike.
    ("../eval/gate.py", None, [], "refuses"),
    ("eval/../eval/gate.py", None, [], "refuses"),
    ("..", None, [], "refuses"),
    ("/eval/gate.py", None, [], "refuses"),
    ("//eval/gate.py", None, [], "refuses"),
    ("", None, [], "refuses"),
    (".", None, [], "refuses"),
    ("./", None, [], "refuses"),
]


class MirrorConstantTests(unittest.TestCase):
    """The loudest drift detector: the mirrored constants must
    equal the live modules' constants, exactly."""

    def test_gate_mirror_matches_live_gate(self):
        self.assertEqual(pathpolicy.GATE_PROTECTED_PREFIXES,
                         gate.PROTECTED_PREFIXES)
        self.assertEqual(pathpolicy.GATE_PROTECTED_FILES,
                         frozenset(gate.PROTECTED_FILES))

    def test_oversight_mirror_matches_live_oversight(self):
        self.assertEqual(pathpolicy.OVERSIGHT_PROTECTED_PREFIXES,
                         oversight.LOCAL_PROTECTED_PREFIXES)
        self.assertEqual(pathpolicy.OVERSIGHT_PROTECTED_FILES,
                         frozenset(oversight.LOCAL_PROTECTED_FILES))

    def test_policy_version(self):
        self.assertEqual(pathpolicy.POLICY_VERSION, "path-policy/1")


class CorpusAgreementTests(unittest.TestCase):
    def test_classify_matches_expectations(self):
        for raw, canonical, protected_by, _ in CORPUS:
            with self.subTest(raw=raw):
                result = pathpolicy.classify(raw)
                self.assertEqual(result["canonical"], canonical)
                self.assertEqual(result["protected_by"], protected_by)
                self.assertEqual(result["canonical_spelling"],
                                 canonical is not None
                                 and canonical == raw)

    def test_agrees_with_gate_on_canonical_spelling(self):
        for raw, canonical, protected_by, _ in CORPUS:
            if canonical is None:
                continue
            with self.subTest(raw=raw):
                gate_verdict = bool(gate.check_protected_paths([canonical]))
                self.assertEqual(gate_verdict, "gate" in protected_by)

    def test_agrees_with_oversight_canonicalised_check(self):
        for raw, canonical, protected_by, _ in CORPUS:
            with self.subTest(raw=raw):
                if canonical is None:
                    with self.assertRaises(ValueError):
                        oversight.canonicalise_path(raw)
                    continue
                self.assertEqual(oversight.canonicalise_path(raw),
                                 canonical)
                oversight_verdict = oversight.is_protected_path(canonical)
                self.assertEqual(
                    oversight_verdict,
                    "gate" in protected_by or "oversight" in protected_by)
                # Oversight's OWN list, isolated: its verdict minus
                # the gate's verdict must match the policy's
                # "oversight" tag on every corpus entry where the
                # two lists do not overlap (they never overlap:
                # disjoint prefixes/files).
                gate_verdict = bool(gate.check_protected_paths([canonical]))
                self.assertEqual(oversight_verdict and not gate_verdict,
                                 "oversight" in protected_by)

    def test_is_protected_matches_classify(self):
        for raw, canonical, protected_by, _ in CORPUS:
            with self.subTest(raw=raw):
                if canonical is None:
                    with self.assertRaises(ValueError):
                        pathpolicy.is_protected(raw)
                else:
                    self.assertEqual(pathpolicy.is_protected(raw),
                                     bool(protected_by))

    def test_manifest_agrees_where_applicable(self):
        for raw, canonical, _, manifest_behaviour in CORPUS:
            if manifest_behaviour == "policy-only":
                continue
            with self.subTest(raw=raw):
                if manifest_behaviour == "same":
                    self.assertEqual(manifest_canonicalise(raw), canonical)
                    self.assertEqual(canonical, raw)
                else:  # "refuses": stricter one-spelling rule
                    with self.assertRaises(ManifestError):
                        manifest_canonicalise(raw)


class AdoptionTests(unittest.TestCase):
    """Pin the ADOPTED behaviour (cycle 13, Dilip's approval of
    the Protected Gate proposal): the gate now judges the
    canonical spelling via path-policy/1, so its verdict on a
    RAW non-canonical spelling agrees with the policy's "gate"
    tag. These tests replace the former KnownDivergenceTests,
    which pinned the now-closed divergence (the gate missing
    "core//loop.py" / "core/./loop.py" on the raw spelling);
    the divergence is closed, and this class is the record of
    that closure. If the gate ever regresses to judging raw
    spellings, these assertions fail — the drift detector doing
    its job in the other direction."""

    def test_gate_raw_spelling_now_catches_what_policy_catches(self):
        for raw in ("core//loop.py", "core/./loop.py"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    gate.check_protected_paths([raw]),
                    ("core/loop.py",))
                self.assertEqual(
                    pathpolicy.classify(raw)["protected_by"], ["gate"])
                # Agreement, stated directly: the gate's verdict
                # on the raw spelling equals the policy's gate
                # tag on that same spelling.
                self.assertEqual(
                    bool(gate.check_protected_paths([raw])),
                    "gate" in pathpolicy.classify(raw)["protected_by"])

    def test_gate_raw_spelling_still_catches_prefix_cases(self):
        # The prefix cases were caught before adoption and are
        # still caught after it — now by canonicalisation rather
        # than by the gate's former prefix/strip rules. Offenders
        # are reported as their canonical spelling.
        for raw in ("./eval/gate.py", "eval//gate.py", "eval\\gate.py"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    gate.check_protected_paths([raw]),
                    ("eval/gate.py",))

    def test_gate_uncanonicalisable_spelling_is_an_error(self):
        # Adoption's other half: a spelling with no canonical
        # form is a GateInputError (a refusal), never a pass.
        # (Kept separate from the agreement pins above because
        # the policy classifies such spellings as unclassifiable,
        # not as unprotected.)
        with self.assertRaises(gate.GateInputError):
            gate.check_protected_paths(["a/../../eval/gate.py"])


if __name__ == "__main__":
    unittest.main()
