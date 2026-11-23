# Cycle 20 — Design A: the KEY BOUNDARY (coder seat A)

Scope: my slice only — replacing the symmetric authorisation MAC
with a scheme in which verifier authority is *independently
attributable*. Seat B owns verifier mode/config + evidence
resolution; seat C owns `pin_ceremony` consumption (atomic live-pin
check, consumption head). Where my sketch names their files it is
an interface proposal, not a design for their slice.

The defect, restated from CROSS-CHECK-13 (both external seats,
converging): in cycle 19, `signing/ceremony_authorisation.py`
signs with `_mac(key, …)` and
`signing/pin_ceremony.py:reanchor_pin` verifies with the *same*
secret, held in a `SigningKey` (`authorisation_key`). Verification
of an HMAC requires the minting secret, so every process that can
consume an envelope can also mint one indistinguishable from a
verifier-issued envelope. The cycle-19 docstring admits this
("anyone holding the verifier key (including a verify-only
consumer) can forge"). Key separation (authorisation key_id ≠
snapshot key_id) is not attribution: it separates two symmetric
secrets, both of which the ceremony process holds. The fix must
make the ceremony process hold *verification-only* material.

---

## 1. Route evaluation

### Route 1 — Ed25519 in pure Python (RFC 8032), stdlib only

Construction. `hashlib.sha512` + built-in big-int `pow` are all
that is needed. Key generation is deterministic from a 32-byte
seed: `h = SHA512(seed)`, clamp the first half, public key
`A = [a]B`. Signing is RFC 8032 deterministic (the nonce `r` is a
hash of the seed's second half and the message — **no RNG is
involved in signing**, so there is no nonce-reuse-by-bad-randomness
failure mode of the ECDSA kind). Verification checks
`[S]B = R + [H(R‖A‖M)]A` over the canonical payload-hash blob
(§3 below).

Performance — MEASURED on this VM (1.5 shared vCPU, CPython
3.12.3, throwaway scripts in /tmp, not committed):

| implementation | derive pubkey | sign | verify |
|---|---|---|---|
| RFC 8032 §6 reference code (affine coords, a modular inversion per point add) | 135 ms | 284 ms | **278 ms** (n=20) |
| Extended twisted-Edwards coords (inversion only on encode/decode) | 3 ms | 3 ms | **8.9 ms** (n=30) |

Both were validated against the RFC 8032 §7.1 TEST 1 vector
(secret `9d61…7f60`, public `d75a…511a`, empty-message signature
`e556…100b`) before timing. Conclusion: the naive reference code
is *correct but must not ship* — 278 ms per verify is survivable
for a rare ceremony but invites a future "optimisation" that
breaks it. The extended-coordinate form is ~30× faster, is still
~120 lines, and at ~9 ms verify / ~3 ms sign the cost is noise
next to the verifier subprocess spawn the flow already pays.
Message size is irrelevant (we sign a fixed 100-odd-byte blob,
and SHA-512 dominates nothing). **Performance is a non-argument
against this route.**

Correctness risks — the honest list, each with its mitigation:

- *Hand-rolled crypto.* The real cost of this route. Mitigations:
  the RFC 8032 §7.1 test vectors are public constants and become
  unit tests verbatim (§5); sign and verify are separate code
  paths cross-checked against each other and against the vectors;
  the implementation is one small module
  (`signing/ed25519.py`, no other caller in cycle 20) so the war
  room can read every line.
- *Verification strictness.* A lax pure-Python verifier is
  malleable. The verifier MUST: reject `S ≥ L`; reject
  non-canonical point encodings (`y ≥ q`, and re-encoding the
  decoded point must reproduce the input bytes exactly); reject
  small-order `A` and `R` (check against the 8 known small-order
  encodings, or equivalently verify `[8]P ≠ identity` handling —
  my recommendation is the encoding blocklist plus the
  cofactorless equation, i.e. strict/"ZIP-215-minus" semantics:
  canonical encodings required, cofactorless equation); reject a
  signature that is not exactly 64 bytes. These checks are
  enumerated as tests, not left as prose.
- *Timing.* Pure-Python scalar multiplication is not
  constant-time. That matters only where a secret scalar is
  multiplied: the *signing* side, inside the verifier process,
  against a local timing observer — the same same-OS-user honesty
  caveat `gate_decision.py` already carries. Verification
  multiplies only public values; its timing leaks nothing.
