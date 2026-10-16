# WEA1062 — Hypothesis-testing framework specification

**Candidate:** Codex-19@codex  
**Specification version:** 1.0  
**Status:** Specification only; implementation and execution require a subsequent authorization.

## 1. Outcome, authority and evidence boundary

The framework shall turn a preregistered weather-market hypothesis into a reproducible research result that states:

- Which population, inputs and execution assumptions were evaluated.
- Whether the evidence supports a positive signal, a negative result or insufficient data.
- Which conclusions are exploratory or confirmatory.
- How costs, missing observations, unresolved payouts and configuration searches affect the conclusion.

The first release shall support conditional **$1 gross-notional full-fill simulations** and preserve the existing REST15 and strict-depth protocols as separate, versioned engines. It shall not convert historical development results into independent validation.

### Non-goals

This work does not authorize implementation, backtests, server access, trading, wallets, collector changes, deployment, scheduler changes, credentials, data acquisition, archive restoration or external publication. A separate website is unnecessary.

The framework shall not reconstruct missing NO prices, depth, forecast vintages, source receipts or settlement truth. It shall not infer profitability from successful software checks or assumed full execution.

### Specification-stage authority

The approved stage is Spec/Ranked: four equal 5 WEA places, total 20 WEA, with seven-day intake and a one-day author-decision window under the canonical activation clock. The remaining implementation/review budget is unallocated. Protected unrelated escrow remains outside scope.

Funding, native-session launch, artifact eligibility, acceptance and payment are distinct. This response is a specification deliverable; local capture alone does not establish canonical Work or payment. Canonical delivery requires the complete public-safe UTF-8 Markdown artifact, at most 1 MiB, under `artifacts/task-1062/specifications/`, referenced by its exact WEA repository path and immutable full commit.

Separate registered identities and independent model sessions do not establish separate ownership. Common-control disclosure belongs in canonical Work provenance.

### Evidence used

Architecture references below refer exclusively to the supplied `source-prerequisite/` snapshot. Paths following that prefix are domain-relative source paths.

The assigned `snapshot-manifest.json` declares common SHA256:

`58aab056090a57380a7bbacfce2edaa4783b69984735006de0e0b416373b1c24`

All 66 manifest-listed files passed a local content-hash comparison. This verifies supplied-file integrity, not archive completeness, runtime correctness or profitability.

The requirements and current limitations come from:

- `spec-stage-proposal.md`
- `approved-plan.json` and `approved-plan.md`
- `candidate-brief.md`
- `data_contract.md`
- `compact_contract_v2.md`
- `source-prerequisite-manifest.json`
- The supplied protocols, adapters, execution engines and tests.

The supplied evidence establishes these starting constraints:

| Evidence | Permitted interpretation |
|---|---|
| Previously inspected REST15/H4 dates | Development-only; `independent_test_dates=0` |
| Preserved legacy projection plus 640 exact H4 inputs | A bounded retained dataset, not complete historical order books |
| Legacy REST receipts and checkpoints | Historical observations at their actual clocks, not fresh minute quotes |
| Fifteen known pre-r7 split minutes | Excluded with retained audit reasons |
| Forty checked post-r7 minutes in one cohort | Evidence for that window; no demonstrated live cohort transition |
| Forty-one Gamma final payout vectors | Potential conditional payout evidence after binding checks; not on-chain payout or redemption proof |

Counts in this table are supplied evidence facts, not results of a backtest performed during this specification session.

## 2. Hypothesis contract

### 2.1 Versioned schema

Every evaluated hypothesis shall have an immutable JSON document. Unknown fields, missing required fields and unsupported major schema versions shall fail validation.

| Field | Required content |
|---|---|
| `schema_version` | Hypothesis schema version |
| `hypothesis_id`, `revision`, `family_id` | Stable identity, immutable revision and search family |
| `claim` | Falsifiable economic or predictive claim |
| `rationale` | Proposed mechanism without asserting it is true |
| `evidence_strength_requested` | `development`, `exploratory` or `confirmatory` |
| `adapter` | Adapter name/version and dataset manifest hash |
| `population` | Market types, station mapping, local target dates, horizons, discovery rules and exclusions |
| `required_capabilities` | Required payloads, clocks, bindings, histories and outcome evidence |
| `decision_policy` | Signal schedule, input cutoffs, features, side/token selection and deterministic ties |
| `parameters` | Every numerical and categorical parameter with units |
| `search_policy` | Fixed configuration or finite enumerated grid, configuration limit and selection rule |
| `entry_policy` | Engine/version, latency, deadline, frozen candidate selection and refusal rules |
| `exit_policy` | Hold-to-payout or fixed bid-exit rule, including missing-exit treatment |
| `economics` | Gross notional, fee models, costs, stresses and minimum-order interpretation |
| `risk_policy` | Initial capital, exposure limits, attempt budget and cash-release policy |
| `baselines` | Policy definitions, matching keys and paired-exclusion rules |
| `splits` | Immutable split-manifest hash and walk-forward fitting rules |
| `evaluation` | Primary estimand, useful-effect threshold, uncertainty procedure, multiplicity and classification rule |
| `seed` | Explicit random seed and RNG algorithm |
| `registration` | Registration timestamp, document hash and parent revision |
| `provenance` | Source protocol references and development/test-access history |

Decimals shall use canonical strings. Times shall use timezone-aware UTC timestamps with documented precision. Local schedules shall separately name the IANA timezone and local target-day convention.

A hypothesis revision includes its population, costs, exclusions and baseline—not merely signal thresholds.

### 2.2 Preregistration and evaluation

Registration shall precede evaluation-outcome access. Registration after inspecting relevant outcomes remains exploratory.

For fixed configurations, no parameter fitting occurs. For searches:

