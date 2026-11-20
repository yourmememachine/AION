"""The versioned path policy, path-policy/1 (Trust Boundary
v2, item 6) — consumed by the build manifest and by the
verifier; the gate has NOT adopted it, and that adoption is
pending Dilip's approval of the Protected Gate Rule proposal
(internal/PROTECTED-GATE-PROPOSAL.md). It is not a universal
policy: see the adoption-status section below for exactly who
consumes it and who does not.

Path canonicalisation drift between the verifier, the gate, the
oversight workflow and the build manifest was a cycle-8
cross-check finding (F8): the gate's protected-path check matches
literal spellings (its _normalise_path strips a leading "./" and
translates backslashes, nothing more), so "core//loop.py" or
"core/./loop.py" slip the gate's exact-file check while
oversight's canonicalised check catches them, and the verifier
had to grow a canonical-spelling workaround in _mode_gate to
compensate. This module is the policy the manifest and the
verifier share (the gate does not consume it — see below):

* Spelling rules come from ONE source:
  oversight.approval.canonicalise_path. canonicalise() below
  delegates to it and adds nothing — strip, backslash
  translation, ""/"." components dropped, ".." refused, absolute
  and drive paths refused, empty refused.
* The protected lists are MIRRORS, copied by reading the source
  modules (see the provenance comments on each constant), not
  imported from them. That is deliberate: tests/
  test_trust_pathpolicy.py compares the mirrors against the live
  modules behaviourally and by constant, so if eval/gate.py's or
  oversight/approval.py's lists ever change without this policy
  following, the drift-detector tests fail loudly instead of the
  policy silently following (importing would make the mirror
  vacuous) or silently diverging (no test would notice).

Adoption status, stated plainly (the documented remainder, not
a silent gap):

* trust/manifest.py consumes this policy inside its own stricter
  canonicalise_path (it additionally refuses spellings the policy
  canonicalises — backslashes, "//", "./", trailing "/" — because
  a manifest must name one spelling per file, not accept several).
* trust/verifier_main.py consumes this policy: its _mode_gate
  canonicalises every gate changed_paths entry via
  trust.pathpolicy.canonicalise and refuses any entry whose
  canonical spelling differs from the spelling presented (the
  verifier additionally demands a lowercase first component, a
  verifier-local strictness on top of this policy). The gate is
  therefore only ever fed canonical spellings by the verifier.
* trust/shipcheck.py consumes this policy only TRANSITIVELY: it
  imports nothing from here; it rebuilds/verifies the build
  manifest (whose own canonicalise_path consumes the policy, see
  above) and checks the signed gate decision bound to that
  manifest, so policy-canonical paths reach it through the
  manifest, not through a direct call.
* eval/gate.py does NOT consume this policy — that adoption has
  NOT happened and remains for a Protected Gate Rule proposal.
  eval/ is a protected path: changing the gate to canonicalise
  before checking requires Dilip's Protected Gate Rule approval
  (the dual-leg oversight workflow). Until then the policy
  MIRRORS the gate under drift detection, and callers that feed
  paths to the gate must canonicalise first (as the verifier
  does) — the gate fed a raw non-canonical spelling can still
  miss a protected file, e.g. check_protected_paths(
  ["core//loop.py"]) returns () while classify("core//loop.py")
  reports it gate-protected. The drift-corpus tests pin exactly
  this divergence so it is a known, watched remainder, not a
  discovered-later surprise.

One classification caveat every consumer must honour:
classify() returns protected_by=[] for spellings that cannot be
canonicalised at all (absolute, escaping "..", empty). There []
means "unclassifiable", NEVER "safe": an uncanonicalisable
spelling is suspect by definition, and consumers must treat it
as a refusal, not as an unprotected path that may proceed.
"""

from __future__ import annotations

from oversight.approval import canonicalise_path as _oversight_canonicalise

POLICY_VERSION = "path-policy/1"

# --- Mirrored protected lists (provenance: read from source) ------
#
# eval/gate.py, module level:
#     PROTECTED_PREFIXES = ("eval/",)
#     PROTECTED_FILES = ("core/loop.py",)
# enforced by eval.gate.check_protected_paths over its own
# _normalise_path spelling (see the module docstring above for
# why the mirror is applied to the CANONICAL spelling here).
GATE_PROTECTED_PREFIXES = ("eval/",)
GATE_PROTECTED_FILES = frozenset({"core/loop.py"})

# oversight/approval.py, module level:
#     LOCAL_PROTECTED_PREFIXES = ("oversight/",)
#     LOCAL_PROTECTED_FILES = ("oversight",)
# enforced by oversight.approval.is_protected_path over an
# already-canonical path, which ALSO returns True for anything
# the gate protects (it delegates to check_protected_paths) and
# for any path whose first component is "oversight" (subsumed by
# the prefix + bare-file entries above for canonical spellings).
# "Oversight-protected" in this policy means oversight's OWN local
# list; classify() reports gate hits separately, and
# is_protected_path agreement with oversight is: oversight's
# verdict == ("gate" in protected_by or "oversight" in
# protected_by). The drift tests assert exactly that.
OVERSIGHT_PROTECTED_PREFIXES = ("oversight/",)
OVERSIGHT_PROTECTED_FILES = frozenset({"oversight"})


def canonicalise(path) -> str:
    """The policy's canonical spelling for a repo-relative path,
    or the refusal oversight.approval.canonicalise_path raises
    (ApprovalError, a ValueError). Single source of spelling
    rules: this function delegates and adds nothing."""
    return _oversight_canonicalise(path)


def _gate_protected(canonical: str) -> bool:
    return canonical in GATE_PROTECTED_FILES or any(
        canonical.startswith(prefix) for prefix in GATE_PROTECTED_PREFIXES)


def _oversight_protected(canonical: str) -> bool:
    return canonical in OVERSIGHT_PROTECTED_FILES or any(
        canonical.startswith(prefix)
        for prefix in OVERSIGHT_PROTECTED_PREFIXES)


def classify(path) -> dict:
    """Classify one path spelling under the policy.

    Returns {"canonical": str | None, "protected_by": sorted
    subset of ["gate", "oversight"], "canonical_spelling": bool}.
    "canonical" is None when the spelling cannot be canonicalised
    at all (absolute, escaping "..", empty): such paths are
    refused by every consumer, and protected_by is [] for them —
    [] there means "unclassifiable", never "safe to accept";
    callers must canonicalise first and treat a refusal as a
    refusal. "canonical_spelling" is True only when the input
    already IS its canonical spelling, byte for byte. Note the
    verifier's _mode_gate additionally demands a lowercase first
    component; that is a verifier-local strictness on top of this
    policy (the policy is case-preserving because both source
    lists are case-sensitive: "EVAL/gate.py" is a different path
    from "eval/gate.py" on a case-sensitive filesystem).
    """
    try:
        canonical = canonicalise(path)
    except (ValueError, TypeError):
        return {"canonical": None, "protected_by": [],
                "canonical_spelling": False}
    protected_by = []
    if _gate_protected(canonical):
        protected_by.append("gate")
    if _oversight_protected(canonical):
        protected_by.append("oversight")
    return {"canonical": canonical,
            "protected_by": sorted(protected_by),
            "canonical_spelling": canonical == path}


def is_protected(path) -> bool:
    """True when the path is protected by either list (gate or
    oversight), judged on its canonical spelling. Raises the
    canonicalisation refusal for spellings that cannot be
    canonicalised: an uncanonicalisable path is refused, not
    "unprotected"."""
    canonical = canonicalise(path)
    return _gate_protected(canonical) or _oversight_protected(canonical)
