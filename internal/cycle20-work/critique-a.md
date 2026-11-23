# Cycle 20 — Critique A: the KEY BOUNDARY seat on designs B and C

Seat: critique A (author of design A). Scope: adversarial review of
design B (evidence provenance + operator auth + deploy surface) and
design C (consumption integrity) from the key-boundary perspective,
plus defence / self-adjustment of design A where B's and C's open
questions touch it.

Verdict in one line: B and C are both buildable alongside A, and
neither blocks route 1 — but (i) B's "no version bump" position is
mooted, and partly contradicted, by A's v2 cutover and the two
must land atomically or not claim each other's semantics;
(ii) C's §4.3 API does not match A's §3 API in names, parameter
shape, or pinning model, and one check both designs carry — the
key-id inequality tripwire — is **vacuous as written** under A's
own id derivations; (iii) the combined cycle adds **two** env
vars, not one, so B's 15→16 allowlist cascade is already stale.

Severity key: BLOCKER = must be resolved before the build round
starts; SHOULD-FIX = resolve in the build round, named owner;
NOTE = record it, no code consequence if the wording is right.

---

## 0. Rulings on the mandated interaction questions (summary)

1. **Version bump (§1 of the brief):** A's v2 bump *does* resolve
   B's indistinguishability concern — as a side effect B did not
   design for and B's §1.9 text does not know about. It resolves
   it **only if** B's evidence-resolution semantics are defined
   as part of what "v2" means and both slices land in the same
   flag-day. A v2 envelope minted by an A-only build would still
   carry a caller-asserted `evidence_hash`. See B-1.
2. **Retention vs commit point (§2 of the brief):**
   `authorisation_id` naming survives v2 unchanged in shape and
   computability. The *commit-point definition* does not survive
   B's §1.6 step 7 unexamined: one commit point is still
   definable (the ceremony-journal append), but B now has three
   post-signing writes and two materially different post-commit
   failure states sharing one code. See B-2.
3. **C §4.3 vs A §3 (§3 of the brief):** names, verify-call shape,
   and pinning model all mismatch — precisely itemised in C-1.
   C is right to keep signer-id and key-id as separate pins in
   principle; it is wrong to add a *second* key-id pin beside
   the pinned key object. And the downgraded id-inequality check
   both designs retain can never fire (prefixes differ by
   construction). See C-1, C-2.
4. **Ceremony records (§4 of the brief):** confirmed unaffected.
   Nothing in A's v2 touches `PinCeremonyRecord`, its HMAC, or
   `_check_ceremony_history`. See C-3 (NOTE, confirmation with
   two fixture-level caveats).

---

## 1. Findings on design B

### B-1. BLOCKER — B's no-bump rationale (§1.9, final note) is superseded by A's v2, and the evidence semantics must be *bound into* the v2 definition, not left riding on it implicitly

B states: "no version bump, no payload change. The payload
fields, domain (`signed-ceremony-authorisation-v1`) and
projection are identical… a consumer cannot distinguish a
cycle-19 envelope from a cycle-20 envelope by inspection," and
accepts that the strengthened claim is "an issuance-time,
deployment fact, not an envelope property."

That premise is false in the combined cycle. A §3 bumps, in one
move: domain `signed-ceremony-authorisation-v1` →
`-v2`, payload `"v"` → `"signed-ceremony-authorisation/2"`,
`"alg"` → `"ed25519"`, `"key_id"` → `pub-…`, signature hex64 →
hex128. A v1 envelope is not even *parseable* by cycle-20 code
(A §3, tripwire 3). So at consumption the distinction B says
cannot be made is in fact total: any envelope `reanchor_pin`
can accept in cycle 20 is a v2 envelope.

But — and this is why this is a BLOCKER and not a free win —
the bump was designed to mean *"asymmetric signature"*, not
*"verifier-computed evidence"*. Three consequences B has not
priced:

- **(a) Semantics conflation.** If A lands and B slips (or is
  reverted alone), v2 envelopes exist whose `evidence_hash` is
  caller-asserted in exactly the cycle-19 way, and every
  consumer/docstring that learned "v2 ⇒ verifier-resolved
  evidence" is now overclaiming. Conversely if B lands and A
  slips, B is back to its own §1.9 position (indistinguishable
  v1) — which B accepted but C's §7 sweep and the external
  brief presumably did not. The two slices' claims are
  *conjunctive*: v2 must be *defined* as
  `ed25519 ∧ verifier-computed evidence_hash ∧ (operator claim
  as narrowed in B §2.3)`.
- **(b) Payload-field meaning change at the projection level.**
  In A's payload projection (`ceremony_authorisation_payload`
  in `signing/ceremony_authorisation.py`), `evidence_hash` is
  today — and in A §3's table, still — an opaque parameter the
  projection copies in. Under B §1.5, in a v2 payload that field
  *means* "the SHA-256 the verifier computed over bytes it read
  under `AION_CEREMONY_EVIDENCE_DIR`". **Who enforces that at
  projection level? Nobody can.** The projection is a pure
  function of its arguments; it cannot distinguish a computed
  hash from an asserted one, and neither can
  `sign_ceremony_authorisation`. Enforcement lives exactly
  where B §1.6 puts it — in `_mode_ceremony_authorise`'s order
  (resolution at step 4, sign at step 6 with the *computed
  variable*) — plus code review. That must be said in A's
  module docstring, not only in B's: a reader of
  `ceremony_authorisation.py` alone must not conclude the
  signing module guarantees provenance. A's §4 "semantics that
  must survive" and §1.9-of-B replacement wording both need a
  merged sentence: in v2, `evidence_hash` is *defined* as
  verifier-computed; the definition is discharged by the
  verifier mode, not by the signing module.
