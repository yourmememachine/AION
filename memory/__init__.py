"""Memory package: gated long-term store, strategy solver, reuse test."""

from .reuse import ReuseError, run_reuse_measurement
from .solver import (
    FAMILIES,
    NAIVE,
    VOCABULARY,
    Explanation,
    StrategySolver,
    classify,
    derive_lessons,
)
from .store import (
    CorruptMemoryError,
    MemoryError,
    MemoryStore,
    TamperDetectedError,
    content_hash_for,
    decide_write,
)

__all__ = [
    "FAMILIES",
    "NAIVE",
    "VOCABULARY",
    "CorruptMemoryError",
    "Explanation",
    "MemoryError",
    "MemoryStore",
    "ReuseError",
    "StrategySolver",
    "TamperDetectedError",
    "classify",
    "content_hash_for",
    "decide_write",
    "derive_lessons",
    "run_reuse_measurement",
]
