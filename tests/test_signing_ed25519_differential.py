"""Differential validation for signing/ed25519.py (cycle 21, R8).

This file is deliberately independent of tests/test_signing_ed25519.py
(fixtures re-declared as literals, never imported from it): the
cycle-20 suite validated the implementation against itself and a
test-only affine oracle, and an implementation that agrees with its
own oracle can still share a misreading of the standard with it.
Three anchors, none of which is the code under test:

* RFC 8032 section 7.1 known-answer literals (the specification
  anchor), including the long-message vector the RFC labels
  "TEST 1024" (its message is 1023 bytes — the RFC's own length
  field says so; the label is the RFC's, the length is pinned
  here as 1023 so nobody "fixes" the transcription to 1024).
* A Wycheproof-style adversarial table with PER-CASE pinned
  (ours, openssl) expectation pairs (the independence anchor).
  Ours must be False on every adversarial row — non-negotiable.
  The openssl half of each pair was PROBED at build time against
  openssl 3.0.13 on this VM (probe recorded in the comments at
  the table) and is asserted exactly: either side changing its
  answer fails the test. There is no "divergence allowed" bucket.
* openssl cross-implementation agreement on honest signatures:
  openssl's deterministic signature must be BYTE-IDENTICAL to
  ours, and each side must verify the other's signatures.

Independent re-probe (review, cycle 21): a non-builder reviewer
re-probed the full adversarial table with separately written
openssl driver code and reproduced every pinned pair with zero
mismatches — recorded in the cycle-21 review record.

GUARD (R8): a KAT literal that disagrees with BOTH this
implementation and openssl is a build blocker to report to the
coordinator — never a reason to edit the implementation to fit
the literal. At build time every literal below agreed with both.

What this does NOT prove: agreement with openssl pins the
implementation against one independent implementation; it does
not prove the RFC reading itself, and openssl's verifier is not
our strict profile (see the divergent rows it accepts below).

Bit-flip sweep runtime: measured at build time on this VM and
recorded in BitFlipTests below.
"""

import hashlib
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import ed25519
from signing.ed25519 import public_key_from_seed, sign, verify

_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493

