#!/usr/bin/env bash
# Launch the AION verifier as the dedicated `aion-verifier` OS user.
#
# Usage: run-verifier.sh < request.json > response.json
#
# The wire protocol is one JSON document in on stdin and one JSON
# document out on stdout (trust/protocol.py); this wrapper passes
# both through untouched — it is a launcher, not a proxy. It is
# meant to be run by the orchestrator as root: `runuser` requires
# root (or an equivalent PAM authorisation) to assume the
# verifier's uid.
#
# Configuration comes ONLY from the root-owned env file
# (default /etc/aion-verifier/verifier.env, mode 0600, created as
# a template by setup.sh). The file is PARSED line by line against
# an allowlist of variable names — never sourced — so a malformed
# or hostile env file cannot smuggle shell into the orchestrator.
# Overrides for testing: AION_VERIFIER_ENV_FILE names a different
# env file (same ownership/mode checks apply); AION_REPO_ROOT
# names the code checkout (default: the repo this script lives
# in). The verifier code must be READABLE by the aion-verifier
# user — see README.md.
set -euo pipefail

VERIFIER_USER="aion-verifier"
ENV_FILE="${AION_VERIFIER_ENV_FILE:-/etc/aion-verifier/verifier.env}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${AION_REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "run-verifier.sh: must be run as root (runuser requires it)" >&2
    exit 1
fi
if ! id "${VERIFIER_USER}" >/dev/null 2>&1; then
    echo "run-verifier.sh: user ${VERIFIER_USER} does not exist; run setup.sh first" >&2
    exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "run-verifier.sh: env file ${ENV_FILE} is missing" >&2
    exit 1
fi
# The env file names the key path and the signer identity: it is
# part of the trust configuration, so it must be root-owned and
# not group/world-accessible.
env_owner="$(stat -c %U "${ENV_FILE}")"
env_mode="$(stat -c %a "${ENV_FILE}")"
if [[ "${env_owner}" != "root" || "${env_mode}" != "600" ]]; then
    echo "run-verifier.sh: ${ENV_FILE} must be owned by root with mode 600 (found ${env_owner} ${env_mode})" >&2
    exit 1
fi

ALLOWED_KEYS=(
    AION_VERIFIER_KEY_PATH
    AION_VERIFIER_SIGNER_ID
    AION_VERIFIER_ACTOR_ID
    AION_REGISTRY_DIR
    AION_VERIFIER_HOME
    AION_VERIFIER_TTL_SECONDS
    AION_VERIFIER_PURPOSE
    AION_VERIFIER_PROPOSAL_BUDGET
    AION_VERIFIER_IDENTITY_BUDGET
    AION_ANCHOR_PATH
    AION_ANCHOR_INIT
    AION_BUDGETS_ANCHOR_PATH
    AION_BUDGETS_ANCHOR_INIT
    AION_DEPLOYMENT_MODE
    AION_CEREMONY_OPERATORS
    AION_CEREMONY_EVIDENCE_DIR
    AION_CEREMONY_SIGNING_SEED_PATH
    AION_CEREMONY_CONSUMPTION_ANCHOR_PATH
    AION_CEREMONY_CONSUMPTION_ANCHOR_INIT
    AION_SUPERSESSION_APPROVER_PUBLIC_KEY
)

declare -A CONFIG=()
while IFS= read -r line || [[ -n "${line}" ]]; do
    # Strip a possible CR and surrounding whitespace.
    line="${line%$'\r'}"
    [[ "${line}" =~ ^[[:space:]]*$ ]] && continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    if [[ ! "${line}" =~ ^([A-Z_]+)=(.*)$ ]]; then
        echo "run-verifier.sh: malformed line in ${ENV_FILE}: ${line}" >&2
        exit 1
    fi
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    allowed=0
    for candidate in "${ALLOWED_KEYS[@]}"; do
        if [[ "${key}" == "${candidate}" ]]; then allowed=1; break; fi
    done
    if [[ "${allowed}" -ne 1 ]]; then
        echo "run-verifier.sh: ${key} is not an allowlisted verifier variable" >&2
        exit 1
    fi
    if [[ -v CONFIG[${key}] ]]; then
        echo "run-verifier.sh: duplicate key ${key} in ${ENV_FILE}: each allowlisted variable may appear at most once" >&2
        exit 1
    fi
    CONFIG["${key}"]="${value}"
done < "${ENV_FILE}"

# Deployment-mode contract (Trust Boundary v3.1, fail-closed):
# the mode is an explicit launcher-level contract, never a
# default. Absent, present-but-empty, or anything other than
# exactly "production" / "research" refuses the launch here —
# before runuser — so a blanked or deleted mode line in the env
# file can never silently downgrade a production deployment to
# research mode (anchoring optional, INIT flags allowed). The
# verifier enforces the same contract again at config load.
DEPLOYMENT_MODE="${CONFIG[AION_DEPLOYMENT_MODE]:-}"
if [[ -z "${DEPLOYMENT_MODE}" ]] \
        || { [[ "${DEPLOYMENT_MODE}" != "production" ]] \
             && [[ "${DEPLOYMENT_MODE}" != "research" ]]; }; then
    echo "run-verifier.sh: AION_DEPLOYMENT_MODE must be set explicitly to 'production' or 'research' in ${ENV_FILE} (found: '${DEPLOYMENT_MODE}'); refusing to launch" >&2
    exit 1
fi

VERIFIER_HOME_DIR="$(getent passwd "${VERIFIER_USER}" | cut -d: -f6)"
if [[ -z "${VERIFIER_HOME_DIR}" ]]; then
    VERIFIER_HOME_DIR="/var/lib/aion-verifier/home"
fi

# Build a clean environment: nothing from the orchestrator's shell
# leaks into the verifier except the allowlisted configuration.
ENV_ARGS=(
    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    "HOME=${VERIFIER_HOME_DIR}"
    "PYTHONPATH=${REPO_ROOT}"
    "PYTHONDONTWRITEBYTECODE=1"
)
for key in "${ALLOWED_KEYS[@]}"; do
    if [[ -n "${CONFIG[${key}]:-}" ]]; then
        ENV_ARGS+=("${key}=${CONFIG[${key}]}")
    fi
done

cd "${REPO_ROOT}"
# Files the verifier creates (ledger, budgets, anchors) must land
# 0600, not the group-writable 0660 a looser inherited umask gave.
umask 077
exec runuser -u "${VERIFIER_USER}" -- env -i "${ENV_ARGS[@]}" \
    python3 -m trust.verifier_main
