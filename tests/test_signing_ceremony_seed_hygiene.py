"""Loader-level seed hygiene tests (cycle 21, R9).

Covers the cycle-21 loader changes that the existing loader
tests in test_signing_ceremony_authorisation.py /
test_signing_gate_decision.py do not pin:

* the shared owner-only permission predicate (no special
  bits, no group/world bits, owner-read set — literally
  {0400, 0600}) on BOTH loaders: 0400 and 0600 accepted;
  0640 / 0644 / 0660 refused; 0200 (no owner-read) refused;
  04600 (setuid) / 01600 (sticky) refused;
* the ceremony seed loader's fd discipline: a FIFO at the path
  is refused promptly (O_NOFOLLOW|O_NONBLOCK + fstat S_ISREG —
  no hang), a directory is refused, a symlink is refused
  (existing behaviour, pinned here at loader level);
* the seed loader's owner-uid check: refused when the file's
  owner differs from the process euid (non-root). The refusal
  case is exercised by patching os.geteuid so it runs even
  under a root test harness; the real-euid case skips when
  running as root, where the check is vacuous by design.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing.ceremony_authorisation import (
    generate_ceremony_key_file,
    load_ceremony_seed,
)
from signing.gate_decision import (
    SigningError,
    generate_key_file,
    load_signing_key,
)

def _write(path: Path, hex_text: str, mode: int) -> Path:
    path.write_text(hex_text + "\n", encoding="ascii")
    os.chmod(path, mode)
    return path


class CeremonySeedPermissionTests(unittest.TestCase):
    def _seed_path(self, tmp, mode):
        # A seed value that loads cleanly when permissions allow:
        # 32 bytes of 0x11 (not in REFUSED_TEST_SEEDS — that set is
        # enforced by the verifier config, not by this loader).
        return _write(Path(tmp) / "ceremony.seed", "11" * 32, mode)

    def test_0400_and_0600_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in (0o400, 0o600):
                loaded = load_ceremony_seed(self._seed_path(tmp, mode))
                self.assertEqual(loaded.seed, b"\x11" * 32)

    def test_group_or_world_bits_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in (0o640, 0o644, 0o660, 0o604, 0o777):
                with self.assertRaises(SigningError, msg=oct(mode)):
                    load_ceremony_seed(self._seed_path(tmp, mode))

    def test_write_only_0200_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SigningError):
                load_ceremony_seed(self._seed_path(tmp, 0o200))

    def test_special_bits_refused(self):
        # LOW-1: setuid (04600) and sticky (01600) variants
        # carry no group/world bits and are owner-readable, so
        # they passed the permission-bit checks before the
        # helper refused special bits explicitly; the accepted
        # set is literally {0400, 0600}. Setgid (02600) pinned
        # alongside for completeness.
        with tempfile.TemporaryDirectory() as tmp:
            for mode in (0o4600, 0o1600, 0o2600):
                with self.assertRaises(SigningError, msg=oct(mode)):
                    load_ceremony_seed(self._seed_path(tmp, mode))


class CeremonySeedFdDisciplineTests(unittest.TestCase):
    def test_fifo_refused_without_hanging(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "ceremony.seed"
            os.mkfifo(fifo)
            outcome = {}

            def attempt():
                try:
                    load_ceremony_seed(fifo)
                    outcome["result"] = "loaded"
                except SigningError:
                    outcome["result"] = "refused"
                except BaseException as exc:  # noqa: BLE001 - recorded
                    outcome["result"] = f"other: {exc!r}"

            thread = threading.Thread(target=attempt, daemon=True)
            thread.start()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(),
                             "seed loader hung on a FIFO")
            self.assertEqual(outcome.get("result"), "refused")

    def test_directory_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "ceremony.seed"
            directory.mkdir()
            os.chmod(directory, 0o700)
            with self.assertRaises(SigningError):
                load_ceremony_seed(directory)

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real.seed"
            made = generate_ceremony_key_file(real)
            link = Path(tmp) / "link.seed"
            link.symlink_to(real)
            with self.assertRaises(SigningError):
                load_ceremony_seed(link)
            self.assertEqual(load_ceremony_seed(real), made)

    def test_generated_seed_still_0600_and_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ceremony.seed"
            made = generate_ceremony_key_file(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_ceremony_seed(path), made)


class CeremonySeedUidTests(unittest.TestCase):
    def test_uid_mismatch_refused_when_euid_nonzero(self):
        # Patch geteuid to a non-root uid that does not own the
        # file: the loader must refuse. Works under any harness
        # euid because the loader consults os.geteuid().
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "ceremony.seed", "11" * 32, 0o600)
            owner = path.stat().st_uid
            with mock.patch("os.geteuid", return_value=owner + 1):
                with self.assertRaises(SigningError):
                    load_ceremony_seed(path)

    def test_uid_match_accepted_when_euid_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "ceremony.seed", "11" * 32, 0o600)
            owner = path.stat().st_uid
            if owner == 0:
                self.skipTest(
                    "file owned by root: a matching non-root euid "
                    "cannot be simulated by patching alone")
            with mock.patch("os.geteuid", return_value=owner):
                loaded = load_ceremony_seed(path)
            self.assertEqual(loaded.seed, b"\x11" * 32)

    @unittest.skipIf(os.geteuid() == 0,
                     "running as root: uid check is vacuous by design")
    def test_real_euid_owns_generated_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ceremony.seed"
            made = generate_ceremony_key_file(path)
            self.assertEqual(load_ceremony_seed(path), made)


class GateLoaderPredicateParityTests(unittest.TestCase):
    """The shared predicate (R9): the gate loader accepts and
    refuses exactly the modes the seed loader does."""

    def test_0400_loads_via_load_signing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            made = generate_key_file(path)
            os.chmod(path, 0o400)
            loaded = load_signing_key(path)
            self.assertEqual(loaded.key_id, made.key_id)
            self.assertEqual(loaded.key, made.key)

    def test_gate_loader_refusals_match_seed_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gate.key"
            generate_key_file(path)
            for mode in (0o640, 0o644, 0o660, 0o200,
                         0o4600, 0o1600):
                os.chmod(path, mode)
                with self.assertRaises(SigningError, msg=oct(mode)):
                    load_signing_key(path)
            os.chmod(path, 0o600)
            self.assertEqual(load_signing_key(path).key,
                             load_signing_key(path).key)


if __name__ == "__main__":
    unittest.main()
