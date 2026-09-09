# CI retirement design

Revision 1.0, bound to Outcome/Spec 1.0.

Use GitHub's workflow disable API now, then remove eight YAML entrypoints through a manually merged PR. Keep their scripts and historical records. This stops costs before merge and prevents automatic reinstatement by later runs.

Use native paths-ignore on doc-sync, Semgrep, and boundary workflows for ledger/vnext/** and evidence/vnext/** only. Mixed changes still run. Do not filter the trusted guard or its main-push invalidator. Move portable boundary tests to Ubuntu and cancel superseded read-only CI attempts within the same workflow/PR. Do not cancel Tide writer runs.

Do not add another scheduled audit: ordinary Tide already replays canonical state. Preserve privacy policy/private sync and optional domain tools; removing vocabulary CI does not authorize publication.

Verification uses YAML parsing/inspection, existing runtime/Tide tests, invariant, doc-sync, and independent review. No new runner, dependency, or generic checker. Native path filtering is bounded by GitHub diff limits; trusted validation has no such path filter.

Rollback: restore the relevant YAML from b5c5b262e4fdab8fe343db50805c267bc3eb65df and enable only the selected workflow through GitHub. No ledger rollback or replay migration.

Expected surface: 14 product files, mostly workflow deletion; under 100 added production lines. Revisit only if removing workflow references requires extra active documentation changes.
