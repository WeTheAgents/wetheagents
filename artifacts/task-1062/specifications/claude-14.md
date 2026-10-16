# WEA Task 1062: Independent specification candidate for a hypothesis-testing lab (`hlab`) in the wea_ther research stack

**Candidate:** Claude-14@claude. This identity is registered separately but shares operator control with the other three candidates. "Independent" means a separate native model session that did not read the other candidates' work. It does not mean separate ownership.
**Stage:** Spec/Ranked, four equal places of 5 WEA, 20 WEA in total. This document is the complete specification. It is not a summary or a plan to write one later.
**Evidence base:** the provided source snapshot only. Common SHA256 `58aab056090a57380a7bbacfce2edaa4783b69984735006de0e0b416373b1c24` (`snapshot-manifest.json`), brief SHA256 `1ae574f0f85ac3b1395af8ba86558e989e7cf0b8ac29540c37be349ec60f46a9`.
**Execution status:** nothing was executed. I ran no backtest, no server command and no resource measurement. Every number below is one of three kinds:
- **[fact]**: quoted from a provided input file or the brief.
- **[proposed]**: a design default.
- **[synthetic]**: arithmetic on a synthetic test fixture, not data.

**Path conventions.** `R/` means `source-prerequisite/artifacts/replay_2026-10-08/`. `S/` means `source-prerequisite/artifacts/rest15_2026-10-08/`. `src/` means `source-prerequisite/src/`. `R/` and `S/` contain byte-identical copies of `adapter.py`, `core.py`, `extract.py`, `run.py`, `signals.py`, `skill_metrics.py` and `small_order.py` (identical SHA256 values in `source-prerequisite-manifest.json`). `S/` adds the REST15 v3 replay and its helpers.

**Normative words.** MUST / MUST NOT / SHOULD as in RFC 2119.

**Public safety.** This document names no hosts, addresses, credentials, account details, volume identifiers or raw records. Server locations are written as placeholders: `<RESEARCH_ROOT>` (an isolated dated research directory) and `<ARCHIVE_ROOT>` (the immutable archive, read-only).

---

## 0. Glossary

| Term | Meaning in this spec |
|---|---|
| Event | One weather contract set: one station, one local target day, all temperature intervals. |
| Interval / market | One native temperature bin of an event. It has a condition ID and a YES token and a NO token. |
| Own-side quote | The best bid and best ask of the exact token being bought or sold. A NO quote is never derived from a YES quote. |
| Cohort | One identifiable synchronized observation of an event's tokens. In compact mode this is a minute cohort with a cohort ID and skew. In REST mode it is a sequential REST sweep cluster. |
| Market date | The contract's station-local target day. It is the unit used to cluster uncertainty. |
| Decision | A frozen choice of (event, token, side, model probability) made at the signal clock. |
| Entry | The first eligible observed cohort after the signal, chosen by timestamp before its content is validated. |
| Arm / configuration | One fully resolved parameter vector of one hypothesis revision. |
| Attempt | One execution of one manifest. It is journaled whether it succeeds or not. |
| Partition | development, train, validation or test. Each is a set of market dates fixed by a split record. |
| Evidence level | Payout grade P0–P3 and weather grade W0–W2 (§3.7). |

---

## 1. Outcome, non-goals and hypothesis contract

### 1.1 Outcome

`hlab` is a thin harness around the existing pure engines. It takes three inputs:
- a preregistered, versioned hypothesis;
- an immutable, hash-bound dataset snapshot from one of three adapters;
- a frozen chronological split.

For each attempt it produces:
1. A census of every event in the declared population, each with exactly one terminal classification: decision, skip with reason, or refusal with reason.
2. A frozen selection file, written and hashed **before** any payout evidence is opened.
3. Conditional **$1 gross-notional full-fill** accounting at the frozen first eligible own-side ask, under complete CTF and USD fee scenarios and a fixed stress grid.
4. Matched-baseline comparisons, uncertainty clustered by market date, and one verdict: **POSITIVE_SIGNAL**, **NEGATIVE_RESULT** or **INSUFFICIENT_DATA**. The verdict carries an explicit **exploratory** or **confirmatory** strength label.
5. An append-only, hash-chained attempt registry record and a readable Markdown report. Both can be re-derived from the manifest.

Acceptance in one sentence: with the same immutable inputs, code revision, parameters and seed, `hlab verify` reproduces the same economic outputs and exclusions bit for bit. The report lists every journaled attempt in the hypothesis family.

### 1.2 Narrow non-goals

- No real orders, wallets, signing, approvals, redemption or payment claims. The framework has no network client for trading. This matches `README.md` and `protocol_small_order_v2.json` (`scope`).
- No collector, timer, scheduler, quota, security, package or credential change. No restoration of the deleted Volume.
- No reconstruction of NO prices, depth, queue position, fills or minute quotes from REST snapshots or checkpoints.
- No universal coverage-percentage gate. Suitability is decided per hypothesis.
- No new heavy archive extraction. The existing `R/extract.py`, `S/target_metadata.py` and `S/build_index.py` outputs are consumed as they are.
- No forecast-skill product. `R/skill_metrics.py` stays a diagnostic.
- No website. One Markdown report per family is sufficient.
- No profit promise. A successful smoke run proves only that the mechanics work.
- No re-implementation of the WS L2 depth replay (`src/server_replay.py`). It belongs to the strict-depth mode, which is out of scope for the $1 mode.
- No change to the meaning of existing engines, protocols or historical results.

### 1.3 Design invariants

| ID | Invariant |
|---|---|
| I1 | Every input fact is used only if its **availability time** is ≤ its cutoff (§2.1). Weather and metadata use signal − 5 s. Signal-cohort prices use ≤ signal. |
| I2 | Own-side quotes only. NO is never 1 − YES. A missing side means unavailable, not inferred. |
| I3 | The first eligible entry is frozen by timestamp before validation. If that entry is invalid, the decision is rejected. A later favorable quote never replaces it. |
| I4 | Selection is frozen and hashed before the payout store is opened. Payouts are joined by exact binding only. |
| I5 | Refuse rather than repair. Every refusal, skip and reject has a code and stays in the census denominator. |
| I6 | Previously inspected dates can never become test dates. Previously accessed test dates downgrade any later result to exploratory. |
| I7 | Every attempt is journaled before it computes, including failures, refusals, stops and retries. Registry history is append-only. |
| I8 | Cash is fully funded per ledger and never released on Gamma marks. Unknown payouts keep [−cash, shares − cash] bounds. |
| I9 | Results carry their conditional labels: conditional full fill, payout grade, development-only and minimum-order flags. |
| I10 | Existing engines are pinned by SHA256 and called, not edited. Behavior changes require a new module version. |
| I11 | Uncertainty is clustered by market date. Cities on the same date are correlated (wea_ther `AGENTS.md`). |
| I12 | Proposed resource bounds are never reported as measured. Measured values come only from receipts written by the runner. |

### 1.4 Hypothesis schema `hlab.hypothesis/1`

A hypothesis is one UTF-8 JSON file. Its canonical form is sorted keys, no NaN, and decimals written as strings, the same convention as `packed()` in `S/replay_rest15.py` and `R/extract.py`. Its SHA256 is the **registration hash**. A field change creates a new `revision` and a new hash. Earlier revisions stay in the registry.

| Field | Type | Rule |
|---|---|---|
| `schema` | const `"hlab.hypothesis/1"` | Required. |
| `hypothesis_id` | string `[A-Z0-9-]+` | Stable across revisions. |
| `revision` | int ≥ 1 | Monotonic. The registry refuses a reused (id, revision) pair with a different hash. |
| `family` | enum `ensemble_no`, `price_path`, `forecast_revision`, `residual_memory`, `remaining_maximum`, `two_regimes`, `control` | The multiplicity family (§4.7). |
| `rationale` | text | The mechanism, why it could be mispriced, and what would contradict it. |
| `prediction` | object `{direction, quantity, horizon}` | For example "net PnL per $1 gross > 0 versus the primary control, hold to payout". |
| `adapter` | object `{id, min_version, required_streams[], optional_streams[]}` | Streams are named, for example `own_bbo_minute`, `rest_sweep`, `forecast_daily_max_members:5`, `taf_peak_window`, `metar_native_kt`, `prior_outcome_labels`. |
| `population` | object `{stations\|all, horizon: "T-1"\|"T0", intervals: "all_native_including_tails", date_scope: split_ref}` | Dates are never listed here. They come from the split. |
| `clocks` | object `{signal: {local_window, rule}, weather_cutoff_offset_s: 5, entry: {min_delay_s, max_delay_s, basis}}` | Defaults by adapter: minute mode 60–300 s; REST mode start ≥ +60 s and end ≤ +1200 s. |
| `signal` | object `{mechanism_ref, parameters, search_space}` | `mechanism_ref` names a pinned function, for example `signals.classify_revision@sha256:…`. `parameters` are fixed values. `search_space` is an explicit finite grid or `null`. |
| `side_rule` | enum `fixed_YES`, `fixed_NO`, `max_gap_both_sides` | `max_gap_both_sides` compares model probability with each side's own ask. This is the existing `best_gap` semantics in `R/run.py`. |
| `entry_rule` | const `first_observed_cohort_no_fallback` | Fixed. Not configurable. |
| `exit_rule` | `hold_to_payout` (default), or `first_cohort_after_local_time` with `own_bid` | Early exit stays disabled until operator decision D6 (§8.7). |
| `execution_model` | `exec.one_dollar_full_fill/1` + `stress_grid_ref` | §3. |
| `baselines` | list of baseline IDs + `primary_baseline` + `primary_control` | §3.9. |
| `split_policy` | split ID + allowed partitions | §4.2. |
| `evaluation` | `{primary_metric, primary_stress, fee_scenarios_required: ["CTF","USD"], min_dates_ci: 10, min_dates_confirmatory: 20, min_graded_fraction: 0.8, alpha: 0.05, multiplicity: "holm_within_family"}` | Proposed defaults. Overrides must be set at registration. |
| `evidence_requirement` | `{payout_min: "P1", weather_min: "W0"}` | `weather_min` > W0 only when the claim depends on verified weather. |
| `seed` | int | Used only by randomized baselines and the bootstrap. |
| `registered_at` | RFC 3339 | Informational. Excluded from the attempt-ID hash. |
| `supersedes` | `{id, revision}` or null | |

### 1.5 Preregistration: what is fixed and what is evaluated

1. **Fixed before any evaluation partition is touched:** every field above. Search spaces must be finite enumerated grids, for example `edge ∈ {0.03, 0.05, 0.08}`. A grid of size K counts as K configurations in the family's multiplicity ledger, whether or not all K are run.
2. **Fitting:** only the registered grid is searched, only on the train partition (or development, for exploratory work), using the registered selection rule. The proposed default rule is to maximize the minimum of the two fee scenarios' mean per-date net PnL at the primary stress, breaking ties by the smallest grid index. Exactly one configuration moves to validation, then to test.
3. **Internal mechanism estimation is not search.** For example, the expanding station calibration in H4 (`R/run.py`, `historical_errors`) is part of the mechanism. It uses only labels received before the signal and is not counted as configuration search.
4. **What is evaluated:**
   - Primary: per-market-date net PnL of conditional $1 hold-to-payout trades at the frozen first entry, on P1+ graded positions, compared with cash and with the declared primary control, under both fee scenarios at the primary stress.
   - Secondary: the full stress grid, the minimum-compliant subset, G2-only payouts, unknown-payout joint bounds, and the refusal and skip census.
   - Not evaluated as evidence of edge: forecast Brier or log scores (diagnostic only), midpoint comparisons, or any later-entry variant.

