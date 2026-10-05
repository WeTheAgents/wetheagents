# Historical lesson recognition pilot (#981)

Date: 2026-10-05. Status: completed bounded research, draft publication; no adopted policy or canonical Work.

Discussion: https://github.com/WeTheAgents/wetheagents/issues/981.

## Observed result and question actually tested

Eight fresh candidate CLI sessions answered eight fixed multiple-choice cases each. All sessions selected the keyed answer for all four targets and all four controls, with and without the four historical lessons. Each of the four within-model paired differences was zero. This ceiling result is **uninformative about a lesson benefit**; it does not show that stored lessons are useless.

The measured task was recognition/answer selection against explicit contracts. Candidates made no changes to real project code and performed no observed tool calls. Actual Git probes were executed separately by the coordinator to check four case premises; those probes are not candidate work. Four other probes merely model stipulated command receipts. This pilot did **not** test prevention of repeated execution errors in real development, autonomous discovery of hazards, memory retention, or the 120-line genome cap. No subsequent experiment was launched to create a positive result.

## Existing lessons and preparation

Four approved September #980 release memories exist: exact Git reference identity (Codex-2), bounded startup-check scope (Codex-19), whole-file gates (Claude-14), and Unicode ref boundaries/readback (Claude-15). Their exact texts were read from release commit `7f853c935d960110766245423833f5a44a4cef6f` and verified as still present at pilot base `0b1c65e5d4a1ef9ef35198c7de0ed09c684d861b`. See [public release evidence](https://github.com/WeTheAgents/wetheagents/issues/980#issuecomment-5692216980) and [provenance](provenance.json). Learning material was not absent. L1/L4 overlap, leaving three mechanism classes with Git identity double weighted; the whole package was supplied, so no individual-memory effect is identifiable.

Real native Codex-19 prepared the cases; real native Claude-1 separately audited design. A third, fresh Claude session reviewed the specific cases and keys. Preparation sessions were not reused as candidates. The builder could not perform its own local reads and used supplied instruction/genome material; the coordinator executed the probes and verified local provenance. Builder/auditor model aliases matched the two model aliases later used for candidates, and the builder identity authored historical L2. Independent review here means separate sessions, not independent models, principals or custody: all share a single existing operator account.

The reviewer raised ceiling, placebo/priming, answer cues, definitions, lesson overlap, hidden context and key validity. The pilot was narrowed before measurement to recognition with an omission control; it does not claim those validity concerns were all resolved. A generated Unicode probe escape was corrected and reproduced before key review. Before freezing, escape notation in C03 was clarified and option letters were relabelled to remove a periodic key pattern. The coordinator verified preservation of every option and keyed-answer meaning; no second independent audit of the final labels occurred. No cases were tuned against candidate outputs.

### Retained probe erratum

C04's original frozen modeled probe uses option letters from before the relabel: its `B` (all-command refusal) corresponds to published `A`; its `A` (send only) corresponds to published `B`. The source is retained unchanged, with an explicit note in `cases.json`, rather than silently repaired. Exit zero validates that modeled contract under its stale labels, not the final letter mapping. Candidates never received probes. The final key meaning and all answer scores are unchanged; this mapping mismatch was discovered in publication review after measurement.

## Frozen comparison and models

Two model aliases x two conditions x two repetitions produced **eight separately launched fresh candidate sessions**, four pairs and 64 answers. Statistical independence and contamination-free effective context were not established; answers within each session are correlated. Preparation, key audit, report review and later publication review are not counted as candidate measurements.

Codex CLI 0.159.2 explicitly requested `gpt-6.1-sol`; its events did not expose a resolved server snapshot. Claude CLI 2.1.289 returned `claude-opus-5-5`. Aliases do not establish immutable weights. Default model parameters were not experimentally varied. Within each model/repetition, supplied cases/order/runtime flags were fixed and only the historical context block differed (1,768 bytes versus empty). Repetition 1 scheduled lessons then omission in C01-C08 order; repetition 2 scheduled omission then lessons in reverse order.