# RFC 8032 section 7.1 vectors (literal constants, re-declared).
TEST_1 = {
    "seed": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    "public": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    "message": "",
    "signature": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                 "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
}
TEST_2 = {
    "seed": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
    "public": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
    "message": "72",
    "signature": "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                 "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
}
TEST_3 = {
    "seed": "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
    "public": "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
    "message": "af82",
    "signature": "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
                 "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
}
# RFC 8032 section 7.1 "TEST 1024": the long-message vector. The
# RFC's MESSAGE length field reads 1023 bytes (verified against
# the RFC text at build time; keygen/sign/verify below and the
# openssl sign direction all agree with these literals).
_TEST_1024_MESSAGE_HEX = (
    "08b8b2b733424243760fe426a4b54908" "632110a66c2f6591eabd3345e3e4eb98"
    "fa6e264bf09efe12ee50f8f54e9f77b1" "e355f6c50544e23fb1433ddf73be84d8"
    "79de7c0046dc4996d9e773f4bc9efe57" "38829adb26c81b37c93a1b270b20329d"
    "658675fc6ea534e0810a4432826bf58c" "941efb65d57a338bbd2e26640f89ffbc"
    "1a858efcb8550ee3a5e1998bd177e93a" "7363c344fe6b199ee5d02e82d522c4fe"
    "ba15452f80288a821a579116ec6dad2b" "3b310da903401aa62100ab5d1a36553e"
    "06203b33890cc9b832f79ef80560ccb9" "a39ce767967ed628c6ad573cb116dbef"
    "efd75499da96bd68a8a97b928a8bbc10" "3b6621fcde2beca1231d206be6cd9ec7"
    "aff6f6c94fcd7204ed3455c68c83f4a4" "1da4af2b74ef5c53f1d8ac70bdcb7ed1"
    "85ce81bd84359d44254d95629e9855a9" "4a7c1958d1f8ada5d0532ed8a5aa3fb2"
    "d17ba70eb6248e594e1a2297acbbb39d" "502f1a8c6eb6f1ce22b3de1a1f40cc24"
    "554119a831a9aad6079cad88425de6bd" "e1a9187ebb6092cf67bf2b13fd65f270"
    "88d78b7e883c8759d2c4f5c65adb7553" "878ad575f9fad878e80a0c9ba63bcbcc"
    "2732e69485bbc9c90bfbd62481d9089b" "eccf80cfe2df16a2cf65bd92dd597b07"
    "07e0917af48bbb75fed413d238f5555a" "7a569d80c3414a8d0859dc65a46128ba"
    "b27af87a71314f318c782b23ebfe808b" "82b0ce26401d2e22f04d83d1255dc51a"
    "ddd3b75a2b1ae0784504df543af8969b" "e3ea7082ff7fc9888c144da2af58429e"
    "c96031dbcad3dad9af0dcbaaaf268cb8" "fcffead94f3c7ca495e056a9b47acdb7"
    "51fb73e666c6c655ade8297297d07ad1" "ba5e43f1bca32301651339e22904cc8c"
    "42f58c30c04aafdb038dda0847dd988d" "cda6f3bfd15c4b4c4525004aa06eeff8"
    "ca61783aacec57fb3d1f92b0fe2fd1a8" "5f6724517b65e614ad6808d6f6ee34df"
    "f7310fdc82aebfd904b01e1dc54b2927" "094b2db68d6f903b68401adebf5a7e08"
    "d78ff4ef5d63653a65040cf9bfd4aca7" "984a74d37145986780fc0b16ac451649"
    "de6188a7dbdf191f64b5fc5e2ab47b57" "f7f7276cd419c17a3ca8e1b939ae49e4"
    "88acba6b965610b5480109c8b17b80e1" "b7b750dfc7598d5d5011fd2dcc5600a3"
    "2ef5b52a1ecc820e308aa342721aac09" "43bf6686b64b2579376504ccc493d97e"
    "6aed3fb0f9cd71a43dd497f01f17c0e2" "cb3797aa2a2f256656168e6c496afc5f"
    "b93246f6b1116398a346f1a641f3b041" "e989f7914f90cc2c7fff357876e506b5"
    "0d334ba77c225bc307ba537152f3f161" "0e4eafe595f6d9d90d11faa933a15ef1"
    "369546868a7f3a45a96768d40fd9d034" "12c091c6315cf4fde7cb68606937380d"
    "b2eaaa707b4c4185c32eddcdd306705e" "4dc1ffc872eeee475a64dfac86aba41c"
    "0618983f8741c5ef68d3a101e8a3b8ca" "c60c905c15fc910840b94c00a0b9d0")
TEST_1024 = {
    "seed": "f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5",
    "public": "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e",
    "message": _TEST_1024_MESSAGE_HEX,
    "signature": "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
                 "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03",
}
VECTORS = (TEST_1, TEST_2, TEST_3, TEST_1024)

SMALL_ORDER_HEX = (
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "0100000000000000000000000000000000000000000000000000000000000000",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
)


def _enc(y: int, sign: int = 0) -> bytes:
    """Raw (possibly non-canonical) encoding bytes for a y value
    and sign bit — construction only."""
    return (y | (sign << 255)).to_bytes(32, "little")


def _scalar(seed_hex: str) -> int:
    h = hashlib.sha512(bytes.fromhex(seed_hex)).digest()
    clamped = bytearray(h[:32])
    clamped[0] &= 248
    clamped[31] &= 63
    clamped[31] |= 64
    return int.from_bytes(clamped, "little")


def _nonce(seed_hex: str, message: bytes) -> int:
    h = hashlib.sha512(bytes.fromhex(seed_hex)).digest()
    return int.from_bytes(
        hashlib.sha512(h[32:] + message).digest(), "little") % _L


def _hash_mod_l(*parts: bytes) -> int:
    return int.from_bytes(
        hashlib.sha512(b"".join(parts)).digest(), "little") % _L


_IDENTITY_ENC = _enc(1, 0)
_ORDER2_ENC = _enc(_Q - 1, 0)
_BASE_ENC = bytes.fromhex(
    "5866666666666666666666666666666666666666666666666666666666666666")