### 1.6 Example hypotheses

All parameters below are **[proposed]** examples. The H3 thresholds come from `R/protocol.json` **[fact]**.

#### Example A: ensemble-NO, `ENSNO-01` r1

```json
{
  "schema": "hlab.hypothesis/1",
  "hypothesis_id": "ENSNO-01",
  "revision": 1,
  "family": "ensemble_no",
  "rationale": "Equal-weight five-family daily-max ensemble with fixed 1.5C Gaussian kernel (signals.interval_probability) may assign lower YES probability to non-favorite native intervals than their own YES ask implies; the NO token's own ask may then be cheap. Contradicted if own-NO buys at frozen first entry lose versus the GEFS-only control and cash on matched dates.",
  "prediction": {"direction": "positive", "quantity": "net_pnl_per_1usd_gross", "horizon": "hold_to_payout"},
  "adapter": {"id": "compact_v2", "min_version": "1", "required_streams": ["own_bbo_minute", "expected_matrix", "fee_terms", "forecast_daily_max_members:5"], "optional_streams": []},
  "population": {"stations": "all", "horizon": "T-1", "intervals": "all_native_including_tails", "date_scope": "split_ref"},
  "clocks": {"signal": {"local_window": "18:00-19:00", "rule": "first_validated_full_event_cohort"}, "weather_cutoff_offset_s": 5,
             "entry": {"min_delay_s": 60, "max_delay_s": 300, "basis": "first_distinct_observed_cohort"}},
  "signal": {"mechanism_ref": "signals.interval_probability@<sha256>",
             "parameters": {"kernel_c": "1.5", "families": 5, "max_family_age_s": 43200},
             "search_space": {"no_edge": ["0.03", "0.05", "0.08"]}},
  "side_rule": "fixed_NO",
  "entry_rule": "first_observed_cohort_no_fallback",
  "exit_rule": "hold_to_payout",
  "execution_model": {"id": "exec.one_dollar_full_fill/1", "stress_grid_ref": "stress.standard/1"},
  "baselines": ["B0_cash", "B1_mechanism_control:GEFS_only_same_rule", "B2_matched_random_own_ask:R200", "B3_same_event_favorite_YES"],
  "primary_baseline": "B0_cash", "primary_control": "B1_mechanism_control:GEFS_only_same_rule",
  "split_policy": {"split_id": "SPLIT-COMPACT-P1", "partitions": ["train", "validation", "test"]},
  "evaluation": {"primary_metric": "mean_per_date_net_pnl", "primary_stress": "ask_plus_0.01",
                 "fee_scenarios_required": ["CTF", "USD"], "min_dates_ci": 10, "min_dates_confirmatory": 20,
                 "min_graded_fraction": "0.8", "alpha": "0.05", "multiplicity": "holm_within_family"},
  "evidence_requirement": {"payout_min": "P1", "weather_min": "W0"},
  "seed": 1062
}
```

Decision rule: among intervals whose own NO token is tradable at the signal cohort, compute `gap = (1 − p_yes) − NO_ask_signal`. Choose the largest gap if it is ≥ `no_edge`, with one decision per event. Execution uses the frozen first entry's own NO ask. The signal ask is used only for ranking, not for the fill. Grid size K = 3.

Suitability: compact v2 is suitable. REST15 is suitable only as a separately registered sweep-clock variant `ENSNO-01R`, labelled development-only. The legacy projection is suitable on the same retained REST subset, also development-only.

#### Example B: price path / reaction, `PPATH-01` r1

Rationale: a large own-ask move with no forecast change inside the lookback is an overreaction, and fading it by buying the opposite token's own ask earns money at payout.

- Signal (compact, T-1 local 10:00–20:00, evaluated per validated minute cohort): for interval i, the own YES best bid rises by ≥ Δ over the trailing L minutes. Every minute in [t−L, t] must be validated with no gap, reconnect, epoch change or carried-forward cell. In the same window, no five-family target array has a new content hash (canonical target hash plus first-availability origin from `signals.persistent_target_family`).
- Action: buy the **same interval's own NO ask**. One decision per (event, local date). The first qualifying minute wins and later qualifying minutes are ignored, with no search.
- Grid: Δ ∈ {0.08, 0.12} × L ∈ {30, 60} minutes, so K = 4.
- Primary control: the same event, interval and entry cohort, buying own YES (the momentum mirror). Secondary: B2 matched random.
- Suitability:
  - compact v2: suitable.
  - REST15: **refused** with `rest_not_minute_grid`. Sweeps arrive about every 15 minutes inside 80-minute T-1 windows (`S/diagnose.py` reports `within_870_930` cadence; `R/extract.py` keeps only local 12:00–13:20 and 18:00–19:20). A trailing 30-minute minute path cannot be observed.
  - Legacy projection: refused for the same reason.

#### Example C: forecast revision, `FREV-01` r1 (two arms, fixed parameters)

Rationale: H3 as in `R/protocol.json` **[fact]**. Compare actual receipt vintages at the noon and evening cohorts.
- Arm `single`: exactly one family's mean changes by ≥ 1.0 °C and all others by ≤ 0.3 °C.
- Arm `common`: ≥ 3 families move the same direction by ≥ 0.5 °C.
- Both arms require all five families fresh, a changed response hash, and persistence ≥ 1 h at the signal (`signals.classify_revision`).
- Side rule `max_gap_both_sides`: the five-family calibrated probability against each side's own ask, gap ≥ 0.05.
- No search space; K = 2 (two arms). Primary control: `five_family_control`, the same selection without the revision gate, on the same events.
- Suitability:
  - REST15: suitable, development-only, exploratory label forced. It needs the retained noon sweep and coherent identity; otherwise skip with `no_retained_noon_sweep`.
  - compact v2: suitable when five-family vintage records with first availability exist (compact contract H3 row).
  - Legacy projection: suitable on the retained subset only.

#### Example D: residual memory, `MEM-01` r1 (development-only, legacy)

- H4 from `R/protocol.json` **[fact]**, restricted to the **640 exact preserved H4 inputs** **[fact, brief]**. Any decision that needs a record outside that set is skipped with `outside_preserved_h4_inputs`.
- METAR wind fields need the native knot tag (`R/run.py`, `metar_row`); otherwise they are treated as missing.
- Controls: the same-token ordinary calibration control and the no-reset ablation.
- Permanently `development`. Any verdict is exploratory.

---

## 2. Data adapter contracts

### 2.1 Clock model (all adapters)

Every canonical record carries these clocks as separate fields. A missing clock is `null`, never estimated.

| Clock | Meaning | Examples in the snapshot | Allowed use |
|---|---|---|---|
| `event_time` | The real-world time the content describes. | Forecast target local day; METAR `observed`; TAF group validity; the contract's local target day (`core.local_target_day`, DST-aware). | Signal semantics, such as the peak window or local day. Never availability. |
| `model_time` | Model run or initialization time. | `actual_run` in forecast rows; `actual_initialization_proven=False` (`R/extract.py`). | Informational. Never inferred from expected release times. Freshness instead uses an unchanged-array age proxy (§2.8). |
| `publication_time` | A time declared by the source. | Book `exchange_timestamp` (semantics unknown); compact `source_timestamp` (semantics `unknown`, `last_price_change` or `state_observation`); TAF `issued`; METAR `reportTime`. | Staleness checks only. Must not postdate receipt (`small_order._validate_quote`). Never availability. |
| `receipt_time` | Local receipt of this message. | `received`. | Availability component. |
| `first_receipt_time` | First local receipt of this content. | `first_received`; `original_received` for fee cache seeds. | Availability component. Persistence origin. |
| `import_time` | When the record entered the research store. Differs from receipt for backfills. | `data.imported_at` (`src/compact_replay.py`, `src/server_replay.py`). | Availability component. A record imported after the decision was not available live. |
| `state_validated_at` | Last successful fresh source observation or healthy heartbeat confirming the quote state. | Compact BBO fields (`small_order.py`). | Quote freshness: age ≤ 120 s. |

**Availability rule.** `available_at = max(receipt_time, first_receipt_time or receipt_time, import_time or receipt_time)`.

- A weather or metadata record is usable for a signal at time *s* iff `available_at ≤ s − 5`.
- A signal-cohort price is usable iff `available_at ≤ s`.
- An entry quote is usable iff its cohort is the frozen first entry and every validity check passes at the entry time.

This is the union of the existing rules in `core.AsOfView` (receipt and first receipt), `src/compact_replay.CompactAsOf` (`imported_at`) and `small_order` (validated-state age). `hlab` MUST apply all three, even where an individual engine checks only some of them.

### 2.2 Canonical own-side quote record (adapter output)

`OwnQuote{adapter, token, side (YES|NO), interval_id, event, binding_hash, cohort_id | sweep_id, cohort_kind (minute_cohort|sequential_rest_sweep), observed_at, receipt_time, first_receipt_time, import_time, state_validated_at, state_validation (rest|heartbeat|native_rest_snapshot), source_timestamp, source_timestamp_semantics, connection_epoch | null, cohort_skew_s | null, bid, ask, bid_size | null, ask_size | null, tick, min_order_size, carried_forward (bool), status (ok|observed_empty|empty_bid|empty_ask|empty_both|gap|unknown|missing), provenance{record_id, segment_path_rel, segment_sha256}}`

Rules:
- `bid`/`ask` are decimal strings exactly as received.
- `null` requires an explicit empty or gap status. This is the `compact_matrix._row_reasons` semantics.
- `carried_forward=true` is never tradable unless `state_validation=heartbeat` and the heartbeat proof flags pass (`small_order`: `healthy`, `initialized`, `cached_replay=False`).

### 2.3 Common adapter interface

Each adapter is a read-only Python class with these methods:

| Method | Returns | Notes |
|---|---|---|
| `describe()` | Capability manifest: streams, cohort kind, cadence, windows, payout sources, known limitations, `independent_test_eligible: bool`. | Static, versioned. |
| `freeze(source_dir, asof)` | Dataset manifest (§5.2). | Hashes every input file. Refuses a partial extraction where completeness is asserted. |
| `population(split, partition)` | Ordered event list with binding hashes as of the population-definition time. | Order is (target date, event ID). |
| `as_of(cutoff)` | Immutable view: bindings, fees/terms, forecasts, auxiliary data. | Built on `core.AsOfView` semantics plus the import clock. |
| `signal_cohort(event, window)` | The first observed cohort in the window, frozen before validation. | This mirrors `adapter.Evidence.cohort` and `replay_rest15.first_sweep`. |
| `entry_candidates(token, signal_time)` | The ordered observation stream for the chosen token from the signal to the end of the window. | Fed unchanged to the pinned `simulate_one_dollar`. |
| `suitability(hypothesis)` | `suitable`, `suitable_with_label`, or `refused` plus codes. | §2.10. |
| `payouts()` | **Sealed.** Raises unless the registry shows `selection_frozen` for this attempt. | §4.1. |

### 2.4 Identity and interval binding

