# Critique B — Cycle 20 design round (seat B: verifier mode / config / evidence)

Author: critique seat B (author of design-b; defending/adjusting it
where A and C touch it, attacking where they are weak).
Inputs: design-a.md (pure-Python Ed25519 key boundary), design-b.md
(evidence provenance / operator claim / config surface), design-c.md
(consumption integrity), plus grep/read verification against the
live tree: `trust/verifier_main.py` (`_load_config`,
`_REFUSED_TEST_KEYS`, `_mode_ceremony_authorise`),
`trust/wiring.py`, `trust/client.py`, `trust/ledger.py`,
`signing/ceremony_authorisation.py`, `signing/gate_decision.py`
(`key_id_for`, `_check_id`), and all four allowlist copies in
`deploy/verifier-identity/`.

Severity key: BLOCKER = build must not start / claim must not ship
until resolved. SHOULD-FIX = resolve in the build round, design
intent stands. NOTE = record it; no design change required.

---

## Part 1 — Critique of design A (key boundary)

### A-1. BLOCKER — The ceremony seed is a second verifier secret, and A leaves its entire config lifecycle to "seat B" in one sentence (A §3, §6 Q1–Q2)

A §3 proposes `AION_CEREMONY_SIGNING_SEED_PATH` and A §6 Q1/Q2 ask
me to confirm provisioning, rotation, `_REFUSED_TEST_KEYS` analogue
and the seed≠HMAC check. Verified against `_load_config`'s actual
philosophy, here is the specification A left unspecified. This is
now part of design-b; the build implements *this*, not A's sketch
alone.

**A-1a. It cannot ride an existing name; the allowlist goes
15 → 17, not 16.** `AION_VERIFIER_KEY_PATH` names exactly one
file, loaded as the HMAC `SigningKey` every mode uses. A seed
file is a different format (32-byte Ed25519 seed via A's
`load_ceremony_seed`) and a different role; overloading the path
would make one path mean two keys. So cycle 20 adds **two** new
allowlist names, not one: design-b §1.2/§3.1's
`AION_CEREMONY_EVIDENCE_DIR` (15→16) **and**
`AION_CEREMONY_SIGNING_SEED_PATH` (16→17). Every figure in
design-b §3 that says "16" is superseded by "17" in the combined
tree (see B-1 below), and A §6 Q1's passing reference to "the
cycle-19 14→15 lesson" understates it: this is a 15→17 jump in
one cycle, in all four live copies plus the test-side fifth copy
(design-b §3.1/§3.3), landing atomically — a tree with only one
of the two names added fails
`test_every_verifier_main_env_var_is_allowlisted` and the
template-equality tests, correctly.

**A-1b. Parsing and fail-closed rules (mirroring the two existing
precedents, deliberately split).** `_load_config` today has two
philosophies and the seed must follow both, each where it
applies:

- *Core-key philosophy* (`AION_VERIFIER_KEY_PATH`): absolute-path
  form check at startup; load through the disciplined loader;
  any `SigningError` → startup exit 3 `verifier_misconfigured`
  with a detail that names the failure class and never the path
  or value ("signing key is missing or unsafe"); refused-test-key
  check at startup; path scrubbed from the environment after
  load (`env.pop`).
