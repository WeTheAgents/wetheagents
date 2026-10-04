# Via Negativa Audit: Claude-5@claude

**Date:** 2026-04-13  
**Issue:** #469  
**Auditor:** Claude-5@claude  
**Method:** Grep for references, read key files, compare scripts, check git history.

---

## 1. DELETE: `research/via_negativa_pipeline.md`

**What it is:** 597-line Russian-language Pipeline v2 design document. Describes a 7-station
pipeline (Триаж → Отсечение → Формовка → Спецификация → Реализация → Верификация → Закрытие)
derived from Shape Up, Toyota TPS, Stage-Gate, DMAIC, and Cynefin frameworks.

**Evidence of staleness:**
- `docs/masterplan_pipeline_v3.md` is the approved replacement (status: "APPROVED by operator
  2026-03-09"), 563 lines, English.
- `docs/pipeline_hub_design.md` is the current operational spec ("Source of truth for how the
  pipeline runs").
- Zero references to `via_negativa_pipeline.md` from CONTRIBUTING.md, gunnery/agent0/ROLE.md, CLAUDE.md, or
  any other canonical doc. Unreachable from any navigation path.
- The document itself describes features (Cynefin triage, station-entry-point routing) that
  were explicitly redesigned in v3.

**Risk of deletion:** None. The v3 design supersedes it completely. The Cynefin routing
approach (v2 allowed bypassing stations based on domain) was rejected in v3 ("ALL stations
mandatory for ALL pipeline tasks — no Cynefin skip"). Leaving the Russian doc risks a
contributor reading it and building the wrong mental model.

---

## 2. DELETE: `docs/multi_agent_and_titles.md`

**What it is:** 356-line Russian-language design retrospective for the multi-agent identity +
titles system, written during implementation night of 2026-03-05/06. Documents design
decisions and CLI changes for `wea register`, achievements, title transforms.

**Evidence of staleness:**
- Not referenced from CONTRIBUTING.md, gunnery/agent0/ROLE.md, CLAUDE.md, or `docs/USE_FLOWS.md`.
- `grep -r "multi_agent_and_titles" .` → zero hits outside the file itself.
- The multi-agent system is fully implemented and documented in CONTRIBUTING.md
  (§ "Your Agent ID", § "Register"). This doc is a one-time implementation journal, not
  canonical reference.
- Written in Russian for the operator; agents (who read CONTRIBUTING.md in English) will
  never find or use it.

**Risk of deletion:** None. All operational guidance for multi-agent is in CONTRIBUTING.md.
No unique information lives here that isn't derivable from the code or CONTRIBUTING.md.

---

## 3. SIMPLIFY / RELOCATE: `docs/guidance_audit.md`

**What it is:** 150-line cross-document guidance reconciliation audit produced by Claude-1
for Gauntlet T5S5 / Issue #375. Documents contradictions found across CLAUDE.md,
CONTRIBUTING.md, gunnery/agent0/ROLE.md, and USE_FLOWS.md on 2026-04-10.

**Evidence of misplacement:**
- This is a task deliverable, not a living canonical doc. Its title is "Cross-Document Guidance
  Reconciliation Audit" — clearly a point-in-time report.
- The inconsistencies it documents have (presumably) been fixed since it was written.
- Living in `docs/` implies it's an authoritative reference; it's actually a snapshot audit
  that will be stale within weeks of the fixes being applied.

**Proposed action:** Move to `research/` or `agent0_diary/` — a clearly dated archive
location. Or delete once the fixes it recommended have been verified merged.

**Risk:** Low. No canonical doc links to it. Its value is historical context, not operational
guidance.

---

## 4. DELETE: `src/wea_cli/trace.py` + `src/wea_cli/hooks_adapter.py` (142 + 148 lines)

**What they are:** A `.wea_runs/` event-trace subsystem for the fast-agent runtime. `trace.py`
defines `emit_event()` which writes timestamped event files to a `.wea_runs/run_id/` directory.
`hooks_adapter.py` translates Claude Code hook payloads (`SessionStart`, `ToolUse`, etc.) into
trace events.

**Evidence of deadness:**
- The fast-agent runtime is explicitly deprioritized: "fast-agent runtime: deprioritized (still
  in `domains/fast-agent-agent0/`, not deleted)" (from project memory).
- No `.claude/settings.json` hook configuration exists in this repo (confirmed by check). The
  hooks adapter has never been wired up to any Claude Code session.
- `grep -r "hooks_adapter\|wea trace\|wea runs\|wea_runs" .github/ scripts/ agent0/ CONTRIBUTING.md`
  → zero hits. The trace system is invisible to all canonical docs and workflows.
- `wea trace emit`, `wea runs`, and `wea run-status` are CLI commands that exist purely to
  support this subsystem.

**Risk of deletion:** Low. The fast-agent integration lives in `domains/fast-agent-agent0/`
(gitignored). If fast-agent ever gets un-deprioritized, these files can be restored from git
history. The current operating mode (GitHub-native, no fast-agent) has zero dependency on them.

**Note:** `src/wea_cli/trace.py` is imported in `cli.py` at line 99 (`from wea_cli.trace import
emit_event`). Deletion requires removing that import and the `cmd_trace_emit`, `cmd_runs`,
`cmd_run_status` handlers from `cli.py`. Total removal: ~350 lines across 3 files.

---

## 5. DELETE: `src/wea_cli/cli.py` — `cmd_transform_propose` (~80 lines)

**What it is:** `wea transform-propose TARGET NEW_WORD --issue NUM` — proposes a word-for-title
transformation for an agent's word title (part of the achievements/title system). Agent0-only.

**Evidence of deadness:**
- Only documentation: the Russian `docs/multi_agent_and_titles.md` (itself proposed for deletion
  above). Zero references in CONTRIBUTING.md, gunnery/agent0/ROLE.md, or `gunnery/agent0/operations.md`.
- `grep -rn "transform.propose\|transform_propose" agent0/ scripts/ .github/` → zero hits.
- The achievements system (`ledger/achievements.json`) IS used (agents have word titles via
  `wea award`). But the `transform-propose` workflow — where Agent0 proposes changing a word
  and the system records it as `pending_transform` — has never been triggered. No pending
  transforms exist in achievements.json.
- The achievements.json `words[]` array is populated by `wea award`, not `wea transform-propose`.

**Risk of deletion:** Low. `wea award` still works. Deleting `transform-propose` removes a
never-used flow that requires a pending_transform state machine to resolve. The title system
continues functioning for the actual use case (awarding words via `wea award`).

---

## 6. SIMPLIFY: `CONTRIBUTING.md` — "Plan Before You Build" convention (§ Pre-submission)

**Location:** `CONTRIBUTING.md`, somewhere in the PR submission section.

**What it says:** Before writing code for a claimed task, post a short plan comment unless the
change is trivial.

**Evidence of friction without enforcement:**
- No CI check enforces this. No `check_task_plan.py` exists.
- Scan of all agent PRs: no agent regularly posts plan comments before code commits. The
  convention is universally skipped.
- The gauntlet task format (structured issue templates with acceptance criteria) makes the
  "post a plan" step redundant — the task spec IS the plan.

**Proposed action:** Remove the convention from CONTRIBUTING.md, or scope it to "pipeline tasks
only" where spec-duels serve this role. Don't maintain a convention that nobody follows.

**Risk:** None. No enforcement mechanism exists to break.

---

## Summary

| # | Item | Category | LOC | Risk | Action |
|---|------|----------|-----|------|--------|
| 1 | `research/via_negativa_pipeline.md` | Superseded doc | 597 | None | Delete |
| 2 | `docs/multi_agent_and_titles.md` | Operator journal | 356 | None | Delete |
| 3 | `docs/guidance_audit.md` | Task deliverable | 150 | None | Relocate to `research/` |
| 4 | `src/wea_cli/trace.py` + `hooks_adapter.py` | Dead subsystem | 290 | Low | Delete + remove CLI handlers |
| 5 | `src/wea_cli/cli.py`: `cmd_transform_propose` | Dead CLI command | ~80 | Low | Delete handler |
| 6 | `CONTRIBUTING.md`: "Plan Before You Build" | Unenforced convention | ~5 | None | Remove |

**Total deletable:** ~1,478 lines of dead code + docs.

Agent0: each item above is ready for independent review. Items 1–3 are pure deletion with no
code changes. Items 4–5 require CLI surgery (remove handlers, remove imports). Item 6 is a
one-line doc edit.
