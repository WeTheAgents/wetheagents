# Public repository layout

The 2026-10-04 audit inspected all 1,240 tracked files, current runtime imports and fixed paths, CI workflows, hook dispatch, role discovery and documentation references. Agent work instructions and reusable tools now live in Gunnery. Protocol records and fixed build/runtime entrypoints retain their established paths.

## Moved into Gunnery

| Previous location | Canonical location | Reason |
| --- | --- | --- |
| `AGENT0.md`, most of `agent0/` | `gunnery/agent0/` | One home for Agent0's role, guides and worker helpers |
| `runlog.md` | `gunnery/runlog.md` | Agent0 handoffs belong alongside its work instructions |
| Full `.agents/skills/` instruction bodies | `gunnery/skills/` | Shared agent knowledge; discovery adapters remain in `.agents/` |
| Active `.claude/commands/` instruction bodies | `gunnery/commands/` | Shared command guidance; discovery adapters remain in `.claude/` |
| `.githooks/` implementation bodies | `gunnery/hooks/` | Shared validation tools; configured Git hook adapters remain |
| `wea-advisor-mcp/` | `gunnery/tools/wea-advisor-mcp/` | Optional agent issue-proposal tool, including its unchanged dependencies |
| `benchmarks/caveman/` | `gunnery/benchmarks/caveman/` | Optional agent prompt experiment, outside the public root |
| `contrib/` | `gunnery/contrib/` | Proposed reusable agent utilities |
| `audit_map.md`, `baseline_report.md`, `report.md`, `submission.md` | `gunnery/archive/root-reports/` | Completed task reports, retained byte for byte as historical evidence |
| `deliverables/` | `gunnery/archive/deliverables/` | Completed architecture/reconciliation reports, retained byte for byte |

Current `commit-push-pr` and `review-pr` guidance follows WORKPLACES.md and required native Codex review. The old task-branch workflow and reference to nonexistent `.claude/agents/` are replaced. Command adapters retain their existing tool metadata and confer no additional authority.

## Removed from active use

- `scripts/censor_diary.py` and its direct test: the operator retired diary vocabulary censorship on 2026-10-03; the active hook already stopped invoking it. Diary content and policy history are retained.
- `.claude/commands/clean-gone.md`: its branch/worktree deletion recipe conflicts with the accepted preservation policy. The recipe remains in `gunnery/archive/retired-commands/`, explicitly marked non-effective.

These removals are recoverable through Git. No worktree, local dirty file or history was discarded.

## Retained outside Gunnery

| Location | Why it remains |
| --- | --- |
| `src/` | Released runtime/package bytes and active protocol implementation; the accepted package hash remains unchanged |
| `pipeline/` | Existing CLI, verification and release code use fixed paths to its configuration and schemas |
| `scripts/` | Core verification/CLI infrastructure with established imports and fixed paths; relocation of all scripts would require a broader runtime transition |
| `tests/` | Current and historical contract/regression evidence; age alone does not make a test obsolete |
| `oled/` | Normative BDD, scenario-registry inputs and historical Hello World attestation validator/data; deleting or moving it breaks accepted evidence |
| `ledger/`, `evidence/` | Canonical economy, identity, Access and replay records, with stable bindings |
| `genomes/`, `agent0_diary/` | Approved agent constitutions/memory and diary history |
| `reports/` | Accepted pilot/Access evidence and existing verification links |
| `research/`, `lore/` | Retained historical context and protected archival prefixes |
| `domains/` | Canonical domain registry and approved project-separation breadcrumbs |
| `docs/` | Public participation/protocol documentation and the existing static website |
| `assets/` | The single approved README cover image |
| `.github/` | GitHub discovers workflows and CODEOWNERS here |
| `.agents/`, `.claude/` | Minimal skill/command discovery adapters; canonical instructions are in Gunnery |
| `.githooks/` | The configured Git hook path; adapters execute Gunnery implementations |
| `agent0/` | Minimal role/PowerShell adapters and established operations/ledger/task-index references; ignored Telegram queue/state retain their original local paths to preserve offsets |

## Root files retained

| Files | Purpose |
| --- | --- |
| `README.md`, `WHY.md`, `CONTRIBUTING.md`, `MAP.md`, `LICENSE` | Public introduction, participation, navigation and licensing |
| `AGENTS.md`, `CLAUDE.md` | Agent instruction discovery and project rules |
| `AGENT0.md`, `runlog.md` | Established links forwarding to canonical Gunnery content |
| `pyproject.toml`, `uv.lock` | Python package build, dependencies, test configuration and reproducible dependency lock |
| `worker.js`, `wrangler.jsonc` | Existing website hosting entrypoints; Wrangler serves `docs/` assets |
| `.editorconfig`, `.gitattributes` | Formatting and Git line-ending rules |
| `.gitignore` | Local credentials, raw inbox state and generated artifacts stay out of Git; moved inbox paths retain exclusions |
| `.semgrep.yml`, `.semgrepignore` | Security rules and existing scanner ignore behavior; an empty ignore file was not assumed equivalent to its absence |

Changing normative BDD, frozen runtime paths or canonical record locations is outside this cleanup. The website is unchanged in this PR. Optional MCP/benchmark services are not started by relocation, and account selection remains wetheagents: `peachgabba22`; Legalbet: `peachgabba-mc`.
