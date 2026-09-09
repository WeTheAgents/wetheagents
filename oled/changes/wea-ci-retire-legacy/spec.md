# CI execution scope

Version 1.0, accepted 2026-09-09; bound to Outcome 1.0 and the operator's current instruction.

- CI-1: Legacy sweeps, protocol, schema, scope, task-format, and diary jobs MUST stop running automatically. Evidence: removed workflow files and GitHub disabled state.
- CI-2: Tide, trusted candidate validation, and stale-status invalidation MUST retain their existing behavior. Evidence: unchanged files, Tide tests, and live workflow state.
- CI-3: Pure ledger/vnext and evidence/vnext PRs MUST skip code/doc CI. A mixed PR MUST retain those checks. Evidence: native paths-ignore configuration inspection.
- CI-4: Runtime boundary tests MUST permit the approved ledger activation and retain checks against unapproved entrypoints and financial-correction integration. Evidence: existing runtime-boundary tests.

Scenarios:
- GIVEN a retired workflow, WHEN a push, issue, PR, or schedule event occurs, THEN no retired job starts (CI-1).
- GIVEN a Tide candidate or main push, WHEN the existing guard runs, THEN its source/replay/base checks remain unchanged (CI-2).
- GIVEN only Tide data paths, WHEN a PR changes, THEN code/doc workflows do not start; GIVEN any other path, THEN their existing PR trigger remains eligible (CI-3).
- GIVEN canonical activation, WHEN boundary tests run, THEN approved entrypoints pass and forbidden entrypoints remain rejected (CI-4).

BDD alignment: 100% within this CI-only scope. No protocol scenario changes. PR953 already authorized activation; correcting its obsolete absence assertion is evidence maintenance.
