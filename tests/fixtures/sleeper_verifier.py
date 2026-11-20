"""Reads the request, then sleeps far past any test timeout."""
import sys
import time

def main():
    sys.stdin.buffer.read()
    time.sleep(60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
