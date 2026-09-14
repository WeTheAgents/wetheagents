# Verification: safe genome genesis

Status: first PR review findings fixed; clean follow-up review pending.

Accepted contract: Outcome 1.0, Spec 1.1, Design 1.1.

Evidence:

- `python -m pytest -q tests/test_wea_cli_genome.py
  tests/test_check_genome_completeness.py
  tests/test_check_genome_naming_adversarial.py tests/test_budget_calc.py`:
  51 passed.
- `python -m pytest -q tests/vnext/test_identity.py
  tests/vnext/test_tide_participants.py tests/vnext/test_tide_ledger.py
  tests/test_wea_cli_genome.py`: 75 passed.
- `python -m ruff check src/wea_cli/genome.py
  tests/test_wea_cli_genome.py`: pass.
- `python -m pyright src/wea_cli/genome.py`: zero errors and warnings. The
  repository configuration emits a pre-existing unknown-setting notice.
- `python scripts/check_doc_sync.py`: pass.
- `python scripts/check_genome_completeness.py --root .`: 108 pass and one
  existing warning for the `base` template directory.
- `python scripts/check_genome_meta_version_consistency.py --root .`: pass.
- Canonical base template: 68 lines, below the 120-line genome limit.
- `python scripts/check_invariant.py --root .`: pass, 19025 WEA equals 19025
  WEA at Tide 10.
- `git diff --check`: pass.

Known unrelated repository defect: the full `genome_guard.py` run rejects the
existing `Codex-20@codex` genome at 127 lines against its 120-line limit. This
change neither reads that genome as a template nor modifies it.

Remaining evidence: PR checks and Codex review with no actionable findings.

First Codex review found four integration gaps: vNext-only agents were unknown
to legacy validators, historical deletions were not checked, self-genesis was
blocked by the commit hook, and the onboarding recipe did not create its task
worktree before writing. Spec and Design 1.1 address all four. The focused
integration suite now has 173 passing tests, including the retained vNext
registry, validator, commit-guard, and historical deletion boundaries.