- **(c) Test consequence.** Because on the success path
  supplied == computed (B §1.5), *no black-box test can tell
  which variable was passed to the signer* — the envelopes are
  byte-identical either way. B's "code must pass the computed
  variable, never the body value" is therefore unenforceable
  by B's own §3.3 test list. The only pins available are
  (i) the mismatch-refusal tests (which prove comparison
  happens, not which value is signed — though combined with
  "mismatch ⇒ no envelope", a sign-the-assertion bug would
  have to bypass the comparison too), and (ii) a source-level
  assertion / mutation test on `_mode_ceremony_authorise`.
  A's test plan (§5) gains this item; it is not currently in
  either design's list.

**What does *not* change:** B §1.5's decision to keep the 7-key
body is fully compatible with A. The request body is not the
envelope; `evidence_hash` in the *request* stays a caller
assertion used only as a cross-check, `evidence_hash` in the
*v2 payload* is the computed value, and the client echo binding
(A §3, §4) is untouched. No field is added, removed, or resized
in the payload by B — B's grammar tightening (§1.3: ref ≤ 512
chars, segment regex) is a mode-level validation stricter than
the projection's 2000-char cap, which A already treats as
defence-in-depth layering. Compatible, but see B-7 on fixtures.

**Proposed resolution:** (1) Coordinator minutes v2 as the
conjunction above; A and B land in one flag-day commit series
with no releasable intermediate state (the ≤900 s TTL argument
in A §3 already makes a flag-day cheap). (2) B §1.9's
"Envelope-format note" paragraph is deleted and replaced with
one paragraph referencing the v2 definition; its claim wording
is re-checked — as written it says "at issuance, the verifier…",
which is now *also* an envelope property via v2, and may say so.
(3) `signing/ceremony_authorisation.py`'s docstring carries the
"discharged by the verifier mode" sentence in (b). (4) Add the
source/mutation pin in (c) to the combined test plan.

### B-2. SHOULD-FIX — Retention write between the two ledger appends (§1.6 step 7, §1.8): `authorisation_id` naming is stable under v2; the single commit point is definable but B's failure taxonomy collapses two different states into `ledger_failed`

Answering B's own R1 (§4) directly, from A's side:

- **Naming: no collision, no redesign needed.** A §3 keeps
  `authorisation_id_for(payload_hash, key_id)`'s formula —
  `sha256(canonical {"v": DOMAIN, "payload_hash", "key_id"})` —
  with `DOMAIN` now v2 and `key_id` now `pub-…`. The id is still
  hex64, still a pure function of the envelope-to-be, still
  computable *before* signing (payload_hash and the public key
  id are both known pre-signature; no secret participates), and
  therefore known before the journal append, let alone before
  the retained write that B sequences after it. A retained file
  named by a v2 id is a different *string* than the same event
  would have had under v1 — irrelevant, since retention starts
  in cycle 20 and there are no v1 retained files to collide
  with. `O_EXCL` semantics are unchanged. B R1 is closed by A:
  the filename stays a pure function of the envelope.
- **Commit point: still well-defined, but B must define it.**
  B §1.6 step 7 calls the journal append "(commit point,
  unchanged)" and then inserts a write *after* the commit point
  and *before* the signing-ledger append. That makes the commit
  sequence three writes: journal → retained-evidence →
  signing-ledger (+ anchor update, a fourth). One commit point
  remains coherent **iff** the docstring defines it as B
  implies: the journal append is the atomic commit; everything
  after is *completion*, whose failure burns the pair and
  withholds the envelope. But the two post-commit failures are
  not symmetric, and one code (`ledger_failed`) now hides the
  difference an auditor most needs:
  - retained-write fails ⇒ journal-committed, pair burned,
    **no retained evidence and no signing-ledger entry**: the
    audit story of §1.8 ("re-hash the retained copy") is
    impossible for exactly the authorisations that failed
    partway — they exist in the journal only.
  - signing-ledger fails after retention ⇒ journal + retained
    copy exist, ledger entry missing; B §1.8 already (rightly)
    keeps this orphan as "a truthful artefact of a burned
    pair".
  A crash (not a handled failure) between journal and retention
  lands in the first state with no `ledger_failed` ever
  returned. None of this is fatal — cycle 19 already had a
  post-commit failure window — but cycle 19 had *one*
  post-commit write; B doubles it and widens the window while
  claiming the recovery story "applies verbatim". It does not:
  cycle 19's story never had to explain a committed ceremony
  with no evidence artefact.
- **Interaction with A:** none cryptographic. Signing (A §3)
  happens at B's step 6, before all three writes; v2 changes
  no append shape (B R2 / A §6 Q3: `key_id` and signature are
  opaque strings in both ledgers — confirmed from A's side,
  ledger entry *length* grows, shape does not).

**Proposed resolution:** (1) B §1.6/§1.8 and the mode docstring
define "commit point = ceremony-journal append; retained-write
and signing-ledger append are post-commit completion; failure
or crash in completion burns the pair" in those words.
(2) The journal entry (or the `ledger_failed` detail, which is
fixed text — so: the journal entry) should record enough to
distinguish "retention never landed" on audit — minimally,
auditors are told journal-only entries are exactly the
retention-failed/crashed class. If the journal entry shape
cannot grow, minute that limitation instead of discovering it.
(3) Consider — and explicitly reject or accept, don't drift
into — moving retention *before* the journal append: a
pre-commit retained orphan is harmless (named by an id that
was never committed, re-derivable as such), and it would make
"every committed ceremony has its evidence" an invariant
rather than a hope. My recommendation: **move it before the
journal append**; B's stated reason for its position is only
sequencing narrative ("after the commit point"), and the
invariant is worth more. If the coordinator keeps B's order,
resolution (1)+(2) are mandatory.

