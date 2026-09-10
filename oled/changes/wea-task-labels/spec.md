# Task labels — Spec 1.0

Accepted Outcome 1.0, 2026-09-10. This adds display scenarios L-01 through L-06.
T-04/T-05/T-06 retain funding, retry, and writer authority. Executor 0.9.0 and participant executor 0.10.0 remain unchanged.
The display becomes effective after this implementation merges. Historical replay has no migration.

## L-01: current-stage payment

GIVEN a canonical task and its current Stage Contract.
WHEN Tide derives its labels.
THEN Tide MUST select exactly one payment, reward, depth, and state label.
Flat PoD maps to `pay:pod`. Ranked with one winner maps to `pay:wta`; other Ranked stages map to `pay:best-x`.
Frontier maps to its linear or Fibonacci label. Duel maps to `pay:duel`.
Equal payout vectors use `reward:N-wea`. Other vectors and Duel use `reward:variable`.
The current stage determines these labels, including after progression and suffix replans.

## L-02: funding and availability

GIVEN proposal labels or an unmerged ledger candidate.
WHEN Tide synchronizes labels.
THEN candidate state MUST NOT become canonical display state or authorize Work.
The author sets `state:proposal` before approval and `state:funding` while canonical funding is pending.
For canonical tasks, `state:open` requires active intake or Duel join, an unexpired deadline, and no active pause.
Full PoD or Frontier allocations MUST NOT display open intake.
Closed intake, Duel moves, and decision phases display `state:review`.
Terminal Plans with remaining task or role escrow display `state:settlement`; other terminal Plans display `state:done`.
An active pause displays `state:paused`. GitHub closure prevents an open display without stopping the Plan.

## L-03: metadata scope

GIVEN a canonical task with topic and audience labels.
WHEN Tide replaces managed payment, reward, depth, and state labels.
THEN Tide MUST preserve unrelated labels and the Issue body, type, and open or closed state.
Audience labels describe the operator's recruitment scope. They MUST NOT grant runtime eligibility.
Historical Issues without a canonical vNext task MUST remain unchanged by automatic synchronization.

## L-04: retry and failure

GIVEN canonical main, including a pass with a pending candidate or no financial effects.
WHEN the existing Tide runs.
THEN it MUST synchronize canonical task labels without creating an extra workflow or ledger PR.
Unchanged label sets MUST produce no writes.
GitHub label failures MUST appear in the run report and remain eligible for the next pass.
They MUST NOT prevent independent settlement or change replay evidence.
If main advances before an Issue update, synchronization MUST stop and retry from the next canonical pass.

## L-05: task discovery and summary

GIVEN an active vNext checkout.
WHEN an agent runs `wea tasks` or `wea start`.
THEN the CLI MUST discover `vnext` Issues and display labels without inferring legacy claims or default PoD.
The entrypoint boundary MUST permit this read-only summary without permitting new transaction writers.
Missing or conflicting categories MUST appear as unknown or conflict.
The summary MUST state that labels do not establish funding or eligibility.

## L-06: proposal preparation

GIVEN a new vNext task proposal.
WHEN its author uses the GitHub form and preparation guide.
THEN the form MUST identify a proposal and collect payment, reward, depth, and audience choices.
The guide MUST require the author or Agent0 to apply matching labels before review.
Form fields and labels MUST NOT create a source declaration, escrow, or worker dispatch.
