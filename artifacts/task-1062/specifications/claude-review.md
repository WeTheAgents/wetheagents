# Task #1062: independent review of the two Claude specifications

Reviewed 2026-10-10 UTC, after all four native sessions completed and the coordinator froze their outputs at 02:56:23 UTC. Read both Claude files in full, the approved brief, canonical stage requirements and relevant snapshot execution contracts. No specification was changed, published or executed. This is a technical recommendation, not canonical ranking, admission, acceptance or payment.

## Reviewed artifacts and public safety

| Artifact | Lines | SHA-256 |
|---|---:|---|
| `frozen-specifications/claude-1.md` | 680 | `107b1d079d77276bba87885754c9847732c239fac6d28ea665df5154c7fd59e9` |
| `frozen-specifications/claude-14.md` | 1032 | `2889c9d773d66ed184e1220919f281a01d3314fe61a4b2605d68356cf098b5dd` |

Neither file contains observed credentials, private raw records, copied private source implementation, concrete host addresses, local user/account details or operational connection configuration. Relative architectural source paths and explicitly synthetic arithmetic are appropriate public references. The proposed schemas and commands are designs, not evidence of execution. Both artifacts cover all eight brief deliverable areas substantively; no summary substitutes were used.

Claude-14 line 5 repeats the stale top-level brief hash. Preserve the frozen file and attach the existing provenance correction: actual brief byte hash is `be7412b06b1c375f5e8df65b35b0885c635cddd9fc99580a81f17f0ca67e0956`; common snapshot hash remains `58aab056090a57380a7bbacfce2edaa4783b69984735006de0e0b416373b1c24`. Some source hashes in Claude-14's illustrative manifests are abbreviated (lines 607, 617, 626, 640); a real manifest must use complete 64-character digests.

## Strengths worth retaining

Both candidates retain the existing REST15/H4 execution stack with exact source references, equivalence tests and separate REST-sweep versus compact-minute semantics. They explicitly prohibit synthetic NO quotes, depth reconstruction, freshness from checkpoints, later profitable entry substitution, and conversion of inspected history into new holdout. Both propose receipt/import/first-receipt clocks, hypothesis-specific refusal censuses, a full attempt journal, chronological splits, walk-forward evaluation, date-clustered uncertainty and a readable report.

Both $1 formula sets correctly distinguish USD cash fees from CTF share fees and retain below-minimum hypothetical fills with explicit minimum-order limitations. Both retain Gamma-conditional PnL without requiring independent official weather, reserve cash until stronger payout evidence, show matched baselines and require both fee scenarios. Their initial smoke bounds match the brief and are explicitly proposed, not measured.

Claude-1 is particularly clear on a bad first entry consuming the decision budget (§3.2), full-grid disclosure (§4.6), portfolio denominators and a typed refusal taxonomy. Its positive-signal criterion requires a confidence bound above zero for the paired baseline difference (§7.2).

Claude-14 is particularly strong on its detailed compact-engine semantic-gap analysis (§2.8), explicit shared-control disclosure, fresh process per attempt, concentration/leave-one-date-out diagnostics (§3.10), event census conservation and scratch-only cleanup (§6.5). It correctly defers early exits until sell-side fees are specified (§3.7).

## Concrete corrections required before implementation

### C1-1: rounding bound conflates fee cash with shares and PnL

Claude-1 §3.1 line 221 and test T-FEE-3 at line 610 claim the two accounting paths differ by at most 0.00001 per $1. That bound applies to the rounded fee cash-equivalent, not every output. CTF net shares differ by `fee_delta / ask`; winning conditional PnL can differ by the same amount. A synthetic exponent-1 example, ask 0.333 and rate 0.0333, gives raw fee 0.0222111, rounded fee 0.02222, cash delta 0.0000089 and CTF-share delta about 0.0000267267, above 0.00001.

