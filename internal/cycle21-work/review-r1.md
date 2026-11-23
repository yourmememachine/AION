# Cycle 21 — War-room review rev-r1 (scope fidelity, BLIND)

Reviewer: rev-r1. Scope: fidelity to DESIGN-FINAL rulings R1–R12,
CROSS-CHECK-14 requirements, and DECISION-CONSUMPTION-HEAD.md claims —
nothing else. Reviewed the uncommitted working tree (coordinator-verified
1464 tests OK, skipped=28; baseline 1406). No other reviewer's files read.
No code edited.

Score: 0.87 — Verdict: FIX

The code build is faithful to almost every ruling, in the ruled files,
with no hard-boundary breach. The FIX rests on one ruled deliverable not
built (the deploy README update, which also leaves a now-false
"exactly 0600" claim in a deployment document) and on crash-test
coverage that cannot be traced to the six ruled kill points. Both are
small, bounded fixes; neither requires redesign.

## Ruling-by-ruling walk (R1–R12)

- R1 Store location — BUILT. `CeremonyConsumptionLedger`,
  FILENAME "ceremony-consumptions.json" (trust/ledger.py:688,729) under
  the verifier home; new mode `_mode_ceremony_consume`
  (trust/verifier_main.py:2394, registered :2573 and
  trust/protocol.py:28-30). No new env var in the production diff
  (grep of `git diff` for environ/getenv additions: only the pre-existing
  `AION_CEREMONY_SIGNING_SEED_PATH` pop and a refusal string). Deploy
  wrapper untouched: `git diff -- deploy/` is empty and
  deploy/verifier-identity/run-verifier.sh still lists exactly 17
  allowlist names. DECISION-CONSUMPTION-HEAD.md claims ("no new env var",
  "wrapper allowlist unchanged") are TRUE of the diff.
- R2 Consume protocol — BUILT. Body exactly `{"signed_authorisation"}`
  (verifier_main.py:2394 ff.; client sends exactly that dict,
  trust/client.py:621). Validation order (config gate → strict key set →
  parse → verify+expiry under verifier-derived key → already-consumed →
  issuance presence/field-match → head rules → commit) matches the ruling
  step for step, including already-consumed BEFORE issuance. Refusal
  codes in the production diff are exactly the ruled set
  (malformed_request / ceremony_authorisation_invalid /
  ceremony_authorisation_expired / ceremony_already_consumed /
  ceremony_not_issued / ceremony_head_regression / ledger_failed /
  ceremony_seed_unconfigured) with ruled exits (_malformed=2, _config=3,
  verifier_main.py:359-363). No extra refusal code was found. Response
  carries authorisation_id/ceremony_id echoes, candidate as
  new_cycle_seq/new_payload_hash, consumption_seq; the client asserts
  exact key set, echoes, and int ≥ 1 (trust/client.py:576-642).
  Operator allowlist and evidence resolution are NOT re-checked —
  confirmed by test_seed_unconfigured_is_the_only_gate
  (tests/test_trust_ceremony_consume.py:391).
- R3 Head rules — BUILT. `check_head` (trust/ledger.py:775) implements
  candidate-behind / at-head-same-hash→already_consumed / at-head-fork /
  ahead, the merged old-pin not-behind rule (ahead passes), and
  initial_anchor against a non-empty journal → regression; single-use
  re-checked inside `append_consumption` (trust/ledger.py:834) against
  freshly reloaded entries in the bounded retry loop, loser surfacing as
  AlreadyConsumedError. Recovery/claim wording (ceremony head, not pin
  head) is present in the ledger and mode docstrings; no overclaim found.
