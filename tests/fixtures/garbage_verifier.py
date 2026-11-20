"""Writes non-JSON to stdout at exit 0."""
import sys

def main():
    sys.stdin.buffer.read()
    sys.stdout.write("this is not a protocol document")
    return 0

if __name__ == "__main__":
    sys.exit(main())
