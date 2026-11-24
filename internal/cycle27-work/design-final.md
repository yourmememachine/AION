# Cycle 27 — Design Record

Date: 2026-11-23.

## Scope

Cycle 27 closes the follow-up `ceremony-journal-anchoring`.

The scope of that follow-up, after cycle 22's narrowing and
cycle 24's extension, covers both ceremony journals:

- the ceremony issuance journal — `CeremonyAuthorisationLedger`,
  file `ceremony-authorisations.json`; and
- the ceremony supersession journal — `CeremonySupersessionLedger`,
  added in cycle 24.

No narrower reading is claimed. Closing only one of the two
journals does not close the follow-up.

## Design

The design mirrors cycle 22's consumption anchoring exactly.

### Anchor kinds

`trust/anchoring.py` gains two new anchor kinds:

- `ceremony-issuance`
- `ceremony-supersession`

Each anchor records the externally anchored position of its
journal in the same manner as the existing consumption anchor.

### Environment variables

Four new environment variables:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`
- `AION_CEREMONY_ISSUANCE_ANCHOR_INIT`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT`

### Startup verification

Both journals are verified at startup on every verifier
invocation, in `_load_config`. A journal whose current position
does not match its external anchor is refused at startup rather
than being discovered later.

### Production requirements

Production mode with the ceremony seed configured requires both
anchor paths and refuses both INIT flags:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH` is required;
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH` is required;
- `AION_CEREMONY_ISSUANCE_ANCHOR_INIT` is refused; and
- `AION_CEREMONY_SUPERSESSION_ANCHOR_INIT` is refused.

The production requirement is keyed to the ceremony seed being
configured, because that is the configuration under which the
ceremony journals are live.

### Anchor path rules

Each anchor path must be:

- absolute;
- outside the verifier home; and
- distinct from all other anchor paths.

No anchor may alias another anchor, and no anchor may live
inside the home it is meant to check from outside.

### Wiring

The `wiring.py` allowlist grows by 4 keys — the two PATH keys
and the two INIT keys above. Both PATH keys join
`REQUIRED_ENV_KEYS`:

- `AION_CEREMONY_ISSUANCE_ANCHOR_PATH`
- `AION_CEREMONY_SUPERSESSION_ANCHOR_PATH`

## Commit orders

### Authorise

1. Issuance append — the commit point.
2. Issuance-anchor update.
3. Signing mirror.
4. Signing anchor.

### Supersede

1. Decision append — the commit point.
2. Supersession-anchor update.
3. Signing mirror.
4. Signing anchor.

In both flows the journal append comes first and is the commit
point; the anchor update follows it, and the signing mirror and
its anchor follow that.

### Anchor-update failure

If an anchor update fails after the journal append:

- the result is `ledger_failed`;
- the artefact is withheld; and
- the journal entry stands — the pair is burned in the authorise
  flow, and the decision stands in the supersede flow.

The journal entry is not rolled back to hide the failure.

## Honest residuals

- The append-to-anchor-update window carries the same rollback
  caveat as every anchored append in this system: between the
  commit point and the completion of its anchor update, the
  external anchor does not yet reflect the new entry.
- Research mode with no anchor configured makes no rollback
  claim.
- A whole-home rollback is still caught by the consumption and
  signing anchors for consumptions whose anchor updates
  completed.

These residuals are stated, not minimised. The claim for cycle 27
is startup-enforced external anchoring of the two ceremony
journals under the configurations described above, subject to
the window caveat that applies to every anchored append here.

## Self-improvement delta

The last two journals whose rollback position rested on
audit-only detection now carry startup-enforced external
anchors, so evidence-reuse and decision-vanishing after rollback
become startup refusals instead of audit findings.

That is the measurable change this cycle makes: a class of
problem that previously could only be found by later inspection
is now refused at startup, before the verifier acts on the
rolled-back state.

## Staffing

15 coders, 5 pods of 3:

- Pod A (seats 1, 5, 8): `trust/anchoring.py` and wiring.
- Pod C (seats 9, 10, 11): verifier config (`_load_config`) and
  the authorise and supersede commit orders.
- Pod D (seats 3, 4, 15): adversarial tests.
- Pod B (seats 2, 6, 7): ledger docstring and residual rewrites.
- Pod E (seats 12, 13, 14): deploy README and records.

## Review

Review is by 6 internal seats drawn from pods other than the
pod that built the slice under review, plus two external seats:
seat-gpt and seat-gemini.

The verdict stays provisional until the external findings are
reconciled in.
