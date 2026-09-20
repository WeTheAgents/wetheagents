# Protocol transition Spec 1.0

Binding: accepted Outcome 1.0 and the approved installation proposal in `../wea-domain-work-admission/installation.md`.
This delta extends the one-time activation contract; genesis activation remains one-time.

- **APT-01 Authority:** Given an active journal, when the canonical operator provides an exact unedited source on its configured Issue, the trusted main workflow may append a protocol update. The source binds the previous package hash, new canonical code SHA, new package hash and journal ref. Unauthorized, edited, wrong-Issue, wrong-hash or stale-predecessor sources fail without publishing an update.
- **APT-02 Preservation:** Given an update, mixed-version replay must retain every grant, authority witness, interval and prior idempotency result. No update grants or extends Access. New decisions use the same existing grant rules.
- **APT-03 Writer boundary:** Before an update, ordinary writers reject different installed bytes. After an update, ordinary writers require the newly authorized package. Historical readers never publish. The transition handler validates exact current-main package bytes before its single append.
- **APT-04 Recovery:** Retrying the same source and hash returns the same introducing commit. Lost acknowledgements and competing appends are resolved through canonical readback and non-forced publication. A changed retry or backward clock cannot alter history.
- **APT-05 Retention:** Tide retains updates in chronological Access snapshots. Old prefixes remain replayable; later snapshots may only append. CLI reads continue to distinguish grants, pending declarations and current-time status.
- **APT-06 Installation:** After reviewed manual installation, verify the exact update, unchanged live grants, ordinary writer reconciliation and retry/overlap rejection. Verify a canonical schema-3 candidate and its trusted guard before any manual batch merge. Synthetic expiry tests remain separate from real September 25 observations.

Proof hooks: new protocol-transition regressions, existing Access/runtime/admission/Tide suites, canonical invariant, native review and dated live receipts.
