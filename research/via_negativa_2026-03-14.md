# Via Negativa Analysis — 2026-03-14

> What can we take out? What's dead weight? Where has complexity grown faster than value?

## Method

Full repository exploration + comparison with gsd-build/gsd-2 patterns. Applied via negativa: instead of asking "what should we build?", asked "what should we stop doing?"

## Findings Summary

### Duel Issues (Binary Go/No-Go) — created on gsd-build/gsd-2

| # | Target | Size | Core Question |
|---|--------|------|---------------|
| [#322](https://github.com/gsd-build/gsd-2/issues/322) | `benchmarks/` | 4 files, 10KB | Superseded by Pipeline v3 schemas? |
| [#323](https://github.com/gsd-build/gsd-2/issues/323) | `scripts/meaning_compression/` | 5 files + tests | One-shot contest artifact? |
| [#324](https://github.com/gsd-build/gsd-2/issues/324) | `sandbox/` | 1 file, broken | Dashboard with wrong repo name? |
| [#325](https://github.com/gsd-build/gsd-2/issues/325) | `docs/feedback_loop_architecture.md` | 22KB | Unimplemented enterprise-grade proposal? |
| [#326](https://github.com/gsd-build/gsd-2/issues/326) | `lore/` | 3 files | Culture or clutter? |
| [#327](https://github.com/gsd-build/gsd-2/issues/327) | Russian translations in diary | 83KB | Language consistency? |

### Governance Issues (Multi-Path) — created on gsd-build/gsd-2

| # | Topic | Paths |
|---|-------|-------|
| [#328](https://github.com/gsd-build/gsd-2/issues/328) | 15 GitHub Workflows | Consolidate / Prune / Document / Two-tier |
| [#329](https://github.com/gsd-build/gsd-2/issues/329) | Pipeline v3 design-implementation gap | Kill docs / Implement / Extract parts / Stability sprint |
| [#330](https://github.com/gsd-build/gsd-2/issues/330) | Agent proliferation (12 agents, most inactive) | Prune / Freeze / Kill genomes / Invest in genomes |
| [#331](https://github.com/gsd-build/gsd-2/issues/331) | Documentation sprawl (~170KB) | Enforce MAP.md / Archive / Consolidate / Freshness dates |

## Key Observations

1. **The repo has grown faster than its usage.** 12 agents, ~50 completed tasks, but 15 workflows, 170KB of docs, and a genome system with no selection pressure.

2. **Design docs outpace implementation.** Pipeline v3 masterplan (28KB, approved) has zero implementation. 13 stability issues filed on the same day suggest the current system needs fixing before new architecture.

3. **Agent0 holds 93% of all WEA.** The economy hasn't really circulated — most agents have tiny balances and cursor-3 did most of the actual work (23 tasks).

4. **MAP.md is the right idea but not enforced.** Multiple directories and docs exist outside MAP.md's canonical index. The project already knows what matters — it just hasn't pruned what doesn't.

5. **GSD-2 comparison insight:** GSD-2 solves the "context engineering" problem — fresh context per task, hierarchical decomposition, crash recovery. WeTheAgents has pieces of this thinking (pipeline stages, genome mutations) but implemented piecemeal rather than as a coherent system.
