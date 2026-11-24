# Cross-Check Brief — Cycle 27: Ceremony Journal Anchoring

You are an external reviewer seat for the AION trust-boundary
work. This brief describes what was built in cycle 27, the
design decisions behind it, and the test evidence available.
Three questions are at the end.

## Background

An earlier follow-up, `ceremony-journal-anchoring`, was left
open after cycle 22 narrowed its scope and cycle 24 extended
it. As extended, the follow-up covers both ceremony journals:

- the ceremony issuance journal — `CeremonyAuthorisationLedger`,
  file `ceremony-authorisations.json`; and
- the ceremony supersession journal —
  `CeremonySupersessionLedger`, added in cycle 24.

Before this cycle, both journals lived inside the verifier
home with no external anchor. Their rollback position therefore
rested on later audit detection rather than on a startup check
against a position held outside that home.

Cycle 22 had already established the anchoring pattern for the
consumption journal: an external anchor, checked at startup,
with the journal append as the commit point and the anchor
update immediately after it. Cycle 27 applies that same pattern
to the two ceremony journals.

## What was built

### Anchor kinds

`trust/anchoring.py` gains two new anchor kinds:

- `ceremony-issuance`
- `ceremony-supersession`

### Environment variables

Four new environment variables:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`
- `AION_CEREMONY_ISSUANCE_ANCHOR_INIT`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT`

### Startup verification

Both journals are verified at startup on every verifier
invocation, in `_load_config`. A journal whose current position
does not match its external anchor is refused at startup.

### Production requirements

Production mode with the ceremony seed configured requires both
anchor paths and refuses both INIT flags:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH` is required;
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH` is required;
- `AION_CEREMONY_ISSUANCE_ANCHOR_INIT` is refused; and
- `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT` is refused.

### Anchor path rules

Each anchor path must be:

- absolute;
- outside the verifier home; and
- distinct from all other anchor paths.

### Wiring

The `wiring.py` allowlist grows by 4 keys — the two PATH keys
and the two INIT keys above. Both PATH keys join
`REQUIRED_ENV_KEYS`:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`

### Commit orders

Authorise:

1. Issuance append — the commit point.
2. Issuance-anchor update.
3. Signing mirror.
4. Signing anchor.

Supersede:

1. Decision append — the commit point.
2. Supersession-anchor update.
3. Signing mirror.
4. Signing anchor.

If an anchor update fails after the journal append, the result
is `ledger_failed`, the artefact is withheld, and the journal
entry stands — the pair is burned in the authorise flow, and
the decision stands in the supersede flow. The journal entry is
not rolled back to hide the failure.

## Design decisions

- Mirror cycle 22's consumption anchoring exactly, rather than
  introducing a second anchoring pattern for the ceremony
  journals. One pattern means one set of path rules, one startup
  verification shape, and one failure vocabulary.
- Anchor both journals in the same cycle, because the follow-up
  as extended covers both; anchoring only the issuance journal
  would leave the supersession journal — whose decisions affect
  whether a recovery may proceed — in the audit-only position.
- Require both anchors in production only when the ceremony
  seed is configured. That is the configuration under which the
  ceremony journals are live; a production configuration without
  the ceremony seed does not operate these journals.
- Keep the journal append as the commit point and place the
  anchor update immediately after it, matching the order already
  used for the consumption journal.

## Stated residuals

- The append-to-anchor-update window carries the same rollback
  caveat as every anchored append in this system: between the
  commit point and the completion of its anchor update, the
  external anchor does not yet reflect the new entry.
- Research mode with no anchor configured makes no rollback
  claim.
- A whole-home rollback is still caught by the consumption and
  signing anchors for consumptions whose anchor updates
  completed.

## Test evidence

- Suite total: 1785 tests OK (skipped=28), coordinator-run on the final tree; baseline 1764
- New tests in `tests/test_cycle27_journal_anchors.py`

The new tests cover the adversarial cases for both journals:
startup verification, production requirements and INIT refusal,
anchor path rules (absolute, outside the verifier home, distinct
from all other anchor paths), both commit orders, and
anchor-update failure handling.

## Questions

**Q1.** Does anchoring both journals close the
`ceremony-journal-anchoring` follow-up at the claimed scope?

**Q2.** Is the append-to-anchor window disclosure honest and
consistent with prior cycles?

**Q3.** Is there any mechanism gap in requiring both anchors in
production only when the ceremony seed is configured?
