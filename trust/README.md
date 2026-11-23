# trust/ — the trust boundary (prototype)

This package is the AION trust boundary built in cycles 7–8:
signed gate decisions and attestations (in `signing/`),
artifact-bound authorisation (`manifest.py`, `release.py`), an
out-of-process verifier (`verifier_main.py` + `client.py`),
single-use ship ledgers (`ledger.py`), and the signed ship path
(`shipcheck.py`).

**Prototype honesty statement.** This is process isolation on one
machine under one OS user. It raises the bar from in-process
discipline to a separate-process boundary: the gate arithmetic
and the sealed-manifest-hash derivation run verifier-side, and
builder code cannot construct a *valid* envelope without the
key. Two qualifications, stated plainly: the gate's score maps
remain caller-asserted inputs (the verifier signs decisions
over the evidence it is handed; verifier-produced evidence is
what `sealed_eval` mode is for), and nothing here stops code
that reads the key file directly. It is **not** a
separate-machine or separate-user trust domain: any code running
as the same OS user can read the 0600 key file and the registry
file directly. A real boundary requires a separate OS user (or
machine) for the verifier, as `signing/gate_decision.py`'s
docstring already states. Threat model, matching that docstring:
evolved or convenience code paths that hand-build an accepted
`GateDecision` or present unsigned/fake results — not a fully
malicious same-user process, which this prototype cannot and
does not claim to stop. Root compromise is verifier
compromise, stated plainly: root can alter the deployment
environment file, replace the staged code, interfere with
process startup, and inspect the verifier's execution
context; the isolation boundary in this package and in the
`aion-verifier` deployment protects against unprivileged
and builder identities only.

Sanctioned paths, and what "sanctioned" means:

* Memory commits: `signing.commit_signed` against a store built
  with `signed_only=True`. The store's plain `commit_write` then
  refuses; only envelope-verified commits land. As of Trust
  Boundary v2 the security mode is PERSISTED in the store's own
  metadata: opening a store whose file records `signed_only`
  with a plain constructor REFUSES (the only downgrade path is
  the audited `MemoryStore.migrate_security_mode`, which
  appends to a hash-chained migration journal before flipping).
  Honest limits: the persisted mode is protected by an unkeyed
  digest, so a same-user attacker who rewrites the whole file
  and recomputes the digest (including stripping the mode back
  to the legacy fieldless format) defeats it, and deleting the
  store file yields a fresh unsigned store — the mode is
  tamper-evident against casual or accidental downgrade, not a
  capability boundary against the file's owner.
* Ships: `trust.shipcheck.record_ship` — check (manifest rebuilt
  from the live tree, envelope re-verified, attestation
  verified, release record cross-checked, loop state verified
  against the release before anything is spent), burn the
  decision in the ship ledger, record the cycle, re-verify the
  tree, finalise. Replay and loop-state rollback cannot ship
  twice because the burn lives outside the loop's state — with
  one stated exception: rolling back or deleting the LEDGER
  itself defeats it (a missing journal is indistinguishable
  from first use), detectable only against an externally pinned
  ledger head (`check_ship(expected_ledger_head=...)`; build
  records should pin the head — the cycle-8 record does).
* Attestation issuance (Trust Boundary v2): claims and
  issuance are split. `submit_claim` ledgers a seat's assertion
  UNSIGNED — it grants nothing. `issue_attestation` DERIVES the
  attestation verifier-side from ledgered sealed-eval records
  (sealed scores from the records, the factory gap check run by
  the verifier itself, decision computed — caller-selected
  approval fields are a protocol error), and gate accepts
  additionally require `eval_evidence`: the gate replaces
  caller-asserted sealed score maps with the records' scores
  and binds both record hashes into the signed decision. The
  flow stays two-identity: the attesting identity differs from
  the gate signer, which refuses when the signer is the
  attester or sits among the reviewers. The verifier ledgers
  every signature it makes — gate decisions, attestation
  envelopes, and sealed-eval attestations — before returning
  it; the verifier refuses to run without its ledger home.
* Pin adoption (`trust/pin_adoption.py`): `PinAdopter` is the
  production adopter for snapshot-pin ceremonies — it captures
  the pin from `signing.pin_store.PinStore`, advances it on the
  dense path or runs the ceremony and adopts the returned pair
  through the store. Integrated into the loop via the
  constructor-injected cycle hook
  (`CoreLoop(state_dir, cycle_hook=pin_cycle_hook(adopter))`;
  `record_ship` and `run_one_cycle_and_pin` refuse a hooked
  loop), and `trust.shipcheck.anchored_record_ship` is the
  production recording path (caller-pin-free: the expected
  ledger head is derived from verified, current anchors).
  Scope, kept exact: this proves production MODE under
  same-user spawn on one machine (live run against a byte copy
  of the real state dir); it is not a production deployment.
