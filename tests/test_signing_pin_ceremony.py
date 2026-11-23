"""Tests for signing/pin_ceremony.py (cycle 15).

The ceremony is the recovery path cycle 14's chain-gap refusal
requires: authorised, evidence-bound, MAC-audited re-anchoring.
These tests pin the happy paths, every refusal condition, the
caller classification contract, and the adversarial shapes
(ceremony-as-bypass, self-derived evidence, backwards moves,
tampered audit records).

Cycle 19: authority is a verifier-issued ceremony authorisation
envelope. The ``reanchor()`` helper below mints envelopes
IN-PROCESS with a distinct test verifier key — that is a
binding fixture only: it exercises MAC/expiry/exact-binding,
and is never evidence the authority path works (issuance-side
authority — env list, ledgers — is proven only by the
subprocess E2E in test_trust_ceremony_authorisation.py).

Cycle 20: the envelope is Ed25519 (asymmetric) — the helper
mints in-process with a ``CeremonySigningKey`` built from a
test seed (NOT an RFC 8032 vector seed), and the ceremony
verifies under the matching pinned ``CeremonyPublicKey``,
which holds public bytes only. ``ceremony_history`` is a
required keyword of ``reanchor_pin``; the helper below supplies
an explicit ``ceremony_history=()`` default IN THE HELPER ONLY
so existing cases stay readable — the function itself has no
default (pinned by test T1).

Cycle 21: ``consume_authorisation`` is likewise a required
keyword of ``reanchor_pin`` with no default (T1b). The helper's
DEFAULT consumer is a REAL CeremonyConsumptionLedger-backed
consumer over a fixture-scoped temp dir (one ledger per test
fixture, reset in each consuming class's setUp, NOT per call),
never an always-succeed fake (DESIGN-FINAL R12). Tests needing
continuity share one consumer explicitly; tests whose semantics
assumed no consumption pass a fresh fixture consumer explicitly
and are noted in the build report. Fakes appear only where the
test's subject is the fake itself (spy/counting consumers,
T-Cc's commit-then-raise consumer).
"""
import inspect
import json
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import SigningError, make_signing_key
from signing.ceremony_authorisation import (
    CEREMONY_AUTHORISATION_DOMAIN,
    PURPOSE_CEREMONY_AUTHORISATION,
    CeremonyPublicKey,
    CeremonySigningKey,
    authorisation_id_for,
    ceremony_authorisation_envelope_from_dict,
    ceremony_authorisation_envelope_to_dict,
    public_key_id_for,
    sign_ceremony_authorisation)
from signing.ceremony_authorisation import (
    _payload_hash as _authorisation_payload_hash)
from signing.ed25519 import public_key_from_seed, sign as _ed25519_sign
from signing.pin_ceremony import (
    advance_pin, classify_verification, reanchor_pin,
    verify_ceremony_record)
from signing.state_snapshot import sign_state_snapshot
from trust.ledger import CeremonyConsumptionLedger, LedgerError

KEY = make_signing_key(bytes(range(32, 64)))


def _ceremony_signing_key(seed):
    """Seat A's v2 minting key, in-process from a test seed."""
    public_key = public_key_from_seed(seed)
    return CeremonySigningKey(
        seed=seed, public_key=public_key,
        key_id=public_key_id_for(public_key))


def _ceremony_public_key(signing_key):
    return CeremonyPublicKey(
        public_key=signing_key.public_key, key_id=signing_key.key_id)


# The verifier's ceremony key pair: DISTINCT seed from the
# snapshot key. Separation is now type/role separation (cycle
# 20): the ceremony side holds only VERIFIER_PUBLIC_KEY.
VERIFIER_SEED = bytes(range(160, 192))
VERIFIER_SIGNING_KEY = _ceremony_signing_key(VERIFIER_SEED)
VERIFIER_PUBLIC_KEY = _ceremony_public_key(VERIFIER_SIGNING_KEY)
# An attacker's ceremony key pair, for key-substitution tests.
ATTACKER_SEED = bytes(range(192, 224))
ATTACKER_SIGNING_KEY = _ceremony_signing_key(ATTACKER_SEED)
ATTACKER_PUBLIC_KEY = _ceremony_public_key(ATTACKER_SIGNING_KEY)
VERIFIER_SIGNER = "verifier-svc"
SIGNER = "seat-3"
NOW = "2026-11-20T12:00:00+00:00"
OPERATOR = "operator-1"
EVIDENCE = "e" * 64
EVIDENCE_REF = "evidence-bundle-1"

_mint_counter = [0]
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def state_bytes(cycle_seq):
    history = [{"cycle_id": i, "item_id": "core-loop-v1",
                "completed_at": "2026-11-20T05:11:13+00:00"}
               for i in range(1, cycle_seq + 1)]
    doc = {"schema_version": 1, "cycle_seq": cycle_seq, "phase": "SCAN",
           "backlog": [], "history": history, "deltas": [],
           "history_pruned": 0, "deltas_pruned": 0, "current_item_id": None}
    return json.dumps(doc, sort_keys=True).encode()


CAL = b'{"log":1}'


def snap(seq, prev=""):
    return sign_state_snapshot(state_bytes(seq), signing_key=KEY,
                               signer_id=SIGNER, calibration_bytes=CAL,
                               prev_snapshot_hash=prev, now=NOW)


def pin_of(s):
    return {"cycle_seq": s.cycle_seq, "payload_hash": s.payload_hash,
            "key_id": s.key_id, "signer_id": s.signer_id}


def _project_old_pin(old):
    """Project a full pin down to the envelope's exact
    {cycle_seq, payload_hash} shape (extra keys refuse loudly
    verifier-side). Returns None when there is no usable pin
    projection (no pin, or a malformed pin dict)."""
    if not isinstance(old, dict):
        return None
    seq, payload_hash = old.get("cycle_seq"), old.get("payload_hash")
    if not isinstance(seq, int) or isinstance(seq, bool) \
            or not isinstance(payload_hash, str) \
            or not _HEX64_RE.fullmatch(payload_hash):
        return None
    return {"cycle_seq": seq, "payload_hash": payload_hash}


def mint_authorisation(old, cand, *, operator_id=OPERATOR,
                       reason="chain_gap_recovery",
                       evidence_hash=EVIDENCE, now=NOW,
                       key=VERIFIER_SIGNING_KEY,
                       signer_id=VERIFIER_SIGNER,
                       old_pin="project"):
    """Mint an in-process authorisation envelope (binding
    fixture only — see the module docstring). ``old_pin`` is
    "project" (project the ceremony's old pin), None, or an
    explicit projection dict."""
    _mint_counter[0] += 1
    if old_pin == "project":
        old_pin = _project_old_pin(old)
    candidate = {"cycle_seq": cand.cycle_seq,
                 "payload_hash": cand.payload_hash,
                 "signer_id": cand.signer_id, "key_id": cand.key_id}
    return sign_ceremony_authorisation(
        signing_key=key, signer_id=signer_id, operator_id=operator_id,
        ceremony_id=f"ceremony-test-{_mint_counter[0]}",
        reason=reason, old_pin=old_pin, candidate=candidate,
        evidence_hash=evidence_hash, evidence_ref=EVIDENCE_REF,
        now=now)