def _adversarial_rows():
    """(name, public_key, message, signature, openssl_expected).

    Ours is False for EVERY row (asserted separately); the
    openssl expectation is the pinned half of the pair.

    PROBE RECORD (build time, openssl 3.0.13, this VM; every row
    below was run through `openssl pkeyutl -verify` with the
    SPKI wrapping used by OpensslDifferentialTests):
    * openssl REJECTS every row except the three noted next —
      including the S+L malleation (agree-reject, contra the
      ZIP-215 leniency hypothesis), every non-canonical y=q /
      q+1 / 2^255-1 spelling as A and as R, the x=-0 spellings,
      all small-order A/R rows, all mixed-torsion rows, and all
      cross-vector swaps.
    * openssl ACCEPTS (divergent pairs, pinned (False, True)):
      (A=identity, R=identity, S=0); (A=order-2, R=identity,
      S=0); and A=identity under its non-canonical y=1+q
      spelling with R=identity, S=0 — openssl's A-decode is
      ZIP-215-lenient there, while the SAME y=1+q spelling as
      R (A=identity, S=0) is REJECTED by openssl: the leniency
      is asymmetric, A-side only, in these constructions.
    Constructions use hashlib only, or the module's point
    arithmetic FOR CONSTRUCTION ONLY (the cycle-20 F3
    discipline); expectations never come from the code under
    test. Mixed A+T rows choose the smallest t >= 1 with
    R = [t]B and k = H(R||A'||M) not divisible by the torsion
    order, so the cofactorless equation fails by exactly
    [k]T != identity while the cofactored equation holds
    ([8k]T = identity) — a cofactored verifier would accept.
    (With t=1 fixed, the order-4 row's k was divisible by 4 and
    the signature was GENUINELY valid for A+T — caught at probe
    time, which is why t is searched, not fixed.)
    """
    pub2 = bytes.fromhex(TEST_2["public"])
    msg2 = bytes.fromhex(TEST_2["message"])
    sig2 = bytes.fromhex(TEST_2["signature"])
    pub3 = bytes.fromhex(TEST_3["public"])
    msg3 = bytes.fromhex(TEST_3["message"])
    sig3 = bytes.fromhex(TEST_3["signature"])
    r_enc, s_val = sig2[:32], int.from_bytes(sig2[32:], "little")
    a2 = _scalar(TEST_2["seed"])
    r2 = _nonce(TEST_2["seed"], msg2)
    rows = []

    for label, y, sign_bit in (("q", _Q, 0), ("q-sign", _Q, 1),
                               ("q+1", _Q + 1, 0),
                               ("2^255-1", 2 ** 255 - 1, 0),
                               ("2^255-1-sign", 2 ** 255 - 1, 1)):
        rows.append((f"noncanonical-A y={label}", _enc(y, sign_bit),
                     msg2, sig2, False))
        rows.append((f"noncanonical-R y={label}", pub2, msg2,
                     _enc(y, sign_bit) + sig2[32:], False))
    rows.append(("x=-0 identity as A", _enc(1, 1), msg2, sig2, False))
    rows.append(("x=-0 identity as R", pub2, msg2,
                 _enc(1, 1) + sig2[32:], False))
    rows.append(("x=-0 order2 as A", _enc(_Q - 1, 1), msg2, sig2, False))
    rows.append(("x=-0 order2 as R", pub2, msg2,
                 _enc(_Q - 1, 1) + sig2[32:], False))
    for label, s in (("L-1", _L - 1), ("L", _L), ("L+1", _L + 1),
                     ("2^256-1", 2 ** 256 - 1),
                     ("S+L malleation", s_val + _L)):
        rows.append((f"S={label}", pub2, msg2,
                     r_enc + s.to_bytes(32, "little"), False))
    for i, encoding_hex in enumerate(SMALL_ORDER_HEX):
        encoding = bytes.fromhex(encoding_hex)
        rows.append((f"small-order A #{i}", encoding, msg2, sig2, False))
        rows.append((f"small-order R #{i}", pub2, msg2,
                     encoding + (1).to_bytes(32, "little"), False))
    torsions = (("order2", SMALL_ORDER_HEX[7], 2),
                ("order4", SMALL_ORDER_HEX[0], 4),
                ("order8", SMALL_ORDER_HEX[3], 8))
    torsion_points = {}
    for label, encoding_hex, order in torsions:
        t_point = ed25519._point_decode(bytes.fromhex(encoding_hex))
        torsion_points[label] = t_point
        r_prime = ed25519._point_encode(ed25519._point_add(
            ed25519._point_decode(r_enc), t_point))
        k = _hash_mod_l(r_prime, pub2, msg2)
        rows.append((f"mixed R+T {label}", pub2, msg2,
                     r_prime + ((r2 + k * a2) % _L).to_bytes(32, "little"),
                     False))
        a_prime = ed25519._point_encode(ed25519._point_add(
            ed25519._point_decode(pub2), t_point))
        for t in range(1, 64):
            r_t = ed25519._point_encode(ed25519._scalarmult(ed25519._B, t))
            k = _hash_mod_l(r_t, a_prime, msg2)
            if k % order != 0:
                break
        else:  # pragma: no cover - hash search cannot plausibly fail
            raise AssertionError("no t with k not divisible by torsion order")
        rows.append((f"mixed A+T {label}", a_prime, msg2,
                     r_t + ((t + k * a2) % _L).to_bytes(32, "little"),
                     False))
    a_mixed = ed25519._point_encode(ed25519._point_add(
        ed25519._point_decode(pub2), torsion_points["order2"]))
    r_mixed = ed25519._point_encode(ed25519._point_add(
        ed25519._point_decode(r_enc), torsion_points["order8"]))
    k = _hash_mod_l(r_mixed, a_mixed, msg2)
    rows.append(("mixed A+T2 R+T8", a_mixed, msg2,
                 r_mixed + ((r2 + k * a2) % _L).to_bytes(32, "little"),
                 False))
    zero_s = (0).to_bytes(32, "little")
    rows.append(("identity A=I R=I S=0", _IDENTITY_ENC, msg2,
                 _IDENTITY_ENC + zero_s, True))
    rows.append(("identity A=order2 R=I S=0", _ORDER2_ENC, msg2,
                 _IDENTITY_ENC + zero_s, True))
    k = _hash_mod_l(_BASE_ENC, _IDENTITY_ENC, msg2)
    rows.append(("identity A=I R=B S=k*a", _IDENTITY_ENC, msg2,
                 _BASE_ENC + ((k * a2) % _L).to_bytes(32, "little"),
                 False))
    rows.append(("noncanonical A y=1+q identity spelling",
                 _enc(1 + _Q, 0), msg2, _IDENTITY_ENC + zero_s, True))
    rows.append(("noncanonical R y=1+q identity spelling",
                 _IDENTITY_ENC, msg2, _enc(1 + _Q, 0) + zero_s, False))
    rows.append(("swap pub3 msg2 sig2", pub3, msg2, sig2, False))
    rows.append(("swap pub2 msg3 sig2", pub2, msg3, sig2, False))
    rows.append(("swap pub2 msg2 sig3", pub2, msg2, sig3, False))
    rows.append(("swap pub3 msg3 sig2", pub3, msg3, sig2, False))
    return rows


