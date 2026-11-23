# Design B — Cycle 20: evidence provenance at issuance, operator
# authentication (honest scope), config/deploy surface

Seat: coder B (design only — no code in this round).
Slices: (1) verifier-side evidence resolution for
`ceremony_authorise`, (2) operator authentication / claim
narrowing, (3) config + deployment surface for any new env var.
Inputs read in full: `internal/CROSS-CHECK-13.md`,
`internal/BUILD-CYCLE-19.md`, `trust/verifier_main.py`
(`_load_config`, `_mode_ceremony_authorise`),
`trust/client.py` (`ceremony_authorise`, `_run`, `_check_pins`),
`trust/ledger.py` (`CeremonyAuthorisationLedger`,
`SigningLedger.append_ceremony_authorisation`),
`signing/ceremony_authorisation.py`, `signing/pin_ceremony.py`
(docstrings + binding checks), `trust/wiring.py`,
`deploy/verifier-identity/{run-verifier.sh,setup.sh,
health_check.py,README.md}`, and the tests that pin the
allowlist (grep evidence in §3.3).

External verdict being answered (CROSS-CHECK-13): Gemini FIX
0.88 item (1) — "the verifier signs whatever
evidence_hash/evidence_ref the caller passes ('theatre moved
into ceremony_authorise'); verifier must resolve the artifact
from a protected path or verify an independent producer's
signature" — and item (4) — "operator_id is an unauthenticated
assertion (allowlist membership only)". GPT FIX 0.91 converges
on scope-claim correction. This note fixes (1) for real, and
for (4) narrows the claim to the truth instead of pretending
to fix it (§2 — read the decision before the token appendix).

---

## 1. Evidence provenance at issuance

### 1.1 Principle

After this cycle, on the success path the `evidence_hash`
inside a ceremony authorisation envelope is a value the
**verifier computed itself**, over bytes **it read itself**,
from a location **only its own environment names**. The
caller's hash survives only as an assertion the verifier
checks its computed value against (§1.5). No code path may
sign a caller-supplied hash that the verifier did not derive:
that is the exact cycle-19 defect, and any fallback, override
flag, or "research-mode skip" reintroduces it. Research mode
differs only in *when an unconfigured verifier refuses*
(per-request, §1.2), never in *whether resolution happens*.

What this proves — and the claim wording in §1.9 says exactly
this and no more — is existence + content at issuance time:
the artifact was there, under the protected location, with
those bytes, when the verifier issued. It does **not** prove
the artifact is true, relevant, adequate, authored by the
operator, or older than the request. Semantic adequacy stays
a human/audit judgement, exactly as the sealed/public split is
stated in `verifier_main.py`'s module docstring today.

### 1.2 New configuration: `AION_CEREMONY_EVIDENCE_DIR`

One new variable, parsed **only** in `_load_config`, only from
the environment, mirroring the `AION_CEREMONY_OPERATORS`
philosophy line for line:

```
AION_CEREMONY_EVIDENCE_DIR   absolute path to the directory
                             holding ceremony evidence
                             artifacts, provisioned OUTSIDE the
                             verifier (operator act, §1.8) and
                             read — never written — by the
                             verifier at issuance. evidence_ref
                             in a ceremony_authorise request is
                             a path RELATIVE to this directory
                             (grammar in §1.3).
```

Rules, in `_load_config` order (after the
`AION_CEREMONY_OPERATORS` block, before TTL parsing — config
errors should surface in the docstring's variable order):

1. **Form (both modes, refuses STARTUP, exit 3
   `verifier_misconfigured`, detail names the variable, never
   its value):** a present value must be a non-empty absolute
   path (`Path(v).is_absolute()`), with no trailing slash
   except the root spelling, and no `.` / `..` segment. A
   relative, blank-padded, or dot-segment spelling is
   malformed configuration, not a runtime condition — the same
   no-strip/no-normalise stance `_load_config` takes for
   `AION_DEPLOYMENT_MODE` and the operator list. Do **not**
   resolve or stat the path at startup (see rule 3 for why).
2. **Production + absent/empty refuses STARTUP** (exit 3,
   `verifier_misconfigured`, "production mode requires
   AION_CEREMONY_EVIDENCE_DIR"), mirroring
   `AION_CEREMONY_OPERATORS` and the anchor rule.
   Justification for startup rather than per-request:
   (a) precedent — cycle 19 already accepted that a production
   verifier refuses to start *at all* (even for `gate` /
   `sealed_eval`, which never touch the operator list) when
   ceremony protective config is missing; consistency beats a
   second, subtler policy for a sibling variable, and the
   deployment-migration note in BUILD-CYCLE-19 (F6) is the
   established way to announce it;
   (b) the failure is a *deployment* fact, knowable before any
   request arrives — per-request refusal would let a
   misdeployed production verifier run indefinitely, serving
   other modes, with the ceremony silently dead until someone
   tries one;
   (c) health_check / production-deploy fixtures already treat
   "production env missing a ceremony variable" as a startup
   fact (§3.3), so this is the cheaper test surface too.
   Cost, stated: adding a ceremony to an existing production
   deployment is a restart-with-new-env act. That is already
   true for the operator list; it is the intended shape.
3. **Research + absent/empty loads as `None`** and the *mode*
   refuses per-request (new exit-3 code
   `ceremony_evidence_unconfigured`, §1.7), mirroring research
   + no operators. Research keeps its "run the rest of the
   verifier with the ceremony disabled" property.
4. **Existence/type are NOT startup checks.** `_load_config`
   validates the *spelling*; the directory's existence,
   directory-ness, and readability are checked per-request at
   resolution time (§1.4). Reasons: the directory is operator-
   provisioned filesystem state that can legitimately be
   mounted/populated after process start in research fixtures;
   a startup stat would be a TOCTOU promise anyway (the check
   that matters is the one on the opened fd, §1.4); and every
   other runtime resource in this module (registry emptiness,
   ledger readability) is likewise a per-mode refusal, not a
   startup one. The line drawn is: *presence in config* is a
   startup fact in production; *filesystem reality* is a
   request-time fact in both modes.

`_Config` gains `ceremony_evidence_dir: Path | None` (the
unresolved spelling as configured; resolution happens
per-request, §1.4). The module docstring's config list gains
the entry above, in the same voice as the
`AION_CEREMONY_OPERATORS` entry, including the production /
research split and the malformed-refuses-startup sentence.

### 1.3 `evidence_ref` grammar — from opaque locator to relative name

Cycle 19: `evidence_ref` is `_check_text(..., 2000)`, "an
opaque, caller-supplied locator string (form-checked only)".
Cycle 20: it is a **relative path under
`AION_CEREMONY_EVIDENCE_DIR`**, and only that. The envelope
continues to bind the ref *as presented* (the canonical
relative spelling) — never the absolute filesystem path, which
would leak deployment layout into every envelope, ledger
audit, and ceremony record, and would make envelopes
non-portable across deployments naming the same artifact.

Grammar (validated in the mode's cheap-validation step, §1.6
step 2 — pure string work, no filesystem touched):

- Must first pass the existing `_check_text(evidence_ref,
  2000)` (non-empty, no control/invisible characters) —
  unchanged.
- Length ≤ 512 characters (new, tighter than the 2000 text
  cap: this is now a path, and the payload projection in
  `signing/ceremony_authorisation.py` keeps the 2000 cap as
  its defence-in-depth copy — the mode is the stricter layer,
  as it already is for `ceremony_id` via `_ID_RE`).
- No leading `/`, no trailing `/`, no `\` anywhere (backslash
  is a separator on no supported platform here and a smuggled
  one on others — refuse, don't interpret), no NUL (already
  excluded by `_check_text`).
- Split on `/`: 1–8 segments; no empty segment (`//`, leading
  or trailing slash all land here or above); no segment equal
  to `.` or `..`; each segment matches
  `^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)*$` — i.e. the
  id grammar plus optional dot-suffixes for file extensions
  (`case-file-1`, `bundle/report-2.json` pass; `Report.PDF`,
  `my evidence.pdf`, `.hidden`, `a..b` do not). Canonical
  lowercase only, mirroring the changed_paths canonical-
  spelling discipline in `_mode_gate`: the verifier accepts
  one spelling per artifact, so two spellings of one file
  cannot mint two "different" refs for one artifact.
- Any violation: **exit 2, `malformed_request`** (existing
  code; detail says the ref must be a relative path under the
  configured evidence directory — never echoing the configured
  directory's value).

Compatibility note: the cycle-19 test fixture's ref
`"case-file-1"` already satisfies this grammar. Refs in the
wild of the prototype are operator-chosen names, not URLs;
anything that was using `evidence_ref` as a free-text locator
(e.g. a ticket URL) loses that use — deliberately: a locator
the verifier cannot resolve is exactly the theatre being
removed. Free-text provenance notes belong in the artifact's
*contents*.

### 1.4 Resolution, containment, and reading

A new helper in `trust/verifier_main.py`,
`_resolve_ceremony_evidence(config, evidence_ref) ->
(bytes, sha256_hex)`, called exactly once per request at the
order position fixed in §1.6. Steps:

1. `root = Path(config.ceremony_evidence_dir).resolve()`.
   If the root does not exist or is not a directory → exit 3
   `ceremony_evidence_unresolvable` (§1.7).
2. **Containment by construction, then by check.** Walk the
   ref segment by segment from an fd opened on `root`,
   using `os.open(segment, O_RDONLY | O_NOFOLLOW,
   dir_fd=current_fd)` per component (POSIX; this codebase
   already depends on `fcntl`/flock and `os.open` with
   `O_DIRECTORY` in `trust/ledger.py`, so dir_fd traversal is
   in-idiom, stdlib-only). `O_NOFOLLOW` on **every** component
   — intermediate directories and the final file alike — means
   **any symlink anywhere on the path refuses** (exit 3,
   `ceremony_evidence_unresolvable`). This is stricter than
   the brief's minimum (resolve + containment-check) and is
   the honest way to meet it: a resolve-then-open sequence has
   a check/use window in which a swapped symlink redirects the
   open outside the root, and this design does not paper over
   that window by resolving harder — it removes symlinks from
   the path entirely and opens through held fds, so the object
   hashed is the object that was containment-checked, per
   component. Deployment consequence, stated in the setup
   template comment (§3.2): evidence artifacts are provisioned
   as **real files in real subdirectories**, never symlinks —
   a provisioning step that copies (`cp`, not `ln -s`) is the
   operator act.
   Residual race honesty: an attacker who can *write the
   evidence directory itself* can swap one regular file for
   another between requests — but that changes the bytes, hence
   the hash, hence fails the §1.5 cross-check or mints an
   authorisation for the artifact actually present; it cannot
   make the verifier hash bytes outside the directory or bytes
   it did not read. An attacker with write access to the
   directory *as the verifier uid* is inside the prototype's
   already-stated same-user honesty limit. A swap *during* the
   read of one file is handled by step 3's size re-check.
3. **Final component:** `os.fstat(fd)` must report a regular
   file (`stat.S_ISREG`); directories, fifos, devices refuse
   (exit 3, unresolvable). Size from fstat must be
   **1 byte … 1 MiB** (§1.5 cap); read the fd in chunks,
   updating a `hashlib.sha256` and a byte counter; refuse if
   the counter exceeds the cap mid-read or differs from the
   fstat size at EOF (file changed under the read — refuse,
   never hash a torn read). Close every fd on every path.
4. Return `(content_bytes, hexdigest)`. Bytes are retained in
   memory for §1.8 (cap makes this ≤ 1 MiB); nothing has been
   written anywhere yet.

Failure detail strings name no absolute path, no segment
beyond what the caller itself supplied, and no errno text that
could map the deployment's filesystem for a caller — the
detail is fixed text, as the config errors already are.

### 1.5 Size cap, hash cross-check, and the 7-key body — decisions

**Size cap: 1 MiB (`1 << 20`)**, proposing the constant live
next to the mode (`_CEREMONY_EVIDENCE_MAX_BYTES`), not in
`signing/`. Grounding: it equals `trust/protocol.py`'s
`MAX_REQUEST_BYTES` — the system's existing "one bounded unit
of work per verifier request" size — and an evidence artifact
for a pin ceremony is a report/bundle (text, hashes, logs),
not a snapshot (snapshots are bound by their own payload
hashes and are explicitly *not* evidence — non-equality,
§1.6). Refusal semantics: oversize is a property of the
*artifact*, discovered from filesystem state, so it is
**exit 3, new code `ceremony_evidence_too_large`, unsigned,
unledgered** — not malformed: the request was well-spelled;
the world refused. Empty (0-byte) artifacts refuse under
`ceremony_evidence_unresolvable` instead: an empty file's hash
is a public constant, and issuing over it would be theatre
with extra steps. Both refusals happen before any ledger
write.

**The request keeps `evidence_hash` — body stays 7 keys.**
`_CEREMONY_BODY_KEYS` is unchanged; `VerifierClient.
ceremony_authorise` keeps its signature and its echo binding
verbatim; the envelope schema, payload projection, ledger
shapes, and `pin_ceremony`'s binding checks are untouched by
this slice. Argument:

- *For keeping (decisive):* the supplied hash is the caller's
  **statement of intent** — "the artifact I mean is the one
  whose hash is X". The verifier resolves the ref, computes
  its own hash, and **compares: mismatch ⇒ exit 2,
  `ceremony_evidence_hash_mismatch` (new code, malformed
  class), unsigned, unledgered, before the anti-replay scan
  and before signing** (order in §1.6). On success the two
  values are equal by construction, and the envelope binds the
  **computed** one — code must pass the computed variable to
  `sign_ceremony_authorisation`, never the body value, so a
  future refactor cannot silently revert to signing the
  assertion. The cross-check catches the realistic accidents
  (stale artifact provisioned under a reused ref, wrong bundle
  version, caller hashed a different file) at issuance, where
  cycle 19 would have minted over them.
- *For dropping (considered, rejected):* a 6-key body is
  purist — the caller asserts nothing — but it breaks the
  strict body, the client signature, every caller, and the
  E2E fixture for zero security gain: a caller-supplied value
  that is *only ever compared, never signed* is not an
  assertion channel. It also removes the caller's ability to
  detect "the deployment provisioned a different artifact than
  I reviewed" before an envelope exists.
- The anti-replay scan (§1.6 step 5) keys on the **computed**
  hash. Since success requires supplied == computed, scan
  behaviour for issued envelopes is identical to cycle 19; the
  change matters only in that a reused *artifact* is now
  detected as reuse of bytes the verifier actually saw, and
  `ceremony_evidence_reused` can no longer be triggered by a
  hash nothing ever had.

**Content type: opaque bytes.** No extension allowlist, no
MIME sniffing, no decoding, no JSON parsing, no following of
references inside the artifact, no execution — the verifier
proves existence + content hash at issuance, full stop
(claim wording §1.9). Parsing evidence would import a parser
attack surface into the signing process to buy a semantic
judgement the verifier has no basis to make.

### 1.6 Validation order in `_mode_ceremony_authorise` (revised)

Existing order is config gate → cheap validation → membership
→ anti-replay scan → sign → ledger-before-return. New order,
with each insertion's reason:

1. **Config gates (exit 3, unsigned, unledgered, before body
   validation — as today):** operators unconfigured
   (`ceremony_operators_unconfigured`), then evidence
   unconfigured (`ceremony_evidence_unconfigured`, research +
   no dir only; production cannot reach here — startup
   refused). A disabled mode refuses wholesale, whatever the
   body says — unchanged philosophy.
2. **Strict 7-key set + cheap field validation (exit 2, no
   ledger, no filesystem):** everything cycle 19 validates,
   plus the §1.3 ref grammar. The supplied-hash non-equality
   pre-check against old/candidate pin hashes stays here (it
   is pure request arithmetic).
3. **Operator membership (exit 3,
   `ceremony_operator_not_authorised`, unsigned, unledgered —
   unchanged).** This step MUST stay before evidence
   resolution. An unlisted operator id must not be able to
   make the verifier touch the filesystem: no existence oracle
   (distinguishing "ref missing" from "hash mismatch" from
   "issued" leaks the evidence store's contents one bit per
   request), no read-amplification (repeated 1 MiB reads at an
   unauthorised caller's request), no timing side channel over
   which artifacts exist. Membership is a pure config
   comparison; resolution is the first step with side effects
   (file opens), and in this mode side effects are earned by
   passing membership first. This is the same reason
   issue_attestation validates before consuming: deterministic
   checks before anything is spent — here, before anything is
   *read*.
4. **Evidence resolution (NEW; §1.4; read-only):**
   unresolvable / symlink / non-regular / empty → exit 3
   `ceremony_evidence_unresolvable`; oversize → exit 3
   `ceremony_evidence_too_large`; computed != supplied →
   exit 2 `ceremony_evidence_hash_mismatch`. All unsigned,
   unledgered, before the scan: a request that fails here
   burns nothing (a corrected retry with the same
   ceremony_id and the fixed artifact must still work — the
   exact analogue of cycle 19's "a bad spelling can never burn
   a single-use pair"). Then re-run the evidence non-equality
   check against the **computed** hash (equal to supplied on
   this path, but the check names the value that will be
   signed).
5. **Anti-replay scan (unchanged codes):** ceremony journal
   scan for `ceremony_id_reused`, then evidence reuse keyed on
   the **computed** hash (`ceremony_evidence_reused`). After
   resolution, because the scan's evidence key is now the
   computed value; the scan remains before signing, and a
   journal that cannot be read still refuses `ledger_failed`.
6. **Sign (unchanged):** `sign_ceremony_authorisation(...,
   evidence_hash=<computed>, evidence_ref=<as presented>)`,
   TTL `min(config, 900)` as today.
7. **Commit (extended, §1.8):** ceremony-journal append
   (commit point, unchanged) → retained-evidence write (NEW)
   → signing-ledger append → anchor update. Any failure after
   the journal append is `ledger_failed` with the pair burned
   and the envelope withheld — the cycle-19 recovery story
   (new ceremony_id + new evidence bundle) applies verbatim,
   and the mode docstring gains one sentence naming the
   retained-write failure as one of the post-commit failures
   it already describes in general terms.

Docstring updates in the mode: delete "It never inspects the
evidence artefact (see the module docstring's honest
limits)"; replace with the §1.9 wording and the order note
"evidence is resolved after membership, before the scan:
an unlisted operator cannot make this process open a file".

### 1.7 Refusal catalogue for this slice

| Condition | Exit | Code | Ledgered? |
|---|---|---|---|
| Evidence dir absent, research (mode reached) | 3 | `ceremony_evidence_unconfigured` (NEW) | no |
| Evidence dir absent/malformed, production; malformed, research | startup 3 | `verifier_misconfigured` | n/a |
| `evidence_ref` grammar (absolute, `..`, `.`, empty segment, `\`, >512, bad segment chars) | 2 | `malformed_request` (existing) | no |
| Root missing / not a dir; any component missing, symlink, non-regular; empty file; size changed mid-read; unreadable | 3 | `ceremony_evidence_unresolvable` (NEW) | no |
| Artifact > 1 MiB | 3 | `ceremony_evidence_too_large` (NEW) | no |
| Computed hash != supplied `evidence_hash` | 2 | `ceremony_evidence_hash_mismatch` (NEW) | no |
| Retained-copy write fails after journal commit | 3 | `ledger_failed` (existing) | journal only; pair burned |

One unresolvable code for all existence/type/symlink failures
is deliberate: distinct codes would hand a listed operator an
enumeration oracle over the directory's structure; the
operator who provisioned the artifact already knows which
case they are in. Oversize gets its own code because the
remedy differs (provision a smaller bundle) and its size is
the caller's own artifact's property, not store structure.

Client surfacing is automatic via `_run` (exit 2 →
`VerifierProtocolError`, exit 3 → `VerifierConfigError`), but
`client.ceremony_authorise`'s docstring must list the three
new codes alongside the existing exit-3 set it already names.

### 1.8 Retention: yes — a copy enters the verifier home at issuance

**Decision: retain.** After the ceremony-journal append (the
commit point) and before the signing-ledger append, the
verifier writes the exact bytes it hashed to

```
<AION_VERIFIER_HOME>/ceremony-evidence/<authorisation_id>
```

(no extension; `authorisation_id` is a hex64 — a safe,
single-segment filename by construction), opened
`O_WRONLY | O_CREAT | O_EXCL`, mode 0600, fsynced, then the
directory fsynced (the ledger `_save` pattern). `O_EXCL`
failure is a post-commit `ledger_failed`. The subdirectory is
created lazily by the verifier (`mkdir(parents=True,
exist_ok=True)` — the `HashChainJournal.__init__` pattern for
the home itself), so `setup.sh` needs no new directory for
retention (contrast the *source* directory, §3.2).

Argument for retaining, against hash-in-place only:

- *Auditability is the point of the hash.* Without a retained
  copy, a later auditor can verify that an envelope binds
  *some* hash, but can never re-derive it: the source artifact
  lives in an operator-provisioned directory that may be
  re-provisioned, cleaned, or lost — and then the cycle-19
  detectability problem returns in a new form ("trust that the
  hash was of the right thing"). With the copy, audit is
  mechanical: re-hash `<authorisation_id>`, compare to the
  envelope and to both ledgers.
- *It repairs a named cycle-19 weakness prospectively:* the
  anchored signing ledger stores neither `evidence_hash` nor
  the artifact, so evidence reuse under a new ceremony_id was
  "not detectable from the anchored store without the retained
  envelopes". Retained copies + retained envelopes make reuse
  detectable by content comparison on audit. (Not *prevented*
  after a journal rollback — the copy is not anchored; see
  risks. Wording must not upgrade this to rollback
  resistance.)
- *Cost is bounded and local:* ≤ 1 MiB per issued
  authorisation, inside the already-0700 verifier home, files
  0600 under the wrapper's `umask 077`. Evidence can be
  sensitive; the verifier home is precisely the deployment's
  existing answer to "where do sensitive verifier artefacts
  live".
- *Why not copy into the evidence directory:* the source
  directory is verifier-read-only by design (§3.2); giving the
  signing process a write path into its own evidence source
  would let a compromised verifier rewrite the evidence it
  later hashes. Source (operator-written, verifier-read) and
  retention (verifier-written, auditor-read) stay separate.

Non-goals / honesty: no retention index, no deletion or GC in
this cycle (growth is one bounded file per *issued*
authorisation, and issued authorisations are already journal-
capped in practice); no external anchor over
`ceremony-evidence/` — it joins `ceremony-journal-anchoring`
as a named follow-up input, it does not silently acquire
anchored status. If the retained write fails, §1.6 step 7
applies; a retained file orphaned by a *later* signing-ledger
failure is a truthful artefact of a burned pair and is kept,
not cleaned (deleting audit artefacts on failure is how
traces disappear).

### 1.9 Exact claim wording (evidence)

Replace the honest-limits passage in `trust/verifier_main.py`'s
module docstring (currently "the verifier never inspects the
evidence artefact an evidence_hash names — a random hex64
from a LISTED operator is still issuable; what the envelope
proves is that a listed operator presented this evidence hash
…") and the mirrored bullet in
`signing/ceremony_authorisation.py` with, in substance verbatim:

> The verifier resolves the evidence itself: `evidence_ref`
> is a relative path under the directory named only by its
> own `AION_CEREMONY_EVIDENCE_DIR` configuration; the
> verifier opens the artifact (refusing absolute refs, `..`
> escapes and any symlink on the path), reads at most 1 MiB
> of opaque bytes, computes the SHA-256 itself, refuses if
> it differs from the hash the caller supplied, and retains
> a copy of the bytes it hashed under its verifier home,
> named by the authorisation id. What the envelope proves:
> at issuance, an artifact with exactly the bound
> `evidence_hash` existed at the bound `evidence_ref` in
> that protected location and was read by the verifier; the
> presentation was ledgered single-use at issuance; and the
> binding is signed by the verifier's key. It does NOT prove
> the artifact's contents are true, relevant or adequate as
> evidence for this recovery, who authored it, or when it
> was created — a listed operator (§2 wording) can still
> obtain an authorisation over a *real but worthless*
> artifact. A random hex64 with no artifact behind it is no
> longer issuable.

And in `signing/pin_ceremony.py`'s evidence-provenance bullet,
the sentences "The verifier never inspects the evidence
artefact the hash names; a random hex64 presented by a LISTED
operator is still issuable" are replaced by a pointer: the
ceremony still does not inspect the artifact in-process (true
— consumption is unchanged), but issuance now does, per the
wording above; the in-process non-equality check stays as
defence in depth. Seat C owns that edit (§4); it is flagged
here because the claim is one claim across both files.

Envelope-format note: **no version bump, no payload change.**
The payload fields, domain (`signed-ceremony-authorisation-v1`)
and projection are identical; what changed is how one field's
value is *derived*. Consequence seat C must confront (§4):
a consumer cannot distinguish a cycle-19 envelope (hash
caller-asserted) from a cycle-20 envelope (hash verifier-
computed) by inspection. The strengthened claim therefore
applies only to authorisations *issued by a verifier running
this cycle's code* — an issuance-time, deployment fact, not an
envelope property. This design accepts that (the alternative —
a v2 domain — would invalidate every cycle-19 test envelope
and the ledger's payload_hash continuity to buy a distinction
no consumer currently branches on), and the claim wording
above is written in issuance terms ("at issuance, the
verifier …") for exactly that reason.

---

## 2. Operator authentication — decision: narrow the claim, do not build a token

### 2.1 Inventory: what authentication machinery actually exists

Read, not assumed:

- **Transport (`VerifierClient._run`):** one subprocess per
  call, `[sys.executable, "-m", module]`, env = `PATH`/`HOME`
  passthrough + the caller-supplied `verifier_env` dict. No
  credential is presented, no peer is authenticated in either
  direction at this layer; trust "comes from orchestrator
  launch control, not from the response bytes" (client module
  docstring — already honest).
- **Pins (`_check_pins`, `expected_signer_id` /
  `expected_key_id`):** authenticate the **verifier to the
  caller** — the response is from the pinned signer identity.
  Wrong direction for operator auth; they say nothing about
  who asked.
- **Keys:** the verifier's signing key authenticates
  *issuance* (whoever holds it minted this — seat A's slice).
  The snapshot/ceremony keys authenticate ceremony artefacts.
  No per-operator key or secret exists anywhere in the repo:
  grep finds no operator credential, token, or password
  concept outside the allowlist itself.
- **`AION_VERIFIER_ACTOR_ID`:** the verifier's *own* registry
  actor for sealed-access logging. It identifies the verifier
  process to the registry; it is not an operator identity and
  is identical for every ceremony.
- **Protocol (`trust/protocol.py`):** strict key sets and a
  random `request_id` (a correlation id, not a secret — it is
  echoed in the response document).
- **Deployment (`run-verifier.sh` / `setup.sh`):** the one
  real boundary. The wrapper runs as **root**, parses a
  root-owned 0600 env file against the allowlist, scrubs the
  environment (`env -i`), and `runuser`s to the dedicated
  `aion-verifier` OS user (nologin, sole member of its group).
  Whoever can invoke the wrapper as root, or write that env
  file, *is* the operator in effect. But note
  `trust/wiring.py`'s declared limit: production client
  construction does **not** route through the wrapper (wrapper
  routing is refused, backlog `verifier-wrapper-routing`) — the
  in-repo client spawns the verifier **same-user, directly**.
  So even the deployment boundary authenticates a *launch
  channel*, per-launch, not a *person per request*; and the
  in-repo path does not pass through it at all.

Conclusion of the inventory: **there is no secret, key,
credential, or OS identity bound to an individual operator
anywhere in this system, and nothing the caller presents in a
`ceremony_authorise` request that another caller able to spawn
the verifier could not present identically.** `operator_id`
selects a row of the allowlist; it does not authenticate the
presenter as that operator. Any code running as the launching
user can assert any listed id and be issued. This is not a
bug in the membership check — the check does what it does —
it is a missing layer the prototype does not have the
infrastructure for (see §2.3).

### 2.2 Decision

**Cycle 20 does not add operator authentication. It renames
the claim to the truth, everywhere, and records the missing
layer as a named follow-up (`operator-authentication-channel`)
that blocks any future wording upgrade.** Rationale:

1. The honest binding requires a channel this prototype
   lacks: a per-operator secret or key that (a) the *human*
   operator holds, (b) the builder-side process does **not**
   hold at rest, and (c) reaches the verifier without becoming
   builder-readable in transit. Candidates all need
   infrastructure that does not exist here: separate OS users
   per operator with the wrapper checking `$SUDO_UID`/peer
   credentials (deployment has exactly one operator-side
   identity: root); an interactive prompt at ceremony time
   (the client is a library called by orchestrator code; there
   is no human in its loop); a hardware key / external IdP
   (out of scope, out of stdlib-only prototype reach).
2. A bearer-token scheme *is* buildable (§2.4 specifies it, in
   case the coordinator overrules) — but what it proves is
   "the presenting **process** possessed operator X's token",
   and in every deployment this repo actually has, the token
   would be stored where the builder-side process can read it
   (env dict, file, orchestrator config), i.e. possessed by
   exactly the code whose assertion is currently
   unauthenticated. It raises the bar against accidents and
   against code paths that were never given the token — a real
   but *process-capability* property — while inviting the
   wording "operator authentication", which would be a new
   overclaim of exactly the kind rev-r6 caught four times in
   cycle 19. Spending a cycle to move an overclaim is worse
   than naming the gap.
3. Gemini's item (4) is answered honestly by the narrowing:
   the external brief for cycle 20 must list operator
   authentication as a **named residual, not a fixed item** —
   mirroring how cycle 19 carried F1 (consumption replay) as a
   preserved dissent rather than a silent gap. If the external
   seats rule that a narrowed claim is insufficient for cycles
   14–16 to ship, that is their call to make against a true
   statement, not against theatre.

### 2.3 Exact claim-wording changes (operator axis)

Terminology, applied mechanically: **"operator authority" →
"operator-id allowlist eligibility"**; **"authorised operator"
→ "allowlisted operator id"**; **"an operator act / a listed
operator presented" → "a caller presented an operator id that
was on the verifier's configured allowlist at issuance"**.
Names that are wire/config identifiers do **not** change:
`operator_id` (field), `AION_CEREMONY_OPERATORS` (env var),
`ceremony_operator_not_authorised` (refusal code), mode and
function names — renaming identifiers would break the body,
the client, and deployment files to buy prose. The canonical
honest sentence, to appear once in each of the first three
files below (adapted in voice, not weakened):

> Operator identity is allowlist membership via the launch
> channel, not authentication: the verifier checks that the
> presented `operator_id` is on its configured list; it does
> not and cannot verify that the presenter *is* that
> operator — no per-operator credential exists in this
> system, and any caller able to launch the verifier can
> present any listed id. The envelope proves a presentation
> under an allowlisted id, ledgered and event-bound; it does
> not prove which human or process made it.

Passages to change (grep-verified locations at design time):

1. `trust/verifier_main.py` module docstring —
   (a) the `AION_CEREMONY_OPERATORS` config entry ("authorised
   to obtain ceremony authorisations" → "allowlisted to be
   named as the operator id in ceremony authorisations");
   (b) the ceremony paragraph ("the operator authority comes
   from this process's protected AION_CEREMONY_OPERATORS
   list" → allowlist-eligibility wording; its existing
   sentence "Operator identity is list membership via the
   launch channel, not authentication of a human" is already
   true — keep it and extend it with "or of a process" per the
   canonical sentence).
2. `trust/verifier_main.py` `_load_config` comment ("Ceremony
   operator authority (cycle 19)" → "Ceremony operator
   allowlist (cycle 19)") and `_mode_ceremony_authorise`
   docstring + step-(3) comment + the strict-key error detail
   ("operator authority comes from the verifier's
   configuration" → "operator eligibility comes from …" — the
   detail is user-visible protocol text; it changes, and the
   mode test that pins it, if any, changes with it).
3. `signing/ceremony_authorisation.py` module docstring —
   paragraph 1 ("operator authority is list membership decided
   at issuance time" — keep the fact, drop "authority"), the
   honest-limits bullet "Operator identity is list membership
   via the launch channel, not authentication of a human"
   (extend per canonical sentence), and
   `verify_ceremony_authorisation`'s closing note ("it does
   NOT prove the operator should have been authorised" →
   "…does NOT prove the presenter was the named operator, nor
   that the named operator should have been allowlisted").
4. `signing/pin_ceremony.py` module docstring — the
   `reanchor_pin` bullet ("operator authority comes from the
   verifier's own protected operator list"), the Honest-limits
   authorisation bullet (already carries the true sentence
   "Operator identity is list membership via the verifier's
   launch channel, not authentication of a human" — extend,
   don't rewrite), and the cycle-16 passage item (1). Seat C
   owns this file; the wording list is handed over in §4.
5. `trust/client.py` `ceremony_authorise` docstring ("the
   AUTHORITY is the verifier's own protected operator list" →
   "ELIGIBILITY is the verifier's own protected operator
   allowlist … this client asserts the operator id; it does
   not authenticate it").
6. `deploy/verifier-identity/setup.sh` template comment
   ("Ceremony operator authority (cycle 19)" → "Ceremony
   operator allowlist (cycle 19)") — comment only; the
   variable line is unchanged.
7. `internal/BUILD-CYCLE-20.md` (coordinator's record, flagged
   not edited here): Part B's heading and F4's "operator
   authority" phrasing must not be carried forward; the cycle-20
   record should state the residual by its follow-up name.

A grep gate for the build round: after edits,
`grep -rn "operator authority" trust/ signing/` returns zero
hits outside `internal/` working papers (the cycle-19
detectability precedent: the claim phrase itself is the test).

### 2.4 Appendix — token scheme, IF the coordinator overrules §2.2

Specified so an overrule is implementable without redesign;
**not recommended**, and its claim ceiling is stated in its
own wording below.

- **Config:** one new variable
  `AION_CEREMONY_OPERATOR_TOKENS`, grammar
  `id:hex64,id:hex64,…` where each `hex64` is the **SHA-256 of
  the operator's bearer token** (the verifier stores digests,
  never tokens — a read of the env file then yields verifiers,
  not credentials; comparison is `hmac.compare_digest` over
  digests). Parsing in `_load_config` only: no whitespace, no
  empty segment, no duplicate id, ≤ 64 entries, every id in
  the `_ID_RE` grammar **and present in
  `AION_CEREMONY_OPERATORS`** (a token for an unlisted id is
  malformed config, startup refusal both modes — the two lists
  must not disagree silently). Production: if *any* operator
  is listed, tokens for *all* listed operators are required at
  startup (partial coverage is a downgrade path: the untokened
  id becomes the soft target). Research: absent loads empty;
  if non-empty, the same all-listed rule applies per-request.
  This is a 17th allowlist name — §3's entire cascade runs
  again (15 → 17 across two cycles, never 16 in a tree that
  also has tokens; the build must land §3 and this appendix
  atomically or not at all).
- **Request:** body grows to **8 keys**: `operator_token`
  (opaque text, `_check_text` cap 512; the raw token, hashed
  verifier-side). Client gains a keyword-only
  `operator_token=None` parameter and echo-binds nothing about
  it (it is not in the envelope — a credential must never be
  signed into an artefact that circulates).
- **Check position and refusal:** immediately **with**
  membership (step 3), as one combined gate: unknown id, or
  listed id with missing/wrong token, both refuse with the
  **existing** code `ceremony_operator_not_authorised`, exit 3,
  unsigned, unledgered — one code for both, so the response is
  not an oracle for which ids exist or which ids have tokens.
  Still before evidence resolution (§1.6's side-effect rule
  applies a fortiori: a token-less caller must not make the
  verifier read files).
- **Honest limit, to be written wherever the scheme is
  described:** "A token proves the presenting process
  possessed the token at request time. In this deployment the
  token is necessarily held by the launching process's
  environment or files, so it authenticates a *process
  capability*, not a human operator; a token is replayable by
  any code that can read it, is not bound to the request body
  beyond this one presentation, and its compromise is silent.
  It is not operator authentication." If that paragraph is
  unacceptable in the docs, the scheme is unacceptable —
  they ship together or not at all.

---

## 3. Config / deploy surface

### 3.1 The one new variable and the four allowlist copies

Cycle 20 adds exactly **one** env name (§2.4's token variable
is appendix-only and excluded from this count):
`AION_CEREMONY_EVIDENCE_DIR`. Allowlist count **15 → 16** in
all four live copies, in the same relative position (after
`AION_CEREMONY_OPERATORS`, the ceremony block staying together):

1. `deploy/verifier-identity/run-verifier.sh` — `ALLOWED_KEYS`
   array gains `AION_CEREMONY_EVIDENCE_DIR`. (The wrapper
   forwards it automatically via its `for key in
   "${ALLOWED_KEYS[@]}"` loop; no other wrapper change. Note
   the wrapper does not validate the *value* — form is
   `_load_config`'s job, as for every other path variable.)
2. `trust/wiring.py` — `ALLOWED_ENV_KEYS` gains the name; the
   two docstring/comment mentions of "15 names" (module
   docstring "ALLOWED_KEYS, 15 names — the shipped wrapper
   governs" and the frozenset comment "as shipped (15 names)")
   become 16. **Not** added to `REQUIRED_ENV_KEYS`:
   `AION_CEREMONY_OPERATORS` is likewise allowlisted-but-not-
   wiring-required (production *startup* refusal is the
   verifier's own rule, and wiring's required set is the
   client-construction minimum) — mirror that exactly, or the
   two ceremony variables acquire different policies for no
   reason. Consequence to state in wiring's docstring edit:
   a production client can be *constructed* with an env
   lacking the evidence dir; the verifier it spawns will
   refuse to start in production — fail-closed, one layer
   down, same as operators today.
3. `deploy/verifier-identity/health_check.py` — `ALLOWED_KEYS`
   tuple gains the name. Plus two functional additions
   (health_check is a checker, not just a copy):
   (a) env-file check: in a production env file, a missing or
   non-absolute `AION_CEREMONY_EVIDENCE_DIR` is a FAIL line
   (mirroring how it treats other production-required config);
   (b) directories check: **if** the configured value equals
   the canonical path (§3.2), verify it exists with the
   §3.2 ownership/mode; a non-canonical absolute value is
   reported as an informational detail, not a FAIL — health
   check must not invent a layout policy the env var
   deliberately leaves open. (If seat C prefers (b) stricter —
   canonical-only in production — that is a deployment-policy
   decision for the coordinator; this design's minimum is (a)
   + the allowlist copy.)
4. `deploy/verifier-identity/setup.sh` — template gains the
   line (§3.2). The completeness test
   (`test_template_keys_equal_allowlist`) makes this
   mandatory, not cosmetic: template set must *equal* the
   allowlist set.

Also a fifth, test-side literal copy the brief did not list
but grep finds: `tests/test_trust_production_deploy.py`'s
wrapper test carries an inline `allowlisted = {…15 names…}`
set asserted as a superset bound on the launched verifier's
environment — it must gain the 16th name or that test fails
the first time a fixture env carries the new variable.

### 3.2 setup.sh template + the evidence directory itself

Template addition, after the `AION_CEREMONY_OPERATORS=` block
(and its comment rewritten per §2.3 item 6):

```sh
# Ceremony evidence (cycle 20): directory the verifier reads
# evidence artifacts FROM at issuance (mode
# ceremony_authorise). evidence_ref in a request is a relative
# path under this directory; the verifier resolves it there,
# hashes the bytes itself, and retains a copy under
# AION_VERIFIER_HOME/ceremony-evidence/. Provision artifacts
# as REAL files (no symlinks — the verifier refuses them),
# owned root, mode 0640 in a root:aion-verifier 0750
# directory: the verifier reads, it never writes here.
# Production refuses startup while this is empty.
AION_CEREMONY_EVIDENCE_DIR=/var/lib/aion-verifier/evidence
```

And in `setup.sh` proper: create `/var/lib/aion-verifier/
evidence` — deliberately **not** via the existing
`install -d -o aion-verifier … 0700` line. New line:
`install -d -o root -g "${VERIFIER_USER}" -m 0750
"${BASE}/evidence"`, plus the directory added to the final
`ls -ld` listing. Rationale for root ownership: every other
verifier directory is verifier-writable because the verifier
*must* write there (ledgers, anchors, key). The evidence
source is the one input the verifier must **not** be able to
rewrite — the same separation as the root-owned env file.
Root (the provisioning operator) writes artifacts; the
`aion-verifier` group (sole member: the verifier) reads.
Deviating from the all-0700 pattern is the point, and the
health_check directories check + its tests must learn the
exception explicitly rather than having it smoothed over.

Migration note (the F6 precedent, to be repeated in
BUILD-CYCLE-20): **existing production deployments must set
`AION_CEREMONY_EVIDENCE_DIR` and provision the directory, or
the verifier refuses to start after upgrade** — fail-closed by
design, announced, identical in kind to the cycle-19
`AION_CEREMONY_OPERATORS` migration.

### 3.3 Every test that pins this surface (grep-verified)

- `tests/test_trust_wiring.py` —
  `test_allowlist_is_the_shipped_15_names` (rename to
  `…_16_names`; `len == 16`; add `assertIn(
  "AION_CEREMONY_EVIDENCE_DIR", …)`; keep the
  `AION_SHIP_ANCHOR_PATH` negative) and
  `test_allowlist_matches_wrapper_script_at_test_time`
  (`len(wrapper_keys) == 15` → 16). The file's module
  docstring ("the wrapper allowlist has 15 names (cycle 19
  added …)") is updated to record cycle 20 adding the 16th.
- `tests/test_verifier_deploy.py` —
  `test_health_check_allowlist_matches_wrapper`
  (`len(health_keys) == 15` → 16);
  `test_every_verifier_main_env_var_is_allowlisted` (no edit
  needed — it extracts `AION_[A-Z_]+` from `verifier_main.py`
  and asserts ⊆ wrapper allowlist, so it *fails* until all
  four copies land: it is the cascade's tripwire);
  `test_template_keys_all_allowlisted` and
  `test_template_keys_equal_allowlist` (fail until setup.sh
  gains the line); add a named pin mirroring
  `test_ceremony_operators_key_allowlisted`:
  `test_ceremony_evidence_dir_key_allowlisted`.
- `tests/test_trust_production_deploy.py` — the inline
  `allowlisted` set (15 → 16 names) in the wrapper-launch
  test, and the production-success fixture
  (`test_f_production_mode_successful_run_reports_production`,
  whose env dict carries `AION_CEREMONY_OPERATORS` with the
  comment "production also requires … at startup") must add
  `"AION_CEREMONY_EVIDENCE_DIR": <tmp path>` — without it the
  production verifier now refuses startup and the test fails
  for the right reason in the wrong place.
- `tests/test_trust_ceremony_mode.py` — fixture rework, the
  largest test delta in this slice: `setUp` must create an
  evidence dir, write a real artifact file, set
  `AION_CEREMONY_EVIDENCE_DIR` in `self.env`, and set
  `EVIDENCE_HASH` to the **actual SHA-256 of the artifact
  bytes** (computed in the fixture, not the current constant
  `"c" * 64` — that constant is now a hash of nothing and
  every happy-path test would mismatch-refuse). New tests:
  production startup refusal without the var; malformed var
  (relative) refuses startup in research too; research +
  absent → `ceremony_evidence_unconfigured`; ref absolute /
  `..` / symlink / missing / empty / oversize refusals with
  **ledger-emptiness assertions** (the cycle-19 "malformed
  bodies burn nothing" discipline, extended: *no* pre-commit
  refusal in this slice burns anything); hash mismatch burns
  nothing and a corrected retry succeeds; unlisted operator +
  existing ref refuses `ceremony_operator_not_authorised`
  (the §1.6 order pin — this test is what stops a future
  refactor moving resolution above membership); retained copy
  exists after issuance, re-hashes to the envelope's
  `evidence_hash`, and is 0600; identical re-presentation and
  evidence-reuse tests now reuse *bytes*, not just a hash.
  The `fake_verifier_echo` client test is unaffected (client
  contract unchanged, §1.5).
- `tests/test_trust_ceremony_authorisation.py` (E2E) — same
  fixture treatment wherever it drives `ceremony_authorise`
  through the real subprocess.
- Unaffected, verified by grep: `tests/
  test_signing_ceremony_authorisation.py` and
  `tests/test_signing_pin_ceremony.py` mint envelopes
  in-process via `sign_ceremony_authorisation` — the signing
  module's API does not change in this slice (seat C's
  consumption changes may touch the latter; this slice does
  not).

### 3.4 `_load_config` implementation shape (for the build seat)

Follow the operators block's exact shape: read raw, validate,
detail strings name the variable and never echo its value,
`_config("verifier_misconfigured", …)` for every startup
refusal. `_Config.__init__` gains the keyword parameter at the
end beside `ceremony_operators` (keyword-only section already
exists for `deployment_mode`). No other mode reads the new
field; `gate` / `sealed_eval` / `issue_attestation` behaviour
in research with the variable absent is byte-identical to
today.

---

## 4. Risks, open questions, hand-offs

**For seat A (key boundary / asymmetric signing):**
- R1. Retention (§1.8) writes verifier-home files named by
  `authorisation_id`, which is derived from payload hash +
  key id. If seat A moves the envelope to asymmetric signing,
  `authorisation_id_for`'s derivation and the retained-file
  naming must be re-checked together — the filename must stay
  a pure function of the envelope, or retention needs its own
  naming rule. Flagging now so the two slices don't collide
  in the ledger commit order (§1.6 step 7 inserts a write
  between the two ledger appends seat A may also be touching).
- R2. Nothing in this slice depends on HMAC vs asymmetric:
  evidence resolution is entirely pre-signing. If seat A's
  design changes *who can verify* envelopes, the §1.9 claim's
  last clause ("signed by the verifier's key") is reworded by
  seat A's terms, not this note's.

**For seat C (consumption / pin_ceremony):**
- R3. **Old vs new envelopes are indistinguishable at
  consumption** (§1.9). If seat C's monotonic-head design
  records issuance provenance, record the *issuing verifier's
  deployment/cycle* alongside, or accept that pre-cycle-20
  envelopes carry the weaker claim forever. `pin_ceremony.py`'s
  evidence bullet must be edited per §1.9/§2.3 item 4 — the
  ceremony still never inspects the artifact; only issuance
  changed.
- R4. `reanchor_pin`'s caller still supplies `evidence_hash`
  as a bare parameter and it is equality-checked against the
  envelope. With issuance now computing the hash, the natural
  caller flow is "read it from the envelope", but this design
  does **not** change `reanchor_pin`'s signature — seat C's
  call whether the parameter stays (as an echo check) or is
  derived from the envelope in-cycle.
- R5. Retained copies give seat C's audit story content to
  compare, but the consumption-side ledger-presence check
  (M5) is still absent: retention does not let `reanchor_pin`
  verify an envelope was ledgered. Do not let §1.8 be cited
  as closing M5.

**Open questions for the coordinator / owner:**
- Q1. Production-startup refusal for the evidence dir (§1.2
  rule 2) extends the F6 migration pattern a second cycle
  running. F4's owner ratification is still outstanding from
  cycle 19; this design assumes the verifier-env placement it
  ratifies-or-not. If the owner rejects env-placement, §1.2
  and §3 move together — the *resolution design* (§1.3–§1.8)
  survives any config home, the variable name may not.
- Q2. §2.2 records operator authentication as a residual, not
  a fix. If the external seats treat CROSS-CHECK-13 item (4)
  as a hard SHIP gate for cycles 14–16 (as they did
  consumption replay), cycle 20's honest output is "evidence:
  fixed; operator auth: claim narrowed, layer still missing"
  — the coordinator should put that sentence in the cycle-20
  external brief verbatim rather than letting the seats
  discover it.
- Q3. Retention has no GC (§1.8). At ceremony volumes this is
  fine; if ceremonies ever become routine, a retention policy
  (anchored archival, then deletion) is a future cycle's
  design, and deleting retained evidence must be a ceremony
  of its own, never a cron.
- Q4. Evidence-directory provisioning (root copies artifacts
  in) is a new operator act with no tooling in this design.
  A `provision-evidence` helper is deliberately out of scope;
  hand-copying in the prototype is acceptable and auditable,
  but the deploy README's ceremony list should name the act
  (docs edit listed in §3.2's setup comment; README text
  itself is seat C / coordinator territory).

**Self-check against the brief:** evidence resolved and
verified verifier-side from an env-only protected location
(§1.2–§1.4); refs relative, absolute/`..`/symlink escapes
refused with the race stated honestly (§1.3–§1.4); verifier
computes the hash (§1.4); supplied hash kept as a cross-check
with malformed-class mismatch refusal before ledgering, body
stays 7 keys, anti-replay keys on the computed value (§1.5);
size cap 1 MiB with exit-3 semantics (§1.5, §1.7); content
opaque, claim says existence+hash only (§1.5, §1.9); retention
decided yes, into the verifier home, named by authorisation
id (§1.8); order places resolution after membership, before
scan/sign/ledger (§1.6); operator machinery inventoried from
the code, claim narrowed with exact passages, token scheme
specified only as an overrule appendix with its ceiling
(§2); new env var cascaded through all four allowlist copies
plus the test-side fifth, with every pinning test enumerated
(§3).
