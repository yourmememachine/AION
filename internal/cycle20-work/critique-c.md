# CRITIQUE C — Cycle 20 design round (seat C, consumption integrity)

Adversarial critique of design-a (pure-Python Ed25519) and
design-b (evidence resolution + operator-auth narrowing), plus
defence/amendment of design-c where their open questions touch
it. Section references are to the three design files in this
directory. Code references are to `signing/pin_ceremony.py`
and `signing/ceremony_authorisation.py` as read this round.

Headline verdicts:

- **A: FIX (not BLOCKER on the route).** Route 1 is the right
  route and C adopts it, but A's verification profile is
  specified at the level of prose where it must be specified
  at the level of an equation plus a rejection list, and the
  "residual id check" A §3 and C §4.3 both retain is **dead
  code by construction** (Finding A2) — both designs missed it.
- **B: FIX.** Evidence resolution is sound in shape; three
  SHOULD-FIXes (fd-walk claim vs its own root handling,
  diagnosability, retention expectations) and one wording
  programme that does not yet agree with C's sweep
  word-for-word (§3 below supplies the single canonical
  sentence both must use).
- **C (self): one claim amended, one parameter dropped.**
  See §6: "fail-closed" must be qualified everywhere as
  "fail-closed on omission", and C drops its
  `expected_authorisation_key_id` parameter in favour of A's
  bundled-object shape, conditional on A pinning an internal
  consistency check (Finding A1).

---

## 1. Design A under C's step order (task point 1)

Current `reanchor_pin` order (code): snapshot-key consistency
check → (1) type checks → (2) key separation → operator/reason/
evidence_hash form checks → single clock capture → old-pin
capture → (3) `verify_ceremony_authorisation` → (4) exact
binding → (5) evidence non-equality → relation/strict checks →
history → bare attestation verify → record.

### A1 — SHOULD-FIX: the verify-call shape in A §3 and C §4.3 disagree, and the vocabulary needs one new pinned meaning

A §3 renames the parameter to `public_key: CeremonyPublicKey`;
design-c §4.3's placeholder call passes `verify_key=…`. One
name must win before the build round or every helper breaks
twice. **Resolution: A's name wins** (`public_key=`), because
the object is a public key, not a generic verify key, and C
amends §4.3 accordingly (see §6).

Reason vocabulary under A's format (A §3 claims "unchanged";
that is *almost* true and the exceptions must be pinned):

- `signature_mismatch` changes semantics. Today (code) it is a
  folded reason: non-hex64 signature **or** HMAC inequality
  both land there. Under A, non-hex128 is refused at
  `from_dict` parse, so inside `verify_…` the reason becomes
  *pure Ed25519 equation failure*. But a
  `SignedCeremonyAuthorisation` can be constructed directly as
  a dataclass, bypassing `from_dict`; `verify_…` must still
  length/format-check the signature itself and fold failure
  into `signature_mismatch` (never raise, never crash on a
  32-byte signature). A's §5 negative vectors test the
  primitive, not this path. **Resolution:** A adds one
  envelope-level test: hand-constructed typed envelope with a
  hex64 (v1-length) signature ⇒ `("signature_mismatch",)`,
  no exception.
- `unknown_key` keeps its meaning exactly: presented
  envelope's `key_id` ≠ pinned public key's derived id
  (A §3). Good — and note it now fires *before* any signature
  work matters, so a substituted-key envelope (A §5a) refuses
  for a stated reason, not a cryptographic shrug.