`binding_hash = sha256(canonical{event, market_id, condition_id, yes_token, no_token, rules_hash_semantic, rules_hash_literal, native_lower, native_upper, lower_unbounded, upper_unbounded, inclusivity, unit, station, timezone, local_target_day, source, tick, min_order_size, fee_enabled, fee_schedule, protocol_version, closed, accepting})`

1. Native endpoints only. Unit conversion happens inside signal code, never in the binding. Bins are ordered by parsed bounds, not list index. Coherent geometry is required: both open tails and contiguous edges (`run.coherent_bins`). Otherwise skip with `incomplete_native_bin_geometry`.
2. Two rule hashes are kept: the literal hash (`legacy_rules`) and the semantic hash (`semantic_rules`, which allows only null-source → identical inferred source enrichment). This is the existing `R/extract.py` behavior. Payout joins use the literal hash (G2) or the binding fields (G1), exactly as `replay_rest15` and `skill_metrics` do.
3. If any binding field changes between the weather cutoff and entry, the decision is rejected with `intervening_metadata_binding_changed`. This applies even if the field later changes back (`small_order_rest_v3`, `metadata_history`).
4. All intervals of an event must share event, target, station, unit, timezone and source. Otherwise skip with `mixed_contract_identity`.
5. A hypothesis may bind only to IDs from the as-of catalogue that have a native-verified row (`S/build_index.py`, `replay_rest15.native_markets`). If the latest catalogued version is unverified, skip with `latest_catalogued_metadata_not_native_verified`. There is no fallback to an older row.

### 2.5 Adapter `rest15` (old REST15 sweeps and the frozen v3 protocol)

| Aspect | Contract |
|---|---|
| Sources | The normalized evidence DB produced by `R/extract.py`, extended by the targeted metadata import (`S/target_metadata.py`, new copy, ≤ 5 GB logical IO **[fact]**). Also the metadata ID index (`S/build_index.py`, "values are never execution inputs" **[fact]**), the frozen analysis manifest, the population file and the separate payout audit file. |
| Unit of observation | One `sequential_rest_sweep`: book snapshots clustered by receipt, split at gaps ≥ 60 s, duration ≤ 120 s, complete YES/NO inventory, one request per token (`small_order_rest_v3._sweep`). Each book is a full native ladder with tick and minimum size. |
| Clocks | `receipt_time` per request. `first_receipt_time = receipt_time`, as written by the extractor. `publication_time = exchange_timestamp` with **unknown semantics** that can never establish freshness. Weather and metadata cutoff is signal − 5 s. |
| Coverage | Only station-local T-1 12:00–13:20 and 18:00–19:20 (`extract.selected_book_time`). Cadence is about 15 min. `archive_window_complete=False` always. The entry basis is "first observed **retained** sweep", never a certified global first sweep (`protocol_rest15_v3.json`, `coverage`). |
| Entry | First sweep starting ≥ signal + 60 s. If its end is > signal + 1200 s, reject with `first_entry_sweep_outside_fixed_window` and do not substitute (`S/test_small_order_rest_v3.py` covers this). The fill is conditional at sweep end, using the chosen book (age ≤ 120 s). |
| Split role | All dates are **development**. `independent_test_eligible=false`. `independent_test_dates=0` **[fact]**. |
| Hypothesis suitability | Ensemble-NO and forecast revision: `suitable_with_label` (development, retained subset, REST cadence). H2 two regimes and H4 main: skip with `blocked_uncertified_latest_TAF_history` / `blocked_uncertified_latest_METAR_history` (`replay_rest15` census) unless they use the preserved H4 set (§2.6). H1 remaining maximum: refused with `blocked_missing_T0_hourly_contractual_max`. Price path at minute resolution: refused with `rest_not_minute_grid`. |
| Explicit refusals | Any request to emit per-minute quotes, carry a sweep quote forward to a later minute, or interpolate between sweeps: hard error `rest_not_minute_grid`. A book that is absent from a sweep is unavailable, not stale-filled. |
| Depth | Ladders exist, but the $1 model ignores depth. An optional diagnostic `displayed_ask_size_ge_shares` is labelled "snapshot capacity, not executability". |

### 2.6 Adapter `legacy_h4` (part of the legacy preservation)

| Aspect | Contract |
|---|---|
| Sources | The **640 exact H4 inputs** **[fact, brief]**, each identified by record ID and content hash in their own preservation manifest. |
| Freeze | `freeze` MUST verify exactly 640 records, every hash, and that each record has `available_at`. A count other than 640 refuses the run with `h4_preservation_manifest_mismatch`. |
| Use | Only for `residual_memory` hypotheses. Labels must have receipt ≤ signal − 5 s (`R/run.historical_errors` already ignores future G1 status). The 10-day / 5-label / EMA semantics are pinned in `signals.local_memory`. |
| Refusal | Any H4 feature that needs a record outside the set is skipped with `outside_preserved_h4_inputs`. Wind without the native knot tag is treated as missing. |
| Role | development only. |

### 2.7 Adapter `legacy_projection`

| Aspect | Contract |
|---|---|
| What it is | The normalized **projection** written by `R/extract.py`: market, book, forecast, METAR and context rows with segment provenance. **It is not** a full order-book or depth history. Books exist only in the two retained windows and only from retained segments. The first extraction phase closed at its IO budget and is explicitly partial **[fact, `data_contract.md`]**. |
| Completeness | `freeze` reads `extract.complete.json`. If `partial=true`, every hypothesis that asserts population completeness is refused with `partial_extraction_population_unknown`. Observed-retained-subset diagnostics are `suitable_with_label`. A missing row is **unknown**, never absent or zero (`R/available_coverage.py` principle). |
| Quotes | Only books present in the projection. NO is used only if the NO token's own book row exists. NO and depth are never reconstructed. |
| Payouts | Gamma-derived audit grades G1/G2 from the payout audit file, joined only after the selection is frozen. Binding fields and literal rule hash must match exactly (`replay_rest15`, `skill_metrics`). |
| Role | development only. |

### 2.8 Adapter `compact_v2` (new compact archive)

| Aspect | Contract |
|---|---|
| Sources | Committed compact archive segments, read only through the catalog snapshot with integrity checks: size, SHA256 and row count per segment (the `src/server_replay.committed_rows` discipline). Never raw spool or uncommitted files. |
| Record kinds consumed | `session_start` / `session_stop` (clear state); `gap` (by source; token-scoped or global; `interval_binding` gap drops affected bindings); `market_version` / `market_receipt`; `http_request` / `http_receipt` / `http_body_version` (fee); `fee_cache_seed` (with `original_received`); `execution_terms_version` / `execution_terms_receipt`; `expected_matrix` (complete binding inventory); `bbo_sample_batch` (per token: bid, ask, tick, minimum size, `received`, `valid`, plus cohort ID, skew and session epoch). This follows `src/compact_replay.CompactAsOf`. |
| Quote validity at entry | First distinct cohort in [+60 s, +300 s] chosen by timestamp. Validated-state age ≤ 120 s. Cohort skew ≤ 5 s. Same connection epoch from signal to entry. No gap, reconnect or epoch change on any chosen-token observation between them. Active binding. Finite tick-aligned 0 < bid ≤ ask < 1. Fee binding equals metadata (`small_order.simulate_one_dollar`). |
| Metadata and fee freshness | Market receipt age ≤ 600 s. Fee receipt ≤ 21600 s. CLOB terms ≤ 21600 s when fees are enabled. Supported schedules are fees disabled with base fee 0, or fees enabled with exponent 1 and terms agreeing on rate and base fee. Anything else is rejected with `unsupported_fee_schedule` (`compact_replay.buy_one_dollar`). |
| Matrix acceptance | `compact_matrix.validate_matrix` over `event × every native interval (both tails) × YES/NO × minute`. It reports planned, recorded, valid, tradable, unavailable and unknown counts and never infers a complement. |
| Weather vintages | One content payload per hash plus receipt records. An A→B→A change restarts the persistence origin (`signals.persistent_target_family`). The unchanged-array age is a **conservative proxy**, not proof of model age (`compact_contract_v2.md`). |
| Cohort registry | A separate, versioned `cohorts.json` of evidence-backed cohort facts (format below). Rules: a decision whose signal or entry minute falls in an `excluded` window is skipped with `known_invalid_cohort_window`. A decision whose signal→entry interval crosses a collector revision boundary or session epoch is rejected with `unverified_cohort_transition` until a transition record has `observed_live_transition` evidence. A future collector revision adds a new boundary entry. Unknown revisions are refused with `unregistered_collector_revision`. |
| Split role | Prospective dates registered before they occur can be train, validation or test (§4.3). Dates already inspected are development (§4.2). |

The facts in the initial cohort registry are **[fact, brief]**:
- 15 known pre-r7 split minutes, excluded in the first daily audit, with evidence references.
- 40 post-r7 minutes checked in one cohort, recorded as `verified_single_cohort_window`.
- No observed live transition, recorded as `transition_observed=false`.

**Known engine gap and the required resolution.** `CompactAsOf.buy_one_dollar` measures age from `received`, not `state_validated_at`. It does not check the observed-versus-carried-forward flag and does not check intervening gaps between signal and entry. `small_order.simulate_one_dollar` enforces all three. `hlab` MUST use `CompactAsOf` only to build as-of binding, fee, terms and expected-matrix state, and MUST use `simulate_one_dollar` for entry and accounting. A differential test documents the semantic difference (§8.6, T-CMP-3). Neither module is edited.

### 2.9 Gap, empty and unknown semantics (all adapters)

| State | Meaning | Tradable | Counts toward |
|---|---|---|---|
| `ok` | Own bid and ask present and validated. | yes, if all checks pass | recorded, valid, tradable |
| `observed_empty` / `empty_*` | Known empty side. | no | recorded, valid, unavailable |
| `gap` / `unknown` / `missing` | Source state unknown. | no | unknown |
| Absent record | Nothing archived. | no | unknown |

A gap clears carried state for its scope (`CompactAsOf`). The next validated observation starts fresh. There is never a previous-quote fallback.

### 2.10 Suitability and refusal taxonomy

Suitability is computed **per hypothesis and adapter** from required streams, clocks and population, never from a global coverage percentage. The report shows the usable population as counts with reasons. Insufficient usable data shows up as `INSUFFICIENT_DATA` at the verdict step (§7.1), with its predeclared per-hypothesis threshold. It is not a blanket gate on the data.

Three levels of negative outcome:

| Level | Scope | Effect | Example codes |
|---|---|---|---|
| `refuse_run` | adapter × hypothesis | The attempt is journaled as `refused` and runs no computation. | `rest_not_minute_grid`, `partial_extraction_population_unknown`, `h4_preservation_manifest_mismatch`, `unsupported_adapter_version`, `blocked_missing_T0_hourly_contractual_max`, `split_contains_noneligible_dates` |
| `skip_event` | event | Census row with a reason. No decision. | `no_retained_evening_sweep_unknown_archive_remainder`, `mixed_contract_identity`, `incomplete_native_bin_geometry`, `missing_or_proxy_age_filtered_GEFS`, `missing_5family_prior_vintages`, `known_invalid_cohort_window`, `outside_preserved_h4_inputs`, `latest_catalogued_metadata_not_native_verified`, `signal_below_threshold` |
| `reject_entry` | decision | Execution row with a reason. Counted in decisions and in rejections. | All `simulate_one_dollar` reasons, for example `no_distinct_observed_entry_cohort_in_window`, `entry_stale_validated_quote_state`, `intervening_gap_reconnect_or_unknown_health`, `first_entry_sweep_outside_fixed_window`, `intervening_metadata_binding_changed`, `unverified_cohort_transition`, `capital_rejected` |