### B-3. SHOULD-FIX — The fd-walk (§1.4 step 2) is the most complex code in B's design, its strictness is inconsistent at the root, and its operational cost is understated

From the key-boundary seat I care because this helper sits in
the signing process, one step before the seed is used: a bug
here is a bug in the verifier's most sensitive mode.

- **Complexity / failure surface.** Per-component
  `os.open(…, O_NOFOLLOW, dir_fd=…)` traversal is ~8 segments ×
  open/close bookkeeping, with "close every fd on every path"
  as a prose obligation. An fd leak or a double-close in this
  walk is a verifier DoS or worse, and it is exactly the class
  of code the rest of the repo avoids by using `Path` reads.
  B cites `trust/ledger.py`'s `os.open`/`O_DIRECTORY` use as
  in-idiom precedent — that is a *single* open of a known name,
  not a hand-rolled walk. The walk needs its own test family
  (fd-count assertion around success and every refusal leg),
  which appears nowhere in B §3.3.
- **Inconsistency at the root.** Step 1 does
  `Path(config.ceremony_evidence_dir).resolve()` — which
  *follows* symlinks, including a symlinked root and symlinked
  parents — and step 2 then refuses any symlink *below* the
  root. So "any symlink anywhere on the path refuses" (§1.4)
  is not what the design does: it is "any symlink below the
  resolved root". That may be the right policy (roots are
  routinely symlinked mount points — `/var/lib/…` on many
  distro layouts), but the claim wording in §1.9 ("refusing …
  any symlink on the path") overstates the implementation —
  the exact failure mode B §2 exists to eliminate on the
  operator axis.
- **Operational rightness of refusal-on-any-symlink.**
  B §3.2's provisioning story (root copies real files into a
  root-owned 0750 directory) makes the strict rule survivable
  *for the shipped template*. But it also means: no symlinked
  bundle directories from a document store, no symlink-farm
  provisioning, no per-case directory linked from elsewhere —
  each becomes an opaque `ceremony_evidence_unresolvable`
  (deliberately undifferentiated, §1.7), debuggable only by
  inspecting the directory by hand. For a *protected evidence
  dir in a prototype* I accept the strict rule; I do not accept
  it going unflagged in the deploy README as an operational
  constraint, beyond the one template comment B provides.
- **Portability.** `dir_fd` + `O_NOFOLLOW` is POSIX-only. The
  codebase already assumes POSIX (`fcntl`/flock), so this is a
  NOTE for portability, not an objection — but the helper
  should say so, since `verifier_main.py` otherwise reads as
  platform-neutral stdlib.

**Proposed resolution:** keep the fd-walk (the TOCTOU argument
in §1.4 is sound and resolve-then-open would be worse), but:
(1) correct §1.4/§1.9 wording to "any symlink below the
resolved evidence root"; minute the root-resolution exception
as deliberate. (2) Add fd-hygiene tests (open-fd count before/
after, per refusal leg) to B §3.3. (3) Deploy README names
"real files, real subdirectories, no symlinks below the root"
as a provisioning constraint, per B Q4's own docs note.
(4) One-line POSIX note on the helper.

### B-4. SHOULD-FIX — Keeping the caller's `evidence_hash` as a cross-check (§1.5) preserves a caller-assertion channel in form, and B's anti-oracle argument (§1.6 step 3, §1.7) is applied inconsistently

Two distinct attacks; B answers neither head-on.

