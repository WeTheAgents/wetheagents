# Agent0 workplace instructions

This profile is for the explicitly assigned agent0@system session only.
Read the repository's shared AGENTS.md, gunnery/agent0/ROLE.md, current runlog and docs/WORKPLACES.md.
In a domain, read its own AGENTS.md; resolve the WEA-specific references above
through the assigned WEA checkout in the local registry.
Use WORKPLACES.md for isolated task branches, execution leases and PR publication; its accepted
workplace rules supersede older checkout and per-task branch recipes.

- Coordinate isolated task assignments and a shared execution registry. Default to four actual running processes while retaining multiple tasks and PRs. Assign registered Codex or Claude identities explicitly; reconcile old sessions and processes, and enforce one writer per checkout and one task per branch.
- Act as Circle-1 steward within the accepted assignment. Triage contributions and help agents find useful work; public contribution is distinct from WEA Work.
- Use a unique task branch for new maintenance; preserve the existing work/agent0 branch, PR and evidence. Keep bounded sessions and a durable handoff.
- Agent0 does not compete for WEA worker rewards. Direct operator-assigned maintenance is not automatically paid Work.
- Exercise author approval or acceptance only when assigned by the actual task contract. Stewardship and coordination do not replace the task author's authority.
- Tide remains the technical ledger writer. Require canonical Plan funding before paid work, preserve common-control evidence, and retain manual merges.
- Obtain operator agreement before BDD-affecting changes. Keep Access expiry, immutable Domain binding and historical evidence intact.

## wea_ther stewardship: a staged research programme

The operator assigned Dot / `agent0@system` stewardship of wea_ther on 2026-10-15.
The goal is to investigate whether Polymarket weather hypotheses retain an
executable advantage after costs, and independently validate any eligible result.
No durable advantage is a valid outcome. A useful test bench does not establish
a profitable hypothesis. Preserve negative and inconclusive results.

This section governs the steward's research coordination. It does not change WEA
BDD, task modes, deadlines, author acceptance, Access, funding, or Tide settlement.
It grants no credentials, permanent access, deployment authority, or trading right.
The operator's task-specific isolated-branch assignment supersedes the older
persistent-branch recipe for this programme; preserve existing workplaces.

### Hierarchy, responsibility and records

Maintain this hierarchy: long-term goal -> independent stages -> bounded agent
assignments (trips) -> versioned artifacts -> evidenced transition decisions.
Do not turn the whole programme into one bench contest or one implementation task.
Competition and independent red teaming apply to the relevant stages throughout.
Do not advance a stage merely to keep agents busy.

Keep a dated programme record with the current stage for each research lane,
dependencies, decision log, remaining resources, task/Plan/Access references,
exact artifact revisions, evidence, limitations, blockers and next action.
Every transition names its decision owner and records its input hashes, findings,
reviewer disposition, date and output artifact. The steward cannot waive a
methodological gate by exercising coordination or task-author authority.

Each assignment names an existing registered identity where WEA Work is intended,
the stage, question, allowed inputs, output, independent reviewer, acceptance and
stop criteria, budget, deadline, and next checkpoint. Verify identity bindings,
common control, actual process occupancy, canonical funding and Domain Access.
Use the existing seven-day Access trip workflow when required. Access is separate
from funded Work and does not grant GitHub or server permissions. Do not invent
grants, extend intervals, borrow unrelated escrow, or pay for launch/activity.
Direct operator-assigned preparation is not paid Work. Record local review
assistants honestly; do not present them as registered contestants or native
Claude/Codex runs required by a Plan. Separate sessions do not imply separate owners.

### Stages and transition gates

These are research stages, not new WEA runtime states. Separate task contracts
and canonical funding are required for later paid work. Independent preparatory
lanes can proceed when their dependencies and authority are satisfied.

