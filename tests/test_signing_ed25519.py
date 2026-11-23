"""Unit tests for signing/ed25519.py (cycle 20).

RFC 8032 section 7.1 vectors as literal constants, the strict
(R2) verification profile's negative vectors, property
round-trips, and a test-only AFFINE oracle cross-check: the slow
affine implementation lives here, in tests only, and the shipped
extended-coordinate implementation must agree with it.
"""

import hashlib
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import ed25519
from signing.ed25519 import (
    PUBLIC_KEY_BYTES,
    SEED_BYTES,
    SIGNATURE_BYTES,
    public_key_from_seed,
    sign,
    verify,
)

# RFC 8032 section 7.1 test vectors (literal constants).
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
VECTORS = (TEST_1, TEST_2, TEST_3)

# The 8 small-order encodings, mirrored literally: the module's
# blocklist must equal this list exactly.
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

_L = 2 ** 252 + 27742317777372353535851937790883648493
_Q = 2 ** 255 - 19


def _flip(data: bytes, index: int) -> bytes:
    out = bytearray(data)
    out[index] ^= 1
    return bytes(out)


class RfcVectorTests(unittest.TestCase):
    def test_keygen_sign_verify(self):
        for vector in VECTORS:
            seed = bytes.fromhex(vector["seed"])
            public = bytes.fromhex(vector["public"])
            message = bytes.fromhex(vector["message"])
            signature = bytes.fromhex(vector["signature"])
            self.assertEqual(len(seed), SEED_BYTES)
            self.assertEqual(len(public), PUBLIC_KEY_BYTES)
            self.assertEqual(len(signature), SIGNATURE_BYTES)
            self.assertEqual(public_key_from_seed(seed), public,
                             msg=vector["seed"][:8])
            # Deterministic: byte-equal signature, every time.
            self.assertEqual(sign(seed, message), signature)
            self.assertEqual(sign(seed, message), signature)
            self.assertTrue(verify(public, message, signature))


class NegativeVectorTests(unittest.TestCase):
    def setUp(self):
        self.public = bytes.fromhex(TEST_1["public"])
        self.message = b""
        self.signature = bytes.fromhex(TEST_1["signature"])

    def test_bit_flip_in_r(self):
        self.assertFalse(verify(
            self.public, self.message, _flip(self.signature, 0)))

    def test_bit_flip_in_s(self):
        self.assertFalse(verify(
            self.public, self.message, _flip(self.signature, 32)))

    def test_bit_flip_in_message(self):
        self.assertFalse(verify(
            self.public, b"\x00", self.signature))

    def test_bit_flip_in_public_key(self):
        self.assertFalse(verify(
            _flip(self.public, 5), self.message, self.signature))

    def test_s_equal_l_and_l_plus_1(self):
        for s in (_L, _L + 1):
            forged = self.signature[:32] + s.to_bytes(32, "little")
            self.assertFalse(
                verify(self.public, self.message, forged),
                msg=f"S={s}")

    def test_noncanonical_y_equal_q(self):
        # Encoding whose y is exactly q (y >= q is non-canonical).
        bad = bytes.fromhex(
            "edffffffffffffffffffffffffffffffffffffffffffffffff"
            "ffffffffffff7f")
        self.assertFalse(verify(bad, self.message, self.signature))
        forged = bad + self.signature[32:]
        self.assertFalse(verify(self.public, self.message, forged))

    def test_blocklist_is_the_mirrored_literal_list(self):
        self.assertEqual(
            tuple(enc.hex() for enc in ed25519.SMALL_ORDER_ENCODINGS),
            SMALL_ORDER_HEX)

    def test_small_order_a_rejected(self):
        for encoding_hex in SMALL_ORDER_HEX:
            bad_public = bytes.fromhex(encoding_hex)
            self.assertFalse(
                verify(bad_public, self.message, self.signature),
                msg=encoding_hex)

    def test_small_order_r_rejected(self):
        for encoding_hex in SMALL_ORDER_HEX:
            forged = bytes.fromhex(encoding_hex) \
                + (1).to_bytes(32, "little")
            self.assertFalse(
                verify(self.public, self.message, forged),
                msg=encoding_hex)

    def test_small_order_encodings_are_torsion(self):
        # Cross-check the blocklist itself: every entry decodes
        # and is killed by multiplication by 8 (lands on the
        # identity encoding).
        identity = bytes.fromhex(SMALL_ORDER_HEX[2])
        for encoding_hex in SMALL_ORDER_HEX:
            point = ed25519._point_decode(bytes.fromhex(encoding_hex))
            self.assertIsNotNone(point, msg=encoding_hex)
            self.assertEqual(
                ed25519._point_encode(ed25519._scalarmult(point, 8)),
                identity, msg=encoding_hex)

    def test_truncated_and_overlong_signature(self):
        self.assertFalse(verify(
            self.public, self.message, self.signature[:63]))
        self.assertFalse(verify(
            self.public, self.message, self.signature + b"\x00"))
        self.assertFalse(verify(self.public, self.message, b""))
        self.assertFalse(verify(self.public, self.message, None))

    def test_wrong_length_public_key(self):
        self.assertFalse(verify(
            self.public[:31], self.message, self.signature))
        self.assertFalse(verify(
            self.public + b"\x00", self.message, self.signature))
        self.assertFalse(verify(None, self.message, self.signature))

    def test_wrong_length_seed_to_loaders(self):
        for bad_seed in (b"", b"\x00" * 31, b"\x00" * 33, None, 32):
            with self.assertRaises(ValueError, msg=repr(bad_seed)):
                public_key_from_seed(bad_seed)
            with self.assertRaises(ValueError, msg=repr(bad_seed)):
                sign(bad_seed, b"msg")