- *Seed handling.* The seed is a bearer secret exactly like
  today's HMAC key file, and reuses the existing discipline
  (§3): 32 bytes as lowercase hex in a 0600 file, outside the
  repo and caller-named forbidden roots, no symlink components —
  i.e. `load_signing_key`'s rules, factored so both loaders share
  `_check_key_path`. The seed lives **only in the verifier's
  environment** (new path variable, seat B's config change). The
  ceremony process never opens it; it holds 32 public bytes.

Key identity / pinning. `key_id_for` derives `"key-" +
sha256(key)[:16]` from secret bytes — impossible for a public
key the consumer must be able to recompute from public material
only in the sense that it must derive from the *public* bytes.
Analogue, as suggested in the brief:

```python
def public_key_id_for(public_key: bytes) -> str:
    # "pub-" + sha256(public_key)[:16]  — matches _check_id grammar
    return "pub-" + _sha256(public_key)[:16]
```

The public key is pinned at the ceremony the same way the
verifier's identity already is: `reanchor_pin` today takes
`expected_verifier_signer_id` as a caller-supplied pin, and
`trust/client.py`'s `VerifierClient` takes constructor pins
`expected_signer_id` / `expected_key_id`. Cycle 20 adds the
public-key pin beside them (§3). The envelope *carries* a
`key_id` claim; verification compares it to the pinned key's
derived id and reports `unknown_key` on mismatch — the envelope
never supplies its own verification key.

### Route 2 — RSA in pure Python

Verification is genuinely cheap: `pow(sig, e, n)` is C-speed
big-int arithmetic (sub-ms to a few ms at 2048 bits), and signing
`pow(m, d, n)` is tens of ms. Key *use* from stdlib is easy; key
*generation* is the problem:

- Pure-Python Miller–Rabin generation of two 1024-bit primes is
  seconds-to-tens-of-seconds, variable-time, and its correctness
  (round count, small-prime sieving, `secrets`-sourced candidates)
  is another hand-rolled-crypto surface — larger than Ed25519's.
- Or keys are generated at provisioning time with the openssl CLI
  and only *used* from stdlib — which smuggles route 3's system
  dependency in through the provisioning door and leaves the repo
  unable to rotate keys without a tool it does not declare.

Forgery pitfalls are the deciding factor. PKCS#1 v1.5 is safe
only under *strict* verification: sig < n, decoded block exactly
modulus-length, `00 01 FF…FF 00` padding of the exact expected
length, the SHA-256 DigestInfo prefix
(`30 31 30 0d 06 09 60 86 48 01 65 03 04 02 01 05 00 04 20`)
byte-exact, the digest byte-exact, and **no trailing garbage**.
The classic Bleichenbacher-2006 forgeries exist precisely because
real verifiers skipped the last two checks; a hand-written parser
in this repo would have to be perfect on its first day. PSS
removes the historical baggage but adds MGF1, salt-length and
trailer checks — more code than Ed25519 verify, not less.
Signatures are 256 bytes (512 hex chars) at 2048 bits vs 64 bytes
for Ed25519, and public keys need a canonical (n, e) encoding
invented for the key_id derivation. Net: more mechanism, larger
envelopes, a worse forgery history, and a keygen problem Ed25519
does not have (32 random bytes *are* an Ed25519 key).

### Route 3 — openssl subprocess for signing (verifier only) + pure-Python verification

`openssl 3.0.13` does exist at `/usr/bin/openssl` on this machine
(checked), and process spawn is ~3 ms. But this route saves
almost nothing and buys a dependency:

- The *hard* half — pure-Python verification with all of route
  1's strictness checks — is still required at the ceremony.
  What openssl replaces is only the signing half, which is the
  easier, vector-pinned, ~3 ms half.
- "Stdlib-only" is a stated repo invariant (every signing module
  header says so). A subprocess call to a system binary is a
  third-party dependency that `requirements` cannot name:
  undeclared, unversioned, and absent on minimal containers /
  other platforms where 3.0.13 happens to exist here. Ed25519
  support itself only arrived in OpenSSL 1.1.1.
- Failure modes multiply: PATH resolution inside the verifier's
  deliberately scrubbed environment, PEM key files (a *second*
  key-file format and discipline to audit), message/signature
  plumbing (must be stdin/stdout with `-rawin`; any temp file is
  a secret-handling bug waiting to happen), stderr parsing, and
  version-dependent CLI flags — all to produce a signature the
  pure-Python code already produces deterministically.

Verdict: reject. It is route 1 with extra moving parts and a
portability debt, adopted only if a future audit forbids
in-repo signing code specifically (see runner-up note — even
then, route 4 is preferable).

### Route 4 — Verifier-delegated consumption (Gemini's alternative)

Sketch, honestly. `reanchor_pin` can no longer complete locally:
after its in-process checks it must call a new verifier mode
(`ceremony_consume`) presenting the envelope plus a claim about
the consumption event, and only the verifier's signed/ledgered
accept lets the ceremony proceed. The main process then holds no
minting key at all — the HMAC key never leaves the verifier — and
a locally minted envelope fails because the verifier's journal
contains no issuance record for its `authorisation_id`.

What the verifier can and cannot bind is where this route
weakens. The verifier cannot see the snapshot, the pin store, or
the live pin (seat C's slice exists precisely because those are
main-process state). A consume request can carry only *claims*:
`authorisation_id`, hashes of the old pin / candidate /
evidence as the main process asserts them. The verifier can
check those claims against its issuance record (the envelope it
issued bound the same projections — so a consume claim that
disagrees with issuance is refused) and burn the id atomically
in its own journal. That genuinely closes consumption replay
(F1) — better than route 1 does. But it does not bind the pin
movement the main process *actually performs* after the accept:
a compromised main process can request consumption for event X
and move the pin to Y. Under route 1 the same compromised process
also cannot be stopped from moving a pin — no in-process scheme
can — but route 4's extra guarantee is narrower than it looks:
it attests the *claimed* event, with the verifier as a
single-use oracle, not the performed event.

Costs: the ceremony becomes online-only (verifier down ⇒ no
disaster recovery, at exactly the moment of disaster recovery);
`reanchor_pin`'s pure-function API becomes client-injected and
asynchronous-by-subprocess; the large in-process ceremony test
suite must be rebuilt on a subprocess or on a test double — and
a test double that "consumes" locally reintroduces a minting/
consuming authority inside the test harness that must be kept
from leaking into production wiring; a new mode means new
ledger/atomicity work in seat B's already-loaded slice
(evidence resolution). It also *keeps* HMAC as the envelope
scheme, so the "forged envelope is indistinguishable at
consumption" audit caveat survives in weakened form (indistinguishable
in the envelope itself; distinguishable only via the journal).