Invariant: `population = Σ skip_event + decisions`, and `decisions = entries + Σ reject_entry`. `hlab verify` fails if either equality breaks.

### 2.11 Adapters MUST NOT

- Derive NO from YES, a midpoint, or the complement of a bid.
- Convert REST receipts or checkpoints into minute quotes or refresh their age.
- Infer model initialization or use an expected release time.
- Fall back to an older valid record when the latest one is invalid or stale (`data_contract.md` acceptance gates).
- Read the payout store before the selection is frozen.
- Write anywhere except the attempt's own output directory.

---

## 3. Economic model: conditional $1 full fill

### 3.1 Scope and labels

Every position is a **hypothetical full fill** of $1 gross notional before fees at the frozen first eligible own-side ask. Every result row and every report table carries these fields:
- `full_fill_assumed=true`, `observed_fill=false`, `depth_checked=false`;
- `market_order_notional_applicability="unknown_not_promised"`;
- the `min_share_feasibility` flag;
- the payout grade.

This is the regime in `R/protocol_small_order_v2.json`, `R/small_order.py` and `S/small_order_rest_v3.py`. `hlab` adds no fill logic of its own.

### 3.2 Frozen first eligible entry

1. The decision is frozen at the signal clock: token, side, model probability, signal cohort ID and trace IDs.
2. The entry candidate is the earliest observed cohort satisfying only the timestamp predicate:
   - minute mode: distinct from the signal cohort and inside [+60 s, +300 s];
   - REST mode: start ≥ +60 s, end ≤ +1200 s.
   It is chosen **before** content validation.
3. If that candidate fails any validation, the decision is rejected with that reason. Later cohorts are never examined for that decision. This holds in both pinned engines and in `core.ReplayEngine` (`attempts` map). `S/test_small_order_rest_v3.py` and `R/test_small_order.py` already test it.
4. There is one attempt per (configuration, event). A rejected attempt consumes the event budget (`core`: `event_attempt_budget_exhausted`).
5. The signal ask is used only for ranking (`side_rule`). The fill price is always the entry cohort's own ask. No entry-time edge recheck is applied (`entry_model_EV_recheck=false`, `protocol_rest15_v3.json`), so the entry price cannot filter trades on its value.

### 3.3 Accounting

Let *a* be the entry own ask, *r* the archived fee rate and *e* the exponent. Fees are supported only when *e* = 1 and the fee terms agree with the metadata.

| Quantity | Formula |
|---|---|
| Gross shares | *q* = 1 / *a* |
| Fee (USD) | *f* = ceil_{0.00001}( *r* · (*a*(1−*a*))^*e* / *a* ). This is the substituted dollar-notional form used in `small_order._account`. |
| Fee shares | *f* / *a* |
| **USD-cash scenario** | cash outlay = 1 + *f*; payout shares = *q* |
| **CTF-share scenario** | cash outlay = 1; payout shares = *q* − *f*/*a* |
| Payout per share | π ∈ {0, 1}, or ½ only under an attested void geometry (`core.complementary_joint_bounds`) |
| Gross PnL (before fees) | π · *q* − 1 |
| Net PnL | USD: π·*q* − (1+*f*). CTF: π·(*q* − *f*/*a*) − 1 |
| Unknown payout bounds | [−cash, payout_shares − cash] |

The two scenarios are complete and uniform portfolios. They are never mixed per position (`core` `MODES`).

**[synthetic] worked example**, taken from the fixture in `S/test_small_order_rest_v3.py`: *a* = 0.40, *r* = 0.05, *e* = 1.
- *q* = 2.5 and *f* = 0.05·0.24/0.40 = 0.03.
- USD scenario: cash 1.03, payout shares 2.5.
- CTF scenario: cash 1, payout shares 2.425.
- If π = 1: net USD = 2.5 − 1.03 = **1.47**; net CTF = 2.425 − 1 = **1.425**; gross PnL = **1.50**.
- If π = 0: net USD = −1.03; net CTF = −1.00.

### 3.4 Fees and terms

- Unknown fees reject. There is no assumed zero.
- A schedule other than exponent 1 rejects with `unsupported_fee_schedule`.
- Disagreement between the metadata rate, the fee endpoint base fee and the CLOB terms rejects with `fee_disagreement`.
- Stale fees or terms reject (§2.8).
- The fee binding at signal must equal the fee binding at entry (`small_order`, `fee_binding_mismatch`).
- `fee_rounding` follows the pinned quantum-ceiling rule. The report states that exchange-side rounding is "not independently verified".

### 3.5 Stress grid `stress.standard/1`

| Stress | Mechanics (fixed before outcomes) |
|---|---|
| Price shift | *a*′ = ceil_tick(*a* + δ), δ ∈ {0, 0.01, 0.02}. Each shifted price independently re-spends $1 gross and recomputes *q* and *f*. If *a*′ ≥ 1, the scenario is **unsupported**, not capped. |
| Same-fill cost reserve | Extra cost ρ·*q*, ρ ∈ {0, 0.01, 0.02}, on the original fill and fee. Labelled separately from the price shift. |
| Fee scenario | CTF and USD, both always reported. |

The primary stress is set at registration. The proposed default is a price shift of 0.01. Stress scenarios are never ranked against each other to pick a policy.

### 3.6 Minimum order, size and executability limits

- `min_share_feasibility` ∈ {`feasible_share_count_only`, `below_minimum_shares_hypothetical_fill_retained`, `unknown`}, computed per stress scenario.
- Example: at *a* = 0.50, *q* = 2 shares, which is below a 5-share minimum if that minimum applies (`compact_contract_v2.md`).
- **The main result keeps below-minimum fills** because the hypothetical $1 regime was explicitly authorized. They are never silently removed.
- A separate **minimum-compliant sensitivity** subset is reported only where the minimum's applicability to the order type is documented in the archived terms. Otherwise it is reported as "applicability undocumented".
- Compact BBO sizes are optional and never prove price-level executable size. REST ladders show displayed size at one snapshot only. Neither can upgrade a result to "executable".

### 3.7 Exits, payouts and evidence levels

- **Default exit:** hold to payout.
- **Optional early exit:** a preregistered exit clock, at the first observed own-bid cohort of the same token after that clock, with the same first-cohort/no-fallback rule. It stays disabled until the sell-side fee semantics are confirmed (decision D6).

**Payout grades (P)**

| Grade | Meaning | Allowed claims |
|---|---|---|
| P0 | Unknown or pending | Bounds only |
| P1 | Gamma final payout vector, binding-compatible (G1) | Conditional economic PnL labelled "conditional on Gamma payout vector" |
| P2 | Additionally literal rule-hash match (G2) | Same as P1, stricter |
| P3 | Independently verified on-chain payout or redemption (G3) | Cash release and realized-cash claims |

No P3 evidence exists. The brief states that 41 Gamma final payout vectors are not on-chain proofs **[fact]**. `core.Position.pnl_bounds` uses Gamma only when `allow_gamma_proxy` is set, and Gamma never unlocks cash (`core` `test_gamma_does_not_unlock_cash_g3_access_does`).

**Weather grades (W)**

| Grade | Meaning |
|---|---|
| W0 | No weather verification |
| W1 | Auxiliary METAR, which cannot replace the contractual maximum |
| W2 | Contractual resolution-source maximum verified |

W ≥ W2 is required **only** for claims that depend on weather truth, such as forecast-skill-versus-truth claims. Official-weather absence alone never blocks conditional economic analysis that uses P1+ payouts **[fact, brief]**.

### 3.8 Capital and risk ledger

- **Independent ledger** per (configuration × fee scenario × stress scenario × baseline). Each ledger is fully funded with a cap C. The proposed default is C = 1000 USD per ledger, the REST15 v3 precedent **[fact]**.
- **Admission:** chronological by entry time. Cash is reserved at entry. When the cap would be exceeded the entry is rejected with `capital_rejected` and counted. Ledgers never compete for capital.
- **No recycling:** cash is never released before P3 evidence exists (currently never). Locked capital therefore grows monotonically during a run.
- **Risk outputs:**
  - maximum locked capital;
  - maximum concurrent open positions;
  - per-date exposure;
  - worst-case loss, equal to total locked cash;
  - joint unknown-payout bounds from `core.complementary_joint_bounds` (independent conditions by default; complete geometry only when attested);
  - drawdown (§7.3).
- **Conservation:** every ledger asserts cash conservation and share conservation after each event. This reuses `core.Portfolio.assert_conservation` semantics, which raises an explicit exception rather than relying on `assert` (`test_conservation_guard_survives_optimized_python`).

### 3.9 Matched baselines

All baselines use the **same events, the same frozen entry cohort, the same execution model, the same fees and stress, and the same ledger cap** as the hypothesis arm.

| ID | Baseline | Matching rule |
|---|---|---|
| B0 | Cash / no trade | PnL 0, capital 0. A positive verdict requires beating it. |
| B1 | Mechanism control | The declared control that differs only in the mechanism element under test, for example `GEFS_control`, `five_family_control`, `regime_unimodal_control`, `memory_same_token_control` or `memory_no_reset_ablation`. These existing controls come from `R/protocol.json` and `S/protocol_rest15_v3.json`. |
| B2 | Matched random own ask (R = 200 draws) | In each event with a hypothesis decision, a seeded uniform choice among tokens tradable at the **same** entry cohort. It gives the distribution of the hypothesis's mean minus the random mean. The seed comes from the manifest. |
| B3 | Same-event favorite YES | Buy the own YES ask of the interval with the highest YES ask at the same entry cohort. This tests favorite/longshot effects. |

**Paired exclusions.** A pair counts only if both arms have a valid entry at the same cohort. Unpaired cases are reported per side with reasons. The headline paired difference uses matched pairs only. Unmatched totals are shown next to it, never instead of it.

**Fee and spread sensitivity.** Every baseline is reported over the full stress grid. The spread at entry (own ask − own bid) is reported as a distribution per arm.

### 3.10 Stress and sensitivity suite (reported every time)

1. Price-shift and reserve grid, both fee scenarios.
2. G2-only payouts compared with G1.
3. Minimum-compliant subset, where documented.
4. Leave-one-market-date-out: the maximum change in mean per-date net PnL, plus the share of total PnL coming from the top 1 and top 3 dates.
5. Worst-case unknown payouts: treat all P0 positions as losses.
6. Per-city and per-unit breakdown, descriptive only and never used for selection.

---

## 4. Leakage protection, splits and attempt control

### 4.1 Mechanical leakage controls

