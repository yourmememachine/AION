# Cycle 25 — Design A (Seat A): Independent supersession authorisation

> **Cycle 26 claim-narrowing note.** This design record's
> over-claim phrasing (including §1's claim block and
> §6's pacing line, fixed in place below, and §§2, 3
> and 7, also narrowed in place in the cycle-26 fix
> round) is superseded as claim wording by the canonical
> cycle-26 sentence — the mechanism described here is unchanged:
>
> "Supersession requires a separately invoked, cryptographically independent approval operation — a standalone tool invocation, with its own inputs, producing its own signed artefact under its own dedicated key — outside the adopter's automated recovery path. The mechanism does not establish that the invocation was performed by a human, nor that no other unattended automation invoked the tool."
>
> Cycle 26 also adds an interactive confirmation gate to
> the approval tool's `approve` command (typed confirmation
> required; no non-interactive override exists); that gate
> does not prove human deliberation either. See
> `internal/DECISION-CONSUMPTION-HEAD.md` Addendum 6.

**Mandate:** `internal/CROSS-CHECK-18.md` — seat-gpt FIX on Q1, the
sole remaining blocker for cycles 14–16. Cycle 24 built a
separately *signed/journaled* supersession decision, but
`PinAdopter` auto-requests it after a refusal, so it is not a
separately *authorised* one. Seat-gpt's five minimum criteria
are the spec for this cycle:

(i) supersession requires a genuinely independent authorisation
event binding the abandoned head + the replacement candidate +
the exact movement + the original failed consumption attempt;
(ii) the approval is independently recorded and verified BEFORE
the supersession envelope (decision) issues; (iii) the verifier
refuses to issue merely because the adopter auto-requests after
a refusal; (iv) regression proof an ordinary recovery cannot
self-escalate; (v) restoration tests exercise the independently
authorised route.

Seat-gemini's Q1 condition also binds: **the mechanism's name
must match what it enforces at each stage** (§9 relabelling).

This document is the contract for seats B (verifier wiring) and
C (adopter stop-and-report). Seat A ships the artefact library
and the approval tool (§10 lists the exact signatures B and C
build against).

---

## 1. The precise trust claim (verbatim wording for all docs)