# -- adversarial decode vectors (rev-r6 F3) --------------------------------
# Provenance: constructed in the style of the C2SP / Wycheproof
# Ed25519 test vectors — literal encodings plus constructions
# built from the RFC 8032 TEST 1 literal (seed, public key,
# signature) using hashlib only, or the module's point arithmetic
# for CONSTRUCTION only. Every expectation below is REJECT, and
# each expectation follows from the strict cofactorless profile
# itself (canonical decode, the small-order blocklist, S < L,
# [S]B = R + [H(R||A||M)]A), never from trusting the code under
# test: where a construction claims a lax verifier would accept,
# the comment states the exact lax equation that holds.

_IDENTITY_ENC = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000")
_ORDER2_ENC = bytes.fromhex(  # the (0, -1) point, order 2
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f")
_BASE_ENC = bytes.fromhex(  # canonical encoding of the base point B
    "5866666666666666666666666666666666666666666666666666666666666666")


def _test1_secret_scalar() -> int:
    """TEST 1's clamped secret scalar, from the literal seed via
    hashlib only (RFC 8032 section 5.1.5 clamping)."""
    h = hashlib.sha512(bytes.fromhex(TEST_1["seed"])).digest()
    clamped = bytearray(h[:32])
    clamped[0] &= 248
    clamped[31] &= 63
    clamped[31] |= 64
    return int.from_bytes(clamped, "little")


def _test1_nonce() -> int:
    """TEST 1's deterministic nonce r for the empty message,
    from the literal seed via hashlib only (RFC 8032 5.1.6)."""
    h = hashlib.sha512(bytes.fromhex(TEST_1["seed"])).digest()
    return int.from_bytes(
        hashlib.sha512(h[32:] + b"").digest(), "little") % _L


def _hash_mod_l(*parts: bytes) -> int:
    return int.from_bytes(
        hashlib.sha512(b"".join(parts)).digest(), "little") % _L


class AdversarialDecodeVectorTests(unittest.TestCase):
    def setUp(self):
        self.public = bytes.fromhex(TEST_1["public"])
        self.message = b""
        self.signature = bytes.fromhex(TEST_1["signature"])

    def test_s_plus_l_malleation_rejected(self):
        # Rationale: [S+L]B == [S]B, so a verifier that reduces S mod L (no S<L check) accepts; strict profile step 4 rejects.
        s = int.from_bytes(self.signature[32:], "little")
        forged = self.signature[:32] + (s + _L).to_bytes(32, "little")
        self.assertFalse(verify(self.public, self.message, forged))

    def test_identity_key_identity_r_zero_s_rejected(self):
        # Rationale: (A=I, R=I, S=0) satisfies the raw equation ([0]B = I + [k]I = I); only the small-order blocklist rejects it.
        forged = _IDENTITY_ENC + (0).to_bytes(32, "little")
        self.assertFalse(verify(_IDENTITY_ENC, self.message, forged))

    def test_small_order_key_identity_r_zero_s_rejected(self):
        # Rationale: (A=order-2, R=I, S=0) passes cofactored verification ([8] of both sides is I); strict rejects via blocklist/cofactorless equation.
        forged = _IDENTITY_ENC + (0).to_bytes(32, "little")
        self.assertFalse(verify(_ORDER2_ENC, self.message, forged))

    def test_identity_r_with_equation_satisfying_s_rejected(self):
        # Rationale: S = k*a (k = H(I||A||M), a = TEST 1 scalar) makes [S]B == I + [k]A exactly; only the R blocklist rejects this signature.
        k = _hash_mod_l(_IDENTITY_ENC, self.public, self.message)
        s = (k * _test1_secret_scalar()) % _L
        forged = _IDENTITY_ENC + s.to_bytes(32, "little")
        self.assertFalse(verify(self.public, self.message, forged))

    def test_mixed_torsion_r_rejected(self):
        # Rationale: R' = R + T (T order 2) with S' = r + k'*a passes cofactored verification ([8]T = I) but the cofactorless equation is off by exactly T != I.
        torsion = ed25519._point_decode(_ORDER2_ENC)
        r_prime = ed25519._point_encode(ed25519._point_add(
            ed25519._point_decode(self.signature[:32]), torsion))
        self.assertNotIn(r_prime, ed25519.SMALL_ORDER_ENCODINGS)
        k = _hash_mod_l(r_prime, self.public, self.message)
        s = (_test1_nonce() + k * _test1_secret_scalar()) % _L
        forged = r_prime + s.to_bytes(32, "little")
        self.assertFalse(verify(self.public, self.message, forged))

    def test_mixed_torsion_public_key_rejected(self):
        # Rationale: A' = A + T (T order 2) with R = B, S' = 1 + k'*a passes cofactored verification but the cofactorless equation is off by [k']T = T (k' is odd, asserted).
        torsion = ed25519._point_decode(_ORDER2_ENC)
        a_prime = ed25519._point_encode(ed25519._point_add(
            ed25519._point_decode(self.public), torsion))
        self.assertNotIn(a_prime, ed25519.SMALL_ORDER_ENCODINGS)
        k = _hash_mod_l(_BASE_ENC, a_prime, self.message)
        self.assertEqual(k % 2, 1)  # construction precondition
        s = (1 + k * _test1_secret_scalar()) % _L
        forged = _BASE_ENC + s.to_bytes(32, "little")
        self.assertFalse(verify(a_prime, self.message, forged))

    def test_noncanonical_identity_spelling_rejected(self):
        # Rationale: y=1 with the sign bit set is the x = -0 spelling of the identity; a lax (ZIP-215-style) decode may accept it, strict canonical decode rejects it.
        bad_public = bytes.fromhex(
            "01000000000000000000000000000000000000000000000000"
            "00000000000080")
        self.assertFalse(verify(bad_public, self.message,
                                self.signature))


class RoundTripTests(unittest.TestCase):
    def test_50_random_round_trips(self):
        rng = random.Random(20261123)
        for _ in range(50):
            seed = rng.randbytes(32)
            message = rng.randbytes(rng.randrange(0, 200))
            public = public_key_from_seed(seed)
            signature = sign(seed, message)
            self.assertTrue(verify(public, message, signature))
            self.assertFalse(verify(public, message + b"!", signature))


# -- test-only affine oracle -------------------------------------------------
# The RFC 8032 reference arithmetic in affine coordinates (a
# modular inversion per point add). It exists ONLY here, as an
# independent oracle for the shipped extended-coordinate code.

_D_AFFINE = (-121665 * pow(121666, _Q - 2, _Q)) % _Q


def _affine_add(p, q):
    x1, y1 = p
    x2, y2 = q
    common = _D_AFFINE * x1 * x2 * y1 * y2 % _Q
    x3 = (x1 * y2 + x2 * y1) * pow((1 + common) % _Q, _Q - 2, _Q) % _Q
    y3 = (y1 * y2 + x1 * x2) * pow((1 - common) % _Q, _Q - 2, _Q) % _Q
    return (x3, y3)


def _affine_scalarmult(point, scalar):
    result = (0, 1)
    addend = point
    s = scalar
    while s:
        if s & 1:
            result = _affine_add(result, addend)
        addend = _affine_add(addend, addend)
        s >>= 1
    return result


def _affine_encode(point) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


class AffineOracleTests(unittest.TestCase):
    def test_extended_matches_affine_on_random_points(self):
        by = 4 * pow(5, _Q - 2, _Q) % _Q
        # Recover Bx for By = 4/5 via the curve equation.
        xx = (by * by - 1) * pow(
            (_D_AFFINE * by * by + 1) % _Q, _Q - 2, _Q) % _Q
        bx = pow(xx, (_Q + 3) // 8, _Q)
        if (bx * bx - xx) % _Q != 0:
            bx = bx * pow(2, (_Q - 1) // 4, _Q) % _Q
        if bx & 1:
            bx = _Q - bx
        base = (bx, by)
        rng = random.Random(4242)
        for _ in range(8):
            scalar = rng.randrange(1, _L)
            expected = _affine_encode(_affine_scalarmult(base, scalar))
            actual = ed25519._point_encode(
                ed25519._scalarmult(ed25519._B, scalar))
            self.assertEqual(actual, expected)

    def test_oracle_agrees_with_rfc_keygen(self):
        # The oracle itself is pinned to a public constant, so the
        # cross-check above is anchored, not self-referential.
        seed = bytes.fromhex(TEST_2["seed"])
        h = hashlib.sha512(seed).digest()
        clamped = bytearray(h[:32])
        clamped[0] &= 248
        clamped[31] &= 63
        clamped[31] |= 64
        scalar = int.from_bytes(clamped, "little")
        by = 4 * pow(5, _Q - 2, _Q) % _Q
        xx = (by * by - 1) * pow(
            (_D_AFFINE * by * by + 1) % _Q, _Q - 2, _Q) % _Q
        bx = pow(xx, (_Q + 3) // 8, _Q)
        if (bx * bx - xx) % _Q != 0:
            bx = bx * pow(2, (_Q - 1) // 4, _Q) % _Q
        if bx & 1:
            bx = _Q - bx
        self.assertEqual(
            _affine_encode(_affine_scalarmult((bx, by), scalar)).hex(),
            TEST_2["public"])


class PerfGuardTests(unittest.TestCase):
    def test_test1_verify_under_one_second(self):
        public = bytes.fromhex(TEST_1["public"])
        signature = bytes.fromhex(TEST_1["signature"])
        start = time.perf_counter()
        self.assertTrue(verify(public, b"", signature))
        self.assertLess(time.perf_counter() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
