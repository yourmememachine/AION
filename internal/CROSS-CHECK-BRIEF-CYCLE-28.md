# Cross-Check Brief — Cycle 28: Pin-Store History Reconciliation

You are an external reviewer seat for the AION trust-boundary
work. This brief describes what was built in cycle 28, the
design decisions behind it, and the test evidence available.
Questions are at the end.

## Background

The snapshot pin ceremony (cycles 15–24) moves a stored pin
over unobserved snapshot sequences under a verifier-issued,
single-use authorisation. Two histories record those
movements:

- the **pin-store history**: ceremony records kept in the same
  document as the pin, on the adopter side; and
- the **verifier's consumption journal**: an externally
  anchored, hash-chained journal in the verifier home,
  recording every consumed authorisation.

An earlier re-review (cycles 14–16) established that the
pin-store history is a *non-authoritative, restoration-lossy
replica*: restoring an older generation of the store document
silently drops later ceremony records, and the store's own
verified load cannot detect the absence, because it verifies
records that are present and cannot detect a record that is
not there. The consumption journal was named the sole
authoritative ceremony audit history, and the claim wording
in the code was rescoped to say so. What was left open, as a
named follow-up (`pin-store-history-reconciliation`), was the
*detection* branch: reconcile the store history against the
consumption journal so incompleteness is detected and
refused/flagged, not silent — or, alternatively, anchor the
pin-store document head externally.

## What was built

### The reconciliation check (new module)

`trust/history_reconciliation.py` provides a pure function,
`find_missing_history`, and a refusing wrapper,
`reconcile_history`. Given the store history captured for an
adoption attempt, the consumption journal entries, the
supersession journal entries, and the candidate the attempt
is about to adopt, it returns the journal entries that are
*missing* — relevant to the candidate and unaccounted for.
The wrapper raises `HistoryReconciliationRefused`, a
`SigningError` subclass carrying the deterministic code
`pin_store_history_incomplete` and the missing authorisation
ids in journal order.

A consumption entry E is missing iff it is relevant and no
excuse holds:

- **Relevance:** `E.new_cycle_seq < candidate_seq`, or
  `E.new_cycle_seq == candidate_seq` with a different payload
  hash. Entries ahead of the candidate are not reported.
- **ID+pair coverage:** a store record with the same
  authorisation id *and* the same movement pair
  `(old seq/hash, new seq/hash)` (and the same ceremony id
  when the entry carries one) accounts for E. An id-only
  match over a different movement accounts for nothing.
- **Pair coverage:** a store record attesting E's exact
  movement pair under a different authorisation accounts for
  E. This is the recovery shape: a consumed-but-unadopted
  ceremony ("burn") and its recovery ceremony share one pair,
  and the adopted recovery record covers both journal
  entries.
- **Supersession:** a supersession decision accounts for E
  only when it names E's authorisation id as the abandoned
  one *and* its replacement side has landed — the
  replacement's authorisation id is among the store records,
  or the decision's candidate pair is pair-covered by the
  store history, or that pair is exactly the candidate under
  attempt. A decision alone excuses nothing.
- **Known-unadopted head:** E is the consumption journal's
  head entry, its authorisation id is in a caller-supplied
  `known_unadopted_authorisation_ids` list — movements proven
  consumed but never adopted — AND the candidate is at E's
  own sequence. The excuse is head-scoped: the head can move
  past a burn only via that burn's recovery (pair coverage)
  or supersession (bound decision), so a non-head entry
  claimed unadopted is never excused by this rule.
  (Fix round, seat-gpt FIX 0.91: the excuse originally also
  reached candidates strictly beyond the head; that reach
  was removed — see design decision 3.)
- **Genesis baseline:** when the attempt has no old pin (an
  initial anchor, or a genesis after pin loss), prior journal
  entries are the attested loss the genesis responds to, and
  nothing is reported.

Malformed inputs — non-record store entries, journal entries
missing required keys or carrying wrongly typed values
(including boolean sequence numbers), duplicate authorisation
ids in the store history — refuse with `SigningError`. The
check never skips an entry it cannot read.

### Wiring

`trust/pin_adoption.PinAdopter` gains two optional
constructor parameters, `consumption_entries_provider` and
`supersession_entries_provider` (zero-argument callables
returning journal entries, loaded fresh per attempt). When a
consumption provider is configured, `snapshot_and_adopt`
reconciles after the candidate is selected and before
anything is persisted, authorised, or consumed — the one
point every outcome (normal advance, already-current,
ceremony re-anchor, genesis) passes through. The
known-unadopted list is derived from the adopter's own
pending journal (ceremonies it consumed but never adopted).
A provider that raises or returns malformed entries fails
closed as an adoption refusal; it never falls back to
unchecked behaviour.