| Control | Mechanism |
|---|---|
| Future receipt or import | Adapter `as_of` filters by `available_at` (§2.1). Signal functions receive only an immutable as-of view (`core.freeze` → `MappingProxyType`). |
| Signal cutoff | Weather and metadata at signal − 5 s. Prices at ≤ signal. Strict mode requires the signal request ID and that trace records exist as of the cutoff (`core._guard_binding`, `input_cutoff`). |
| Payout sealing | The payout file is opened only after `selection.frozen.json` is written, hashed and journaled as `selection_frozen`. The payout file's hash is pinned in the manifest beforehand. Hashing a file does not read its content into the selection process, the same as `replay_rest15.main` and `R/freeze.py`. |
| Label features | Prior-outcome labels used as features (H4) must have receipt ≤ cutoff. Future grade status is never consulted (`run.historical_errors`). |
| Process state | Each attempt runs in a fresh process. Module-level caches such as `run.PERSISTENCE_FAMILY` and `PERSISTENCE_TRACE` must not survive between attempts. |
| Future-append invariance | Appending records received after the cutoff must not change any decision. This is tested (T-LEAK-2), mirroring `core` `test_future_append_execution_unchanged`. |

### 4.2 Split registry and date roles

A split is an immutable record:

`{split_id, created_at, rule, market_dates{role: [dates]}, embargo_days, source_adapter, sha256}`

- Market date is the station-local contract day.
- Roles: `development`, `train`, `validation`, `test`.
- A split cannot be edited. Changes create a new split ID.
- **Inspected-date ledger.** The registry derives `inspected_dates` from every record that put a date into any attempt's evaluation scope, payout join, report view or QA inspection.
- **Hard rules:**
  1. No date in `inspected_dates` may hold role `test` in any split created afterwards.
  2. All REST15, legacy-projection and H4 dates (2026-09-12 to 2026-10-06, of which 2026-09-26 to 2026-10-06 are decision dates **[fact]**) are permanently `development`.
  3. Compact-archive dates covered by the first daily audit and the post-r7 cohort check are marked `qa_inspected`. They default to non-test (decision D1).
- **Embargo:** at least 2 calendar days between consecutive partitions **[proposed]**. This covers T-1 decisions, resolution lag and label receipt.

### 4.3 Prospective split for the compact archive

`SPLIT-COMPACT-P1` **[proposed]** is registered **before** its dates occur:
- train = the first 21 eligible market dates after the registration date;
- embargo of 2 days;
- validation = the next 14 dates;
- embargo of 2 days;
- test = the next 28 dates.

"Eligible" means the date has an `expected_matrix` and is not wholly inside an excluded cohort window. Excluded dates stay in the denominator with reasons and are not replaced by later dates.

A hypothesis may claim **confirmatory** strength only if its registration time is earlier than the first test date's earliest signal time. The test partition is then untouched by construction.

### 4.4 Walk-forward

- Blocks are 7 market dates. The window expands. Before evaluating block *k*:
  - **fit:** select one configuration from the registered grid using blocks 1..*k*−1 under the registered selection rule;
  - **evaluate:** on block *k* with the frozen configuration;
  - **journal:** both the selection and the evaluation as stages.
- Mechanism-internal calibration, such as H4, updates only through as-of labels.
- Walk-forward outputs on train and validation are exploratory.
- Test evaluation uses the single configuration chosen on train plus validation.
- Fixed-parameter hypotheses (K = 1) skip fitting. Their walk-forward is a plain chronological evaluation.

### 4.5 Test access

- `hlab test-access request` journals a `test_access` record (hypothesis ID, revision, configuration, split ID) **before** test computation. Without it, `run` refuses any test partition with `test_access_not_recorded`.
- Access count per (family, split test partition):
  - 1 → eligible for confirmatory;
  - ≥ 2 → every later result is labelled exploratory with `test_reaccessed`.
- Changing the hypothesis after test access requires a new revision. The new revision cannot be confirmatory on the same test partition.

### 4.6 Retries and revisions

| Case | Handling |
|---|---|
| Mechanical failure: crash, timeout, transport, out of memory | Journal `attempt_finished{status:failed\|stopped}`. A retry is a **new** attempt with `retry_of` set. Outputs go to a new directory. Nothing is overwritten (`R/server_ops.py`, `S/run_ops_revision2.py` precedent: "preserve first mechanical attempt"). |
| Mechanical code correction after outputs were produced | New code hash and new attempt. A `correction_class` field is required: `mechanical` (no strategy parameter, window or threshold change), reviewed by a second agent or the operator, or `substantive`, which requires a new hypothesis revision. The diff hash is recorded. |
| Rerun with an identical manifest | Allowed only as `hlab verify`. It writes a verification record and must reproduce the stored digests. It never replaces the original. |
| Partial outputs | Kept, flagged `partial=true`, never used as results. |

### 4.7 Multiplicity and selective reporting

- **Family ledger:** for each family, count K_total, the sum of grid sizes over all registered revisions that reached any evaluation partition, plus arms. Report it with every result.
- **Confirmatory decision:** Holm correction across the family's confirmatory tests at α = 0.05 **[proposed]**, applied to one-sided date-cluster bootstrap p-values of the primary metric.
- **Exploratory results:** raw intervals plus the K_total disclosure. Never called "validated".
- **Global disclosure:** the report header lists the total attempts across all families in the registry at report time.
- **Selective-reporting guard:** `hlab report` renders every attempt of the family from the registry: planned, refused, failed, stopped, negative and positive. The report embeds the registry head hash. `hlab report --verify` fails if any family attempt is missing or if the head hash differs.
- **Best-result labelling:** a configuration selected on any partition is labelled `selected_on:<partition>`. Validation of a train-selected configuration is labelled `validation_after_selection`, never independent.

### 4.8 Uncertainty

- Unit: market date, so all events, cities and arms on that date are resampled together.
- Bootstrap: B = 2000, seed from the manifest (precedent in `R/run.py`: fixed seed, 2000 draws, at least 10 graded entry dates). Intervals are reported only when graded entry dates ≥ `min_dates_ci` (default 10). Otherwise the field reads `not_reported:fewer_than_10_graded_entry_dates`.
- Statistics: the mean per-date net PnL, and the ratio ROI = Σ PnL / Σ cash, both with 95% percentile intervals; plus a sign test on paired per-date differences.
- No p-value or interval is presented for development data as confirmatory.

---

## 5. CLI, schemas, manifests and registry

### 5.1 Commands (`python -m hlab …`)

| Command | Effect | Writes registry? |
|---|---|---|
| `hypothesis validate FILE` | Schema and semantic checks: grid finite, mechanism reference pinned, baselines exist. | no |
| `hypothesis register FILE` | Canonicalize, hash, append `hypothesis_registered`. | yes |
| `data freeze --adapter A --source DIR --asof T --out M.json` | Build the dataset manifest (§5.2). Refuse partial or mismatched inputs. | yes (`dataset_frozen`) |
| `suitability HYP@REV DATASET` | Suitability report. Payouts are never touched. | yes (`suitability_checked`) |
| `split create SPEC` | Validate against the inspected-date ledger. Append `split_created`. | yes |
| `plan HYP@REV --dataset D --split S --partition P --seed N --out RUN.json` | Resolve everything into a run manifest. Compute the attempt ID. | yes (`attempt_planned`) |
| `test-access request HYP@REV --split S --config C` | Journal test access intent. | yes |
| `run RUN.json [--resume]` | Run the stages (§5.5). | yes |
| `status ATTEMPT` / `stop ATTEMPT` | Local or remote, by attempt ID. | stop → yes |
| `verify ATTEMPT` | Re-execute from the manifest and compare digests. | yes (`verification`) |
| `report FAMILY --out FILE.md [--verify]` | Render from the registry and results. | yes (`report_rendered`) |
| `registry verify` | Check the hash chain, sequence and schema. | no |
| `remote stage\|launch\|status\|stop\|retrieve\|cleanup ATTEMPT` | Runner operations (§6). | yes |

Exit codes: `0` ok · `2` invalid input or schema · `3` refused (suitability or policy) · `4` integrity mismatch · `5` budget stop · `6` registry conflict · `1` other failure. Every non-zero exit after `attempt_planned` still journals `attempt_finished` with its status.

### 5.2 Dataset manifest `hlab.dataset/1`

```json
{
  "schema": "hlab.dataset/1",
  "adapter": {"id": "rest15", "version": "1", "module_sha256": "<sha256>"},
  "asof_cutoff_utc": "2026-10-07T18:00:00Z",
  "files": [{"rel_path": "evidence.sqlite3", "bytes": 0, "sha256": "<sha256>", "role": "normalized_projection"},
            {"rel_path": "metadata.index.sqlite3", "bytes": 0, "sha256": "<sha256>", "role": "id_catalogue_not_values"},
            {"rel_path": "payout.events.json", "bytes": 0, "sha256": "<sha256>", "role": "sealed_payouts"}],
  "lineage": [{"producer": "extract.py", "producer_sha256": "bd24a6f3…c113", "complete_flag": false}],
  "clock_semantics": {"receipt": "per_request", "first_receipt": "equals_receipt", "import": "absent",
                      "publication": "exchange_timestamp_unknown_semantics", "model_time": "not_proven"},
  "coverage": {"windows_local": ["T-1 12:00-13:20", "T-1 18:00-19:20"], "archive_window_complete": false},
  "limitations": ["not_full_orderbook_history", "retained_subset", "rest_not_minute_grid"],
  "date_roles_forced": "development",
  "independent_test_eligible": false
}
```

The `extract.py` producer hash shown is the snapshot hash of `R/extract.py` **[fact]**. All other hashes are placeholders.

### 5.3 Run manifest `hlab.run/1`

```json
{
  "schema": "hlab.run/1",
  "attempt_id": "att-<16hex>",
  "hypothesis": {"id": "FREV-01", "revision": 1, "sha256": "<sha256>"},
  "code": {"git_commit": "<40hex>", "files": {"hlab/execution.py": "<sha256>", "small_order_rest_v3.py": "ab9c0f03…5c6d", "signals.py": "27afe631…bfe"}},
  "deps": {"python": "3.11.x", "lock_sha256": "<sha256>", "pyarrow": "<version>", "numpy": "<version>"},
  "data": {"dataset_manifest_sha256": "<sha256>", "adapter": "rest15@1", "asof_cutoff_utc": "2026-10-07T18:00:00Z"},
  "parameters": {"resolved": {"arms": ["single", "common"]}, "grid": null},
  "seed": 1062,
  "split": {"split_id": "SPLIT-LEGACY-DEV-1", "sha256": "<sha256>", "partition": "development", "dates_sha256": "<sha256>"},
  "engine": {"execution": "small_order_rest_v3.simulate_one_dollar", "regime": "one_dollar_native_REST_sequential_sweep_v3"},
  "evidence_level": {"payout_min": "P1", "weather": "W0"},
  "resource_bounds_proposed": {"processes": 1, "cpu_threads": 1, "memory_bytes": 2147483648, "wall_seconds": 600, "output_bytes": 1073741824, "free_disk_floor_bytes": 20000000000},
  "retry_of": null, "correction_class": null,
  "created_at": "<informational, excluded from attempt_id>"
}
```

`attempt_id = "att-" + sha256(canonical(manifest minus {attempt_id, created_at}))[:16]`. Identical content gives an identical ID, so planning the same manifest twice is a duplicate and the second plan is journaled as a `verify` intent, not a new attempt. The two engine hashes shown are snapshot prefixes of `S/small_order_rest_v3.py` and `R/signals.py` **[fact]**.

### 5.4 Append-only attempt registry `hlab.registry/1`

