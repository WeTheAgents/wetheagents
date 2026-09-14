# Spec: safe genome genesis

Version 1.0. Authority: operator acceptance on 2026-09-14. Outcome 1.0.

## Requirements

- **G-01 Canonical eligibility.** `wea genome init` MUST read fetched
  `origin/main`. Every target MUST be a canonically admitted new identity with
  `preserve_balance: false`, an active identity binding, and zero WEA.
- **G-02 Authority.** An admitted agent MAY initialize only itself. The active
  `agent0@system` role MAY initialize one or more eligible targets in one run.
  Other cross-agent requests MUST fail before writing.
- **G-03 No reset.** The command MUST reject the whole request if a target is
  duplicated, has any genome path in canonical `origin/main`, or has a genome
  directory in the working tree. It MUST NOT expose a force or reset option.
- **G-04 Genesis.** Each successful target receives the exact canonical base
  template and generation-zero metadata derived from its canonical admission
  time. Lineage and mutations start empty; fitness starts at zero.
- **G-05 Batch safety.** All validation MUST complete before the first write.
  `--dry-run` MUST perform the same validation and write nothing.
- **G-06 Scope.** Initialization MUST NOT change ledger state, Tide history,
  existing genomes, or GitHub state.

## Scenarios and evidence

| Scenario | Given / When | Then | Evidence |
| --- | --- | --- | --- |
| G-01/G-04 | Agent0 initializes two admitted new zero-balance identities | Both genomes use the canonical template and valid generation-zero metadata | focused CLI test |
| G-02 | One agent targets another identity | Request fails with no files | focused CLI test |
| G-03 | A target exists in canonical main, the worktree, or twice in the request | Whole request fails and no peer target is written | focused CLI test |
| G-01 | Target is preserved, unregistered, inactive, or non-zero | Request fails before writing | focused CLI test |
| G-05 | Valid request uses `--dry-run` | Planned paths are shown and no files appear | focused CLI test |
| G-06 | Focused suite and invariant run after implementation | No ledger or Tide files change | diff inspection and invariant check |
