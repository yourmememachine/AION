"""Static deploy tests for deploy/verifier-identity/.

FINDING-1 (war room): the verifier's budget variables
AION_VERIFIER_PROPOSAL_BUDGET / AION_VERIFIER_IDENTITY_BUDGET
were missing from run-verifier.sh's ALLOWED_KEYS allowlist and
from setup.sh's verifier.env template — an operator setting
them made the wrapper hard-fail, and otherwise the budgets
silently ran at compiled defaults in deployment. These tests
pin the general invariant, not just the two keys: every env
variable trust/verifier_main.py reads must be allowlisted by
the wrapper, and every key in the setup.sh template must be
allowlisted too (a template key the wrapper rejects would make
a fresh deployment unlaunchable).

No root, no live system: the scripts are only parsed / syntax
checked, never executed.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy" / "verifier-identity"
RUN_VERIFIER = DEPLOY / "run-verifier.sh"
SETUP = DEPLOY / "setup.sh"


def _allowed_keys():
    text = RUN_VERIFIER.read_text()
    block = re.search(r"ALLOWED_KEYS=\((.*?)\)", text, re.S).group(1)
    return set(re.findall(r"[A-Z][A-Z_]+", block))


def _template_env():
    """{key: value} from the verifier.env heredoc in setup.sh."""
    text = SETUP.read_text()
    block = re.search(r"<<'EOF'\n(.*?)EOF", text, re.S).group(1)
    env = {}
    for line in block.splitlines():
        match = re.match(r"([A-Z][A-Z_]*)=(.*)$", line)
        if match:
            env[match.group(1)] = match.group(2)
    return env


class DeployScriptTests(unittest.TestCase):
    def test_scripts_parse_as_bash(self):
        for script in (RUN_VERIFIER, SETUP):
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                             msg=f"{script}: {result.stderr}")

    def test_budget_keys_allowlisted(self):
        allowed = _allowed_keys()
        self.assertIn("AION_VERIFIER_PROPOSAL_BUDGET", allowed)
        self.assertIn("AION_VERIFIER_IDENTITY_BUDGET", allowed)

    def test_ceremony_evidence_dir_key_allowlisted(self):
        self.assertIn("AION_CEREMONY_EVIDENCE_DIR", _allowed_keys())

    def test_ceremony_signing_seed_path_key_allowlisted(self):
        self.assertIn("AION_CEREMONY_SIGNING_SEED_PATH",
                      _allowed_keys())

    def test_ceremony_operators_key_allowlisted(self):
        # Cycle 19: AION_CEREMONY_OPERATORS is read by
        # trust/verifier_main.py, so the wrapper must allowlist
        # it — the invariant test below covers it too, but this
        # names the key the way test_budget_keys_allowlisted
        # names the budget keys.
        self.assertIn("AION_CEREMONY_OPERATORS", _allowed_keys())

    def test_health_check_allowlist_matches_wrapper(self):
        # Cycle 19 drift pin (critique-b missed item):
        # health_check.py's ALLOWED_KEYS is a literal COPY of the
        # wrapper's allowlist, not parsed from it, so it silently
        # drifts when the wrapper gains a name. Pin the copy to
        # the wrapper at test time.
        text = (DEPLOY / "health_check.py").read_text()
        block = re.search(r"ALLOWED_KEYS = \((.*?)\)", text,
                          re.S).group(1)
        health_keys = set(re.findall(r"[A-Z][A-Z_]+", block))
        self.assertEqual(health_keys, _allowed_keys())
        self.assertEqual(len(health_keys), 19)

    def test_every_verifier_main_env_var_is_allowlisted(self):
        main_text = (REPO / "trust" / "verifier_main.py").read_text()
        read_vars = set(re.findall(r"AION_[A-Z_]+", main_text))
        self.assertTrue(read_vars)  # the extraction found something
        self.assertLessEqual(read_vars, _allowed_keys())

    def test_template_keys_all_allowlisted(self):
        self.assertLessEqual(set(_template_env()), _allowed_keys())

    def test_template_keys_equal_allowlist(self):
        # Completeness direction of the pin above: the template
        # must not OMIT an allowlisted key either — a key the
        # wrapper allows but setup.sh never writes (e.g.
        # AION_CEREMONY_OPERATORS) would leave a fresh deployment
        # silently unconfigured for that feature.
        self.assertEqual(set(_template_env()), _allowed_keys())

    def test_template_shows_compiled_budget_defaults(self):
        # trust/verifier_main.py documents defaults 25 / 500; the
        # template must show exactly those, so the deployed value
        # is the reviewed value.
        env = _template_env()
        self.assertEqual(env.get("AION_VERIFIER_PROPOSAL_BUDGET"),
                         "25")
        self.assertEqual(env.get("AION_VERIFIER_IDENTITY_BUDGET"),
                         "500")

    def test_setup_converges_existing_user(self):
        # A pre-existing aion-verifier user must be converged to
        # the nologin shell and verifier home on re-run, not kept
        # as-is.
        text = SETUP.read_text()
        self.assertIn("usermod", text)
        self.assertIn('--shell "${NOLOGIN}"', text)
        self.assertIn('--home "${BASE}/home"', text)


if __name__ == "__main__":
    unittest.main()
