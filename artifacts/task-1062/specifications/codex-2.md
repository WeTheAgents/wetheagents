# WEA #1062 — Hypothesis-testing framework specification

**Candidate:** Codex-2@codex  
**Specification version:** 1.0  
**Scope:** Research specification; implementation requires a separate decision.

## 1. Outcome, authority and evidence

The framework must answer a bounded question:

> Under a preregistered information set, population and execution assumption, does a specified weather-market hypothesis produce a worthwhile net economic advantage over matched simple controls, and how strong is that evidence?

Its outputs are reproducible experiment artifacts and a readable report. A completed experiment may establish a positive signal, a negative result or insufficient data. Successful execution does not establish profitability.

This specification covers hypothesis definitions, archive compatibility, conditional execution, evaluation, experiment history, CLI behavior, a bounded research runner and migration. It does not authorize implementation, trading, deployment, collector changes, scheduler changes, additional data acquisition or publication from this session. A separate website is outside scope.

The supported specification stage has four equal 5 WEA ranked places, totaling 20 WEA, with seven-day intake followed by a one-day author decision window. Budget approval, canonical funding, native execution, eligible Work and payment are separate events. Funding is confirmed by the dispatch; this document does not independently establish settlement authority. Later implementation and review allocations remain unallocated.

The coordinator must retain native-session provenance and freeze this complete specification as one public-safe UTF-8 Markdown artifact, at most 1 MiB, under `artifacts/task-1062/specifications/`, referenced by an immutable full commit. Local capture alone is not canonical Work or payment. Independent candidate sessions do not imply independent ownership.

### Evidence boundary

Architecture statements below derive only from the assigned source snapshot:

`58aab056090a57380a7bbacfce2edaa4783b69984735006de0e0b416373b1c24`

All 66 file entries in `snapshot-manifest.json` matched their listed sizes and SHA256 values during this read-only session. No source was edited, backtest executed or server accessed.

References use original relative repository paths. Their inspected copies are under `source-prerequisite/`. Proposed files and behaviors are explicitly described as proposed.

The governing inputs are:

- `candidate-brief.md`, `spec-stage-proposal.md`, `approved-plan.json` and `approved-plan.md`.
- `snapshot-manifest.json` and `source-prerequisite-manifest.json`.
- `data_contract.md`, `compact_contract_v2.md` and `README.md`.
- The provided REST15 and replay engines, protocols, adapters and tests.

The supplied evidence establishes important limits:

| Evidence | Supported interpretation | Unsupported interpretation |
|---|---|---|
| Previously inspected REST15/H4 dates | Development-only evidence | New untouched holdout |
| Legacy projection plus 640 exact H4 inputs | Preserved inputs for bounded replay and equivalence work | Full historical orderbook or depth archive |
| Legacy REST receipts/checkpoints | Actual retained observations with original clocks | Fresh minute quotes |
| First compact daily audit | 15 known pre-r7 split minutes excluded; 40 post-r7 minutes checked within one cohort | Demonstrated live cohort transition |
| 41 Gamma final payout vectors | Potentially usable payout-proxy evidence after binding validation | On-chain payout or redeemable-cash proof |
| Current historical test population | `independent_test_dates = 0` | Confirmatory performance evidence |

These are input facts, not measurements produced by a new experiment in this session.

## 2. Hypothesis contract and preregistration

### Versioned hypothesis schema

Every executable hypothesis must have an immutable `hypothesis.v1` document. Unknown required fields, unsupported major versions or ambiguous units refuse execution.

| Field | Type and requirement |
|---|---|
| `schema_version` | Exact supported schema identifier |
| `hypothesis_id`, `revision`, `family_id` | Stable identifiers; revision changes whenever behavior changes |
| `claim`, `mechanism`, `claim_scope` | Falsifiable statement, rationale and economic/forecast/descriptive scope |
| `evidence_mode` | `development`, `exploratory` or `confirmatory` |
| `adapter_id`, `adapter_version`, `engine_id`, `engine_version` | Explicit data and execution semantics |
| `input_contracts` | Required schemas, source roles, versions and suitability predicates |
| `population` | Target dates, station/market criteria, horizons, discovery/existence rules and exclusions |
| `decision_clock` | Local clock/window, timezone policy, DST policy and input cutoffs |
| `features` | Definitions, units, lookbacks, availability rules and revision handling |
| `parameters` | Complete resolved values; no hidden defaults |
| `search` | Allowed configurations, fitting objective, maximum attempts and selection rule |
| `signal` | Eligibility predicate, side/token selection, probability construction and deterministic tie-break |
| `entry` | First-attempt selector, latency/window and validity requirements |
| `exit` | Hold-to-payout or a separately versioned timed-exit rule |
| `economics` | Notional, fee modes, stress scenarios, capital limits and minimum-size treatment |
| `baselines` | Named controls with matching and exclusion rules |
| `splits` | Immutable split identifier, chronology, warm-up, purge and access policy |
| `evaluation` | Primary estimand, worthwhile-effect threshold, uncertainty method, adequacy criteria and decision rule |
| `seed` | Integer plus named random-number algorithm |
| `provenance` | Parent revisions, registration digest and selection history |
| `limitations` | Explicit unsupported claims and prerequisites |

Decimal prices, fees and cash values are serialized as decimal strings. Times are UTC instants with source precision retained; local dates carry an IANA timezone. Missing values are explicit nulls with reasons, never fabricated zeros.

Population, clocks, thresholds, baselines, fee assumptions, evaluation and search policy must be frozen before evaluating labels. Changing any of them creates another registered revision and attempt. Fixing an implementation defect also records the affected revisions and whether previously accessed test data are compromised.

### Example A: ensemble-NO valley hypothesis

**Identifier:** `ensemble_no_valley.v1`  
**Relationship to source:** Preserve the H2 mechanism in `artifacts/replay_2026-10-08/signals.py` and `protocol.json`.

At the fixed T−1 evening decision:

