"""Cycle-32 demo check: exits 0 iff trust/proofcarry.py is present
and carries the proof-artefact format + seam. Deterministic:
prints exactly one fixed line on success, nothing on failure."""
import sys
from pathlib import Path

def main():
    p = Path("trust/proofcarry.py")
    if not p.is_file():
        return 1
    text = p.read_text(encoding="utf-8")
    if "proof-artefact/1" in text and "record_ship_with_proof" in text:
        print("PROOFCARRY_PRESENT")
        return 0
    return 1

if __name__ == "__main__":
    sys.exit(main())
