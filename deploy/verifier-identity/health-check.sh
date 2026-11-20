#!/usr/bin/env bash
# Thin launcher for the deployment health check
# (deploy/verifier-identity/health_check.py): root-only, execs
# the checker with PYTHONPATH=<repo root>. The checker itself is
# read-only against the deployment — see its docstring.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "health-check.sh: must be run as root" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

exec env PYTHONPATH="${REPO_ROOT}" python3 \
    "${SCRIPT_DIR}/health_check.py" "$@"