class RfcKatTests(unittest.TestCase):
    def test_vectors_keygen_sign_verify(self):
        for vector in VECTORS:
            seed = bytes.fromhex(vector["seed"])
            public = bytes.fromhex(vector["public"])
            message = bytes.fromhex(vector["message"])
            signature = bytes.fromhex(vector["signature"])
            self.assertEqual(public_key_from_seed(seed), public,
                             msg=vector["seed"][:8])
            self.assertEqual(sign(seed, message), signature,
                             msg=vector["seed"][:8])
            self.assertTrue(verify(public, message, signature),
                            msg=vector["seed"][:8])

    def test_long_message_vector_shape(self):
        # The RFC labels this vector TEST 1024; its message is
        # 1023 bytes per the RFC's own length field. Pin both
        # facts so a transcription "fix" fails loudly.
        message = bytes.fromhex(TEST_1024["message"])
        self.assertEqual(len(message), 1023)


class AdversarialTableTests(unittest.TestCase):
    def test_ours_rejects_every_adversarial_row(self):
        rows = _adversarial_rows()
        self.assertGreaterEqual(len(rows), 50)
        for name, public, message, signature, _openssl in rows:
            self.assertFalse(verify(public, message, signature),
                             msg=name)


class BitFlipTests(unittest.TestCase):
    # Measured at build time on this VM: the full sweep below
    # — 512 signature flips + 256 public-key flips (TEST 1) +
    # 8 message flips (TEST 2) = 776 verifies — took 13.3 s,
    # well under the 60 s subsample-fallback threshold from
    # the design, so the exhaustive sweep ships unreduced.
    def test_exhaustive_single_bit_flips(self):
        public = bytes.fromhex(TEST_1["public"])
        signature = bytes.fromhex(TEST_1["signature"])
        start = time.perf_counter()
        for byte_index in range(64):
            for bit in range(8):
                forged = bytearray(signature)
                forged[byte_index] ^= 1 << bit
                self.assertFalse(
                    verify(public, b"", bytes(forged)),
                    msg=f"signature byte {byte_index} bit {bit}")
        for byte_index in range(32):
            for bit in range(8):
                forged_key = bytearray(public)
                forged_key[byte_index] ^= 1 << bit
                self.assertFalse(
                    verify(bytes(forged_key), b"", signature),
                    msg=f"public key byte {byte_index} bit {bit}")
        message2 = bytes.fromhex(TEST_2["message"])
        public2 = bytes.fromhex(TEST_2["public"])
        signature2 = bytes.fromhex(TEST_2["signature"])
        for byte_index in range(len(message2)):
            for bit in range(8):
                forged_msg = bytearray(message2)
                forged_msg[byte_index] ^= 1 << bit
                self.assertFalse(
                    verify(public2, bytes(forged_msg), signature2),
                    msg=f"message byte {byte_index} bit {bit}")
        elapsed = time.perf_counter() - start
        # Generous ceiling: the design's subsample fallback
        # triggers above 60 s; assert we are nowhere near it.
        self.assertLess(elapsed, 60.0)

    def test_message_bit_flips_long_message(self):
        # LOW-3 follow-up: the message dimension above covers
        # only TEST_2's 1-byte message (8 flips). Here a
        # 32-byte message under a fixed seed gets the full
        # sweep: all 256 single-bit flips must verify False
        # against production verify (and the unflipped
        # signature must verify True, so the sweep is not
        # vacuously passing on a broken fixture). Measured
        # on this VM at fix time: 3.5 s for this test
        # (256 flips plus the fixture sign/verify).
        seed = bytes.fromhex(TEST_2["seed"])
        public = public_key_from_seed(seed)
        message = bytes(range(32))
        signature = sign(seed, message)
        self.assertTrue(verify(public, message, signature))
        start = time.perf_counter()
        for byte_index in range(len(message)):
            for bit in range(8):
                forged_msg = bytearray(message)
                forged_msg[byte_index] ^= 1 << bit
                self.assertFalse(
                    verify(public, bytes(forged_msg), signature),
                    msg=f"long message byte {byte_index} bit {bit}")
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 60.0)


