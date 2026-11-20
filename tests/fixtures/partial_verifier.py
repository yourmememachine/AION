"""Writes half a document, then dies without finishing it."""
import os
import sys

def main():
    sys.stdin.buffer.read()
    sys.stdout.write('{"v": "trust-response/1", "request_id": "req-')
    sys.stdout.flush()
    os._exit(3)

if __name__ == "__main__":
    main()