def remac_authorisation(auth):
    """Re-sign a hand-built envelope under the test verifier seed.

    The hash is computed over the RAW payload projection, not
    via ``auth.payload()``: for the un-mintable events below,
    ``payload()`` itself raises (its validation mirrors the
    ceremony's own rules), which is exactly why those events
    can never carry a verifying envelope. For a mintable
    payload the raw projection is identical to ``payload()``'s
    output, so the re-signed envelope verifies clean."""
    raw = {
        "v": "signed-ceremony-authorisation/2", "alg": "ed25519",
        "purpose": PURPOSE_CEREMONY_AUTHORISATION,
        "signer_id": auth.signer_id, "key_id": auth.key_id,
        "operator_id": auth.operator_id,
        "ceremony_id": auth.ceremony_id, "reason": auth.reason,
        "old_pin": auth.old_pin, "candidate": auth.candidate,
        "evidence_hash": auth.evidence_hash,
        "evidence_ref": auth.evidence_ref,
        "signed_at": auth.signed_at, "expires_at": auth.expires_at,
    }
    payload_hash = _authorisation_payload_hash(raw)
    blob = (CEREMONY_AUTHORISATION_DOMAIN + "\n" + "ed25519" + "\n"
            + auth.key_id + "\n" + payload_hash).encode("utf-8")
    return replace(
        auth, payload_hash=payload_hash,
        authorisation_id=authorisation_id_for(payload_hash,
                                              auth.key_id),
        signature=_ed25519_sign(VERIFIER_SEED, blob).hex())


def hand_authorisation(old, cand, *, reason, evidence_hash=EVIDENCE):
    """An envelope bound to the ACTUAL event, however
    un-mintable: take a mintable envelope for the candidate,
    ``replace`` its reason / old pin / evidence with the
    event's own, and re-MAC under the test verifier key (the
    construction pattern of
    test_malformed_evidence_case_is_now_tampered_envelope,
    completed with a re-MAC). Whether the ceremony then
    reaches the check a test names depends on the envelope
    verifier's own payload validation — see the re-scoped
    tests below."""
    base = mint_authorisation(None, cand, reason="lost_pin",
                              old_pin=None)
    return remac_authorisation(replace(
        base, reason=reason, old_pin=_project_old_pin(old),
        evidence_hash=evidence_hash))


class LedgerBackedConsumer:
    """Test-local adapter (R12): the real consumer over a
    fixture-scoped temp dir. Each call opens a FRESH
    CeremonyConsumptionLedger instance over the same on-disk
    dir, so a refusal can only come from what the journal
    persisted — never from in-memory state carried between
    calls. LedgerError is translated to SigningError, which
    is reanchor_pin's refusal vocabulary (the production
    adapter in trust/client.py does the same translation
    for Verifier* errors)."""

    def __init__(self, journal_dir):
        self.journal_dir = Path(journal_dir)

    def __call__(self, authorisation):
        ledger = CeremonyConsumptionLedger(self.journal_dir)
        try:
            ledger.append_consumption(authorisation,
                                      recorded_at=NOW)
        except LedgerError as exc:
            raise SigningError(str(exc)) from exc
        return None

    def entries(self):
        return CeremonyConsumptionLedger(self.journal_dir).entries()


_fixture_tempdirs = []
_DEFAULT_CONSUMER = None


def _fresh_fixture_consumer():
    """A real ledger-backed consumer over a NEW fixture temp
    dir (kept alive for the process). Used explicitly by
    tests whose semantics assumed no prior consumption."""
    td = tempfile.TemporaryDirectory()
    _fixture_tempdirs.append(td)
    return LedgerBackedConsumer(td.name)


def _reset_fixture_consumer():
    """Per-fixture reset (each consuming class's setUp): the
    helper default becomes a real ledger-backed consumer over
    a fresh fixture-scoped temp dir, shared by every
    reanchor() call within the test."""
    global _DEFAULT_CONSUMER
    _DEFAULT_CONSUMER = _fresh_fixture_consumer()
    return _DEFAULT_CONSUMER


def _default_consumer():
    global _DEFAULT_CONSUMER
    if _DEFAULT_CONSUMER is None:
        _reset_fixture_consumer()
    return _DEFAULT_CONSUMER


def reanchor(old, cand, **kw):
    kw.setdefault("signing_key", KEY)
    kw.setdefault("state_bytes", state_bytes(cand.cycle_seq))
    kw.setdefault("calibration_bytes", CAL)
    kw.setdefault("expected_signer_id", SIGNER)
    kw.setdefault("operator_id", OPERATOR)
    kw.setdefault("reason", "chain_gap_recovery")
    if kw["reason"] == "chain_gap_recovery":
        kw.setdefault("strict_reasons", ("chain_gap",))
    kw.setdefault("evidence_hash", EVIDENCE)
    kw.setdefault("now", NOW)
    kw.setdefault("authorisation_public_key", VERIFIER_PUBLIC_KEY)
    kw.setdefault("expected_verifier_signer_id", VERIFIER_SIGNER)
    # Helper-only default (design-c §6): existing cases stay
    # readable; reanchor_pin itself has NO default for
    # ceremony_history — omitting it there is a TypeError (T1).
    kw.setdefault("ceremony_history", ())
    # Helper-only default (R12): a REAL ledger-backed consumer
    # over the fixture-scoped temp dir — never an
    # always-succeed fake; reanchor_pin itself has NO default
    # for consume_authorisation (T1b).
    kw.setdefault("consume_authorisation", _default_consumer())
    if "authorisation" not in kw:
        # Mint now= MUST equal the ceremony's now= (one clock per
        # call): cycle-16 tests reanchor at LATER, and a 900 s TTL
        # envelope minted at NOW would be expired by then.
        try:
            kw["authorisation"] = mint_authorisation(
                old, cand, operator_id=kw["operator_id"],
                reason=kw["reason"], evidence_hash=kw["evidence_hash"],
                now=kw["now"])
        except SigningError:
            # The ceremony's own parameters are un-mintable (bad
            # reason, candidate-derived evidence, a non-gap
            # relation, a malformed pin...). Fall back to a
            # genuine envelope bound to a DIFFERENT event, so the
            # refusal assertion still targets reanchor_pin's
            # binding checks rather than the mint.
            kw["authorisation"] = mint_authorisation(
                None, cand, operator_id=kw["operator_id"],
                reason="lost_pin", evidence_hash=EVIDENCE,
                now=kw["now"], old_pin=None)
    return reanchor_pin(old, cand, **kw)


class ClassifyTests(unittest.TestCase):
    def test_classification_contract(self):
        self.assertEqual(classify_verification(()), "ok")
        self.assertEqual(classify_verification(("chain_gap",)),
                         "reanchor_required")
        for bad in [("expired",), ("chain_gap", "expired"),
                    ("signature_mismatch",), ("pin_mismatch",)]:
            self.assertEqual(classify_verification(bad),
                             "integrity_failure", bad)