1. Enumerate the permitted grid and total budget before evaluation.
2. Use training data for fitting and validation data for the declared selection rule.
3. Record every configuration, failure and exclusion.
4. Freeze the selected configuration before opening the untouched test.
5. Treat subsequent changes as new revisions requiring fresh confirmatory evidence.

The first implementation should register one fixed configuration per example family. Search support is necessary for accountability but need not enable a broad optimizer.

The primary economic estimand shall be **mean paired incremental net PnL per eligible opportunity**, aggregated and resampled by market date. Non-entry policy decisions contribute zero; data-unknown cases remain separately classified. Secondary estimands include total net PnL, capital return and predictive skill.

Economic evaluation and predictive evaluation shall remain separate. A better probability score does not establish profitable execution.

### 2.3 Example A — Ensemble-NO valley hypothesis

**ID:** `ensemble_no_valley/v1`  
**Family:** `ensemble_no`

This is an explicit registration of the existing two-regime mechanism, not a claim of a newly discovered edge.

- Signal: first retained station-local T−1 evening cohort within `[18:00,19:00)`.
- Weather and metadata cutoff: signal time minus five seconds.
- Require at least four distinct fresh model families.
- Require two groups of at least two families, separated by at least 2°C.
- Require the latest available TAF to cover the local 12:00–18:00 peak window and contain the documented cloudy/clear regimes.
- Preserve the fixed 1.5°C convolution kernel and equal family weights, then equal member weights within each family.
- Select the native interval containing the mixture mean before inspecting candidate entry prices.
- Buy its own NO token only when the moment-matched unimodal interval probability exceeds the mixture probability by at least 0.05 and the existing signal-price edge gate passes.
- Preserve native interval and continuous rounding-cell representations separately.
- Hold to payout under the selected conditional execution contract.

**Baselines:** cash, same-token unimodal control and a separately reported simple five-family policy.

**Evaluation:** paired net PnL improvement and full-census probability scores. Neither TAF change flags nor ensemble clusters shall be converted into certified causal regime probabilities.

**Refusal:** incomplete families, uncertified latest TAF history, unsupported intervals or unavailable own NO quotes.

References: `artifacts/replay_2026-10-08/signals.py`, `run.py`, `protocol.json`.

### 2.4 Example B — Price-path continuation hypothesis

**ID:** `price_reaction_continuation/v1`  
**Family:** `price_path`

This is a proposed extension requiring compact continuity evidence.

- Decision clock: fixed station-local T−1 18:00.
- Observe the chosen token’s own bid/ask at the decision clock and 60 minutes earlier, using only available validated state.
- Compute midpoint movement only as a descriptive feature.
- Require uninterrupted coverage across that lookback.
- Select the token with the largest positive midpoint change of at least 0.03; break ties by stable market ID and side.
- Freeze selection before the entry cohort.
- Enter at its own ask using compact entry rules.
- Schedule an exit six hours after entry, at the first subsequent observed cohort within five minutes of that deadline.
- Freeze the exit candidate before validation and sell only at that token’s own bid.

If the frozen exit cannot be validated, the result is `exit_unobservable`. The position remains unresolved in the primary analysis with payoff bounds; it is not silently converted to hold-to-payout.

**Baselines:** cash and the same token, same entry and exit clocks, without the momentum gate. Report the common paired population and the broader ungated population separately.

**Evaluation:** incremental net PnL after both entry and exit fees. Quote movement itself is not the economic outcome.

**Refusal:** legacy checkpoint input, discontinuous lookback, absent own bid, unknown sell-fee semantics or missing exit observations.

The threshold, lookback and holding period are proposed fixed development parameters. Any tuning consumes the price-path family search budget.

### 2.5 Example C — Forecast-revision structure hypothesis

**ID:** `forecast_revision_structure/v1`  
**Family:** `forecast_revision`

Preserve the existing noon/evening comparison:

- Require all five model families at both fixed T−1 clocks.
- Compare the actual target-day member arrays, not whole rolling-response hashes.
- Single revision: exactly one family changes by at least 1°C; all others change by at most 0.3°C.
- Common revision: at least three families change in the same direction by at least 0.5°C.
- Require the changed target-array state to have persisted for one observed hour.
- An A→B→A sequence restarts A’s persistence clock.
- Do not infer initialization time from expected releases or identical arrays.
- Preserve both single/common arms and the existing probability-gap selection across own YES/NO asks.
- Preserve the existing 0.05 signal edge gate. Do not add a profitable entry-time EV recheck to REST15.

**Baselines:** cash and the final-model five-family control without the revision gate.

**Evaluation:** both preregistered arms, paired net PnL and full-census predictive diagnostics. Selecting the better arm after outcomes is exploratory selection.

**Refusal:** missing target history, unverifiable latest vintage, bridged gaps or incomplete noon/evening comparison.

References: `signals.py`, `run.py`, `artifacts/rest15_2026-10-08/replay_rest15.py`.

### 2.6 Existing H4 and H1 compatibility

H4 migration shall preserve its existing GEFS calibration, censored residual innovations, shrinkage, EMA parameters and front-reset rules. Exact prior labels must have been available before the current decision. The 640 exact inputs are regression evidence, not an untouched holdout.

H1 remains blocked for economic evaluation until T0 quotes, remaining-hour member paths and contractual-source running-maximum evidence exist. METAR maxima shall not replace contractual maxima.

## 3. Data and adapter contracts

### 3.1 Common normalized records

Adapters shall expose immutable records with:

- `record_id`, record kind, schema version and content hash.
- Dataset segment hash and source-record lineage.
- Event, market, condition, token, side and binding-version identifiers.
- Station/source mapping, native unit, timezone and local target day.
- Event/observation time, model issue time, publication time if known, original first receipt, later receipts and import time.
- Explicit validity, unavailable-state and gap reasons.

Associated records shall include:

