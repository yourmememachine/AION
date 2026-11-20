"""Self-modification package: canary staging, gated commit, rollback."""

from .canary import (
    MAX_CHANGE_BYTES,
    MAX_FILE_BYTES,
    MAX_FILES_PER_CHANGE,
    MAX_TREE_BYTES,
    PROPOSAL_STATES,
    ApplyResult,
    CanaryError,
    CanaryManager,
    ChangeProposal,
    CorruptJournalError,
    FileChange,
    NeedsRecoveryError,
    canonicalise_path,
)

__all__ = [
    "MAX_CHANGE_BYTES",
    "MAX_FILE_BYTES",
    "MAX_FILES_PER_CHANGE",
    "MAX_TREE_BYTES",
    "PROPOSAL_STATES",
    "ApplyResult",
    "CanaryError",
    "CanaryManager",
    "ChangeProposal",
    "CorruptJournalError",
    "FileChange",
    "NeedsRecoveryError",
    "canonicalise_path",
]
