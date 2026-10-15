# Design: versioned activation evidence

Binding: Outcome 1 and Spec 1. Revision 1, 2026-10-15.

Use the existing activate-policy operation, source parser, protected package transition, and journal schema.
Add one immutable capability module to the installed manifest with a known exact byte hash.
Only that capability and an explicit version 2 payload select new semantics.
Historical packages retain the old predicate even when a historical rejected source contains future-shaped fields.

The version 2 payload retains code_sha as the installed SHA and adds execution_code_sha and activation_schema.
The handler already checks current checkout, GITHUB_SHA, Actions provenance and the full committed manifest.
Retain the checked manifest and both identities in versioned activation_evidence.
Pure replay compares this evidence with the package selected at that historical journal position.
The writer's final current-main read remains before publication. Package races fail the exact evidence comparison.
No package repin relaxation, workflow permission, dependency, global configuration, or financial schema change is necessary.

No-change fails the reproduced case. Repinning unchanged bytes violates APT's no-op rule and does not repair future drift.
Removing SHA equality alone loses authority and historical rejection semantics.
The explicit capability avoids interpreting an old source through new predicates.

Expected surface: three production files, approximately 80-120 added production lines, focused tests and contract documentation.
Revisit scope before adding a dependency, another protocol, or more than three additional product files.
Recovery remains append-only. Before installation, discard the candidate branch if needed.
After any future installation, recovery requires a separately authorized package transition, never journal rewriting.

Proof hooks: AS-01 positive drift, AS-02 single-variable negatives and trusted run, AS-03 historical replay and retries.
Implementation and synthetic checks are authorized now. Merge, installation and live activation remain operator gates.