1. Require at least four distinct fresh forecast families.
2. Require two groups with at least two families each, separated by at least 2°C under the existing deterministic clustering policy.
3. Require the latest available TAF to cover the contractual station’s local 12:00–18:00 peak window and contain the specified low-cloud and clear regimes.
4. Construct the existing equal-family, equal-member mixture with the fixed 1.5°C kernel.
5. Select the interval containing the mixture mean before consulting prices.
6. Require its moment-matched unimodal probability to exceed mixture probability by at least 0.05.
7. Evaluate buying that interval’s own NO token under the frozen execution mode.

The evaluation separates:

- Whether the probability distinction improves forecast diagnostics.
- Whether the resulting decision policy improves net economics over cash and a preregistered simpler policy.

The same-token unimodal control is a forecast/gating comparator. If both arms buy the identical token at the identical time and cost, their trade PnL is mechanically identical; that cannot demonstrate incremental economic value.

Daily maxima and TAF support this pilot. They do not establish causal cloud/member branch mapping. That stronger claim requires additional paired hourly evidence.

### Example B: price-path reaction hypothesis

**Identifier:** `price_reaction_continuation.v1`  
**Relationship to source:** New proposed family, not an existing demonstrated strategy.

Use the compact archive only. At a fixed T−1 evening decision, compare complete observed event cohorts at the decision and 60 minutes earlier.

For each interval:

- Calculate the change in its own YES ask.
- Require an upward change of at least 0.03 and an increase of at least 0.02 in the preregistered ensemble YES probability.
- Require valid coverage throughout the specified comparison window.
- Select the greatest qualifying ask change, with ties resolved by stable market ID.
- Buy the selected YES token using the first frozen entry cohort.
- Hold to payout.

The proposed thresholds are registration choices, not evidence-derived findings. A reversal variant is a different configuration, counted in the same search family.

Primary evaluation is conditional net economic advantage over cash and a final-model edge policy using the same dates, cohorts and costs. Secondary evaluation measures own-bid changes at fixed +60-minute and +180-minute horizons. Those horizons are diagnostics; they do not create executable exits unless a timed-exit protocol was registered.

Missing path observations refuse this hypothesis instance. A REST15 retained endpoint pair cannot be relabeled as a minute path.

### Example C: forecast revision structure

**Identifier:** `forecast_revision_structure.v1`  
**Relationship to source:** Preserve H3 in `signals.py`, `run.py` and the REST15 protocol.

Require five fresh families at the fixed noon and evening clocks, with target-specific arrays and actual change history.

Report both existing arms:

- **Single revision:** exactly one family mean changes by at least 1°C; all others change by at most 0.3°C.
- **Common revision:** at least three families change in the same direction by at least 0.5°C.

Qualifying changes must have persisted for at least one hour through uninterrupted observed target-state history. Comparing noon and evening snapshots alone does not prove persistence.

Select the largest permitted final-model probability-minus-own-ask gap across YES and NO using the existing fixed edge threshold and deterministic tie-break. The hypothesis does not assume that revisions should always be followed or faded.

Compare against the same final-model policy without the revision gate. Both arms, their controls and their exclusions remain visible. Choosing the better arm after evaluation is exploration.

### H4 preservation

The framework must also support the existing residual-memory policy without silently broadening it:

- Prior exact-bound outcomes available before the current signal.
- Station/lead-matched GEFS forecasts.
- Existing censored innovations, expanding calibration, shrinkage and residual-memory calculation.
- The existing METAR reset policy with explicit units and correction clocks.

The preserved 640 exact inputs are an equivalence resource. They neither supply all missing execution quotes nor become independent test observations.

## 3. Data and adapter contracts

### Common normalized records

Adapters expose immutable records, not trading clients:

- `BindingVersion`
- `ForecastVintage`
- `ObservationVersion`
- `QuoteObservation`
- `ExpectedCohort`
- `Gap`
- `OutcomeVersion`
- `SourceManifest`

Each carries a source-record identity, content/provenance digest, applicable binding, availability clocks, quality status and lineage. Every decision records the exact input-record references used.

### Clocks and availability

The following clocks must remain distinct:

| Clock | Meaning |
|---|---|
| Event/valid time | Time described by an observation, forecast or market target |
| Model issue/run time | Actual supplied model vintage; unknown if not proven |
| Publication time | Proven upstream release time, where available |
| Request time | Acquisition request or subscription action |
| Original receipt time | First receipt of that source record |
| Import availability | Time a late import became available to the replay system |
| Normalization time | Time a derived representation was created |
| State validation time | Successful current observation or healthy initialized subscription validation |

Operational replay availability is the latest applicable receipt/first-receipt/import-availability clock. Issue time, expected initialization and upstream publication cannot move availability earlier than actual receipt.

Normalization performed later on an already captured immutable historical record does not create a new historical source receipt. Its `derived_at` timestamp is separate. Conversely, a later backfill cannot gain historical availability merely by copying an old source timestamp.

Adapters must preserve and document this distinction. Ambiguous import semantics refuse claims dependent on historical availability.

Weather and metadata normally use the inherited signal-minus-five-seconds cutoff for the existing pilots. Signal quotes use their explicitly registered signal-cohort clock. Entry quotes and execution terms are validated at entry without reopening signal selection.

Corrections apply forward from their actual availability. A latest invalid record blocks its required input; the adapter cannot silently select an older valid record.

### Binding and interval identity

A binding includes:

- Event, market, condition and own YES/NO token IDs.
- Trading asset/protocol identity where distinct.
- Contractual station or documented exact mapping.
- Source, native unit, IANA timezone and target local day.
- Literal rules hash and metadata revision.
- Native interval endpoints, inclusivity and unbounded-tail flags.
- Tick, minimum-order terms, fee schedule and active state.

Derived continuous rounding cells remain separate from contractual native intervals. `bracket_index` is not temperature order. Sort parsed contractual bounds.