# -- openssl differential ---------------------------------------------------

OPENSSL = shutil.which("openssl")
_PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _openssl_run(args, **kwargs):
    return subprocess.run([OPENSSL] + args, capture_output=True,
                          timeout=30, **kwargs)


def _openssl_verify(public: bytes, message: bytes,
                    signature: bytes) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "pub.der").write_bytes(_SPKI_PREFIX + public)
        (tmp / "msg").write_bytes(message)
        (tmp / "sig").write_bytes(signature)
        result = _openssl_run(
            ["pkeyutl", "-verify", "-pubin", "-inkey",
             str(tmp / "pub.der"), "-keyform", "DER", "-rawin",
             "-in", str(tmp / "msg"), "-sigfile", str(tmp / "sig")])
        return result.returncode == 0


def _openssl_sign(seed: bytes, message: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "priv.der").write_bytes(_PKCS8_PREFIX + seed)
        (tmp / "msg").write_bytes(message)
        result = _openssl_run(
            ["pkeyutl", "-sign", "-rawin", "-inkey",
             str(tmp / "priv.der"), "-keyform", "DER",
             "-in", str(tmp / "msg")])
        if result.returncode != 0:
            raise AssertionError(
                f"openssl sign failed: {result.stderr!r}")
        return result.stdout


