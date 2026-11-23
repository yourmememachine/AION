"""Trust boundary package: build manifests, the out-of-process
verifier, and the signed ship path.

Prototype honesty: this is process isolation on one machine under
one OS user — not a separate-machine trust domain. See
trust/README.md.
"""

from .attestation import (
    EVAL_DOMAIN,
    answers_hash_for,
    registry_digest_for,
    sign_eval_attestation,
    verify_eval_attestation,
)
from .client import GateOutcome, Verdict, VerifierClient
from .errors import (
    ShipRefused,
    TrustError,
    VerifierConfigError,
    VerifierError,
    VerifierProtocolError,
    VerifierTimeout,
    VerifierUnavailable,
)
from .ledger import (
    CorruptLedgerError,
    HashChainJournal,
    LedgerError,
    ShipLedger,
    SigningLedger,
)
from .manifest import (
    BUCKETS,
    BuildManifest,
    ManifestDiff,
    ManifestError,
    build_manifest,
    canonicalise_path,
    manifest_from_dict,
    manifest_from_json,
    verify_manifest,
    write_manifest,
)
from .release import (
    ReleaseRecord,
    build_release_record,
    release_from_dict,
    release_from_json,
)
from .anchoring import (
    AnchorError,
    JournalIntegrityError,
    force_reanchor,
    initialise_anchor,
    load_anchor,
    update_anchor,
    verify_anchor,
)
from .budgets import (
    BudgetError,
    BudgetStore,
)
from .pathpolicy import (
    POLICY_VERSION,
    classify as classify_path,
    is_protected as is_protected_path,
)
from .shipcheck import check_ship, record_ship, recover_ship_tx
from .shiptx import ShipTxJournal, derive_tx_id
from .wiring import (
    commit_production,
    open_production_store,
    production_client,
)

__all__ = [
    "EVAL_DOMAIN",
    "answers_hash_for",
    "registry_digest_for",
    "sign_eval_attestation",
    "verify_eval_attestation",
    "GateOutcome",
    "Verdict",
    "VerifierClient",
    "ShipRefused",
    "TrustError",
    "VerifierConfigError",
    "VerifierError",
    "VerifierProtocolError",
    "VerifierTimeout",
    "VerifierUnavailable",
    "CorruptLedgerError",
    "HashChainJournal",
    "LedgerError",
    "ShipLedger",
    "SigningLedger",
    "BUCKETS",
    "BuildManifest",
    "ManifestDiff",
    "ManifestError",
    "build_manifest",
    "canonicalise_path",
    "manifest_from_dict",
    "manifest_from_json",
    "verify_manifest",
    "write_manifest",
    "ReleaseRecord",
    "build_release_record",
    "release_from_dict",
    "release_from_json",
    "JournalIntegrityError",
    "check_ship",
    "record_ship",
    "commit_production",
    "open_production_store",
    "production_client",
]