Legacy title parsing is retained only within its frozen supported grammar. Unsupported wording refuses interpretation. New explicit interval bindings must not silently change historical parsing.

A rule/token/fee/active-state change between decision and entry rejects the attempt, including a change followed by restoration. A narrowly documented historical source enrichment does not permit general rule-text normalization.

### Adapter A: retained REST15 observations

**Sources:** `artifacts/rest15_2026-10-08/adapter.py`, `replay_rest15.py`, `small_order_rest_v3.py`, `protocol_rest15_v3.json`.

The adapter must:

- Use read-only evidence/index access.
- Verify retained records against pinned native provenance.
- Preserve actual receipts and request identities.
- Build sweeps chronologically, splitting at receipt gaps of at least 60 seconds.
- Require certified full event interval/token inventory for admitted sweeps.
- Retain the sequential, non-atomic nature of observations.
- Preserve the earliest retained signal sweep rather than claim the globally first historical sweep.
- Select the first subsequent retained sweep beginning at least 60 seconds after decision, then validate its end against the 1,200-second deadline.
- Require sweep duration at most 120 seconds and chosen quote age at most 120 seconds at sweep end.
- Record chosen-token receipt separately from logical conditional entry at sweep end.

The first selected sweep remains frozen if it is incomplete, invalid or outside the ending deadline. A later favorable sweep cannot replace it.

This mode supports bounded retained-subset diagnostics and eligible mechanisms with sufficient native inputs. It does not establish between-poll continuity or minute-path coverage. Missing latest catalogued metadata refuses admission without older fallback.

### Adapter B: legacy projection and exact H4 inputs

The projection must retain:

- Selection lineage and its infrastructure-driven scope.
- Original clocks, source IDs and binding grades.
- Partial/completeness flags.
- Exact preserved inputs and their hashes.
- Known omissions and unavailable record classes.

Permitted uses include signal replay, H4 feature equivalence, proper-score diagnostics and economics where actual required own-side quotes and terms survive.

Explicit refusals include:

- Depth simulation without retained native ladders.
- Path/reaction testing without the required observations.
- Persistence claims across unobserved gaps.
- Synthetic minute entries from receipts or checkpoints.
- Population-wide opportunity counts from partial extraction.
- Reclassification as untouched test data.

Adapter suitability is evaluated per hypothesis. The strict historical runner’s partial-input refusal remains unchanged. A new registered retained-subset experiment may have narrower admissibility, but must identify its limited population and cannot describe missing records as zero opportunities.

### Adapter C: prospective compact archive

**Sources:** `compact_contract_v2.md`, `src/compact_replay.py`, `artifacts/replay_2026-10-08/compact_matrix.py`, `small_order.py`, `protocol_small_order_v2.json`.

The expected matrix is:

`event × every contractual interval × YES/NO × planned minute`

Both tails and each token’s own bid/ask are mandatory. Expected cohorts come from an independently retained as-of inventory, not whichever quote rows happen to exist.

Record separately:

- Planned, recorded, validated and economically usable cells.
- Observed empty sides.
- Missing records and explicit gaps.
- Cohort ID, epoch and maximum skew.
- Original quote receipt/change timestamp.
- Current state-validation evidence.
- Fee and execution-term binding.

Changed quotes plus minute heartbeats are acceptable. A heartbeat refreshes validity only after a successful source observation or continuously healthy initialized subscription. Cached replay is not a fresh observation.

For the inherited minute mode:

- Freeze the first distinct observed cohort at signal +60 through +300 seconds before content validation.
- Require validated-state age at most 120 seconds.
- Require cohort skew at most five seconds.
- Require no intervening gap or reconnect.
- Require active binding and tick-aligned `0 < bid <= ask < 1`.
- Permit an old price-change timestamp only when current healthy-state validation is independently established.

Known pre-r7 invalid minutes remain excluded by an evidence-backed exclusion list. Forty checked minutes within one cohort do not certify cohort transitions. Synthetic transition tests validate implementation; prospective observed transitions are a separate acceptance prerequisite.

### Hypothesis-specific suitability

| Hypothesis | Necessary evidence | Missing evidence consequence |
|---|---|---|
| Ensemble-NO pilot | Fresh family maxima, TAF peak coverage, full event binding/cohort and own NO quotes | Refuse affected instance |
| Price-path reaction | Registered comparison/path cohorts and own-side quotes | Refuse path evaluation |
| Revision structure | Five-family target vectors and uninterrupted change history | Refuse persistence-dependent signal |
| H4 memory | Prior available bound outcomes, matching forecasts and required METAR reset features | Main arm blocked; separately registered ablation may differ |
| Remaining maximum | T0 quotes, remaining-hour member paths and contractual observed running maximum | Remains blocked |
| Strict depth mode | Actual native ladders and inherited depth/fee guards | Refuse strict execution |
| Conditional economic analysis | Reliable bound payout evidence | Official weather absence alone does not block |

There is no universal coverage percentage. Required completeness follows the particular decision: a full-event ranking requires all relevant intervals; a path requires its registered observations; weather verification is required only for claims using weather truth.

### Refusal taxonomy

Every excluded opportunity records all applicable reasons and a deterministic primary reason:

- `not_applicable`: outside population or not yet existing.
- `no_signal`: valid inputs, hypothesis predicate false.
- `data_unavailable`: absent required input or unknown coverage.
- `data_invalid`: identity, units, interval, clocks or numeric defects.
- `execution_unsupported`: missing own quote, invalid first entry, gap, terms or fee failure.
- `outcome_unavailable`: selection/entry retained, evaluation pending or bounded.
- `budget_exhausted`: frozen capital constraint prevented entry.
- `run_integrity_failure`: hash, schema or journal corruption.
- `resource_limit` or `cancelled`: operationally incomplete.

An observed empty book is validly recorded but unavailable for the required execution. No-signal is not missing data. An unresolved payout does not erase a position.

## 4. Conditional execution, accounting and controls

### Execution claim