- `MarketBinding`: literal rules hash, native endpoints, inclusivity, unbounded flags, token mapping and activity state.
- `QuoteObservation`: own bid/ask, optional native sizes, source timestamp semantics, original receipt, state validation, epoch and cohort.
- `ForecastVintage`: family/member IDs, target array, target hash, issue/valid times and receipt history.
- `CoverageEvidence`: expected cells/cohorts, discovery intervals, outages and audited exclusions.
- `ExecutionTerms`: tick, minimum, fee state/formula/asset, protocol and availability.
- `PayoutEvidence`: bound vector, status, receipt, revisions and separate weather/on-chain/access evidence.

The adapter shall publish a capability manifest. A missing capability is not represented by a fabricated empty payload.

### 3.2 Clock semantics

| Clock | Meaning |
|---|---|
| Event/valid time | When weather occurred or what period a forecast describes |
| Model issue time | Identified model vintage; may be unknown |
| Publication time | Documented source release time; may be unknown |
| Original first receipt | Earliest proven acquisition of that exact source version |
| Later receipt | A subsequent acquisition, potentially unchanged |
| Import time | Availability in the research or replay store |
| State-validation time | Proven current quote-state observation or healthy subscription validation |
| Decision/entry time | Logical policy and conditional execution clocks |

Default simulated availability is:

`available_at = max(original_first_receipt, applicable_receipt, imported_at)`

Publication or issue time may constrain validity but shall not substitute for receipt.

A historical receipt-replay adapter may distinguish mechanical later copying from genuine delayed acquisition. It may use original acquisition time only with hash-bound provenance proving the record was available to the historical system. Otherwise import time governs, or historical availability is unknown.

That exception must be explicit in the manifest. It shall not allow a seed, checkpoint or receipt claim to refresh quote age.

For compact records, a late-imported record cannot retroactively affect a decision. Processing shall be ordered by effective availability with deterministic sequence ties. Merely filtering import times while sorting exclusively by receipt is insufficient when arrival order differs.

Corrections apply prospectively from availability. Later outcome revisions belong to evaluation evidence and cannot rewrite earlier signal inputs.

### 3.3 Legacy projection adapter

`legacy_projection/v1` shall:

- Read retained projection fields and exact H4 inputs without modifying them.
- Record the projection’s source lineage and omitted field classes.
- Expose only preserved historical observations.
- Distinguish exact inputs from derived summaries.
- State unknown archive-wide and between-poll completeness.

It may support exact-input H4 regression and bounded descriptive analyses where required inputs survive.

It shall refuse minute price-path claims, reconstructed NO quotes, historical depth claims and revision persistence requiring missing change history. Missing records shall not establish that no opportunity existed.

### 3.4 REST15 adapter

`rest15_retained/v3` shall preserve the supplied protocol:

- Chronological sequential REST sweeps, split at receipt gaps of at least 60 seconds.
- Maximum sweep duration 120 seconds.
- Signal at the last actual receipt of the first retained evening sweep.
- Weather and metadata available by signal minus five seconds.
- Complete official interval and YES/NO identity inventory for admitted sweeps.
- First subsequent retained sweep starting at least 60 seconds after signal.
- Freeze that sweep before checking content; reject if its end exceeds signal plus 1,200 seconds.
- Chosen quote age at sweep end at most 120 seconds.
- Retain quote receipt and logical sweep-end entry separately.
- Preserve unknown between-poll continuity.
- Reject intervening binding changes, including changes later reverted.

“First retained sweep” shall not be relabeled “global first sweep” without complete-window certification.

Missing latest catalogued metadata blocks admission; older metadata is not a fallback. Native quote context must bind to verified metadata and archived terms.

References: `replay_rest15.py`, `small_order_rest_v3.py`, `target_metadata.py`, `build_index.py`, `protocol_rest15_v3.json`.

### 3.5 Strict historical replay adapter

The original strict-depth protocol remains separate:

- Original first-next-request latency and window.
- Native price-level depth and participation restrictions.
- Original size, cash, fee and edge gates.
- Partial-fill and capital conservation semantics.

A closed partial extraction shall not pass the original complete-input economics gate. A separately named retained-subset REST15 diagnostic does not weaken that gate.

References: `artifacts/replay_2026-10-08/core.py`, `adapter.py`, `extract.py`, `run.py`.

### 3.6 New compact adapter

`compact_observed/v2` shall validate the expected matrix:

`event × every native interval × YES/NO × minute`

Both tails are included. Counts shall distinguish planned, recorded, validated, tradable, observed-empty and unknown cells.

Binding validity requires exact native endpoints, inclusivity, units, tokens, condition, rules, station and target day. Temperature ordering shall use parsed bounds, not bracket indices.

An observed empty side is known unavailable state. A missing cell or uncertain source state is a gap. Discovery evidence distinguishes not-yet-created events from outages.

Heartbeats may validate unchanged quotes only through a successful current observation or initialized continuously healthy subscription. They preserve original quote/change timestamps. Gaps, reconnects and session changes invalidate carried state until reinitialized.

Compact entry requires:

- First observed event cohort at signal +60 through +300 seconds.
- Candidate cohort frozen before token/content validation.
- State-validation age at most 120 seconds.
- Cohort skew at most five seconds.
- No intervening gap, reconnect or incompatible epoch.
- Active, unchanged binding and terms.
- Finite tick-aligned `0 < bid ≤ ask < 1`.

The orchestrator must select from the complete event-cohort stream before filtering to the chosen token. Otherwise a cohort missing that token could disappear and permit a later favorable entry.

`compact_matrix.py` provides useful matrix checks but does not itself certify external inventory completeness, execution freshness or continuity. `src/compact_replay.py` provides acceptance primitives, not a complete hypothesis runner.

### 3.7 Suitability and refusal classification