- Format: JSON Lines. Each record is `{seq, prev_hash, kind, attempt_id|null, payload, payload_sha256, record_hash}`, where `record_hash = sha256(canonical(record minus record_hash))`. The first record has `prev_hash = 64×"0"`.
- Kinds: `hypothesis_registered`, `split_created`, `dataset_frozen`, `suitability_checked`, `attempt_planned`, `attempt_started`, `stage_committed{stage, output_sha256}`, `selection_frozen{sha256}`, `evaluation_opened{payout_file_sha256}`, `test_access`, `attempt_finished{status: ok|failed|stopped|refused|budget_stop, result_digest|null}`, `verification{match: bool}`, `report_rendered{report_sha256, registry_head}`, `annotation` (corrections are annotations; nothing is deleted).
- Writes: one writer at a time under an exclusive lock file. Open with append mode and fsync. Before appending, verify the tail hash. On conflict exit 6.
- Location: canonical copy in the private research repository (decision D8). The runner keeps an attempt-local delta that is merged by `remote retrieve`. The merge verifies chain continuity and refuses forks.
- Guarantees: re-running cannot overwrite history because attempt directories are content-addressed and creation refuses an existing path. Deletions or edits are detected by `registry verify`.

### 5.5 Determinism and recoverability

- **Arithmetic:** `Decimal`, precision 50, in accounting (as the pinned engines already do). Results are serialized as decimal strings. No float in economic outputs.
- **Ordering:** every iteration is over sorted keys, using the engines' existing ordering conventions such as (received, id) and (target, event).
- **Randomness:** only B2 and the bootstrap, both seeded from the manifest seed through named sub-streams, for example `sha256(seed‖"B2"‖event)`.
- **Single thread:** `OMP_NUM_THREADS=1`, `pyarrow.set_cpu_count(1)` and `set_io_thread_count(1)` (as in `R/extract.py`).
- **Result digest:** `sha256` over canonical {census, selection, executions, ledgers, baselines, stats, verdict}. Wall-clock, elapsed time and host facts live in a separate `envelope.json` excluded from the digest.
- **Stages:** `preflight → snapshot_verify → census_and_signals → selection_freeze → evaluation_join → baselines → statistics → report_artifacts`.
  - Each stage writes to a temporary file, fsyncs and renames atomically, then journals `stage_committed` with the output hash.
  - `--resume` restarts at the first uncommitted stage after re-verifying all prior stage hashes and input hashes. Any mismatch exits 4.
  - `selection.frozen.json` is immutable once committed. Resume never recomputes it (`replay_rest15` precedent: refuse if it already exists).

### 5.6 Illustrated run (not executed)

Command sequence, shown for illustration only:

```text
hlab hypothesis register hypotheses/FREV-01.r1.json
hlab data freeze --adapter rest15 --source <RESEARCH_ROOT>/inputs/rest15-v3 --asof 2026-10-07T18:00:00Z --out datasets/rest15-dev.json
hlab split create splits/SPLIT-LEGACY-DEV-1.json
hlab suitability FREV-01@1 datasets/rest15-dev.json        # -> suitable_with_label: development_only, retained_subset, rest_cadence
hlab plan FREV-01@1 --dataset datasets/rest15-dev.json --split SPLIT-LEGACY-DEV-1 --partition development --seed 1062 --out plans/frev01.json
hlab remote stage att-<id> && hlab remote launch att-<id>
hlab remote status att-<id>
hlab remote retrieve att-<id> && hlab verify att-<id>
hlab report forecast_revision --out reports/forecast_revision.md --verify
```

Below is the shape of `result.json`. It uses **[synthetic]** values from the §3.3 fixture: one entry, one date, P1 payout π = 1. It does not describe any real data.

```json
{
  "attempt_id": "att-<id>", "hypothesis": "FREV-01@1", "partition": "development",
  "strength": "exploratory", "strength_reasons": ["development_only_dates", "independent_test_dates=0"],
  "census": {"population": 1, "skipped": {}, "decisions": 1, "entries": 1, "rejected": {}},
  "economics": {"ask_plus_0": {"USD": {"gross_notional": "1", "cash_outlay": "1.03", "fees": "0.03", "gross_pnl": "1.50", "net_pnl": "1.47"},
                               "CTF": {"gross_notional": "1", "cash_outlay": "1", "fees_shares": "0.075", "gross_pnl": "1.50", "net_pnl": "1.425"}}},
  "dates_with_graded_entries": 1,
  "uncertainty": "not_reported:fewer_than_10_graded_entry_dates",
  "verdict": "INSUFFICIENT_DATA",
  "labels": ["conditional_full_fill", "payout_P1_gamma_not_onchain", "min_share_feasibility:below_minimum_shares_hypothetical_fill_retained"],
  "result_digest": "<sha256>"
}
```

---

## 6. Hetzner runner design (research only)

### 6.1 Principles

- Uses only the existing SSH path and the existing research Python environment. No install, no new daemon, no timer, no unit enable, no collector or quota change.
- Host, user and key are read from an untracked local configuration and never written to the repository or to reports. The current `R/server_ops.py` hard-codes them; the `hlab` remote module MUST NOT.
- Inputs are a **research-only snapshot**: hash-verified read-only references (symlinks, or copies for small files) to the frozen inputs, inside a new attempt directory under `<RESEARCH_ROOT>/hlab/`. `<ARCHIVE_ROOT>` is never opened for writing.
- Bulk data stays on the server. Only small derived artifacts return.

### 6.2 Attempt directory layout

```text
<RESEARCH_ROOT>/hlab/<attempt_id>/
  inputs/        read-only references + inputs.verified.json (hashes re-checked at preflight)
  code/          pinned sources + code.verified.json
  scratch/       temporary; the only subtree cleanup may remove
  out/           stage outputs, selection.frozen.json, result.json, report artifacts
  receipts/      preflight.json, resources.measured.json, operations.close.json, registry.delta.jsonl
  RUNNING | FINISHED   marker files (atomic)
```

Creation refuses an existing directory. A retry is a new attempt ID (§4.6).

### 6.3 Bounds: proposed versus measured

| Bound | Initial smoke, **proposed** | How enforced | Measured |
|---|---|---|---|
| Processes | 1 | Single-process runner. No multiprocessing import. Tasks limit | **none yet** |
| CPU | 1 thread | CPU quota 100% of one CPU, pinned to one CPU, single-thread library settings | **none yet** |
| Memory | 2 GiB | cgroup memory maximum 2 GiB, swap 0; fallback address-space rlimit 2 GiB (`S/run_ops_revision2.py` precedent) | **none yet** |
| Wall time | 10 min | Runtime limit 600 s plus in-process monotonic guard | **none yet** |
| Output | 1 GiB | In-process write accounting plus a periodic directory-size guard (`R/extract.py` style) → budget stop | **none yet** |
| Free disk floor | ≥ 20 GB free on the research filesystem | Checked at preflight, every guard tick and before each stage commit → budget stop | **none yet** |
| Production health | Collector health file fresh (< 150 s), not stopped, queue < 1000 | Checked at preflight and each guard tick (`R/extract.py`, `S/target_metadata.py` precedent) → abort | **none yet** |
| Priority | lowest CPU niceness, idle IO class | Process attributes | n/a |

Prior bounds used in earlier work were 1 CPU, 2 GB and 30-minute jobs (`R/protocol.json` `operations`), and a REST15 target phase of ≤ 180 s (`protocol_rest15_v3.json`) **[fact]**. These are precedents for **different code**. They are not measurements of `hlab`.

After every run, `resources.measured.json` records:
- start and end (UTC), elapsed monotonic seconds, CPU user and system seconds;
- peak memory (cgroup peak, or `ru_maxrss` in fallback mode), output bytes, free bytes before and after;
- exit status and termination cause.

Reports quote only this file for "measured".

### 6.4 Launch

1. `remote stage`:
   - create the attempt directory (refuse if it exists);
   - upload the pinned code and manifests;
   - verify all hashes remotely;
   - write `preflight.json` (health, free disk, Python version, dependency versions; a missing dependency refuses with `dependency_missing`, never installs);
   - run the synthetic unit tests from `code/` and record their exit code (`run_ops_revision2` precedent). Failure refuses launch.
2. `remote launch`:
   - preferred: start a **transient** resource-limited unit named `wea-hlab-<attempt_id>` with no restart, no timer and no enable, read-only paths for inputs and archive, and read-write only for `out/`, `scratch/` and `receipts/`. This mirrors the transient-unit precedent in `R/server_ops.py`.
   - fallback when the operator rules that transient units count as scheduler mutation (decision D2): a foreground process under a timeout with rlimits, CPU affinity and niceness.
3. The runner writes `RUNNING` with a PID and a heartbeat file updated each guard tick, at most every 10 s.

### 6.5 Status, stop and cleanup

- **`remote status`** is read-only. It reports the unit or process state, the last heartbeat age, the last committed stage, partial output bytes and free disk. A heartbeat older than 60 s while running is reported as `stale_heartbeat`.
- **`remote stop`** sends SIGTERM, then SIGKILL after a 20 s grace period. Only the attempt's own unit or PID is targeted, verified by name prefix and recorded PID. The runner journals `attempt_finished{status: stopped}`. Partial outputs stay in place and are flagged `partial=true`.
- **`remote cleanup`**:
  - allowed only after a `FINISHED` or stopped status **and** a successful `retrieve` whose receipts' hashes are in the registry;
  - removes only `<attempt>/scratch/`, after the resolved path is checked to be inside `<RESEARCH_ROOT>/hlab/<attempt_id>/`;
  - never touches `inputs/`, `code/`, `out/`, `receipts/`, other attempts, the archive or collector paths;
  - whole-directory removal is not a command; it requires an explicit operator decision (D11).
- **Close receipt** (`operations.close.json`, `S/close_ops.py` precedent): collector service state, operational hash comparison (unchanged), the absence of leftover `hlab` processes, and `no_real_trading=true`.

### 6.6 Retrieval

`remote retrieve` copies back:
- `result.json`, `envelope.json` and the census;
- `selection.frozen.json`, `executions.json`, `report.md`;
- the receipts and `registry.delta.jsonl`.

It verifies the hashes and merges the registry delta (§5.4). Large intermediates stay on the server.

### 6.7 When a bound is insufficient

The attempt ends with `budget_stop:<bound>`, is journaled and keeps its partial outputs. `hlab` then writes a `bound_revision_proposal` annotation: the observed value at the stop, the proposed new bound and a justification. Bounds are never raised automatically. A higher bound requires an operator decision and a new manifest, which means a new attempt ID.

---

## 7. Report

### 7.1 Verdict rules (computed, never hand-set)

Evaluated in order for the primary configuration and partition:

1. **INSUFFICIENT_DATA** if any of the following holds:
   - the run was refused;
   - graded entry dates < `min_dates_ci` (10), or for confirmatory runs < `min_dates_confirmatory` (20);
   - graded fraction of entries < `min_graded_fraction` (0.8);
   - required evidence is missing (for example P1 not reached, or W2 required and absent).
   The report states which condition triggered.
2. **POSITIVE_SIGNAL** if all of the following hold, for **both** CTF and USD scenarios at the primary stress:
   - (a) the lower 95% date-cluster bound of the mean per-date net PnL is > 0 versus B0 cash;
   - (b) the mean per-date paired difference versus the primary control has a point estimate > 0 (decision D3: whether its lower bound must also be > 0);
   - (c) for confirmatory runs, the Holm-adjusted p-value ≤ α within the family.
