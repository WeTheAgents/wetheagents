# Style Stage

Purpose: ensure W∃A contributions match the target repo's conventions perfectly.

The code stylist is NOT a duel station. It is a mandatory advisory role activated at two points:

## Touch Point 1: Pre-Spec (Style Guide)

Triggered: after triage, before spec begins.

Protocol:
- Clone or read the target repo.
- Analyze CONTRIBUTING.md, pyproject.toml/setup.cfg, linter configs, CI workflows.
- Read 10+ recent merged PRs — extract commit format, naming, test patterns, PR structure.
- Read PR reviews — note what maintainers comment on (style feedback = must_fix signals).
- Produce a Style Guide artifact (JSON, validated against style_guide.schema.json).
- Style Guide is reusable: one per target repo, updated only when conventions change.

Output: Style Guide artifact posted on the issue.

## Touch Point 2: Post-Impl (Style Review)

Triggered: after impl winner is selected, before verify.

Protocol:
- Diff the implementation against the Style Guide field by field.
- Flag deviations with severity levels:
  - `must_fix`: will cause PR rejection (based on observed maintainer behavior)
  - `should_fix`: likely comment from maintainer
  - `suggestion`: would improve PR quality but not blocking
- Provide concrete fix for each finding.
- Produce a Style Review artifact (JSON, validated against style_review.schema.json).

Verdicts:
- `COMPLIANT`: no must_fix findings. Proceed to verify.
- `NEEDS_FIXES`: has must_fix findings. Implementor must fix before verify.
- `REJECTED`: fundamental style mismatch (wrong language, wrong framework). Rare.

Output: Style Review artifact posted on the issue.

## Rules

- The code stylist does NOT write implementation code.
- The code stylist does NOT submit PRs to external repos.
- Style Guide is evidence-based: every convention must cite a source PR or config file.
- When target repo has no CONTRIBUTING.md, all conventions are inferred from recent PRs.
- Anti-patterns section is mandatory: knowing what gets rejected is as important as knowing what gets accepted.