With no provider configured (the default, and therefore every
pre-existing construction), the adopter behaves exactly as
before this cycle and makes no history-completeness claim.
The production factory (`build_pin_adopter`) accepts the
providers as pass-through arguments but deliberately does
*not* derive them from its environment, even though that
environment names the verifier home: the adopter does not
read the verifier's journals itself, and the providers are
supplied by the composition layer that legitimately holds
both sides. Helper functions in the new module build
providers from a verifier home for that composition layer.
Two docstring sentences (in the pin-store and pin-ceremony
modules) now name the detection and its refusal code; the
authority claims are unchanged.

## Design decisions worth scrutiny

1. **Reconciliation over anchoring.** The alternative branch
   — an external anchor over the pin-store document head —
   was not built. Reasons given: the store lives outside the
   verifier home, so a new anchor kind plus provisioning is a
   larger change; an anchor detects *any* document rollback
   but cannot say *which* ceremony record is missing; and a
   legitimate operator restore of pin + history together
   would trip it even though the consumption head already
   bounds that case.
2. **Detection is wiring-dependent.** As with the ceremony's
   consumption guarantee in an earlier cycle (an
   integrated-system property of the production wiring, not
   of the function alone), the completeness claim exists only
   when real providers are wired. The default adopter is
   unchanged.
3. **The known-unadopted excuse is caller-attested.** In the
   adopter wiring its source is the adopter's own pending
   journal, which lives in the same directory as the pin
   store. A rollback that also loses that journal loses the
   excuse and the check fails closed; a fabricated excuse
   list at the pure-function level could suppress detection
   for the journal head entry only. FIX ROUND (after the
   external round): seat-gpt showed the compound state —
   adopted-line loss in the pending journal combined with a
   store restore — is indistinguishable from a genuine burn,
   so the excuse no longer reaches a candidate strictly
   beyond the head entry at all; it excuses only a candidate
   at the head entry's own sequence, which cannot adopt past
   the head without the verifier's recovery/supersession
   rules. A beyond-head candidate now refuses.

## Test evidence

New file `tests/test_cycle28_history_reconciliation.py`
(27 tests after the external fix round; 23 at the internal
war room):

- Pure-function detection: a middle restoration gap (store
  history [seq 1, seq 4], journal holding an intermediate
  ceremony), a gap at the journal head behind the candidate,
  empty journal, empty history, determinism under shuffled
  input order.
- Excuses, each with a control case that flags without the
  excuse: recovery pair coverage, supersession with the
  replacement record landed (and two negative variants —
  decision without the landed record, decision abandoning a
  different entry), known-unadopted head (and the same entry
  as non-head, not excused), the candidate's own burn.
- Boundaries: entries ahead of the candidate ignored; a
  forked entry at or behind the candidate's sequence flagged;
  genesis baseline.
- Malformed inputs: non-record history entries, missing
  journal keys, boolean sequence, duplicate authorisation ids.
- Adopter integration against a real verifier subprocess:
  a restored pin-store file (genesis generation spliced back
  under a two-entry consumption journal) refuses with
  `pin_store_history_incomplete`, names the missing
  authorisation, and persists nothing; the same scenario
  without providers behaves exactly as before this cycle
  (it stops as supersession-pending, with no completeness
  signal); a wired adopter whose journal matches the store
  proceeds normally, and a failing/malformed provider fails
  closed.
- Fix-round crash-injection (seat-gpt's scenario, written
  failing-first): an adopted gap ceremony whose "adopted"
  pending-journal line is stripped, combined with a store
  restore to the pre-adoption generation, refuses for a
  beyond-head candidate (pre-fix it was silently excused and
  proceeded to supersession-pending); a store-only restore
  with the pending journal intact refuses; an independent
  pending-journal rollback combined with the store restore
  refuses; a pending-journal rollback alone (store intact)
  does not refuse — the store record pair-covers the entry.

The new tests were written before the implementation: on the
pre-change tree the test module fails at import because the
reconciliation module does not exist. The full suite baseline
before this cycle was 1785 tests passing (28 skipped).

## Questions for the external seats

1. Is the excuse set complete and sound — in particular, is
   the head-scoped known-unadopted excuse (caller-attested,
   sourced from the adopter's pending journal) an acceptable
   basis for excusing the journal head, or does it reopen the
   silent-incompleteness hole in a scenario we have not
   constructed?
2. Is wiring-dependent detection an acceptable closure of
   the follow-up — the mechanism exists, is tested end-to-end
   when wired, and the unwired default claims nothing — or
   should the follow-up stay open until a production path
   enables it by default?
3. Was reconciliation the right branch, or does the
   pin-store head anchor remain necessary regardless?