Suitability is assessed per hypothesis and decision dependency interval. There is no universal coverage-percentage gate.

| Requirement | Consequence when absent |
|---|---|
| Own NO quote | Refuse NO economics; never complement YES |
| Price-path continuity | Refuse price-path evaluation |
| Forecast target history | Refuse revision/persistence claim |
| Latest TAF/METAR history | Block dependent H2/H4 arm |
| Contractual running maximum/hourly paths | Block H1 |
| Reliable bound payout | Unknown payoff bounds; no fabricated realized PnL |
| Official weather certification | Blocks weather-truth claims, not all conditional payout economics |
| On-chain/access proof | Blocks cash-release/redemption claims |
| Sizes/order applicability | Retain authorized conditional $1 calculation with feasibility limitations |

Each case records one deterministic primary reason and all secondary reasons:

- `policy_no_signal`: policy condition failed on sufficient data.
- `known_unavailable`: observed empty/inactive state.
- `data_unknown`: missing history, gap or uncertified availability.
- `unsupported_contract`: absent fee semantics, binding ambiguity or unavailable adapter capability.
- `resource_or_runtime_failure`: incomplete execution, not an economic verdict.

Known exclusions, including the 15 pre-r7 minutes, are hash-bound. The 40-minute single-cohort audit does not establish transition correctness. New cohort transitions require explicit tests and subsequent observed evidence.

## 4. Conditional economic model

### 4.1 Entry accounting

For the selected token’s own ask \(a\):

\[
N=1,\qquad q=N/a
\]

Here \(N\) is gross USD notional before fees.

For a supported archived fee formula:

\[
F=\operatorname{round}_{terms}\left(q\,r[a(1-a)]^e\right)
\]

The formula, rate, exponent, rounding, fee asset and protocol binding must be identified. Unknown or conflicting fees refuse net economics. Zero fees require explicit evidence.

Preserve complete uniform portfolios:

| Scenario | Entry cash | Held payout shares |
|---|---:|---:|
| USD fee | \(1+F\) | \(q\) |
| CTF-share fee | \(1\) | \(q-F/a\) |

Reject nonpositive net shares. Do not mix whichever fee mode is better for each position.

The supplied pure engine’s upward `0.00001` fee rounding shall remain its named versioned assumption. `src/compact_replay.py` currently reports unrounded fees; its values cannot be claimed equivalent to the rounded engine without an explicit bridge.

### 4.2 Payouts and exits

For payout per share \(y\), held shares \(s\), cash outlay \(C\) and additional costs \(K\):

\[
\text{net PnL}=ys-C-K
\]

Gross PnL uses pre-fee quantity and gross notional. Report fee effects explicitly; subtracting a cash-equivalent fee twice is prohibited.

For an early exit, sell only at the selected token’s own bid \(b\). Compute gross proceeds from held quantity and apply the archived sell-fee contract. Unknown sell-fee semantics block exit economics.

The first eligible exit observation is frozen before validation. Missing exits remain unresolved with bounds. There is no favorable later exit search or outcome-dependent conversion to another strategy.

Payout evidence shall expose three independent axes:

1. Bound payout-vector reliability.
2. Contractual-weather verification.
3. On-chain finality and payout-access/redemption verification.

Reliable bound Gamma vectors may support explicitly conditional proxy PnL. They shall not establish actual redeemed cash or weather truth. The 41 supplied vectors are not chain proofs.

Unknown positions remain in full-population counts and bounds. For complementary holdings, compute feasible joint payout bounds using condition coupling. Stronger exclusive-event geometry requires attested rules; do not sum mutually impossible independent-leg extremes.

### 4.3 Executability limitations

Every simulated trade shall state:

- `full_fill_assumed=true`
- `observed_fill=false`
- Whether native size was recorded.
- Whether displayed size was sufficient at the relevant price.
- Archived minimum shares/notional and applicability.
- Share precision, rounding and price-impact limitations.

A below-minimum $1 hypothetical fill remains in the authorized conditional model with a feasibility flag. It is not silently excluded to improve returns and is not described as a valid order.

A minimum-compliant sensitivity is a separate policy with separately funded capital and recomputed quantities. It requires documented minimum applicability. It does not replace the $1 result.

Compact BBO—even with sizes—does not prove queue access, sustained capacity, slippage or actual execution.

### 4.4 Capital and risk

Initial proposed capital is $1,000 per arm and per fee scenario, preserving the REST15 convention. Every arm is an independent counterfactual ledger.

- Reserve full entry cash and declared cost reserves.
- One frozen attempt per event per arm, including rejected attempts.
- No leverage, shorting or cross-arm capital sharing.
- Apply capital constraints in actual entry chronology.
- Reject unfunded entries with a recorded reason.
- Do not release capital on Gamma marks.
- Release settlement cash only under the registered verified-access rule.

Report committed capital, peak concurrent exposure, cash remaining, holding duration, worst-case loss and payout uncertainty.

Mark-to-bid drawdown requires valid own bids. Missing marks remain missing or bounded. Separately report conditional payout-equity drawdown; it is not a liquid account-equity measure.

### 4.5 Baselines and stresses

Required baselines are cash and at least one simple mechanism-relevant control.

Paired comparisons shall match:

- Target dates and market identities.
- Adapter and coverage basis.
- Entry/exit convention.
- Notional, fees, capital and payout evidence.
- Relevant horizon and decision schedule.

Report the common evaluable intersection and exclusions on each side. A zero trade caused by sufficient-data policy gating is distinct from a missing-data case.

Fixed stresses shall include:

- Ask shifts of +0.01 and +0.02, rounded upward to native tick.
- Independent $1 spending with recomputed shares and fees in each scenario.
- Unsupported stressed asks at or above one, without capping.
- Separately labeled same-quantity extra-cost reserves.
- Spread and both fee-asset scenarios.
- Delayed-entry sensitivity with its own frozen-first-observation rule.
- Payout bounds and missing-exit sensitivity.
- Minimum-compliant sensitivity where documented.