The primary compact economic model assumes a fully filled **$1 gross-notional purchase** at the selected token’s own ask. It is conditional.

It does not prove displayed size, actual minimum compliance, share precision, queue position, market impact or a real fill. Minimum-order flags do not silently remove the authorized hypothetical trade.

For own ask \(p\):

\[
q = 1/p
\]

where \(q\) is gross shares. NO uses its own ask. Complementing a verified binary probability is distinct from inventing a NO price; the latter is prohibited.

For the inherited supported fee formula:

\[
F=q\,r[p(1-p)]^e
\]

Use the archived rate, exponent, applicability, protocol and versioned rounding policy. The existing small-order engine uses upward cash-equivalent rounding to `0.00001`; that is a pinned scenario assumption unless actual matching terms establish it.

Unknown or contradictory fees refuse primary net economics. They cannot default to zero. Gross-only diagnostics may remain explicitly incomplete.

Two complete portfolios are reported when fee-asset semantics require scenarios:

| Mode | Entry cash | Payout shares |
|---|---:|---:|
| USD cash fee | \(1+F\) | \(q\) |
| CTF share fee | \(1\) | \(q-F/p\) |

Do not choose the more favorable fee mode per trade.

For payout per share \(y\), hold-to-payout net PnL is:

\[
\text{net PnL}=yq_{\text{net}}-\text{entry cash}-\text{additional costs}
\]

Gross PnL uses pre-fee shares and excludes fees/reserves. Reports show the reconciliation between gross and net explicitly.

### Exits and payout evidence

Version 1 defaults to hold-to-payout. Timed exits require another registered protocol specifying the first exit observation, deadline, own bid, fees, invalid-exit handling and residual-position treatment.

A missing exit cannot trigger hindsight liquidation at the best later bid. Midpoints are not executable exits.

Outcome records preserve the full bound YES/NO payout vector, status, original availability and later revisions. Evidence axes remain separate:

1. Final payout-proxy compatibility.
2. Independently verified contractual weather.
3. Verified on-chain payout/access.
4. Observed cash realization.

Reliable Gamma final vectors may support conditional proxy PnL after exact binding validation. They do not prove weather certification, on-chain payouts or realized cash. Partial, conflicting or pending outcomes retain uncertainty.

For unknown payouts, report position and portfolio bounds. Where verified geometry supports complementary or mutually exclusive outcomes, reuse coupled bounds rather than summing impossible independent winners.

### Minimums and capacity

For every trade and stress arm record:

- Gross and net share quantities.
- Archived minimum and units.
- Whether that minimum applies to the modeled order semantics.
- Below-minimum/unknown status.
- Available own-side size, if retained.
- Actual share precision status.
- `full_fill_assumed=true`, `observed_fill=false`.

A minimum-compliant sensitivity is separate and runs only where applicability is documented. It reports its different stake and denominators; it cannot replace the $1 headline.

Compact BBO does not establish scalable capacity. Optional size observations support diagnostics, not a reconstructed depth history.

### Frozen entry and capital

Signal, token, arm and first entry candidate are frozen before outcome lookup. The economic engine does not reselect a token or impose an unregistered entry-time EV gate.

Each arm, fee scenario and stress portfolio receives separate preregistered capital. For inherited REST15 reproduction, preserve its $1,000-per-arm/scenario allocation.

Reserve full entry cash and required cost reserves. Gamma marks never unlock capital. Conservative version 1 reserves held positions for the run unless separately verified release evidence and a registered release policy exist.

Concurrent admissions use a frozen ordering by decision time, event ID and token ID. Capital failures remain journaled; do not reorder to favor winners.

Report maximum committed cash, peak exposure, event/date concentration, capital shortfall and capital-time usage. Complementary NO positions remain correlated.

### Stress tests

Report all fixed scenarios:

- Recorded ask.
- Ask +0.01.
- Ask +0.02.

Round upward to the native tick. A stressed ask at or above one is unsupported, not capped. Each repriced scenario spends $1 gross and recomputes shares, fees and minimum flags.

Separately report same-quantity additional-cost reserves of 0.01 and 0.02 per gross share. These retain original quantity and are not interchangeable with repricing.

Further preregistered sensitivities may include delayed entry, adverse exit bids, documented minimum-compliant stakes, payout bounds and missing-data sensitivity. They create additional counted configurations when they affect selection or claims.

### Matched baselines

Every experiment includes cash/no-trade and a simple mechanism-relevant control.

Controls share:

- Intended dates and population.
- Availability cutoffs and first entry observations.
- Binding validity and outcome evidence.
- Fee/stress assumptions.
- Capital and admission ordering.

Baseline-specific required token quotes must also be available. Report both standalone populations and paired comparisons. Paired exclusions are explicit and determined by data requirements, not observed profit.

The principal economic comparison uses preregistered decision opportunities, including valid no-trade decisions, rather than only jointly profitable or executed trades. Missing required evidence remains unknown or excluded with disclosed scope; it is not assigned cash PnL of zero.

Forecast baselines in `skill_metrics.py` remain distinct from economic baselines. A normalized midpoint benchmark may be used for proper-score diagnostics but never as an entry price.

## 5. Leakage, splits and search controls

### Chronological partitions

A split manifest fixes non-overlapping train, validation and untouched-test date ranges.

- Training fits permitted calibration.
- Validation chooses among registered configurations.
- Test evaluates the frozen selected policy once.
- Warm-up/history is explicitly assigned and cannot be mistaken for test performance.

Previously inspected REST15/H4 dates remain development data regardless of new labels, branches or random seeds. Currently, no independent test dates exist.

Prospective test dates must be reserved before inspecting their outcomes, scores or strategy-dependent diagnostics. Public knowledge or incidental exposure is recorded. Exposed dates cannot quietly remain “untouched.”

Events sharing a target market date remain in one partition across cities. Feature windows, open positions and label availability govern purge/embargo requirements; a nominal date boundary alone is insufficient.

### Walk-forward

