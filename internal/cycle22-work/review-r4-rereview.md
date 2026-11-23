# Cycle 22 — Re-review rev-r4 (WS3 fix round)

Seat: rev-r4, blind re-review. Scope read: my first review
(`internal/cycle22-work/review-r4.md`), `trust/pin_adoption.py`,
`tests/test_trust_pin_adoption.py`. No other seats' re-reviews read.

**Verdict: SHIP — score 0.97**

Test run by this seat: `python3 -m unittest tests.test_trust_pin_adoption -v`
→ **9 tests, OK, 12.8s** (test_01 … test_08 incl. 05/05b), same set as
the first review, all green.

---

## Fix verification

### F1 — `_retained_candidate` payload-hash check — FIXED

`_retained_candidate` now returns the retained envelope only when
both conditions hold:

```python
if signed.cycle_seq == candidate_seq \
        and signed.payload_hash == entry.get("candidate_hash"):
    return signed
```

(`trust/pin_adoption.py:412-413`.) This is exactly the check my first
review asked for: a journal entry whose retained envelope does not
hash to the entry's recorded `candidate_hash` is no longer
re-presented as the burned candidate. Previously the consequence was
fail-closed only; now the tightening is in place at the source, and
it matches the discipline already used by `_retained_current_candidate`
(seq + hash both checked) and `_find_unadopted_burn` (seq + hash +
old pin seq + hash).

### F2 — `already_current` TTL bound documented — FIXED

The module docstring now states it explicitly
(`trust/pin_adoption.py:35-40`):

> The ``already_current`` outcome is reachable only within
> the retained envelope's TTL: it depends on re-presenting
> the retained candidate envelope, and once that envelope
> has expired a repeat attempt on unchanged state fails
> closed (an integrity refusal) rather than reporting
> ``already_current``.

That is the behaviour I observed in the first review (expired
retained envelope → integrity refusal, fail-closed), now documented
where an operator will see it. No code behaviour changed, none was
needed.

### F4 — post-adopt `phase:"adopted"` journal append guarded — FIXED (both sites)

In `_reanchor`, the append after the successful `store.adopt` is now
wrapped (`trust/pin_adoption.py:721-731`):

```python
try:
    self._append_journal({**journal_base, "phase": "adopted"})
except OSError:
    pass
```

preceded by a comment giving the exact rationale from the fix spec:
the pin has adopted, a journal-append failure must not mask that
success with a raw `OSError`, the journal is a detection aid and
never authority, and the next attempt self-heals via
`already_current`. The swallow is narrow (`OSError` only — the
failure mode of the append's open/write/fsync path), not a blanket
`except Exception`, so unrelated programming errors still surface.

The same guard, with the same comment, was applied to the identical
pattern in `adopt_returned` (`trust/pin_adoption.py:748-761`), as
the fix round claimed. Both post-adoption append sites are now
guarded; I found no other unguarded post-success append in the
module (the `authorised` and `consumed` appends sit *before* the
point of no return, where raising is correct — a failed `authorised`
append aborts before consumption, and a failed `consumed` append
still precedes `store.adopt`, so neither can mask a completed
adoption).

### Bonus: test_05b artefact assertion is now an exact count — CONFIRMED

`test_05b` now asserts `len(artefacts) == 3`
(`tests/test_trust_pin_adoption.py`, the `pin-evidence-*` glob at the
end of the test) instead of merely asserting a new artefact exists.
The count is the right expectation: genesis (1) + the burned
ceremony (1) + the `burned_unadopted` recovery ceremony (1). This is
rev-r6's F5; from this seat it is a strict strengthening and it
passes.

---

## Regression check

- All 9 tests pass against the real verifier subprocess, including
  the mandatory cases from my first review: consume-committed /
  adopt-failed → `PinAdoptionBurned` with the returned pair
  (test_05), `adopt_returned` with no new consumption (test_05),
  discarded-pair recovery under `burned_unadopted` with a second
  consumption and no `lost_pin` (test_05b), `already_current` with
  no new consumption (test_03), and integrity failure persisting
  nothing (test_04).
- The rest of the module reads unchanged in substance from the
  version I shipped at 0.92: single production client construction
  via `production_client`, verifier-backed consumption, computed
  reason with `lost_pin` unreachable, adopter-authored evidence
  bundle hashed from its own bytes, `core/loop.py` untouched by the
  driver design. The only production-code deltas are the three
  fixes above, each surgical and in the place claimed.
- No production code or tests were edited by this seat; no
  state/calibration files were touched by this seat.

## Remaining nits

None of my first-review findings remain open. F3 (Info: no
virgin-journal integrity-failure case) was informational only, is
subsumed by test_04's byte-identical assertion, and does not block.

**Verdict: SHIP — 0.97** (up from 0.92; all three Low findings from
my first review are fixed as specified, plus the test_05b
strengthening, with the full suite green and no regression found.)