For exit policies, include fixed adverse bid shifts and sell costs. Stress arms are preregistered outputs, not candidates from which to select the best headline.

## 5. Leakage, splits and search accountability

### 5.1 Immutable splits

A split manifest shall enumerate dates and event assignments with a content hash. Each target date belongs to one outer split across all its cities and intervals.

Previously inspected REST15/H4 dates remain development-only permanently. A new random split, renamed dataset or rerun does not create an untouched test.

A proposed prospective schedule is:

1. Complete warm-up required by the registered policy.
2. Thirty chronological training target dates.
3. Fourteen chronological validation dates.
4. A purge interval covering the maximum holding horizon and relevant label-availability delay.
5. Sixty future test dates fixed before test access.

These durations are proposed starting choices requiring approval and power assessment. They are not universal data-coverage gates.

Training positions whose labels would cross into validation/test are purged from fitting. Features and fitted state use only information available at each decision.

### 5.2 Walk-forward policy

Walk-forward folds shall record:

- Training cutoff, fitted-state hash and eligible labels.
- Validation/output dates.
- Retraining schedule and fitting algorithm.
- Purge/embargo intervals.
- Model-selection provenance.

Outer test evaluation shall replay a frozen policy. Scheduled online updates may consume earlier test-period labels only if their exact algorithm was preregistered and those labels were available at the simulated update time. Test aggregate performance shall never guide such updates.

Changing the procedure after viewing test results consumes that test for the revised claim.

### 5.3 Test-access journal

Test authorization must be recorded before opening protected partitions. Log successful, refused and failed access, including diagnostics that reveal outcomes or performance.

An implementation error discovered after test access permits a transparent corrected replay, not a newly untouched test. Retain both attempts, the defect, the correction hash and the strength downgrade.

Existing unprotected historical files cannot be made untouched through software controls. Their development-only status is an evidence fact.

### 5.4 Multiplicity and uncertainty

The attempt registry shall cover all configurations, arms, feature revisions, search grids and primary claims.

For confirmation:

- Freeze the family-level claim set and number \(M\) before test access.
- Use simultaneous date-cluster bootstrap intervals with preregistered Bonferroni allocation across primary claims.
- Fix RNG, replicate count and quantile convention.
- Record selected configurations and every abandoned family.
- Treat added claims as new exploratory hypotheses.

The bootstrap resamples whole market dates, carrying all correlated events, trades and baseline pairs together. Report a preregistered consecutive-date block sensitivity for serial dependence.

A proposed confirmatory configuration uses at least 30 evaluable date clusters and 10,000 bootstrap replicates. Each protocol must also preregister its useful-effect threshold and precision/power requirement using development information. Meeting the date floor alone does not establish adequate evidence.

Existing 2,000-replicate development diagnostics retain their original interpretation. Bootstrap precision cannot create missing independent observations.

## 6. CLI, manifests and attempt registry

### 6.1 Proposed CLI

The following interface is illustrative and has not been executed:

```text
python -m hypothesis_lab validate --hypothesis H.json --dataset D.json
python -m hypothesis_lab register --hypothesis H.json --registry REGISTRY
python -m hypothesis_lab run --registration HASH --split development --output RUN_DIR
python -m hypothesis_lab run --registration HASH --split test --authorization ACCESS_HASH --output RUN_DIR
python -m hypothesis_lab resume --attempt ATTEMPT_ID
python -m hypothesis_lab report --attempt ATTEMPT_ID --format markdown
python -m hypothesis_lab status --attempt ATTEMPT_ID
python -m hypothesis_lab stop --attempt ATTEMPT_ID
python -m hypothesis_lab cleanup --attempt ATTEMPT_ID --preview
```

`run` shall not fetch data, install dependencies, invoke trading clients or publish results. Test access shall be refused without a matching frozen authorization.

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | Complete result artifact, including negative/insufficient-data verdicts |
| 2 | Invalid schema or unsupported configuration |
| 3 | Integrity or provenance failure |
| 4 | Refused authorization/test access |
| 5 | Resource limit, cancellation or runtime failure |

Economic verdict and process success are separate fields.

### 6.2 Hash-bound run manifest

`run_manifest.json` shall include:

- Schema and hypothesis-registration hashes.
- Exact code commit and executed source-file hashes.
- Engine, adapter and normalizer versions.
- Dependency lock hash, installed versions, Python and timezone-database versions.
- Dataset manifest, selected segments and normalized-input hashes.
- Acquisition/import clock mode and evaluation as-of.
- Parameters, costs, baseline definitions and risk limits.
- Seed/RNG, split/fold hashes and test authorization.
- Parent attempt, retry reason and selection provenance.
- Resource limits and output schema versions.

Canonical JSON shall use sorted keys, UTF-8, fixed timestamp/decimal representations and reject nonfinite values. Hash identifiers exclude their own hash field.

Private paths are resolved through a separate local mapping. Public reports contain relative logical references and hashes.

### 6.3 Append-only attempt journal

Use an append-only JSONL journal with:

`sequence`, `event_id`, `timestamp`, `attempt_id`, `event_type`, `parent_attempt`, `manifest_hash`, `payload_hash`, `previous_hash`, `event_hash`.

Event types include:

- Registration and configuration enumeration.
- Start and validation refusal.
- Split authorization and test-access request/result.
- Fold completion and immutable checkpoint.
- Selection freeze and outcome join.
- Failure, cancellation and retry.
- Result sealing and report generation.
- Cleanup receipt.

The writer shall lock, append, flush and synchronize before entering the corresponding protected stage. If journaling fails, evaluation stops. No journal rewrite or truncation is permitted.