Each fold specifies:

- Fit cutoff and training window.
- Validation/selection cutoff.
- Parameters selected using earlier available evidence.
- Evaluation dates.
- Retraining schedule.
- Eligible labels as of each cutoff.

Delayed labels and corrections enter only after availability. Historical signals cannot use subsequently revised final outcomes.

Development walk-forward is reported as development walk-forward. It cannot manufacture an untouched holdout from inspected history.

### Attempts and test access

Register every configuration before execution, including malformed requests where enough metadata exists. Retain:

- Successful, failed, blocked and cancelled attempts.
- Search family/configuration counts.
- Parameter changes, ablations and seeds.
- Selection provenance.
- Test-access intent and actual access.
- Retries and defect corrections.

Append a durable test-access event before opening test labels. A crash afterwards conservatively counts as exposure until evidence proves otherwise.

A retry using identical inputs is linked to the original attempt and is not independent evidence. A changed configuration is another attempt. After test access, fixes may be reported as corrected exposed-test reproduction; fresh confirmation requires new untouched dates.

### Multiplicity and uncertainty

Preregistration must enumerate primary hypotheses, comparisons and allowed search space. Hidden notebook trials and manually inspected alternatives belong in the registry.

Use family-wise multiplicity control for confirmatory claims; version 1 proposes Holm adjustment over the frozen primary comparison family. Development rankings and secondary diagnostics remain exploratory.

Uncertainty resamples market-date clusters, preserving all cities, events, strategies and paired controls within each sampled date. Members, tokens and trades are not independent sample units. Serial date dependence is assessed with a preregistered consecutive-date block sensitivity.

Adequacy is experiment-specific:

- Define a minimum worthwhile effect.
- Determine date/trade requirements from development-only variability and the desired precision or power.
- Freeze those requirements before test access.
- Refuse confirmatory interpretation when they are unmet.

The inherited minimum for an exploratory bootstrap is not a universal sufficient sample size. One day or one cohort cannot establish reliable profitability.

## 6. CLI, manifests and recoverable artifacts

### Proposed interface

The following commands are proposed, not existing commands or executions:

```text
python -m src.hypothesis_lab validate --hypothesis H --dataset D
python -m src.hypothesis_lab preregister --hypothesis H --splits S --registry R
python -m src.hypothesis_lab run --registration P --dataset D --phase development --output O
python -m src.hypothesis_lab run --registration P --dataset D --phase confirmatory --output O
python -m src.hypothesis_lab resume --run RUN_ID --registry R
python -m src.hypothesis_lab report --run RUN_ID --format markdown
python -m src.hypothesis_lab status --run RUN_ID
python -m src.hypothesis_lab stop --run RUN_ID
python -m src.hypothesis_lab cleanup --run RUN_ID --dry-run
```

`validate` checks schemas and hypothesis suitability without evaluating outcomes. Preregistration stores the exact resolved documents. `run` accepts only immutable registrations and pinned inputs. No command accepts order credentials or mutates collectors.

Proposed exit codes:

- `0`: completed experiment, including a negative scientific result.
- `2`: completed readiness/evaluation refusal or insufficient data.
- `3`: integrity failure.
- `4`: resource-limit interruption.
- `64`: invalid CLI/schema request.
- `130`: cancelled.

Machine-readable operational status and scientific status remain separate.

### Hash-bound manifest

`run-manifest.v1` includes:

- Hypothesis, registration, schema and protocol hashes.
- Source full commit where available, source-tree/file hashes and engine version.
- Common source snapshot digest.
- Interpreter/platform, dependency lock and resolved dependency versions.
- Dataset inventory, catalog snapshot, segment hashes and normalization lineage.
- Dataset as-of cutoff and clock-semantics version.
- Exact binding/fee/outcome-evidence policy.
- Resolved parameters, baselines, search family and configuration ID.
- Seed and random algorithm.
- Split and exposure-registry hashes.
- Precision, rounding, sorting and timezone-data version.
- Proposed resource envelope.
- Parent attempt/resume references.

The run ID binds this deterministic content. Actual start/end timestamps, attempt UUIDs and machine receipts are separate operational metadata.

Output schemas include:

| Artifact | Required content |
|---|---|
| `selection.frozen.json` | Decisions, input traces, token choices, first-attempt candidates and hash |
| `executions.jsonl` | Conditional fills, refusals, fees, scenarios, minimum flags and capital |
| `outcomes.jsonl` | Bound evidence levels, revisions and unresolved positions |
| `date_metrics.jsonl` | Date clusters, paired economics and denominators |
| `result.json` | Scientific status, estimand, uncertainty, baselines, skips and limits |
| `report.md` | Readable complete result |
| `resource-receipt.json` | Actual enforcement, measurements, exit and stop reason |
| `artifact-manifest.json` | Artifact schemas, counts, byte sizes and hashes |

### Append-only registry

Use an append-only JSONL attempt journal with:

`sequence`, `event_type`, `attempt_id`, `run_id`, `registration_hash`, `timestamp`, `payload_hash`, `previous_event_hash`, `event_hash`.

Events cover registration, start, input validation, selection freeze, test access, evaluation, completion, failure, cancellation, resume and cleanup.

Writers use a single registry lock, append and flush before proceeding. Incomplete trailing writes are retained and documented during recovery; committed events cannot be edited. Periodic immutable copies or externally retained roots make truncation detectable. A local hash chain alone does not prove that history was never deleted.

Refuse execution when the registry is unavailable or inconsistent.

### Determinism and recovery

Given identical bound inputs, code, dependencies, parameters, seed and split state, economic outputs and refusal classifications must match.

Use stable ordering, pinned decimal arithmetic and deterministic bootstrap generation. Do not derive results from wall-clock time or filesystem enumeration order.

Checkpoint only completed chronological units, including portfolio state, source cursor, selection digest and journal sequence. Atomic artifact replacement occurs only inside the owned research directory.