- **Form vs substance.** B's decisive argument — "a
  caller-supplied value that is *only ever compared, never
  signed* is not an assertion channel" — is true of the *hash
  value* and false of the *evidence selection*. The caller
  still chooses the artifact (via `evidence_ref`) and states
  its hash; the verifier proves the chosen artifact exists
  with that content. Provenance in v2 therefore means
  "verifier-witnessed existence of caller-selected evidence",
  not independent evidence. That is exactly what B §1.9's
  wording claims — good — but B should expect the external
  seats to press the same point they pressed in cycle 19
  ("theatre moved"): the caller-asserted *flavour* survives
  in the selection, and the cross-check's real value is
  accident-detection (stale/wrong bundle), as B itself says.
  From A's seat: the cross-check costs nothing
  cryptographically (the signed value is the computed one —
  subject to B-1(c)'s enforceability caveat) and the 7-key
  stability is worth having. I **support keeping it** — but
  the cycle-20 external brief should present it as
  accident-detection over caller-selected evidence, not as
  the caller being removed from the evidence path.
- **Oracle inconsistency.** B §1.6 step 3 keeps membership
  before resolution so an *unlisted* caller gets no existence
  oracle — sound. B §1.7 then gives all existence/type/symlink
  failures one code "because distinct codes would hand a
  listed operator an enumeration oracle" — and in the same
  table gives oversize its own code and hash-mismatch an
  exit-2 code of its own. A *listed* operator therefore still
  has a three-way oracle per ref: unresolvable (absent /
  wrong type / symlink / empty) vs too_large (exists, big) vs
  mismatch (exists, regular, ≤1 MiB, not the hash you
  guessed) vs issued (exists and hash confirmed). Mismatch in
  particular is a *content-confirmation* oracle: present a
  guessed hash for a ref you cannot read and learn whether
  you guessed the artifact's exact bytes. B's §1.7 rationale
  ("the operator who provisioned the artifact already knows")
  assumes prover == provisioner; the allowlist (§2) names
  *ids any launching caller can present*, so that assumption
  is weaker than B states. Does the mismatch refusal "leak
  anything"? Yes: one bit of existence + one bit of
  hash-confirmation per request, to anyone who can present a
  listed id. In this prototype's same-launch-channel honesty
  model that is acceptable — but it is a *residual to name*,
  not a property the design currently admits while claiming
  oracle-avoidance two paragraphs earlier.
- **Mismatch class.** B makes mismatch exit 2
  (`malformed_request` class) — "the request was well-spelled;
  the world refused" is B's own test for oversize (exit 3),
  and mismatch is equally a world fact (the provisioned bytes
  differ). B's implicit reason is presumably "the caller
  asserted wrongly, so it's the caller's error". Either is
  defensible; the asymmetry with oversize should be argued,
  not silent, because the client surfaces exit 2 and exit 3
  as *different exception types* (`VerifierProtocolError` vs
  `VerifierConfigError`, B §1.7) — a caller catching one will
  mishandle the other.

**Proposed resolution:** (1) Keep the cross-check and the
7-key body. (2) B §1.7 gains a residual sentence naming the
listed-presenter oracle (existence + hash-confirmation) as
accepted under the launch-channel model, and §1.6 step 3's
claim is scoped to *unlisted* callers. (3) Coordinator rules
on mismatch's exit class with the client-exception consequence
stated; my lean: keep exit 2 (it *is* a caller assertion
failure, and retry-with-corrected-hash is a client-correctable
act, unlike oversize), but write that reason down.

### B-5. NOTE — Operator-claim narrowing (§2.2, §2.3): endorsed from the key-boundary seat; one cross-reference to A

B's decision to narrow rather than build the §2.4 token is
correct, and its reasoning (a token held by the launching
process authenticates a process capability, inviting a new
overclaim) is the same shape as A's route-4 analysis (an
attestation of the *claimed* event, not the performed one).
A §4 already records that A's scheme "neither helps nor
hinders" operator authentication; B §2.3 items 3–4 correctly
assign the `ceremony_authorisation.py` / `pin_ceremony.py`
wording edits, and A's build tasks must include them — they
are not in A §5's test plan as a grep gate. **Resolution:**
adopt B §2.3's closing grep gate (`operator authority` → zero
hits outside `internal/`) into the *combined* cycle test plan,
owned by whoever edits each file. If the coordinator overrules
§2.2 and builds the token: note it changes the request body to
8 keys, which does **not** touch A's payload/envelope (the
token is never signed in — B §2.4 is correct on this), but it
*does* invalidate B-1's "7-key stability" argument and must be
decided before, not after, the client work.

### B-6. BLOCKER (coordination) — The combined cycle adds TWO env vars, not one: B's 15→16 cascade (§3.1, §3.3) omits A's ceremony seed variable, and A's design omits the cascade entirely

B §3.1: "Cycle 20 adds exactly one env name… Allowlist count
15 → 16 in all four live copies." A §3 proposes a new,
separate path variable for the ceremony seed (proposed
`AION_CEREMONY_SIGNING_SEED_PATH`), loaded in `_load_config`
and scrubbed like `AION_VERIFIER_KEY_PATH`. A is a second new
name by the same counting B uses. In the combined tree the
count is **15 → 17**, and:

- every test B §3.3 enumerates as pinning "16"
  (`test_allowlist_is_the_shipped_15_names`, the wrapper-length
  assertions, `test_health_check_allowlist_matches_wrapper`,
  the inline set in `test_trust_production_deploy.py`) will
  fail *again* on A's variable if the two slices are built to
  their own designs independently — the cycle-19 14→15 lesson
  A §6 Q1 already cites;
- `test_every_verifier_main_env_var_is_allowlisted` (B §3.3)
  extracts `AION_[A-Z_]+` from `verifier_main.py` — it will
  catch the seed variable the moment A's `_load_config` code
  lands, whichever slice lands second;
- `setup.sh`'s template must gain *both* lines for
  `test_template_keys_equal_allowlist` to pass, and the seed
  line needs the same production-startup treatment: A implies
  but never states whether production refuses startup without
  the seed path. It must (a production verifier that cannot
  sign ceremonies but starts anyway is B §1.2 rule 2's
  "silently dead ceremony" in a second costume). Research mode:
  absent seed ⇒ per-request `ceremony_*_unconfigured`-class
  refusal, mirroring operators/evidence.
- A's `_REFUSED_TEST_KEYS` analogue for the seed (A §3, §6 Q2)
  and B's seed ≠ HMAC provisioning check are verifier-config
  work that sits in B's slice by ownership but appears in
  neither B §3 nor B §3.3's test list.

**Proposed resolution:** coordinator assigns the *combined*
config cascade to one owner (B, as deploy-surface seat) with a
single 15→17 pass: both variables, both template lines, all
four live copies plus the test-side fifth, counts pinned at
17, and the seed variable's startup/per-request refusal
semantics written into B §1.2's pattern (present-malformed ⇒
startup refusal both modes; absent ⇒ production startup
refusal, research per-request refusal). A's §6 Q1 is answered:
yes, seed rotation is a flag-day re-pin of `pub-…` at every
ceremony caller, ratified by the same owner act that provisions
the new seed — one sentence in the deploy README, owned by B.

### B-7. NOTE — Fixture and claim-wording fallout for A's test plan

- B §3.3's fixture rework (real artifact, hash computed in the
  fixture, `"c"*64` retired) applies to every E2E test A §5
  relies on; A's E2E additions (forged-envelope injection,
  seed provisioned through the real loader) must be built on
  B's reworked fixtures, not cycle-19's. Sequencing: B's
  fixture lands first.
- B §1.3's ref grammar invalidates any A-side fixture using a
  URL-shaped or uppercase ref; A has none in its design, but
  the build round should grep before assuming.
