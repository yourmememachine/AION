"""Pure-Python Ed25519 (RFC 8032), strict verification profile.

Standard library only, and no imports from ``signing/`` — this
module is usable by both the signing side (the verifier process)
and the verifying side (ceremony / client processes), and is
auditable in isolation.

Implementation: extended twisted-Edwards coordinates (inversion
only on encode/decode), deterministic RFC 8032 signing.

Verification is the strict profile pinned for cycle 20 (the
"R2 profile"). ``verify`` performs these checks IN ORDER and
never raises on bad input — every failure returns ``False``:

1. exact lengths (public key 32 bytes, signature 64 bytes);
2. canonical decode of A and R: ``y < q`` and re-encoding the
   decoded point reproduces the input bytes exactly (this also
   rejects encodings that do not decode to a curve point, and
   the ``x = -0`` spelling of the identity);
3. small-order blocklist: A and R are rejected if their
   encodings are any of the 8 small-order encodings carried
   below as literal constants;
4. ``S < L``;
5. the cofactorless equation ``[S]B = R + [H(R||A||M)]A``.

There is exactly one signer of these signatures (this module,
inside the verifier process), so permissive-verification
interoperability with other Ed25519 stacks is irrelevant and
malleability is the enemy: signatures an honest RFC 8032 signer
produces always satisfy the strict profile.

Honest limits:

* Pure-Python scalar multiplication is NOT constant-time. The
  secret-dependent multiplications — the clamped secret scalar
  AND the deterministic-nonce scalar — happen only inside
  ``sign`` / ``public_key_from_seed``, i.e. only inside the
  verifier process, which deployment runs as a dedicated OS
  user. Verification multiplies public values only; its timing
  leaks no secret.
* A seed is a bearer secret: anyone holding the 32 seed bytes
  can sign. Placement discipline for seed files lives with the
  loaders in signing/ceremony_authorisation.py and with the
  verifier's configuration, not in this module.
"""

from __future__ import annotations

import hashlib

PUBLIC_KEY_BYTES = 32
SEED_BYTES = 32
SIGNATURE_BYTES = 64

_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)  # sqrt(-1) mod q

# The 8 canonical encodings of the small-order (torsion) points
# on edwards25519, as literal constants: the points of order 1,
# 2, 4 and 8. (Source: the low-order point list published with
# the C2SP ed25519 test vectors; cross-checked in the tests by
# confirming each decoded point is killed by multiplication
# by 8.) Non-canonical spellings of the same points never reach
# this check: the canonical-decode step above them rejects any
# encoding whose y >= q or whose re-encoding differs.
SMALL_ORDER_ENCODINGS = (
    bytes.fromhex(
        "00000000000000000000000000000000000000000000000000000000"
        "00000000"),
    bytes.fromhex(
        "00000000000000000000000000000000000000000000000000000000"
        "00000080"),
    bytes.fromhex(
        "01000000000000000000000000000000000000000000000000000000"
        "00000000"),
    bytes.fromhex(
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b1380288"
        "6d53fc05"),
    bytes.fromhex(
        "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b1380288"
        "6d53fc85"),
    bytes.fromhex(
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7"
        "792ac037a"),
    bytes.fromhex(
        "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7"
        "792ac03fa"),
    bytes.fromhex(
        "ecffffffffffffffffffffffffffffffffffffffffffffffffffffff"
        "ffffff7f"),
)
_SMALL_ORDER_SET = frozenset(SMALL_ORDER_ENCODINGS)

# Extended twisted-Edwards points are (X, Y, Z, T) with
# x = X/Z, y = Y/Z, xy = T/Z.
_IDENTITY = (0, 1, 1, 0)


def _point_add(p, q):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = (y1 - x1) * (y2 - x2) % _Q
    b = (y1 + x1) * (y2 + x2) % _Q
    c = 2 * _D * t1 * t2 % _Q
    d = 2 * z1 * z2 % _Q
    e = (b - a) % _Q
    f = (d - c) % _Q
    g = (d + c) % _Q
    h = (b + a) % _Q
    return (e * f % _Q, g * h % _Q, f * g % _Q, e * h % _Q)


def _point_double(p):
    x1, y1, z1, _t1 = p
    a = x1 * x1 % _Q
    b = y1 * y1 % _Q
    c = 2 * z1 * z1 % _Q
    d = (-a) % _Q
    e = ((x1 + y1) * (x1 + y1) - a - b) % _Q
    g = (d + b) % _Q
    f = (g - c) % _Q
    h = (d - b) % _Q
    return (e * f % _Q, g * h % _Q, f * g % _Q, e * h % _Q)


