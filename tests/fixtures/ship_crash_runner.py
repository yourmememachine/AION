"""Standalone ship crash-laboratory runner (Trust Boundary v3,
mandate item 2; CROSS-CHECK-4 seat-gpt F2).

Builds a complete, valid ship scenario in a target directory
(mirroring tests/test_trust_shipcheck.py's setup: a small repo
tree, a temp CoreLoop with a pickable item, a manifest, a release
record, a ship-purpose signed envelope + signed attestation, and
a ship ledger in a verifier-home), then calls
trust.shipcheck.record_ship — with crash injection when the
AION_CRASH_POINT environment variable names a point: the process
os._exit(99)s immediately AFTER the real durable side effect at
that point but BEFORE the next step. These are real process
kills, not hand-constructed states: whatever is on disk when the
process dies is exactly what the production code managed to
persist.

Crash points (named exactly):

    after_begin               PREPARED journaled, nothing else
    after_auth_verified       AUTHORISATION_VERIFIED journaled
    after_burn_pending        BURN_PENDING journaled, no burn yet
    after_burn                burn landed, cycle NOT yet run
                              (the critical gap)
    after_cycle               loop recorded the cycle,
                              CYCLE_RECORDED NOT yet journaled
    after_cycle_journaled     CYCLE_RECORDED journaled
    after_post_record_verified  POST_RECORD_VERIFIED journaled,
                              finalise NOT yet landed
    after_finalise            finalise landed, COMMITTED NOT
                              yet journaled
    after_commit              COMMITTED journaled, anchor NOT
                              yet updated (anchored variant only
                              in the tests: without an anchor this
                              is simply the end of record_ship)
    after_anchor              anchor update returned (anchored
                              variant only)
    during_finalise_save      dies inside the ship ledger's save
                              during the finalise append
                              (os.replace patched as used by that
                              save): the tmp file is written and
                              fsynced but never replaced, so the
                              finalise does NOT land
    during_anchor_save        dies inside the anchor write
                              (anchored variant only; os.replace
                              patched as used by the anchor's
                              atomic write): the tmp file is
                              written and fsynced but never
                              replaced, so the anchor does NOT
                              advance past its pre-ship value
    during_burn_save          dies inside the ship ledger's save
                              (os.replace patched as used by that
                              save): the tmp file is written and
                              fsynced but never replaced, so the
                              burn does NOT land
    during_tx_save            dies inside the tx journal's write
                              at BURN_PENDING (same os.replace
                              patch): the BURN_PENDING entry never
                              lands, the journal still shows
                              AUTHORISATION_VERIFIED

Exit codes: 0 = record_ship completed; 3 = ShipRefused (reason
on stderr); 99 = crash-injected kill; 4 = LedgerError in burn
mode (see below); anything else = an unexpected exception
(traceback on stderr).

Usage:  python ship_crash_runner.py <scenario-dir>

The scenario's key ids are written as JSON to
<scenario-dir>/scenario-<variant>.json (and scenario.json)
BEFORE record_ship starts, so a test can find them even when
the process is killed.

Modes / knobs (environment):
    AION_CRASH_POINT   one of the points above, or unset
    AION_VARIANT       artifact variant label (default "1");
                       each variant gets its own manifest /
                       envelope / attestation / release files so
                       several decisions can share one scenario
                       tree, one ship ledger and one tx journal
    AION_PROPOSAL_ID   proposal override (default: prop-ship for
                       variant 1, prop-ship-<variant> otherwise)
    AION_ITEM_ID       item override (default the fixture item)
    AION_LOOP_SUBDIR   loop state subdir under the scenario dir
                       (default "loop-state"); a different subdir
                       models a rolled-back / second loop over
                       the same shared ledgers
    AION_ANCHORED=1    anchored variant: an anchor for the ship
                       ledger is initialised at
                       <scenario-dir>/ship-anchor.json (OUTSIDE
                       the ledger's verifier-home directory, as
                       trust.anchoring requires) before shipping,
                       and that anchor_path is passed to
                       record_ship — and, in recover mode, to
                       recover_ship_tx
    AION_SETUP_ONLY=1  build + persist the scenario artifacts,
                       then exit 0 without shipping
    AION_MODE=recover  load the scenario's ledger + loop and run
                       trust.shipcheck.recover_ship_tx once
                       (root=<scenario>/repo); outcomes JSON on
                       stdout
    AION_MODE=burn     treat <scenario-dir> as a ship-ledger home
                       and burn one decision into it:
                       AION_BURN_DECISION_ID (required),
                       AION_BURN_PROPOSAL_ID / AION_BURN_MANIFEST_HASH
                       / AION_BURN_PAYLOAD_HASH (optional)
    AION_BARRIER_DIR + AION_BARRIER_COUNT
                       if set, the process announces itself in
                       the barrier dir and waits until that many
                       processes have announced, just before the
                       mode's main operation — used by the
                       concurrency tests to line processes up on
                       the same starting line
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.loop import CoreLoop
from eval.gate import GateDecision, VerifierAttestation
from signing import (
    PURPOSE_SHIP,
    make_signing_key,
    sign_attestation,
    sign_gate_decision,
)
from signing.attestation import (
    attestation_envelope_from_json,
    attestation_envelope_to_json,
)
from signing.gate_decision import envelope_from_json, envelope_to_json
from trust.errors import ShipRefused
from trust.ledger import LedgerError, ShipLedger
from trust.manifest import build_manifest, manifest_from_json
from trust.release import build_release_record, release_from_json
from trust.anchoring import initialise_anchor
import trust.shipcheck as _shipcheck_module
from trust.shipcheck import record_ship, recover_ship_tx
from trust.shiptx import ShipTxJournal, derive_tx_id

ANCHOR_NAME = "ship-anchor.json"

KEY = make_signing_key(bytes(range(32, 64)))
SEALED = "b" * 64
DEFAULT_PROPOSAL = "prop-ship"
DEFAULT_ITEM = "store-enforced-signed-commits"
CODERS = ["seat-1", "seat-2", "seat-3"]
REVIEWERS = ["rev-r1", "rev-r2", "rev-r3", "rev-r4", "rev-r5", "rev-r6"]
DELTA = {"metric": "tests_passing", "before": 1, "after": 2,
         "evidence_ref": "fixture run", "verifier": "rev-r1"}

CRASH_POINT = os.environ.get("AION_CRASH_POINT", "")
ANCHORED = bool(os.environ.get("AION_ANCHORED"))


def anchor_path_for(base: Path) -> Path:
    return Path(base) / ANCHOR_NAME


def ensure_anchor(base: Path, ledger) -> Path:
    """Initialise the ship-ledger anchor (genesis, seq 0) if it
    does not exist yet. The ledger must still be empty here —
    the scenario ships nothing before this is called in ship /
    setup mode — so the plain empty-ledger ceremony applies."""
    anchor_path = anchor_path_for(base)
    if not anchor_path.exists():
        initialise_anchor(ledger, anchor_path, kind="ship",
                          recorded_at=_ts(0))
    return anchor_path


def _ts(minutes_offset):
    from datetime import datetime, timedelta, timezone
    moment = datetime.now(timezone.utc) \
        + timedelta(minutes=minutes_offset)
    return moment.replace(microsecond=0).isoformat()


def _die():
    # A real, unrecoverable process kill: no cleanup, no flush of
    # anything the production code has not already made durable.
    os._exit(99)


def _barrier():
    barrier_dir = os.environ.get("AION_BARRIER_DIR")
    if not barrier_dir:
        return
    count = int(os.environ.get("AION_BARRIER_COUNT", "2"))
    path = Path(barrier_dir)
    path.mkdir(parents=True, exist_ok=True)
    name = os.environ.get("AION_BARRIER_NAME") or str(os.getpid())
    (path / f"{name}.ready").write_text("x")
    deadline = time.time() + 60
    while time.time() < deadline:
        if len(list(path.glob("*.ready"))) >= count:
            return
        time.sleep(0.005)
    raise RuntimeError("crash-lab barrier timed out")


def make_tree(root: Path):
    (root / "core").mkdir(parents=True, exist_ok=True)
    (root / "core" / "a.py").write_text("A = 1\n")
    (root / "eval").mkdir(exist_ok=True)
    (root / "eval" / "gate.py").write_text("GATE = True\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (root / "internal").mkdir(exist_ok=True)
    (root / "internal" / "REVIEW.md").write_text("# review\n")
    return root


def _ensure_loop(base: Path, loop_subdir: str, item: str) -> CoreLoop:
    loop = CoreLoop(base / loop_subdir)
    if item not in {it["id"] for it in loop.state["backlog"]}:
        loop.scan([{"id": item, "title": f"fixture ship item {item}",
                    "leverage": 5.0}])
    if not loop.state_path.exists():
        loop.scan([])
    return loop


def build_or_load(base: Path):
    """Build the scenario artifacts for this variant, or load
    them if a previous (setup) invocation already persisted
    them. Returns a namespace dict."""
    variant = os.environ.get("AION_VARIANT", "1")
    item = os.environ.get("AION_ITEM_ID", DEFAULT_ITEM)
    proposal = os.environ.get("AION_PROPOSAL_ID") or (
        DEFAULT_PROPOSAL if variant == "1"
        else f"{DEFAULT_PROPOSAL}-{variant}")
    loop_subdir = os.environ.get("AION_LOOP_SUBDIR", "loop-state")
    repo = base / "repo"
    home = base / "verifier-home"
    manifest_path = base / f"manifest-{variant}.json"
    envelope_path = base / f"envelope-{variant}.json"
    attestation_path = base / f"attestation-{variant}.json"
    release_path = base / f"release-{variant}.json"

    loop = _ensure_loop(base, loop_subdir, item)
    if manifest_path.exists() and envelope_path.exists() \
            and attestation_path.exists():
        manifest = manifest_from_json(manifest_path.read_text())
        envelope = envelope_from_json(envelope_path.read_text())
        satt = attestation_envelope_from_json(
            attestation_path.read_text())
        if release_path.exists():
            release = release_from_json(release_path.read_text())
        else:
            release = build_release_record(
                manifest, envelope,
                expected_cycle_id=loop.state["cycle_seq"] + 1,
                pre_ship_cycle_seq=loop.state["cycle_seq"],
                pre_ship_state_sha256=hashlib.sha256(
                    loop.state_path.read_bytes()).hexdigest())
            release_path.write_text(release.to_json())
    else:
        make_tree(repo)
        loop = _ensure_loop(base, loop_subdir, item)
        now = _ts(0)
        manifest = build_manifest(
            repo, proposal_id=proposal, item_id=item,
            review_record_path="internal/REVIEW.md", stage="final",
            created_at=now)
        att = VerifierAttestation(
            verifier_id="seat-3", decision="approve",
            sealed_hash=SEALED, reward_hacking_checked=True,
            evidence_ref="review-cycle-8", attested_at=_ts(-10))
        satt = sign_attestation(
            att, signing_key=KEY, signer_id="seat-3",
            proposal_id=proposal,
            manifest_hash=manifest.manifest_hash, now=_ts(-5))
        decision = GateDecision(
            accepted=True, proposal_id=proposal, reasons=(),
            regressions=(), forgetting_failures=(),
            verifier_id="seat-3", evaluated_at=now,
            protected_violations=(),
            verifier_note=f"content-hash:{manifest.manifest_hash}")
        envelope = sign_gate_decision(
            decision, signing_key=KEY, signer_id="verifier-svc",
            attestation=att, signed_attestation=satt,
            gate_inputs_hash=manifest.manifest_hash,
            purpose=PURPOSE_SHIP, now=now)
        release = build_release_record(
            manifest, envelope,
            expected_cycle_id=loop.state["cycle_seq"] + 1,
            pre_ship_cycle_seq=loop.state["cycle_seq"],
            pre_ship_state_sha256=hashlib.sha256(
                loop.state_path.read_bytes()).hexdigest())
        manifest_path.write_text(manifest.to_json())
        envelope_path.write_text(envelope_to_json(envelope))
        attestation_path.write_text(
            attestation_envelope_to_json(satt))
        release_path.write_text(release.to_json())

    scenario = {
        "variant": variant,
        "decision_id": envelope.decision_id,
        "item_id": manifest.item_id,
        "manifest_hash": manifest.manifest_hash,
        "proposal_id": manifest.proposal_id,
        "tx_id": derive_tx_id(envelope.decision_id,
                              manifest.manifest_hash),
        "loop_subdir": loop_subdir,
        "anchored": ANCHORED,
        "anchor_file": ANCHOR_NAME if ANCHORED else None,
    }
    text = json.dumps(scenario, indent=2, sort_keys=True)
    (base / f"scenario-{variant}.json").write_text(text)
    (base / "scenario.json").write_text(text)
    return {"variant": variant, "repo": repo, "home": home,
            "loop": loop, "manifest": manifest, "envelope": envelope,
            "satt": satt, "release": release, "scenario": scenario}


# -- crash injection ---------------------------------------------------

_TRANSITION_POINTS = {
    "AUTHORISATION_VERIFIED": "after_auth_verified",
    "BURN_PENDING": "after_burn_pending",
    "CYCLE_RECORDED": "after_cycle_journaled",
    "POST_RECORD_VERIFIED": "after_post_record_verified",
    # after_commit: the COMMITTED transition has landed, so the
    # transaction is terminal on disk, but record_ship has not
    # yet run its anchor update (trust/shipcheck.py's final step).
    "COMMITTED": "after_commit",
}


def install_crash_patches():
    if not CRASH_POINT:
        return
    if CRASH_POINT == "after_begin":
        real_begin = ShipTxJournal.begin

        def begin_then_die(self, *args, **kwargs):
            result = real_begin(self, *args, **kwargs)
            _die()
            return result

        ShipTxJournal.begin = begin_then_die

    if CRASH_POINT in _TRANSITION_POINTS.values() \
            or CRASH_POINT == "during_tx_save":
        real_transition = ShipTxJournal.transition
        armed = {"on": False}
        if CRASH_POINT == "during_tx_save":
            _patch_replace("ship-tx.json", armed)

        def transition_then_maybe_die(self, tx_id, to_state,
                                      *args, **kwargs):
            if CRASH_POINT == "during_tx_save" \
                    and to_state == "BURN_PENDING":
                armed["on"] = True
                try:
                    return real_transition(
                        self, tx_id, to_state, *args, **kwargs)
                finally:
                    armed["on"] = False
            result = real_transition(self, tx_id, to_state,
                                     *args, **kwargs)
            if _TRANSITION_POINTS.get(to_state) == CRASH_POINT:
                _die()
            return result

        ShipTxJournal.transition = transition_then_maybe_die

    if CRASH_POINT == "after_burn" or CRASH_POINT == "during_burn_save":
        real_burn = ShipLedger.burn
        armed = {"on": False}
        if CRASH_POINT == "during_burn_save":
            _patch_replace("ship-ledger.json", armed)

        def burn_then_maybe_die(self, *args, **kwargs):
            if CRASH_POINT == "during_burn_save":
                armed["on"] = True
                try:
                    return real_burn(self, *args, **kwargs)
                finally:
                    armed["on"] = False
            result = real_burn(self, *args, **kwargs)
            _die()
            return result

        ShipLedger.burn = burn_then_maybe_die

    if CRASH_POINT == "after_cycle":
        real_cycle = CoreLoop.run_one_cycle

        def cycle_then_die(self, *args, **kwargs):
            result = real_cycle(self, *args, **kwargs)
            _die()
            return result

        CoreLoop.run_one_cycle = cycle_then_die

    if CRASH_POINT == "after_finalise":
        real_finalise = ShipLedger.finalise

        def finalise_then_die(self, *args, **kwargs):
            result = real_finalise(self, *args, **kwargs)
            _die()
            return result

        ShipLedger.finalise = finalise_then_die

    if CRASH_POINT == "during_finalise_save":
        real_finalise = ShipLedger.finalise
        armed = {"on": False}
        _patch_replace("ship-ledger.json", armed)

        def finalise_during_save(self, *args, **kwargs):
            armed["on"] = True
            try:
                return real_finalise(self, *args, **kwargs)
            finally:
                armed["on"] = False

        ShipLedger.finalise = finalise_during_save

    if CRASH_POINT in ("after_anchor", "during_anchor_save"):
        # record_ship calls update_anchor through the
        # trust.shipcheck module namespace, so patch THAT name.
        real_update = _shipcheck_module.update_anchor
        armed = {"on": False}
        if CRASH_POINT == "during_anchor_save":
            _patch_replace(ANCHOR_NAME, armed)

        def update_then_maybe_die(*args, **kwargs):
            if CRASH_POINT == "during_anchor_save":
                armed["on"] = True
                try:
                    return real_update(*args, **kwargs)
                finally:
                    armed["on"] = False
            result = real_update(*args, **kwargs)
            _die()
            return result

        _shipcheck_module.update_anchor = update_then_maybe_die


def _patch_replace(target_name, armed):
    """Patch os.replace (as used by the journal saves) so the
    process dies with the tmp file written but not replaced,
    while `armed` is on and the destination is the target
    journal. The patch is process-local to this runner."""
    real_replace = os.replace

    def replacing(src, dst):
        if armed["on"] and Path(dst).name == target_name:
            _die()
        return real_replace(src, dst)

    os.replace = replacing


# -- modes ---------------------------------------------------------------

def main() -> int:
    base = Path(sys.argv[1])
    base.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get("AION_MODE", "ship")

    if mode == "burn":
        ledger = ShipLedger(base)
        decision_id = os.environ["AION_BURN_DECISION_ID"]
        proposal = os.environ.get("AION_BURN_PROPOSAL_ID", "p-burn")
        manifest_hash = os.environ.get("AION_BURN_MANIFEST_HASH") \
            or hashlib.sha256(decision_id.encode()).hexdigest()
        payload_hash = os.environ.get("AION_BURN_PAYLOAD_HASH") \
            or hashlib.sha256(
                ("payload:" + decision_id).encode()).hexdigest()
        _barrier()
        try:
            ledger.burn(decision_id=decision_id,
                        proposal_id=proposal,
                        manifest_hash=manifest_hash,
                        payload_hash=payload_hash,
                        recorded_at=_ts(0))
        except LedgerError as exc:
            print(f"burn refused: {exc}", file=sys.stderr)
            return 4
        return 0

    if mode == "recover":
        loop_subdir = os.environ.get("AION_LOOP_SUBDIR", "loop-state")
        ledger = ShipLedger(base / "verifier-home")
        loop = CoreLoop(base / loop_subdir)
        _barrier()
        outcomes = recover_ship_tx(
            ledger, loop, root=base / "repo",
            anchor_path=anchor_path_for(base) if ANCHORED else None)
        print(json.dumps(outcomes))
        return 0

    parts = build_or_load(base)
    ledger = ShipLedger(parts["home"])
    anchor_path = ensure_anchor(base, ledger) if ANCHORED else None
    if os.environ.get("AION_SETUP_ONLY"):
        return 0
    install_crash_patches()
    _barrier()
    try:
        record_ship(
            parts["loop"], root=parts["repo"],
            manifest=parts["manifest"], signed=parts["envelope"],
            signing_key=KEY, ledger=ledger, coders=CODERS,
            reviewers=REVIEWERS, delta=DELTA,
            release=parts["release"],
            expected_attestation=parts["satt"],
            expected_ledger_head=ledger.head(),
            anchor_path=anchor_path)
    except ShipRefused as exc:
        print(str(exc), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
