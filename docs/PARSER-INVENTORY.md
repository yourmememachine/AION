# Parser Inventory — Trust Boundary v3.1, mandate item 4

Date: 2026-11-20. Scope: every place the production packages
(`core/`, `eval/`, `memory/`, `oversight/`, `selfmod/`,
`signing/`, `trust/`) parse JSON or JSON-like artefact documents.
Method: grep for `json.loads` / `json.load` / `JSONDecoder` /
`strict_loads` across those packages (no other JSON parser exists
in them, and no `json.loads` exists anywhere else in the repo
outside `tests/`), code inspection of each loader's hooks and
post-parse validation, and empirical probes: each suspect loader
was fed a fully valid document carrying a bogus FIRST copy of a
duplicated key (real value second — a last-wins parser accepts
and validates it, a strict parser refuses) plus the non-finite
corpus (`NaN`, `Infinity`, `-Infinity`, `1e999`).

## The strict parsing contract

A security-relevant consumer of a signed or integrity-checked
artefact MUST, at parse time — before any schema validation —
refuse:

1. **Duplicate keys**, at any depth (including duplicates that
   only appear after JSON string decoding, e.g. `"a"` vs
   `"\u0061"` — an `object_pairs_hook` sees decoded keys, so this
   is structural).
2. **Non-finite numbers**: the constants `NaN`, `Infinity`,
   `-Infinity` (via `parse_constant`) and float tokens that
   overflow to infinity such as `1e999` / `-1e999` (via a
   `parse_float` hook that checks `math.isfinite`).
3. **Malformed documents**: invalid UTF-8, invalid JSON, and —
   where the format defines them — inexact key sets (missing or
   unknown keys at any level).

Refusal is raised in the consumer module's own corruption error
type, so existing callers' fail-closed handling applies
unchanged. Writers in this codebase always emit canonical JSON
(`allow_nan=False`, unique keys by construction), so the
contract rejects no artefact any writer here can produce;
leniency in the fixed loaders was not load-bearing for backward
compatibility with already-written files, and no compatibility
exception was needed anywhere.

**Consumers bound by the contract** (all rows classified
`strict` or `fixed-this-cycle` below): the trust wire protocol
and client, the verifier's request intake, all three signing
envelope parsers and the state-bytes parser, the manifest and
release-record parsers, both ledger journals and the ship
transaction journal, the budget store, the ledger anchor and
reanchor-audit readers, the loop state loader, the memory store
( state, migration audit, freshness check), the oversight
approval journal, and the self-modification canary journal.
Two protected consumers in `eval/` do not yet meet the
duplicate-key clause and are recorded as findings below; one
consumer in `trust/verifier_main.py` is recorded as a finding
for its owning pod.

## Inventory