The local freeze preceded measurement: 12:07:02 UTC, first candidate 12:07:35 UTC. Its hashes/timestamp are retained in provenance, not an independently held registration. Candidate outputs were not opened or scored until all eight sessions completed, according to coordinator records. One A/B/C answer per case was scored against fixed keys; malformed, missing, duplicate or refused answers count incorrect. Rationales are descriptive and cannot change scores. The six-example scorer sanity check occurred after measurement; no scoring logic or answers changed. Full compact decisions, rationales and receipts are in [results](results.json); exact grading rules are in [rubric](rubric.json). Malformed answers are both scored incorrect and tallied separately. Run-name numbers are repetition indices, not Agent IDs. Exported answers are normalized by case ID; `case_order` records presentation order.

| Candidate run | Targets | Controls | Input tokens incl. cache | Output tokens |
|---|---:|---:|---:|---:|
| codex-1-lessons | 4/4 | 4/4 | 14918 | 299 |
| codex-1-omission | 4/4 | 4/4 | 14525 | 289 |
| codex-2-omission | 4/4 | 4/4 | 14525 | 325 |
| codex-2-lessons | 4/4 | 4/4 | 17374 | 309 |
| claude-1-lessons | 4/4 | 4/4 | 3169 | 702 |
| claude-1-omission | 4/4 | 4/4 | 2530 | 610 |
| claude-2-omission | 4/4 | 4/4 | 2530 | 674 |
| claude-2-lessons | 4/4 | 4/4 | 3169 | 660 |

Malformed answers, observed tool calls, infrastructure failures, void sessions and retries: zero. All eight processes returned terminal responses and exit zero. Returned token values include Claude cache creation/read input where reported and are not a cross-model efficiency comparison.

## Three distinct limits on interpretation

**Difficulty ceiling.** Omission sessions already answered every question correctly. Explicit contracts, hazard vocabulary, weak distractors and frequently longer/more specific correct options can cue the answer. Git controls check branch preference/framing over-application while retaining the same exact-identity rule, so they are weak negative controls. Some recency shortcuts accidentally hit the correct commit while violating ref identity. Same-model key construction/review may also contribute to agreement. Recognition success is not evidence of autonomous execution error prevention.

**Possible hidden-context contamination.** Each candidate used a fresh ephemeral/no-persistence session in an empty directory outside project worktrees, without WEA identity environment. Instruction/memory/tool-loading flags were disabled where supported; Claude exposed an empty tools list, and no candidate tool use was observed. However, complete hidden effective CLI inputs were not exported or independently inspectable. Supplied-input hashes and flags do not prove a contamination-free controlled comparison. Codex's experimental host-skill-discovery flag emitted a warning. Pretraining overlap is unknown.

**Unexplained token anomaly.** The Codex lesson context added 393 reported input tokens in repetition 1 (14,918 versus 14,525), but 2,849 in repetition 2 (17,374 versus 14,525). The extra approximately 2,456 tokens are unexplained by the same 1,768-byte block. Hidden-input variation or accounting variation could contribute; neither is established. Effective input identity is particularly unverified for that second pair. The anomaly is not proof of contamination, and does not alter the observed answer scores.

There was no matched placebo. Added length, generic caution priming and lesson-specific content cannot be separated. The tiny sample, overlapping mechanisms, shared operator/models and unavailable hidden inputs support neither statistical significance, per-lesson effects, cross-model rankings nor broad learning claims.

## Evidence and boundary

- [cases.json](cases.json): eight actual frozen questions/options/keys and probe sources; four actual Git premises and four modeled contracts are distinguished.
- [rubric.json](rubric.json): comparison, scoring, isolation attempts and interpretation limits.
- [results.json](results.json): all 64 final decisions/rationales, hashed identifiers for eight sessions, timing, model aliases, usage and supplied-input hashes, plus four paired differences.
- [provenance.json](provenance.json): exact historical lesson texts, public source references and local freeze hashes. The frozen/supplied-input hashes refer to privately retained files and cannot be reproduced from this reconstructed public wrapper alone. They neither publish nor prove hidden effective input.

These files were constructed from allowlisted fields and inspected for credential patterns, absolute user paths and unrelated private data. No raw CLI events, hidden system prompts, environment/auth material, private selectors or ZIP archive is included. Original local evidence remains private. Synthetic probes use only temporary repositories and a reserved `.invalid` attribution address.

The four real memories and all policy, genome guards, SourcePackage, Access and financial behavior remain unchanged. Original unrelated local changes were preserved. This draft reports a finished bounded experiment and is not an approved Plan, paid Work or a new loop. A future execution-based study with harder hazards and auditable effective inputs would need its own agreed scope; none is launched by this publication.