- R4 Commit/mirror/ordering — BUILT. Consumption append is the commit;
  mirror via `SigningLedger.append_ceremony_consumption`
  (trust/ledger.py:426) with kind "consume", format
  "ceremony-consumption", EXISTING EXTRA_KEYS (no format migration);
  then `_update_anchor`. Mirror invoked only after a successful append;
  mirror failure → ledger_failed with the envelope burned (pinned by
  test_mirror_failure_after_commit_burns). The mode's step-5 mirror
  cross-check is scoped to kind="consume" + format="ceremony-consumption"
  exactly as the R4 trap requires — and it is what makes the R10
  rollback-resurrection wording true, so it is fidelity, not creep.
  Benign-interleaving / not-cross-ledger-atomic wording is in the mode
  docstring.
- R5 Ceremony-side integration — BUILT. `reanchor_pin` gains required
  keyword `consume_authorisation` with NO default (TypeError on omission,
  pinned by T1b), explicit None/non-callable refuses before envelope
  verification, one-argument callable invoked exactly once after all
  local checks and before record construction (spy tests pin 1-on-success
  / 0-on-local-refusals). signing/ imports nothing from trust/ (grep of
  the signing diff: no trust import). Transport lives in trust/client.py:
  `ceremony_consume` (:576) + `ceremony_consumer` (:644) translating
  Verifier* errors to SigningError. Offline trade-off and integrated-
  system claim wording appear verbatim in substance in the pin_ceremony
  module and function docstrings.
- R6 ceremony_history — BUILT (wording only). `_check_ceremony_history`
  and the admissibility table are untouched in the diff; requiredness
  unchanged; docstrings demote it to an audit/consistency input that can
  only refuse, with the verifier head authoritative, and COMPLETE-HISTORY
  demoted to an audit obligation (signing/pin_ceremony.py module
  docstring).
- R7 Crash contract — BUILT IN SUBSTANCE, coverage shortfall below
  (MEDIUM-2). Exact contract wording is in the mode docstring, the
  pin_ceremony docstrings, and the client consumer docstring; the client
  never auto-retries (single attempt per invocation). T-Cc is present
  (commit-then-raise consumer: nothing returned, second attempt refuses
  already-consumed, exactly one entry). Verifier-side: kill-before-append
  burns nothing, kill-after-append burns, mirror failure burns,
  two-process barrier race yields exactly one winner, corrupt journal
  fails closed as ledger_failed.
- R8 Differential suite — BUILT. New file
  tests/test_signing_ed25519_differential.py (481 lines; cycle-20 file
  not extended). RFC 8032 §7.1 KAT literals incl. the long-message
  vector; adversarial table with PER-CASE pinned (ours, openssl) pairs
  and a recorded probe (non-canonical R/A incl. sign-bit and x=−0
  spellings, S ∈ {L−1, L, L+1, 2^256−1} + S+L malleation agree-reject,
  all 8 small-order encodings as A and as R with the (False, True)
  divergent rows pinned, mixed torsion order 2/4/8, identity/zero,
  cross-vector swaps); exhaustive bit-flip sweep over signature (512),
  public key (256) and message against our verify only, with the 60 s
  subsample threshold asserted not reached; openssl differential with
  the ruled DER prefixes, byte-identical sign direction, skip-cleanly
  via shutil.which + setUpClass probe; seeded cross-implementation
  agreement on honest signatures. One literal deviation, documented in
  the file (:80-83,306-310): the "TEST 1024" message is 1023 bytes per
  the RFC's own length field, not the 1024 bytes DESIGN-FINAL says —
  an evidence-backed correction, not a shortfall (see LOW-3).