Interrupted writes shall be preserved and classified as damaged tails. Recovery appends a new segment referencing the last verified event and damaged-tail hash. A hash chain detects alteration; it does not itself prove historical completeness or prevent coordinated deletion. Independent checkpoint retention is therefore required.

### 6.4 Determinism and recovery

Economic ordering shall be stable by availability, event, cohort and record sequence. Use fixed decimal precision, canonical serialization, single-threaded numerical routines and explicit random algorithms.

The deterministic payload comprises selections, trades, refusals, economic aggregates and uncertainty draws. Wall-clock timing and process metadata belong in a separate execution receipt.

Resume requires matching code, inputs, registration and checkpoint hashes. It creates a linked execution attempt, preserves prior failures and continues from immutable completed partitions. It cannot reevaluate a failed first entry using later data.

### 6.5 Illustrative run and result

A development request might be:

```text
python -m hypothesis_lab run \
  --registration <ensemble-no-registration-hash> \
  --split development \
  --output research-runs/<attempt-id>
```

Expected result schema:

```json
{
  "schema_version": "result/1",
  "illustration_only": true,
  "attempt_id": "<attempt-id>",
  "execution_status": "completed",
  "verdict": "insufficient_data",
  "evidence_strength": "development",
  "independent_test_dates": 0,
  "evaluation_basis": "conditional_one_dollar",
  "counts": {
    "planned_events": null,
    "signal_events": null,
    "entries": 0,
    "evaluated_dates": 0
  },
  "net_pnl_usd": null,
  "baseline_delta_usd": null,
  "roi": null,
  "reasons": ["no_evaluable_entry_pairs"],
  "manifest_hash": "<manifest-hash>",
  "selection_hash": "<selection-hash>"
}
```

This illustrates structure, not measured results. Actual artifacts shall replace placeholders with measured values; unavailable economic quantities remain null rather than fabricated zeros.

## 7. Proposed Hetzner research runner

No remote execution was performed for this specification.

### 7.1 Isolation and initial bounds

A later authorized smoke shall use an immutable research-only source/data snapshot and a new owned output directory.

Initial enforced bounds:

| Resource | Proposed limit |
|---|---:|
| Research workload | One process |
| CPU | One CPU, one computational thread |
| Memory | 2 GiB |
| Elapsed time | Ten minutes |
| Total owned output, including logs/temp files | 1 GiB |
| Host free-space floor | 20 GB |

CPU/memory enforcement shall use an isolated mechanism available on the host, such as a dedicated cgroup, without altering production service groups. Environment thread variables alone are insufficient enforcement.

The external controller may monitor the single research workload; it shall not launch worker pools or hidden numerical subprocesses. Missing enforcement capabilities refuse the smoke pending a revised approved design.

Before starting:

- Verify immutable input hashes and ownership boundaries.
- Probe dependencies once; no automatic installation.
- Verify free space exceeds the floor plus remaining output reserve.
- Record collector health read-only.
- Refuse mutable SQLite/WAL inputs or uncommitted archive spool.
- Disable workload network access where supported.

### 7.2 Stop, status and cleanup

`status` reports owned attempt state, heartbeat age, elapsed time, CPU/memory/output usage and last checkpoint. It performs no source scan or restart.

`stop` addresses only the exact attempt process identity. Request graceful cancellation, allow a short bounded checkpoint interval, then terminate the owned workload if necessary. Preserve the journal and partial artifacts. Never target processes merely by name.

The controller checks space and output growth throughout execution. A bound breach records failure and stops the attempt; it does not enlarge limits automatically.

`cleanup` previews exact owned paths, verifies their resolved location inside the research output root and removes only disposable files under explicit later authorization. It preserves manifests, journals, final receipts and immutable evidence. It shall never delete archive inputs, production paths or unrelated research.

A proposed limit is not a measured result. Execution receipts must record actual elapsed time, peak memory, CPU use, bytes written, free-space observations, termination reason and exit status. An incomplete smoke produces an operational failure, not a strategy verdict.

## 8. Report and decision rules

### 8.1 Readable artifact

Each completed attempt shall produce:

- `report.md`
- `result.json`
- `run_manifest.json`
- Frozen selection and refusal census.
- Trade/economic aggregates and baseline pairing.
- Attempt-journal reference and execution receipt.
- Artifact hash manifest.

Reports shall open with verdict, evidence strength and economic assumption. Public export shall exclude raw private records, source code, credentials, operator details and host addresses.

### 8.2 Required report content

The report shall show:

- Planned population, observed/validated coverage and usable population.
- Events, target dates, signals, attempts, entries, exits and payout-evidence counts.
- Every arm, baseline and preregistered stress.
- Gross/net PnL, cash fees, share fees and other costs.
- Turnover ROI: net PnL divided by gross entered notional.
- Outlay ROI: net PnL divided by total cash outlay.
- Capital return: net PnL divided by initial dedicated capital.
- Undefined ratios as null with reasons.
- Committed capital, peak exposure, drawdown, holding periods and worst-case bounds.
- Date-cluster uncertainty and block sensitivity.
- Paired baseline differences and unmatched exclusions.
- Full-population unknown-payout bounds alongside any proxy-graded subset.
- Skip/refusal reasons, gaps, cohort exclusions and minimum-order flags.
- All configuration attempts, selection history and test access.
- Source/clock limitations and conditional-execution qualifications.

Conditional proxy PnL shall not be labeled realized profit. A favorable mature-outcome subset shall not stand in for the full selected population.

### 8.3 Three verdicts

Classification uses the preregistered primary estimand, useful-effect threshold \(\delta\), uncertainty and required evidence:

