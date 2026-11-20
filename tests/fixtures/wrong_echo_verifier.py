"""Returns a well-formed response document echoing the WRONG id."""
import json
import sys

def main():
    sys.stdin.buffer.read()
    doc = {"v": "trust-response/1", "request_id": "req-0000000000000000",
           "mode": "gate", "status": "ok", "result": {}, "error": None}
    sys.stdout.write(json.dumps(doc))
    return 0

if __name__ == "__main__":
    sys.exit(main())
