"""Exits with an unhandled code and no protocol document."""
import sys

def main():
    sys.stdin.buffer.read()
    return 7

if __name__ == "__main__":
    sys.exit(main())