class AdvanceTests(unittest.TestCase):
    def test_advance_one_step(self):
        a, b = snap(1), None
        b = snap(2, prev=a.payload_hash)
        self.assertEqual(advance_pin(pin_of(a), b, ()), pin_of(b))

    def test_advance_idempotent_same(self):
        a = snap(1)
        self.assertEqual(advance_pin(pin_of(a), a, ()), pin_of(a))

    def test_advance_refusals(self):
        a = snap(1)
        gap = snap(3, prev="f" * 64)
        unchained = snap(2, prev="f" * 64)
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), gap, ())
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), unchained, ())
        with self.assertRaises(SigningError):
            advance_pin(pin_of(a), snap(2, prev=a.payload_hash),
                        ("chain_gap",))


class ReanchorTests(unittest.TestCase):
    def setUp(self):
        _reset_fixture_consumer()

    def test_gap_recovery_happy(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        new_pin, rec = reanchor(pin_of(a), cand)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual((rec.gap_from_seq, rec.gap_to_seq), (2, 3))
        self.assertEqual(verify_ceremony_record(rec, signing_key=KEY), ())

    def test_initial_anchor(self):
        cand = snap(2)
        new_pin, rec = reanchor(None, cand, reason="initial_anchor")
        self.assertEqual(new_pin, pin_of(cand))
        self.assertIsNone(rec.gap_from_seq)

    def test_lost_pin_recovery(self):
        cand = snap(3)
        _, rec = reanchor(None, cand, reason="lost_pin")
        self.assertEqual(rec.reason, "lost_pin")

    def test_refusals(self):
        a, cand = snap(2), snap(5, prev="f" * 64)
        cases = [
            dict(reason="routine_bypass"),                # bad reason
            dict(evidence_hash=cand.state_sha256),        # self-derived
            dict(expected_signer_id="seat-9"),            # signer mismatch
            dict(calibration_bytes=b'{"log":2}'),         # calibration mismatch
        ]
        for kw in cases:
            with self.assertRaises(SigningError, msg=str(kw)):
                reanchor(pin_of(a), cand, **kw)
        # The candidate-payload evidence leg is NOT in the loop
        # above: it is split out into
        # test_refusals_candidate_payload_evidence_case_is_now_
        # envelope_verification_refusal below, because it cannot
        # reach the step-5 check the loop's other self-derived
        # leg (state_sha256) reaches.

    def test_refusals_state_hash_evidence_reaches_independence_check(self):
        # The state_sha256 leg IS mintable (the envelope payload
        # rule refuses only evidence == candidate PAYLOAD hash),
        # so this leg reaches the ceremony's step-5 non-equality
        # check itself — assert its specific refusal message.
        a, cand = snap(2), snap(5, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand,
                     evidence_hash=cand.state_sha256)
        self.assertIn(
            "ceremony evidence must be independent of the candidate",
            str(cm.exception))

    def test_refusals_candidate_payload_evidence_case_is_now_envelope_verification_refusal(self):
        # Re-scoped (rev-r4 F1): the payload_hash leg originally
        # named the step-5 independence check ("ceremony evidence
        # must be independent of the candidate"), but that check
        # is UNREACHABLE for this leg even with a hand-constructed
        # envelope: the envelope payload validation refuses
        # evidence == candidate payload hash, so an envelope
        # bound to the actual event fails verification as
        # malformed_payload before binding or step 5 ever run.
        # This test therefore exercises the envelope-verification
        # refusal the leg actually reaches, with an envelope
        # hand-bound to the actual event (replace + re-MAC).
        a, cand = snap(2), snap(5, prev="f" * 64)
        auth = hand_authorisation(
            pin_of(a), cand, reason="chain_gap_recovery",
            evidence_hash=cand.payload_hash)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand,
                     evidence_hash=cand.payload_hash,
                     authorisation=auth)
        self.assertIn(
            "ceremony authorisation does not verify: "
            "['malformed_payload']", str(cm.exception))

    def test_operator9_case_is_now_binding_mismatch(self):
        # Cycle 19 conversion: there is no in-ceremony
        # "unauthorised operator" refusal left to test here —
        # unlisted-operator refusal lives verifier-side (seat B's
        # mode tests / the E2E). In-process, an envelope minted
        # for operator-9 presented to a ceremony run as
        # operator-1 refuses on exact binding.
        a, cand = snap(2), snap(5, prev="f" * 64)
        auth9 = mint_authorisation(pin_of(a), cand,
                                   operator_id="operator-9")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth9)
        self.assertIn("different operator", str(cm.exception))

    def test_malformed_evidence_case_is_now_tampered_envelope(self):
        # Cycle 19 conversion: evidence_hash="xyz" can no longer
        # reach the ceremony as a mintable envelope (the mint
        # itself refuses malformed hex64), so the malformed-
        # evidence case is rewritten as a TAMPERED envelope:
        # mint valid, then swap the evidence — the ceremony
        # refuses, via payload re-derivation / binding.
        a, cand = snap(2), snap(5, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        for bad_evidence in ("xyz", "f" * 64):
            tampered = replace(auth, evidence_hash=bad_evidence)
            with self.assertRaises(SigningError, msg=bad_evidence):
                reanchor(pin_of(a), cand, authorisation=tampered)

    def test_no_backwards_or_same_seq_case_is_now_envelope_verification_refusal(self):
        # Re-scoped (rev-r4 F1): this test originally named the
        # relation refusal ("re-anchor never moves a pin
        # backwards or replaces a pin at the same sequence"),
        # but that check is UNREACHABLE for backwards and
        # same-seq candidates even with a hand-constructed
        # envelope: the envelope payload validation is gap-only
        # (candidate cycle_seq must be at least old_pin
        # cycle_seq + 2), so an envelope bound to the actual
        # event fails verification as malformed_payload before
        # the relation check ever runs. Both legs below use
        # envelopes hand-bound to the actual event (replace +
        # re-MAC) and assert the envelope-verification refusal
        # they actually reach — NOT the helper fallback's
        # "different reason" binding mismatch.
        a = snap(3)
        for cand in (snap(2), snap(3, prev="f" * 64)):
            auth = hand_authorisation(pin_of(a), cand,
                                      reason="chain_gap_recovery")
            with self.assertRaises(SigningError,
                                   msg=f"seq {cand.cycle_seq}") as cm:
                reanchor(pin_of(a), cand, authorisation=auth)
            self.assertIn(
                "ceremony authorisation does not verify: "
                "['malformed_payload']", str(cm.exception))

    def test_ceremony_not_for_normal_advance_case_is_now_envelope_verification_refusal(self):
        # Re-scoped (rev-r4 F1): this test originally named the
        # successor refusal ("candidate is the pin's chained
        # successor; use advance_pin, not the ceremony"), but
        # that check is UNREACHABLE for a chained successor even
        # with a hand-constructed envelope: the envelope payload
        # validation is gap-only (candidate cycle_seq must be at
        # least old_pin cycle_seq + 2), so an envelope bound to
        # the actual successor event fails verification as
        # malformed_payload before the relation check ever runs.
        a = snap(1)
        nxt = snap(2, prev=a.payload_hash)
        auth = hand_authorisation(pin_of(a), nxt,
                                  reason="chain_gap_recovery")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), nxt, authorisation=auth)
        self.assertIn(
            "ceremony authorisation does not verify: "
            "['malformed_payload']", str(cm.exception))

    def test_reason_pin_coherence_case_is_now_envelope_verification_refusal(self):
        # Re-scoped (rev-r4 F1): this test originally named the
        # ceremony's reason/pin coherence refusals ("with an
        # existing pin the only ceremony reason is
        # chain_gap_recovery" / "chain_gap_recovery requires an
        # existing pin"), but both are UNREACHABLE even with
        # hand-constructed envelopes: the envelope payload
        # validation mirrors the same coherence rule (a no-pin
        # reason requires no pin; an old pin requires
        # chain_gap_recovery), so an envelope bound to either
        # actual event fails verification as malformed_payload
        # before the ceremony's coherence gate ever runs. Both
        # legs use envelopes hand-bound to the actual event
        # (replace + re-MAC) and assert the envelope-verification
        # refusal they actually reach.
        cand = snap(2)
        auth = hand_authorisation(pin_of(snap(1)), cand,
                                  reason="initial_anchor")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(snap(1)), cand, reason="initial_anchor",
                     authorisation=auth)
        self.assertIn(
            "ceremony authorisation does not verify: "
            "['malformed_payload']", str(cm.exception))
        auth = hand_authorisation(None, cand,
                                  reason="chain_gap_recovery")
        with self.assertRaises(SigningError) as cm:
            reanchor(None, cand, reason="chain_gap_recovery",
                     authorisation=auth)
        self.assertIn(
            "ceremony authorisation does not verify: "
            "['malformed_payload']", str(cm.exception))

    def test_tampered_candidate_refused(self):
        a = snap(1)
        cand = replace(snap(4, prev="f" * 64), cycle_seq=4,
                       signature="0" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand)

    def test_fix_round_cycle15_fork_case_is_now_envelope_verification_refusal(self):
        # Re-scoped (rev-r4 F1): the first leg of
        # test_fix_round_cycle15 originally named the
        # successor-fork refusal ("candidate at pin+1 does not
        # chain to the pin; that is an integrity failure, not a
        # re-anchor case"), but that check is UNREACHABLE for a
        # pin+1 fork relabelled lost_pin even with a
        # hand-constructed envelope, for two independent reasons:
        # the envelope payload validation refuses it twice over
        # (an old pin requires reason chain_gap_recovery, and
        # the gap-only rule requires candidate cycle_seq >=
        # old_pin cycle_seq + 2), so an envelope bound to the
        # actual event fails verification as malformed_payload;
        # and in reanchor_pin's own order the reason/pin
        # coherence gate precedes the relation check anyway.
        # This leg therefore asserts the envelope-verification
        # refusal it actually reaches, with an envelope
        # hand-bound to the actual event (replace + re-MAC).
        a = snap(1)
        fork = snap(2, prev="f" * 64)
        auth = hand_authorisation(pin_of(a), fork, reason="lost_pin")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), fork, reason="lost_pin",
                     authorisation=auth)
        self.assertIn(
            "ceremony authorisation does not verify: "
            "['malformed_payload']", str(cm.exception))

    def test_fix_round_cycle15(self):
        a = snap(1)
        # The pin+1-fork first leg is split out into
        # test_fix_round_cycle15_fork_case_is_now_envelope_
        # verification_refusal above (rev-r4 F1 re-scope).
        # Forced-dissent: gap recovery gated on a real chain_gap.
        cand = snap(4, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, strict_reasons=None)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, strict_reasons=("expired",))
        # rev-r5 branches: calibration-hash evidence, wrong key,
        # malformed old pin, corrupted_pin happy path.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand,
                     evidence_hash=cand.calibration_sha256)
        with self.assertRaises(SigningError):
            reanchor({"cycle_seq": "x", "payload_hash": "z"}, cand)
        _, rec = reanchor(None, snap(3), reason="corrupted_pin")
        other = make_signing_key(b"\xff" * 32)
        self.assertEqual(verify_ceremony_record(rec, signing_key=other),
                         ("unknown_key", "signature_mismatch"))
        # classify: duplicates and list input are not reanchor_required.
        self.assertEqual(classify_verification(("chain_gap", "chain_gap")),
                         "integrity_failure")
        self.assertEqual(classify_verification(["chain_gap"]),
                         "reanchor_required")

    def test_rev_r2_round(self):
        a = snap(1)
        nxt = snap(2, prev=a.payload_hash)
        gap = snap(4, prev="f" * 64)
        # F1: relabelling cannot launder a jump or a routine advance.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), nxt, reason="lost_pin")
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), gap, reason="corrupted_pin")
        # F2: snapshot_id is candidate-derived evidence.
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), gap, evidence_hash=gap.snapshot_id)
        # F3: advance_pin honours the pin's signer binding.
        bad_pin = pin_of(a)
        bad_pin["signer_id"] = "evil-9"
        with self.assertRaises(SigningError):
            advance_pin(bad_pin, nxt, ())
        # F4: a signed record violating ceremony invariants fails.
        _, rec = reanchor(pin_of(a), gap)
        bad_rec = replace(rec, reason="lost_pin")
        self.assertIn("invalid_reason",
                      verify_ceremony_record(bad_rec, signing_key=KEY))

    def test_audit_record_tamper_detected(self):
        _, rec = reanchor(None, snap(2), reason="initial_anchor")
        bad = replace(rec, operator_id="operator-2")
        self.assertIn("payload_hash_mismatch",
                      verify_ceremony_record(bad, signing_key=KEY))
        bad2 = replace(rec, signature="0" * 64)
        self.assertIn("signature_mismatch",
                      verify_ceremony_record(bad2, signing_key=KEY))


