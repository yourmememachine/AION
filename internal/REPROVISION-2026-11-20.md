# Verifier deployment RE-PROVISIONING — 2026-11-20 (post VM OS reset)

The VM's OS state reset again on 2026-11-20: the `aion-verifier`
OS user, `/etc/aion-verifier/` and `/var/lib/aion-verifier/` were
gone (only `~/workspace` persisted). The live production-deployment
tests skipped by design ("live deployment not provisioned") and the
full suite showed ~25 skips instead of the normal 2. This record
covers the re-run of the documented operator ceremony
(`deploy/verifier-identity/README.md`, `setup.sh`; cycles 10–11
procedure). No production code or tests were modified — operations
only.

## What was run, in order

1. `deploy/verifier-identity/setup.sh` — recreated the system user
   `aion-verifier` (**uid 997** this time; was 999 in cycle 10,
   997 in cycle 9 — the uid is not stable across resets and nothing
   depends on its value), `nologin` shell, home
   `/var/lib/aion-verifier/home`; verifier-owned 0700 dirs
   `home/ keys/ anchors/ registry/`; root-owned 0700
   `/etc/aion-verifier/` with the 0600 env template.
2. Env filled (root, 0600): signer `verifier-main`, actor
   `verifier-actor`, TTL 900, purpose `memory-commit`, budgets
   25/500 (template values), both anchor paths under
   `/var/lib/aion-verifier/anchors/`, INIT flags blank,
   `AION_DEPLOYMENT_MODE=production`.
3. Signing key generated with the repo's own tooling
   (`signing.generate_key_file`) at
   `/var/lib/aion-verifier/keys/gate.key`, handed over
   `aion-verifier:aion-verifier` 0600.
4. Staged code copy refreshed at `/var/lib/aion-verifier/code`:
   content mirror of `core eval memory oversight signing selfmod
   trust` + `deploy/verifier-identity`, bytecode excluded,
   root-owned, `a+rX` (verifier-readable, not verifier-owned, not
   world-writable).
5. Registry provisioned **as the verifier** (via `runuser`, staged
   code on `PYTHONPATH`): the initial operator set — 3 public /
   6 sealed / 1 golden general-knowledge items, sealed and golden
   recorded under actor `operator-ceremony`. Sealed manifest
   `ed5c594a76a9f790…`. (Item wording was recreated to the
   documented counts/domains; the previous item text was not
   recorded anywhere and nothing depends on it — the live tests
   read expected answers from the registry itself.)
6. Anchor ceremony **outside production**: a temporary
   research-mode ceremony env (root 0600) with
   `AION_ANCHOR_INIT=1` + `AION_BUDGETS_ANCHOR_INIT=1`, one
   bootstrap invocation (junk `verify_envelope`) through the real
   wrapper → both anchors initialised at genesis. Ceremony env
   deleted afterwards; the real env never carried an INIT flag.
7. Live production verification: a `sealed_eval` with the
   all-correct answers through the real wrapper under the real
   production env — score 1.0 (6/6), signed by `verifier-main`,
   response reported `deployment_mode: production` from inside
   the process; signing ledger + budgets created, anchors
   advanced.
8. Final operator budget reset (documented ceremony, as in
   cycles 10–11): budgets store + budgets anchor deleted, ONE
   bootstrap run outside production (research-mode ceremony env
   with `AION_BUDGETS_ANCHOR_INIT=1` only) re-pinned the budgets
   anchor at the fresh store's genesis head — so the delivered
   deployment starts with fresh budgets (step 7's smoke run had
   consumed the all-correct transcript). Ceremony env deleted.

## Verification evidence

- `id aion-verifier` → `uid=997(aion-verifier) gid=992(aion-verifier)`,
  group single-member.
- Deployment health check (`deploy/verifier-identity/health-check.sh`):
  **10/10 PASS** — user, group-membership, directories, env-file,
  key-file, anchors (exact head/seq vs live ledger; budgets head
  match), registry (validated on a copy: 6 sealed items), state-files,
  staged-code (sha256 match vs repo), effective-mode (production,
  reported from inside the running verifier).
- Unprivileged denial, direct: `runuser -u nobody -- cat
  /var/lib/aion-verifier/keys/gate.key` → Permission denied;
  `ls` of the keys dir → Permission denied.
- Live production suite (`tests/test_trust_production_deploy.py`):
  **18 tests, OK — all ran, none skipped**, including
  `test_10`/`test_11` running and passing on the fresh budgets
  (they consumed their transcripts in that run and return to the
  by-design skip state until the next operator budget reset).
- Full suite: **1077 tests, OK (skipped=2)** — skips back to the
  by-design 2 (live `test_10`/`test_11` post-run consumed state).

## Notes

- One environmental quirk: `/tmp` is not readable by the
  `aion-verifier` user on this VM, so the registry-provisioning
  script was fed to the as-verifier Python process via stdin
  instead of a temp file. No security check was bypassed; the
  provisioning ran as the verifier user against verifier-owned
  dirs exactly as documented.
- Steady state delivered: production mode, anchoring mandatory,
  no INIT flags anywhere under `/etc/aion-verifier/`, fresh query
  budgets, signing ledger holding the one provisioning smoke
  signature with its anchor in exact agreement.