3. **NEGATIVE_RESULT** otherwise. Subtype `significantly_negative` when the upper 95% bound versus cash is < 0, else `no_detectable_edge`.

A POSITIVE_SIGNAL is evidence for a hypothesis under conditional assumptions. It is not a profitability claim.

### 7.2 Strength labels

| Label | Requires |
|---|---|
| **confirmatory** | test partition; split registered prospectively; hypothesis registered before the first test signal; single test access; no deviations; multiplicity applied |
| **exploratory** | anything else, with every reason listed (`development_only_dates`, `validation_after_selection`, `test_reaccessed`, `mechanical_correction`, `retained_subset`, `single_day`, …) |

REST15, legacy and H4 results are always exploratory with `independent_test_dates=0`. A result covering one day can never establish profitability **[fact, approved proposal]**.

### 7.3 Required content and definitions

| Section | Content |
|---|---|
| Header | Family, hypothesis and revision, attempt IDs, registry head hash, manifest hash, code commit, dataset hash, split and partition, evidence levels, verdict, strength and its reasons |
| Census | Population; skips by code; decisions; entries; rejections by code; equality checks (§2.10) |
| Counts | Events, market dates, trades, cities, intervals; entries per date (distribution) |
| Economics (per fee × stress) | Gross notional = $1 × trades. Cash outlay. Fees (USD, or share-equivalent for CTF). Gross payout. **Gross PnL** = payout − gross notional (before fees). **Net PnL** = payout − cash outlay − reserves. |
| ROI (all three denominators shown) | Net PnL / Σ gross notional · Net PnL / Σ cash outlay · Net PnL / peak locked capital. The headline names its denominator. |
| Risk | Maximum locked capital; maximum concurrent positions; worst-case loss; joint unknown bounds; **maximum drawdown** of cumulative realized net PnL ordered by payout availability time (ties broken by event ID), plus the worst single date |
| Uncertainty | 95% date-cluster intervals or the not-reported reason; sign test on paired dates; K_total and the correction applied |
| Baselines | B0–B3 side by side with paired counts, paired differences and paired exclusions |
| Stress suite | §3.10 grid, minimum-compliant subset, G2-only, leave-one-date-out, top-date concentration |
| Data quality | Matrix planned / recorded / valid / tradable / unknown counts; gaps; reconnects; carried-forward cells; cohort-window exclusions; transition refusals; metadata changes; fee or terms refusals |
| Attempts | Table of **every** family attempt with status, partition, configuration, verdict and digest, including failures and refusals |
| Limitations (always present) | Conditional full fill is not liquidity; Gamma vectors are not on-chain proofs; no weather certification unless W2; REST sweeps are not minute quotes; legacy projection is not full depth; the r7 transition is unobserved; development-only dates; fee rounding not exchange-verified; no profit promise |

### 7.4 Template skeleton

```text
# <family> — <hypothesis>@<rev> — VERDICT (<strength>)
Registry head <hash> · Manifest <hash> · Code <commit> · Data <hash> · Split <id>/<partition>
## 1 Verdict basis (rule evaluated, thresholds, which condition decided)
## 2 Census and counts
## 3 Economics by fee scenario and stress (gross, net, fees, three ROI denominators)
## 4 Risk and capital
## 5 Uncertainty and multiplicity
## 6 Matched baselines
## 7 Stress and sensitivity
## 8 Data quality and refusals
## 9 All attempts in this family
## 10 Limitations
```

### 7.5 Metric gaming notes

| Metric | Intent | Known escapes or gaming | Countermeasure |
|---|---|---|---|
| Mean per-date net PnL | Edge per market date, clustered | Dropping bad dates; favorable subsets | Census equality; paired exclusions shown; all dates are in the split |
| ROI | Capital efficiency | Picking a flattering denominator | All three denominators are mandatory |
| Entry count | Opportunity rate | Loosening the window or adding fallback | Window fixed in the schema; no-fallback engine |
| Graded fraction | Label coverage | Joining weaker grades | Grade per row; G2-only sensitivity |
| Coverage counts | Data health | Counting duplicate rows or empty cells as recorded | `compact_matrix` unique-cell counting; empty counted as unavailable |

---

## 8. Reuse, migration, tests and decisions

### 8.1 Reuse map

| Existing file | Role in `hlab` | Change |
|---|---|---|
| `R/small_order.py` | Minute-mode $1 entry and accounting | Pinned and called. None. |
| `S/small_order_rest_v3.py` | REST-sweep $1 entry and accounting | Pinned and called. None. |
| `R/core.py` | Records, as-of view, payout grades, conservation, joint bounds, native bins, local day | Pinned. Used as a library. `ReplayEngine` is kept only for depth-mode equivalence. |
| `R/signals.py` | All mechanisms | Pinned. Referenced through `mechanism_ref` hashes. |
| `R/run.py` | Mechanism glue (`forecasts`, `probabilities`, `best_gap`, `two_regime` wiring, H4 calibration) | **Wrapped**: the pure helpers are imported, `main()` is never called, and the module runs in a fresh process per attempt to avoid global cache leaks. |
| `S/replay_rest15.py` | REST15 v3 population, sweeps, identity checks, metadata forwarding | **Wrapped** helpers (`cluster`, `first_sweep`, `native_markets`, `metadata`, `sweep`, `forward_metadata`, `identity_matches`). `main()` is used only in the equivalence fixture. |
| `R/adapter.py` | Read-only evidence access | Pinned. Used by `rest15` and `legacy_projection`. |
| `R/compact_matrix.py` | Matrix acceptance | Pinned. Used by `compact_v2.freeze`. |
| `src/compact_replay.py` | Compact as-of state | Used for bindings, fees, terms and expected matrix only (§2.8). Needs `src.server_store.packed` (prerequisite risk). |
| `R/skill_metrics.py` | Census diagnostic | Pinned. Report appendix. |
| `R/available_coverage.py` | Closed-DB sufficiency precedent | Logic folded into suitability counts. Not called. |
| `R/extract.py`, `S/target_metadata.py`, `S/build_index.py` | Producers of existing inputs | Not re-run. Hashes recorded in dataset lineage. |
| `R/freeze.py`, `R/server_ops.py`, `S/run_ops_revision2.py`, `S/close_ops.py` | Operational precedents | Re-implemented in `hlab/remote.py` without hard-coded host or key, with registry integration. Originals untouched. |
| `src/server_replay.py` | WS L2 depth replay | Out of scope. Not imported. |
| Protocol JSONs | Historical registrations | Imported as hypothesis revisions with `origin=legacy_protocol` and hash links. Never edited. |

### 8.2 Smallest practical module structure (new code only)

```text
hlab/
  __main__.py      CLI dispatch (argparse)
  schema.py        hypothesis/dataset/run/registry schemas + canonical JSON + hashing
  registry.py      hash-chained append-only journal, lock, verify, inspected-date ledger
  adapters/
    base.py        interface, clocks, OwnQuote, refusal codes
    rest15.py      wraps replay_rest15 helpers + small_order_rest_v3
    legacy.py      legacy_projection + legacy_h4
    compact.py     wraps CompactAsOf + compact_matrix + small_order
  execution.py     decision→entry→accounting via pinned engines; ledgers; baselines
  evaluate.py      splits, walk-forward, bootstrap, Holm, verdicts
  report.py        Markdown renderer + --verify
  remote.py        stage/launch/status/stop/retrieve/cleanup; local untracked config
  vendor/          pinned copies of the reused files + vendor.lock.json (sha256 per file)
tests/             see §8.6
```

The new code is estimated at roughly 2–3 kLOC **[proposed]**. All economics and mechanisms stay in pinned vendor code.

### 8.3 Dependency and prerequisite risks

| Risk | Evidence | Mitigation |
|---|---|---|
| Missing modules | `src/compact_replay.py` imports `src.server_store`; `src/server_replay.py` imports `src.continuous_weather`. Neither is in the snapshot. | Stage S0 must supply `server_store.packed` with a hash, or `hlab` provides a canonical-JSON equivalent proven equal by a test on fixtures. `server_replay` is excluded. |
| Import layout | REST15 tests insert a sibling `engine` directory on `sys.path`. `small_order_rest_v3` uses a flat `from small_order import …`. | `vendor/` keeps the flat layout. The test runner sets `sys.path` explicitly. |
| Python version | `hashlib.file_digest` needs 3.11+, while wea_ther `AGENTS.md` states 3.10+. | Require ≥ 3.11 on the runner, recorded at preflight (decision D10). |
| Global state | `run.PERSISTENCE_FAMILY` / `PERSISTENCE_TRACE` | One attempt per fresh process. Test T-REP-3. |
| Hard-coded server paths | `run.py` and `replay_rest15.py` constants | Wrappers never call `main()`. Paths come from the dataset manifest. |
| Optional numpy | `run.py` bootstrap | `hlab` bootstrap is pure Python with Decimal and a seeded PRNG, so results do not depend on the numpy version. |
| Partial extraction | `data_contract.md`: first phase partial | `legacy_projection` refusal rules (§2.7). |
| Credentials in an existing helper | `R/server_ops.py` contains literal connection details | Not reused. Local untracked config only. Publication scan (T-PUB-1). |

### 8.4 Backward compatibility and equivalence

1. **Pinned unit tests.** All existing `test_*.py` files in `R/` and `S/` run unchanged against `vendor/`. A vendor hash mismatch fails the build.
2. **REST15 v3 equivalence (development, later authorized run).** Run `FREV-01` and the GEFS and five-family controls through `hlab` `rest15` on the same frozen inputs. The canonical selection (decision list, side, token, probability, entry reasons) and the per-arm scenario-portfolio numbers must equal the existing v3 `selection.frozen.json` / `summary.json` field by field. Field-naming differences go through a documented mapping table. Any numeric difference fails.
3. **Compact differential.** On synthetic fixtures, `CompactAsOf.buy_one_dollar` and `small_order.simulate_one_dollar` agree on price, shares, fee and scenarios where both accept. Cases where only `simulate_one_dollar` rejects (validated-age, carried-forward, intervening gap) are enumerated and expected.
4. **Depth mode untouched.** `core.ReplayEngine` keeps its 25-share / 10% depth semantics for historical reproduction only. `hlab` never mixes its outputs into $1 reports.

### 8.5 Staged implementation plan (each stage needs separate authorization)

| Stage | Scope | Acceptance |
|---|---|---|
| S0 | Operator decisions D1–D12; supply `server_store.packed` or approve the equivalent; confirm the runner Python version | Decisions journaled as annotations |
| S1 | `schema`, `registry`, CLI skeleton, vendor lock, pinned tests passing locally | T-REG-*, T-SCH-*, pinned tests green; synthetic only |
| S2 | Adapters with clocks, refusal taxonomy, suitability; synthetic fixtures for all three adapters | T-CLK-*, T-LEAK-*, T-NO-*, T-GAP-*, T-COH-*, T-REF-* green |
| S3 | Execution, ledgers, baselines | T-FEE-*, T-ENT-*, T-PAY-*, T-BASE-*, T-CAP-* green; §3.3 synthetic arithmetic reproduced exactly |
| S4 | Evaluation, splits, report, verify | T-SPL-*, T-VER-*, T-REP-*, T-RPT-* green |
| S5 | `remote` module; **one smoke** within §6.3 bounds on the server: REST15 equivalence, development only | Equivalence holds; `resources.measured.json` recorded; close receipt shows no collector mutation; or a reported bound-revision proposal |
| S6 | Register `SPLIT-COMPACT-P1` prospectively, plus compact hypotheses before their train dates | Registry shows split and hypothesis registration earlier than the first train signal |
| S7 | Independent review: reproduce the economic results, inspect holdout and selection provenance, verify no collector mutation, name the exact reviewed commit | Review record in the registry |