- `key_id_inconsistent` needs a **new pinned meaning** A does
  not state: today it means `signing_key.key_id !=
  key_id_for(signing_key.key)` (the held secret disagrees with
  its claimed id). The analogue for a `CeremonyPublicKey`
  object is `obj.key_id != public_key_id_for(obj.public_key)`
  — the object lying about its own id. Without this check, a
  caller-constructed object with a *correct* public key and a
  *fabricated* `key_id` field makes `unknown_key` compare the
  envelope against the fabrication while the signature is
  verified against the real key — the two halves of step (3)
  would be talking about different keys. **Resolution:** A
  pins `key_id_inconsistent` := the verify object's internal
  inconsistency, checked first in `verify_…` (mirroring
  today's early return), and C's step (1) type check asserts
  the same consistency so `reanchor_pin` refuses a lying
  object even before step (3).

### A2 — BLOCKER (wording/mechanism, both A and C): the retained id-equality tripwire can never fire

A §3 layer 3 and design-c §4.3 both retain: refuse if the
authorisation key id equals the snapshot `signing_key.key_id`.
Under A's own derivations this is **vacuously false forever**:
the snapshot id is `"key-" + sha256(secret)[:16]`
(`key_id_for`), the authorisation id is `"pub-" +
sha256(public_key)[:16]` (A §1/§3). The 4-character prefixes
differ; the strings can never be equal, for *any* key
material, including the exact misconfiguration the check
claims to catch (same seed wired to both slots produces a
`key-…` id on one side and a `pub-…` id on the other — and
passes). A retained check that cannot fire is worse than no
check: a future reader sees "separation tripwire" in the
docstring and stops thinking. C indicts its own §4.3 here
equally — this is C's §7 item 3 wording ("refuses gross
misconfiguration") repeating a claim the mechanism does not
support.

**Resolution (concrete):** delete the id-equality check from
both designs. Replace it with the two checks that *can* fire:
(i) in-process, step (1): `authorisation_public_key` type is
`CeremonyPublicKey` and internally consistent (A1) — a
`SigningKey` in that slot is a type refusal, which is the
real gross-misconfiguration catch available in-process;
(ii) provisioning-side (seat B, A §3 already gestures at it):
refuse a ceremony seed **byte-equal** to any HMAC key in the
deployment, and refuse a ceremony seed whose *derived public
key's raw bytes* equal any held HMAC key's raw bytes (the
only same-material reuse detectable from public material).
The docstring sentence in C §7 item 3 must be rewritten to
say separation is type-level + provisioning-level, with **no**
in-process id tripwire claimed.

### A3 — NOTE: signer_id / key_id binding to `expected_verifier_signer_id` survives intact

Walked explicitly, since the task asks: the envelope's
top-level `signer_id` is a payload field independent of the
key; `verify_…` compares it to `expected_signer_id` and
returns `signer_mismatch`; step (4) never reads it (it relies
on step (3)'s pin, per the existing code comment). Nothing in
A's format change touches `signer_id` derivation, so
`expected_verifier_signer_id` keeps working byte-for-byte,
and C §4.3 is right to keep it **unmerged** with the key id:
under A the distinction actually sharpens — `signer_id` is a
*claimed identity string*, `key_id` is now a *hash of the
actual verifying key*, and an envelope could in principle
carry the right signer_id signed by the wrong key (refused by
`unknown_key`) or the wrong signer_id signed by the right key
(refused by `signer_mismatch`). Both legs must stay separate
tests; A §5's key-substitution matrix covers the first, C
asks A to confirm the second is in the carried-over
field-tamper matrix by name.

### A4 — NOTE: nothing else in `pin_ceremony` secretly assumed HMAC — verified, one exception handled by A2

Grepped and read: `pin_ceremony.py` uses `authorisation_key`
in exactly two places — the step (1) `isinstance` check and
`.key_id` at step (2) — and passes it whole to `verify_…`.
It never touches `.key` bytes, never MACs with it, and step
(4) never read the key (C §4.3 already said this; now
verified against code, not memory). The ceremony *record's*
MAC uses the snapshot `SigningKey` and is untouched (A §4
agrees). `authorisation_id` derivation changes inputs (v2
domain + `pub-…` id, A §3) but reaches C only as an opaque
carried string in the record. No step in `pin_ceremony`
derives anything from authorisation secret bytes. The one
implicit HMAC assumption was step (2)'s "two ids are
comparable because both derive from secrets the same way" —
that is A2, and it is the whole list.

### A5 — SHOULD-FIX: sign-time side channels — A's §1 dismissal is one sentence too fast

A §1 says timing "matters only where a secret scalar is
multiplied: the *signing* side, inside the verifier process,
against a local timing observer", citing the existing
same-OS-user caveat. C's assessment: **in scope as a
documented limit, out of scope as a blocker** — but A must
earn that placement, not assert it. The concrete exposure:
the verifier is spawned per-request as a subprocess (B §2.1);
a local attacker who can *invoke* ceremony authorisation
repeatedly and time responses gets many samples of a
variable-time scalar multiplication of the clamped secret
scalar (and of the deterministic nonce point `[r]B`, whose
leak is equally fatal — `r` plus the signature yields the
secret scalar arithmetically). The mitigations are real —
dedicated `aion-verifier` OS user, scrubbed environment,
subprocess-spawn noise (~ms) swamping the signal, and the
repo's pre-existing same-user honesty limit — but they are
*deployment* facts from B's slice that A never cites.
**Resolution:** A §1's timing bullet is rewritten to (i) name
both secret-dependent multiplications (secret scalar and
nonce scalar), (ii) cite the dedicated-user deployment and
the existing honesty limit as the reason this is a documented
limit rather than a defect, and (iii) state the residual in
the module's honest-limits docstring, not only in the design
file. If the war room judges a *shared-host, multi-tenant*
deployment in scope, this upgrades to BLOCKER and route 1's
signing half needs a constant-time ladder — that judgement is
a coordinator decision (§7), not something A may pre-decide
by silence.

### A6 — BLOCKER (specification): pin the exact verification equation and rejection list; "or equivalently" is not a spec

A §1's strictness paragraph offers alternatives at exactly
the points where a pure-Python verifier lives or dies:
"check against the 8 known small-order encodings, **or
equivalently** verify `[8]P ≠ identity` handling", and the
label "strict/'ZIP-215-minus' semantics" is a nickname, not a
definition. These are **not** equivalent in edge behaviour
(the blocklist rejects specific encodings including
non-canonical representatives of small-order points; a
cofactor-multiplication check on a *decoded* point interacts
differently with the canonical-encoding requirement), and an
implementer choosing the other branch produces a different
verifier than the war room reviewed. The forgery surface if
this is left soft: with the cofactorless equation
`[S]B = R + [H(R‖A‖M)]A`, a verifier that accepts
non-canonical `A`/`R` encodings or small-order `R` admits
signature *malleability* (the same logical signature under
multiple byte strings — which then have different
`authorisation_id`-adjacent artefacts and defeat any
byte-level duplicate detection), and a verifier that accepts
a small-order `A` anywhere the pinned-key check is ever
relaxed admits the classic identity-key forgery
(`A = identity`, `R = [S]B` for arbitrary `S`). A's pinned-key
design blunts the `A` attack *today*; verification profiles
outlive the call sites that blunt them.

**Resolution — A must state, verbatim, in §1 and in the
module docstring:**
1. Equation: cofactorless, `[S]B = R + [H(R‖A‖M)]A`, `H` =
   SHA-512, message = the §3 signed blob. No cofactored
   variant accepted anywhere.
2. `S` rejected unless `0 ≤ S < L` (canonical scalar).
3. `A` and `R` rejected unless: encoding is canonical
   (`y < q` **and** decode→re-encode reproduces the input
   bytes exactly), **and** the decoded point is not in the
   small-order blocklist (the 8 encodings listed as literal
   constants in the module, sourced and commented), **and**
   the point is not the identity. Blocklist is the mechanism;
   the `[8]P` formulation is deleted, not offered as an
   alternative.
4. Signature rejected unless exactly 64 bytes; public key
   unless exactly 32 bytes (already in A §5 — move from test
   list to normative text).
5. Every rejection returns `False`/`signature_mismatch` —
   the verifier never raises on adversarial input (A §3's
   sketch already promises this for the primitive; extend the
   promise to the envelope layer per A1).
A §6 item 6 asks the room to ratify "strict" as a judgement
call; C ratifies the *direction* and refuses to ratify the
*current text* — ratification applies to the list above once
written.

### A7 — NOTE: A's §5 test plan is strong; two additions

(a) The golden-v1 test (A §5c) must assert the *version*
refusal distinctly — see §4 below. (b) Add a test that a
genuine envelope verified against a `CeremonyPublicKey` whose
`public_key` bytes are the verifier's but whose `key_id`
field is fabricated refuses with `key_id_inconsistent` (A1).
Otherwise C endorses §5, in particular §5b (local minting) as
the correct regression test for the cycle-19 defect.

---

## 2. Design B at consumption: the `evidence_hash` parameter (task point 2)

### B1 — NOTE (analysis) + SHOULD-FIX (one docstring precondition): keep the parameter; the "caller lying to itself" framing dissolves under a who-protects-whom analysis

B §1.5 keeps the request's `evidence_hash` as an issuance
cross-check and makes the verifier's computed hash
authoritative in the envelope. B §4 R4 then asks whether
`reanchor_pin`'s caller-supplied `evidence_hash` argument
should survive, since at consumption it is still
caller-asserted. Walked from the consumption seat:

**Who is protected from whom at consumption?** Three parties
matter: the *caller* (future loop/storage layer stating what
ceremony it intends), the *envelope presenter* (whoever hands
the envelope to that caller — in today's in-process API the
same process, but the API is explicitly designed for the
wired system where they separate, cf. design-c §2), and the
*verifier* (whose computed hash the envelope now binds,
post-B). The step-(4) equality `env_evidence_hash !=
evidence_hash ⇒ refuse` protects **the caller from a
substituted envelope**: without the parameter, the envelope
is self-certifying on the evidence axis — *any* genuine
envelope for this operator/reason/candidate, including one
minted over different (real, verifier-resolved, but wrong
for this caller's purpose) evidence, would consume. With it,
the caller states its intent independently and the envelope
must match the intent. That is the same protective shape as
every other step-(4) leg (operator, reason, old_pin,
candidate are all caller-asserted arguments exact-bound to
the envelope) — evidence was never the odd one out; it only
looked odd in cycle 19 because the *issuance* side also
trusted the assertion. B fixes the issuance side. The
consumption side assertion was never the defect.

**"A caller lying to itself"** is therefore not a threat in
the model: a caller that supplies a false `evidence_hash`
gets a refusal (it won't match the envelope) or, if it also
fabricated the envelope, is stopped by A, not by this check.
Self-deception by the trusted caller is out of scope for
every parameter of this function (a caller can equally pass
a restaged `old_pin` — that is design-c's §5 residual, a
*stale-input* problem, not a *lying-input* problem, and it is
not made worse by this parameter).

**Re-deriving step (5) if the parameter were dropped**
(the exercise the task sets): step (5) refuses when the
evidence hash equals `signed.payload_hash`,
`signed.snapshot_id`, `signed.state_sha256`, or
`signed.calibration_sha256`, and `_check_ceremony_history`
refuses evidence reuse against the same value. If the
parameter were dropped, both would run on
`authorisation.evidence_hash` *after* step (3) has verified
the signature — a value that is then verifier-computed
(post-B) and signature-bound (post-A), i.e. **stronger**
provenance than the caller assertion. The checks re-derive
cleanly; nothing breaks mechanically. What is lost is only
the intent-binding above, plus signature stability of a
function whose callers don't exist yet (design-c §2) — so
the cost of keeping is ~zero and the cost of dropping is a
real (if future) substitution leg.

**Resolution:** the parameter **stays** under B+A.
Design-c §4.1 is unchanged on this point. But B R4's
"natural caller flow is 'read it from the envelope'" must be
**refused as guidance**: a caller that copies the value out
of the presented envelope and passes it back as the argument
makes step (4)'s evidence leg a tautology and silently
retires the intent-binding. **SHOULD-FIX:** design-c gains a
fourth named caller precondition beside FRESH-PIN /
COMPLETE-HISTORY / ATOMIC-ADOPTION (§4.2) —
**EVIDENCE-INTENT:** `evidence_hash` must come from the
caller's own record of the evidence it reviewed, never copied
from the presented envelope; copying it converts the binding
check into an echo. B's §1.9/client wording must not suggest
the read-it-from-the-envelope flow. (Symmetric to issuance:
there the caller's hash is intent the verifier checks; here
it is intent the envelope is checked against. One concept,
both ends — B should say so in §1.5, it strengthens B's own
argument for keeping the 7-key body.)

### B2 — SHOULD-FIX: the fd-walk's "any symlink anywhere" claim is false for the root, and the root has the very race B removes below it

B §1.4 step 1 does `root = Path(…).resolve()` and step 2
walks from "an fd opened on `root`" with `O_NOFOLLOW` on
every component, claiming "any symlink anywhere on the path
refuses" and that the check/use window is removed. Two
problems:

1. **The root itself is exempt in practice, and must be.**
   `resolve()` *follows* symlinks in the root path and all
   its ancestors. That is not a bug — it is what makes the
   legitimate deployment work: the configured value in B
   §3.2's template is `/var/lib/aion-verifier/evidence`, and
   path canonicalisation above the evidence dir (a symlinked
   `/var/lib` component, a bind-mounted or symlinked
   `/var/lib/aion-verifier`, a distro layout where the base
   is a link) is ordinary systems plumbing that has nothing
   to do with evidence substitution. If B's claim were
   implemented literally (no symlink in *any* component
   including ancestors), the canonical deployment breaks on
   exactly those systems. Conversely, a symlink *below* the
   root (`evidence/current → bundle-2`, a versioned-bundle
   provisioning pattern) **does** refuse under B — B states
   this consequence honestly ("real files in real
   subdirectories"), and C accepts it: below-root symlinks
   are the substitution surface, above-root canonicalisation
   is the deployment's own config trust.
2. **The root reintroduces a resolve→open window.** Between
   `resolve()` and `os.open(root)` the root path can be
   swapped — the same check/use gap B §1.4 refuses to "paper
   over" for components below it. The window is small and the
   attacker who can swap the root directory is close to the
   already-stated same-user limit, but B's text currently
   claims the window is *removed*, full stop.

**Resolution:** B §1.4 is reworded to scope the guarantee
precisely: "no symlink in any component **below the
configured root**; the root path itself is resolved once
(trusted configuration — whoever can rewrite the root or its
ancestors can already rewrite the env file naming it) and
opened by fd; all traversal below it is fd-relative with
`O_NOFOLLOW`, so the object hashed is the object
containment-checked." Add the intermediate-component detail
the build will need anyway: directory components opened
`O_RDONLY | O_DIRECTORY | O_NOFOLLOW` with `dir_fd`. No
mechanism change; the claim shrinks to the mechanism, which
is rev-r6's whole discipline.

### B3 — SHOULD-FIX: one caller-facing refusal code, yes; zero operator diagnosability, no

B §1.7 folds root-missing, symlink, non-regular, empty,
unreadable, and torn-read into one code,
`ceremony_evidence_unresolvable`, arguing distinct codes hand
a listed operator an enumeration oracle and "the operator who
provisioned the artifact already knows which case they are
in". The oracle argument is sound **for the caller-facing
code**. The diagnosability conclusion does not follow: the
operator *on call at 03:00* is not necessarily the operator
who provisioned, and B gives them a single code covering
"directory was never mounted" through "file is a fifo" — a
production ceremony outage with no first diagnostic bit,
in a design that elsewhere (B §1.2) is careful about exactly
operational surfacing.

**Resolution:** keep the single caller-facing code and fixed
caller-facing detail (oracle argument stands). Add a
**verifier-side diagnostic** that never crosses the protocol:
a distinct fixed reason string per sub-case written to the
verifier's stderr / diagnostic log at refusal time (the
verifier process already lives behind a wrapper with its own
logging surface; the string names the sub-case, never a path
or errno text). One paragraph in B §1.7; one test asserting
the caller-visible document is byte-identical across two
different sub-cases while the diagnostics differ. This is
the standard split — uniform to the potential prober,
specific to the operator — and B's current text conflates
the two audiences.

### B4 — SHOULD-FIX: retention is worth its commit-order cost, but B must explicitly *deny* the consumption-side expectation it will otherwise create

Task's challenge, taken head-on: does retention without
anchoring earn the §1.6 step-7 complexity (a new post-commit
`ledger_failed` burn mode inserted between the two ledger
appends)? C's verdict: **yes, and the "unanchored" objection
is weaker than it looks** — because the retained bytes do not
need their own anchor: the *envelope's signed `evidence_hash`*
is the commitment, and it is ledgered. A tampered retained
copy re-hashes to something ≠ the envelope hash and is
*detected*, which is all anchoring would buy for integrity
(anchoring buys non-repudiation of *existence at a time*,
which B correctly lists as a follow-up, not a property).
B §1.8's auditability argument therefore holds.

But two things must be nailed down before the build:

1. **No consumption path reads retained copies this cycle.**
   The moment `ceremony-evidence/<authorisation_id>` exists,
   a future reader will assume `reanchor_pin` or an audit
   mode can re-hash retained evidence as part of consumption
   — i.e. that retention is a step toward closing M5
   (ledger-presence at consumption). It is not: `reanchor_pin`
   is in-process in a different trust domain with no access
   to the verifier home, and B §4 R5 already warns against
   citing §1.8 as closing M5. **Resolution:** B §1.8 gains an
   explicit non-goal sentence — "retained copies are an
   audit artefact for a future audit process; no code in
   this cycle reads them, and consumption neither consults
   nor may be described as able to consult them" — and
   design-c §7 item 4's docstring sentence gains the matching
   clause so the expectation cannot grow from C's file
   either.
2. **The burn cost must be accepted by name.** Retention
   failure after journal commit burns the (ceremony_id,
   evidence_hash) pair and withholds a *valid* envelope for
   a bookkeeping write. C accepts B's ordering (retention
   before signing-ledger append is the only order that makes
   "every issued envelope has its copy" true), but
   BUILD-CYCLE-20 must list "retained-write failure burns
   the pair" as an accepted failure mode, not let it be
   discovered in review. NOTE severity on the ordering
   itself; the SHOULD-FIX is the expectation wording in (1).

### B5 — NOTE: points where C endorses B against likely attack

For the record, so the room does not re-litigate settled
ground: membership **before** resolution (B §1.6 step 3) is
correct and C's consumption-side ordering (§4.1 step 2.5,
presence before envelope verification) follows the same
principle — cheap, side-effect-free refusals before any
check with effects. The mismatch refusal
(`ceremony_evidence_hash_mismatch`, exit 2, unledgered,
retryable) is correctly classed. The 1 MiB cap grounded in
`MAX_REQUEST_BYTES` is the right kind of grounding. The
token appendix (§2.4) with its claim ceiling is the correct
way to spec a rejected option.

---

## 3. Claim narrowing: B §2 vs C §7 — the single canonical sentence (task point 3)

**Do the two programmes agree word-for-word? No.** They agree
in substance and diverge in at least four places that matter
for a grep-gated sweep:

| Point | B §2.3 | C §7 |
|---|---|---|
| Term | "allowlist membership" / "operator-id allowlist eligibility" | "list membership" (carried from cycle-19 text); §7 item 3 keeps "a listed operator's presentation" |
| Scope of non-authentication | "not authentication" + "or of a process" extension | "not authentication of a human" (cycle-19 sentence, extended only in part) |
| Mechanism reason | "no per-operator credential exists in this system, and any caller able to launch the verifier can present any listed id" | absent — C asserts the conclusion without the reason |
| Provenance clause | envelope "proves a presentation under an allowlisted id, ledgered and event-bound; it does not prove which human or process made it" | C §7 item 3 adds the sharper clause B lacks: the binding is **workflow provenance, not cryptographic attribution** — "nothing in the envelope is evidence *by* the operator, only *about* them" |

**Coverage diff (each missed places in the other):**

- **B's list has, C's sweep (§7.1) missed:** `setup.sh`
  template comment (B §2.3 item 6); the `_load_config`
  comment (item 2); the **strict-key error detail** in
  `_mode_ceremony_authorise` — user-visible protocol text
  saying "operator authority comes from the verifier's
  configuration" (item 2) — C's sweep, being docstring-only,
  structurally cannot see error strings, and this one is a
  claim a caller actually reads; `verify_ceremony_authorisation`'s
  closing note rewording ("does NOT prove the presenter was
  the named operator…", item 3).
- **C's sweep has, B's list missed:** the workflow-provenance
  / cryptographic-attribution sentence (C §7 item 3) — B's
  canonical sentence proves *presentation*, but never says
  the envelope is not evidence *by* the operator, which is
  the sentence a future reader needs when treating an
  envelope as operator attestation; the issuance-≠-consumption
  sentence for single-use scoping (C §7 item 4) — B §7.1(a) in
  C's file assigns B the "single-use" scoping for `ledger.py`
  / client, and B §2.3's list does not mention `trust/ledger.py`
  at all (B's §1.9 wording covers evidence claims in
  `verifier_main.py` only); and the GATE-CLOSURE dependency-
  **coverage** wording (C §7 item 5/§7.1), outside B's
  operator axis but inside the same claim-correction verdict
  B claims to answer.

**Proposed single canonical sentence** (both designs adopt
verbatim; per-file voice adaptations are forbidden for this
sentence — B §2.3 says "adapted in voice, not weakened", and
adaptation is exactly how cycle 19's wording drifted):

> Operator identity is operator-id allowlist eligibility via
> the verifier's launch channel, not authentication: the
> verifier checks that the presented `operator_id` was on its
> configured allowlist at issuance; it does not and cannot
> verify that the presenter *is* that operator — no
> per-operator credential exists in this system, and any
> caller able to launch the verifier can present any listed
> id. The envelope proves a presentation under an allowlisted
> id, ledgered at issuance and bound to this event — workflow
> provenance, not cryptographic attribution: nothing in the
> envelope is evidence *by* the operator, only *about* them,
> and it does not prove which human or process made the
> presentation.

This is B's canonical sentence with C's provenance clause
fused in and B's term "operator-id allowlist eligibility"
made the head term. **Resolution:** B §2.3 and C §7 item 3
both carry this text; the mechanical replacements in B §2.3
("operator authority" → "operator-id allowlist eligibility",
"authorised operator" → "allowlisted operator id") are
adopted by C unchanged, and C's grep gate extends B's: after
the build, `grep -rn "operator authority" trust/ signing/
deploy/` returns zero hits outside `internal/`, **and**
`grep -rn "authentication of a human" signing/ trust/`
returns zero (the superseded shorter sentence must not
survive anywhere as a weaker variant).

---

## 4. Version indistinguishability: C accepts A's v2, and demands explicit v1 refusal (task point 4)

B §1.9 declines a version bump (envelope format unchanged;
the strengthened evidence claim is an issuance-time fact, not
an envelope property) and flags the consequence for C in
§4 R3: old and new envelopes are indistinguishable at
consumption. **That consequence is dissolved by A, not by
B:** A §3 bumps the domain to
`signed-ceremony-authorisation-v2`, payload `"v"` to `/2`,
and `alg` to `ed25519` in the same change. A cycle-20
consumer therefore never faces B's ambiguity for
*cycle-20-issued* envelopes — a v2 envelope is recognisably
post-change on every axis at once. **C accepts v2 as the
resolution of B R3, conditional on A and B landing in the
same cycle.** If B landed alone, C would BLOCK: B's
issuance-terms wording ("at issuance, the verifier…") is
honest in B's files but unenforceable at consumption, where
the strengthened claim would be applied to indistinguishable
artefacts. The coordinator must not split A and B across
cycles without re-opening this point (§7).

**Must consumption REFUSE v1 explicitly, rather than merely
fail to parse it? Yes — explicit, with a named test.** A's
§3 tripwires make a v1 envelope fail three ways (domain in
the signed blob, alg projection, hex64 vs hex128), and A
§5c's golden-fixture test asserts `from_dict` raises. That
is not enough, for the rev-r4 reason: a raise is not a
*reason*. A v1 envelope presented to cycle-20 code is not
"malformed" in the same sense as a truncated one — it is a
*known, superseded format*, and the operator action differs
(re-issue under v2; do not debug the artefact). Worse, if
the failure surfaces as generic `malformed_payload`, a
future maintainer may "fix" it by adding a v1 parse path —
the silent fallback A §3 exists to prevent, arriving via
diagnosability failure.

**Resolution:** `ceremony_authorisation_envelope_from_dict`
refuses any envelope whose payload/domain/version identifies
it as v1 with a `SigningError` whose message names the
superseded version (proposed text: "ceremony authorisation
version 1 is not accepted by this build (cycle 20 requires
v2)"), checked *before* the signature-format check so the
message is not masked by the hex128 failure. This is a
parse-level `SigningError`, **not** a new `verify_…` reason —
a v1 envelope can never become a typed object, so it can
never reach verify, and A's "vocabulary unchanged" claim
(A1's pinned exceptions aside) survives. Tests: A §5c's
golden v1 fixture asserts the version message specifically;
plus one `reanchor_pin`-level test presenting the golden v1
envelope (via whatever pre-parse path the helper uses)
asserting the ceremony refuses with that message and mints
no record. Cost is nil: v1's maximum lifetime is the 900 s
TTL (A §3), so explicit refusal strands nothing legitimate.

---

## 5. Consolidated findings on A and B (severity index)

| # | Design | Severity | Finding |
|---|---|---|---|
| A1 | A §3 | SHOULD-FIX | Verify-call name + `key_id_inconsistent` new meaning pinned; direct-construction signature-format path tested |
| A2 | A §3 / C §4.3 | **BLOCKER** | Retained id-equality tripwire can never fire (`pub-` vs `key-` prefixes); delete, replace with type + provisioning checks |
| A3 | A §3/§5 | NOTE | signer_id/key_id separation survives; both refusal legs named as tests |
| A4 | A §3 | NOTE | No other HMAC assumption in `pin_ceremony` — verified against code |
| A5 | A §1 | SHOULD-FIX | Sign-time timing: name both secret multiplications, cite deployment mitigations, carry in honest-limits docstring; BLOCKER only if shared-host timing is ruled in scope |
| A6 | A §1/§6 | **BLOCKER** | Verification profile must be one pinned equation + rejection list; delete "or equivalently" and the ZIP-215-minus nickname |
| A7 | A §5 | NOTE | Add v1-message assertion (§4) and fabricated-key_id test (A1) |
| B1 | B §1.5/§4 R4 | NOTE + SHOULD-FIX | `evidence_hash` stays at consumption (intent-binding); add EVIDENCE-INTENT precondition; forbid read-from-envelope flow |
| B2 | B §1.4 | SHOULD-FIX | "Any symlink anywhere" is false for the resolved root and would break legitimate canonicalisation; scope the claim below-root; root resolve→open window named |
| B3 | B §1.7 | SHOULD-FIX | Single caller code kept; add verifier-side per-sub-case diagnostic that never crosses the protocol |
| B4 | B §1.8 | SHOULD-FIX | Retention endorsed (envelope hash is the commitment); add explicit "no consumption path reads retained copies" non-goal in B and C; burn mode accepted by name in the BUILD record |
| B5 | B §1.6/§1.5/§2.4 | NOTE | Membership-before-resolution, mismatch classing, cap grounding, token appendix endorsed |

---

## 6. Design C's weakest point, stated by C (task point 6)

**Is required-history with empty-allowed for
`chain_gap_recovery` actually fail-closed in any meaningful
sense for a FIRST ceremony? No — and C amends its language
accordingly.** For a first gap ceremony, the honest history
(`()`) and the attacker's stale history (`()`) are the *same
value*. Nothing is verified; a claim is recorded. What §3.1
buys for that case is exactly two things, neither of which is
prevention: (i) omission — the *accidental* disabling path,
the one a tired integrator takes — now refuses instead of
silently skipping every check; (ii) the assertion becomes
explicit and attributable, so a caller who passes `()` twice
has made a falsifiable statement a reviewer (or the future
protected head) can hold it to, instead of having omitted a
default. Calling that "fail-closed" without qualification
commits the overclaim design-c §3.2 itself warns against:
Gemini's demand was "fail-closed if state/history
continuity cannot be verified", and for the first-ceremony
case continuity *cannot* be verified in-process — the design
fails closed on **absence of an assertion**, not on
**absence of verification**. Those are different properties
and cycle 19's history is what happens when they are
blurred.

**Does T8 concede Gemini's point entirely? For the
stale-history leg, yes — and C should say so in those
words.** T8's stale leg replays a genuine envelope against a
restaged `old_pin`, with the real pin since advanced past
the candidate by `advance_pin` steps the history cannot even
see, and the ceremony *succeeds and returns the regressed
pin*. That is Gemini FIX (3)'s attack, succeeding, in a test
C wrote. What C defends is not the outcome but the
*boundary*: every stronger in-process rule was examined and
deadlocks or deceives — non-empty history for
`chain_gap_recovery` deadlocks the first genuine gap
ceremony (the ceremony's primary use case, §3.2); a
`live_pin` callback is the restaged argument in a function
costume (§2); a store read is not atomic with adoption and
the store does not exist. The symmetry between "first" and
"stale" is broken only by state the caller does not supply —
the protected monotonic head of §5. So the honest minute for
cycle 20 is: **Gemini (3) is answered on two of three legs**
(omission now refuses; updated-history duplicate now
refuses) **and conceded on the third** (stale history),
with F1 carried as *narrowed, still open* — which is what
design-c §8 items 7–8 already require of the BUILD record.

**Amendments to design-c (C makes these itself, no
coordinator ruling needed except item 3):**

1. Everywhere design-c and the §7 docstring replacements say
   "fail-closed" for §3, read **"fail-closed on omission"**.
   §7 item 1's replacement text gains the clause: "…
   fail-closed on omission: an explicit empty history is a
   caller assertion this module cannot check (§ residual),
   not verified continuity."
2. T8's test docstring and the §5 residual paragraph gain
   the sentence: "This test concedes the stale-history leg
   of the external consumption-replay finding; it is pinned
   so the concession is executable, not rhetorical."
3. rev-r6 and the external seats are re-polled on the
   two-of-three-legs basis (§8 item 7) **before** the build
   round, with the specific question whether "mandatory
   history + named residual" satisfies the flip condition or
   whether cycles 14–16 stay held until the protected head
   exists. C does not pre-answer it.
4. §4.1/§4.3 amended per A1/A2: parameter becomes
   `authorisation_public_key: CeremonyPublicKey` (A's shape);
   C's separate `expected_authorisation_key_id` parameter is
   **dropped** — A1's internal-consistency check gives the
   bundled object the property C wanted the extra pin for
   (the object's id cannot lie about its key), and a second
   caller-supplied pin at the same trust level added a
   parameter, not a guarantee. The id-equality tripwire is
   **deleted** per A2. `expected_verifier_signer_id` stays,
   unmerged (A3).

What C continues to defend without amendment: required
history itself (the alternative — leaving omission silent —
is strictly worse and was the actual defect in §1(iii));
empty-allowed for `chain_gap_recovery` (a bootstrap fixed
point, not a convenience); `initial_anchor` empty-*only*
(the one per-reason rule that does add a real refusal: it
kills the re-bootstrap laundering path the generic checks
miss, §3.2); and the refusal to build a live-pin callback
(§2) — a mechanism that cannot work, built anyway, is how
cycle 19 got its findings.

---

## 7. Decisions needed from the coordinator

1. **A2 ratification:** delete the id-equality tripwire from
   both A §3 and C §4.3 and replace with (type +
   internal-consistency) in-process and (seed byte-equality)
   at provisioning (seat B). Needs A's and B's assent since
   the replacement spans both slices.
2. **A6 ratification:** the pinned verification list in A6
   (cofactorless equation, canonical encodings, blocklist
   mechanism, exact lengths, never-raises) as the text A §6
   item 6 asked the room to ratify — replacing A's current
   prose before the build round, not during it.
3. **A5 scope ruling:** is a same-host timing observer of the
   verifier process inside cycle 20's threat model? If yes,
   A5 upgrades to BLOCKER and route 1's signing half needs a
   constant-time scalar ladder (or the room revisits route
   3/4 for signing only). If no, A documents the limit per
   A5 and the room moves on.
4. **A+B same-cycle landing:** confirm A and B land together;
   if they split, B-alone requires re-opening §4 (v1/v2
   indistinguishability of the evidence claim) before B
   ships.
5. **Canonical sentence:** adopt §3's fused sentence verbatim
   in B §2.3 and C §7, with the extended two-pattern grep
   gate. If either seat edits a word, both files change —
   the sentence is one artefact with two homes.
6. **Explicit v1 refusal (§4):** approve the parse-level
   version-named `SigningError` and its two tests as part of
   A's slice.
7. **B3 diagnostics:** approve the stderr/diagnostic-log split
   (uniform caller code, specific verifier-side sub-case) —
   touches B's verifier slice and possibly the wrapper's
   logging surface.
8. **Re-poll before build (§6 amendment 3):** rev-r6 +
   external seats re-polled on the two-of-three-legs basis
   for Gemini (3) / GPT's cycles 14–16 condition, so the
   build round does not start on an assumed flip.