class CeremonyAuthorisationTests(unittest.TestCase):
    def setUp(self):
        _reset_fixture_consumer()

    """Cycle 19, Part C: envelope consumption in reanchor_pin."""

    def test_signing_key_as_authorisation_public_key_refused_on_type(self):
        # Cycle 20 (T11 as amended): key separation is a TYPE
        # gate. The snapshot SigningKey passed as
        # authorisation_public_key refuses on type, before
        # envelope verification — there is no second secret in
        # the ceremony to compare ids with, and the cycle-19
        # id-inequality check is deleted (it compared disjoint
        # ``pub-…`` / ``key-…`` namespaces and could never fire).
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     authorisation_public_key=KEY)
        self.assertIn("CeremonyPublicKey", str(cm.exception))

    def test_key_substitution_attacker_public_key_pinned_refused(self):
        # Key substitution, direction (i): a GENUINE verifier
        # envelope, but the ceremony is pinned to an ATTACKER
        # CeremonyPublicKey ⇒ refusal at envelope verification.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     authorisation_public_key=ATTACKER_PUBLIC_KEY)
        self.assertIn("ceremony authorisation does not verify",
                      str(cm.exception))

    def test_key_substitution_envelope_under_attacker_seed_refused(self):
        # Key substitution, direction (ii): an envelope minted
        # under the ATTACKER's seed for the exact real event,
        # presented to a ceremony pinned to the GENUINE verifier
        # public key ⇒ refusal. Substitution produces refusal
        # (DoS), never acceptance, in either direction.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand,
                                  key=ATTACKER_SIGNING_KEY)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth)
        self.assertIn("ceremony authorisation does not verify",
                      str(cm.exception))

    def test_envelope_binding_refusals_per_field(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        other_pin = pin_of(snap(2))
        other_cand = snap(5, prev="f" * 64)
        cases = {
            "operator": mint_authorisation(
                pin_of(a), cand, operator_id="operator-2"),
            "reason": mint_authorisation(
                None, cand, reason="lost_pin", old_pin=None),
            "old_pin": mint_authorisation(other_pin, cand),
            "candidate": mint_authorisation(pin_of(a), other_cand),
            "evidence": mint_authorisation(
                pin_of(a), cand, evidence_hash="d" * 64),
        }
        for field, auth in cases.items():
            with self.assertRaises(SigningError, msg=field):
                reanchor(pin_of(a), cand, authorisation=auth)

    def test_expired_envelope_refused(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)  # minted at NOW, TTL 900 s
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     now="2026-11-20T12:16:00+00:00")
        self.assertIn("expired", str(cm.exception))

    def test_wrong_key_envelope_refused(self):
        # Superseded in shape by the two key-substitution tests
        # above; kept as the plain wrong-pin leg: a genuine
        # envelope verified against an unrelated public key
        # refuses.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        wrong = _ceremony_public_key(
            _ceremony_signing_key(b"\xaa" * 32))
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth,
                     authorisation_public_key=wrong)

    def test_wrong_verifier_signer_pin_refused(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth,
                     expected_verifier_signer_id="verifier-other")

    def test_dict_authorisation_refused(self):
        # reanchor_pin takes the typed object, never a raw dict.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand,
                     authorisation=ceremony_authorisation_envelope_to_dict(
                         auth))
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth,
                     authorisation_public_key="not-a-key")

    def test_record_carries_authorisation_binding(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        _pin, rec = reanchor(pin_of(a), cand, authorisation=auth)
        self.assertEqual(rec.ceremony_id, auth.ceremony_id)
        self.assertEqual(rec.authorisation_id, auth.authorisation_id)
        self.assertEqual(verify_ceremony_record(rec, signing_key=KEY),
                         ())
        # A swapped (well-formed) authorisation id is MAC-bound:
        bad = replace(rec, authorisation_id="d" * 64)
        self.assertIn("payload_hash_mismatch",
                      verify_ceremony_record(bad, signing_key=KEY))
        # Malformed ids report the shared invalid_authorisation:
        bad2 = replace(rec, authorisation_id="not-hex")
        self.assertIn("invalid_authorisation",
                      verify_ceremony_record(bad2, signing_key=KEY))
        bad3 = replace(rec, ceremony_id="BAD ID!")
        self.assertIn("invalid_authorisation",
                      verify_ceremony_record(bad3, signing_key=KEY))


LATER = "2026-11-20T13:00:00+00:00"


def snap_at(seq, prev="", when=LATER):
    return sign_state_snapshot(state_bytes(seq), signing_key=KEY,
                               signer_id=SIGNER, calibration_bytes=CAL,
                               prev_snapshot_hash=prev, now=when)


class Cycle16HardeningTests(unittest.TestCase):
    def setUp(self):
        _reset_fixture_consumer()

    def _first_ceremony(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        new_pin, rec = reanchor(pin_of(a), cand)
        return a, cand, new_pin, rec

    def test_forged_strict_reasons_wrong_pin_binding_refused(self):
        # The caller-supplied ("chain_gap",) is not trusted: with a
        # pin carrying a different signer binding, the recomputed
        # strict result is not a sole chain_gap and the ceremony
        # refuses, where cycle 15 would have proceeded.
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        bad_pin = pin_of(a)
        bad_pin["signer_id"] = "evil-9"
        with self.assertRaises(SigningError):
            reanchor(bad_pin, cand)

    def test_gap_prev_is_pin_refused(self):
        a = snap(1)
        cand = snap(4, prev=a.payload_hash)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand)

    def test_strict_reasons_corpus_never_typeerror(self):
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        for bad in ["chain_gap", 42, ("chain_gap", "chain_gap"),
                    ("chain_gap", "expired")]:
            with self.assertRaises(SigningError, msg=repr(bad)):
                reanchor(pin_of(a), cand, strict_reasons=bad)

    def test_history_evidence_reuse_refused_fresh_accepted(self):
        _a, cand, new_pin, rec = self._first_ceremony()
        nxt = snap_at(7, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER,
                     ceremony_history=[rec])
        pin2, rec2 = reanchor(new_pin, nxt, now=LATER,
                              evidence_hash="d" * 64,
                              ceremony_history=[rec])
        self.assertEqual(pin2, pin_of(nxt))
        self.assertEqual(verify_ceremony_record(rec2, signing_key=KEY),
                         ())

    def test_history_tampered_and_duplicate_evidence_refused(self):
        _a, _c, new_pin, rec = self._first_ceremony()
        nxt = snap_at(7, prev="f" * 64)
        tampered = replace(rec, operator_id="operator-2")
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[tampered])
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[rec, rec])
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history="not-a-history")
        with self.assertRaises(SigningError):
            reanchor(new_pin, nxt, now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[object()])

    def test_history_replayed_target_and_behind_head_refused(self):
        a, cand, _pin, rec = self._first_ceremony()
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        behind = snap_at(3, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), behind, now=LATER,
                     evidence_hash="d" * 64, ceremony_history=[rec])

    def test_history_explicit_empty_accepted(self):
        # Cycle 20 split of the old empty-and-absent test: the
        # EMPTY half survives — an explicit empty history is a
        # caller assertion that no prior ceremony exists, and a
        # first chain_gap ceremony succeeds on it. The ABSENT
        # half is inverted by cycle 20: omission is now a
        # TypeError and explicit None refuses (see
        # Cycle20ConsumptionTests, T1–T3).
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _, rec = reanchor(pin_of(a), cand, ceremony_history=[])
        self.assertEqual(verify_ceremony_record(rec, signing_key=KEY),
                         ())

    def test_one_step_record_never_verifies_clean(self):
        _a, _c, _p, rec = self._first_ceremony()
        one_step = replace(rec, new_cycle_seq=rec.old_cycle_seq + 1)
        self.assertIn("not_a_gap_reanchor",
                      verify_ceremony_record(one_step, signing_key=KEY))

    def test_record_pin_context(self):
        a, cand, _p, rec = self._first_ceremony()
        self.assertEqual(
            verify_ceremony_record(
                rec, signing_key=KEY, expected_old_pin=pin_of(a),
                expected_new_pin=pin_of(cand)), ())
        other = snap(5, prev="f" * 64)
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(
                rec, signing_key=KEY, expected_old_pin=pin_of(a),
                expected_new_pin=pin_of(other)))

    def test_fix_round_cycle16(self):
        from signing.pin_ceremony import _mac, _payload_hash
        a, cand, new_pin, rec = self._first_ceremony()
        # Replayed target, isolated by its refusal message.
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        self.assertIn("already a ceremonied target", str(cm.exception))
        # Stale candidate, isolated: signed before the history's
        # latest ceremony, refused by the predates check itself.
        stale = snap_at(7, prev="f" * 64,
                        when="2026-11-20T11:55:00+00:00")
        with self.assertRaises(SigningError) as cm:
            reanchor(new_pin, stale, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        self.assertIn("predates the latest ceremony",
                      str(cm.exception))
        # Equal-seq / different-hash against the history head.
        rival = snap_at(4, prev="a" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), rival, now=LATER,
                     evidence_hash="d" * 64, ceremony_history=[rec])
        self.assertIn("abandon higher attested work",
                      str(cm.exception))
        # Forked history: two verified records, same target seq,
        # different hashes.
        _, rec2 = reanchor(None, rival, reason="initial_anchor",
                           evidence_hash="b" * 64, now=LATER,
                           consume_authorisation=_fresh_fixture_consumer())
        nxt = snap_at(7, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(new_pin, nxt, now=LATER,
                     evidence_hash="c" * 64,
                     ceremony_history=[rec, rec2])
        self.assertIn("history is forked", str(cm.exception))
        # A validly MACed one-step record: exactly one reason.
        one = replace(rec, new_cycle_seq=rec.old_cycle_seq + 1)
        ph = _payload_hash(one.payload())
        one = replace(one, payload_hash=ph,
                      signature=_mac(KEY.key, ph, KEY.key_id))
        self.assertEqual(verify_ceremony_record(one, signing_key=KEY),
                         ("not_a_gap_reanchor",))
        # Context: each side independent; explicit absent-old
        # assertion; malformed context reports, never raises.
        self.assertEqual(
            verify_ceremony_record(rec, signing_key=KEY,
                                   expected_new_pin=pin_of(cand)), ())
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(rec, signing_key=KEY,
                                   expected_old_pin=None))
        _, rec_init = reanchor(None, snap(2), reason="initial_anchor",
                               evidence_hash="b" * 64,
                               consume_authorisation=_fresh_fixture_consumer())
        self.assertEqual(
            verify_ceremony_record(rec_init, signing_key=KEY,
                                   expected_old_pin=None), ())
        self.assertIn(
            "pin_context_mismatch",
            verify_ceremony_record(
                rec, signing_key=KEY,
                expected_new_pin={"cycle_seq": "x",
                                  "payload_hash": "z"}))
        # Binding-absent pin: known, pinned behaviour — a minimal
        # pin carries no bindings for the recomputation to bind.
        minimal = {"cycle_seq": a.cycle_seq,
                   "payload_hash": a.payload_hash}
        pin3, _ = reanchor(minimal, cand, evidence_hash="c" * 64,
                           consume_authorisation=_fresh_fixture_consumer())
        self.assertEqual(pin3, pin_of(cand))
        # strict_reasons must be a list/tuple, captured once.
        for bad in [{"chain_gap": 1}, {"chain_gap"}]:
            with self.assertRaises(SigningError, msg=repr(bad)):
                reanchor(pin_of(a), cand, strict_reasons=bad)


