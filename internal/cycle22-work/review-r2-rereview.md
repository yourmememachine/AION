# War-room RE-REVIEW — seat rev-r2 (WS2 focus) — cycle 22

Blind re-review of the working tree after the fix round for my
first-round findings F1–F3 (review-r2.md). No other seats'
re-reviews were read. Production code, tests and docs were NOT
edited by this seat.

## Verdict: SHIP — score 0.96

All three first-round findings are resolved in the actual
current text, verified by direct reading and repo-wide grep,
and the journal-anchor + wiring + production-deploy suites
re-run green (78 tests, OK, skipped=12). The repository no
longer simultaneously claims and disclaims the consumption
journal's anchoring on any live claim surface.

## F1 — RESOLVED (was MAJOR, docs/claim)

- `trust/ledger.py:715-737` (`CeremonyConsumptionLedger`
  docstring): the stale R10 paragraph is gone. The new
  "Anchoring (cycle 22, R2, replacing cycle 21's R10
  residual)" paragraph states the journal IS externally
  anchored in its own right (anchor kind
  "ceremony-consumption", verified at startup on every
  invocation when configured; required in production when
  the ceremony seed is configured); a burn whose anchor
  update completed survives a verifier-home rollback
  (detected at startup, anchor_refused); the append→anchor
  window is protected against an intact home but NOT
  against a full rollback inside it; research mode / anchor
  unconfigured: no rollback claim. The follow-up is stated
  as "narrowed to the issuance journal only". This matches
  R2 and the consume-mode docstring
  (`trust/verifier_main.py:2615-2624`, re-read, unchanged
  and consistent).
- `signing/pin_ceremony.py` module docstring (~lines
  280-325): rewritten. The burn-proof passage now states it
  "inherits the consumption journal's anchoring position:
  trustworthy under the per-request anchor verification
  when the consumption anchor is configured; research mode
  / anchor unconfigured makes no rollback claim". The
  residual passage is now headed "Issuance-journal rollback
  residual (the ceremony authorisation — ISSUANCE —
  journal; NOT the consumption journal)" and explicitly
  states "since cycle 22 the consumption journal is
  externally anchored in its own right" with the
  completed-update / window / research-mode qualifiers.
  The old R10 consumption residual ("can lower the enforced
  head for never-consumed envelopes") no longer appears as
  the consumption position — a grep for "never-consumed"
  across trust/, signing/, deploy/ returns nothing.
- Aggravating factor closed: the cycle-22 addendum in
  `internal/DECISION-CONSUMPTION-HEAD.md` asserted this
  docstring "is rewritten" — previously false, now true.

## F2 — RESOLVED (was MINOR, docs)

- `trust/verifier_main.py:255-259` now reads "The ceremony
  ISSUANCE journal is NOT externally anchored (follow-up:
  ceremony-journal-anchoring, narrowed in cycle 22 to this
  issuance journal only — the consumption journal is
  separately anchored, see above)". The unqualified name
  collision is gone; this is now the ONLY remaining
  "NOT externally anchored" statement in trust/, signing/
  or deploy/, and it is substantively correct under R2's
  narrowing.

## F3 — UNCHANGED, still benign (observation, no action)

The production consumption-anchor gate remains conditioned
on `ceremony_seed_raw`; as established in round 1, the
weaker form is unreachable because production without a
seed refuses startup earlier. No change was required and
none was needed.

## Grep sweep (stale / contradictory passages)

- `grep -rn "NOT externally anchored" trust/ signing/
  deploy/`: exactly one hit — the qualified ISSUANCE
  statement above.
- `grep -rn "both journals" trust/ signing/ deploy/`: one
  hit, `trust/README.md:85` — "both journals' heads CAN be
  anchored to a file outside the journal directory". This
  file is unmodified in cycle 22 and the sentence is a
  capability statement about `trust/anchoring.py`, not a
  claim that any particular journal IS anchored in a given
  deployment; it does not contradict R2. Recorded as a
  benign observation, not a finding.
- Repo-wide sweep for "NOT externally anchored" / "covers
  both journals" outside the live tree returns only
  historical cycle-21 records
  (`internal/cycle21-work/design-c.md`,
  `DESIGN-FINAL.md`, `review-r1.md`), which correctly
  describe the cycle-21 state they record.
- The only remaining "R10" mentions in the live tree are
  the two "replacing cycle 21's R10 residual" headers
  (ledger.py, verifier_main.py) — correct historical
  framing, not stale claims.

## Deploy README (re-checked; rewritten by another fix seat)

My round-1 (c)/(e) checks covered deploy text, so both
rewritten passages were re-read in full:

- `deploy/verifier-identity/README.md:127-141` (Deployment
  mode): production with the ceremony seed configured
  additionally requires `AION_CEREMONY_CONSUMPTION_ANCHOR_PATH`;
  completed-update burns survive a verifier-home rollback
  (detected at startup); full rollback inside the
  append→anchor-update window not protected; research mode
  / unconfigured: no rollback claim. The INIT-refusal list
  at lines 122-125 includes
  `AION_CEREMONY_CONSUMPTION_ANCHOR_INIT`. Consistent with
  R2 and with `_load_config` as verified in round 1.
- `deploy/verifier-identity/README.md:266-286` (Ceremony
  consumption): "the consumption journal is externally
  anchored via AION_CEREMONY_CONSUMPTION_ANCHOR_PATH /
  AION_CEREMONY_CONSUMPTION_ANCHOR_INIT (allowlist
  17 → 19); production mode with the ceremony seed
  configured requires the path and refuses the INIT flag",
  followed by the same completed-update / window /
  research-mode claim wording. Consistent with the code
  docstrings and with the 19-key allowlist verified in
  round 1.

## Tests re-run by this seat

`python3 -m unittest tests.test_trust_ceremony_journal_anchor
tests.test_trust_wiring tests.test_trust_production_deploy`
→ **78 tests, OK (skipped=12)**, 23s. (Round 1 ran these
plus test_trust_ceremony_consumption for 90 tests OK; the
fix round touched wording only, and the three suites named
for this re-review cover the anchor mechanism, the wiring
allowlist equality, and the production deploy contract.)

## Bottom line

The fix round did exactly what F1/F2 asked, in every place
asked, with wording that agrees across the ledger class
docstring, the pin-ceremony module docstring, the verifier
header, the consume-mode docstring, and both deploy README
passages. Nothing stale or contradictory remains on the
anchoring claim surface. SHIP.
