# External AI cross-check #2 — 2026-11-20 (~02:04–02:08 MST)
Per Dilip's standing rule (2026-11-20), upgraded the same night:
ChatGPT and Gemini are seats IN the war room, not only a post-room
check. This cycle ran them after the internal blind round and the
fix round; the verdict stayed provisional until Gemini's review was
reconciled in (see REVIEW-CYCLE-7 fix #10).

## Gemini — received (signed in as Dilip's Google account)
Assessment: solid v1 stdlib engineering; praised the early catches
(compare_digest non-ASCII, float canonicalisation, timestamp
normalisation) and the honest limits. Core warning: a signed
decision can create false confidence if the envelope proves
integrity of a decision object while authority, freshness,
state-binding and execution boundaries stay loose.
Points raised:
1. Same-principal HMAC sharing collapses the boundary if the agent
   process can read the key or invoke the signer. (Already the
   docstring's central limit; no change.)
2. No store-state / monotonic-version binding: an envelope proves
   the entry payload, not the store state at commit time (TOCTOU).
3. 48h max window and no consumed-envelope tracking: replay room.
4. Canonicalisation traps remain possible (bool/int, None/omitted,
   tuple/list); verifier_note delimiter parsing can drift; optional
   hashes must distinguish absent from zero. (Our encoding: absent
   is "", a zero hash is a distinct valid hex64 — no ambiguity;
   strict types are now validated in the payload builder.)
5. Key/path checks are point-in-time; signer_id is caller-supplied
   metadata, not key policy. (Docstring now says exactly this.)
6. Signed rejects are safe only if commit_signed strictly refuses
   them. (It does, before touching the store; pinned by tests.)
Change-first list: shorten the default TTL to minutes and bind a
store id/epoch; make require_attestation fail-closed by default;
domain-separation prefix in the MAC input (already present:
DOMAIN + ALG + key_id precede the payload hash in the MAC blob).
Understated risks: "caller discipline" understates the unsigned
path in a self-improving system (wording adopted: temporary,
un-enforced bypass boundary); rollback + replay can resurrect
rejected or poisoned memory (wording adopted verbatim in
substance); stale/unverified gate inputs are a bigger risk than
the recompute caveat alone suggests.
Action taken this cycle: default TTL 7200s -> 900s; docstring
sharpened on both understated risks. Queued, not dropped:
store-state/epoch binding and attestation-by-default belong to
store-enforced-signed-commits (8.0), the gated store change.

## ChatGPT — unreachable this cycle
chatgpt.com loaded normally, but no saved login signs in to it and
a detached scheduled run cannot complete the Google sign-in (no
interactive chat to enter credentials). The cross-check message
was NOT sent and no reply was obtained. Recorded as a vacant
external seat — explicitly not a pass, not an approval. Next cycle
should retry; if Dilip signs in to ChatGPT in the browser once,
the saved login should persist for later runs.

## Convergence with the internal war room
Gemini's change-first list matches R2's dissent on the two points
that matter (unsigned path is the weakest link; provenance must be
enforceable, not optional-by-default) — both are now the queued
store-enforcement item rather than claims made for this cycle.