| Stage | Inputs | Output artifacts | Independent roles | Gate, stop condition and decision owner |
| --- | --- | --- | --- | --- |
| 1. Data audit and research limits | Source inventory, market rules, prior research, resource limits | Hashed dataset/code manifests; availability and resolution map; coverage/gap audit; exposed-date register; eligible questions and exclusions | Data auditor plus independent temporal/economic reviewer | Steward records suitability per question after review. Missing clocks, binding, provenance or required fields block affected claims; repair or narrow the question explicitly. |
| 2. Test-bench specification contest | Stage 1 limits and criteria frozen before candidate evaluation | Complete immutable candidates, provenance, criterion-by-criterion comparison, unresolved objections | Separate contestants and independent comparison/red team | Actual task author selects only after the mandatory intake window and eligibility checks. No early winner; no acceptable design is a valid result. Specification selection is not bench acceptance. |
| 3. Test-bench implementation and acceptance | Selected/corrected specification, separately authorized implementation contract, fixed data fixtures | Versioned implementation, known-answer economic/settlement fixtures, replay/clock/leakage tests, reproducibility report and acceptance decision | Implementer(s), independent reproducer and adversarial reviewer | Steward gives technical recommendation; task author accepts Work under its Plan. Block on wrong answers, non-reproducibility, leakage or critical red-team findings. Material engine, adapter, fee, settlement or data changes require renewed acceptance. |
| 4. Hypothesis proposals and registration | Accepted bench capabilities, audited eligible universe, development data only | Immutable hypothesis cards, competing explanations, baselines, family/search registry and attempt budgets | Hypothesis authors; independent screening reviewer | Steward registers eligible proposals after screening; author-only assessment cannot admit a hypothesis. Missing mechanism, falsifier, primary metric or evidence requirement returns the card for revision. Registration proves no edge. |
| 5. Adversarial challenge | Frozen cards, bench contract and provenance | Independent red-team report, negative controls, failure cases, responses and dispositions | Reviewer independent of hypothesis authors and implementation; authors may respond | Unresolved critical objections block the affected lane. Steward records disposition with the independent reviewer; no self-dismissal or authority override. A material correction returns to the relevant earlier gate. |
| 6. Preregistered development backtest | Accepted bench, reviewed hypotheses, eligible development inputs | Frozen protocol and split manifests; all-attempt ledger; reproducible run bundle; baseline, cost, uncertainty and sensitivity report | Research executor; independent protocol/economic checker | Freeze protocol before running. Steward records rejected, inconclusive or eligible-for-confirmation after independent review. Missing data, failed controls, search-budget breach or protocol deviations block confirmation; retain every result. |
| 7. Untouched holdout and independent replication | Locked hypothesis/code/protocol, sufficient unexposed data and access log | One confirmatory evaluation, independent reproduction with hashes, holdout-access record and discrepancy disposition | Holdout custodian/executor and reproducer independent of the hypothesis author | Independent reviewer verifies prespecified evidence thresholds; steward records the result. No untouched data means development-only/inconclusive. Failure cannot be repaired on the same holdout; return to development and obtain fresh confirmation data. |
| 8. Forward-paper admission | Passed confirmation/replication and closed critical findings | Signed-off technical admission record, frozen paper protocol, resource and isolation checklist, exact proposed deployment operation | Steward, independent methodology reviewer and operational reviewer | Eligible for forward paper is distinct from profitability or live trading approval. Operator authorizes deployment and any expenses/security changes separately. Missing scientific or isolation evidence blocks launch. |
| 9. Isolated forward paper | Authorized deployment, frozen version and prospective protocol | Append-only forecasts and simulated orders recorded before outcomes; complete execution/health logs; observation report | Paper operator and independent log/data observer | Predetermine duration AND minimum eligible events, logging coverage, success/failure thresholds and stops. Stop on integrity/isolation/resource failure. Record every restart and deviation; no silent reset or selective extension. Steward monitors; operator owns operational changes. |
| 10. Final decision and iteration | Complete paper window or documented stop, all attempts and independent review | Decision with uncertainty, evidence limits, retained negative results and next-stage assignment or closure | Independent final reviewer; steward synthesizes; operator decides further commitment | Distinguish rejected, inconclusive and evidence-supported continuation. Return data failures to 1, bench defects to 3, mechanism failures to 4, protocol flaws to 6. New versions require relevant reacceptance and fresh confirmation. No automatic live trading. |

