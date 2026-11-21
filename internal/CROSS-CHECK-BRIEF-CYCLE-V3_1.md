# Cross-check brief — Trust Boundary v3.1 (delta round)

You reviewed Trust Boundary v3 (provenance chain, exactly-once
consumption, extraction accounting, production isolation,
serialisation strictness). Both seats returned FIX, converging on
ONE ship-blocker plus qualifications. This brief covers ONLY what
changed in response, the demonstrations, and the updated declared
limits. The full v3 brief and design are unchanged except where
this delta says so.

## The ship-blocker: fail-open deployment mode — FIXED

v3 read the deployment mode from AION_DEPLOYMENT_MODE, and a
missing/blank value silently selected the permissive research
mode. Now:

- The mode is REQUIRED. A verifier started with the mode missing,
  empty, whitespace-only, unknown, or non-canonical refuses
  startup (deployment_mode_refused, exit 3) before loading the
  key or touching any ledger, anchor, or budget state. Research
  mode is reachable only by naming it exactly; there is no
  default anywhere in the configuration type.
- The production launcher refuses earlier still: the wrapper
  script validates the env file before dropping privileges and
  exits without starting the verifier when the mode is absent,
  empty, invalid, or duplicated in the env file.
- Production requirements are properties of the mode, not of a
  string comparison at one call site: production refuses to start
  without both anchors configured and verified, and refuses
  outright if either anchor-bootstrap (INIT) flag is present —
  anchor ceremonies run outside production by design.
- The EFFECTIVE mode is verified from inside the running
  process, not inferred from configuration: every post-config
  response carries the mode the process actually loaded, the
  client library can pin an expected mode and refuses ok
  responses that omit the field or report a different one, and
  the deployment health check (below) probes the live deployment
  through its real launcher and checks the reported mode.
  Declared limit, stated in the client documentation: the
  reported mode is verifier-REPORTED, not cryptographic
  evidence — the pin detects stale/downgraded verifiers and
  configuration drift; a compromised verifier can lie about its
  mode (and root compromise remains verifier compromise, below).

Live demonstrations against the real provisioned deployment
(production mode, dedicated OS user): blanking the mode in a
copy of the live env makes the real launcher refuse, with the
signing ledger byte-identical before/after; a probe through the
real launcher returns the effective mode "production" reported
from inside the verifier process.

## Deterministic refusal precedence — FIXED, and hardened further

The disclosed race (a concurrent-issuance loser sometimes refused
registry_untrusted instead of eval_evidence_consumed) is fixed:
registry reads that record access-log entries retry on fresh
registry instances, so the loser reaches the consumption check
and is refused for the true reason. The previously failing test
now passes 20/20 consecutive runs; the full suite is green.

The fix review then applied the same standard to the sealed-
evaluation path, where three state saves (registry snapshot,
evaluation record, eval-attestation ledger append) could each
lose a concurrent-write race and refuse nondeterministically.
All three now retry on fresh instances under a bounded attempt
count; the query budget is recorded exactly once, before the
retries, so retries cannot double-charge; a failed append is
guaranteed by the journal's design to have written nothing
(freshness is re-checked under lock before any write), so
retries cannot double-append. The bounds are declared in code
as engineering margins, NOT proofs: each attempt fails only if
a competitor's save lands inside its load→save window, and
exhaustion still refuses (fail-closed), never succeeds wrongly.
Measured under barrier-synchronised contention (12 processes,
distinct transcripts, 20 sealed items): 144/144 evaluations
succeed with exact budget and ledger counts; before the fix the
same width produced ~25% nondeterministic refusals. A committed
regression test runs 10 barrier-synchronised processes and
asserts all-succeed plus exact budget/ledger accounting.
Independent multi-process race tests (4 OS processes per pair)
show exactly one issuance success with all losers refused
eval_evidence_consumed.

One declared limit from that review: a transcript whose answer
count mismatches spends registry access-log entries (truthful
attempt records) without a budget charge, because the snapshot
precedes the count check; the access log's cap fails closed.

## Strict-parser consumer inventory — DELIVERED, with two protected exceptions

An inventory (docs/PARSER-INVENTORY.md, 34 rows) enumerates
every JSON consumer of security-relevant artefacts across the
production packages and the deployment tooling, each classified
and dispositioned. Permissive loaders in the ledger, budgets,
anchoring, core-loop, verifier budgets-anchor, and health-check
code were brought under the strict contract (duplicate keys and
non-finite values refused). Differential tests cover the
security-relevant consumers.