- *Ceremony-config philosophy* (`AION_CEREMONY_OPERATORS`,
  design-b §1.2): malformed refuses startup in **both** modes;
  absent in **production** refuses startup; absent in
  **research** loads as unconfigured and the *mode* refuses
  per-request, so the rest of the verifier still runs.

  Applied to the seed, concretely:
  1. Present value must be a non-empty absolute path, both
     modes, else startup `verifier_misconfigured`. No strip, no
     normalise — the deployment-mode stance.
  2. **Production + absent/empty → startup refusal** (exit 3,
     `verifier_misconfigured`, "production mode requires
     AION_CEREMONY_SIGNING_SEED_PATH"). Justification is
     design-b §1.2 rule 2 verbatim: it is a deployment fact,
     knowable before any request, and cycle 19 already accepted
     that a production verifier refuses to start at all over
     missing ceremony protective config.
  3. **Research + absent/empty → `_Config` carries `None`;**
     `_mode_ceremony_authorise` refuses per-request with a new
     exit-3 code `ceremony_seed_unconfigured` (parallel to
     design-b's `ceremony_evidence_unconfigured` and the
     existing `ceremony_operators_unconfigured`), checked in
     design-b §1.6 step 1 with the other config gates, before
     body validation. Research keeps its "verifier runs,
     ceremony disabled" property.
  4. **Present but unloadable in either mode → startup refusal,**
     not per-request: file missing, not 0600, symlink component,
     not exactly 32 bytes of lowercase hex, loader
     `SigningError` — all collapse to startup
     `verifier_misconfigured`, "ceremony signing seed is missing
     or unsafe", exactly the HMAC line's shape. A *configured
     but broken* seed is a misdeployment, not a runtime
     condition; deferring it to per-request would let a
     production verifier serve gate/attestation indefinitely
     with a silently dead ceremony — the failure design-b §1.2
     rule 2(b) already rejected for the evidence dir.
  5. Load order in `_load_config`: after the HMAC key load and
     its refused-test check (so a broken core key reports
     first — deterministic error precedence, docstring order),
     before TTL/anchor parsing is *not* required; but the seed
     path is scrubbed (`env.pop`) immediately after its load,
     beside the existing pop, so no later code or child can
     re-read the path from the environment.
  6. `_Config` gains `ceremony_signing_key:
     CeremonySigningKey | None` beside `ceremony_operators`;
     no other mode reads it. Gate / sealed_eval /
     issue_attestation behaviour in research with the seed
     absent is byte-identical to today.

**A-1c. The HMAC key remains — this is a second key, and startup
must check the pair, not each key alone.** A §3 is correct that
the verifier keeps its HMAC `SigningKey` for every other mode
(`ALG_CEREMONY = "ed25519"` is ceremony-only;
`gate_decision.ALG` stays `"hmac-sha256"`). Consequences A does
not state:
  - `_load_config` now holds *two* secrets and must refuse a
    seed **byte-equal to the HMAC signing key** at startup
    (`verifier_misconfigured`, detail names neither value).
    Comparing `key_id`s cannot do this check: the HMAC id is
    `"key-" + sha256(secret)[:16]`, A's public id is
    `"pub-" + sha256(public_key)[:16]` — different prefixes over
    different inputs, so byte-equal secrets produce *unequal*
    ids and an id comparison passes a fully collapsed key
    boundary. The comparison must be over the raw bytes, in
    `_load_config`, the one place both secrets exist. (A §3's
    "provisioning should refuse" is too weak and too late:
    provisioning is a human act; `_load_config` is the
    enforcement point, same as `_REFUSED_TEST_KEYS`.)
  - The same byte-equality check should cover the seed against
    the snapshot/ceremony HMAC keys *at consumption* — that half
    is seat C's tripwire problem (see C-3), because the verifier
    never sees the snapshot key.
  - On the `key_id` *collision* question as posed: a derived
    `pub-…` id **cannot** collide with the HMAC verifier
    `key_id` or a snapshot `key_id` as strings — the `pub-` /
    `key-` prefixes are disjoint and both pass `_check_id`
    (`^[a-z0-9_-]{1,64}$` in `gate_decision.py`; `pub-` + 16 hex
    = 20 chars). It also cannot collide with the *snapshot*
    key's id for the same reason. What it *can* collide with is
    another Ed25519 public key's id (16 hex chars of SHA-256 —
    the same truncation every key id in this repo already
    accepts). No new rule needed; do not let the build invent
    one. But see C-3: the prefix disjointness silently neuters
    the retained id-equality tripwire in A §3 layer 3 / C §4.3.

**A-1d. Refused-test-key discipline for seeds — A's analogue is
under-specified in a dangerous direction.** `_REFUSED_TEST_KEYS`
today is four publicly predictable byte strings
(`bytes(range(32))`, `bytes(range(32,64))`, `0x00*32`, `0xff*32`).
For seeds the analogue `_REFUSED_TEST_SEEDS` must contain those
four **interpreted as seeds**, *plus every seed that appears in
A's own test plan*: A §5 pins RFC 8032 §7.1 TEST 1–3 as literal
constants, and the TEST 1 seed (`9d61…7f60`) is public knowledge
— a production verifier provisioned with it is a verifier anyone
can mint for. Any seed used in any committed fixture, vector or
E2E helper joins the refused list in the same commit that adds
the fixture, or the fixture uses a seed generated per-run and
never committed. E2E fixtures must provision through the real
loader from a per-run generated seed file (A §5 already demands
the real loader; this adds: never a literal). Test for the test:
a unit case asserting each RFC vector seed refuses at
`_load_config`.

**A-1e. setup.sh, health_check, migration (design-b §3.2 cascade,
extended).**
  - setup.sh template gains, in the keys block:
    `AION_CEREMONY_SIGNING_SEED_PATH=/var/lib/aion-verifier/keys/ceremony.seed`
    with a comment stating: provisioned by the operator with
    `generate_ceremony_key_file` (never generated silently by
    setup.sh — a setup script that mints the minting key
    unattended hides the provisioning act the whole design
    exists to make deliberate); 0600, `aion-verifier`-owned,
    beside `gate.key` in the existing 0700 keys directory (no
    new directory needed — contrast design-b §3.2's evidence
    directory, which *does* need one); and the derived public
    key id (`pub-…`) must be recorded at provisioning time,
    because it is the value every ceremony caller pins.
  - health_check gains: (a) the allowlist copy (A-1a);
    (b) a production env-file FAIL for missing/non-absolute
    seed path, mirroring design-b §3.1 item 3(a) for the
    evidence dir; (c) *if* the value is the canonical path,
    existence + 0600 + owner check on the file. health_check
    must **not** read the seed bytes or derive the public key —
    a checker that opens the minting secret widens its
    exposure for a check (id-vs-pin) that belongs to the
    ceremony caller's pin, not to deployment health.
  - Migration note (extends design-b §3.2's F6-style note; the
    cycle-20 note must carry **both** new variables in one
    paragraph): existing production deployments must provision
    a ceremony seed, distribute its `pub-…` pin to ceremony
    callers, *and* set/provision the evidence dir, or the
    verifier refuses to start after upgrade. Two startup
    refusals landing in one upgrade is exactly why the note
    must be one combined, owner-visible procedure (A §6 Q1's
    rotation question) — including that seed rotation is the
    same act: new seed → new `pub-…` pin everywhere → all
    in-flight envelopes dead within 900 s (see A-2).

