"""Writes more than the response cap to stdout at exit 0."""
import sys

def main():
    sys.stdin.buffer.read()
    sys.stdout.write("x" * (2 << 20))
    return 0

if __name__ == "__main__":
    sys.exit(main())
