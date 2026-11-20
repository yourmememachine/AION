"""Dies by signal mid-run, like a verifier killed during work."""
import os
import sys

def main():
    sys.stdin.buffer.read()
    os.abort()

if __name__ == "__main__":
    main()
