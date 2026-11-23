"""Subprocess child helper for the cycle-23 crash tests
(DESIGN-FINAL R4) — NOT a test module; it is executed as
``python3 tests/cycle23_crash_child.py <config.json>`` by
tests/test_trust_pin_adoption_crash.py and must not be
collected as tests.

The child drives a real ``PinAdopter`` (research-mode verifier
subprocess, the R12 fixture pattern) against temp dirs named
in its JSON config, and synchronises with the parent through
barrier files in a barrier dir:

- mode "burn": wraps PinStore.adopt so that, at the ceremony
  adopt call — which happens strictly AFTER the verifier has
  committed the consumption inside reanchor_pin — it records
  the returned (pin, record) pair to the pair file (when one
  is configured), touches the "consumed" barrier, and then
  sleeps forever. The parent SIGKILLs it there: a true
  post-consume / pre-adopt process death.
- mode "adopt-returned": adopts a pair file written by a
  "burn" child via PinAdopter.adopt_returned (no new
  ceremony, no new consumption) and writes its result file.
- mode "race": wraps PinStore.adopt with a start barrier —
  each racer announces itself at the adopt call and waits
  until both racers are there, so both have captured the same
  old pin and contend on the store's flock CAS — then runs
  snapshot_and_adopt and writes its outcome (or exception
  class) to its result file.

The adopt wrappers here are test-side synchronisation only:
they interpose on timing, never on verdicts, and the wrapped
real adopt is always what persists (except in "burn", where
NOT persisting is precisely the crash being simulated).
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from signing import make_signing_key
from signing.ceremony_authorisation import CeremonyPublicKey
from signing.pin_store import PinStore, ceremony_record_from_dict, \
    ceremony_record_to_dict
from trust.client import VerifierClient
from trust.pin_adoption import PinAdopter, PinAdopterConfig

# Must match the parent fixture in
# tests/test_trust_pin_adoption_crash.py exactly: the snapshot
# key is a deterministic test key so parent and child sign and
# verify the same snapshots.
SNAP_KEY = make_signing_key(bytes(range(32, 64)))
BARRIER_TIMEOUT = 120.0


def _touch(barrier_dir, name):
    (Path(barrier_dir) / name).write_text("1", encoding="utf-8")


def _wait_for(barrier_dir, name, timeout=BARRIER_TIMEOUT):
    deadline = time.monotonic() + timeout
    target = Path(barrier_dir) / name
    while time.monotonic() < deadline:
        if target.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"barrier {name} never appeared")


def _wait_for_count(barrier_dir, prefix, count,
                    timeout=BARRIER_TIMEOUT):
    deadline = time.monotonic() + timeout
    barrier = Path(barrier_dir)
    while time.monotonic() < deadline:
        if len(list(barrier.glob(prefix + "*"))) >= count:
            return
        time.sleep(0.05)
    raise TimeoutError(f"fewer than {count} {prefix}* barriers")


def _write_result(cfg, payload):
    Path(cfg["result_path"]).write_text(
        json.dumps(payload), encoding="utf-8")


def _build_adopter(cfg):
    pub = CeremonyPublicKey(
        public_key=bytes.fromhex(cfg["pub_key_hex"]),
        key_id=cfg["pub_key_id"])
    client = VerifierClient(
        verifier_env=cfg["env"],
        expected_signer_id=cfg["signer"],
        expected_key_id=cfg["pub_key_id"],
        authorisation_public_key=pub)
    state_dir = Path(cfg["state_dir"])
    store = PinStore(cfg["pin_dir"], state_dir=state_dir)
    config = PinAdopterConfig(
        state_path=state_dir / "state.json",
        calibration_path=Path(cfg["calibration_path"]),
        pin_dir=Path(cfg["pin_dir"]),
        snapshot_signer_id=cfg["snap_signer"],
        expected_snapshot_signer_id=cfg["snap_signer"],
        operator_id=cfg["operator"],
        expected_verifier_signer_id=cfg["signer"],
        evidence_dir=Path(cfg["evidence_dir"]))
    adopter = PinAdopter(client=client, store=store,
                         signing_key=SNAP_KEY, config=config,
                         authorisation_public_key=pub)
    return adopter, store


def _mode_burn(cfg, adopter, store):
    real_adopt = store.adopt
    pair_path = cfg.get("pair_path")

    def dying_adopt(new_pin, record=None, **kw):
        if record is None:
            return real_adopt(new_pin, record, **kw)
        # The consumption has already committed at the
        # verifier (reanchor_pin returned the pair); adoption
        # has not happened. Record the pair if asked, signal,
        # and die here (the parent SIGKILLs this process).
        if pair_path:
            Path(pair_path).write_text(json.dumps({
                "pin": new_pin,
                "record": ceremony_record_to_dict(record),
                "expected_old_pin": kw.get("expected_old_pin"),
            }), encoding="utf-8")
        _touch(cfg["barrier_dir"], "consumed")
        while True:
            time.sleep(60)

    store.adopt = dying_adopt
    adopter.snapshot_and_adopt()
    _write_result(cfg, {"unexpected": "snapshot_and_adopt returned"})
    return 3


def _mode_adopt_returned(cfg, adopter, store):
    pair = json.loads(Path(cfg["pair_path"]).read_text(
        encoding="utf-8"))
    record = ceremony_record_from_dict(pair["record"])
    result = adopter.adopt_returned(
        pair["pin"], record,
        expected_old_pin=pair["expected_old_pin"])
    _write_result(cfg, {"outcome": result.outcome,
                        "pin_seq": result.pin["cycle_seq"]})
    return 0


def _mode_race(cfg, adopter, store):
    real_adopt = store.adopt

    def barrier_adopt(new_pin, record=None, **kw):
        _touch(cfg["barrier_dir"], f"at-adopt-{os.getpid()}")
        _wait_for_count(cfg["barrier_dir"], "at-adopt-", 2)
        return real_adopt(new_pin, record, **kw)

    store.adopt = barrier_adopt
    try:
        result = adopter.snapshot_and_adopt()
        _write_result(cfg, {"outcome": result.outcome,
                            "pin_seq": result.pin["cycle_seq"]})
    except Exception as exc:  # the loser's refusal is the datum
        _write_result(cfg, {"exception": type(exc).__name__,
                            "message": str(exc)[:300]})
    return 0


def main(argv):
    cfg = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    adopter, store = _build_adopter(cfg)
    mode = cfg["mode"]
    if mode == "burn":
        return _mode_burn(cfg, adopter, store)
    if mode == "adopt-returned":
        return _mode_adopt_returned(cfg, adopter, store)
    if mode == "race":
        return _mode_race(cfg, adopter, store)
    _write_result(cfg, {"unexpected": f"unknown mode {mode}"})
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
