#!/usr/bin/env bash
# Create the dedicated OS identity for the AION verifier.
#
# Idempotent and root-only. Creates:
#   * system user `aion-verifier` (nologin shell, no password login)
#   * /var/lib/aion-verifier/{home,keys,anchors,registry}
#       owned aion-verifier:aion-verifier, mode 0700
#   * /etc/aion-verifier/ (root-owned, 0700) and, ONLY if absent,
#     /etc/aion-verifier/verifier.env (root-owned, 0600) — a
#     template the operator fills in; an existing env file is
#     never overwritten.
#
# This script does NOT generate a signing key, does NOT copy a
# registry, and does NOT start anything. Key generation and the
# registry copy are separate operator ceremonies (see README.md):
# bundling them here would put key material creation inside a
# script that might be run casually.
#
# Honest scope: this separates the verifier from OTHER OS users
# on the same machine. It does not protect anything from root.
set -euo pipefail

VERIFIER_USER="aion-verifier"
BASE="/var/lib/aion-verifier"
ENV_DIR="/etc/aion-verifier"
ENV_FILE="${ENV_DIR}/verifier.env"
NOLOGIN="/usr/sbin/nologin"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "setup.sh: must be run as root" >&2
    exit 1
fi

if id "${VERIFIER_USER}" >/dev/null 2>&1; then
    # Converge, don't just keep: a pre-existing user created by
    # hand (or by an older provisioning path) may carry a login
    # shell or a different home, which would silently weaken the
    # boundary this script exists to create. usermod re-asserts
    # the nologin shell and the verifier home on every re-run;
    # it does not move any existing home contents (-d without -m
    # only rewrites the passwd entry).
    usermod --shell "${NOLOGIN}" --home "${BASE}/home" \
        "${VERIFIER_USER}"
    echo "setup.sh: user ${VERIFIER_USER} already exists, converged shell/home"
else
    useradd --system \
        --home-dir "${BASE}/home" \
        --shell "${NOLOGIN}" \
        --no-create-home \
        --user-group \
        "${VERIFIER_USER}"
    echo "setup.sh: created system user ${VERIFIER_USER}"
fi

# install -d is idempotent: it creates missing directories and
# re-asserts owner/mode on existing ones without touching contents.
install -d -o "${VERIFIER_USER}" -g "${VERIFIER_USER}" -m 0700 \
    "${BASE}" "${BASE}/home" "${BASE}/keys" "${BASE}/anchors" \
    "${BASE}/registry"

install -d -o root -g root -m 0700 "${ENV_DIR}"
if [[ -e "${ENV_FILE}" ]]; then
    echo "setup.sh: ${ENV_FILE} already exists, not overwriting"
else
    # umask + install mode: the file must never be group/world
    # readable, even briefly enough to matter for a template that
    # the operator is about to fill with real paths.
    umask 077
    cat > "${ENV_FILE}" <<'EOF'
# AION verifier environment — read by run-verifier.sh, passed to
# the verifier process via `runuser -u aion-verifier -- env ...`.
# Plain KEY=VALUE lines only (no quoting, no shell expansion);
# this file is parsed, never sourced. Root-owned, mode 0600.
# Fill in real values; the verifier refuses to run while any
# required value is empty.
AION_VERIFIER_KEY_PATH=/var/lib/aion-verifier/keys/gate.key
AION_VERIFIER_SIGNER_ID=
AION_VERIFIER_ACTOR_ID=
AION_REGISTRY_DIR=/var/lib/aion-verifier/registry
AION_VERIFIER_HOME=/var/lib/aion-verifier/home
AION_VERIFIER_TTL_SECONDS=
AION_VERIFIER_PURPOSE=
# Sealed-eval query budgets (trust/verifier_main.py). These ARE
# the verifier's compiled defaults, written out so the deployed
# values are visible and tunable here; raise/lower deliberately,
# never delete-and-assume. (Omitting a key entirely also yields
# the default, but an operator setting one in a file whose
# wrapper allowlist lacked it used to hard-fail the launch.)
AION_VERIFIER_PROPOSAL_BUDGET=25
AION_VERIFIER_IDENTITY_BUDGET=500
AION_ANCHOR_PATH=/var/lib/aion-verifier/anchors/signing.anchor.json
AION_ANCHOR_INIT=
AION_BUDGETS_ANCHOR_PATH=/var/lib/aion-verifier/anchors/budgets.anchor.json
AION_BUDGETS_ANCHOR_INIT=
# Ceremony operator authority (cycle 19): comma-separated
# operator ids authorised to obtain ceremony authorisations
# (mode ceremony_authorise). The list lives ONLY in this
# protected env file — a request can never carry it. Production
# refuses startup while this is empty; research loads with the
# mode disabled. Fill with the operator ids, e.g.
# AION_CEREMONY_OPERATORS=operator-uma
AION_CEREMONY_OPERATORS=
# Production steady state (after the one-time anchor ceremony):
# anchoring is mandatory and fail-closed, and the INIT flags
# above are refused. Research deployments must set this variable
# explicitly to "research" (research is NOT rollback-protected);
# leaving it unset or blank makes the verifier refuse to start
# (fail-closed) — there is no default mode.
AION_DEPLOYMENT_MODE=production
EOF
    chown root:root "${ENV_FILE}"
    chmod 0600 "${ENV_FILE}"
    echo "setup.sh: wrote template ${ENV_FILE} (fill it in)"
fi

echo "setup.sh: done. Layout:"
ls -ld "${BASE}" "${BASE}/home" "${BASE}/keys" "${BASE}/anchors" \
    "${BASE}/registry" "${ENV_FILE}"
