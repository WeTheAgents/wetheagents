# Circle-1 CRAP risk harness review notes

## Pre-Implementation Spec Redteam

1. The issue asks for CRAP, but CRAP depends on coverage. Risk: a scanner could
   silently invent coverage. Decision: coverage is `unknown` unless a JSON/XML
   artifact is explicitly supplied and matched to file lines.
2. The issue asks for `scripts/` observability integration. Risk: rewriting #884
   could break a settled harness. Decision: consume `scan_observability()` and
   join detections by evidence line range.
3. The issue asks for a compact pilot artifact and a full runnable harness. Risk:
   committing a noisy full dump. Decision: CLI can emit full JSON on demand, but
   the committed checkpoint stores only summary plus top-risk records.

## Pre-Implementation Logic Redteam

1. Complexity alone can punish harmless formatting helpers. Decision: risk bands
   include coverage state and side-effect weight, and the markdown report names
   review use instead of claiming automatic failure.
2. `src/wea_cli` has no #884 observability source. Decision: empty channels mean
   unannotated, not side-effect-free; this limitation is documented.
3. Parse errors could vanish if only functions are reported. Decision: read and
   parse failures are preserved in `scope.skipped_files`.

## Implementation Self-Roast

1. Possible flaw: AST complexity is McCabe-like, not radon. Fix: the
   `complexity_source` field names the exact static source instead of claiming a
   third-party score.
2. Possible flaw: line coverage mapped to function ranges may not represent
   branch coverage. Fix: logic and JSON limitations state that branch coverage is
   not inferred.
3. Possible flaw: observability join can miss module-level side effects and
   wrapper calls. Fix: script channels are joined only when evidence lines are in
   the function range, and limitations say wrappers may be missed.

Missed edge cases considered:

1. Coverage artifact contains the file but no executable lines in a function.
   Fix: report `not_applicable` instead of zero or unknown.
2. Coverage artifact uses absolute or package-relative paths. Fix: normalize
   paths relative to repo root and fall back to unique suffix matching.

## Post-Implementation Redteam / Fix Notes

1. Redteam: risk ordering could be unstable if scores tie. Fix: final sort adds
   path, start line, and symbol after priority.
2. Redteam: CLI might write only one format despite the task asking for JSON and
   markdown. Fix: CLI supports `--json-output`, `--markdown-output`, and compact
   `--checkpoint-output`; no-output mode prints full JSON.
3. Redteam: function ranges could include nested function observability in the
   outer function. Status: complexity skips nested function bodies, but
   observability line-range joins can include nested detections in outer ranges.
   This is a known conservative review-priority limitation, not proven fixed.

## Final Codex Review Notes

The deliverable is measurement-only. It adds no CI gate, Tide behavior, ledger
mutation, GitHub workflow, or issue-template change. It scans both required
zones recursively, preserves skipped-file evidence, reports missing coverage as
unknown, computes CRAP only for known coverage, and leaves tracking fields for
future Agent0 sweeps.