> **Supersession independence in cycle 25 is independence at the
> authorisation-event level, and nothing more.** A supersession
> decision can be issued only against a supersession *approval
> artefact* that (a) is signed under a dedicated **approver key**
> — a third Ed25519 key, distinct from the snapshot signing key
> and from the verifier's ceremony seed; (b) is produced by a
> **separate tool invocation** (`trust.supersession_approval_tool`,
> §3) with its own CLI, its own inputs and its own seed file,
> outside any adopter or verifier code path; and (c) binds the
> abandoned head movement, the replacement candidate, the exact
> (old → new) movement, and the original failed consumption
> attempt (§5). The verifier verifies the approval **before**
> journaling any supersession decision, and the adopter's code
> path contains no route to mint one: it never imports the
> tool module, never receives the approver seed path in its
> configuration or environment, and on `ceremony_supersede_required`
> it **stops and reports pending-approval** instead of requesting
> a decision (seat C's contract, §8).
>
> **What is NOT claimed:** the approver is not a separate human
> and not a separate OS user. On this same-user VM the operator
> and the approver are the same person running a second command,
> via a separately invoked approval operation. The guarantee is
> that supersession cannot happen as a *side effect* of an
> automated recovery flow: it requires a distinct, signed,
> single-use, expiring artefact created by an operation that no
> running service performs on its own behalf. A fully malicious
> same-user process remains outside the prototype's claim,
> exactly as in `trust/verifier_main.py`'s honesty statement —
> such a process could read the approver seed file directly; the
> control is that no *code path* short of that separately
> invoked approval operation mints an approval. (Cycle 26: the
> mechanism does not establish that the invocation was performed
> by a human, nor that no other unattended automation invoked
> the tool — see the claim-narrowing note at the top.)

Every doc seat B/C touches (mode docstring, adopter docstring,
decision addendum) must carry this claim in substance and must
not upgrade it ("independent approver", "second operator",
"four-eyes") anywhere.

---

## 2. Shape of the solution, in one paragraph

A new signed artefact type, the **supersession approval**
(`trust/supersession_approval.py`, verify-side primitives only),
is minted exclusively by a new standalone CLI,
`python -m trust.supersession_approval_tool` (§3), signing with
an **approver seed** that only that tool ever loads. The flow
becomes three-stage: (1) the adopter's consume attempt refuses
pre-commit with `ceremony_supersede_required`; the adopter
**stops**, writes a *pending-supersession report* (§7) and
surfaces it — it does not call `ceremony_supersede`; (2) the
operator, via a separate approval invocation, runs the approval tool
against the pending report; the tool signs an approval artefact
into the adopter's approval inbox (§6); (3) on its next run the
adopter finds the approval in its inbox and presents it —
together with the same envelope — to a widened
`ceremony_supersede` request; the verifier verifies the approval
(signature, expiry, full binding against its **own** journals,
single-use) **before** the existing shape gate and decision
commit, and records the approval's id and payload hash in the
supersession decision entry. No approval, no decision — there
is no request shape the adopter can send that skips stage (2).

---

## 3. The approval tool

**Module:** `trust/supersession_approval_tool.py` — the ONLY
module in the repo that calls `ed25519.sign` for approvals.
**Invocation:** `python -m trust.supersession_approval_tool …`
with three subcommands:

```
generate-key  --seed-path <abs path> [--force-refuse-existing]
public-key    --seed-path <abs path>            # prints hex64 pubkey + key_id
approve       --seed-path <abs path> --approver-id <id>
              --pending-report <file> --out <file>
              [--ttl-seconds N]                 # default 900, cap 3600
```

- `approve` reads the pending-supersession report (§7), builds
  the binding projection **from the report's fields**, signs,
  and writes the approval artefact JSON to `--out` with mode
  0600, refusing to overwrite an existing file (a second
  approval for the same report is a new separate approval invocation: delete
  or use a new `--out` name; the verifier's single-use rule
  makes a stale duplicate inert anyway).
- The tool performs **no network, verifier or journal access**.
  It cannot check that the report is truthful — it does not
  need to: the verifier re-derives every bound fact from its
  own journals (§8), so a fabricated or stale report yields an
  approval that simply does not match and is refused. The
  tool's job is to make the approval a separate, signed operation, not to
  be a second verifier.
- The tool refuses (exit 2, `SigningError` text on stderr): a
  seed in `REFUSED_TEST_SEEDS` (imported from
  `signing.ceremony_authorisation`, the single source); a report
  whose `refusal_code` is not `ceremony_supersede_required`; a
  report naming reason `burned_unadopted` (an ordinary recovery
  is not a supersession and must never acquire an approval —
  criterion (iv) at the minting surface); TTL outside
  [60, 3600].

**Why a separate module, not a flag on an existing CLI:** the
auditable property seat-gpt's criterion (i)/(iii) needs is
"the adopter cannot create one". That is checkable by import
and source scan only if create/sign lives in exactly one named
place. Seat A's tests pin: `trust/pin_adoption.py`,
`trust/client.py` and `trust/verifier_main.py` contain no
import of `supersession_approval_tool`, and
`trust/supersession_approval.py` contains no `ed25519.sign`
call.

---

## 4. Key custody

Three distinct Ed25519 keys now exist; no two may be equal, and
the equalities that are *checkable* are checked:

| key | seed held by | public key known to |
|---|---|---|
| snapshot signing key (HMAC) | verifier only | — |
| ceremony seed | verifier only (`AION_CEREMONY_SIGNING_SEED_PATH`) | ceremony/client pin |
| **approver seed (new)** | **the approval tool's invocation environment only** | **verifier (new env var, §4.2)** |

### 4.1 Approver seed

- A 32-byte Ed25519 seed in a hex file under the exact
  discipline of `signing.ceremony_authorisation.load_ceremony_seed`
  (owner-only mode, O_NOFOLLOW single-fd read, size cap, no
  symlink components, never inside this repo): the tool's
  `load_approver_seed` mirrors that loader's checks but returns
  the tool-side type `SupersessionApproverKey`, so approver
  material can never be passed where a `CeremonySigningKey` is
  expected (type separation, the cycle-20 pattern).
- Its path reaches the tool via the tool's own CLI flag
  `--seed-path` or the tool-process env var
  **`AION_SUPERSESSION_APPROVER_SEED_PATH`**. This name is
  deliberately **not** a verifier variable: it is not in the
  wrapper allowlist (§4.3), so if it is mistakenly placed in
  the verifier env FILE, `run-verifier.sh` HARD-FAILS the
  launch (any non-allowlisted env-file key refuses the launch;
  it is not silently discarded) — the discarded case is only
  an occurrence in the invoking shell, which the wrapper's
  `env -i` clean environment drops — and
  `trust/wiring.py` refuses it as an unknown key in a production
  client env. The adopter's configuration must never carry it;
  seat C's wiring must not add it to any adopter env allowlist.
- Provisioning: `generate-key` (O_EXCL, 0600, independent
  `secrets.token_bytes` draw — never derived from either other
  key). Deployment `setup.sh` (seat B/deploy follow-up) gains a
  step that generates it outside the verifier home and prints
  the public key for the verifier env file.
- Seed-equality defence in depth: the tool refuses
  `REFUSED_TEST_SEEDS`; the verifier, which holds both public
  keys, refuses startup if the approver public key equals the
  ceremony public key (§4.2 check (c)) — seed equality would
  imply public equality, so the one seed-collision the verifier
  *can* detect is detected. No stronger claim is made (the
  verifier never sees either seed).

### 4.2 How the verifier gets only the public key — ONE new env var

**`AION_SUPERSESSION_APPROVER_PUBLIC_KEY`** — the hex64 (64
lowercase hex chars) encoding of the approver's 32-byte Ed25519
public key. Public material only; it is not a secret and needs
no file discipline. `_load_config` (seat B):

(a) parses it beside the ceremony seed block: present-but-not-
hex64 → `verifier_misconfigured` in both modes; (b) derives a
`SupersessionApproverPublicKey` via
`approver_public_key_from_hex` (§10) and stores it on `_Config`
as `config.supersession_approver_key`; (c) refuses startup if
its bytes equal the ceremony signing key's public key;
(d) production rule, mirroring the consumption-anchor rule:
production **with the ceremony seed configured** requires the
approver public key (absent → `verifier_misconfigured`),
because a production verifier that can consume supersede-shaped
envelopes but can never authorise one is a wedge, not a policy;
research + absent loads as `None` and the supersede mode refuses
per-request with the new code
`ceremony_supersede_approval_unconfigured` (§8 step 0).

### 4.3 EVERY place the allowlist must change (19 → 20)

One new verifier env var means the allowlist copies move
together — enumerated exhaustively (grep-verified against
`AION_CEREMONY_CONSUMPTION_ANCHOR_PATH`'s footprint, the last
var added):

1. `deploy/verifier-identity/run-verifier.sh` — `ALLOWED_KEYS`
   array (19 → 20).
2. `deploy/verifier-identity/health_check.py` — its literal
   `ALLOWED_KEYS` copy.
3. `trust/wiring.py` — `ALLOWED_ENV_KEYS` frozenset + the two
   docstring mentions of "19 names". (`trust/runner.py` imports
   `ALLOWED_ENV_KEYS`; it follows automatically — no literal
   change, noted so nobody greps for a fourth copy there.)
4. `trust/verifier_main.py` — module docstring env list,
   `_Config` field, `_load_config` parsing (§4.2).
5. `deploy/verifier-identity/setup.sh` — write the var into the
   generated env file (from the `public-key` output at
   provisioning).
6. `deploy/verifier-identity/README.md` — env documentation.
7. Tests that pin the count/set and must be updated by seat B:
   `tests/test_trust_wiring.py` (asserts `len == 19` and wrapper
   set-equality), `tests/test_verifier_deploy.py` (wrapper vs
   health-check copy equality), `tests/test_trust_production_deploy.py`
   (env fixtures), and harness env builders
   (`tests/cycle23_harness.py` pattern) if they construct
   production envs.

`AION_SUPERSESSION_APPROVER_SEED_PATH` appears in **none** of
these places — that absence is part of the design and seat A's
tests pin its absence from `trust/wiring.py`'s allowlist.

---

## 5. Artefact format and binding

Module `trust/supersession_approval.py` mirrors
`signing/ceremony_authorisation.py`'s construction exactly in
kind: an allowlisted payload projection, canonical JSON
(`signing.gate_decision._canonical`), `payload_hash = sha256`,
an id derived from (domain, payload_hash, key_id), and an
Ed25519 signature over the newline-joined blob
`domain \n alg \n key_id \n payload_hash`. Domain:
`signed-supersession-approval-v1`; purpose:
`pin-ceremony-supersession-approval`; alg: `ed25519` (pinned in
the projection, as ceremony v2 pins it).

### 5.1 Payload fields (the signed projection — exact key sets)

```
v, alg, purpose, approver_id, key_id,
abandoned:      {authorisation_id, ceremony_id,
                 old_cycle_seq, old_payload_hash,
                 new_cycle_seq, new_payload_hash},
replacement:    {authorisation_id, ceremony_id, reason,
                 operator_id,
                 superseding_old_cycle_seq,
                 superseding_old_payload_hash,
                 candidate_cycle_seq, candidate_payload_hash},
failed_attempt: {attempted_authorisation_id, refusal_code,
                 head_authorisation_id, head_entry_seq,
                 head_entry_hash},
approved_at, expires_at
```

### 5.2 How the four required bindings map

- **(a) the abandoned head movement** — `abandoned.*`: the
  consumption head entry's authorisation id, ceremony id and
  its full (old → new) pair, copied from the head entry.
- **(b) the replacement candidate** — `replacement.candidate_*`
  plus the replacement envelope's authorisation/ceremony ids.
- **(c) the exact movement** — both movements, in full: the
  abandoned (old → new) pair above, and the replacement
  movement `replacement.superseding_old_* → candidate_*` (the
  new envelope's old pin and its candidate).
- **(d) the original failed consumption attempt** —
  `failed_attempt.*`: the attempted envelope's authorisation id
  (== `replacement.authorisation_id`; the duplication is
  deliberate, so the attempt is identified as an attempt, not
  merely as an envelope), the refusal code that ended it
  (`ceremony_supersede_required` — the only value the
  projection accepts), and the head it was refused against:
  the head entry's authorisation id, its journal `seq`, and
  its `entry_hash`. The seq+hash pair pins the attempt to one
  exact journal state: any head movement after the refusal
  changes all three head facts and the approval goes stale
  (§6), which is the desired semantics — an approval is for
  *that* refusal against *that* head, not a standing licence.

`operator_id` is bound inside `replacement` because the
decision journal records it and `check_head` binds it; the
approval must cover every field the decision will assert.

### 5.3 Wire form

The artefact dict (JSON file / request field) is the payload
fields plus `payload_hash`, `approval_id`, `signature` (hex128)
— the ceremony envelope's serialisation pattern, with strict
exact-key-set parsing in `supersession_approval_from_dict`
(unknown or missing keys raise `SigningError`).

### 5.4 What the approver signs *about*

The approval is the verifier-about-operator pattern one level
up: the approver signs *about* a reported refusal. The report
is adopter-produced and therefore untrusted input to the tool;
the signature does not launder it. Truth enters at the
verifier, which recomputes (a)–(d) from its own consumption
journal head, its issuance journal and the presented envelope
(§8 step 8b). An approval over fabricated facts verifies
cryptographically and still refuses — binding mismatch, folded
into the single shape code.

---

## 6. Storage, discovery, expiry, single-use

- **Approver side:** the tool writes one JSON file per approval
  (0600, no overwrite) wherever `--out` names; the operator
  delivers it to the adopter's inbox by the deployment's normal
  file channel. This hand-off *is* the out-of-band step; no
  service performs it.
- **Adopter side (seat C's surface, specified here):** an
  **approval inbox directory** in the adopter's own config
  (a new adopter-side setting, NOT a verifier env var — the
  verifier never learns this path). Files are named
  `<approval_id>.json`. On start-up after a pending-supersession
  report, the adopter scans the inbox, parses candidates with
  `supersession_approval_from_dict`, and selects the one whose
  `replacement.authorisation_id` equals the pending envelope's
  id and whose `failed_attempt.head_entry_hash` equals the
  pending report's. Unparseable files are ignored (never
  fatal); a selected approval is presented once (§8) and the
  file is then moved aside by the adopter regardless of outcome
  (a refused approval is evidence, not a retry token).
- **Verifier side:** the verifier stores no approval files. It
  receives the artefact in the request (§8), verifies it, and
  **records it** by copying `approval_id`, `approval_payload_hash`
  and `approver_key_id` into the supersession decision entry
  (seat B widens `CeremonySupersessionLedger.EXTRA_KEYS` by
  those three fields — a journal born in cycle 24 with no
  external anchor yet, so the widening is a load-coherence
  change, not a migration of anchored data; entries written
  before cycle 25 do not exist in any production home because
  cycles 14–16 are held). Criterion (ii)'s "independently
  recorded" is discharged by this journal record plus the
  existing anchored signing-ledger mirror of the decision.
- **Expiry:** `approved_at`/`expires_at` in the projection;
  TTL default 900 s, hard cap 3600 s (the one documented
  deviation from the ceremony envelope's 900 s cap: an approval
  is a separately invoked operation — report, separate tool
  invocation, adopter
  re-run — and 900 s would make the honest path racy; the
  exposure is bounded by single-use + full binding + head
  staleness, §5.2(d)). Effective window, stated honestly
  (cycle-25 fix round, r6): in practice the usable approval
  window is bounded by the candidate envelope's REMAINING TTL
  — the envelope's own 900 s cap runs from its issuance, which
  precedes the failed consume, the report, the completion step
  (§7) and the tool run — so an approval minted late in the
  envelope's life may have far less than its own TTL of usable
  time, or none. Verification applies the ceremony
  temporal discipline: `signed_in_future` beyond
  `CLOCK_SKEW_SECONDS` (300) or `expired` are the temporal
  reasons, carved out by the verifier exactly as for envelopes.
- **Single-use:** an approval is spent by the decision it
  enables. Enforcement is verifier-side and twofold: the
  existing single-decision-per-envelope rule (a second decision
  for the envelope refuses) and a new **single-use-per-approval**
  rule — `approval_id` may occur in at most one decision entry
  (checked at supersede step 8b against the supersession
  journal, and at journal load, mirroring the duplicate-
  authorisation load rule). Replay against a *different*
  envelope is already impossible by binding (§5).

---

## 7. The pending-supersession report (adopter → approver input)

When the adopter stops (seat C), it writes a report file —
this is the tool's `--pending-report` input. Exact fields:

```json
{"report": "pending-supersession/1",
 "refusal_code": "ceremony_supersede_required",
 "envelope": { …the full ceremony envelope dict… },
 "operator_id": "<id>",
 "head": {"authorisation_id": …, "ceremony_id": …,
          "old_cycle_seq": …, "old_payload_hash": …,
          "new_cycle_seq": …, "new_payload_hash": …,
          "seq": …, "entry_hash": …},
 "reported_at": "<iso8601>"}
```

Provenance honesty: `head` is what the *adopter* believes the
head to be (from its own ceremony history view); the tool
copies it into the signed projection verbatim, and the
verifier's re-derivation (§8) is what makes a wrong report
harmless. The report is also the operator's human-readable
surface: it names the envelope, the head movement to be
abandoned and the candidate to be favoured — the three things
the separate approval invocation is *about* — before any signature exists.

Completion step, disclosed precisely (cycle-25 fix round,
r6): the adopter cannot know the verifier journal's `seq` /
`entry_hash` for the head entry, so the report it writes
carries those two `head` fields as null. The approver
completes them by copying them from the verifier's
consumption journal — a transcription step inside
the separate approval invocation itself (the tool performs no journal access
by design, so the approver is the data bus for exactly these
two fields). A wrong transcription is inert, never a
misapproval: the approval tool's signing projection refuses
nulls, and the verifier re-derives the head seq/entry_hash
from its own journal and binding-checks the approval against
them, refusing rather than misapproving on any mismatch.

---

## 8. Verifier checks, in order (seat B's contract)

`_mode_ceremony_supersede` keeps cycle-24 steps (1)–(10) and
changes exactly these points; the request body key set widens
to `{"operator_id", "signed_authorisation", "supersession_approval"}`:

0. **New config gate (before step 1's existing gates):**
   `config.supersession_approver_key is None` →
   `_config("ceremony_supersede_approval_unconfigured", …)`.
   A verifier with no approver key can never issue a decision;
   there is no fallback path.
5b. **Approval verification — after envelope verification
   (step 5), before any journal read** (so an unapproved
   request gets no state oracle, mirroring step 4's rationale):
   parse via `supersession_approval_from_dict` (`SigningError`
   → `malformed_request`); then
   `verify_supersession_approval(approval,
   public_key=config.supersession_approver_key,
   expected_approver_id=None)` — approver identity is the key
   pin itself (`unknown_key` covers a foreign key); any
   non-empty reasons collapse exactly as envelope reasons do:
   temporal-only → `ceremony_supersede_approval_expired`;
   otherwise the single code
   `ceremony_supersede_approval_invalid` (exit 2). No per-reason
   output anywhere, stderr included.
8b. **Binding + single-use — folded into step 8**, after the
   shape gate computes `head_entry`, every failure the single
   existing code `ceremony_supersede_unproven` (no new oracle):
   `approval_binding_mismatches(approval,
   abandoned_entry=head_entry, head_entry_seq=head_entry["seq"],
   head_entry_hash=head_entry["entry_hash"], signed=signed)`
   (§10) must return `()`; and no existing decision entry may
   carry this `approval_id`. The helper checks, in its own
   order: abandoned id/ceremony/pair == head entry; replacement
   ids/ceremony/reason/operator == envelope; superseding old
   pin == envelope old pin; candidate == envelope candidate;
   failed attempt: attempted id == envelope id, refusal code ==
   the constant, head id/seq/hash == the head entry's.
9. **Commit (unchanged step, widened record):**
   `append_decision` additionally records `approval_id`,
   `approval_payload_hash`, `approver_key_id` from the verified
   approval.

Client (seat B/C boundary): `VerifierClient.ceremony_supersede`
gains a required third parameter `approval_dict`; the adopter
calls it **only** when it holds an inbox approval — the
cycle-24 auto-request call is deleted, not gated (criterion
(iii) is a property of there being no other call site; seat C
§8 of its design owns the stop-and-report flow, and the
client's docstring must say the method is never called in
response to a refusal, only in presentation of an approval).

**Criterion (iv) — ordinary recovery cannot self-escalate:**
three independent layers, each testable: the shape predicate
already excludes `burned_unadopted` envelopes, so no approval
can ever make a recovery consume as a supersession; the tool
refuses to mint an approval over a `burned_unadopted` report;
and the approval's binding includes the envelope's reason, so
an approval minted for a primary cannot be re-bound to a
recovery envelope. Seat B/C regression tests: a recovery
consume after a refusal never reaches `ceremony_supersede`
(adopter call-count assertion), and a supersede request for a
recovery envelope with a *validly signed* approval still
refuses `ceremony_supersede_unproven`.

**Criterion (v):** restoration tests (seat C) must drive the
full route — refusal → pending report → tool-minted approval →
presentation → decision → consume → adopt — using the real
tool module's signing function in-process as the tool's test
double (the artefact must be genuinely signed; a fabricated
decision or a stubbed approval check does not satisfy (v)).

---

## 9. Relabelling (seat-gemini's Q1 condition)

Names must match enforcement at each stage, effective cycle 25:

- The consume refusal `ceremony_supersede_required` keeps its
  code (wire compatibility) but its documented meaning becomes:
  "supersession **pending independent approval**" — the adopter
  exception/phase names become `…PendingApproval` (seat C picks
  exact names; `CeremonySupersedeRequired` as a *terminal* name
  goes away).
- Cycle 24's decision is renamed in prose from "separately
  authorised" to **"independently approved supersession
  decision"** only where the cycle-25 approval gate is in the
  path; Addendum 4's disclosed reading is superseded by a
  cycle-25 addendum carrying §1's claim verbatim in substance.
- The approval artefact is never called an "authorisation" in
  new prose: it is an **approval**; the envelope remains the
  authorisation; the journal entry remains the decision. Three
  artefacts, three names, three acts.

---

## 10. What seat A ships (this seat, now)

**`trust/supersession_approval.py`** — verify-side primitives
only. No signing function, no seed type, no seed loader; safe
for the verifier, the client and the adopter to import.

```python
SUPERSESSION_APPROVAL_DOMAIN = "signed-supersession-approval-v1"
PURPOSE_SUPERSESSION_APPROVAL = "pin-ceremony-supersession-approval"
REFUSAL_CODE_SUPERSESSION_REQUIRED = "ceremony_supersede_required"
APPROVAL_TTL_DEFAULT_SECONDS = 900
APPROVAL_TTL_MAX_SECONDS = 3600

@dataclass(frozen=True)
class SupersessionApproverPublicKey:  # public bytes + derived key_id only
    public_key: bytes; key_id: str

@dataclass(frozen=True)
class SignedSupersessionApproval:
    approver_id: str; key_id: str
    abandoned: dict; replacement: dict; failed_attempt: dict
    approved_at: str; expires_at: str
    payload_hash: str; approval_id: str; signature: str
    alg: str = "ed25519"
    def payload(self) -> dict: ...

def approver_public_key_from_hex(text) -> SupersessionApproverPublicKey
def supersession_approval_payload(*, approver_id, key_id, abandoned,
    replacement, failed_attempt, approved_at, expires_at,
    alg="ed25519") -> dict
def approval_id_for(payload_hash, key_id) -> str
def verify_supersession_approval(signed, *, public_key,
    expected_approver_id=None, now=None) -> tuple   # () == valid;
    # reasons: key_id_inconsistent, unknown_key, malformed_payload,
    # payload_hash_mismatch, approval_id_mismatch,
    # signature_mismatch, approver_mismatch, signed_in_future, expired
def approval_binding_mismatches(approval, *, abandoned_entry,
    head_entry_seq, head_entry_hash, signed) -> tuple
    # () == fully bound; mismatch names: abandoned_mismatch,
    # replacement_mismatch, movement_mismatch, failed_attempt_mismatch
def supersession_approval_to_dict(signed) -> dict
def supersession_approval_from_dict(data) -> SignedSupersessionApproval
def supersession_approval_to_json(signed) -> str
def supersession_approval_from_json(text) -> SignedSupersessionApproval
```

`abandoned_entry` is a consumption-journal entry dict (the
verifier's head entry); `signed` is a
`SignedCeremonyAuthorisation`. The binding helper is pure: no
I/O, no journal access — seat B passes what it derived.

**`trust/supersession_approval_tool.py`** — the create side,
imported by nothing in the running system:

```python
@dataclass(frozen=True)
class SupersessionApproverKey:  # seed + public + key_id; repr never leaks seed
    ...
def load_approver_seed(path, *, forbidden_roots=()) -> SupersessionApproverKey
def generate_approver_key_file(path, *, forbidden_roots=()) -> SupersessionApproverKey
def approver_public_key_for(key) -> SupersessionApproverPublicKey
def sign_supersession_approval(*, approver_key, approver_id, abandoned,
    replacement, failed_attempt, ttl_seconds=900, now=None)
    -> SignedSupersessionApproval
def build_approval_for_report(*, approver_key, approver_id, report,
    ttl_seconds=900, now=None) -> SignedSupersessionApproval
def main(argv=None) -> int   # generate-key | public-key | approve
```

**Tests:** `tests/test_trust_supersession_approval.py` —
round-trip, tamper/mutation per bound field, wrong-key,
expiry/future, strict key sets, binding-helper mutations
(abandoned pair, candidate, movement, failed attempt head
hash/seq), tool refusals (test seed, recovery report, TTL),
and the auditability pins of §3 (no tool import in adopter/
client/verifier sources; no `ed25519.sign` in the verify
module; approver seed-path var absent from the wiring
allowlist).

**Explicitly not seat A's:** `trust/verifier_main.py`,
`trust/client.py`, `trust/pin_adoption.py`, the ledger widening
(§6), the allowlist edits (§4.3) — seats B and C own those,
building against the signatures above.