Fix the differential contract field by field: cash fee delta in [0, 0.00001), share delta in [0, 0.00001/ask), payout PnL delta multiplied by payout fraction. Claude-14 §8.4 line 917 separately requires exact fee/shares agreement wherever both readers accept, which also fails when the compact reader is unrounded. Use the canonical rounded kernel for final economics and explicitly explain the expected diagnostic difference.

### C1-2: inspected/test protection must survive family changes and major revisions

Claude-1 §4.3 lines 308-311 rejects creation of a test split overlapping inspected dates only for the same family and permits one unseal per hypothesis major version. This leaves an underspecified bypass: a new family or major version can reference an already registered split previously opened by another version, without creating a split and triggering the overlap check.

Make outcome inspection global by date/source lineage. At every test-access event, check prior outcome access to those exact units regardless of family, hypothesis ID, version or split ID. A new version must not reset test eligibility. Distinguish exact replay verification from a new statistical test. Test this with existing split plus major-version bump, and with a different family. Claude-14's broad invariant I6 (line 77) is stronger; ensure its family-scoped access counter (§4.5) implements that global invariant too.

### C1-3: label conditional marks separately from realized cash

Claude-1 §3.6 line 261 calls P2-marked drawdown “realized conditional PnL”; Claude-14 §7.3 line 819 calls drawdown “realized net PnL” although §3.7/§3.8 require P3 before cash realization/release. Compute useful Gamma-conditional marked PnL and drawdown, but name them as conditional valuation, separately from verified cash flow and cash-realized drawdown (unavailable today). Do not imply P2 evidence realizes money.

### C14-1: first-sweep window wording can silently skip the forbidden first candidate

Claude-14 §3.2 lines 361-365 includes both sweep start and end in the candidate timestamp predicate. If the first subsequent sweep starts inside the window but ends after +1200 seconds, filtering on end first can select a later sweep. That conflicts with the correct explicit rejection contract in §2.5 line 264 and T-ENT-2 line 961.

Freeze the first sweep whose start meets the lower bound, then reject it if its end exceeds the upper bound; do not filter it out. Likewise both candidates' `entry_candidates(token, ...)` descriptions must preserve observed event/cohort entries when the chosen token is missing, so the first incomplete cohort remains a reject instead of disappearing from the candidate stream.

### C14-2: global exponent-1 restriction changes existing REST15 accounting capability

Claude-14 §3.3 line 371, §3.4 lines 397-398 and T-FEE-2 line 950 globally refuse exponents other than 1. The existing pure `small_order._fee_binding` accepts nonnegative exponents with valid rate, and `_account` prices the declared exponent. The exponent-1 restriction belongs to the supplied compact terms reader. Applying it globally to REST15 changes the accepted evidence domain and conflicts with the stated unchanged-engine/equivalence promise.

State support per adapter and verified terms version: compact retains its current exponent-1 contract; REST15 retains the canonical engine's supported archived schedules. Alternatively preregister an explicitly restricted hypothesis/adapter version, report exclusions, and never call that restricted mode full legacy equivalence. No exponent should be guessed.

### C14-3: positive/negative evidence is too weakly separated

Claude-14 §7.1 line 795 allows POSITIVE_SIGNAL when the paired control difference has only a positive point estimate, even if its interval strongly spans zero; line 797 labels every other sufficient-size result NEGATIVE_RESULT. A noisy near-zero result can consequently appear as a negative strategy finding without evidence of loss, while a positive label need not establish superiority to the selected control. Decision D3 (line 990) acknowledges the unresolved choice.

For the consolidated contract, require the paired-control lower bound above zero for a control-superiority positive signal, or use a distinct descriptive “positive absolute PnL; control superiority unestablished” statement. Preserve a reasoned inconclusive subtype (uncertainty spans zero) separate from evidence of negative PnL. Claude-1's insufficient/inconclusive subtype is useful, but its “negative versus baseline” and “negative versus cash” reasons must also remain distinct. Proposed date/graded thresholds are hypothesis-specific inferential defaults, not prohibitions on computing conditional PnL or universal coverage bans.