Two consumers are exceptions we are declaring rather than
hiding: the sealed-registry loader and the calibration-log
loader accept duplicate keys with last-wins semantics. Both
modules are under this project's Protected Gate Rule — the
system may not modify its own evaluator/gate/calibration code
without the owner's separate approval and external review — so
they were NOT changed in this cycle. The recommended change
(duplicate-key rejection hooks identical to the ones applied
elsewhere) is recorded in the inventory and in the gate
proposal awaiting the owner's decision. The residual is a
parser differential, not an integrity break: both stores
recompute their digests/chains over the last-wins parse, so a
duplicate-key file cannot smuggle content past verification;
it can only be read differently by a stricter second reader.

## Deployment health check — DELIVERED

A reproducible checker (script + tests, 10 checks) verifies the
provisioned deployment's isolation, effective mode, anchoring,
and permissions WITHOUT consuming production budgets or
single-use transcripts: the registry is validated on a copy
(the live access log is untouched), the mode probe is a junk
envelope, and the probe is suppressed entirely when the env or
anchor checks fail — a review found that an unsuppressed probe
against a bootstrap-flagged env could CREATE the anchor it was
checking for; that is now impossible and test-pinned. It
detects, on copies of the deployment: permission changes,
wrapper changes, env changes (blanked mode, bootstrap flags,
path redirection), group-membership changes (including
supplementary groups), staged-code changes (including planted
interpreter hooks and bytecode), stale anchors, registry
corruption, and known-test-key substitution. One recorded
residual: substitution of the signing key by another
well-formed, non-test key is undetectable by any check the
deployment supports, because no key fingerprint is recorded in
the deployment's artefacts; downstream MAC verification is
where that surfaces. Against the real deployment at this
writing, the checker passes 10/10.

## Provenance dependency-mutation demonstration — DELIVERED

From a genuinely valid record and configuration (a control case
issues successfully), exactly one provenance dependency is
mutated per case: the trusted registry grows after the original
evaluation; a cross-registry swap with identical ids and one
differing answer; a different key file; a different signer id;
an empty ledger home; a swapped pair order. Every mutation
refuses issuance, each with its discriminating refusal detail
(manifest binding; unknown-key/signature-mismatch;
signer-mismatch), with zero consumption and zero new signatures
asserted per case. Fixture scope declared in the test: research
mode, unanchored — the provenance bindings exercised are
mode-independent.

## Claim wording — UPDATED everywhere it appears

- Crash-safety claims are scoped to PROCESS crashes. Power-loss
  durability is stated as conditional on the filesystem/storage
  honouring fsync semantics; it is not claimed independently.
- Extraction results are described as an accounting mechanism
  plus empirical measurements on a stated fixture (n=8, the
  4-token alphabet GIVEN to the attacker; coordinate descent
  2/8; group-testing pools alone 0/8, pools plus tolerated
  refinement probes 4/8 of 20 attempted / 19 evaluated under a
  60-query allowance). They are not a general confidentiality
  guarantee.
- The path-divergence claim is scoped to the tested corpus
  dimensions (canonical spellings, case variants, zero-width/
  BOM/homoglyph insertions, repeated slashes, backslashes, dot
  components, trailing slash/dot, leading ./, spaces, lexical
  .., absolute/drive prefixes, NUL, empty). Explicitly out of
  scope: symlink traversal, case-insensitive filesystem
  folding, unicode normalisation equivalence, hard links,
  alternate roots/mounts, and TOCTOU.
- The threat model states plainly: root compromise = verifier
  compromise. Root can read the env file, replace the staged
  code the launcher runs, interfere with startup, and inspect
  the execution context; the isolation protects against
  unprivileged and builder identities only.

## Explicit deferrals (recorded, not silent)

Three qualifications from your v3 round are NOT addressed in
this delta, by scope decision, and we are declaring them rather
than letting them drop: (1) an adaptive cross-proposal
extraction/reconstruction attack study — new work, queued for
the next trust cycle; (2) a gate negative-integration test —
the gate is a protected path, and the test belongs with the
owner's pending gate decision; (3) execution-environment
attestation — no mechanism exists in the current design beyond
the uid/staged-code isolation the health check verifies; it is
a known gap.

## Test totals

Full suite: 1075 tests, all passing (2 live-deployment tests
skip in their by-design state after their one post-reset run;
both were run and passed in this cycle after a documented
operator budget reset). The v3 suite was 964.