class Cycle20ConsumptionTests(unittest.TestCase):
    def setUp(self):
        _reset_fixture_consumer()

    """Cycle 20, seat C: required ceremony_history, per-reason
    admissibility, the duplicate-consumption matrix, and the
    honest residual pins (design-c §6 T1–T8 as amended by
    critique-c; DESIGN-FINAL R6)."""

    def _direct_kwargs(self, old, cand):
        """The full reanchor_pin argument set, built directly
        (not via the reanchor() helper) so a test can OMIT a
        keyword the helper would supply."""
        return dict(
            signing_key=KEY,
            state_bytes=state_bytes(cand.cycle_seq),
            calibration_bytes=CAL,
            expected_signer_id=SIGNER,
            operator_id=OPERATOR,
            reason="chain_gap_recovery",
            strict_reasons=("chain_gap",),
            evidence_hash=EVIDENCE,
            authorisation=mint_authorisation(old, cand),
            authorisation_public_key=VERIFIER_PUBLIC_KEY,
            expected_verifier_signer_id=VERIFIER_SIGNER,
            now=NOW)

    def test_t1_ceremony_history_keyword_is_required(self):
        # T1: the parameter has no default — omitting the
        # keyword raises TypeError before any logic runs. Pins
        # the call shape against a future "convenience" default
        # creeping back.
        param = inspect.signature(
            reanchor_pin).parameters["ceremony_history"]
        self.assertIs(param.default, inspect.Parameter.empty)
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(TypeError):
            reanchor_pin(pin_of(a), cand,
                         **self._direct_kwargs(pin_of(a), cand))

    def test_t2_explicit_none_refuses_before_envelope_verification(self):
        # T2: explicit None refuses for chain_gap_recovery with
        # the fail-closed-on-omission message — and the refusal
        # fires even with an EXPIRED envelope, pinning the
        # ordering (presence before envelope verification).
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, ceremony_history=None)
        self.assertIn("fail-closed on omission", str(cm.exception))
        auth = mint_authorisation(pin_of(a), cand)  # minted at NOW
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=None,
                     now="2026-11-20T12:16:00+00:00")
        self.assertIn("fail-closed on omission", str(cm.exception))

    def test_t3_explicit_none_refuses_for_every_no_pin_reason(self):
        # T3: omission is not a bootstrap path — None refuses
        # with the same message for every no-pin reason.
        cand = snap(3)
        for reason in ("initial_anchor", "lost_pin",
                       "corrupted_pin"):
            with self.assertRaises(SigningError, msg=reason) as cm:
                reanchor(None, cand, reason=reason,
                         ceremony_history=None)
            self.assertIn("fail-closed on omission",
                          str(cm.exception))

    def test_t4_initial_anchor_nonempty_history_refused(self):
        # T4, leg 1: initial_anchor with a non-empty VERIFIED
        # history refuses with the empty-only message, naming
        # the contradiction and pointing at lost_pin (with a new
        # authorisation/evidence required).
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _pin, rec = reanchor(pin_of(a), cand)
        cand2 = snap(5, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(None, cand2, reason="initial_anchor",
                     evidence_hash="d" * 64, ceremony_history=[rec])
        self.assertIn("initial_anchor requires an empty ceremony "
                      "history", str(cm.exception))
        self.assertIn("lost_pin", str(cm.exception))

    def test_t4_lost_pin_populated_history_evidence_reuse_refused(self):
        # T4, leg 2: lost_pin with a populated history runs the
        # generic checks — reusing the first ceremony's evidence
        # refuses.
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _pin, rec = reanchor(pin_of(a), cand)
        nxt = snap_at(7, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(None, nxt, reason="lost_pin", now=LATER,
                     ceremony_history=[rec])
        self.assertIn("already been used in a prior ceremony",
                      str(cm.exception))

    def test_t4_corrupted_pin_populated_history_behind_head_refused(self):
        # T4, leg 3: corrupted_pin with a populated history and
        # a candidate behind its ceremony head refuses.
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        _pin, rec = reanchor(pin_of(a), cand)
        behind = snap_at(3, prev="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(None, behind, reason="corrupted_pin",
                     now=LATER, evidence_hash="d" * 64,
                     ceremony_history=[rec])
        self.assertIn("abandon higher attested work",
                      str(cm.exception))

    def test_t5_duplicate_consumption_second_presentation_none_refused(self):
        # T5 (unit leg): the same envelope consumed once, then
        # presented again with ceremony_history=None ⇒ refused.
        # The cycle-19 pinned limit (replay succeeds when
        # history is omitted) is DELETED — this is its
        # replacement.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        reanchor(pin_of(a), cand, authorisation=auth,
                 ceremony_history=())
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=None)
        self.assertIn("fail-closed on omission", str(cm.exception))

    def test_t6_duplicate_consumption_updated_history_refused(self):
        # T6: the same envelope twice, the second call supplying
        # the UPDATED history [rec1] ⇒ refused as a replayed
        # target.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        _pin1, rec1 = reanchor(pin_of(a), cand, authorisation=auth,
                               ceremony_history=())
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=[rec1])
        self.assertIn("already a ceremonied target",
                      str(cm.exception))

    def test_consumption_replay_with_stale_history_succeeds_named_residual_protected_head(self):
        """T7' — the cycle-20 residual is CLOSED by the head.
        (This test was the cycle-20 residual pin: it asserted
        the replay SUCCEEDED with stale history. Cycle 21
        flips it.) The same envelope twice, the second call
        supplying the STALE history (the same () as the first
        call) REFUSES — via the consumer, not the history:
        the second call goes through a FRESH
        CeremonyConsumptionLedger instance over the same
        fixture dir, so the already-consumed refusal can only
        come from the on-disk journal."""
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        pin1, rec1 = reanchor(pin_of(a), cand, authorisation=auth,
                              ceremony_history=())
        fresh_instance_consumer = LedgerBackedConsumer(
            _default_consumer().journal_dir)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=(),
                     consume_authorisation=fresh_instance_consumer)
        self.assertIn("already consumed", str(cm.exception))

    def test_t8_regression_scenario_stale_history_returns_regressed_pin(self):
        """T8' — Gemini's regression attack, flipped by cycle
        21. (This test was the cycle-20 regression pin: it
        asserted the stale-history leg SUCCEEDED and returned
        the regressed pin.) Consume seq1->seq4, advance the
        real pin to seq6 by ordinary advance_pin steps (which
        leave NO trace in the ceremony history), then replay
        the original envelope with old_pin restaged to the
        seq-1 pin: updated history refuses (replayed target,
        the history leg, as before); stale history NOW
        refuses via the consumer (already-consumed) and NO
        regressed pin is returned. Added leg: a NEW envelope
        for old=seq1/candidate=seq5 (head=4, live pin 6)
        refuses at the consumer with the head-regression
        refusal (old pin behind the consumed head)."""
        a = snap(1)
        cand = snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        pin4, rec1 = reanchor(pin_of(a), cand, authorisation=auth,
                              ceremony_history=())
        s5 = snap(5, prev=cand.payload_hash)
        s6 = snap(6, prev=s5.payload_hash)
        pin6 = advance_pin(advance_pin(pin4, s5, ()), s6, ())
        self.assertEqual(pin6["cycle_seq"], 6)
        # Updated history: refused (history leg, as before).
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=[rec1])
        self.assertIn("already a ceremonied target",
                      str(cm.exception))
        # Stale history: NOW refused via the consumer, and no
        # regressed pin is returned (the call raises).
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=())
        self.assertIn("already consumed", str(cm.exception))
        # Fresh-envelope leg: new envelope, old=seq1,
        # candidate=seq5, head=4, live pin 6 — refuses at the
        # consumer with the head-regression refusal.
        cand5 = snap(5, prev="f" * 64)
        auth5 = mint_authorisation(pin_of(a), cand5,
                                   evidence_hash="f" * 64)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand5, authorisation=auth5,
                     evidence_hash="f" * 64, ceremony_history=())
        self.assertIn("old pin is behind the consumed head",
                      str(cm.exception))

    def test_v1_golden_envelope_refused_with_version_wording(self):
        # R6: v1 refusal is EXPLICIT. A literal cycle-19 envelope
        # dict (hex64 HMAC signature, ``key-…`` id) converted via
        # from_dict must raise a SigningError NAMING the
        # superseded version, before any reanchor logic; and the
        # raw dict presented to reanchor_pin refuses as a
        # non-typed authorisation.
        v1 = {
            "operator_id": OPERATOR,
            "ceremony_id": "ceremony-golden-v1",
            "reason": "chain_gap_recovery",
            "old_pin": {"cycle_seq": 1, "payload_hash": "b" * 64},
            "candidate": {"cycle_seq": 4, "payload_hash": "c" * 64,
                          "signer_id": SIGNER, "key_id": KEY.key_id},
            "evidence_hash": EVIDENCE,
            "evidence_ref": EVIDENCE_REF,
            "signer_id": VERIFIER_SIGNER,
            "key_id": "key-0123456789abcdef",
            "signed_at": NOW,
            "expires_at": "2026-11-20T12:15:00+00:00",
            "payload_hash": "d" * 64,
            "authorisation_id": "f" * 64,
            "signature": "a" * 64,
        }
        with self.assertRaises(SigningError) as cm:
            ceremony_authorisation_envelope_from_dict(v1)
        self.assertRegex(str(cm.exception), r"(?i)version 1|v1")
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=v1)