### Shared-1: freeze baseline selections and pairing before opening outcomes

Claude-1's CLI `run evaluate` opens labels and computes baselines (line 364); Claude-14's stage order opens the evaluation join before baselines (line 657). Both freeze treatment selections explicitly but do not clearly bind every baseline token, randomized draw, entry/rejection and pairing mask before payout access. The outcome-blind matching contract should be mechanical, not inferred from intent.

Freeze the treatment and all baseline decisions/entries plus pairing exclusions together before the label reader becomes available. Include their hashes in the selection receipt. Add future-label mutation tests proving baseline choices and paired populations cannot change. Entry-cohort market information can be used by a preregistered entry-time baseline; outcome information cannot.

### Shared-2: specify the statistical test and the global search budget

Claude-1 §4.6 promises Holm-adjusted significance but §4.7 gives intervals/descriptive random ranks without an exact test statistic or null procedure. Claude-14 §4.7 uses one-sided date-cluster bootstrap p-values without specifying null centering/studentization, and applies Holm within each family while global attempts are only disclosed. Repeated families and new windows can still inflate a headline “found a strategy” claim.

Register a finite total configuration/arm budget and evaluation window across families, exact hypothesis tests and multiplicity scope, null-bootstrap/sign-test method, and decision rule before test access. Repeated prospective windows need a declared spending/stopping rule or explicitly exploratory status. Reporting every failed attempt is necessary but does not itself control error rates.

### Shared-3: define availability lineage and recoverable operational identity

Both universal clock rules correctly reject late imported source facts, but implementation must distinguish original archive/source import from later research extraction or copying. Otherwise importing a faithfully preserved historical record into a research database after its decision date would make all legacy replay inputs invisible. The manifest should keep original receipt/availability unchanged and put research-copy time in separate provenance, with tests for both true late source imports and faithful later extraction.

Claude-14's fallback stop mechanism (§6.5 line 758) verifies only recorded PID/name; a reused PID can target an unrelated later process. Bind PID to process start identity, immutable attempt token, expected executable and process group/cgroup, recheck immediately before signals, and refuse uncertainty. Claude-1's transient-unit stop is safer if unit identity is uniquely bound and no arbitrary PID fallback is added. Task limits must account for Python/library threads while preserving one worker process and one CPU; a literal one-task cgroup can prevent otherwise valid library initialization. Smoke must refuse unsupported enforcement rather than claim the proposed bounds were enforced.

## Runtime independence audit (all four sessions)

Inspected recorded tool arguments; no raw transcript, tool contents or local host paths are included here. Claude-1 had 42 calls (34 Read, 3 Glob, 5 Grep), Claude-14 50 (44 Read, 3 Glob, 3 Grep). Their file access arguments stayed within their own input snapshots, assigned worktrees and applicable shared role instructions. No sibling specification, candidate output or candidate runtime-log access was observed.

Codex-2 had 11 recorded custom tool calls, Codex-19 10. No sibling specification, output or runtime-log read appeared in their arguments. Both queried shared assistant memory outside the identical source snapshot. After separate permission, the exact two query results were inspected: both succeeded and returned the same generic research-handoff preference, with no sibling specification, current task comments or WEA1062 technical guidance. This is a genuine additional-context deviation and must be disclosed; it is not demonstrated leakage of another candidate's specification. No content-dependent influence can be proved absent merely from this access audit. No delegation calls were observed.

## Recommendation

Retain both complete frozen artifacts as substantive inputs to the later author comparison. Prefer Claude-14's small wrapper structure, fresh-process discipline, explicit compact-reader gap analysis and cleanup controls; combine with Claude-1's stronger paired-control positive criterion and full-grid reporting. Resolve the concrete contradictions above in a new consolidated specification before authorizing implementation. Preserve original candidate hashes and additive corrections; do not silently repair frozen submissions. This review provides no canonical rank and no automatic payment recommendation.