- B §1.9's replacement wording ends "…and the binding is
  signed by the verifier's key" — under A this becomes
  "signed by the verifier's ceremony seed (Ed25519)" and the
  honest-limits rewrite in A §4 must merge with B §1.9 rather
  than overwrite it. One merged docstring pass, not two edits
  to the same paragraphs (B §2.3 already lists three files
  where operator wording and evidence wording cohabit).

---

## 2. Findings on design C

### C-1. BLOCKER — C §4.3's API does not match A §3's API: type name, module, parameter names, verify-call shape, and a redundant second key-id pin

C is candid that its names are "placeholders to be reconciled"
(§4.3, §8 Q1) — this finding does the reconciliation, and it is
a BLOCKER because C §6 T11 and the build estimate are written
against the placeholder shape. Precisely:

| Aspect | A §3 (authoritative for the key boundary) | C §4.1/§4.3 (as written) | Ruling |
|---|---|---|---|
| Public-key type | `CeremonyPublicKey`, defined in `signing/ceremony_authorisation.py` (the raw 32-byte primitives live in `signing/ed25519.py`, which exports **no** key-object type — bytes only) | "`authorisation_verify_key` — a public-key-only object of seat A's verify-key type", name and home unspecified | C adopts `CeremonyPublicKey` from `signing.ceremony_authorisation`; there is no verify-key type in `ed25519.py` to import |
| `reanchor_pin` parameter | `authorisation_public_key: CeremonyPublicKey` (A §3, "Ceremony (seat C's implementation, my interface ask)") | `authorisation_verify_key` **plus** `expected_authorisation_key_id: str` | Name: `authorisation_public_key`. Second pin: see below |
| Verify call | `verify_ceremony_authorisation(signed, *, public_key: CeremonyPublicKey, expected_signer_id=…, now=…)` — the pinned key object is passed under the name `public_key`; key-id comparison happens *inside*, against `public_key.key_id` | `verify_ceremony_authorisation(authorisation, verify_key=…, expected_key_id=…, expected_signer_id=…, now=…)` | C's call as written does not type-check against A's signature: wrong keyword (`verify_key`), extra keyword (`expected_key_id`), positional envelope name differs. Rewrite §4.3 step (3) to A's shape |
| Where `unknown_key` arises | envelope `key_id != public_key.key_id` (derived from the pinned bytes) inside verify (A §3) | "an envelope whose `key_id` ≠ the pinned expected id refuses there (`unknown_key`)" — true only under C's two-pin shape | Under A's shape the same refusal exists with one pin; C §6 T11's "wrong `expected_authorisation_key_id`" leg must be re-expressed (below) |

**On the second pin specifically.** C's rationale (§4.3) is
that a caller "cannot be silently re-pointed at a different
verifier key by whoever hands it the key object". Under A's
type that attack already fails: `CeremonyPublicKey.key_id` is
*derived from the public bytes it carries*
(`public_key_id_for`, A §3), and verify compares the envelope's
claimed `key_id` to that derived id. Handing the caller a
different key object hands it a different derived id, and a
genuine envelope refuses (`unknown_key` / signature failure) —
re-pointing produces refusal, exactly as in A §5 test (a). A
separate `expected_authorisation_key_id: str` adds a second
source of truth with **no defined disagreement semantics**:
if `expected_authorisation_key_id != authorisation_verify_key.key_id`,
which refuses, with what message, at which step? C does not
say, because in the placeholder shape the question is
invisible. Two pins that can disagree are a misconfiguration
generator, not defence in depth.

**Signer id vs key id — where C is right.** C §4.3 keeps
`expected_verifier_signer_id` "unchanged and not merged" with
the key pin, because signer identity and key identity are
separate envelope fields. A agrees completely: A §3's ceremony
interface ask is "`authorisation_public_key` plus the unchanged
`expected_verifier_signer_id`", and the client pins
(`expected_signer_id` / `expected_key_id`) are likewise
separate in A §3. So the *principle* "pin key id separately
from signer id" is upheld — it is satisfied by pinning the
`CeremonyPublicKey` object (whose id is inseparable from its
bytes) beside the signer-id string. What is rejected is only
pinning the key id *twice*.

**Proposed resolution:** (1) C §4.1 signature becomes
`…, authorisation_public_key, expected_verifier_signer_id, ceremony_history, …`
— one new parameter replacing `authorisation_key`, not two.
(2) C §4.3 step (3) rewritten to A's verify shape. (3) T11
re-scoped: type refusal (a `SigningKey` passed as
`authorisation_public_key` refuses at step (1)); genuine
envelope + attacker-pinned `CeremonyPublicKey` refuses at
step (3); the "wrong expected id" leg is *deleted* as a
separate case — it is the attacker-pin case, since id and
bytes cannot be varied independently. (4) If the coordinator
nonetheless wants a belt-and-braces string pin (e.g. because a
future caller constructs `CeremonyPublicKey` from
envelope-adjacent bytes), it must be specified as a step-(2)
equality check `expected == authorisation_public_key.key_id`
with its own refusal, *before* verify — and minuted as
guarding caller construction, not key substitution. My
recommendation: don't add it.

### C-2. BLOCKER (shared A+C defect) — The retained key-id inequality check is vacuous under A's id derivations; C's "downgrade to tripwire" (§4.3) and A §3 layer 3 both overstate a check that can never fire

This one is mine as much as C's, and I am adjusting A on the
record here.