@unittest.skipUnless(OPENSSL, "openssl not available")
class OpensslDifferentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Probe: a broken openssl install is a skip, not a
        # failure (the repo's skipUnless pattern). The probe
        # exercises a real Ed25519 sign+verify round-trip, not
        # just `openssl version`: an openssl that runs but
        # lacks Ed25519 / pkeyutl support is present but
        # incapable, so the class skips rather than failing.
        try:
            result = _openssl_run(["version"])
        except (OSError, subprocess.SubprocessError) as exc:
            raise unittest.SkipTest(f"openssl cannot execute: {exc}")
        if result.returncode != 0:
            raise unittest.SkipTest("openssl version probe failed")
        seed = bytes.fromhex(TEST_2["seed"])
        public = bytes.fromhex(TEST_2["public"])
        message = bytes.fromhex(TEST_2["message"])
        try:
            signature = _openssl_sign(seed, message)
            verified = _openssl_verify(public, message, signature)
        except (AssertionError, OSError,
                subprocess.SubprocessError) as exc:
            raise unittest.SkipTest(
                f"openssl Ed25519 round-trip cannot execute: {exc}")
        if signature != bytes.fromhex(TEST_2["signature"]) \
                or not verified:
            raise unittest.SkipTest(
                "openssl Ed25519 sign+verify round-trip failed: "
                "openssl is present but incapable")

    def test_der_prefixes_are_structurally_as_documented(self):
        self.assertEqual(len(_PKCS8_PREFIX) + 32, 48)
        self.assertEqual(len(_SPKI_PREFIX) + 32, 44)
        self.assertIn(bytes.fromhex("06032b6570"), _PKCS8_PREFIX)
        self.assertIn(bytes.fromhex("06032b6570"), _SPKI_PREFIX)

    def test_openssl_derives_the_same_public_keys(self):
        for vector in VECTORS:
            seed = bytes.fromhex(vector["seed"])
            with tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                (tmp / "priv.der").write_bytes(_PKCS8_PREFIX + seed)
                result = _openssl_run(
                    ["pkey", "-in", str(tmp / "priv.der"),
                     "-inform", "DER", "-pubout", "-outform", "DER"])
                self.assertEqual(result.returncode, 0)
                self.assertEqual(
                    result.stdout,
                    _SPKI_PREFIX + bytes.fromhex(vector["public"]),
                    msg=vector["seed"][:8])

    def test_sign_direction_byte_identical(self):
        # Messages of length >= 1 only: openssl pkeyutl cannot
        # process 0-byte messages (a tooling failure that would
        # masquerade as a rejection — critique-c section 6). The
        # empty message is covered by the KAT above.
        for vector in (TEST_2, TEST_3, TEST_1024):
            seed = bytes.fromhex(vector["seed"])
            public = bytes.fromhex(vector["public"])
            message = bytes.fromhex(vector["message"])
            signature = bytes.fromhex(vector["signature"])
            openssl_signature = _openssl_sign(seed, message)
            self.assertEqual(openssl_signature, signature,
                             msg=vector["seed"][:8])
            self.assertEqual(openssl_signature, sign(seed, message))
            self.assertTrue(
                _openssl_verify(public, message, sign(seed, message)),
                msg=vector["seed"][:8])

    def test_adversarial_pairs_are_pinned_exactly(self):
        for name, public, message, signature, openssl_expected \
                in _adversarial_rows():
            self.assertFalse(verify(public, message, signature),
                             msg=name)
            self.assertEqual(
                _openssl_verify(public, message, signature),
                openssl_expected, msg=f"openssl outcome changed: {name}")

    def test_seeded_random_cross_implementation_agreement(self):
        rng = random.Random(20261123)
        for i in range(10):
            seed = rng.randbytes(32)
            message = rng.randbytes(rng.randrange(1, 200))
            public = public_key_from_seed(seed)
            ours = sign(seed, message)
            theirs = _openssl_sign(seed, message)
            self.assertEqual(theirs, ours, msg=f"pair {i}")
            self.assertTrue(verify(public, message, theirs),
                            msg=f"pair {i}")
            self.assertTrue(_openssl_verify(public, message, ours),
                            msg=f"pair {i}")


if __name__ == "__main__":
    unittest.main()