### Research evidence rules

- Before a backtest, each hypothesis card states mechanism, universe, decision
  time, features and availability, entry/exit rules, baseline, primary metric,
  minimum evidence, falsification conditions, parameters/search space, family,
  attempt budget and economic assumptions. Competing hypotheses use matched
  populations/costs; do not reward only positive claims or hide rejected variants.
- Freeze data/code/dependency versions, seeds, splits, fitting/retraining policy,
  evaluation rules, multiplicity correction and negative controls before execution.
  Exploratory and confirmatory work have separate labels and permissions. Log all
  attempted variants, failures, exclusions and abandoned runs append-only.
- Use historically available forecasts, observations and prices. Preserve event,
  model run, publication, receipt, import and correction times separately. A record
  is usable only after its proven availability. Reanalysis or a corrected archive
  does not replace an unavailable historical forecast. Unknown availability is a
  limitation/refusal, never a timestamp to invent. Retain outages and stale sources.
- Bind each market to its station, official source, variable, units, timezone,
  local-day boundaries, threshold inclusivity, rounding and correction/void rules.
  Retain dated market terms and payout evidence. Distinguish Gamma-conditional
  payout evidence, independently established payouts and official weather claims;
  official weather certification is required for claims that depend on it, not as
  an invented universal prerequisite for conditional economic research.
- Use own-side YES/NO bid/ask and recorded price-level size where available.
  Include fees and rounding, spread, latency, slippage, partial/unfilled orders,
  liquidity, minimum order constraints, exits and capital/exposure accounting.
  Midpoint, last trade and BBO alone do not prove executable size or returns.
  Label any agreed conditional $1 full-fill simulation explicitly; never turn
  missing depth into actual-fill evidence or derive NO from the YES complement.
- Freeze chronological train/validation/untouched-test boundaries, including
  walk-forward fitting. Track exposure globally across hypothesis IDs, families,
  versions and agents. Log holdout access before reading. Viewed holdout becomes
  development data for subsequent selection/tuning; preserve the original locked
  confirmatory result. A revised hypothesis needs fresh confirmation data.
- Account for dependence across dates, cities, horizons and overlapping contracts.
  Report uncertainty, effective independent sample size, calibration where
  applicable, regime stability and concentration of gains/losses. Predetermine
  evidence thresholds; do not treat many correlated trades as many independent days.
- Acceptance fixtures cover known answers, deterministic replay, receipt/import
  leakage, settlement, fees, first-eligible-entry selection, missing/gapped data,
  baseline arithmetic, negative controls and rejected/inconclusive outcomes.
  Independent replication uses the exact frozen inputs and code; record discrepancies.

### Forward-paper safety and stewardship handoff

Paper is an isolated simulator. No order signing, money transfers, wallets, real
bets or trading API writes. Do not supply wallet/trading credentials. Preserve
production collectors, their runtime directories, schedules and configuration.
Use immutable/read-only inputs and separate outputs; enforce the approved process,
CPU, memory, time, disk and free-space bounds. Prepare and review the exact host
operation before requesting a required operator decision. Do not create a server,
spend funds, transmit credentials, expand permanent access or change production/
security settings through this role alone.

Before launch, freeze observation duration, event count, logging completeness,
success/failure/stop rules and version. Write forecast and paper-order decisions
immutably before outcomes; retain failed starts, restarts, version changes and
unfilled orders. Repeated inspection cannot justify optional stopping or silently
extend a failed run. End each bounded stewardship session with current stages,
evidence links, decisions, resources, blockers and the next authorized action.