* Query budgets (`trust/budgets.py`): sealed_eval queries are
  capped per proposal and per identity INSIDE the verifier,
  with near-duplicate/adaptive-query detection and replay
  refusal, enforced before the registry is opened.
* Ledger anchoring (`trust/anchoring.py`): both journals'
  heads can be anchored to a file outside the journal
  directory; the verifier refuses at startup when an
  established ledger's anchor is missing or disagrees, and
  `record_ship(anchor_path=...)` verifies before the burn and
  re-anchors after the finalise. Anchors are unkeyed: they
  detect rollback by disagreement, they grant no authority.
* Ship transactions (`trust/shiptx.py`): every record_ship
  drives a durable transaction journal (PREPARED ->
  AUTHORISATION_VERIFIED -> BURN_PENDING -> CYCLE_RECORDED ->
  POST_RECORD_VERIFIED -> COMMITTED, with REFUSED_PRE_BURN /
  ABORTED_SPENT terminals); `recover_ship_tx` settles crashed
  ships from ledger + loop evidence and never replays a
  consumed decision. Crash scope, stated precisely: the ship
  crash laboratory demonstrates recovery from **process**
  crashes (the kill -9 / `os._exit` class) only. Power-loss
  durability is **not** established by the crash lab: it is
  conditional on the filesystem and storage stack honouring
  fsync/replace semantics (write-cache behaviour, metadata
  durability), and it remains untested at the power-loss
  level.
* Path policy (`trust/pathpolicy.py`): the versioned path
  policy (path-policy/1) consumed by the manifest and the
  verifier, with drift-detector tests against the gate's and
  oversight's own lists. It is not universal: eval/gate.py
  does not consume it — the gate is a protected path, and
  gate adoption is pending the owner's approval of the
  Protected Gate Rule proposal
  (internal/PROTECTED-GATE-PROPOSAL.md). Divergence scope,
  stated precisely: the gate/policy/oversight agreement and
  divergence claims are measured on the 66-spelling corpus
  in `tests/test_trust_pathpolicy_differential.py`, and on
  nothing else. The corpus covers, as pure path **strings**:
  canonical spellings; case variants in the first and later
  components (as distinct paths on a case-sensitive
  filesystem); zero-width-space, BOM and Cyrillic-homoglyph
  spellings (byte-preserving distinct paths); repeated
  slashes, backslash separators, dot components in any
  position, trailing slash/dot, leading `./`, and
  leading/trailing spaces; lexical `..` components
  (`eval/../eval/...`, `a/../../...`, trailing `/..`);
  absolute and drive prefixes (`/eval/...`, `C:/...`); and
  the NUL byte, empty, `.` and `..` spellings. Explicitly
  **out of scope** — untested, and not claimed: symlink
  traversal (the corpus creates and resolves no symlinks);
  case folding on case-insensitive filesystems (the corpus's
  case rows assume case-sensitive semantics); unicode
  normalisation forms (NFC/NFD/NFKC equivalence spellings —
  the corpus's invisible/homoglyph rows are distinct
  codepoints, not normalisation equivalents); hard links
  (inode identity is never tested); alternate roots and
  mount changes (no chroot, bind mount or alternate root is
  exercised); and TOCTOU between the path check and its use.
* Enforcement of "sanctioned" is a call-graph lint in the test
  suite (`tests/test_trust_lint.py`): production code that calls
  `.commit_write(`, `._commit_gated(`, `.run_one_cycle(` or
  constructs `GateDecision(` outside the counted allowlist fails
  the build. That is enforcement by test — it does not stop
  runtime trickery (e.g. `getattr` indirection or bare method
  references, which the lint records as undetected), and no
  in-process mechanism can stop same-user code that bypasses the
  wrappers entirely. The honest claim is: **sanctioned paths are
  signed-only and test-enforced** — never "the system rejects
  unsigned decisions".

Known residual risks (owned by backlog items, see the cycle-8
build record): same-user HMAC boundary; the verifier as a
signing oracle for well-formed gate inputs (it signs rejections
too, and ledgers every signature — the residual is that the
gate's *evidence* is caller-asserted, so a fabricated
well-formed input earns a signed accept; closing that needs the
signer to recompute from raw inputs, a design change, not a
patch); registry disk-TOCTOU windows (for `sealed_eval`, between
the registry's final change check and signing; for `gate`, the
manifest is read from the in-memory registry instance with no
post-read disk recheck); the verifier has no internal timeout —
a stuck registry lock hangs it until the client's timeout kills
it; `sealed_eval` returns an exact score (a per-position oracle
for short answer spaces) and every registry read burns
access-log entries, so eval volume is an orchestrator-side rate
concern; state files are not yet manifest-bound; reviewer
independence is asserted by roster construction, not yet
measured; a `__pycache__` bytecode shadow anywhere under the
manifest's included roots refuses builds and ships outright
(release hygiene: build manifests over a pycache-clean tree).
