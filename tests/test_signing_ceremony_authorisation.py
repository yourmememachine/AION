"""Unit tests for signing/ceremony_authorisation.py (cycle 20, v2).

The envelope unit half: payload projection refusals (reason
allowlist, reason/pin coherence, gap-only sequence relation,
evidence non-equality), the REASONS mirror drift pin against
signing.pin_ceremony, Ed25519 sign/verify round trip, each verify
reason in the vocabulary, serialisation strictness,
authorisation_id derivation — plus the cycle-20 adversarial
suites: (a) key substitution in both directions, (b) local
minting with everything the ceremony process holds, and (c) the
no-HMAC-fallback tripwires (golden v1 fixture, alg flip, source
scan).
"""

import hashlib
import hmac
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import signing.pin_ceremony as pin_ceremony
from signing import (
    SigningError,
    make_signing_key,
)
from signing.ceremony_authorisation import (
    ALG_CEREMONY,
    CEREMONY_AUTHORISATION_TTL_MAX_SECONDS,
    REASONS,
    CeremonyPublicKey,
    _EITHER_PIN_REASONS,
    _NO_PIN_REASONS,
    _make_ceremony_signing_key,
    authorisation_id_for,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_from_json,
    ceremony_authorisation_envelope_to_dict,
    ceremony_authorisation_envelope_to_json,
    ceremony_authorisation_payload,
    ceremony_public_key_for,
    generate_ceremony_key_file,
    load_ceremony_seed,
    public_key_id_for,
    sign_ceremony_authorisation,
    verify_ceremony_authorisation,
)
from signing.ed25519 import public_key_from_seed, sign as ed_sign

VERIFIER_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle20 test verifier ceremony seed").digest())
ATTACKER_KEY = _make_ceremony_signing_key(
    hashlib.sha256(b"cycle20 test attacker ceremony seed").digest())
VERIFIER_PIN = ceremony_public_key_for(VERIFIER_KEY)
ATTACKER_PIN = ceremony_public_key_for(ATTACKER_KEY)
# Everything the ceremony process holds besides the pin: the
# snapshot HMAC key. Cycle 19's defect was that this material
# sufficed to mint; cycle 20's regression test is that it does
# not.
SNAPSHOT_KEY = make_signing_key(
    hashlib.sha256(b"cycle20 test snapshot key").digest())
NOW = "2026-11-28T10:00:00+00:00"
OLD_HASH = "a" * 64
CAND_HASH = "b" * 64
EVIDENCE_HASH = "c" * 64
CANDIDATE = {"cycle_seq": 47, "payload_hash": CAND_HASH,
             "signer_id": "snapshot-svc",
             "key_id": "key-0123456789abcdef"}
OLD_PIN = {"cycle_seq": 41, "payload_hash": OLD_HASH}


def mint(**over):
    kwargs = dict(
        signing_key=VERIFIER_KEY, signer_id="verifier-svc",
        operator_id="operator-uma",
        ceremony_id="ceremony-2026-11-28-001",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN),
        candidate=dict(CANDIDATE), evidence_hash=EVIDENCE_HASH,
        evidence_ref="case-file-1", now=NOW)
    kwargs.update(over)
    return sign_ceremony_authorisation(**kwargs)


def verify(signed, **over):
    kwargs = dict(public_key=VERIFIER_PIN, now=NOW)
    kwargs.update(over)
    return verify_ceremony_authorisation(signed, **kwargs)


def payload_kwargs(**over):
    kwargs = dict(
        signer_id="verifier-svc", key_id=VERIFIER_KEY.key_id,
        operator_id="operator-uma",
        ceremony_id="ceremony-2026-11-28-001",
        reason="chain_gap_recovery", old_pin=dict(OLD_PIN),
        candidate=dict(CANDIDATE), evidence_hash=EVIDENCE_HASH,
        evidence_ref="case-file-1", signed_at=NOW,
        expires_at="2026-11-28T10:15:00+00:00")
    kwargs.update(over)
    return kwargs


class MirrorDriftTests(unittest.TestCase):
    def test_reasons_mirror_matches_pin_ceremony(self):
        # The mirror exists because importing pin_ceremony from
        # ceremony_authorisation would be circular; this pin is
        # what keeps the copy honest.
        self.assertEqual(REASONS, pin_ceremony.REASONS)
        self.assertEqual(_NO_PIN_REASONS,
                         pin_ceremony._NO_PIN_REASONS)
        self.assertEqual(_EITHER_PIN_REASONS,
                         pin_ceremony._EITHER_PIN_REASONS)