- R9 Seed hygiene — BUILT, with two small literal deviations (LOW-1,
  LOW-2). Shared helper `_check_owner_only_mode`
  (signing/gate_decision.py:230) used by both loaders; "exactly 0600"
  retired in both loaders and docstrings. Seed loader fd discipline
  (O_NOFOLLOW|O_NONBLOCK open, fstat S_ISREG + mode, bounded fd read —
  signing/ceremony_authorisation.py:261-330) on the ceremony loader
  ONLY; the gate loader keeps stat-then-read with the follow-up
  `signing-key-loader-fd-hardening` named in its docstring
  (gate_decision.py:325), as ruled. Owner-uid check seed-loader only,
  root-vacuous (ceremony_authorisation.py:300). Derivation-overlap
  closed set checked in `_load_config`'s pair block
  (verifier_main.py:571 ff.) — relations (2)–(6) and (8) each have a
  dedicated startup test; (1) is the pre-existing byte-equality check;
  the A-R4 dead relation (seed ∈ REFUSED_TEST_KEYS) is NOT implemented,
  as ruled; the mandatory residual wording ("catch accidents and known
  derivations, not arbitrary KDF overlap") is present.
- R10 Anchoring — BUILT. No anchoring of the consumption journal this
  cycle; the precise residual wording is in the
  CeremonyConsumptionLedger docstring, and the follow-up is stated to
  cover both journals jointly.
- R11 File ownership — BUILT except the README item (MEDIUM-1).
  `git diff --stat` + untracked list contain exactly the ruled files:
  Seat A (gate_decision, ceremony_authorisation, differential + seed-
  hygiene tests), Seat B (ledger, verifier_main, protocol,
  test_trust_ceremony_consume), Seat C (pin_ceremony, client,
  test_signing_pin_ceremony, test_trust_ceremony_authorisation,
  test_trust_ceremony_consumption), plus internal decision/design docs.
  No other production or test file changed. (The R9/R11 "separate
  bisectable commits" sequencing cannot be assessed: the build is
  uncommitted by design at review time.)
- R12 Helper discipline — BUILT. The reanchor() helper's default
  consumer is a real CeremonyConsumptionLedger-backed consumer
  (LedgerBackedConsumer opens a fresh ledger instance over the fixture
  dir per call, so refusals come only from persisted state), never an
  always-succeed fake; reset per consuming class's setUp, NOT per
  reanchor() call, so calls within a test share one journal. Fakes
  appear only where the fake is the subject (_CountingConsumer spies,
  T-Cc's commit-then-raise). T7′/T8′ are flipped and wire the real
  ledger-backed consumer; the subprocess suite
  (tests/test_trust_ceremony_consumption.py) wires the real verifier
  (replay across fresh clients, never-issued, expired, verifier-down
  fail-closed, mirror scoping). Minor wording drift only: the fixture
  is reset per test METHOD (setUp), which is stricter isolation than
  "per class fixture" but preserves the ruled property (continuity
  within a test, never per-call freshness).

## Hard boundaries — all held

- eval/ untouched: `git diff --stat -- eval/` empty; no eval/ path in
  status. PASS.
- Cycles 14–16 substance untouched: signing/state_snapshot.py has no
  diff; the snapshot/chain-gap logic in pin_ceremony is unchanged —
  the pin_ceremony diff is docstrings, the new keyword, its early gate,
  and the single consumption call site. PASS.
- Part A / Item A untouched: eval/gate.py, trust/pathpolicy.py,
  oversight/ — no diff, no status entries. PASS.
- DECISION-CONSUMPTION-HEAD.md vs build: store location, mode name,
  journal name/class, "no new env var", wrapper allowlist unchanged —
  all verified above. PASS.

## Findings

### MEDIUM-1 — Ruled deploy README update not built; stale "exactly 0600" claim remains
R11 assigns Seat B "deploy/verifier-identity/README.md (consumption
mode + recovery note, if modes are documented there)". The condition is
met: that README documents the ceremony modes and client ceremony
behaviour (e.g. its discussion of `ceremony_authorise` at first use).
Yet `git diff -- deploy/` is empty: no ceremony_consume mode, no
consumption journal, no burned-envelope recovery note was added.
Worse, the README still states at line 19 that gate.key is "itself
exactly 0600 — `load_signing_key` refuses any other mode", which R9
made false this cycle (0400 now loads; pinned by
tests/test_signing_ceremony_seed_hygiene.py:159). A deployment document
that misstates the key-file predicate is a fidelity defect, not a
nice-to-have. Fix: add the consumption-mode + recovery note and correct
the 0600 wording (and any other exactly-0600 loader claims) in that
README.

### MEDIUM-2 — Crash coverage cannot be traced to the ruled K1–K6 kill points
R7 rules "B's verifier-side kill points K1–K6 (wrapper-module os._exit
patches…)". tests/test_trust_ceremony_consume.py contains exactly two
os._exit wrapper modules (KILL_BEFORE_MODULE :423, KILL_AFTER_MODULE
:441), plus a mirror-failure patch, a barrier race, and a corrupt-
journal test — five scenarios, none labelled K1–K6, and no kill point
after the mirror / at the anchor step is exercised. Either one ruled
kill point is missing or the mapping exists but is unrecorded; on the
evidence in the diff the six-point requirement is not demonstrably met.
Fix: label the tests K1–K6 and add the missing kill point (post-mirror /
anchor boundary is the obvious gap), or record the coordinator ruling
that collapses the six points into the five scenarios.