class _CountingConsumer:
    """Spy consumer: records every invocation; optionally
    delegates to a real consumer. Used only where the test's
    subject is the invocation discipline itself (R12)."""

    def __init__(self, delegate=None):
        self.calls = []
        self._delegate = delegate

    def __call__(self, authorisation):
        self.calls.append(authorisation)
        if self._delegate is not None:
            return self._delegate(authorisation)
        return None


class Cycle21ConsumptionTests(unittest.TestCase):
    """Cycle 21, seat C: required consume_authorisation (T1b),
    invocation discipline (spy/counting consumers), and the
    commit-then-raise crash contract (T-Cc)."""

    def setUp(self):
        _reset_fixture_consumer()

    def _direct_kwargs(self, old, cand):
        return dict(
            signing_key=KEY,
            state_bytes=state_bytes(cand.cycle_seq),
            calibration_bytes=CAL,
            expected_signer_id=SIGNER,
            operator_id=OPERATOR,
            reason="chain_gap_recovery",
            strict_reasons=("chain_gap",),
            evidence_hash=EVIDENCE,
            authorisation=mint_authorisation(old, cand),
            authorisation_public_key=VERIFIER_PUBLIC_KEY,
            expected_verifier_signer_id=VERIFIER_SIGNER,
            ceremony_history=(),
            now=NOW)

    def test_t1b_consume_authorisation_keyword_is_required(self):
        # T1b: no default — omission is a TypeError at the
        # call site, mirroring T1's ceremony_history pin.
        param = inspect.signature(
            reanchor_pin).parameters["consume_authorisation"]
        self.assertIs(param.default, inspect.Parameter.empty)
        a, cand = snap(1), snap(4, prev="f" * 64)
        with self.assertRaises(TypeError):
            reanchor_pin(pin_of(a), cand,
                         **self._direct_kwargs(pin_of(a), cand))

    def test_t1b_none_and_noncallable_refuse_before_envelope_verification(self):
        # T1b ordering: explicit None / a non-callable refuses
        # EARLY, before envelope verification — pinned with an
        # EXPIRED envelope (the T2 construction): the refusal
        # reports the omission, never the expiry.
        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)  # minted at NOW
        for bad in (None, 42, "consumer"):
            with self.assertRaises(SigningError, msg=repr(bad)) as cm:
                reanchor(pin_of(a), cand, authorisation=auth,
                         consume_authorisation=bad,
                         now="2026-11-20T12:16:00+00:00")
            self.assertIn("fail-closed on omission",
                          str(cm.exception), repr(bad))

    def test_spy_consumer_exactly_one_invocation_on_success(self):
        a, cand = snap(1), snap(4, prev="f" * 64)
        spy = _CountingConsumer(delegate=_default_consumer())
        new_pin, _rec = reanchor(pin_of(a), cand,
                                 consume_authorisation=spy)
        self.assertEqual(new_pin, pin_of(cand))
        self.assertEqual(len(spy.calls), 1)

    def test_spy_consumer_zero_invocations_on_local_refusals(self):
        # Zero invocations on each local refusal class: bad
        # (expired) envelope, binding mismatch, history
        # refusal, a strict-recomputation refusal (tampered
        # candidate), the relation gates, the strict-shape
        # gate, the evidence-independence refusal, and a
        # no-pin bare-attestation refusal (rev-r4 MEDIUM-1).
        a, cand = snap(1), snap(4, prev="f" * 64)
        # (i) bad envelope: expired.
        spy = _CountingConsumer()
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth,
                     consume_authorisation=spy,
                     now="2026-11-20T12:16:00+00:00")
        self.assertEqual(spy.calls, [])
        # (ii) binding mismatch: envelope for another operator.
        spy = _CountingConsumer()
        auth9 = mint_authorisation(pin_of(a), cand,
                                   operator_id="operator-9")
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth9,
                     consume_authorisation=spy)
        self.assertEqual(spy.calls, [])
        # (iii) history refusal: replay with updated history.
        _pin, rec = reanchor(pin_of(a), cand)
        spy = _CountingConsumer()
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), cand, authorisation=auth,
                     ceremony_history=[rec],
                     consume_authorisation=spy)
        self.assertEqual(spy.calls, [])
        # (iv) relation/recomputation refusal: tampered
        # candidate signature.
        spy = _CountingConsumer()
        tampered = replace(snap(4, prev="f" * 64), signature="0" * 64)
        with self.assertRaises(SigningError):
            reanchor(pin_of(a), tampered, consume_authorisation=spy)
        self.assertEqual(spy.calls, [])
        # (v) relation gates. The chained-successor and
        # successor-fork legs are refused by the envelope's
        # gap-only payload validation (candidate must be at
        # least old+2) before the relation gate itself — the
        # re-scope the cycle-15 tests record — while
        # gap_prev_is_pin carries a valid gap envelope and
        # refuses AT the relation gate. All three are local
        # refusals, so the consumer is never invoked.
        spy = _CountingConsumer()
        nxt = snap(2, prev=a.payload_hash)
        auth_succ = hand_authorisation(
            pin_of(a), nxt, reason="chain_gap_recovery")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), nxt, authorisation=auth_succ,
                     consume_authorisation=spy)
        self.assertIn("malformed_payload", str(cm.exception))
        self.assertEqual(spy.calls, [])
        spy = _CountingConsumer()
        fork = snap(2, prev="f" * 64)
        auth_fork = hand_authorisation(
            pin_of(a), fork, reason="chain_gap_recovery")
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), fork, authorisation=auth_fork,
                     consume_authorisation=spy)
        self.assertIn("malformed_payload", str(cm.exception))
        self.assertEqual(spy.calls, [])
        spy = _CountingConsumer()
        gap_prev = snap(4, prev=a.payload_hash)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), gap_prev,
                     consume_authorisation=spy)
        self.assertIn(
            "candidate claims the pin as its immediate "
            "predecessor", str(cm.exception))
        self.assertEqual(spy.calls, [])
        # (vi) strict-shape gate: strict_reasons of a
        # non-list/tuple type (a bare string) refuses before
        # strict recomputation — and before consumption.
        spy = _CountingConsumer()
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, strict_reasons="chain_gap",
                     consume_authorisation=spy)
        self.assertIn(
            "requires a strict verification result of exactly "
            "('chain_gap',)", str(cm.exception))
        self.assertEqual(spy.calls, [])
        # (vii) evidence-independence refusal: evidence_hash
        # equal to a candidate hash (the candidate's state
        # hash — the mintable leg that reaches the step-5
        # non-equality check itself).
        spy = _CountingConsumer()
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand,
                     evidence_hash=cand.state_sha256,
                     consume_authorisation=spy)
        self.assertIn(
            "ceremony evidence must be independent of the "
            "candidate", str(cm.exception))
        self.assertEqual(spy.calls, [])
        # (viii) no-pin bare-attestation refusal: a lost_pin
        # candidate failing attestation bindings (tampered
        # signature). No strict recomputation runs on the
        # no-pin path, so the bare verifier is the last local
        # gate before consumption — and it refuses first.
        spy = _CountingConsumer()
        bad_cand = replace(snap(3), signature="0" * 64)
        auth_lost = mint_authorisation(
            None, bad_cand, reason="lost_pin", old_pin=None)
        with self.assertRaises(SigningError) as cm:
            reanchor(None, bad_cand, reason="lost_pin",
                     authorisation=auth_lost,
                     consume_authorisation=spy)
        self.assertIn("candidate fails attestation bindings",
                      str(cm.exception))
        self.assertEqual(spy.calls, [])

    def test_tcc_commit_then_raise_consumer_burns_envelope(self):
        # T-Cc: a fake consumer backed by a REAL ledger that
        # commits, then raises (the lost-response crash,
        # C-c). reanchor_pin returns nothing; a second attempt
        # refuses already-consumed; exactly one consumption
        # entry exists.
        consumer = _fresh_fixture_consumer()
        state = {"committed": False}

        def commit_then_raise(authorisation):
            if not state["committed"]:
                consumer(authorisation)  # the durable commit
                state["committed"] = True
                raise SigningError("verifier timeout after commit")
            return consumer(authorisation)

        a, cand = snap(1), snap(4, prev="f" * 64)
        auth = mint_authorisation(pin_of(a), cand)
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     consume_authorisation=commit_then_raise)
        self.assertIn("timeout after commit", str(cm.exception))
        with self.assertRaises(SigningError) as cm:
            reanchor(pin_of(a), cand, authorisation=auth,
                     consume_authorisation=commit_then_raise)
        self.assertIn("already consumed", str(cm.exception))
        self.assertEqual(len(consumer.entries()), 1)


if __name__ == "__main__":
    unittest.main()