class KeyTypeTests(unittest.TestCase):
    def test_public_key_id_derivation(self):
        self.assertEqual(
            public_key_id_for(VERIFIER_KEY.public_key),
            "pub-" + hashlib.sha256(
                VERIFIER_KEY.public_key).hexdigest()[:16])
        self.assertEqual(VERIFIER_KEY.key_id, VERIFIER_PIN.key_id)
        self.assertTrue(VERIFIER_KEY.key_id.startswith("pub-"))
        # Disjoint namespace from the HMAC key ids.
        self.assertFalse(SNAPSHOT_KEY.key_id.startswith("pub-"))

    def test_repr_never_shows_seed(self):
        text = repr(VERIFIER_KEY)
        self.assertNotIn(VERIFIER_KEY.seed.hex(), text)
        self.assertNotIn(repr(VERIFIER_KEY.seed), text)
        self.assertIn(VERIFIER_KEY.key_id, text)

    def test_sign_rejects_snapshot_signing_key(self):
        # Type separation: the cycle-19 HMAC key type cannot be
        # used to mint a v2 authorisation at all.
        with self.assertRaises(SigningError):
            mint(signing_key=SNAPSHOT_KEY)

    def test_verify_rejects_snapshot_signing_key_as_public_key(self):
        with self.assertRaises(SigningError):
            verify_ceremony_authorisation(
                mint(), public_key=SNAPSHOT_KEY, now=NOW)

    def test_key_id_inconsistent_means_lying_public_key_object(self):
        lying = CeremonyPublicKey(
            public_key=VERIFIER_KEY.public_key,
            key_id="pub-0000000000000000")
        self.assertEqual(
            verify_ceremony_authorisation(
                mint(), public_key=lying, now=NOW),
            ("key_id_inconsistent",))

    def test_seed_file_round_trip_and_refusals(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ceremony.seed"
            made = generate_ceremony_key_file(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            loaded = load_ceremony_seed(path)
            self.assertEqual(loaded, made)
            self.assertEqual(
                public_key_from_seed(loaded.seed), loaded.public_key)
            with self.assertRaises(SigningError):
                generate_ceremony_key_file(path)  # no overwrite
            path.chmod(0o644)
            with self.assertRaises(SigningError):
                load_ceremony_seed(path)  # mode discipline
            with self.assertRaises(SigningError):
                load_ceremony_seed(Path(tmp) / "missing.seed")

    def test_seed_file_odd_length_hex_is_signing_error(self):
        # rev-r2 Low: an odd-length hex file must fail as
        # SigningError, never as a raw ValueError from
        # bytes.fromhex escaping the loader.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odd.seed"
            path.write_text("a" * 63, encoding="ascii")
            path.chmod(0o600)
            with self.assertRaises(SigningError):
                load_ceremony_seed(path)

    def test_seed_file_uppercase_char_is_signing_error(self):
        # A 64-char file with one uppercase (non-lowercase-hex)
        # char is refused as SigningError.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upper.seed"
            path.write_text("a" * 63 + "A", encoding="ascii")
            path.chmod(0o600)
            with self.assertRaises(SigningError):
                load_ceremony_seed(path)


class RefusedTestSeedsTests(unittest.TestCase):
    def test_exported_set_contains_rfc_vector_seeds(self):
        # rev-r6 F5.1: the exported set is the single source the
        # verifier side unions/imports; it must contain the three
        # RFC 8032 section 7.1 vector seeds (the test fixtures).
        from signing.ceremony_authorisation import REFUSED_TEST_SEEDS
        self.assertIsInstance(REFUSED_TEST_SEEDS, frozenset)
        for vector in (
                "9d61b19deffd5a60ba844af492ec2cc4"
                "4449c5697b326919703bac031cae7f60",
                "4ccd089b28ff96da9db6c346ec114e0f"
                "5b8a319f35aba624da8cf6ed4fb8a6fb",
                "c5aa8df43f9f837bedb7442f31dcb7b1"
                "66d38535076f094b85ce3a2e0b4458f7"):
            self.assertIn(bytes.fromhex(vector), REFUSED_TEST_SEEDS)

    def test_exported_set_covers_verifier_local_list(self):
        # Superset of trust/verifier_main.py's local refused
        # values: the four predictable test keys plus the RFC
        # seeds, so the verifier can import this set
        # unconditionally.
        from signing.ceremony_authorisation import REFUSED_TEST_SEEDS
        for seed in (bytes(range(32)), bytes(range(32, 64)),
                     b"\x00" * 32, b"\xff" * 32):
            self.assertIn(seed, REFUSED_TEST_SEEDS)


class PackageExportTests(unittest.TestCase):
    def test_cycle20_names_importable_from_package(self):
        # rev-r5 MEDIUM: the cycle-20 public names are package
        # exports, and the ed25519 submodule is reachable.
        import signing
        import signing.ed25519 as ed25519_module
        from signing import (  # noqa: F401
            ALG_CEREMONY,
            REFUSED_TEST_SEEDS,
            CeremonyPublicKey,
            CeremonySigningKey,
            ceremony_public_key_for,
            generate_ceremony_key_file,
            load_ceremony_seed,
            public_key_id_for,
        )
        self.assertIs(signing.ed25519, ed25519_module)
        for name in ("CeremonyPublicKey", "CeremonySigningKey",
                     "public_key_id_for", "load_ceremony_seed",
                     "generate_ceremony_key_file",
                     "ceremony_public_key_for", "ALG_CEREMONY",
                     "REFUSED_TEST_SEEDS", "ed25519"):
            self.assertIn(name, signing.__all__, msg=name)


class PayloadProjectionTests(unittest.TestCase):
    def test_payload_shape(self):
        payload = ceremony_authorisation_payload(**payload_kwargs())
        self.assertEqual(payload["v"],
                         "signed-ceremony-authorisation/2")
        self.assertEqual(payload["alg"], "ed25519")
        self.assertEqual(ALG_CEREMONY, "ed25519")
        self.assertEqual(payload["purpose"],
                         "pin-ceremony-authorisation")
        self.assertEqual(set(payload["old_pin"]),
                         {"cycle_seq", "payload_hash"})
        self.assertEqual(set(payload["candidate"]),
                         {"cycle_seq", "payload_hash", "signer_id",
                          "key_id"})

    def test_unknown_reason_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(reason="whatever"))

    def test_no_pin_reason_with_pin_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(reason="lost_pin"))

    def test_gap_reason_without_pin_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(old_pin=None))

    def test_no_pin_reason_without_pin_ok(self):
        payload = ceremony_authorisation_payload(**payload_kwargs(
            reason="initial_anchor", old_pin=None))
        self.assertIsNone(payload["old_pin"])

    def test_gap_relation_refusals(self):
        for seq in (41, 40, 42):  # equal, backwards, +1 chained
            with self.assertRaises(SigningError, msg=f"seq {seq}"):
                ceremony_authorisation_payload(**payload_kwargs(
                    candidate=dict(CANDIDATE, cycle_seq=seq)))

    def test_pin_shape_refusals(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                old_pin=dict(OLD_PIN, key_id="key-x")))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                candidate=dict(CANDIDATE, extra=1)))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                candidate=dict(CANDIDATE, cycle_seq=True)))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                old_pin=dict(OLD_PIN, cycle_seq=-1)))

    def test_evidence_non_equality(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                evidence_hash=CAND_HASH))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                evidence_hash=OLD_HASH))

    def test_evidence_ref_refusals(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(evidence_ref=""))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(evidence_ref="x" * 2001))

    def test_window_over_hard_cap_refused(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(**payload_kwargs(
                expires_at="2026-11-28T10:15:01+00:00"))


class SignVerifyTests(unittest.TestCase):
    def test_round_trip(self):
        signed = mint()
        self.assertEqual(len(signed.signature), 128)
        self.assertEqual(
            verify(signed, expected_signer_id="verifier-svc"), ())

    def test_signer_need_not_equal_operator(self):
        # The structural divergence from attestation: the
        # verifier signs ABOUT the operator.
        signed = mint()
        self.assertNotEqual(signed.signer_id, signed.operator_id)
        self.assertEqual(verify(signed), ())

    def test_authorisation_id_derivation(self):
        signed = mint()
        self.assertEqual(
            signed.authorisation_id,
            authorisation_id_for(signed.payload_hash, signed.key_id))

    def test_ttl_default_and_hard_cap(self):
        signed = mint()
        start = datetime.fromisoformat(signed.signed_at)
        end = datetime.fromisoformat(signed.expires_at)
        self.assertEqual((end - start).total_seconds(), 900)
        capped = mint(ttl_seconds=172800)
        start = datetime.fromisoformat(capped.signed_at)
        end = datetime.fromisoformat(capped.expires_at)
        self.assertEqual((end - start).total_seconds(),
                         CEREMONY_AUTHORISATION_TTL_MAX_SECONDS)
        shorter = mint(ttl_seconds=120)
        start = datetime.fromisoformat(shorter.signed_at)
        end = datetime.fromisoformat(shorter.expires_at)
        self.assertEqual((end - start).total_seconds(), 120)

    def test_signature_mismatch(self):
        signed = mint()
        tampered = replace(signed, signature="0" * 128)
        self.assertIn("signature_mismatch", verify(tampered))

    def test_hand_constructed_v1_length_signature_folds_to_mismatch(self):
        # A typed envelope can bypass from_dict; a hex64
        # (v1-length) signature must fold into signature_mismatch,
        # never raise.
        signed = mint()
        tampered = replace(signed, signature="0" * 64)
        self.assertIn("signature_mismatch", verify(tampered))

    def test_unknown_key(self):
        signed = mint()
        reasons = verify_ceremony_authorisation(
            signed, public_key=ATTACKER_PIN, now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)

    def test_payload_hash_mismatch(self):
        signed = mint()
        tampered = replace(signed, payload_hash="d" * 64)
        self.assertIn("payload_hash_mismatch", verify(tampered))

    def test_authorisation_id_mismatch(self):
        signed = mint()
        tampered = replace(signed, authorisation_id="d" * 64)
        self.assertIn("authorisation_id_mismatch", verify(tampered))

    def test_malformed_payload_reason(self):
        signed = mint()
        tampered = replace(signed, evidence_ref="")
        self.assertIn("malformed_payload", verify(tampered))

    def test_binding_mismatches(self):
        signed = mint()
        cases = [
            ({"expected_signer_id": "other-svc"}, "signer_mismatch"),
            ({"expected_operator_id": "operator-x"},
             "operator_mismatch"),
            ({"expected_ceremony_id": "ceremony-x"},
             "ceremony_mismatch"),
            ({"expected_reason": "lost_pin"}, "reason_mismatch"),
            ({"expected_candidate": dict(CANDIDATE, cycle_seq=48)},
             "candidate_mismatch"),
            ({"expected_evidence_hash": "d" * 64},
             "evidence_mismatch"),
            ({"expected_evidence_ref": "other-ref"},
             "evidence_ref_mismatch"),
        ]
        for kwargs, reason in cases:
            reasons = verify(signed, **kwargs)
            self.assertIn(reason, reasons, msg=kwargs)

    def test_old_pin_sentinel_semantics(self):
        signed = mint()
        # Omitted: asserts nothing.
        self.assertEqual(verify(signed), ())
        # Exact dict: matches.
        self.assertEqual(
            verify(signed, expected_old_pin=dict(OLD_PIN)), ())
        # Explicit None against a pin-carrying envelope: mismatch.
        reasons = verify(signed, expected_old_pin=None)
        self.assertIn("old_pin_mismatch", reasons)
        # Wrong pin: mismatch.
        reasons = verify(
            signed, expected_old_pin={"cycle_seq": 40,
                                      "payload_hash": OLD_HASH})
        self.assertIn("old_pin_mismatch", reasons)
        # And on a no-pin envelope, explicit None matches.
        no_pin = mint(reason="initial_anchor", old_pin=None)
        self.assertEqual(
            verify(no_pin, expected_old_pin=None), ())

    def test_expired_and_signed_in_future(self):
        signed = mint()
        later = (datetime.fromisoformat(NOW)
                 + timedelta(seconds=901)).isoformat()
        self.assertIn("expired", verify(signed, now=later))
        earlier = (datetime.fromisoformat(NOW)
                   - timedelta(seconds=301)).isoformat()
        self.assertIn(
            "signed_in_future", verify(signed, now=earlier))

    def test_verify_rejects_non_envelope(self):
        with self.assertRaises(SigningError):
            verify_ceremony_authorisation(
                {"not": "an envelope"}, public_key=VERIFIER_PIN,
                now=NOW)

    def test_field_tamper_matrix(self):
        # Each payload field mutated on an otherwise genuine
        # envelope: verification must refuse (signature_mismatch
        # or a binding/projection reason), never accept.
        signed = mint()
        tampers = [
            replace(signed, operator_id="operator-x"),
            replace(signed, ceremony_id="ceremony-x"),
            replace(signed, reason="lost_pin", old_pin=None),
            replace(signed, evidence_hash="d" * 64),
            replace(signed, evidence_ref="other-ref"),
            replace(signed, signer_id="other-svc"),
            replace(signed, candidate=dict(CANDIDATE, cycle_seq=48)),
            replace(signed, signed_at="2026-11-28T09:59:00+00:00"),
            replace(signed, key_id=ATTACKER_KEY.key_id),
        ]
        for tampered in tampers:
            self.assertNotEqual(verify(tampered), (),
                                msg=tampered)


class KeySubstitutionTests(unittest.TestCase):
    """Adversarial (a): substitution produces refusal (DoS),
    never acceptance, in either direction."""

    def test_genuine_envelope_against_attacker_pin_refused(self):
        signed = mint()
        reasons = verify_ceremony_authorisation(
            signed, public_key=ATTACKER_PIN, now=NOW)
        self.assertIn("unknown_key", reasons)
        self.assertNotEqual(reasons, ())

    def test_attacker_minted_envelope_against_true_pin_refused(self):
        # The attacker mints, under their own seed, an envelope
        # for the EXACT real event (every field identical).
        forged = mint(signing_key=ATTACKER_KEY)
        self.assertEqual(forged.ceremony_id, mint().ceremony_id)
        reasons = verify(forged)
        self.assertIn("unknown_key", reasons)
        self.assertIn("signature_mismatch", reasons)


class LocalMintingTests(unittest.TestCase):
    """Adversarial (b): the attacker holds EVERYTHING the
    ceremony process holds — the pinned public key, the snapshot
    SigningKey, all payload code, the exact event fields. In
    cycle 19 that material sufficed to mint; here every variant
    must fail. This is the regression test for the cycle-19
    defect itself."""

    def test_hmac_forgery_with_snapshot_key_fails(self):
        genuine = mint()
        # The best cycle-19 construction: HMAC under the held
        # snapshot key over the v1 blob for this exact event.
        blob = ("signed-ceremony-authorisation-v1\nhmac-sha256\n"
                + SNAPSHOT_KEY.key_id + "\n"
                + genuine.payload_hash).encode("utf-8")
        mac = hmac.new(SNAPSHOT_KEY.key, blob,
                       hashlib.sha256).hexdigest()
        for signature in (mac, mac + mac):  # hex64, and padded hex128
            forged = replace(genuine, signature=signature)
            self.assertIn("signature_mismatch", verify(forged))

    def test_hmac_forgery_with_public_key_bytes_fails(self):
        genuine = mint()
        blob = ("signed-ceremony-authorisation-v2\ned25519\n"
                + genuine.key_id + "\n"
                + genuine.payload_hash).encode("utf-8")
        mac = hmac.new(VERIFIER_PIN.public_key, blob,
                       hashlib.sha256).hexdigest()
        forged = replace(genuine, signature=mac + mac)
        self.assertIn("signature_mismatch", verify(forged))

    def test_self_seed_ed25519_forgery_fails(self):
        # Ed25519 under a self-generated seed, exact event fields,
        # even claiming the verifier's key_id in the envelope:
        # the signature is made over the attacker's blob/key, so
        # presenting it under the true pin fails — and re-deriving
        # the authorisation id for the claimed key cannot save it.
        genuine = mint()
        blob = ("signed-ceremony-authorisation-v2\ned25519\n"
                + genuine.key_id + "\n"
                + genuine.payload_hash).encode("utf-8")
        forged = replace(
            genuine,
            signature=ed_sign(ATTACKER_KEY.seed, blob).hex())
        reasons = verify(forged)
        self.assertIn("signature_mismatch", reasons)
        self.assertNotIn("unknown_key", reasons)

    def test_copied_signature_from_another_event_fails(self):
        other = mint(ceremony_id="ceremony-2026-11-28-002")
        genuine = mint()
        forged = replace(genuine, signature=other.signature)
        self.assertIn("signature_mismatch", verify(forged))
        # And the donor envelope itself does not bind to this
        # event.
        reasons = verify(
            other, expected_ceremony_id=genuine.ceremony_id)
        self.assertIn("ceremony_mismatch", reasons)


# A literal cycle-19 (v1) envelope dict: HMAC-era key id
# ("key-…" over secret bytes) and a hex64 HMAC signature.
GOLDEN_V1_ENVELOPE = {
    "operator_id": "operator-uma",
    "ceremony_id": "ceremony-2026-11-28-001",
    "reason": "chain_gap_recovery",
    "old_pin": {"cycle_seq": 41, "payload_hash": OLD_HASH},
    "candidate": dict(CANDIDATE),
    "evidence_hash": EVIDENCE_HASH,
    "evidence_ref": "case-file-1",
    "signer_id": "verifier-svc",
    "key_id": "key-0123456789abcdef",
    "signed_at": NOW,
    "expires_at": "2026-11-28T10:15:00+00:00",
    "payload_hash": "d" * 64,
    "authorisation_id": "e" * 64,
    "signature": "f" * 64,
}


class NoFallbackTests(unittest.TestCase):
    """Adversarial (c): no HMAC fallback, by construction."""

    def test_golden_v1_envelope_refused_naming_superseded_version(self):
        with self.assertRaises(SigningError) as ctx:
            ceremony_authorisation_envelope_from_dict(
                dict(GOLDEN_V1_ENVELOPE))
        message = str(ctx.exception)
        self.assertIn("version 1", message)
        self.assertIn("superseded", message)

    def test_v1_refusal_precedes_signature_format_check(self):
        # The v1 fixture's signature is hex64: if the hex128
        # format check ran first, the error would be the format
        # wording instead of the version wording.
        with self.assertRaises(SigningError) as ctx:
            ceremony_authorisation_envelope_from_dict(
                dict(GOLDEN_V1_ENVELOPE))
        self.assertNotIn("hex128", str(ctx.exception))

    def test_alg_flip_to_hmac_sha256_is_malformed_payload(self):
        signed = mint()
        flipped = replace(signed, alg="hmac-sha256")
        self.assertEqual(verify(flipped), ("malformed_payload",))
        with self.assertRaises(SigningError):
            ceremony_authorisation_payload(
                **payload_kwargs(alg="hmac-sha256"))

    def test_module_does_not_import_hmac(self):
        source = (Path(__file__).resolve().parents[1]
                  / "signing" / "ceremony_authorisation.py")
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("import hmac", text)
        self.assertNotIn("hmac.", text)
        self.assertNotIn("_mac", text)

    def test_verify_parameter_is_public_key_not_signing_key(self):
        import inspect
        params = inspect.signature(
            verify_ceremony_authorisation).parameters
        self.assertIn("public_key", params)
        self.assertNotIn("signing_key", params)


class SerialisationTests(unittest.TestCase):
    def test_dict_round_trip(self):
        signed = mint()
        restored = ceremony_authorisation_envelope_from_dict(
            ceremony_authorisation_envelope_to_dict(signed))
        self.assertEqual(restored, signed)

    def test_json_round_trip(self):
        signed = mint()
        restored = ceremony_authorisation_envelope_from_json(
            ceremony_authorisation_envelope_to_json(signed))
        self.assertEqual(restored, signed)

    def test_no_pin_dict_round_trip(self):
        signed = mint(reason="lost_pin", old_pin=None)
        envelope = ceremony_authorisation_envelope_to_dict(signed)
        self.assertIsNone(envelope["old_pin"])
        self.assertEqual(
            ceremony_authorisation_envelope_from_dict(envelope),
            signed)

    def test_signature_is_hex128(self):
        envelope = ceremony_authorisation_envelope_to_dict(mint())
        self.assertEqual(len(envelope["signature"]), 128)
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, signature="zz" * 64))
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, payload_hash="zz"))

    def test_strict_key_sets(self):
        envelope = ceremony_authorisation_envelope_to_dict(mint())
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, extra=1))
        shrunk = dict(envelope)
        del shrunk["reason"]
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(shrunk)
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, old_pin=dict(OLD_PIN, key_id="k")))
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                dict(envelope, candidate={"cycle_seq": 47}))

    def test_json_strictness(self):
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json(
                '{"operator_id":"a","operator_id":"b"}')
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json("not json")
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_json(42)

    def test_domain_separation_from_attestation(self):
        # An attestation envelope dict is not a ceremony
        # authorisation envelope (strict key sets differ).
        signed = mint()
        envelope = ceremony_authorisation_envelope_to_dict(signed)
        attestation_shaped = dict(envelope)
        attestation_shaped["attestation"] = attestation_shaped.pop(
            "operator_id")
        with self.assertRaises(SigningError):
            ceremony_authorisation_envelope_from_dict(
                attestation_shaped)


if __name__ == "__main__":
    unittest.main()