| # | Consumer | Artefact | Parser used | Duplicate keys | Non-finite numbers | Exact key sets | Security decision it feeds | Classification |
|---|----------|----------|-------------|----------------|--------------------|----------------|----------------------------|---------------|
| 1 | `trust/protocol.py` `strict_loads` / `decode_request` / `decode_response` | Verifier wire requests & responses | `JSONDecoder` with dup/constant/float hooks + trailing-data check | Refused at parse | Refused at parse | Yes — request, response, error objects | Every verifier decision (gate, sealed eval, attestation issuance) | strict (reference) |
| 2 | `trust/client.py` (`decode_response`, `_error_document`) | Verifier responses | Delegates to `protocol.strict_loads` / `decode_response` | Refused at parse | Refused at parse | Yes (via protocol) | Trusting a verifier result builder-side | strict |
| 3 | `trust/verifier_main.py` request intake | Wire requests | Delegates to `protocol.decode_request` | Refused at parse | Refused at parse | Yes (via protocol) | All verifier modes | strict |
| 4 | `signing/gate_decision.py` `envelope_from_json` | Signed gate-decision envelopes | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — envelope and decision objects | Signature verification; memory commit; ship gate | strict |
| 5 | `signing/attestation.py` `attestation_envelope_from_json` | Signed verifier-attestation envelopes | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes | Attestation verification for ship / commit decisions | strict |
| 6 | `signing/state_snapshot.py` `snapshot_envelope_from_json` | Signed state-snapshot envelopes | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes | Snapshot verification (state integrity) | strict |
| 7 | `signing/state_snapshot.py` `parse_state_bytes` | Loop `state.json` bytes presented for signing / verification | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Partial by design: extracts the bound facts; the state byte hash binds everything else | Facts a state snapshot signs; release pre-ship comparison | strict |
| 8 | `trust/manifest.py` `manifest_from_json` | Build manifests | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — manifest, file entries, review record | Ship authorisation (manifest hash binding) | strict |
| 9 | `trust/release.py` `release_from_json` | Release records | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — record and pre-ship state | Ship gate (pre-ship state snapshot comparison) | strict |
| 10 | `trust/ledger.py` `HashChainJournal._load` — `ShipLedger` | Ship ledger journal (`ship-ledger.json`) | **Was plain `json.loads`; now dup/constant/float hooks raising `CorruptLedgerError`** | **Were accepted last-wins (verified: bogus-first duplicate entry `kind` and top-level `entries` loaded); now refused at parse** | Were accepted by the parser (refusal leaked as a raw `ValueError` from canonical re-hashing, outside the `LedgerError` contract); now refused at parse | Yes — top-level `{entries}` and per-entry keys (pre-existing) | Replay protection: single-use burns for ship decisions | **fixed-this-cycle** |
| 11 | `trust/ledger.py` `HashChainJournal._load` — `SigningLedger` | Signing ledger journal (`signing-ledger.json`) | Same loader as #10 | Same as #10 | Same as #10 | Yes (pre-existing) | Issuance audit: a signature with no ledger entry evidences a second signer | **fixed-this-cycle** |
| 12 | `trust/shiptx.py` `ShipTxJournal` | Ship transaction journal (`ship-tx.json`) | Inherits `HashChainJournal._load` (#10) | Same as #10 | Same as #10 | Yes (pre-existing) | Ship recovery: settling crashed ships exactly once | **fixed-this-cycle** |
| 13 | `trust/shipcheck.py` `check_ship` / `record_ship` / `recover_ship_tx` | Ship ledger, ship-tx journal, loop state, envelopes, manifest, release | No parser of its own: delegates to #4/#5/#8/#9/#10/#12/#17 | Refused at parse (via delegates, after this cycle's fixes) | Refused at parse (via delegates) | Via delegates | The ship decision itself | strict-by-delegation (after fix) |
| 14 | `trust/budgets.py` `BudgetStore._load` | Sealed-eval budget store (`budgets.json`) | **Was plain `json.loads`; now dup/constant/float hooks raising `BudgetError(budget_store_corrupt)`** | **Were accepted last-wins (verified: bogus-first duplicate `chain_hash` loaded and passed the chain check); now refused at parse** | Were accepted by the parser and refused only incidentally by downstream int/type validation; now refused at parse | Yes — top, identity, proposal, transcript, family keys (pre-existing) | Budget accounting: extraction caps, replay / adaptive-query latches inside the verifier | **fixed-this-cycle** |
| 15 | `trust/anchoring.py` `_read_anchor` / `load_anchor` | Ledger anchor files | **Was plain `json.loads`; now dup/constant/float hooks, mapped to `anchor_malformed`** | **Were accepted last-wins (verified: bogus-first duplicate `head` loaded); now refused at parse** | Were accepted by the parser and refused only by downstream type checks; now refused at parse | Yes (pre-existing) | Anchor verification: rollback detection for both ledgers | **fixed-this-cycle** |
| 16 | `trust/anchoring.py` `_read_audit` / `load_reanchor_audit` | Reanchor audit files | Same fix as #15, mapped to `reanchor_audit_malformed` | Same as #15; now refused at parse | Same as #15; now refused at parse | Yes — file and entry keys (pre-existing) | Audit-chain integrity for forced re-pins | **fixed-this-cycle** |
| 17 | `core/loop.py` `CoreLoop._load` | Loop state (`state.json`) | `json.loads` with constant/float hooks (pre-existing) + **dup hook added this cycle** raising `CorruptStateError` | **Were accepted last-wins (verified: duplicate `cycle_seq` 999-then-0 loaded) — a live differential against #7, which parses the same bytes strictly; now refused at parse** | Refused at parse (pre-existing) | Partial (pre-existing, unchanged): required fields/types validated, unknown keys tolerated | State integrity; shipcheck joins ship transactions and release snapshots against this history | **fixed-this-cycle** |
| 18 | `memory/store.py` `MemoryStore._load` | Memory store (`memory.json`) | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — base keys ± `security_mode` (legacy files without the field still load, by design) | Store commit decisions; persisted security mode (`signed_only` vs `unsigned`) | strict |
| 19 | `memory/store.py` `_load_migration_audit` / `verify_migration_audit` | Security-mode migration audit journal | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes | Whether a security-mode change was authorised and recorded | strict |
| 20 | `memory/store.py` `MemoryStore._disk_changed` | Memory store (freshness re-read) | Same strict hooks as #18 | Refused (reads as changed) | Refused (reads as changed) | Yes | Refusing to overwrite externally changed state | strict |
| 21 | `oversight/approval.py` `ApprovalManager._load` | Human-approval journal | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — top level; entries validated | Whether a protected change was human-approved | strict |
| 22 | `selfmod/canary.py` `CanaryManager._load` | Canary journal | `json.loads` with dup/constant/float hooks | Refused at parse | Refused at parse | Yes — top level; entries validated | Self-modification commit / rollback decisions | strict |
| 23 | `eval/registry.py` `EvalRegistry._load` | Sealed evaluation registry (`registry.json`) | `json.loads` with constant/float hooks, **no duplicate-key hook** | **ACCEPTED last-wins (verified: valid registry with bogus-first duplicate `public_version` loads)** | Refused at parse | Yes — top level, items, access-log entries (post-parse) | Sealed-eval integrity; the verifier refuses an untrusted registry | **protected-finding** (see below) |
| 24 | `eval/registry.py` `EvalRegistry._disk_changed` | Registry (freshness re-read; reads `state_digest` only) | **Plain `json.loads`** | Accepted last-wins | Accepted by the parser (a non-finite token elsewhere is invisible to this read) | No (single field read) | Freshness guard behind #23's save path | **protected-finding** (see below) |
| 25 | `eval/calibration.py` `CalibrationLog._load` | Reviewer calibration log | `json.loads` with constant/float hooks, **no duplicate-key hook** | **ACCEPTED last-wins (verified: bogus-first duplicate entry `score` loads; the entry hash covers the last-wins parse)** | Refused at parse | Entries yes; top level partial | Calibration scores feeding reviewer weighting | **protected-finding** (see below) |
| 26 | `trust/verifier_main.py` `_read_budgets_anchor` | Budgets anchor file (`budgets-anchor/1`) | **Plain `json.loads`** | Accepted last-wins | Accepted by the parser (a numeric `head` then fails the string/length check) | No — only `v` and `head` checked; extra keys tolerated | Pins the budget-store head at verifier startup (budget accounting integrity) | finding — owned by the `verifier_main` pod; not edited by this cycle's parser pod |
| 27 | `trust/attestation.py` | Sealed-eval attestation records | No JSON parser: operates on record dicts; the JSON boundary is `protocol.strict_loads` (#1) | n/a (inherits #1) | n/a (inherits #1) | Payload keys rebuilt and compared in `verify_eval_attestation` | Attestation verification inside the verifier | non-security-parser — inherits strict boundary, with reasons |
| 28 | `eval/factory.py`, `eval/gate.py` | — | No JSON parsing (in-memory objects and the registry API only) | n/a | n/a | n/a | Gate decisions are computed, not parsed | non-security — no parser, with reasons |
| 29 | `memory/reuse.py` | — | No JSON parsing (existence checks; delegates to #18/#23 loaders) | n/a | n/a | n/a | — | non-security — no parser, with reasons |
| 30 | `memory/solver.py` | — | Serialises only (`json.dumps` for hashing); parses nothing | n/a | n/a | n/a | — | non-security — no parser, with reasons |
| 31 | `trust/pathpolicy.py` | — | No JSON parsing (path canonicalisation) | n/a | n/a | n/a | Path policy is enforced on strings, not documents | non-security — no parser, with reasons |
| 32 | `selfmod/canary.py` tree / snapshot byte reads | Working-tree and snapshot files | Raw bytes hashed and compared; never JSON-parsed | n/a | n/a | n/a | Tamper evidence is the byte hash itself | non-security — not a document parser, with reasons |
| 33 | `signing/gate_decision.py` key-file loader | Signing key files | Hex text (`bytes.fromhex` after strip); not JSON | n/a | n/a | n/a | Key material loading | non-security — outside the JSON contract, with reasons |

## Protected findings (eval/ — not edited by this pod)

**Finding P-1 (`eval/registry.py`, `EvalRegistry._load` and
`_disk_changed`).** Wording for the protected-change proposal:
"`EvalRegistry._load` rejects non-finite numbers at parse time
(`parse_constant` / `parse_float` hooks) but has no
`object_pairs_hook`, so duplicate keys are silently resolved
last-wins; verified 2026-11-20: a valid `registry.json` carrying
a bogus first `"public_version": 999` duplicated before the real
value loads without error. The freshness check `_disk_changed`
uses a plain `json.loads` and reads only `state_digest`. Because
the registry's `state_digest` and access-log chain are recomputed
over the last-wins parse, a writer of the registry file gains
nothing from a duplicate they could not gain by editing values
directly and recomputing the digest — the residual risk is
differential: any strict consumer of `registry.json` (for
example a future offline inspection tool built on
`protocol.strict_loads`) will refuse documents this loader
accepts, and the two will disagree about the registry's contents
in the meantime. Recommended protected change: add an
`object_pairs_hook` duplicate rejection to `_load` (raising
`CorruptRegistryError`, mirroring `memory/store.py`) and use the
same strict parse in `_disk_changed`."

**Finding P-2 (`eval/calibration.py`, `CalibrationLog._load`).**
Same shape as P-1: non-finite numbers are refused at parse time
but duplicate keys are accepted last-wins; verified 2026-11-20
with a bogus-first duplicate entry `score`. Recommended
protected change: add the same `object_pairs_hook` rejection
(raising `CorruptCalibrationError`).

## Differential tests

`tests/test_trust_parser_inventory.py` exercises the real load
path of every fixed consumer and the principal strict consumers
with the ambiguous corpus, including the same-artefact agreement
pair: the loop state bytes are fed to both `CoreLoop` and
`parse_state_bytes`, which must agree on the valid document and
both refuse every ambiguous one; the ship-ledger, signing-ledger
and ship-transaction journals are each exercised through the
shared `HashChainJournal` loader they all inherit.
