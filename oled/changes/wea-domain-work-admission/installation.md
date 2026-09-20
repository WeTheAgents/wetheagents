# Installation checkpoint

Status: proposed follow-up, not implemented or approved by this candidate.
The operator approved the admission behavior and its implementation. A live Access protocol transition remains a separate behavior change.

## Exact current candidate

- Code commit: `3fa22ab7eae58dd350136d4e360c28a30c6fd872`.
- Activated Access protocol hash: `267e5d60c8407e6afd08aec3d7edb2d56f1ee939b225a15c8e788795e20c6f1f`.
- Candidate package hash: `69d099e2d32cdb549ff05a31ab18a82564dbe943f881953eee69c2153ec6f4de`.
- Draft PR: https://github.com/WeTheAgents/wetheagents/pull/1008.

The six changed closure paths are the Access CLI/reader, Tide runner/replay/ledger and the new admission module.
The base-code guard rejects the new module as a changed writer universe. Its failed result remains visible.
A manual merge exception alone is insufficient: the old Access genesis still pins the old package and rejects subsequent grants.

## Smallest proposed transition

Retain the existing genesis, decisions, grant IDs, intervals and idempotency history.
Introduce one explicit operator-authorized append-only protocol-update record in the same Access journal.
The operator source would bind the previous protocol hash, reviewed new code SHA and new protocol hash.
The handler would reject mismatched predecessors, edited sources, unauthorized accounts and changes to historical grants.
The record would authorize new writer code, not new trips, money or GitHub permissions.
Old journal records and historical Tide snapshots would remain reproducible under their recorded formats.
An exact retry would return the same update. Recovery would append forward without replacing genesis or extending any trip.

This proposal needs an accepted Outcome/Spec/Design delta before implementation.
Its affected behavior includes the current one-time activation/closure rule and mixed-version journal replay.
The admission PR can then form part of one reviewed installation package with that transition.
After the manual installation and exact update source, verify a fresh CLI read, original intervals, overlap rejection and a new admissible operation.
Then verify schema-3 admission through a canonical Tide candidate and its trusted guard.
Until those steps pass, keep PR #1008 unmerged and do not claim live enforcement.