Resume requires identical bound inputs and hashes. It continues the same trial without selecting new parameters or reseeding. Changed inputs create another run. Existing immutable artifacts are never overwritten.

### Illustrative run and result

The following is a fictional interface example; it was not executed:

```text
python -m src.hypothesis_lab run \
  --registration registrations/revision-v1.json \
  --dataset manifests/rest15-development.json \
  --phase development \
  --output research/example-run
```

An illustrative result for an incompatible path hypothesis is:

```json
{
  "schema_version": "result.v1",
  "operational_status": "refused",
  "scientific_status": "insufficient_data",
  "evidence_strength": "development_only",
  "hypothesis_id": "price_reaction_continuation.v1",
  "independent_test_dates": 0,
  "reason_codes": [
    "required_price_path_unavailable",
    "legacy_receipts_are_not_minute_observations"
  ],
  "economic_metrics": null,
  "holdout_accessed": false,
  "illustrative": true
}
```

A refusal is a complete useful artifact. It must not appear as zero trades proving no edge.

## 7. Bounded Hetzner research runner

This section proposes future runner behavior. No server run or resource measurement occurred in this specification session.

### Isolation and initial envelope

The runner receives an immutable source bundle, dependency environment and research-only data/catalog snapshot. Inputs are read-only; outputs have one uniquely owned directory. It does not glob mutable spool files or read uncommitted segments.

Initial smoke limits:

| Resource | Proposed bound |
|---|---:|
| Research payload processes | 1 |
| CPU | 1 CPU; library threads fixed to 1 |
| Memory | 2 GiB hard limit |
| Wall time | 10 minutes |
| Owned output | 1 GiB, including temporary files and journals |
| Host free space | At least 20 GB decimal |

The smoke uses a frozen small fixture/subset selected for mechanics before outcomes. It is not a full performance test.

A proposed research cgroup or equivalent enforced sandbox applies CPU, memory and task bounds; thread environment settings supplement enforcement. A dedicated research supervisor monitors elapsed time, output quota and free space without changing production resources. If enforcement is unavailable, refuse the smoke rather than report unenforced limits as guarantees.

Preflight also verifies archive accessibility, source/dependency hashes and absence of trading/collector capabilities. Existing hardcoded paths in historical helpers are not reusable deployment assumptions.

No collector quota, service, timer, scheduler, production checkout or credentials are changed. Missing historical storage is a prerequisite failure; deleted storage is not restored.

### Lifecycle

`status` reports registration/run digest, owned process identity including birth/start identity, state, progress, resource consumption and current reason codes.

`stop`:

1. Targets only the verified owned run.
2. Requests graceful interruption.
3. Flushes an incomplete-run receipt and journal event.
4. Escalates only within that run’s isolated process group after a bounded grace period.
5. Never targets processes by a broad name match.

Time, memory, output or disk-floor failure stops the run. Limits are not silently expanded. A revised envelope needs a separately approved research decision.

`cleanup`:

- Defaults to dry-run.
- Requires a terminal run and no active owned writer.
- Resolves and verifies paths within the explicit research output root.
- Retains the registration, journal, manifests, reports and resource receipt.
- Removes only disposable files listed as owned by that run.
- Never removes archives, shared environments or production state.

A local cleanup request is not deletion authority for historical evidence.

### Measured receipt

Future smoke evidence records actual enforcement configuration, peak memory, CPU time, elapsed time, output bytes, disk checks, exit status, stop reason and artifact hashes.

Requested bounds and measured consumption occupy different fields. A passing smoke proves bounded mechanics on its stated input, not archive completeness, holdout validity or economic advantage.

## 8. Evaluation and report contract

### Scientific outcomes

Every result identifies its evidence strength independently of its scientific status.

The preregistered primary estimand is net economic advantage per defined comparable decision opportunity, with paired baseline arithmetic and fixed weighting. It must not quietly switch to per-winning-trade ROI.

Let \(\delta\) be the registered minimum worthwhile advantage.

- **Positive signal:** Adequacy requirements are met; the multiplicity-adjusted lower uncertainty bound exceeds \(\delta\); strategy net economics also satisfy the registered positive-net criterion. Required fee/stress scenarios and payout evidence are complete.
- **Negative result:** Adequacy requirements are met, and the upper bound is at or below \(\delta\), or a preregistered nonpositive-net criterion is met. State the specific rejected claim.
- **Insufficient data:** Required inputs/evidence are unavailable, sample/precision is inadequate, unresolved payout bounds prevent classification, or uncertainty cannot distinguish the registered alternatives.

Failure to reach significance is not automatically proof of no effect. A completed but inconclusive experiment can therefore return insufficient data for the decision while retaining valid descriptive economics.

Positive development evidence remains exploratory. Confirmatory strength requires the untouched-test protocol. Current historical evidence cannot receive that strength.

### Required report

`report.md` contains:

1. Hypothesis, version, scope, registration and run digests.
2. Scientific status and evidence strength.
3. Intended and usable populations, chronology and exposure history.
4. Execution assumption, conditional-fill and minimum-size limitations.
5. All arms, baselines, fee modes and fixed stresses.
6. Economic accounting and risk.
7. Paired uncertainty and multiplicity.
8. Data quality, refusals, exclusions and unresolved outcomes.
9. Reproducibility and resource evidence.
10. Supported conclusion and remaining limitations.

Required metrics include:

- Gross/net PnL and fee/cost reconciliation.
- Gross notional, actual modeled cash outlay and reserved capital.
- Net PnL / gross notional.
- Net PnL / cash outlay.
- Net PnL / initial allocated capital.
- Peak commitment, exposure and capital-time usage.
- Event/date/trade/opportunity counts and pending positions.
- Paired baseline counts, differences and exclusions.
- Date-cluster uncertainty and registered adequacy.
- Spread, stress support and minimum-order flags.
- Planned/recorded/validated/usable coverage and gap lengths.

Zero denominators produce null with a reason.