def _scalarmult(point, scalar):
    result = _IDENTITY
    addend = point
    s = scalar
    while s:
        if s & 1:
            result = _point_add(result, addend)
        addend = _point_double(addend)
        s >>= 1
    return result


def _point_encode(point) -> bytes:
    x, y, z, _t = point
    zinv = pow(z, _Q - 2, _Q)
    ax = x * zinv % _Q
    ay = y * zinv % _Q
    return (ay | ((ax & 1) << 255)).to_bytes(32, "little")


def _point_decode(data: bytes):
    """Decode a canonical encoding, or return None. Canonical
    means: y < q, the bytes decode to a curve point, and
    re-encoding the decoded point reproduces ``data`` exactly."""
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    if y >= _Q:
        return None
    # x^2 = (y^2 - 1) / (d y^2 + 1)
    yy = y * y % _Q
    u = (yy - 1) % _Q
    v = (_D * yy + 1) % _Q
    if v == 0:
        return None
    xx = u * pow(v, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = x * _I % _Q
    if (x * x - xx) % _Q != 0:
        return None
    if x == 0 and sign == 1:
        return None  # x = -0 is not a canonical encoding
    if (x & 1) != sign:
        x = _Q - x
    point = (x, y, 1, x * y % _Q)
    if _point_encode(point) != data:
        return None
    return point


def _base_point():
    by = 4 * pow(5, _Q - 2, _Q) % _Q
    encoded = by.to_bytes(32, "little")  # sign bit 0
    point = _point_decode(encoded)
    assert point is not None
    return point


_B = _base_point()


def _clamp(h32: bytes) -> int:
    a = bytearray(h32)
    a[0] &= 248
    a[31] &= 63
    a[31] |= 64
    return int.from_bytes(a, "little")


def _check_seed(seed) -> bytes:
    if not isinstance(seed, (bytes, bytearray)) \
            or len(seed) != SEED_BYTES:
        raise ValueError(f"seed must be exactly {SEED_BYTES} bytes")
    return bytes(seed)


def _check_message(message) -> bytes:
    if not isinstance(message, (bytes, bytearray)):
        raise ValueError("message must be bytes")
    return bytes(message)


def public_key_from_seed(seed: bytes) -> bytes:
    """Derive the 32-byte public key for a 32-byte seed."""
    seed = _check_seed(seed)
    h = hashlib.sha512(seed).digest()
    a = _clamp(h[:32])
    return _point_encode(_scalarmult(_B, a))


def sign(seed: bytes, message: bytes) -> bytes:
    """Deterministic RFC 8032 signature (64 bytes) of ``message``
    under ``seed``. No RNG is involved: the nonce is a hash of
    the seed's hash prefix and the message."""
    seed = _check_seed(seed)
    message = _check_message(message)
    h = hashlib.sha512(seed).digest()
    a = _clamp(h[:32])
    prefix = h[32:]
    public_key = _point_encode(_scalarmult(_B, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(),
                       "little") % _L
    r_enc = _point_encode(_scalarmult(_B, r))
    k = int.from_bytes(
        hashlib.sha512(r_enc + public_key + message).digest(),
        "little") % _L
    s = (r + k * a) % _L
    return r_enc + s.to_bytes(32, "little")


def verify(public_key: bytes, message: bytes,
           signature: bytes) -> bool:
    """Strict-profile verification (see the module docstring for
    the ordered check list). Never raises on bad input."""
    try:
        # (1) exact lengths
        if not isinstance(public_key, (bytes, bytearray)) \
                or len(public_key) != PUBLIC_KEY_BYTES:
            return False
        if not isinstance(signature, (bytes, bytearray)) \
                or len(signature) != SIGNATURE_BYTES:
            return False
        if not isinstance(message, (bytes, bytearray)):
            return False
        public_key = bytes(public_key)
        signature = bytes(signature)
        message = bytes(message)
        a_enc = public_key
        r_enc = signature[:32]
        # (2) canonical decode of A and R
        a_point = _point_decode(a_enc)
        if a_point is None:
            return False
        r_point = _point_decode(r_enc)
        if r_point is None:
            return False
        # (3) small-order blocklist
        if a_enc in _SMALL_ORDER_SET or r_enc in _SMALL_ORDER_SET:
            return False
        # (4) S < L
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        # (5) cofactorless equation [S]B = R + [H(R||A||M)]A
        k = int.from_bytes(
            hashlib.sha512(r_enc + a_enc + message).digest(),
            "little") % _L
        left = _scalarmult(_B, s)
        right = _point_add(r_point, _scalarmult(a_point, k))
        return _point_encode(left) == _point_encode(right)
    except Exception:
        return False
