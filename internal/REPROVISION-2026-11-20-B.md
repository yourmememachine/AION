# Verifier deployment RE-PROVISIONING B — 2026-11-20 (second VM OS reset, cycle-13 code)

The VM's OS state reset again: `aion-verifier` user,
`/etc/aion-verifier/` and `/var/lib/aion-verifier/` were all gone
(verified before starting). The documented ceremony in
`internal/REPROVISION-2026-11-20.md` was re-run exactly, against
the CURRENT repo code (cycle-13 tree, staged fresh from
`~/workspace/ai`). No repo code or tests were modified —
operations only. No git commands were run.

## What was run, in order

1. `deploy/verifier-identity/setup.sh` — recreated system user
   `aion-verifier` uid=997 gid=992, `nologin` shell, home
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
   `aion-verifier:aion-verifier` 0600. Key id reported in the
   smoke attestation: `key-edff2c569bfce4b4`.
4. Staged code copy refreshed at `/var/lib/aion-verifier/code`:
   content mirror of `core eval memory oversight signing selfmod
   trust` + `deploy/verifier-identity`, bytecode excluded,
   root-owned, `a+rX` (verifier-readable, not verifier-owned,
   not world-writable).
5. Registry provisioned **as the verifier** (via `runuser`,
   staged code on `PYTHONPATH`, script fed via stdin because
   `/tmp` is not readable by `aion-verifier` — same quirk as the
   earlier record): initial operator set — 3 public / 6 sealed /
   1 golden general-knowledge items, sealed and golden recorded
   under actor `operator-ceremony`. Item wording was recreated
   to the documented counts/domains (previous text was not
   recorded; nothing depends on it — live tests read expected
   answers from the registry itself). Sealed manifest
   `574ff877a81f71c962d22ee2a5a481c6f58d43d128a41fba0ce08fb63ba81129`.
6. Anchor ceremony **outside production**: temporary
   research-mode ceremony env (root 0600, at
   `/etc/aion-verifier/ceremony.env`) with
   `AION_ANCHOR_INIT=1` + `AION_BUDGETS_ANCHOR_INIT=1`, one
   bootstrap invocation (junk `verify_envelope`,
   `{"envelope": {}}`) through the real wrapper → both anchors
   initialised at genesis (head `000…0`, signing seq 0).
   Ceremony env deleted afterwards; the real env never carried
   an INIT flag.
7. Live production verification: a `sealed_eval` with the
   all-correct answers through the real wrapper under the real
   production env — score 1.0 (6/6), signed by `verifier-main`,
   response reported `deployment_mode: production` from inside
   the process; signing ledger + budgets created, anchors
   advanced (signing anchor seq 1).
8. Final operator budget reset (documented ceremony): budgets
   store + budgets anchor deleted, ONE bootstrap run outside
   production (research-mode ceremony env with
   `AION_BUDGETS_ANCHOR_INIT=1` only) re-pinned the budgets
   anchor at the fresh store's genesis head (`000…0`).
   Ceremony env deleted. Delivered state before verification:
   production mode, no INIT flags anywhere under
   `/etc/aion-verifier/`, fresh query budgets, signing ledger
   holding the one provisioning smoke signature with its anchor
   in exact agreement.

## Verification evidence (in the required order)

### 1. Deployment health check — 10/10 PASS

Command: `bash deploy/verifier-identity/health-check.sh`

```
PASS user: aion-verifier exists, shell /usr/sbin/nologin, home /var/lib/aion-verifier/home
PASS group-membership: group aion-verifier effective members: ['aion-verifier']; no supplementary group memberships beyond the primary group
PASS directories: base/home/keys/anchors/registry are aion-verifier-owned 0700; env dir root 0700, env file root 0600
PASS env-file: env file parses under the wrapper allowlist, required keys non-empty, values validate as the verifier validates them, paths are bound to the deployment base, no INIT flags, AION_DEPLOYMENT_MODE=production
PASS key-file: /var/lib/aion-verifier/keys/gate.key is aion-verifier 0600, loads under signing.load_signing_key and is not a known test key
PASS anchors: signing anchor verifies (incl. reanchor audit) and its head/seq exactly equal the live signing ledger; budgets anchor head matches the budget store head and the store's integrity verifies
PASS registry: registry validated entirely on a copy: 6 sealed items, manifest 574ff877a81f…; the live registry at /var/lib/aion-verifier/registry was never opened, so its access log is untouched
PASS state-files: 4 state files are aion-verifier-owned regular files with no world access and no special bits
PASS staged-code: staged copy at /var/lib/aion-verifier/code matches the repo for core, eval, memory, oversight, signing, selfmod, trust and deploy/verifier-identity (sha256); no bytecode, no root-level .py files, no verifier-owned or world-writable staged files
PASS effective-mode: verifier started under the wrapper, reported effective mode production from inside the process, rejected a junk envelope; no signing was performed or verified
health-check: 10/10 checks passed
```

### 2. Live wiring test — RAN (not skipped) and PASSED

Command: `python3 -m unittest tests.test_trust_wiring.LiveProductionWiringTests`

Exact output:
```
.
----------------------------------------------------------------------
Ran 1 test in 0.123s

OK
```

Verbose re-run (junk `verify_envelope` probe, consumes no budget):
```
test_production_client_against_live_deployment (tests.test_trust_wiring.LiveProductionWiringTests.test_production_client_against_live_deployment) ... ok
Ran 1 test in 0.131s
OK
```

### 3. Production deployment suite

Command: `python3 -m unittest tests.test_trust_production_deploy`

First run (immediately after the budget reset):
```
..................
----------------------------------------------------------------------
Ran 18 tests in 3.060s

OK
```
18 tests, all ran, none skipped — including `test_10`/`test_11`
running and passing on the fresh budgets.

Verbose re-run immediately afterwards:
`Ran 18 tests — OK (skipped=2)`, with `test_10` and `test_11`
in their by-design skip state
("live budget state already consumed this transcript; an
operator budget reset is required before this live test can
run again"), all other 16 tests `ok`. This is the expected
post-run state, exactly as in the earlier record.

### 4. Identity + unprivileged denial

- `id aion-verifier` → `uid=997(aion-verifier) gid=992(aion-verifier) groups=992(aion-verifier)`, group single-member.
- `runuser -u nobody -- cat /var/lib/aion-verifier/keys/gate.key` → `Permission denied` (exit 1, no output).
- `runuser -u nobody -- ls /var/lib/aion-verifier/keys` → `Permission denied` (exit 2).

## Deviations from the earlier record

- None in procedure. Same steps, same env values, same counts.
- New sealed manifest (`574ff877…`, vs `ed5c594a…` earlier)
  because the recreated general-knowledge item wording differs;
  the earlier record states wording is not depended upon.
- New signing key (fresh generation, as required after a reset).
- uid is again 997 (gid 992 this run); uid is not stable across
  resets and nothing depends on its value.
- Staged code is the current cycle-13 tree, staged fresh;
  health-check staged-code sha256 comparison passes against it,
  and the live wiring test (cycle-13) runs and passes against
  this deployment — it skipped in earlier cycles only because
  it had not been written / provisioned for at that time.