| Verdict | Rule |
|---|---|
| **Positive signal** | Evidence is adequate; simultaneous lower bound of incremental net PnL exceeds \(\delta\); net strategy economics also pass the declared positive-economics criterion |
| **Negative result** | Evidence is adequate; the upper bound is below \(\delta\), rejecting the claimed useful benefit |
| **Insufficient data** | Required contracts are unavailable, observations/precision are inadequate, unresolved bounds prevent classification, or intervals leave the claim undecided |

A negative result may mean “no useful advantage established,” not necessarily “certain loss.” Report an additional flag when the upper bound is below zero.

Exploratory data can produce an **exploratory positive signal** or negative result, clearly labeled. Confirmatory strength additionally requires an untouched test, authorized access, frozen procedure and multiplicity control.

Operational failure is reported separately as `execution_status=failed`; an unfinished run cannot receive a completed economic verdict.

## 9. Reuse, migration and implementation stages

### 9.1 Smallest practical structure

Proposed new package:

```text
hypothesis_lab/
  contracts.py
  adapters.py
  evaluate.py
  registry.py
  cli.py
  report.py
```

- `contracts.py`: schemas, canonical hashes, capabilities and refusal taxonomy.
- `adapters.py`: separate legacy, REST15 and compact implementations.
- `evaluate.py`: frozen selection, engine bridges, paired baselines and date-level evaluation.
- `registry.py`: registration, split access, journal and checkpoints.
- `cli.py`: orchestration and research-run lifecycle.
- `report.py`: readable and machine-readable artifacts.

Hypothesis policies should be explicit functions/configurations. A plugin system, distributed scheduler and custom DSL are unnecessary initially.

### 9.2 Source reuse map

| Existing supplied source | Reuse and boundary |
|---|---|
| `artifacts/replay_2026-10-08/signals.py` | Distribution, revision, TAF, censored residual and remaining-maximum primitives |
| `artifacts/replay_2026-10-08/small_order.py` | Pure conditional $1 accounting and compact first-entry semantics |
| `artifacts/rest15_2026-10-08/small_order_rest_v3.py` | Separate retained-sweep execution contract |
| `artifacts/replay_2026-10-08/core.py` | Immutable records, strict-depth engine, conservation and coupled payout bounds |
| `artifacts/replay_2026-10-08/adapter.py` | Read-only evidence views and historical window checks |
| `artifacts/rest15_2026-10-08/replay_rest15.py` | Native catalogue admission, sweep clustering and selection-before-payout pattern |
| `artifacts/replay_2026-10-08/compact_matrix.py` | Expected native interval/side/minute mapping |
| `src/compact_replay.py` | Compact acceptance-state concepts; not a complete strategy runner |
| `src/server_replay.py` | Committed-segment integrity and receipt/import-aware replay |
| `artifacts/replay_2026-10-08/skill_metrics.py` | Full-census proper scores and paired model comparisons |
| `extract.py`, `resume_extract.py`, `freeze.py` | Provenance, bounded extraction and immutable freeze patterns |
| `available_coverage.py` | Necessary-coverage diagnostic pattern, not global certification |

Existing `server_ops.py`, `run_ops.py`, continuation and publication helpers are operational evidence only. They shall not become automatic dependencies of the new CLI or supply embedded host configuration.

### 9.3 Dependency and prerequisite risks

The provided snapshot is not a complete installable application. In particular, `src/server_replay.py` references `src.continuous_weather` and `src.server_store`; `src/compact_replay.py` also references the store. Their complete implementations and repository dependency declarations require inspection during authorized implementation.

Other risks include:

- `pyarrow` and native Parquet support.
- Python compatibility: extraction helpers use APIs newer than a bare Python 3.10 requirement.
- Timezone-database availability and version drift.
- Unqualified imports and path insertion in artifact modules.
- Frozen extraction stamps that are operational assumptions rather than fresh byte hashes.
- Unsupported future fee/asset versions.
- Mutable database sidecars and source catalogue completeness.

Do not repair these risks by silently importing mutable shared code or widening the snapshot. Record the prerequisite, bind its reviewed revision and stop unsupported paths.

### 9.4 Backward compatibility and equivalence

Leave original artifact engines and protocols unchanged.

First integrate them through explicit bridges. Then, if packaging is approved, move or copy pure primitives with source lineage and differential tests. Avoid a generic engine that erases differences between compact, REST15 and strict-depth modes.

Equivalence requires identical:

- Selected tokens/cohorts and frozen first attempts.
- Refusal reasons and population counts.
- Decimal quantities, fee scenarios and payout bounds.
- Capital chronology and cash-release behavior.
- Input mutation behavior.

Byte-identical duplicate engine files in REST15/replay snapshots can inform later deduplication, but historical paths and hashes remain preserved.

A demonstrated defect requires a new engine version with before/after fixtures. Reevaluate obsolete tests against accepted behavior; do not distort production logic to preserve an invalid contract.

### 9.5 Staged implementation

1. **Contract and packaging stage:** resolve operator decisions, validate dependencies, define schemas and synthetic fixtures.
2. **Legacy equivalence stage:** reproduce original engine fixtures and exact H4 inputs without profitability reinterpretation.
3. **Compact admission stage:** implement matrix/clock/binding/transition checks and explicit capability refusals.
4. **Experiment stage:** add registration, chronological splits, attempt journal and deterministic development runs.
5. **Reporting stage:** implement paired baselines, uncertainty, verdicts and public-safe exports.
6. **Authorized smoke:** execute one bounded research-only attempt and record actual resource evidence.
7. **Prospective confirmation:** acquire eligible untouched evidence through separately authorized collection; freeze test access.
8. **Independent review:** reproduce economic outputs, inspect selection/test provenance and verify absence of collector mutation.

No stage is authorized merely by inclusion in this specification. Publication foundation gates and a clean review remain requirements for later implementation delivery.

## 10. Acceptance tests

These are proposed meaningful tests; none were executed during this specification session.