### Summary table

| | R1 Ed25519 pure-Py | R2 RSA pure-Py | R3 openssl sign + Py verify | R4 delegated consumption |
|---|---|---|---|---|
| Ceremony holds minting material? | **No** (32 public bytes) | No (n, e) | No | No (no key at all) |
| Locally minted envelope fails? | **Yes, cryptographically** | Yes | Yes | Yes, via journal absence |
| New dependency | none | none (or openssl at provisioning) | **system openssl, undeclared** | none |
| Verify cost (measured/est.) | 9 ms (extended) | ~1 ms | 9 ms (still route-1 verify) | HMAC µs + subprocess RTT |
| Sign cost | 3 ms, deterministic, no RNG | tens of ms | ~3 ms spawn + CLI | HMAC µs (verifier-side) |
| Key generation | 32 random bytes | **MR prime search or CLI** | CLI (PEM) | unchanged (HMAC) |
| Signature size | 64 B / 128 hex | 256 B / 512 hex | 64 B | 32 B |
| Main forgery risk | lax verify strictness (mitigated by enumerated checks) | **v1.5 lax-parse forgeries; PSS complexity** | route-1 verify risk + plumbing | main process lies about performed event |
| Offline / in-process ceremony | **yes** | yes | yes | **no — verifier must be live** |
| Closes consumption replay (F1)? | no (seat C's head still needed) | no | no | **yes, for claimed events** |
| Hand-rolled crypto surface | ~120 lines, RFC vectors | keygen + strict parser ≫ R1 | verify half of R1 + CLI glue | none new |

## 2. Recommendation

**Route 1: pure-Python Ed25519 (RFC 8032), extended coordinates,
strict verification, seed held only by the verifier, public key
pinned at the ceremony.**

Reasons, in order of weight:

1. It is the only route that makes the boundary *cryptographic
   rather than procedural* while keeping the ceremony a pure,
   offline, in-process function — the property the existing
   architecture (library `reanchor_pin`, subprocess only at
   issuance) is built around. Gemini's own wording offered
   asymmetric signing *or* delegation; asymmetric is the one
   that does not re-shape every other seat's slice.
2. The measured performance removes the only quantitative
   objection: ~9 ms verify, ~3 ms sign on this throttled VM.
3. Key generation is trivial and RNG-minimal (one 32-byte draw
   at provisioning; signing itself is deterministic), versus
   RSA's prime search or CLI provisioning.
4. The failure surface is enumerable and testable: RFC vectors
   plus the strictness checklist in §5. The module is small
   enough for the war room to read line by line — the same
   standard the repo applies to its canonicalisers.

**Runner-up: route 4 (delegated consumption).** Prefer it if
either (a) the war room / owner rules that no hand-rolled
asymmetric code ships in this repo at all, or (b) closing
consumption replay (F1) is promoted into cycle 20's scope —
route 4 is the only route that closes it, and it composes with
route 1 later (asymmetric issuance now, delegated consumption
when seat C's monotonic head is designed). Note the routes are
not exclusive long-term; recommending R1 now does not foreclose
R4 for the held cycles 14–16 re-review, which needs the
consumption head regardless.

## 3. Concrete API / format sketch (route 1)

New module `signing/ed25519.py` (stdlib only, no imports from
`signing/` — usable by both sides, auditable in isolation):

```python
PUBLIC_KEY_BYTES = 32
SEED_BYTES = 32
SIGNATURE_BYTES = 64

def public_key_from_seed(seed: bytes) -> bytes: ...
def sign(seed: bytes, message: bytes) -> bytes: ...        # 64 bytes
def verify(public_key: bytes, message: bytes,
           signature: bytes) -> bool: ...                  # strict, §1 checks; never raises on bad sig
```

Changes in `signing/ceremony_authorisation.py`:

```python
CEREMONY_AUTHORISATION_DOMAIN = "signed-ceremony-authorisation-v2"
ALG_CEREMONY = "ed25519"            # payload "alg"; NOT gate_decision.ALG
                                    # (that constant stays "hmac-sha256"
                                    # for the gate/attestation/record MACs,
                                    # which are out of scope and unchanged)

@dataclass(frozen=True)
class CeremonySigningKey:           # verifier-side ONLY
    seed: bytes                     # repr shows key_id + pub fingerprint only
    public_key: bytes
    key_id: str                     # public_key_id_for(public_key)

@dataclass(frozen=True)
class CeremonyPublicKey:            # ceremony/client-side; the pin
    public_key: bytes
    key_id: str                     # public_key_id_for(public_key)

def load_ceremony_seed(path, *, forbidden_roots=()) -> CeremonySigningKey
    # Same file discipline as load_signing_key (0600, hex, exactly
    # 32 bytes, _check_key_path) — factor the checks, don't copy them.
def generate_ceremony_key_file(path, *, forbidden_roots=()) -> CeremonySigningKey
def public_key_id_for(public_key: bytes) -> str   # "pub-" + sha256(pk)[:16]

def sign_ceremony_authorisation(*, signing_key: CeremonySigningKey, ...)
    # was: signing_key: SigningKey (HMAC). All other params unchanged.
def verify_ceremony_authorisation(signed, *, public_key: CeremonyPublicKey, ...)
    # was: signing_key: SigningKey. Param RENAMED, not re-typed in
    # place: a call site still passing a SigningKey fails loudly.
```

Payload / envelope changes (everything not listed is byte-identical
to cycle 19 — operator, ceremony, reason, old_pin, candidate,
evidence_hash/ref, TTL fields, projections):

| field | cycle 19 | cycle 20 |
|---|---|---|
| payload `"v"` | `"signed-ceremony-authorisation/1"` | `"signed-ceremony-authorisation/2"` |
| payload `"alg"` | `"hmac-sha256"` | `"ed25519"` |
| payload `"key_id"` | `"key-"+sha256(secret)[:16]` | `"pub-"+sha256(public_key)[:16]` |
| domain string | `signed-ceremony-authorisation-v1` | `signed-ceremony-authorisation-v2` |
| signed blob | `domain \n alg \n key_id \n payload_hash` (utf-8) — HMAC input | **same blob, as the Ed25519 message** — the construction carries over; only the primitive changes |
| envelope `"signature"` | hex64 (HMAC) | **hex128** (64-byte Ed25519 signature, lowercase hex) |
| `payload_hash`, `authorisation_id` | hex64 | hex64, unchanged shape |

`authorisation_id_for(payload_hash, key_id)`: formula unchanged
(`sha256(canonical {"v": DOMAIN, "payload_hash", "key_id"})`),
but `DOMAIN` is now v2 and `key_id` is the *public* key id — so
the id now binds the payload to a publicly derivable key
identity, and consumers (client, ceremony record) still re-derive
it key-free, exactly as today. No secret participates in the id.

`verify_ceremony_authorisation` reason vocabulary: unchanged,
with `signature_mismatch` now meaning Ed25519 failure and
`unknown_key` meaning `signed.key_id != pinned public key_id`.
The `_HEX64_RE` check on `signature` in
`ceremony_authorisation_envelope_from_dict` becomes a hex128
check; `payload_hash`/`authorisation_id` stay hex64.

Verifier (seat B's implementation, my interface ask): the seed
is loaded in `_load_config` from a **new, separate** path
variable (proposed `AION_CEREMONY_SIGNING_SEED_PATH`), scrubbed
from the environment after load like `AION_VERIFIER_KEY_PATH`;
`_mode_ceremony_authorise` calls the new
`sign_ceremony_authorisation` with it. The verifier keeps its
existing HMAC `SigningKey` for every other mode — the ceremony
seed is an *additional*, purpose-only key. `_REFUSED_TEST_KEYS`
needs a ceremony-seed analogue (seat B).

Ceremony (seat C's implementation, my interface ask):
`reanchor_pin(..., authorisation_key=…)` is **replaced** by
`authorisation_public_key: CeremonyPublicKey` (required, no
default) plus the unchanged `expected_verifier_signer_id`.

### What "key separation" becomes

Cycle 19's check — two `SigningKey`s with different `key_id`s —
is deleted, because there is no longer a second secret to
separate. Separation becomes structural, in three layers:

1. **Type separation.** The ceremony's authorisation parameter
   is a `CeremonyPublicKey`, which *cannot contain* secret
   material. Passing the snapshot `SigningKey` is a type error
   at the `isinstance` gate, not a policy refusal.
2. **Role separation.** Even a fully compromised ceremony
   process yields only public bytes: minting capability is not
   present to be leaked, misconfigured, or compared.
3. **Residual id check (defence in depth, seat C to keep).**
   `authorisation_public_key.key_id != signing_key.key_id`
   remains as an explicit refusal — it can now only trigger on
   a provisioning error (the verifier's public key accidentally
   pinned where… / seed derived from snapshot key bytes), which
   is exactly the misconfiguration class worth still catching.
   Additionally, provisioning should refuse a ceremony seed
   byte-equal to any HMAC key in the deployment (seat B).

### Retiring the HMAC path — no silent fallback (requirement c)

Four independent tripwires, so no single oversight revives it:

1. **Domain + version bump together:** v2 domain string and
   payload `"v": "…/2"`. A v1 envelope re-labelled v2 fails the
   signature check (the blob it was MACed over names v1); a v1
   envelope presented as-is fails at parse/projection.
2. **Alg is pinned by the projection:** `ceremony_authorisation_payload`
   emits `"alg": "ed25519"` only; an envelope claiming
   `hmac-sha256` cannot re-derive its payload and dies as
   `malformed_payload` before signature checking.
3. **Signature length:** v1's hex64 signature fails the hex128
   envelope check in `from_dict` — a v1 envelope is not even
   *parseable* by cycle-20 code.
4. **API deletion:** `sign_/verify_ceremony_authorisation` lose
   the HMAC code path entirely (the module's `_mac` is removed;
   `hmac` import goes with it). There is no flag, parameter or
   fallback branch. Grep-level test: `ceremony_authorisation.py`
   must not import `hmac`.

Cutover cost is bounded by design: v1 envelopes live at most
900 s (the hard TTL cap), so a flag-day switch strands at most
15 minutes of in-flight authorisations. No dual-verify window
is needed, and none should be built — a dual window *is* the
silent fallback.

### Client impact (`trust/client.py`, seat B/C boundary)

`VerifierClient.ceremony_authorise` is already key-free: it
re-derives `payload_hash` and `authorisation_id`, checks
signer/key pins and expiry, and enforces the full echo binding.
All of that survives unchanged in shape: `authorisation_id_for`
keeps its signature; `_check_pins` now pins the envelope's
`key_id` against a `pub-…` id (the client's `expected_key_id`
constructor pin simply takes the new form). One *optional*
strengthening, flagged as an open question below: if the client
is configured with the pinned `CeremonyPublicKey`, it *can* now
verify the signature itself (~9 ms) and fail fast — impossible
under HMAC without handing the client the minting secret. That
asymmetry is itself evidence the boundary moved.

## 4. Semantics that must survive the rewrite

From cycle 19, unchanged in meaning (tests will be rewritten;
these behaviours must not be):

- TTL: 900 s default **and hard cap** (`min(ttl, 900)`), TTL-min
  bound, single captured clock at consumption.
- Reason allowlist + the local-mirror/drift-test arrangement;
  reason/pin coherence (no-pin reasons ⇔ `old_pin is None`;
  old pin ⇒ `chain_gap_recovery`); gap-only sequence relation
  (`candidate.cycle_seq ≥ old_pin.cycle_seq + 2`) at projection.
- Evidence non-equality at projection (vs candidate and old-pin
  payload hashes) **and** the fuller in-process check in
  `reanchor_pin` (vs payload_hash, snapshot_id, state/calibration
  hashes) — neither layer may drop its half.
- Issuance-side single-use: ceremony journal is the commit
  point; (ceremony_id, evidence_hash) burned on ledger failure;
  unsigned/unledgered exit-3 refusal for unlisted operators.
- Signer ≠ operator: the verifier signs *about* the operator;
  operator authority is the verifier's protected list, decided
  at issuance. (Cycle 20 does not fix operator *authentication*
  — GPT/Gemini item (4) — that is seat B's slice; my scheme
  neither helps nor hinders it.)
- Client: payload-hash + authorisation-id re-derivation, pins,
  expiry-on-arrival, and the full 7-field echo binding.
- Ceremony: typed-envelope-only (raw dict refused), exact
  binding equality per field with per-field refusals, record
  carries `ceremony_id` + `authorisation_id` as required fields.
  The ceremony *record's* own MAC stays HMAC under the snapshot
  key — out of scope for this slice, stated so nobody reads the
  change as covering it.
- Honest-limits docstrings must be *rewritten, not deleted*: the
  "HMAC is symmetric / forged envelope indistinguishable"
  paragraph is replaced by the asymmetric truth (forgery requires
  the verifier's seed; a forged envelope fails verification in
  process, not merely on audit) — and the limits that remain
  (evidence not inspected at issuance unless seat B changes it,
  consumption replay, pin-substitution = deployment trust) stay
  stated.

## 5. Test plan

Primitive (`tests/test_signing_ed25519.py`, new):

- RFC 8032 §7.1 vectors as literal constants: TEST 1 (empty
  msg), TEST 2 (1-byte msg), TEST 3 (2-byte msg) — keygen,
  sign (deterministic: byte-equal signatures), verify.
- Negative vectors: bit-flip in R, in S, in message, in pubkey;
  `S == L`, `S == L+1`; non-canonical `y = q` encoding;
  small-order A (identity encoding) and small-order R; truncated
  / overlong signature; wrong-length pubkey/seed to the loaders.
- Property: 50 random seed/message round-trips; cross-check
  extended-coordinate implementation against a test-only affine
  implementation on random points (the slow code earns its keep
  as an oracle, in tests only).
- Loose perf guard: verify of the TEST 1 vector < 1 s (catches
  an accidental affine implementation; not a benchmark).

Envelope / adversarial (rewritten ceremony-authorisation +
pin-ceremony suites):

- **(a) Key substitution, both directions.** (i) Genuine
  verifier envelope, ceremony pinned to an *attacker*
  `CeremonyPublicKey` ⇒ `unknown_key`/`signature_mismatch`,
  ceremony refused. (ii) Envelope minted under the attacker's
  seed for the exact real event, ceremony pinned to the *true*
  verifier public key ⇒ fails identically. Together they pin
  the semantics: substitution produces refusal (DoS), never
  acceptance, in either direction.
- **(b) Local minting.** The attacker is given *everything the
  ceremony process holds*: the pinned public key, the snapshot
  `SigningKey`, all payload code, the exact event fields. They
  construct the best envelope constructible from that material
  (HMAC under any held key; Ed25519 under a self-generated seed;
  signature copied from a genuine envelope for a different
  event) ⇒ every variant fails verification / exact binding.
  This is the regression test for the cycle-19 defect itself —
  in cycle 19 this test *cannot be written to pass*, because
  the held material sufficed.
- **(c) No HMAC fallback.** A golden cycle-19 v1 envelope
  (fixture captured pre-change) ⇒ `from_dict` raises; a v2
  envelope with `"alg"` flipped to `hmac-sha256` ⇒
  `malformed_payload`; `inspect.signature` assertion that
  `verify_ceremony_authorisation` has no `SigningKey`-typed
  authorisation parameter; source scan: no `hmac` import in
  `ceremony_authorisation.py`.
- Field-tamper matrix carried over from cycle 19 (each payload
  field mutated ⇒ `signature_mismatch` or binding refusal),
  expiry / signed-in-future / TTL-cap tests re-pointed at the
  new signer, key-separation tests rewritten to the §3 form
  (type refusal for a `SigningKey`; id-collision refusal).
- E2E (`test_trust_ceremony_authorisation.py`): real verifier
  subprocess with a provisioned seed file; client echo binding;
  a *forged-envelope injection* case — hand-built envelope
  delivered straight to `reanchor_pin` bypassing the verifier —
  refused. Test fixtures must provision the seed through the
  real loader (0600 file outside the repo), not an in-process
  shortcut that bypasses the file discipline.

## 6. Risks / open questions for the other seats

For seat B (verifier mode/config + evidence):

1. Seed provisioning & rotation story: new env var + wiring /
   `setup.sh` / allowlist-count pins (the cycle-19 14→15 lesson:
   every live copy). Rotation invalidates in-flight envelopes
   (≤900 s) and requires re-pinning the public key at every
   ceremony caller — is a `pub-…` id change an acceptable
   flag-day, and who ratifies the new pin? Needs an owner-visible
   procedure, not just code.
2. `_REFUSED_TEST_KEYS` analogue for the seed, and the
   seed ≠ HMAC-key provisioning check (§3).
3. Does the ceremony journal / signing ledger entry shape change
   when `key_id` becomes `pub-…` and signatures double in length?
   (I believe no shape change — both are opaque strings — please
   confirm against `SigningLedger.append_ceremony_authorisation`.)

For seat C (consumption):

4. The atomic live-pin check and monotonic consumption head are
   *not* closed by this slice and must not be claimed closed:
   route 1 makes envelopes unforgeable, but a genuine envelope
   replayed within TTL against a moved pin is still seat C's
   F1 problem, unchanged.
5. `reanchor_pin`'s parameter rename is a hard break for every
   caller and test helper (cycle 19 counted one helper funnelling
   43 calls — recount before estimating).

For the war room / coordinator:

6. **Strictness choice needs ratification:** I recommend
   canonical-encoding + small-order rejection + cofactorless
   equation (strict). ZIP-215-style permissive verification
   would accept non-canonical encodings some other Ed25519
   stacks produce — irrelevant here (one signer, ours), and
   permissiveness is where malleability lives. Flagging because
   it is a judgement call, not a derivation.
7. Hand-rolled-crypto acceptance: route 1 asks the project to
   own ~120 lines of ECC. If the room will not own it, the
   runner-up (route 4) is the fallback — decide in the design
   round, not mid-build.
8. Client-side signature verification (§3, optional): worth it
   as fail-fast defence in depth, or an unwanted second verify
   path to keep consistent? My lean: adopt — it is the same
   `verify_ceremony_authorisation` call, not a new path — but it
   changes the client's "key-free structural checks" section
   contract, so it is the room's call.
9. Scope honesty for the cycle record: cycle 20-A closes the
   *minting* boundary only. Evidence resolution (Gemini item 1)
   and operator authentication (item 4) remain seat B's defects
   to close; nothing in this design should be minuted as
   addressing them.