### LOW-1 — One derivation-overlap relation beyond the ruled closed set
R9 calls the overlap list a "closed set". verifier_main.py:571 ff.
adds, under relation (7), seed == sha256(public key derived by treating
the HMAC key bytes as an Ed25519 seed) — a relation not in the ruled
list ((7) as ruled reads seed == sha256(own public key), which the code
also implements via (5)'s bytes) — with its own startup test
(test_seed_is_sha256_of_signing_keys_public_key_refused,
tests/test_trust_ceremony_consume.py:618). The code comment discloses
the "read both ways" choice. It is conservative (refuses more, in an
owned file), but it is an unruled addition to a set the ruling
explicitly closed. Record it as an adopted interpretation or drop it.

### LOW-2 — Shared predicate is stricter than the ruled formula
R9's predicate: accept iff mode & 0o077 == 0 AND owner-read set.
`_check_owner_only_mode` (signing/gate_decision.py:230) additionally
requires the owner-execute bit clear. The result is exactly the ruled
"in practice {0400, 0600}" set, so behaviour matches the ruling's
stated outcome; only the formula differs (0500/0700 would pass the
formula, fail the helper). Note for the record; no change needed
unless the formula was meant literally.

### LOW-3 — R8 long-message length: ruling says 1024 bytes, build pins 1023
DESIGN-FINAL R8 says "a long-message (1024-byte) vector". The suite
pins the RFC 8032 "TEST 1024" vector whose message is 1023 bytes per
the RFC's own length field, with the discrepancy documented in the
test file (:80-83). This is the correct evidence-backed reading of the
ruling's intent (the RFC vector), recorded here so the reconciliation
does not mistake it for a missing byte.

### LOW-4 — signed_in_future mapped to ceremony_authorisation_expired
verifier_main.py:2475 maps verify reasons ⊆ {expired, signed_in_future}
to the expired code. R2's table names only expiry for that code and
assigns all non-temporal failures to the invalid code; signed_in_future
is temporal, so the mapping is defensible and leaks no oracle, but it
is an interpretation not spelled out in the ruling. Record it in the
reconciliation.

## Scope-creep sweep (beyond the findings above)

- Production refusal codes: exactly the ruled set — no extras.
- Production env vars: none added; the only new env read anywhere is
  CEREMONY_TEST_BARRIER inside a test-harness wrapper string
  (tests/test_trust_ceremony_consume.py:469) — test-only synchronisation
  for the ruled two-process race, not a production env var and not an
  env fault hook (faults are injected by module patching, as ruled).
- Behaviour changes outside the ceremony/seed surface: none found.
  trust/ledger.py additions are the consumption ledger, its two error
  subclasses, the mirror method, and a find_by_authorisation_id reader
  the consume mode's issuance check requires — all inside Seat B's
  owned file and the ruled surface.
- Extra public surface in trust/client.py is exactly the two ruled
  methods.

## Verdict

FIX (score 0.87). Ship the code as-is once MEDIUM-1 (README) is done
and MEDIUM-2 is either completed or formally re-ruled; LOW-1/LOW-4
need only a recorded reconciliation note. No BLOCKER, no HIGH, no
boundary breach, no unruled production behaviour change found.