Drawdown must state the equity convention. Own-bid marked drawdown is conditional and unavailable where bids are missing. Cash-plus-cost-valued positions is not market equity. Gamma-mark equity is separate from realized cash; unresolved positions retain bounds.

Report all negative, blocked and unsuccessful arms. Do not select a favorable fee scenario, payout subset, date window or stress case for the headline. Proper-score diagnostics use the full eligible forecast census, not only traded events.

Reports contain no profit promises, private raw records, secrets, operator account details or host addresses.

## 9. Reuse, module structure and staged implementation

### Exact reuse map

| Existing source | Reuse or preserved boundary |
|---|---|
| `artifacts/replay_2026-10-08/core.py` | Immutable evidence, first-request discipline, strict execution and coupled payout bounds |
| `artifacts/replay_2026-10-08/adapter.py` | Read-only SQLite views and original closed-window semantics |
| `artifacts/replay_2026-10-08/signals.py` | Family mixture, revision/persistence, TAF regimes, censored memory and capability checks |
| `artifacts/replay_2026-10-08/small_order.py` | Pure minute-mode conditional $1 accounting and stresses |
| `artifacts/replay_2026-10-08/compact_matrix.py` | Full interval/YES/NO expected-matrix diagnostics |
| `artifacts/replay_2026-10-08/skill_metrics.py` | Full-census proper scores and paired model comparisons |
| `artifacts/rest15_2026-10-08/small_order_rest_v3.py` | Separate sequential-sweep entry/accounting semantics |
| `artifacts/rest15_2026-10-08/replay_rest15.py` | Retained sweep selection, native inventory and selection-before-payout pattern |
| `artifacts/rest15_2026-10-08/build_index.py`, `target_metadata.py` | Inventory/provenance patterns; not authorization for new extraction |
| `artifacts/replay_2026-10-08/extract.py`, `resume_extract.py` | Normalization lineage, partial flags and bounded-extraction lessons |
| `artifacts/replay_2026-10-08/available_coverage.py` | Readiness distinction; not population-wide completeness |
| `src/compact_replay.py` | Compact as-of, gap/epoch, terms and own-side acceptance behavior |
| `src/server_replay.py` | Committed catalog integrity and receipt/import-aware replay patterns |

Historical `run.py`, `freeze.py`, `server_ops.py` and operation helpers are reference material. Their side effects, fixed locations and historical resource envelopes must not become the new CLI merely through imports.

The snapshot shows identical copies of several core modules. Introduce one pinned reusable implementation for future work without rewriting historical artifacts.

### Smallest practical proposed structure

```text
src/hypothesis_lab/
  __init__.py
  __main__.py       CLI dispatch
  contracts.py     schemas, clocks, binding and refusal types
  adapters.py      mode-specific immutable evidence views
  replay.py        frozen selection and existing engine integration
  evaluation.py    paired metrics, splits, uncertainty and classification
  artifacts.py     manifests, journal, checkpoints and reports

scripts/research_lab_runner.py
```

Keep the runner separate from the scientific core. Avoid a plugin framework, service, database server or generic workflow engine in version 1.

Existing pure functions should be reused through explicit interfaces. Historical unqualified imports such as `core`, `run` and `small_order` require controlled packaging; ambient `sys.path` must not select the wrong duplicate module.

### Prerequisite risks

The supplied snapshot is not the complete application/dependency environment:

- `src/compact_replay.py` references `src.server_store`.
- `src/server_replay.py` references `src.continuous_weather` and PyArrow.
- Existing scripts reference sibling evidence, inventories and outcome audits.
- Historical helpers contain fixed paths and remote-operation behavior.
- Dataset availability and a matching dependency lock are not established by copied source alone.

Implementation must obtain separately approved immutable prerequisites or refuse the affected mode. It must not inspect mutable shared roots, install into production or substitute unverified data to overcome these gaps.

### Compatibility strategy

Leave frozen protocols and historical artifacts unchanged. Introduce explicit modes:

- `legacy_strict_depth_v1`
- `rest15_small_order_v3`
- `compact_small_order_v2`

A common report schema may wrap them, but entry windows, source-age rules, partial-fill assumptions and fee conventions stay mode-specific.

Before extraction into reusable modules, compare old and new behavior on existing synthetic fixtures and available exact H4 inputs:

- Signal eligibility, probabilities and selected token.
- Trace identities and clocks.
- First entry candidate and refusal reasons.
- Quantities, fees, stresses and minimum flags.
- Capital ordering and payout bounds.

Economic values must match under the same pinned arithmetic. Semantic comparisons exclude operational timestamps. Any intended difference requires a versioned contract change and explicit acceptance; tests are not weakened to conceal drift.

### Staged implementation

1. **Contract checkpoint:** Resolve operator decisions below; freeze schemas and evidence-mode boundaries.
2. **Packaging/equivalence:** Isolate pure existing engines and reproduce historical fixture semantics.
3. **Adapters/readiness:** Implement hypothesis-specific suitability without outcome evaluation or new collection.
4. **Registry/CLI:** Add preregistration, append-only attempts, manifests and recovery.
5. **Evaluation/report:** Add paired baselines, chronology, uncertainty and three-way classification.
6. **Bounded smoke:** Execute only after separate authorization, on immutable research fixtures with measured limits.
7. **Prospective exploratory evaluation:** Use newly suitable data and report every attempted arm.
8. **Confirmation:** Reserve fresh untouched dates, freeze selection, perform one registered evaluation and obtain independent review.

Later publication follows the repository foundation gates and review-until-clean requirement. Those checks are future implementation obligations, not claims of execution in this session.

## 10. Meaningful acceptance tests

Use existing fixtures before adding focused counterexamples. Tests must assert economic outputs and refusal reasons, not only successful exits.