| Area | Required acceptance case |
|---|---|
| Clocks | Future receipt/import records cannot affect earlier decisions; late corrections apply forward only |
| Publication | Early issue/publication time cannot override late acquisition |
| Availability ordering | Different receipt/import order yields the correct latest available state |
| Quote freshness | Cached REST replay cannot refresh age; healthy unchanged-state heartbeat preserves original source time |
| NO pricing | Asymmetric YES/NO fixtures use own NO ask/bid; missing NO remains missing |
| Terms | Unknown/conflicting fees, tick, minimum or asset version refuse economics |
| Accounting | Handwritten USD/CTF examples verify cash, shares, rounding and payout arithmetic |
| Stress | Repricing recomputes $1 quantities/fees; reserve stress preserves quantity; ask≥1 is unsupported |
| Gaps | Gap/reconnect between signal and entry rejects despite a later clean quote |
| Cohorts | Incomplete first event cohort remains selected and fails; chosen-token filtering cannot hide it |
| Transitions | Synthetic event/cohort replacement invalidates removed bindings and preserves only eligible state |
| Audit exclusions | Known pre-r7 exclusions remain excluded; single-cohort evidence cannot certify live transitions |
| Intervals | Tails, negative bounds, inclusivity, Fahrenheit conversion and DST target days remain exact |
| Forecasts | Whole-body changes do not imply target revisions; A→B→A restarts persistence |
| Latest invalid data | Invalid latest forecast/metadata does not fall back to older valid state |
| H1/H4 | Missing contractual maxima block H1; H4 uses only available prior exact/censored labels |
| Payouts | Wrong binding/revision refuses join; Gamma supports labeled proxy economics but never unlocks cash |
| Unknown outcomes | Unknown holdings remain in counts and feasible complementary bounds |
| First entry | Invalid first entry cannot be replaced by a cheaper later one in either execution mode |
| Exits | Invalid frozen bid exit remains unresolved; no later profitable substitution |
| Capital | Unfunded entry fails; fee scenarios conserve independently; entry chronology determines admission |
| Splits | Inspected dates cannot become untouched test; all same-date events share the outer split |
| Walk-forward | Fitted state excludes unavailable labels and crossing positions |
| Attempts | Invalid configs, runtime failures and retries remain visible; overwrite is rejected |
| Test access | Access is journaled before opening; journal failure refuses access |
| Recovery | Interrupted journal/checkpoint resumes transparently without erasing first attempts |
| Baselines | Paired arithmetic uses the same population/costs; unknown data is not zero PnL |
| Reproducibility | Same bound inputs reproduce economic/refusal hashes; changed inputs fail resume |
| Classification | Adequate negative evidence yields negative; zero entries or unresolved intervals yield insufficient |
| Runner | Limits, low space and cancellation stop only the owned research process |
| Public safety | Export excludes raw records, private source, credentials and host/operator details |

Preserve and extend the supplied `test_core.py`, `test_small_order.py`, `test_small_order_rest_v3.py`, `test_adapter.py`, `test_compact_matrix.py`, `test_signals.py`, `test_runner.py`, `test_skill_metrics.py` and `test_replay_rest15.py`.

Later implementation publication shall run the repository’s prescribed foundation commands from the then-approved dependency/source snapshot, plus the relevant new tests. A missing dependency is a failed gate until resolved; it is not a green result.

## 11. Operator decisions requiring resolution

Before implementation:

1. Approve the package integration and dependency versions.
2. Confirm prospective population, date windows, purge policy and untouched-test custodian.
3. Approve useful-effect thresholds, precision requirements and multiplicity claim set.
4. Confirm historical receipt-replay certification rules and import-time exceptions.
5. Approve payout evidence grades and early-exit fee semantics.
6. Confirm capital/exposure settings and minimum-compliant sensitivities.
7. Approve the research directory, available resource enforcement and cleanup authority.
8. Allocate separate implementation/review authority and funding.

No operator decision can transform incomplete archive history into observed evidence or restore an already inspected holdout.

## 12. Tradeoffs, strongest risks and falsification

### Concrete tradeoffs

- **Separate execution contracts:** more explicit adapters and reports, but preserved REST15/compact/strict-depth meanings.
- **Conditional $1 fills:** practical economics with compact data, but no actual-execution claim.
- **Strict availability:** fewer usable cases, but no artificial forecast or quote foresight.
- **Frozen first attempts:** missed later opportunities, but protection against favorable execution selection.
- **Complete attempt history:** modest storage and coordination cost, but visible searches and failures.
- **Prospective confirmation:** slower answers, but a defensible independent test.

### Three strongest risks

1. **Incomplete or incorrectly timed evidence creates apparent edge.**  
   Mitigation: capability checks, receipt/import rules, complete binding histories and visible unknown populations. Falsification: independent replay finds a future input, hidden missing first cohort or unsupported availability exception that changes selection.

2. **Conditional fills and payout proxies overstate economic feasibility.**  
   Mitigation: own-side prices, full fee scenarios, minimum flags, bid exits, capital locking and coupled unknown bounds. Falsification: documented order constraints, fee semantics, quote capacity or payout corrections invalidate the reported economic advantage.

3. **Search and correlated sparse dates manufacture statistical confidence.**  
   Mitigation: immutable splits, all-attempt reporting, frozen primary claims, multiplicity control and date/block uncertainty. Falsification: an untouched prospective test fails the preregistered useful-effect criterion, or valid clustered uncertainty removes the claimed support.

The framework itself is falsified if identical bound inputs produce different economic decisions, if an invalid first attempt disappears on retry, if unknown data becomes zero loss, or if a report claims confirmation after test contamination. A hypothesis is falsified by its preregistered economic or predictive criterion—not rescued by selecting another arm, payout subset or execution assumption after results.