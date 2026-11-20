"""Floods stderr (200 KiB) and then answers with a proper error
document at exit 2. Proves the client drains stderr and still
maps the failure correctly."""
import json
import sys

def main():
    raw = sys.stdin.buffer.read()
    request = json.loads(raw.decode("utf-8"))
    sys.stderr.write("flood " * 40000)
    sys.stderr.flush()
    doc = {"v": "trust-response/1",
           "request_id": request["request_id"],
           "mode": request["mode"], "status": "error", "result": None,
           "error": {"code": "test_flood", "detail": "flooded"}}
    sys.stdout.write(json.dumps(doc))
    return 2

if __name__ == "__main__":
    sys.exit(main())