| Area | Observable acceptance |
|---|---|
| Future leakage | Appending future receipts/imports leaves earlier decisions and executions unchanged |
| Clock separation | Old issue time cannot admit late receipt/import; normalization time cannot rewrite original availability |
| Latest invalid input | Invalid latest forecast/metadata blocks rather than selecting an older valid record |
| Target persistence | Receipt-only changes and unrelated target-day changes do not create revisions; A→B→A restarts persistence |
| Own NO pricing | Asymmetric YES/NO fixtures use the recorded own NO ask/bid |
| Fees | Hand-calculated cash/share-fee examples reconcile; unknown schedules refuse; no favorable per-trade mixing |
| Terms | Changed tick, minimum, fee, rules or token rejects, including change-back |
| Gaps | Cached checkpoints, reconnects and uninitialized heartbeats cannot restore continuity |
| Cohorts | Missing NO/tail, duplicate cells, excessive skew and binding mismatches remain explicit defects |
| Transitions | Old-cohort cells cannot satisfy a new cohort; observed transition evidence remains distinct from synthetic tests |
| Payouts | Valid bound proxy supports conditional economics without weather certification; conflicting vectors retain bounds |
| Capital | Gamma marks do not unlock cash; simultaneous ordering and budget refusals are deterministic |
| First entry | Bad first candidate stays rejected despite a later cheaper valid quote |
| REST deadline | First sweep with an ending deadline failure is not replaced |
| Minimums | Below-minimum $1 fill remains hypothetical; separate compliant sensitivity changes stake and denominators |
| Stress | Upward tick rounding recomputes quantity/fees; ask ≥1 is unsupported |
| Splits | Inspected dates cannot enter untouched test; correlated date groups cannot cross partitions |
| Journal | Failed/retried attempts and pre-label test access survive crashes; committed history cannot be overwritten |
| Baselines | Hand-calculated paired opportunity PnL and ROI reconcile; unmatched favorable subsets cannot become primary results |
| Reproducibility | Reordering identical inputs and deterministic resume preserve outputs and reasons |
| Classification | Adequate positive, adequate negative, missing-data and imprecise fixtures produce the declared distinctions |
| Runner | Timeout/output/disk-floor stops retain incomplete receipts and do not affect production processes |
| Cleanup | Active runs and paths outside the owned research root refuse deletion |

Relevant existing tests include:

- `artifacts/replay_2026-10-08/test_core.py`
- `test_adapter.py`, `test_extract.py`, `test_signals.py`
- `test_small_order.py`, `test_compact_matrix.py`
- `test_skill_metrics.py`, `test_available_coverage.py`, `test_runner.py`
- `artifacts/rest15_2026-10-08/test_small_order_rest_v3.py`
- `artifacts/rest15_2026-10-08/test_replay_rest15.py`

Their current tests already exercise first-entry rejection, own NO pricing, forward corrections, persistence, matrix defects and paired forecast diagnostics. New tests must preserve those contracts.

## 11. Decisions requiring operator resolution

Before implementation, resolve:

1. **Initial scope:** Which existing mechanisms and new path hypothesis enter version 1?
2. **Claim level:** Conditional payout-proxy economics, independently weather-verified claims, or on-chain evidence requirements?
3. **Economic decision rule:** Worthwhile-effect threshold, primary baseline, required stress cases and precision/power targets.
4. **Future holdout:** Prospective dates, exposure custodian, test-access gate and walk-forward schedule.
5. **Capital:** Allocation, concentration limits and whether separately verified cash release is permitted.
6. **Order semantics:** Actual fee rounding/asset and minimum applicability; preserve scenarios where unresolved.
7. **Prerequisites:** Approved immutable datasets, dependency environment, path mappings and observed compact transition evidence.
8. **Runner:** Research isolation mechanism and separately authorized smoke execution.

These decisions do not prevent a complete specification. They prevent implementation from silently choosing economically consequential policy.

## 12. Tradeoffs, strongest risks and falsification

### Concrete tradeoffs

- **Compact BBO versus depth:** Lower storage and simpler non-scalping research, with explicitly conditional capacity and fills. Strict depth mode remains separate.
- **Conservative first entry versus recovered opportunities:** Rejecting a defective first attempt loses trades but prevents price shopping and preserves historical semantics.
- **Payout proxies versus stronger proof:** Reliable bound final vectors permit useful conditional analysis sooner; weather truth, redeemability and cash realization remain separate claims.
- **One shared evaluation layer versus mode-specific execution:** Shared accounting/reporting reduces duplication; separate selectors avoid changing REST and minute semantics.
- **Append-only search history versus convenience:** More bookkeeping, but failed attempts and exposed tests remain visible.

### Three strongest risks

1. **Suitability mistaken for completeness.** Partial legacy inputs or a short compact audit could support a favorable subset while missing other opportunities.  
   **Mitigation:** Independently bound expected cohorts, hypothesis-specific refusal rules, full denominator reporting and explicit limited-population claims.

2. **Selection leakage mistaken for confirmation.** Inspected dates, repeated arms and post-test fixes could produce an apparently independent result.  
   **Mitigation:** Immutable chronological splits, exposure events, complete attempt history, frozen multiplicity and fresh dates after contamination.

3. **Conditional arithmetic mistaken for executable profit.** Fees, minimums, size, payout-access or capital recycling could erase an apparent advantage.  
   **Mitigation:** Own-side quotes, uniform fee scenarios, fixed stresses, minimum flags, conservative capital and separated payout evidence.

### How the design can be falsified

The framework fails its contract if an adversarial fixture can:

- Change an earlier decision by appending future data.
- Admit an invented NO price, cached fresh quote or cross-cohort state.
- Replace an invalid first entry with a favorable later one.
- Produce irreconcilable baseline, fee or capital arithmetic.
- Lose a failed attempt or hide prior test exposure.
- Produce different economic outputs after a hash-identical resume.

The hypothesis claims are falsified or materially weakened if preregistered adequate prospective evaluation places their net advantage below the worthwhile threshold, if fixed costs/stresses remove the advantage, or if required execution/payout evidence remains unsupported. A negative result satisfies this framework’s purpose; a positive headline without these safeguards does not.