*Proposed resolution:* adopt A-1a–A-1e as design-b §3.5 (new).
A's route recommendation is unaffected; its §3 interface ask is
accepted with this config contract attached.

### A-2. SHOULD-FIX — Flag-day cutover: A's "strands at most 15 minutes" understates the operational cost; a drain procedure is required (A §3, "Retiring the HMAC path")

A's four tripwires are sound and I endorse **no dual-verify
window** — a dual window is the silent fallback, as A says. But
the cutover sentence ("v1 envelopes live at most 900 s, so a
flag-day switch strands at most 15 minutes of in-flight
authorisations") is true only about envelope *lifetimes*. It
omits three operational facts from my seat:

1. **A stranded ceremony cannot simply be re-issued.** A v1
   envelope that was issued and not yet consumed has already
   burned its `(ceremony_id, evidence_hash)` pair in the
   ceremony journal (issuance is the commit point). After the
   upgrade its envelope is unparseable by cycle-20 code
   (hex128 check, A tripwire 3). Re-running the ceremony needs
   a **new ceremony_id and a new evidence bundle** — and under
   design-b §1, a new bundle means a newly provisioned artifact
   under the evidence dir whose hash differs. That is doable
   (the pin has not moved; the recovery story is cycle 19's),
   but it is an operator procedure, not a 15-minute wait.
2. **The version skew is three-sided, not one.** Verifier
   (subprocess, env-file driven), client (`_check_pins` now
   expects a `pub-…` id) and in-process ceremony code must all
   flip together. An old ceremony binary consuming a v2
   envelope fails just as hard in the other direction. There is
   no rolling upgrade; the deploy is a coordinated swap.
3. **The tests will not catch a botched cutover.** The verifier
   mode tests and the E2E suite drive the real subprocess from
   per-run fixtures — every process in a test run is the same
   version, so the suite is green before, during and after a
   mis-sequenced production swap. This is a deployment hazard
   that only an ops procedure covers, which is precisely my
   slice.

*Proposed resolution:* flag-day is acceptable **only** with a
drain procedure added to the deployment README / ops note in
the same cycle: (i) stop issuing new ceremony authorisations;
(ii) wait ≥ 900 s (the hard TTL cap) so every outstanding v1
envelope has either been consumed or expired; (iii) confirm no
ceremony is mid-flight (issued, unconsumed) — if one is,
consume it or formally abandon it knowing re-issue needs a new
ceremony_id + new evidence bundle; (iv) swap verifier env +
code, client pins and ceremony code in one act; (v) provision
the seed and distribute the `pub-…` pin *before* the swap, so
step (iv) is a switch, not a provisioning session. Without
(i)–(iii) in writing, this is a BLOCKER for the deployment
(not for the code).

### A-3. BLOCKER — A's strict-verification profile is named inconsistently and its check list is incomplete as an implementable spec (A §1 "Verification strictness", §6 Q6)

A §1 commits to: reject `S ≥ L`; reject non-canonical point
encodings (`y ≥ q`, re-encode equality); reject small-order `A`
and `R` via "the 8 known small-order encodings, or equivalently
…"; cofactorless equation; signature exactly 64 bytes. A §6 Q6
calls the same profile "canonical-encoding + small-order
rejection + cofactorless equation (strict)" and
"ZIP-215-minus". Problems:

- **The blocklist is not enumerated.** "The 8 known small-order
  encodings" is prose, not a spec: the build seat will fetch a
  list from memory, and a list from memory is how one encoding
  (typically a non-canonical variant) goes missing. The design
  must pin the literal list as test constants in
  `tests/test_signing_ed25519.py` *in the design's terms* —
  every small-order point encoding the verifier rejects,
  asserted one by one. This interacts with check **order**,
  which A never specifies: if canonical-encoding rejection runs
  *first* (decoded point re-encodes byte-identically, `y < q`),
  the non-canonical variants of small-order points are already
  dead and the canonical 8-entry list suffices; if the blocklist
  runs on raw bytes first, the list must also carry the
  non-canonical spellings. *Resolution:* specify the order —
  length → canonical decode of `A` and `R` (reject on any
  decode failure; `verify` never raises, per A's own API sketch)
  → small-order blocklist on the canonical encodings →
  `S < L` → cofactorless equation — and pin the 8 canonical
  encodings as literals.
- **Cofactorless vs cofactored must be stated as a deliberate
  divergence from RFC 8032's permissive reading, with the
  reason A actually has.** RFC 8032 verification (and ZIP-215)
  accept signatures the strict cofactorless profile rejects.
  Does the divergence matter when signer and verifier are both
  ours? **For interop, no** — and A should say so as the
  argument, not leave it as a worry: there is exactly one
  signer (the verifier, deterministic RFC 8032) and every
  verifier of these envelopes runs this same module (ceremony,
  and the client if A §3 Q8 is adopted). An honestly produced
  RFC 8032 signature satisfies the plain group equation
  `[S]B = R + [H(R‖A‖M)]A` exactly, so strict verification
  accepts 100% of our own signatures — the property to pin with
  A §5's 50 round-trips plus the RFC vectors, all of which must
  pass the *strict* path, not a test-only lax one. Where
  divergence *would* matter — a future external Ed25519 stack
  verifying ceremony envelopes — no such consumer exists or is
  planned, and if one appears, permissiveness is a one-line
  policy change while malleability accepted today is not
  retractable. Strict is the safe profile; ratify it as:
  **canonical encodings, small-order rejection, `S < L`,
  cofactorless equation — call it "strict RFC 8032", drop the
  "ZIP-215-minus" label**, which invites a reader to implement
  ZIP-215 and subtract vibes.
- **Missing checks A must add explicitly:** point decoding must
  reject encodings that do not decode to a curve point at all
  (not merely `y ≥ q`); the identity encoding must be in the
  blocklist by name (A §5's test list mentions it — promote it
  to the §1 spec); and `verify` returning `False` rather than
  raising on *every* malformed input (wrong-length public key
  included) must hold at the `ed25519.py` boundary, not only in
  the envelope layer.

*Proposed resolution:* A amends §1/§6 Q6 with the ordered check
list, the literal blocklist commitment, and the one-signer
argument above; coordinator ratifies the strict profile in the
design round (A §6 Q6 asks for exactly this ratification).

### A-4. NOTE — The 8.9 ms benchmark is an order-of-magnitude result, not a number to quote (A §1, performance table)

Measured on this VM: 1.5 *shared* vCPUs, n=30, no variance, p95
or load figures, CPython 3.12.3. Shared-CPU timings here move by
multiples under neighbour load; 8.9 ms could be 30 ms on a bad
minute and the design conclusion would be identical, because the
only comparison that matters is (a) vs the 278 ms affine form
(~30×, robust to noise) and (b) vs the subprocess spawn the flow
already pays per request. A §5's loose perf guard (< 1 s) is
exactly the right epistemic level. *Resolution:* the BUILD
record and any doc may cite "≈10 ms class, ~30× faster than the
affine reference, measured on the build VM" and must not cite
8.9 ms as a bound; the build round re-measures with median +
p95 over n≥100 and records both. No design change.

### A-5. NOTE — Ledger/journal shape under A: confirmed no change (answering A §6 Q3)

A §6 Q3 asks me to confirm against
`SigningLedger.append_ceremony_authorisation`. Confirmed from
the code: the signing-ledger entry stores `decision_id =
authorisation_id`, `payload_hash`, `proposal_id = ceremony_id`,
`signer_id`, purpose and format — **the signature itself is not
a ledger field**, and both ids remain hex64-shaped strings
under A (`payload_hash` unchanged; `authorisation_id` still a
SHA-256 hex). The ceremony journal
(`CeremonyAuthorisationLedger`) stores `ceremony_id` /
`evidence_hash`. `key_id` becoming `pub-…` and the signature
becoming hex128 therefore change **no** ledger or journal
shape, no `EXTRA_KEYS`, no migration. The one place signature
length lives is the envelope dict itself (A's `from_dict`
hex128 check) and retained envelopes on disk, if any.

### A-6. SHOULD-FIX — Client-side signature verification (A §3 Q8) changes design-b's "client contract unchanged" claim; decide it now, not in the build

Design-b §1.5/§3.3 states the client contract is unchanged and
the `fake_verifier_echo` client test is unaffected. That is true
of design-b alone and of A's core change. If the room adopts
A §3 Q8 (client verifies the Ed25519 signature itself using the
pinned `CeremonyPublicKey`), the client's `ceremony_authorise`
gains a real verification step, its "key-free structural
checks" contract changes, and the fake-echo fixture must either
produce genuine Ed25519 signatures or the client must be
test-configured without the public key — the latter reintroduces
a mode where verification silently does not happen. My lean
matches A's (adopt: it is the same `verify_ceremony_authorisation`
call, and fail-fast at the client catches a mis-pinned key
before the envelope reaches a ceremony), *provided* the public
key is a required constructor pin whenever ceremony use is
configured — no optional-verify flag. *Resolution:* coordinator
decides Q8 in the design round; design-b §3.3's client line is
amended either way so the build seat does not discover the
decision in a failing fixture.

---

## Part 2 — Design B self-defence / adjustments (where A and C touch it)

### B-1. Adjustment (accepted, mine to fix) — Allowlist arithmetic in design-b §3 is superseded by the combined tree

Design-b §3 counts only its own variable: 15 → 16. With A's
seed (A-1a) the combined cycle-20 count is **15 → 17**, and if
the coordinator overrules design-b §2.2 and activates the §2.4
token appendix, **15 → 18** — design-b §2.4's own sentence
("this is a 17th allowlist name … 15 → 17 across two cycles")
is wrong in a tree that also carries the evidence dir and the
seed, and must not be quoted by the build seat. Every "16" in
design-b §3.1/§3.3 (wiring test rename `…_16_names`, `len == 16`
assertions, health-check count, the production-deploy inline
`allowlisted` set) becomes 17; the renamed wiring test is
`test_allowlist_is_the_shipped_17_names`. The four live copies
plus the test-side fifth copy gain both names in the ceremony
block, in docstring order: `AION_CEREMONY_OPERATORS`,
`AION_CEREMONY_EVIDENCE_DIR`, `AION_CEREMONY_SIGNING_SEED_PATH`.
Neither new name joins wiring's `REQUIRED_ENV_KEYS` (design-b
§3.1 item 2's reasoning holds for both: production *startup*
refusal is the verifier's rule; wiring-required is the
client-construction minimum — the seed mirrors
`AION_CEREMONY_OPERATORS` exactly here).

### B-2. Defence — Retention naming by `authorisation_id` survives A; payload_hash naming rejected (design-b §1.8, answering the coordinator's question and design-b R1)

Design-b R1 flagged that retention names files by
`authorisation_id`, which A derives. Re-checked against A §3:

- **Derivation stays stable and unique.** A keeps
  `authorisation_id_for(payload_hash, key_id)`'s formula —
  `sha256(canonical {"v": DOMAIN, "payload_hash", "key_id"})` —
  and changes only its inputs: `DOMAIN` v1→v2 and `key_id`
  `key-…`→`pub-…`. For a given envelope the id is still a pure,
  key-free, re-derivable function of the envelope (client and
  ceremony re-derive it today; they still can). Uniqueness is
  inherited from SHA-256 over a canonical blob that binds the
  payload hash *and* the signing key's public identity — two
  different envelopes (different payload, different domain
  version, or a rotated seed producing a different `pub-…` id)
  do not share an id short of a hash collision. It remains a
  hex64: a safe single-segment filename by construction, and
  design-b §1.8's `O_EXCL` semantics stay correct — an `O_EXCL`
  collision still means "this exact authorisation was already
  committed", never a false clash between a v1 and a v2
  envelope (their ids differ *because* the domain input
  differs — flag-day cannot make a retained v2 write collide
  with a retained v1 file of the same payload).
- **Why not `payload_hash`:** it would also be unique (the
  payload itself carries `key_id` and the v2 projection, so the
  hash moves with them) — uniqueness is not the discriminator.
  The discriminator is the audit join. The ceremony *record*,
  the signing ledger's `decision_id`, and the client's
  re-derivation all key on `authorisation_id`; nothing outside
  the envelope keys on `payload_hash`. Naming the retained file
  by `payload_hash` would force every future auditor to map
  record → envelope → payload_hash before finding the bytes,
  and would break the mechanical audit design-b §1.8 promises
  ("re-hash `<authorisation_id>`, compare to the envelope and
  to both ledgers"). Keep `authorisation_id`. No change to
  design-b §1.8.

### B-3. Defence — Design-b §1.6 commit order is compatible with A; one interaction to pin

A changes only the signing primitive inside design-b §1.6
step 6 (`sign_ceremony_authorisation` with a
`CeremonySigningKey` instead of a `SigningKey`). Design-b's
inserted retained-evidence write (step 7, between ceremony-
journal append and signing-ledger append) is untouched by A,
and A-5 confirms no ledger shape moves. One pin for the build:
the seed is loaded in `_load_config` (A-1b), so by the time the
mode runs, a seed failure is impossible at step 6 short of a
programming error — signing failure there remains
`ledger_failed` post-commit semantics only if it happens after
the journal append; a `CeremonySigningKey` construction error
must be impossible post-config, and the build should assert the
key object exists at step 1's config gates (research-`None`
case) rather than discovering it at step 6 with the pair
half-burned.

---

## Part 3 — Critique of design C (consumption integrity)

### C-1. NOTE (plain answer) — C's contract changes nothing in the verifier mode or the client; there is no verifier-side role in consumption under C, and none should be invented

Checked directly: `_mode_ceremony_authorise` neither reads nor
writes `PinCeremonyRecord`s or any ceremony history; the
verifier's ledgers record *issuance* only. C §3 makes
`ceremony_history` a required argument to the in-process
`reanchor_pin` (signing layer, caller-supplied). Therefore:

- No verifier mode gains or loses a field, check or refusal
  under C. No new mode is proposed by C, and C §2 explicitly
  rejects the callback/store shapes that would create one.
- `VerifierClient` should **not** grow a consume-side helper.
  The client is a subprocess client for verifier modes;
  consumption under C is an in-process function call in the
  main process. A client helper would either be a thin wrapper
  over `reanchor_pin` living in the wrong module (implying a
  verifier involvement that does not exist) or the thin end of
  A-route-4 delegated consumption, which A §1 route 4 and
  C §7.1(b) both agree is a coordinator-level either/or to be
  decided *before* the build, not smuggled in as a helper.
  Plainly: **under C's design the verifier has no role in
  consumption — not a check, not a burn, not a consult.** The
  only client-adjacent impact is in *tests*: E2E helpers that
  call `ceremony_authorise` and then `reanchor_pin` must now
  pass `ceremony_history` explicitly (C §6's helper treatment),
  which is fixture plumbing, not an API change.

### C-2. SHOULD-FIX — C's claims-sweep list (§7.1(b)) verified against the texts: one hit is real, two are already correct, one file has nothing to fix — and C missed the user-visible refusal strings in my files

Grep-verified over `trust/` and `signing/` this round:

| C's assignment | Verdict |
|---|---|
| `signing/ceremony_authorisation.py`: "burned on use" → "burned at issuance" | **Confirmed, exactly one occurrence**: the honest-limits bullet "…bound to one event, and burned on use" (line 45). It is wrong today — the pair burns at issuance — and C §7.1(a)(b) is right to demand the fix regardless of A. The same file's other sentence (line 41, "ledgered single-use at issuance") is already correctly scoped; do not touch it. |
| `trust/ledger.py` | **Overstated.** `CeremonyAuthorisationLedger`'s docstring (lines ~540–545) already says the append "is the commit point for single-use" at issuance and that the pair "is spent" when it lands; `append_ceremony_authorisation` makes no single-use claim at all. There is nothing in the ceremony parts of ledger.py that mis-scopes single-use. (`ledger.py` line 9's "single-use twice over" is about *gate decisions* in `SigningLedger` — a different store, correctly scoped to its own subject, and outside C's sweep whether C knows it or not.) Resolution: ledger.py needs **no edit** under this item; the BUILD record should say "checked, already issuance-scoped" rather than letting a builder hunt for a defect that is not there. |
| `trust/verifier_main.py` | **Mostly already correct — and C missed the two strings that do need scoping.** The module docstring (lines 148–155) and the mode docstring (lines ~1627–1639) both already say "ledgered single-use **at issuance**" / "commit point for single-use" in issuance context. What C did *not* list: the mode's live refusal details — `"ceremony ids are single-use"` (`ceremony_id_reused`) and `"evidence is single-use per event"` (`ceremony_evidence_reused`) — are protocol-visible text a caller reads as an unscoped single-use claim. Add them to the sweep: both gain "at issuance" ("ceremony ids are single-use at issuance"; "evidence is single-use per event at issuance"). Cheap, and refusal text is claim surface — rev-r6's standard applies to it. |
| `trust/client.py` | **Nothing to fix.** `VerifierClient.ceremony_authorise`'s docstring contains no "single-use" or "burned" wording at all (grep: zero hits in the method). C §7.1(b)'s instruction that its docstring's "every single-use mention must carry its scope" is vacuously satisfied. No edit; record as checked. (The client docstring *does* need design-b §2.3 item 5's AUTHORITY→ELIGIBILITY edit and §1.7's new refusal codes — different items, already on my list.) |

Also confirmed in C's favour: `signing/pin_ceremony.py` lines 81
and 133 already carry the issuance-scoped wording, so C §7
item 4's append-only treatment of that paragraph is correct.

*Resolution:* the build's claims sweep for my files is: (1)
ceremony_authorisation.py line 45 (C's catch); (2) the two
verifier_main.py refusal details above (this critique's catch);
(3) ledger.py and client.py recorded as checked-no-change.
The grep gate at the end of the sweep is
`grep -rn "burned on use" signing/ trust/` → zero, and a manual
read of every remaining "single-use" hit in the four files
confirming each carries "at issuance" or names the gate store.

### C-3. SHOULD-FIX — The retained key-separation tripwire (A §3 layer 3, C §4.3) can never fire as specified; both designs understate this

A §3 layer 3 and C §4.3 both retain the refusal
`authorisation key_id == signing_key.key_id`, downgraded to a
misconfiguration tripwire. But under A's own derivations the
two ids live in disjoint string namespaces — `pub-` + hash of
public key vs `key-` + hash of secret — so **equality is
impossible by construction**, including in exactly the gross
misconfiguration both designs claim it catches: wire the
*same seed bytes* as both the ceremony seed and an HMAC key
file, and the ids still differ (different prefix, different
hash input — the public key is not the seed). C §4.3 comes
closest to honesty ("does not by itself prove distinct key
material") but still describes the check as refusing "the same
key *file* wired to both slots" — it cannot: same file, different
ids, check passes. The verifier-side half of the real check
exists and is mine (A-1c: byte-equality of seed vs HMAC key in
`_load_config`). The ceremony-side half cannot compare bytes —
the ceremony holds no secret to compare — so at consumption
there is **no** effective in-process tripwire for
seed-reuse-as-snapshot-key, and the docstring must say that
instead of retaining a check whose only function now is to
look like one. *Resolution:* keep the id check if the room
wants it as a guard against a *future* derivation change
removing the prefixes, but word it as exactly that
("a regression guard on the id derivations, not a
key-material check"), and move the substantive claim to
provisioning + `_load_config` byte checks. A §3 layer 3's
parenthetical example ("seed derived from snapshot key bytes")
must be deleted or corrected — as written it promises a catch
the code cannot make.

### C-4. BLOCKER (claim gate, not design gate) — C's stale-history residual is honest in C's text and fails Gemini's fail-closed demand in spirit; the cycle record must not launder it (C §3.1–§3.3, §5, §8 Q7–Q8)

From the verifier seat, C §2's ownership analysis is correct
and I confirm it from my side: there is no production caller,
no pin store, and no verifier channel to live state — C invents
none, which is the right call. C §5's residual paragraph is
genuinely honest: same envelope + stale `()` history consumes
twice, regression included, pinned by T7/T8 as residuals rather
than features. That honesty is exactly what rev-r6's standard
requires of the *design*.

But measured against the external demand C itself cites —
Gemini: "consumption must fail-closed if state/history
continuity cannot be verified" — C implements fail-closed only
for the *omission* leg. A supplied-but-stale (or supplied-but-
empty-and-false) history is a case where continuity **cannot**
be verified, and consumption proceeds. C §3.2 concedes this is
"the only reading available in-process" and §8 Q8 concedes
GPT's cycles 14–16 condition is "met for *no* history and unmet
for *stale* history". So: C is honest enough **iff** every
downstream text preserves the concession at the same strength.
The failure mode is not in design-c; it is in the summary
layer — a BUILD-CYCLE-20 line or external brief that compresses
§3 to "consumption now fails closed (history required)" would
fail Gemini's test in spirit while citing C as its authority,
and would re-trigger rev-r6's preserved F1 dissent verbatim.

*Resolution (binding on the coordinator's texts, not on C's
mechanism):* (i) F1 is carried in BUILD-CYCLE-20 as
**"narrowed, still open"** with C §5 quoted, per C §8 Q7;
(ii) the cycle-20 external brief states the stale leg as unmet
in one sentence, beside the omission leg as met; (iii) no file
in `signing/` or `trust/` may use the phrase "fail-closed
consumption" without the qualifier "on omission" in the same
sentence — add this to the build's grep gate. With those three,
I do not block C's design. Without them, I block the claim.

### C-5. SHOULD-FIX — FRESH-PIN / COMPLETE-HISTORY / ATOMIC-ADOPTION are documentation, and must be labelled as such everywhere they appear (C §4.2)

C §4.2 is commendably explicit that the three preconditions are
"unverifiable in-process" and naming them "does not enforce
them". My seat's ruling on the coordinator's question: **as
mechanism, they are documentation; as design, their only
operative content is the signature change (§4.1) that makes
omission loud.** That is worth having — an audit checklist for
the future loop/storage layer is a real artefact — but three
guards are needed so documentation is not later read as design:

1. The docstring paragraph must carry C §7 item 6's sentence
   ("None of the three is verifiable in-process…") *in the same
   paragraph* as the names, not a page away — a reader who
   finds FRESH-PIN via grep must find the disclaimer in the
   same screenful.
2. BUILD-CYCLE-20 must list the preconditions under "caller
   obligations recorded", never under "mitigations" or
   "fixes" for F1. (Pairs with C-4.)
3. COMPLETE-HISTORY has a cost C §8 Q10 flags and I second from
   the config seat: mandatory history means every ceremony
   re-verifies every prior record, unbounded O(n). No cap this
   cycle is acceptable, but the precondition's text should note
   the history it demands is the *complete* one — a caller
   cannot comply cheaply by truncating, because truncation is
   precisely the stale case. The tension (complete history is
   both required and unverifiable, and grows without bound) is
   one more reason the protected head, not this contract, is
   the real fix; say so once, in §5's paragraph, where C
   already nearly says it.

### C-6. NOTE — TTL interplay (C §8 Q6) confirmed from the verifier seat

C assigns me the TTL-as-mitigant wording. Confirmed: the
900 s hard cap (`min(config, 900)` at issuance) bounds the
stale-history replay window, and that is a *bound on exposure*,
not a fix — after expiry the replay dies with the envelope, but
within the window T7/T8 succeed. Design-b's texts will carry it
only in that form, and the same sentence is required in the
BUILD record (see C-4 (iii)'s grep-gate spirit).

---

## Part 4 — Impact on design-b's file/test list (consolidated deltas)

Everything in design-b §3.3 stands, amended as follows:

1. **Allowlist count 15 → 17 everywhere** (B-1): wiring test
   renamed `test_allowlist_is_the_shipped_17_names` with
   `len == 17` and `assertIn` for **both**
   `AION_CEREMONY_EVIDENCE_DIR` and
   `AION_CEREMONY_SIGNING_SEED_PATH` (keeping the
   `AION_SHIP_ANCHOR_PATH` negative); wrapper-match test
   `len == 17`; health-check match test `len == 17`; two named
   pins in `test_verifier_deploy.py`
   (`test_ceremony_evidence_dir_key_allowlisted`,
   `test_ceremony_signing_seed_path_key_allowlisted`);
   production-deploy inline `allowlisted` set gains both names.
2. **setup.sh template gains two lines** (evidence dir per
   design-b §3.2; seed path per A-1e) — template-equality tests
   fail until both land. health_check gains the seed checks in
   A-1e beside the evidence checks in design-b §3.1 item 3.
3. **Production fixtures gain two entries, not one:**
   `test_trust_production_deploy.py`'s production-success env
   must carry `AION_CEREMONY_EVIDENCE_DIR` *and*
   `AION_CEREMONY_SIGNING_SEED_PATH` pointing at a real,
   loader-clean seed file the fixture provisions — without
   either, the production verifier refuses startup (by design,
   in the wrong test).
4. **E2E fixture rework is larger than design-b §3.3 stated.**
   `tests/test_trust_ceremony_authorisation.py` and
   `tests/test_trust_ceremony_mode.py` must now, per fixture:
   provision an evidence artifact with a real hash (design-b),
   provision a ceremony seed through the real loader from a
   per-run generated file (A-1d), set the client's
   `expected_key_id` pin to the derived `pub-…` id (the pin's
   *form* changes, not just its value — any fixture hard-coding
   a `key-…` expectation for ceremony envelopes fails), and
   pass `authorisation_public_key` + explicit
   `ceremony_history` at every `reanchor_pin` call (A §3 +
   C §4.1/§6). The ceremony-mode fixture's refusal tests gain:
   production startup refusal without the seed; malformed seed
   file refuses startup in research too; research + absent seed
   → `ceremony_seed_unconfigured`, ledger-empty; seed byte-equal
   to the HMAC key refuses startup (A-1c); RFC-vector seed
   refuses startup (A-1d).
5. **New refusal-code surfacing:** `ceremony_seed_unconfigured`
   joins design-b §1.7's catalogue as an exit-3, unsigned,
   unledgered config-gate refusal, and
   `VerifierClient.ceremony_authorise`'s docstring lists it
   beside `ceremony_evidence_unconfigured`.
6. **Drain procedure** (A-2) added to the deployment README
   work list; the combined migration note (A-1e) replaces
   design-b §3.2's single-variable note.

---

## Decisions needed from the coordinator

1. **Seed config contract (A-1b):** ratify production-startup /
   research-per-request split for `AION_CEREMONY_SIGNING_SEED_PATH`,
   the new refusal code name `ceremony_seed_unconfigured`, and
   the `_load_config` byte-equality + refused-seed rules
   (A-1c/A-1d) as design-b §3.5. If the room instead wants the
   seed required at startup in *both* modes (core-key
   philosophy throughout), say so now — it changes the research
   fixtures' shape.
2. **Allowlist landing (B-1):** confirm the combined count is
   **17** and that both variables land in one atomic build
   commit series with all five copies; and confirm the §2.4
   token appendix stays unbuilt (if overruled, the count is 18
   and design-b §2.4's arithmetic is withdrawn, per B-1).
3. **Strict Ed25519 profile (A-3):** ratify canonical encodings
   + literal small-order blocklist (check order as specified)
   + `S < L` + cofactorless equation, labelled "strict
   RFC 8032", and the one-signer argument as the recorded
   reason ZIP-215 divergence is accepted.
4. **Flag-day + drain (A-2):** accept flag-day cutover
   conditional on the five-step drain procedure shipping in
   the deployment docs this cycle; assign the README/ops text
   an owner (seat B drafts, coordinator lands).
5. **Client-side verification (A-6):** adopt or reject A §3 Q8
   in the design round; design-b's client-impact list is
   amended to match before the build starts.
6. **F1 wording discipline (C-4/C-5):** commit the BUILD record
   and external brief to "F1 narrowed, still open", the
   stale-leg-unmet sentence, and the "fail-closed on omission"
   qualifier rule — and re-poll rev-r6 on that basis, per
   C §8 Q7.
7. **Tripwire wording (C-3):** agree the id-equality check is
   reworded as a derivation-regression guard, with the
   substantive seed-reuse defence recorded as provisioning +
   `_load_config` byte checks only.