A §3 defines: snapshot/HMAC ids as `"key-" + sha256(secret)[:16]`
(existing `key_id_for`), authorisation public ids as
`"pub-" + sha256(public_key)[:16]` (`public_key_id_for`). The
prefixes differ by construction. Therefore
`authorisation_public_key.key_id != signing_key.key_id` — the
"residual id check (defence in depth)" in A §3 layer 3, and
the check C §4.3 retains as a tripwire that "can now only
trigger on a provisioning error" — **is true for every possible
pair of values and can never refuse anything.** A test that
pins it (C §6 T11's separation leg; A §5's "id-collision
refusal") cannot be written to fail-then-pass; it can only
pass, vacuously.

C §4.3 goes further than A in one respect and is right to:
"the same underlying seed used for both an HMAC secret and an
asymmetric private key would produce different ids and pass."
Correct — and stronger than C states: even the *hash inputs*
are incommensurable (secret bytes vs derived public bytes), so
no id comparison in the ceremony process can detect
seed-reuse-across-roles at all. The ceremony holds only the
public key; the equality that matters (ceremony seed bytes ==
any HMAC key bytes) is checkable only where both secrets
exist — **at provisioning, verifier-side** — which is A §3's
*B-side* ask ("provisioning should refuse a ceremony seed
byte-equal to any HMAC key") and B-6 above. The in-process
check is not a weakened tripwire; it is no tripwire.

**Does C's downgrade match A's redefinition?** In direction,
yes: A §3 already redefines separation as (1) type separation,
(2) role separation, (3) residual id check — in that order of
weight — and C §4.3/§7 item 3 correctly promotes the
cryptographic/type-level separation to "the real separation"
and demotes the id check. The mismatch is that both texts
keep layer 3 alive as a *check*. It should be deleted as a
check and kept only as history.

**Proposed resolution (adjusts A §3 and C §4.3/§7 jointly):**
(1) Delete the in-process id-inequality refusal from both
designs; step (2) of `reanchor_pin` becomes the *type* gate
alone (a `SigningKey` in the authorisation slot refuses —
that part of C T11 survives and is the real test).
(2) A §3's "What key separation becomes" loses layer 3 and
gains: "id comparison across the two namespaces is vacuous
(`key-…` vs `pub-…` prefixes, incommensurable hash inputs);
seed-reuse across roles is refused at provisioning by the
verifier (seat B), the only place both secrets exist."
(3) C §7 item 3's replacement docstring text is amended
accordingly — its current sentence ("plus a retained
in-process id-inequality tripwire that refuses gross
misconfiguration") must not ship. (4) C §8 Q3 is answered:
the derivations are domain-separated by prefix and by input,
stated here and to be stated in A's module docstring.

### C-3. NOTE (confirmation, as briefed) — A's v2 does not affect ceremony records or their verification; two fixture-level caveats

Confirmed, with the reasoning on the record so the build round
does not re-litigate it:

- `PinCeremonyRecord`'s MAC is HMAC under the **snapshot**
  `SigningKey`, in the record/`gate_decision` MAC world whose
  `ALG` stays `"hmac-sha256"` — A §3 explicitly scopes this
  out ("that constant stays… for the gate/attestation/record
  MACs, which are out of scope and unchanged"), and C §4.3's
  "what does NOT change" agrees. `_check_ceremony_history`
  verifies records via that MAC and is untouched by anything
  in A: no domain string, payload projection, or key in the
  record path is shared with the ceremony-authorisation path.
  The two domains (`signed-ceremony-authorisation-v2` vs the
  record MAC's domain) are distinct strings; there is no
  cross-verification surface to contaminate.
- The record *carries* `authorisation_id` as a required field
  (A §4). Under v2 the carried value is derived from different
  inputs (v2 domain, `pub-…` id) but is the same shape (hex64)
  and is opaque to record verification — C §4.3's "only the
  record's carried value changes here, opaquely" is exactly
  right. C §8 Q2 is answered: A keeps the envelope field name
  `signature` (value becomes hex128) and changes
  `authorisation_id` only through its derivation inputs;
  step-(4) exact binding in `reanchor_pin` reads neither the
  signature nor the derivation — **no step-(4) impact**.

Caveats (fixtures, not semantics): (i) any test fixture or
golden file that hardcodes a cycle-19 `authorisation_id` or a
hex64 `signature` will fail under v2 and must be regenerated —
this lands in C's files (`test_signing_pin_ceremony.py`) as
much as A's; (ii) C §3.1's list of what a verified history
refuses is unchanged, but T10's "pass unchanged" re-run will
in fact run against v2-minted envelopes in the E2E file — the
*records* are unchanged, the envelopes feeding them are not;
the build round should not be surprised by E2E churn there.

### C-4. SHOULD-FIX — C's "fail-closed" headline (§3.1, §3.2) overstates what the required-history contract closes: for `chain_gap_recovery` the no-history replay survives transmuted into an empty-history replay

C is admirably honest in §5 and §3.3 leg 3 — the stale-history
residual is named, pinned by T7/T8, and never claimed closed.
The problem is the *headline* text a skimming reviewer (or the
BUILD record, or the external brief) will quote:

- §3.1: "**Does requiring it kill the documented no-history
  replay? Yes — that exact case dies.**" True only of the
  *syntactic* case (parameter omitted / `None`). For
  `chain_gap_recovery` — the ceremony's primary use case —
  §3.2 expressly allows an empty history, and an empty history
  is *truthful* before the first consumption and *stale* after
  it, with nothing in-process able to tell the two apart
  (C §5 says exactly this). So the documented attack — "same
  envelope twice within TTL succeeds" — still succeeds, by
  supplying `()` twice instead of omitting the parameter
  twice. The hole changed shape from *omission* to *assertion*;
  for a first ceremony it did not close. C §3.2's defence
  ("empty is now an explicit caller assertion… where a
  reviewer can hold the caller to it") is a *reviewability*
  gain, not a consumption-integrity gain, and §3.1's "Yes"
  elides the distinction C itself draws in §4.2
  (COMPLETE-HISTORY is "unverifiable in-process").
- This matters beyond wording: C §8 Q7/Q8 correctly warn the
  coordinator not to schedule cycles 14–16 re-review on a
  full-closure claim. If §3.1's "Yes" reaches the external
  brief unqualified, that warning is undercut by C's own text.
  Gemini's demand was "fail-closed if state/history
  continuity cannot be verified" — under the empty-history
  leg, continuity *cannot* be verified (an assertion is not
  verification) and consumption does *not* fail. The design
  implements the weaker reading and §3.2 does say so ("the
  demand's stronger reading… is not implementable
  in-process") — that sentence belongs in §3.1 next to the
  "Yes", not two sections later.

**Proposed resolution:** wording only — the mechanism is the
best available in-process and I do not propose changing it.
(1) §3.1's answer becomes: "It kills the *omitted-history*
case. The same replay against an explicitly empty history —
admissible for a first `chain_gap_recovery` — succeeds and is
the §5 residual." (2) Every use of "fail-closed" in C §3 is
qualified as "fail-closed on omission" at first use.
(3) The BUILD-CYCLE-20 record and external brief must carry
C §8 Q8's sentence (met for no-history, unmet for
stale/empty-history) verbatim. With those edits, C's claim
posture matches A's: A §6 Q4 makes the identical point for
route 1 (genuine-envelope replay within TTL is C's F1,
unchanged by unforgeability) — the two designs agree on the
residual; only the headline needs to stop sounding like
closure.

### C-5. SHOULD-FIX — `initial_anchor` empty-only (§3.2): the escape hatch works, but two edge cases need explicit answers before the build

C's rule — non-empty verified history ⇒ `initial_anchor`
refuses, pointing at `lost_pin` — kills a real laundering
path (second bootstrap past the head) and I support it. From
the consumption/key seam, two edges are unexamined:

- **(a) Reason is chosen at issuance, not consumption.** The
  envelope binds the reason (A §4: reason allowlist + binding
  unchanged). A caller who mints an `initial_anchor` envelope
  and *then* discovers a non-empty history (store recovered,
  history partition found) holds an envelope that can never
  consume: the fix is a *new issuance* under `lost_pin`,
  which burns a new `(ceremony_id, evidence_hash)` pair at
  the verifier — and evidence is single-use at issuance
  (B §1.6 step 5 keys reuse on the computed hash), so the
  caller also needs a *new evidence bundle* for the retry.
  That is survivable but it is a real operational cost the
  design never mentions, and it will present as "the ceremony
  deadlocked" to the first operator who hits it. The refusal
  message pointing at `lost_pin` (C §3.2) should also say a
  new authorisation (and evidence) is required — the current
  envelope cannot be re-reasoned.
- **(b) Irrelevant-history deadlock.** Empty-only refuses on
  *any* non-empty verified history, including one whose
  records belong to a different snapshot lineage / a fork the
  generic checks would themselves refuse or ignore. Is there
  a deployment state where history is non-empty, the pin is
  genuinely absent, *and* `lost_pin` is unavailable as a
  reason (e.g. a caller whose policy layer permits only
  `initial_anchor` for a fresh store)? C's table makes
  `lost_pin` admissible with any history, so the *function*
  never deadlocks — but a *caller policy* that pre-commits to
  `initial_anchor` for "new store" and discovers the shared
  history is non-empty has no path that doesn't cross a
  reason boundary it defined for itself. That is arguably
  correct behaviour (the premise "initial" was false), and I
  do not propose a bypass — a bypass *is* the laundering path.
  It needs one docstring sentence so a future war room does
  not "fix" it: "`initial_anchor` refusing on any non-empty
  history, including unrelated-lineage history, is
  deliberate; the recovery is a `lost_pin` authorisation,
  not a history edit."
- A third, smaller edge: `initial_anchor` with a history
  containing only records that *fail* verification — the
  generic check refuses first ("an unverifiable history
  establishes nothing"), so empty-only never gets to speak;
  ordering at the §4.1 call site (empty-only "immediately
  before the generic check") means the empty-only message
  fires on a *verified-non-empty* history only if the check
  order is: presence → … → empty-only → generic verify. If
  generic verification runs first inside
  `_check_ceremony_history`, a tampered non-empty history
  refuses with the generic message — fine — but C should
  state which message a *verified* non-empty history gets
  (empty-only's, per its ordering sentence) and pin it in T4.

**Proposed resolution:** adopt the rule unchanged; add the
two docstring/message sentences in (a) and (b); state the
message-ordering in §4.1 and assert it in T4. No mechanism
change.

### C-6. NOTE — Points where C changes A's test plan or format decisions (consolidated with B-7)

- **Caller-break accounting doubles.** A §6 Q5 warns that the
  `authorisation_key` rename is a hard break for every caller
  and the one test helper funnelling 43 calls. C §4.1 adds a
  *second* hard break in the same signature
  (`ceremony_history` loses its default) plus, per C-1, the
  parameter is renamed once, not twice. The recount A asks for
  must be done once, against the *combined* new signature, and
  C §6's helper strategy (explicit `ceremony_history=()` in
  the helper only) is the right funnel — adopt it for the
  key parameter too (helper passes a fixed test
  `CeremonyPublicKey`), so the 43-call surface changes in one
  place.
- **A §5 test (c) gains a sibling.** A's no-HMAC-fallback
  tests pin the envelope side; C T1 (signature pin:
  omitting `ceremony_history` raises `TypeError`) pins the
  consumption side's no-silent-default property. Both belong
  to the same "no silent fallback" family and should be
  listed together in the cycle record.
- **A §3's optional client-side verify (A §6 Q8) interacts
  with C-1's ruling.** If the room adopts client-side
  verification, the client needs the pinned `CeremonyPublicKey`
  — the same single-pin model as C-1's resolution; under C's
  two-pin shape the client would have needed a third
  representation of the same pin. The C-1 ruling (one pin, the
  object) makes Q8 cheaper to adopt. My lean in A was adopt;
  C's design gives no reason to change it, and the coordinator
  decision (below) should be taken with C-1 settled first.
- **No format impact from C on A.** C changes no envelope
  field, no payload projection, no derivation (C §4.3,
  confirmed in C-3). A's format decisions stand as designed.

### C-7. NOTE — C §7.1(b) hands B a wording duty that B has already (mostly) discharged; one phrase in A needs the same fix

C §7.1(b) requires B's "single-use" mentions to carry their
issuance scope, and flags `ceremony_authorisation.py`'s
phrase "bound to one event, and burned on use" as wrong
("burned at **issuance**; consumption burns nothing"). That
phrase is in *A's* module. Conceded and adopted into A's
build tasks verbatim: the honest-limits rewrite in A §4 must
include C's correction, alongside B-5's operator grep gate
and B-1's evidence-definition sentence. Three seats' wording
edits converge on the same two docstrings
(`ceremony_authorisation.py`, `pin_ceremony.py`); the build
round should assign each file's docstring to **one** editor
with all three lists in hand, or the edits will conflict.

---

## 3. Defence of design A, where B/C open questions touch it

- **B R2 (§4):** confirmed — evidence resolution is entirely
  pre-signing and independent of HMAC-vs-Ed25519; if A's claim
  wording for the signature clause differs from B §1.9's
  "signed by the verifier's key", A's wording governs that
  clause (see B-7).
- **B R1:** answered in B-2 — naming stable, formula unchanged
  in shape, id computable pre-commit.
- **B Q2 / external brief:** A supports B §2.2's sentence
  going into the brief verbatim ("evidence: fixed; operator
  auth: claim narrowed, layer still missing"), and adds A's
  parallel sentence: "key boundary: fixed (minting);
  consumption replay: narrowed, still open (C §5)."
- **C §8 Q1:** type is `CeremonyPublicKey` in
  `signing/ceremony_authorisation.py`; `public_key_id_for`
  derivation per A §3; reason vocabulary unchanged
  (`unknown_key` = pinned-id mismatch, `signature_mismatch` =
  Ed25519 failure) — C's assumptions hold once C-1's call
  shape is adopted.
- **C §8 Q2:** answered in C-3 — field name `signature` kept,
  `authorisation_id` inputs change (domain + key id), no
  step-(4) impact.
- **C §8 Q3:** answered in C-2 — derivations are
  domain-separated by prefix and input; the consequence is
  that the cross-namespace id check is vacuous, which cuts
  against both designs' layer-3/tripwire text, not against
  the separation itself (type + role separation, A §3 layers
  1–2, is the separation, and it is intact).
- **C §4.3 fallback paragraph:** endorsed. If A does not land,
  C stands alone with the HMAC parameter retained — and
  symmetrically, A stands alone if C slips: unforgeability
  does not depend on mandatory history. Neither seat holds
  the other hostage; the *claims* are conjunctive (B-1), the
  *mechanisms* are independent. That asymmetry should be
  minuted so a partial landing is described honestly.

---

## 4. Decisions needed from the coordinator

1. **v2 semantics + atomic landing (B-1):** minute v2 as
   `ed25519 ∧ verifier-computed evidence_hash ∧ narrowed
   operator claim`; rule that A and B land in one flag-day
   with no releasable intermediate, or explicitly accept the
   weaker per-slice claims if they land separately.
2. **Retention position (B-2):** move the retained-evidence
   write *before* the ceremony-journal append (my
   recommendation — "every committed ceremony has its
   evidence" becomes an invariant), or keep B's order with
   the commit/completion definition and journal-only-class
   audit note as mandatory docstring text.
3. **Combined allowlist cascade (B-6):** assign one owner
   (proposed: B) for a single 15→17 pass covering both
   `AION_CEREMONY_EVIDENCE_DIR` and
   `AION_CEREMONY_SIGNING_SEED_PATH`, including the seed
   variable's production-startup / research-per-request
   refusal semantics and the seed `_REFUSED_TEST_KEYS`
   analogue + seed≠HMAC provisioning refusal.
4. **Single-pin model (C-1):** ratify
   `authorisation_public_key: CeremonyPublicKey` as the only
   key pin in `reanchor_pin` (beside the unchanged
   `expected_verifier_signer_id`), with C §4.3/T11 rewritten
   to A's verify-call shape — or, if a redundant string pin
   is wanted, specify its disagreement semantics as in C-1(4).
5. **Delete the vacuous id-inequality check (C-2):** ratify
   removing it from both designs, with seed-reuse protection
   assigned to verifier-side provisioning (decision 3's
   owner), and the amended docstring sentence in C §7 item 3.
6. **Mismatch exit class (B-4):** exit 2 (my lean, as a
   caller-assertion failure) or exit 3 (world-refusal
   symmetry with oversize) — with the client exception-type
   consequence stated in the ruling.
7. **Client-side signature verification (A §6 Q8, C-6):**
   adopt or drop, after decision 4 (the single-pin model
   makes adoption a one-call change in the client).
8. **Claim-wording custody (B-5, C-4, C-7):** rule that the
   cycle record and external brief carry (a) B §2.2's
   operator sentence, (b) C §8 Q8's stale-history sentence,
   and (c) B-1's v2 conjunction, verbatim; and assign each
   shared docstring (`ceremony_authorisation.py`,
   `pin_ceremony.py`, `verifier_main.py`) a single editor
   holding all three seats' wording lists.