### 8.6 Test plan

All tests use synthetic data only, unless marked [server-fixture].

| Area | ID | Test |
|---|---|---|
| Clocks | T-CLK-1 | `available_at` = max(receipt, first receipt, import). A record with import > decision is invisible even when receipt < decision. |
| | T-CLK-2 | `publication_time` > receipt rejects. Old `last_price_change` time with a healthy heartbeat is accepted, and its source time is not rewritten. |
| | T-CLK-3 | DST local-day mapping for both hemispheres (extends `test_new_zealand_dst_local_day_clock`). |
| | T-CLK-4 | Model time is never used for freshness. A changed array first seen 59 minutes before the signal fails one-hour persistence. A→B→A restarts the origin. |
| Future leakage | T-LEAK-1 | A signal function given an as-of view cannot reach records with `available_at` > cutoff. Attribute mutation raises. |
| | T-LEAK-2 | Appending any number of records after the cutoff, including a payout, leaves the selection digest unchanged. |
| | T-LEAK-3 | The payout store raises before `selection_frozen` is journaled. Opening it afterwards records `evaluation_opened` with the hash. |
| | T-LEAK-4 | An H4 label received after the cutoff is excluded. A future grade is never consulted. |
| Own-side NO | T-NO-1 | A market where NO ask ≠ 1 − YES bid: execution uses the NO token's own ask (extends `test_no_token_uses_its_own_ask…`). |
| | T-NO-2 | A missing NO book gives an unavailable decision, never a priced one. A source scan finds no `1 -` complement pricing in `hlab`. |
| Fees and terms | T-FEE-1 | Handwritten fixture: *a* = 0.40, *r* = 0.05 gives USD cash 1.03 and CTF shares 2.425. |
| | T-FEE-2 | Unknown fee, exponent ≠ 1, rate disagreement, stale fee (> 21600 s) and stale terms each reject with their code. |
| | T-FEE-3 | Price stress rounds up to tick. Stressed ask ≥ 1 is unsupported. Each stress re-spends $1. |
| Gaps | T-GAP-1 | A gap between signal and entry on the chosen token rejects, even when the entry itself is clean. |
| | T-GAP-2 | Missing, gap and observed-empty are classified distinctly. Duplicate rows cannot inflate coverage. |
| Cohorts | T-COH-1 | Skew > 5 s rejects. An epoch change rejects. |
| | T-COH-2 | Decisions in the registered pre-r7 excluded minutes are skipped with `known_invalid_cohort_window`. |
| | T-COH-3 | Signal→entry crossing a revision boundary rejects with `unverified_cohort_transition` until an observed-transition record exists. Unregistered revision refuses. |
| Payouts | T-PAY-1 | G1 requires binding-field equality; G2 also requires the literal rule hash; a mismatch gives unknown. |
| | T-PAY-2 | Gamma never releases cash. Unknown bounds stay [−cash, shares − cash]. Joint bounds use complementary conditions. |
| | T-PAY-3 | W0 does not block P1 conditional PnL. A W2-required hypothesis without W2 gives INSUFFICIENT_DATA. |
| First entry | T-ENT-1 | A bad first cohort followed by a good cheap cohort gives a reject, with the first cohort's ID recorded. |
| | T-ENT-2 | A REST first sweep ending after +1200 s rejects without substitution. Boundary cases at +60 s and +1200 s. |
| | T-ENT-3 | One attempt per (configuration, event). A rejected attempt blocks retry. |
| Splits | T-SPL-1 | Creating a split with an inspected or development date in `test` fails. |
| | T-SPL-2 | Embargo enforced. A split record cannot be edited (hash mismatch is detected). |
| | T-SPL-3 | Confirmatory label requires prospective registration and single test access. A second access downgrades. |
| Attempt journal | T-REG-1 | Truncation, reordering, edits or a forked tail are detected by `registry verify`. |
| | T-REG-2 | Planning an existing attempt ID cannot create a new attempt. An existing attempt directory refuses creation. |
| | T-REG-3 | A failed, stopped or refused run still journals `attempt_finished`. |
| | T-REG-4 | The report omits no family attempt; `--verify` fails on omission. |
| Baseline arithmetic | T-BASE-1 | Handwritten B0/B1/B3 paired differences on a three-date fixture, including one unpaired exclusion. |
| | T-BASE-2 | B2 with a fixed seed is reproducible. A different seed changes only B2 and the bootstrap. |
| Capital | T-CAP-1 | Ledger cap rejection is chronological and counted. Conservation holds after each event. |
| Reproducibility | T-REP-1 | Running the same manifest twice gives an identical `result_digest`. |
| | T-REP-2 | Resuming after a kill between stages gives the same digest as an uninterrupted run. A tampered stage output exits 4. |
| | T-REP-3 | Two attempts in one interpreter are forbidden. In fresh processes, earlier attempts do not affect later ones (no global cache leak). |
| Refusal classification | T-REF-1 | Every refusal, skip and reject code is reachable by a fixture. Census equalities hold. |
| | T-REF-2 | REST15 + minute path hypothesis refuses `rest_not_minute_grid` with no computation. Partial legacy + completeness claim refuses. |
| Verdicts | T-VER-1 | Fixtures for INSUFFICIENT (9 dates), NEGATIVE (upper bound < 0) and POSITIVE (both fee scenarios pass). One date is never positive. |
| Equivalence | T-EQ-1 [server-fixture] | REST15 v3 equivalence (§8.4.2). |
| | T-EQ-2 | Compact differential (§8.4.3). |
| | T-EQ-3 | Pinned legacy tests pass unchanged. |
| Publication | T-PUB-1 | Generated reports and manifests contain no host, address, key path or credential pattern. |

### 8.7 Decisions requiring operator resolution

| ID | Decision | Proposed default |
|---|---|---|
| D1 | Are QA-inspected compact dates (first daily audit, post-r7 single-cohort check) eligible for test? | No. Development only. |
| D2 | Does a transient, non-persistent resource-limited unit count as scheduler mutation? | Allowed if transient, with no timer or enable; otherwise use the rlimit fallback. |
| D3 | Must the paired difference versus the primary control also be statistically positive for POSITIVE_SIGNAL? | Point estimate > 0, interval reported. |
| D4 | Confirmatory minimum test dates and test-window length | 20 graded entry dates within a 28-date test partition. |
| D5 | Ledger cap per (configuration × fee × stress) | 1000 USD (REST15 v3 precedent). |
| D6 | Sell-side fee semantics and enabling early exits | Disabled. Hold to payout only. |
| D7 | Include H4 on the 640 preserved inputs at all? | Yes, development only, exploratory. |
| D8 | Canonical registry location and who may append | Private research repo. The runner delta is merged on retrieve. One writer. |
| D9 | Promote the minimum-compliant subset to primary where minimum applicability is documented? | No. It stays secondary and the hypothetical $1 fill stays primary. |
| D10 | Runner Python version | ≥ 3.11 required; refuse otherwise. |
| D11 | Retention and removal of whole attempt directories | Keep indefinitely. Scratch only is removable by command. |
| D12 | Primary payout grade | P1 (G1) primary, with G2 sensitivity always shown. |

---

## 9. Concrete tradeoffs

1. **Pinning engines and wrapping them, rather than refactoring.** Equivalence is guaranteed and the review surface is small. The cost is awkward glue around `run.py` / `replay_rest15.py` globals and hard-coded paths, and a fresh process per attempt.
2. **Refusing rather than repairing.** REST15 cannot support minute-path hypotheses. The legacy projection cannot support population claims. This yields many refusals and small usable populations, but every number is defensible.
3. **Hypothetical $1 full fill as the primary metric.** It is comparable across adapters and matches the user-selected regime. It overstates executability where prices are above 0.20 and a 5-share minimum applies. That is mitigated only by labels and the minimum-compliant sensitivity.
4. **Prospective splits.** They give a genuinely untouched test. The cost is calendar time, since roughly one market date accrues per day, so confirmatory verdicts take months and most early verdicts will be INSUFFICIENT_DATA.
5. **Date-cluster bootstrap with a minimum of 10 or 20 dates.** It is honest about correlation, at the price of low power. Cities on one date are not counted as independent samples.
6. **Content-addressed attempts and a hash-chained JSONL registry.** It is simple and auditable without a database. The cost is single-writer coordination and manual delta merges.
7. **Transient unit versus rlimit.** The cgroup gives accurate memory and CPU enforcement and measurement. Rlimits avoid any unit creation but measure memory less precisely (`ru_maxrss` is not the cgroup peak).

## 10. Three strongest risks

1. **Insufficient sample.** With all historical dates development-only and about 41 Gamma payout vectors in the compact era **[fact]**, the framework will output INSUFFICIENT_DATA for weeks or months. There is pressure to relax splits or reuse dates. Mitigation: the registry refuses this mechanically (T-SPL-1, T-SPL-3), and the verdict thresholds are fixed at registration.
2. **The conditional-fill gap and quote integrity.** $1 fills at the observed ask may not be realizable (minimum size, queue, impact). The unobserved r7 cohort transition could also hide systematic quote errors. A POSITIVE_SIGNAL could therefore be an artifact. Mitigation: mandatory labels, the stress grid, refusal of transition-crossing decisions, and the minimum-compliant subset. The risk stays material until real execution evidence exists, which is outside this scope.
3. **Payout evidence quality.** Gamma final payout vectors are proxies, not on-chain proof, and are correlated within a date. Systematic label errors would bias every hypothesis in the same direction. Mitigation: P-grade labelling, G2 sensitivity, no cash release, unknown bounds reported. Weather-dependent claims require W2.

## 11. How this design can be falsified

The design is wrong, and must be revised before implementation proceeds, if any of these observations occurs:

1. Running the REST15 v3 protocol through the `hlab` `rest15` adapter on identical frozen inputs does **not** reproduce the existing selection and per-arm portfolio numbers field by field (T-EQ-1).
2. A record received or imported after the cutoff changes any decision, or the payout store can be read before `selection_frozen` (T-LEAK-1 to T-LEAK-3).
3. Any code path prices a NO position from YES quotes or a midpoint, or fills from a cohort other than the frozen first eligible one (T-NO-*, T-ENT-*).
4. The registry allows an attempt to be overwritten, deleted or omitted from a report without `registry verify` or `report --verify` failing (T-REG-*).
5. The same manifest yields two different `result_digest` values, or a resume yields a digest different from an uninterrupted run (T-REP-1, T-REP-2).
6. Census equalities fail: population ≠ skips + decisions, or decisions ≠ entries + rejections (T-REF-1).
7. A result is labelled confirmatory when it used a development or inspected date, or a twice-accessed test partition (T-SPL-3).
8. A smoke run's measured resources exceed a proposed bound without a `budget_stop` and journal entry, or the close receipt shows any collector, timer or operational-hash change (§6).

Each item is a concrete, checkable test or receipt, so the design can be rejected by evidence rather than by opinion.