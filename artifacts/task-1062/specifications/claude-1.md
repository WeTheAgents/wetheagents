I've read everything I need and am writing the specification now.

# WEA1062 specification candidate: a hypothesis-testing lab for the wea_ther research stack

**Candidate:** Claude-1@claude, an independent native CLI session (Task 1062, Spec/Ranked stage)
**Input snapshot:** common SHA-256 `58aab056090a57380a7bbacfce2edaa4783b69984735006de0e0b416373b1c24`. The files are listed in `snapshot-manifest.json`; source files carry the per-file hashes in `source-prerequisite-manifest.json`.
**Status:** specification only. Nothing has been implemented, executed or measured. No Hetzner command, trade, collector change, deployment or publication was performed in producing this document. Every number below is either a fact taken from the provided inputs (cited) or a *proposed* default (labelled). This document contains no profit claim.

Paths are relative to the provided snapshot. `R/` is `source-prerequisite/artifacts/replay_2026-10-08/`, `S/` is `source-prerequisite/artifacts/rest15_2026-10-08/`, and `src/` is `source-prerequisite/src/`. Host names, addresses, credentials, absolute mount paths and raw records are deliberately left out.

---

## 0. Design summary

The lab is a thin, append-only orchestration layer around the existing pure execution kernels. It does not rewrite them. It adds:

1. a **versioned hypothesis contract**, frozen before any outcome is read;
2. **three adapters** (REST15 sweep, legacy projection, compact archive) that emit one common *as-of evidence view* with explicit clocks. Each adapter must either deliver an own-side executable quote or return a typed refusal;
3. a **single canonical conditional $1 accounting path**, reusing the existing pure kernel in `R/small_order.py` and its REST15 sweep wrapper `S/small_order_rest_v3.py`, plus matched baselines and stress tests;
4. a **split registry, attempt registry and access journal** that are hash-chained and append-only. These make test-set access, retries and searches visible and impossible to overwrite;
5. a **deterministic CLI** whose manifest binds code, dependencies, data, as-of time, parameters, seed and splits;
6. a **bounded Hetzner runner**. Its first smoke run is capped at 1 process, 1 CPU, 2 GiB, 10 minutes and 1 GiB of output, with a 20 GB free-disk floor;
7. a **readable Markdown + JSON report** with three outcome classes: positive signal, negative result, insufficient data.

The core principle comes from the existing protocols: **select first, freeze, then open labels.** The existing runners already do this: `S/replay_rest15.py` writes `selection.frozen.json` before it opens the payout file, and `R/freeze.py` refuses to overwrite a freeze. The lab turns that per-script discipline into a framework invariant enforced by the registry.

---

## 1. Outcome, non-goals, hypothesis schema

### 1.1 Outcome

Given a registered hypothesis version and immutable inputs, the lab produces a reproducible verdict, labelled exploratory or confirmatory, on whether the rule beats no-trade and a matched baseline under conditional $1 full-fill economics with archived fees. Every skip, refusal and data limit is reported. Anyone with the same code, data and seed can re-run it and get byte-identical economic outputs.

### 1.2 Narrow non-goals (via negativa)

- No order placement, wallet, signing, approval, redemption or network client to any trading endpoint. The CLI has no code path to one.
- No new collection, collector change, timer, scheduler or quota change, and no restoration of deleted volumes.
- No full-depth, queue or impact model in v1. `src/server_replay.py` (an L2 WebSocket replay) stays a diagnostic. It is not part of the $1 path (see §3.9).
- No reconstruction of NO from YES, no midpoint fills, no synthetic minute quotes from REST sweeps or checkpoints, and no depth inferred from BBO.
- No universal coverage threshold. Suitability is decided per hypothesis.
- No website and no dashboard service. Reports are Markdown/JSON files.
- No claim of on-chain payout, real executability or official-weather truth unless the specific evidence level exists.
- No re-labelling of previously inspected dates (REST15/H4 September 12 – October 6, 2026; first compact audits) as a holdout.

### 1.3 Hypothesis schema `hypolab.hypothesis/1`

The document is JSON with canonical serialization: sorted keys, no NaN, Decimals as strings, the same convention as `packed()` in `S/replay_rest15.py`. Its hash is the SHA-256 of the canonical bytes. Once registered, a version is immutable; any change creates a new `version` that links back through `parent`.

| Field | Type | Meaning / constraint |
|---|---|---|
| `schema_version` | const `"hypolab.hypothesis/1"` | A schema migration needs a new constant. |
| `hypothesis_id` | string `HX-<FAMILY>-<NNN>` | Stable across versions. |
| `version` | semver | Major = economic or selection change; minor = reporting-only change; patch = typo. Only reporting fields may change in a minor or patch version (enforced by a diff check). |
| `parent` | hash or null | Previous registered version. |
| `family` | enum `ensemble_no`, `price_path`, `forecast_revision`, `remaining_max`, `local_memory` | Multiplicity family (§4.6). |
| `rationale` | text ≤ 2,000 chars | Mechanism and why it could pay after costs. |
| `mechanism` | `{module, function, version_hash}` | Pointer to a pure signal function, e.g. `signals.classify_revision` with its file SHA. |
| `adapters` | list of `{adapter_id, adapter_version, required_kinds[]}` | e.g. `compact/1` with `bbo_sample_batch`, `expected_matrix`, `market_version`, `fee`, `execution_terms`. |
| `inputs` | list of `{kind, identity_keys, freshness_rule, max_age_s, fallback:"none"}` | `fallback` is always `"none"`: an invalid latest record blocks the signal. |
| `population` | `{stations or "all_bound", horizon:"T-1"/"T0", interval_scope:"all_native_including_tails", event_filter}` | Filters are defined on metadata available at the decision cutoff only. |
| `decision_clock` | `{local_anchor:"18:00", anchor_window_s, cohort_rule, weather_cutoff_offset_s, metadata_cutoff_offset_s}` | e.g. first cohort in local [18:00, 19:00), weather/metadata cutoff at signal − 5 s (as in `R/protocol.json`). |
| `parameters` | object of fixed values | Every threshold, written literally. |
| `search_space` | `{name: [finite values]}` or `{}` | Finite grid only. Each point gets a `config_id` = hash(hypothesis hash + point). Every point counts toward multiplicity. |
| `selection` | `{side_rule, interval_rule, tie_break, max_positions_per_event:1}` | Deterministic tie-break (an existing example is the `best_gap` key in `R/run.py`). |
| `entry` | `{min_delay_s, max_wait_s, freeze:"first_observed_before_validation", max_state_age_s, max_cohort_skew_s, gap_policy:"reject_if_any_between_signal_and_entry"}` | Window values are bound to the adapter (§2.6). |
| `execution` | `{model:"conditional_one_dollar_full_fill/1", fee_modes:["CTF","USD"], price_shifts:["0","0.01","0.02"], reserves:["0","0.01","0.02"], minimum_order_policy:"flag_and_sensitivity"}` | §3. |
| `exit` | `{kind:"hold_to_payout"}` or `{kind:"exit_at_own_bid", clock, fee_on_exit:true}` | v1 default is hold. |
| `capital` | `{per_arm_cap_usd:"1000", reservation:"full_until_verified_payout", recycle:false}` | As in `S/protocol_rest15_v3.json`. |
| `payout` | `{min_evidence_level:"P2", weather_certification_required:false}` | §3.5. Set to `true` only for claims that depend on weather truth. |
| `baselines` | list of baseline IDs (§3.7) | Must include `B0_no_trade` and at least one matched baseline. |
| `splits` | `{split_set_id, walk_forward:{...} or null}` | Must reference a registered split set (§4.2). |
| `evaluation` | `{primary_metric, secondary[], decision_rule, min_entry_dates, min_entries, bootstrap:{B, seed, cluster:"market_date"}}` | §4.7, §7.2. |
| `seed` | int | Used by seeded baselines and the bootstrap only. Signals are deterministic. |
| `claims_allowed` | enum `development_only`, `exploratory`, `confirmatory_candidate` | Upper bound on report strength. |

Registration rejects any document that is missing a required field, uses an unknown enum, has an unbounded search space, a fallback other than `none`, or a split set that includes a date already marked inspected for this family (§4.3).

### 1.4 Three worked examples (illustrative registrations, not results)

**Example A — ensemble-NO family: `HX-ENSNO-001` v1.0.0**
- Rationale: on T−1 evening, intervals that the five-family ensemble considers improbable may have own NO asks priced below the model's NO probability. Buying the own NO captures that gap after fees.
- Mechanism: `signals.interval_probability` with the fixed Gaussian kernel of 1.5 °C, delta 0, equal family weights, then equal member weights within each family. These are the existing parameters from `R/protocol.json`, reused unchanged.
- Inputs: all five families fresh (≤ 12 h receipt age, persistent target hash via `signals.persistent_target_family`); a coherent native interval inventory including both tails (`run.coherent_bins`).
- Selection: for each event, compute `gap_NO(i) = (1 − p_i) − NO_ask_i`, using **the NO token's own ask**. Choose the maximum gap. Tie-break: lowest interval ID, then side. Enter only if the gap is ≥ `min_gap`.
- `parameters`: `min_gap` taken from `search_space`.
- `search_space`: `{"min_gap": ["0.05","0.08"]}` — two configs, both counted.
- Entry, compact adapter: first observed cohort at signal + 60 s … + 300 s, state age ≤ 120 s, skew ≤ 5 s (from `compact_contract_v2.md`).
- Baselines: B0 no-trade; B1 `same_interval_YES`; B2 `seeded_random_NO_same_event` (§3.7).
- Evaluated: mean net PnL per entered $1 gross, CTF and USD fee modes, at ask + 0.01, with payout level ≥ P2.

**Example B — price path/reaction family: `HX-PATH-001` v1.0.0**
- Rationale: when the market's own ask for the forecast-favoured interval moves sharply between two fixed clocks **without** any change in the persistent forecast target arrays, the move may be noise that partly reverts before resolution.
- Mechanism: a new pure function `price_reaction(own_quotes_t1, own_quotes_t2, forecast_hashes_t1, forecast_hashes_t2)`. Its inputs are own-token observed BBO at two fixed cohorts (local 12:00 and 18:00 on T−1), each frozen as the first observed cohort in its window. A forecast is "unchanged" when the canonical target hash of all five families is identical across both cutoffs (`signals.canonical_target_hash`).
- Signal: let `Δ = ask_YES(t2) − ask_YES(t1)` for the modal-probability interval, chosen at t1 and frozen. If `Δ ≥ move` and the forecast is unchanged, buy the own **NO** of that interval at t2 + entry. If `Δ ≤ −move`, buy the own **YES**.
- `search_space`: `{"move": ["0.05","0.10"]}`.
- Suitability: **compact archive only** for minute-level t1/t2 cohorts. REST15 can serve only where both fixed-clock sweeps were retained (noon and evening sweeps exist in `S/replay_rest15.py`). Such REST15 runs are marked `development_only`, because every REST15 date has already been inspected.
- Baselines: B0; B3 `same_clock_momentum` (the opposite direction, with identical entry and costs); B2.

**Example C — forecast-revision family: `HX-REV-001` v3.1.0**
- This re-registers existing H3 with **unchanged** thresholds: `signals.classify_revision` (single revision: exactly one family's mean changes by ≥ 1 °C and every other family by ≤ 0.3 °C; common revision: ≥ 3 families move ≥ 0.5 °C in the same direction; the changed response must persist ≥ 1 hour; clocks are 12:00 → 18:00).
- `search_space: {}`. The two arms (`single`, `common`) are both reported, and neither is promoted (as in `R/protocol.json`).
- Selection: the largest probability gap to the **own** ask across YES/NO (`run.best_gap`, min 0.05).
- Prior status: development only (REST15 v3 census). Any confirmatory claim requires the compact-era untouched test split (§4.3).
- Baselines: B0; `five_family_control` (the existing no-gate control, used as a matched baseline); B2.

H1 `remaining_max` and H4 `local_memory` are registered with status `data_blocked` and their required inputs listed (`compact_contract_v2.md` table). They still appear in every report as blocked arms (the convention in `S/replay_rest15.py`).

### 1.5 Preregistration and what is evaluated

- **Order of operations:** register the hypothesis → register or verify the split set → build the data manifest → run plan (counts only, outcome-blind) → execute selection → freeze selection (hash recorded in the registry) → evaluate (labels opened) → report. The registry rejects an `evaluate` event without a preceding `freeze` for the same `attempt_id`.
- **Search:** only grid points in `search_space`. Running a config not in the registered grid requires a new version. Every grid point is executed and reported. Partial grid execution is recorded as such.
- **What is evaluated:** the hypothesis's own entries (the *treatment*) against (a) no-trade and (b) matched baselines on the same units, under all fee modes and stresses. The **primary metric** is chosen at registration: one metric, one fee mode reported as primary (both are always shown), one stress level. Defaults (proposed): mean net PnL per entry, USD-fee mode, ask + 0.01, P2 payout. Forecast skill (`R/skill_metrics.py`) is a secondary diagnostic only, never the decision metric.

---

## 2. Adapter contracts

### 2.1 Common evidence model

Every adapter emits immutable `Record`s compatible with `core.Record` in `R/core.py` (`id, kind, entity, received, event_time, issue_time, revision_time, first_received, data`), extended with a sidecar `clocks` object. Clocks must stay distinct:

| Clock | Meaning | Source examples | May gate availability? |
|---|---|---|---|
| `event_time` | When the observed physical or market fact occurred (METAR observed time, minute bucket) | `extract.weather_row`, compact minute | No |
| `model_time` | Claimed model initialization or run label | forecast `actual_run`; `actual_initialization_proven=False` in `R/extract.py` | **Never** (not proven) |
| `publication_time` | Source-declared issue/valid time (TAF issued, report time) | context `issued` | No |
| `source_timestamp` | Exchange or source timestamp on a quote; semantics `unknown`, `last_price_change` or `state_observation` | REST `exchange_timestamp`; compact source time | Only as an upper bound (must not exceed receipt) |
| `received` | When our collector actually received the bytes | all | **Yes** |
| `first_received` | First receipt of this exact content | forecasts, metadata | **Yes** |
| `imported_at` | When the record entered the archive or catalog (late imports, seeds) | `imported_at` in `src/compact_replay.py`, `src/server_replay.py` | **Yes** |
| `state_validated_at` | Last successful source observation or healthy-subscription validation proving the quote is current | compact v2 | Gates quote freshness |
| `decision_at` | Logical signal time | lab | — |

**Availability rule (universal):** `available_at = max(received, first_received or received, imported_at or received)`. A record is visible at cutoff `c` iff `available_at ≤ c`. This generalizes `core.AsOfView` (receipt plus first receipt) and the `imported_at` handling in `src/compact_replay.py` and `src/server_replay.py`. Tests in §8.6 require that a record received early but imported late is invisible before its import.

**Quote freshness rule:** a quote is usable at `t` only if `0 ≤ t − state_validated_at ≤ max_state_age_s` **and** `source_timestamp ≤ received` (when present). An unchanged price may carry an old `last_price_change` time while its subscription is healthy (`small_order._validate_quote`). A cached replay cannot refresh `state_validated_at`.

**Own-side executable quote** (`OwnQuote`): `{token, side, interval_id, event, bid, ask, tick, min_size, received, state_validated_at, source_timestamp, source_semantics, cohort_id, cohort_skew_s, epoch, carried_forward, validation:"rest"|"heartbeat", binding_hash, fee_binding, terms_hash}`. It is valid only if `0 < bid ≤ ask < 1` and both prices are tick-aligned. **An adapter never fills `ask` for a NO token from a YES record.** If the NO record is missing, the quote is missing.

**Refusal model:** every adapter call returns either a value or a `Refusal{code, layer, unit, evidence_ids[]}`. Codes are a closed enum; a new code needs a version bump. Layers are `data` (gap or missing), `identity` (binding mismatch), `clock` (future or stale), `execution` (invalid quote or fee), `policy` (hypothesis gate). Every code is counted in the report.

### 2.2 Adapter L-REST15 (`rest15/3`): old REST15 sweeps

- **Source:** the closed partial evidence database read through `S/adapter.py` (`Evidence`, read-only, `query_only`), the hash-verified metadata ID catalogue built by `S/build_index.py` (versions table: id, event, market, received), and the census population file. Freeze inputs come from `analysis.frozen.json` and `target.complete.json` (as `S/replay_rest15.py` asserts).
- **Unit:** an event × a *sequential REST sweep*. Sweeps are built by chronological clustering with a split gap of ≥ 60 s and a maximum duration of 120 s (`replay_rest15.cluster`, `small_order_rest_v3` constants). A sweep is **non-atomic**: each book carries its own `received`.
- **Signal clock:** last actual receipt of the first retained sweep in the fixed local window. Weather and metadata cutoff is signal − 5 s.
- **Entry clock:** the **first** subsequent retained sweep that starts ≥ signal + 60 s, frozen before content validation; its end must be ≤ signal + 1,200 s (`S/protocol_rest15_v3.json`). The fill is logically at the sweep end; the price is the chosen token's own ask, aged ≤ 120 s at sweep end.
- **Identity and interval binding:**
  - The as-of market version set comes only from catalogue IDs whose native rows verify. A missing native row for the latest catalogued ID refuses with `latest_catalogued_metadata_not_native_verified`. There is never an older fallback (`test_latest_catalogued_missing_metadata_never_falls_back_to_older_row`).
  - Inventory must be coherent: tails present, contiguous native bins (`run.coherent_bins`), uniform event/target/station/unit/timezone/source, and a T−1 noon anchor check for the timezone (`identity_matches`).
  - Every YES and NO token of the inventory must appear exactly once in the sweep.
  - Any intervening metadata change between cutoff and entry rejects, even if it later changes back.
- **Gaps:** between-poll continuity is **unknown**. `archive_window_complete=False` means absence of a sweep is *not* absence in the population. Refusal: `no_retained_evening_sweep_unknown_archive_remainder`.
- **Must not:** produce minute quotes, interpolate between sweeps, treat a checkpoint or receipt as a fresh quote, or claim the first retained sweep is the global first sweep.
- **Status:** every date is `development_only`; `independent_test_dates = 0` (the report field in `S/replay_rest15.py`).

### 2.3 Adapter L-PROJ (`projection/1`): legacy normalized projection + 640 exact H4 inputs

- **Source:** the normalized projection produced by the bounded extraction (`R/extract.py`, `R/resume_extract.py`). Per `data_contract.md` this is 139,846 rows retained from a phase that closed at its IO budget and is explicitly partial. Per the brief it also includes **640 exact H4 inputs**. The projection holds forecast rows (per station/unit/timezone/target/model, with validity flags), market metadata versions (semantic and literal rule hashes), METAR/context rows, and the book rows already counted under L-REST15.
- **Provides:** weather features, forecast vintages, metadata vintages, and label-history candidates for walk-forward calibration (H4), each with `received`, `first_received`, `event_time` and `issue_time`.
- **Does not provide:** a full order book, a depth history, minute quotes, or a complete METAR/TAF history. `R/protocol_rest15_v3.json` keeps H2/H4 blocked "until latest native auxiliary receipt coverage can be certified".
- **640 exact H4 inputs:** these are exposed as their own record set `h4_exact/1`, each bound by record ID and hash. An H4 version may evaluate only units whose full input tuple (GEFS members, prior labels with receipt, METAR pair, station mapping) is drawn **entirely** from this set or from verified native rows. Anything else refuses with `h4_input_not_in_exact_set`. Gaps elsewhere in the projection never borrow from these inputs.
- **Partial-input semantics:** a missing normalized row is `unknown`, never `absent` and never zero opportunities (`R/extract.py` docstring). The adapter refuses to report population-level rates unless the hypothesis explicitly allows `observed_retained_subset`.
- **Status:** `development_only` for all dates.

### 2.4 Adapter N-COMPACT (`compact/1`): new compact archive

- **Source:** compact archive rows read in received order with storage-ID de-duplication. The as-of semantics follow `src/compact_replay.py` (`CompactAsOf`), and matrix acceptance follows `R/compact_matrix.py` (`validate_matrix`). Record kinds used: `session_start/stop`, `gap` (sources compact_books, books, ingest, clock, interval_binding), `expected_matrix`, `market_version`, `market_receipt`, fee receipts and seeds, `execution_terms_version/receipt`, and `bbo_sample_batch` (per token: bid, ask, received, source time, `state_validated_at`, validity, cohort ID, skew, session epoch, tick, minimum size).
- **Unit:** event × native interval × side × UTC minute (the expected matrix), including both tails.
- **Cell classes**, a disjoint enum: `tradable` (ok, own bid and ask valid); `observed_empty` (a valid known empty side, non-tradable); `gap` (explicit or unknown); `missing_record`; `invalid` (wrong token/unit/bounds, crossed, future validation); `excluded_known_invalid_cohort` (see below). Counts for planned, recorded, valid, tradable, unavailable and unknown are always reported separately (the `validate_matrix` output contract).
- **Clocks:** `received`, `state_validated_at`, `source_timestamp` with declared semantics, `imported_at`. A heartbeat refreshes validation only with an initialized, continuously healthy epoch and `cached_replay=False` (`small_order._validate_quote`).
- **Fees and terms:** an archived fee receipt or seed with its original receipt; `execution_terms` (protocol version, fee base, curve). The adapter binds the fee schedule from metadata to the terms. Disagreement refuses with `fee_disagreement`. A missing or stale (> 6 h) fee or terms record refuses (the `compact_replay` limits, kept as adapter defaults; they are hypothesis-overridable only downward).
- **Known cohort defects:**
  - The **15 known pre-r7 split minutes** excluded in the first daily audit are loaded from an evidence-bound exclusion file `{event, minute, reason:"pre_r7_split_cohort", audit_record_hash}`. Cells in those minutes are `excluded_known_invalid_cohort`: neither gaps nor tradable. Any signal or entry selecting such a minute refuses with `excluded_cohort_minute`. Exclusion is never silently extended to other minutes.
  - The **40 post-r7 minutes checked in one cohort** establish only that single-cohort behaviour was observed in that window. **No live cohort transition has been observed.** A *cohort-layout transition* means a change in the expected matrix, a new session epoch, or a change in the token membership of the cohort. Until an audit records and validates such a transition, any entry whose signal→entry span contains one refuses with `cohort_transition_unverified`. Relaxing this rule is an operator decision (§8.8).
- **Gaps:** a gap event clears affected tokens (or all tokens) in the as-of state, as `CompactAsOf` does. Interval-binding gaps clear the market's bindings. A gap or reconnect anywhere between signal and entry rejects (`small_order` intervening checks).
- **Must not:** carry a quote forward across a gap, session restart or epoch change; complement YES into NO; floor off-grid minutes; or treat an empty side as the previous quote.
- **Status:** dates already read by any economic attempt or by the first daily audits are `development`. New dates can enter a registered untouched test split only through the access journal (§4.3).

### 2.5 Identity and interval binding (all adapters)

The binding key is `(event_id, market_id, condition_id, yes_token, no_token, native_lower, native_upper, unit, inclusivity flags, station, timezone, local_target_day, source, rules_hash)`.

- Rules: keep both the literal rule hash and the semantic hash (`extract.legacy_rules`, `extract.semantic_rules`). Payout joins use the strict literal match (existing G1/G2 rule).
- Native endpoints are compared as native values. No °C/°F conversion happens in binding, and half-degree rounding cells are derived separately (`core.native_temperature_bin`, `compact_matrix` "native_endpoint_conversion: False").
- A position carries its binding hash from signal to payout. Any mismatch at entry or payout refuses or marks the payout `unknown`.

### 2.6 Hypothesis-specific suitability (no universal threshold)

`hypolab data suitability --hypothesis H --split S` computes, per adapter and per unit, which gates pass. The output is a census: units planned, units with each refusal code, and usable units. It never reports a single "coverage %" gate.

| Hypothesis family | L-REST15 | L-PROJ | N-COMPACT |
|---|---|---|---|
| ensemble-NO (A) | Usable (development): evening sweep plus 5 fresh families; own NO ask present in sweep | Forecast features only | Usable: needs the full YES/NO matrix for the event at signal and entry minutes |
| price path (B) | Development only, and only when both fixed-clock sweeps are retained; no between-sweep path claims | Not suitable (no quotes) | Primary adapter; needs both cohorts plus unchanged forecast hashes |
| forecast revision (C) | Development only (existing v3 census) | Forecast vintages (noon/evening) | Usable once noon/evening forecast vintages and the matrix exist |
| remaining max (H1) | Refuse: `T0_hourly_contractual_maximum_data_blocked` | Refuse | Refuse until T0 BBO, hourly member paths and contractual running maximum exist |
| local memory (H4) | Development, and only on the 640 exact-input units | Exact-input set only | Needs METAR/label receipt history per the contract table |

Entry-window parameters are adapter-bound and **not unified**: REST15 v3 uses +60 … +1,200 s at sweep end; compact v2 uses +60 … +300 s at the first cohort; the original depth protocol used +5 … +1,200 s (`R/protocol.json`). Each hypothesis version fixes one adapter/window pair. Comparing across adapters is a reporting operation, never pooling.

---

## 3. Conditional $1 full-fill economic model

### 3.1 Canonical accounting (reuse, do not reimplement)

The canonical per-entry accounting is `small_order._account` (`R/small_order.py`), used by both `small_order.simulate_one_dollar` (minute mode) and `small_order_rest_v3.simulate_one_dollar` (sweep mode).

For own-side ask `p` (tick-aligned, `0 < p < 1`) and an archived fee schedule with rate `r` and exponent `e` (or fees disabled):

- gross shares `q = 1/p` ($1 gross notional before fees);
- fee cash-equivalent `f = ceil_{0.00001}( r · (p(1−p))^e / p )`, or 0 if fees are disabled;
- **CTF mode** (fee taken in shares): cash = $1, net shares = `q − f/p`;
- **USD mode** (fee taken in cash): cash = `1 + f`, net shares = `q`;
- if net shares ≤ 0, the entry is unsupported (`nonpositive_net_shares_after_fee`).

Both modes are complete, uniform portfolios. They are never mixed per position (`core` module docstring and `MODES`).

**Equivalence note (must be tested):** `src/compact_replay.CompactAsOf.buy_one_dollar` computes the fee *unrounded*, accepts only exponent 1, and checks terms agreement. It is the acceptance reader, not the accounting authority. The lab uses `CompactAsOf` semantics only to build the as-of state, and always prices through `_account`. A test asserts that the two differ by at most the 0.00001 rounding quantum per $1 for exponent-1 schedules (§8.6, T-FEE-3).

### 3.2 Entry: frozen first eligible observation

- The candidate set is all observed cohorts (compact) or sweeps (REST15) for the **chosen token** that are distinct from the signal cohort and start within the window.
- The first is chosen by `(time, id, index)` **before** any content validation (the `small_order` and `small_order_rest_v3` selection rule).
- If that first candidate fails any check (stale, gap, crossed, fee mismatch, inactive, binding changed), the decision is **rejected**. No later candidate is ever examined. Existing tests: `test_first_bad_quote_cannot_be_replaced_by_later_cheap_quote`, `test_first_sweep_missing_chosen_token_or_bad_quote_never_falls_back`, `test_first_sweep_end_outside_window_is_not_replaced`, `test_sweeps_use_actual_receipts_and_first_incomplete_is_not_replaced`.
- One attempt per (arm, event): `core.ReplayEngine.attempts` semantics (`event_attempt_budget_exhausted`).
- No entry-time EV recheck in REST15 v3 (`entry_model_EV_recheck: false`). A hypothesis may declare a recheck only in a new major version, and a recheck failure is a rejection, not a retry.

### 3.3 Costs, spread and stress (fixed before outcomes)

- **Spread:** reported per entry as `ask − bid` of the own token, and aggregated. The diagnostic "entry at mid" PnL appears only in the cost-decomposition table, never as a headline.
- **Price stress:** ask + {0, 0.01, 0.02}, rounded **up** to the native tick. Each repriced scenario independently spends $1 gross and recomputes q and fee. A stressed ask ≥ 1 is unsupported, never capped (`test_price_stress_reaching_one_is_unsupported_not_capped`).
- **Same-fill extra-cost reserves:** {0, 0.01, 0.02} per gross share, reported separately from the repriced scenarios.
- **Fee-rate sensitivity:** an optional preregistered multiplier set (proposed: {1.0, 1.5}) applied to the archived rate. It is labelled as a sensitivity, never as archived truth.
- No stress is ever chosen after outcomes. All stresses are always reported.

### 3.4 Minimum order, size and executability limits

- Each entry records `min_share_feasibility` ∈ {`feasible_share_count_only`, `below_minimum_shares_hypothetical_fill_retained`, `unknown`} (`small_order._minimum_flag`). An example from the contract: $1 at 0.50 gives 2 shares, below a 5-share minimum if that minimum applies.
- **The main analysis keeps below-minimum entries** (the user-authorized hypothetical $1 fill). A **minimum-compliant sensitivity** drops them, and is reported only where the minimum's applicability is documented for that market/protocol version. Otherwise the report says `minimum_applicability_unknown`.
- Every report carries the fixed labels: `full_fill_assumed=true`, `observed_fill=false`, `depth_checked=false`, `market_order_notional_applicability=unknown_not_promised`. No text may describe these as fills, executions or achievable sizes.

### 3.5 Payout evidence levels

| Level | Evidence | Allowed use |
|---|---|---|
| P0 `unknown` | None, or binding mismatch | Bounds only: `[−cash, net_shares − cash]` |
| P1 `G1` | Gamma final payout vector, strict literal binding match | Exploratory conditional PnL, labelled "Gamma-conditional" |
| P2 `G2` | P1 plus the stricter existing G2 grade (from the hash-verified audit), final status, no later vector change before the evaluation as-of | Primary conditional PnL (default `min_evidence_level`) |
| P3 `G3` | Independently verified on-chain payout/access (`verified=True`, redeemed) | Cash recycling allowed only here (`core.apply_payout_access`); none exists today (`G3: 0`) |
| W `weather_certified` | Contractual-source final maximum with revision history | Required only when `payout.weather_certification_required=true` |

The **41 Gamma final payout vectors** available today are P1/P2 candidates, **not** P3. The absence of official weather does **not** block P1/P2 conditional economics (brief fact). Unknown payouts keep complementary joint bounds (`core.complementary_joint_bounds`; independent conditions by default, exclusive geometry only if attested).

### 3.6 Capital and risk

- Each arm × fee mode × price-stress scenario has its own funded ledger. Default cap: $1,000 locked cash (`S/replay_rest15.py`). An entry that would exceed the cap is `capital_rejected` and counted, never silently dropped.
- Cash is reserved until P3. Gamma marks never release cash (`no_cash_recycled: true`).
- Risk metrics: locked cash over time, maximum concurrent locked cash, number of open events per date, and the **max drawdown** of cumulative realized conditional PnL ordered by resolution receipt (P2 only). Separately, the worst-case path where every unknown payout resolves at its lower bound.
- One position per event per arm; complementary positions in the same condition are netted in the bounds.

### 3.7 Matched baselines (same units, same execution, same costs)

All baselines run through the identical adapter, entry freezing, accounting, fee modes and stress. They differ only in the *selection rule*.

- **B0 `no_trade`:** PnL 0 and capital 0. It is the null for "is it profitable at all".
- **B1 `same_interval_opposite_side`:** buy the other own token of the selected interval at the same entry cohort. This tests whether side choice matters.
- **B2 `seeded_random_same_event`:** in each treated event, pick an interval/side uniformly among *eligible* own quotes at the signal cohort, with a seed derived from `(seed, event, config_id)`. 1,000 seeded draws give a null distribution (proposed). This is the main matched baseline.
- **B3 `family_control`:** the family's natural control, e.g. `five_family_control` for C, `same_clock_momentum` for B, and for A the `GEFS_control` and `regime_unimodal_control` arms (these exist in `S/replay_rest15.py` ARMS).
- **B4 `favorite_buy`** (optional): buy the own YES of the highest-model-probability interval. It is a "markets are efficient" reference.

**Pairing rule:** the primary comparison is paired on units where *both* treatment and baseline produced a `hypothetical_full_fill`. Units where only one side filled are listed as `paired_exclusion` with reasons. Population-level (unpaired) results are reported next to the paired ones and are never substituted for them.

### 3.8 Exit

v1 is hold-to-payout. A preregistered `exit_at_own_bid` variant prices the exit at the own token's **bid** at the first observed cohort after the exit clock, with the same freeze, no-fallback, fee and stress rules. It is applied symmetrically to the baselines.

### 3.9 Excluded from v1

`core.ReplayEngine` depth participation (10 % displayed depth, 25 shares, edge/stress gates) and the `src/server_replay.Replay.hypothetical_buy` L2 path stay unchanged as **legacy strict-mode engines**. They are reachable only through a separate `execution.model="legacy_depth/1"` with its own equivalence tests. They are never mixed into $1 results.

---

## 4. Leakage protection and validation

### 4.1 Leakage controls (mechanical, not advisory)

1. **As-of view only.** Mechanisms receive an `AsOfView` built at `decision_at − cutoff_offset`. Quotes are visible only at ≤ `decision_at`. The view object has no accessor to records past its cutoff.
2. **Labels live in a separate store** (payout audit file, outcome vectors). The adapter API has no label access. Only `evaluate` opens labels, and only after a `selection_frozen` event whose hash matches the selection file (the `S/replay_rest15.py` pattern, enforced by the registry).
3. **Walk-forward label availability:** calibration labels (H4 memory, any fitted parameter) are visible only if `label.available_at ≤ decision cutoff` (`R/protocol.json` H4: "labels actually received before current signal").
4. **No inferred initialization:** model run labels never gate availability (`actual_initialization_proven=False`).
5. **No stale fallback:** if the latest record is invalid, the signal is blocked (data contract acceptance gate).
6. **Content-hash revisions:** revision detection uses the target-array hash only, and A→B→A restarts the clock (`persistent_target_family`).
7. **Population fixed outcome-blind:** population filters use metadata available at cutoff and never use outcome, payout or price-vs-payout information.

### 4.2 Split registry (immutable)

A `split_set` record holds `{split_set_id, created_at, family_scope, ranges:[{name:"train"|"validation"|"test", start_market_date, end_market_date}], embargo_days, inspected_exclusions_hash, registry_prev_hash}`.

- Ranges are chronological and non-overlapping by **market date** (local target day). The embargo between consecutive ranges defaults to ≥ 1 market date (proposed), because labels resolve after the local day.
- Once registered, a split set can never be edited. Corrections create a new ID, and the old one stays in history with a `superseded_by` pointer.
- **Walk-forward spec:** `{fold_length_days, min_train_days, refit:"none"|"expanding"|"rolling", embargo_days}`. Every fold is a deterministic function of the split set. Fitted state uses only labels available before each fold start.

### 4.3 Development dates and the untouched test

- **Inspected-date ledger:** a registry record class `inspected` listing market dates and data sources already read with outcome or economic access. It is seeded with the full REST15/H4 development population (frozen 1,025 event-days, Sep 12 – Oct 6, 2026, per `data_contract.md`; decisions Sep 26 – Oct 6) and with every compact-archive date read by an economic or label-joined attempt.
- A split set whose `test` range intersects the inspected ledger for the same family cannot be registered (`inspected_date_in_test`).
- **First untouched test:** compact-archive market dates strictly after the test-start date. The test-start date must be ≥ the registration time of the hypothesis version plus one market date (proposed), so the test data did not exist when the rule was frozen.
- **Sealing:** the adapter refuses to emit any record with market date inside a sealed test range unless the registry holds an `unseal` event for `(hypothesis_hash, split_set_id)`. `unseal` requires a completed development/validation attempt and a frozen selection config for the test (the single config chosen on validation). An unseal is one-shot per hypothesis major version; a second unseal is refused.
- **Outcome-blind QA access:** daily collection audits must count planned, observed and tradable cells on test dates. They may do so through a QA-only interface that returns counts, never price levels joined to outcomes. Each QA read is journaled as `qa_outcome_blind`. Whether this counts as "untouched" is an **operator decision** (§8.8).
- **When no untouched test exists**, every result is labelled `exploratory/development_only` with `independent_test_dates=0`. This applies to every REST15/H4 result.

### 4.4 Attempt journal

Every invocation that touches data appends to `attempts.jsonl`:

`{attempt_id, parent_attempt_id, hypothesis_hash, config_id, split_set_id, split_part, phase, manifest_hash, started_at, ended_at, exit_status, outcome_class, result_hash, refusal_counts_hash, labels_opened:bool, test_access:bool, operator_note, prev_record_sha256, record_sha256}`.

- Failures, crashes, missing-data runs, refusals and aborted grids are all recorded. A crash leaves a `started` record without an `ended` record, and the next CLI call marks it `abandoned` while keeping it.
- **Hash chain:** each record contains the previous record's SHA-256. `registry verify` recomputes the chain. Any break is a hard error.
- **Single writer:** an exclusive lock file created with `O_EXCL`, append + `fsync`. No in-place rewrite, ever.

### 4.5 Retries and reruns

- A retry is a new `attempt_id` with `parent_attempt_id`. The old record stays.
- A rerun with an identical `manifest_hash` must give an identical `result_hash`. A mismatch is logged as `nondeterminism_detected`, the report is blocked, and the attempt stays in the journal.
- Output directories are per attempt (`runs/<attempt_id>/`). An existing directory is never overwritten (matching the existing guards that assert the target directory does not exist).

### 4.6 Multiplicity and selective-reporting control

- **Counted:** every `config_id` executed on validation or test, across all versions of a hypothesis and across all hypotheses in the same family. The report shows `configs_tried_family`, `configs_tried_hypothesis` and `versions_registered`.
- **Confirmatory control:** at most one config per hypothesis major version reaches the test. Across families, Holm–Bonferroni applies over all hypotheses unsealed in the same evaluation window. The family-wise α (proposed 0.05) is split equally across families declared at the window's start.
- **Exploratory:** the report shows the full grid and highlights nothing. A "best config" can be named only with the sentence "selected on development data; not independent validation".
- **Selective-reporting guard:** `report render` refuses to render a hypothesis report that omits any arm, blocked arm, grid point or failed attempt present in the journal for that hypothesis version.

### 4.7 Uncertainty

- The cluster unit is the **market date** (cities on the same day are correlated; wea_ther `AGENTS.md`).
- **Date-cluster bootstrap:** resample market dates with replacement, B = 2,000, fixed seed (as in `R/protocol.json`), percentile 95 % CI. It runs only when there are ≥ 10 P2-graded entry dates; otherwise the result is "insufficient data", with no CI shown as evidence.
- The paired treatment-minus-baseline difference is bootstrapped jointly on the same resampled dates.
- B2 random-baseline null: the share of seeded draws whose mean ≥ the treatment mean, reported as a *descriptive* rank, not a p-value, in exploratory mode.
- One day of test can never support a profitability claim; the minimums in §7.2 enforce this.

---

## 5. CLI, schemas, manifest, determinism

### 5.1 Commands

The entry point is `python -m scripts.hypolab <group> <command>`. It is a thin wrapper over the package `src/hypolab/`, following the repository's `python -m scripts.*` convention. Every command prints one JSON object to stdout and returns exit 0 on success, 2 on a refusal or validation failure, and 3 on an integrity error.

| Command | Purpose | Writes |
|---|---|---|
| `hypothesis validate FILE` | Schema and policy check, canonical hash | nothing |
| `hypothesis register FILE` | Immutable registration | registry `hypothesis_registered` |
| `split register FILE` / `split show ID` | Split set | registry `split_registered` |
| `data manifest --adapter A --asof T --out M` | Hash inputs, record lineage and clocks | dataset manifest file |
| `data suitability --hypothesis H --split S --manifest M` | Outcome-blind census of gates | `suitability.json` + registry attempt (phase `suitability`) |
| `run plan --hypothesis H --config C --split S --manifest M` | Freeze the run manifest | `runs/<id>/run.manifest.json` |
| `run execute --attempt ID` | Selection + execution, outcome-blind | `selection.json`, `executions.json`, `refusals.json` |
| `run freeze --attempt ID` | Hash the selection, write the registry event | registry `selection_frozen` |
| `run evaluate --attempt ID` | Open labels, compute PnL, baselines, bootstrap | `evaluation.json` |
| `run status / resume / stop --attempt ID` | Lifecycle | registry lifecycle events |
| `test unseal --hypothesis H --split S --config C` | One-shot test access | registry `unseal` |
| `report render --hypothesis H [--attempt ID...]` | Markdown + JSON report | `report.md`, `report.json` |
| `registry verify` / `registry list [filters]` | Chain integrity, history | nothing |
| `runner stage / launch / status / stop / collect` | Hetzner operations (§6) | runner receipts |

There is no `delete`, no `--force` and no `--overwrite` anywhere.

### 5.2 Run manifest `hypolab.run_manifest/1` (hash-bound)

```json
{
  "schema_version": "hypolab.run_manifest/1",
  "attempt_id": "att-<ulid>",
  "hypothesis": {"id": "HX-ENSNO-001", "version": "1.0.0", "sha256": "<64hex>"},
  "config": {"config_id": "<64hex>", "point": {"min_gap": "0.05"}},
  "code": {"git_commit": "<40hex>", "tree_dirty": false,
           "files": {"src/hypolab/...py": "<64hex>", "R/small_order.py": "<64hex>"}},
  "dependencies": {"python": "3.x.y", "lockfile_sha256": "<64hex>",
                   "packages": {"pyarrow": "<ver>"}},
  "data": [{"adapter": "compact/1", "manifest_sha256": "<64hex>",
            "asof_utc": "2026-..Z", "inputs": [{"logical_name": "...", "sha256": "<64hex>",
            "bytes": 0, "records": 0}]}],
  "labels": {"source": "payout_vectors", "sha256": "<64hex>", "opened": false},
  "splits": {"split_set_id": "SS-...", "part": "validation", "folds": []},
  "seed": 2000,
  "engine": {"execution_model": "conditional_one_dollar_full_fill/1",
             "kernel_sha256": "<sha of R/small_order.py>"},
  "evidence_level_floor": "P2",
  "resource_bounds_proposed": {"cpu": 1, "processes": 1, "memory_gib": 2,
                               "wall_s": 600, "output_gib": 1, "min_free_gb": 20}
}
```

`manifest_hash` is the SHA-256 of the canonical manifest bytes. Execution refuses if any listed file hash differs at start or at any checkpoint.

### 5.3 Dataset manifest `hypolab.dataset_manifest/1`

`{adapter, adapter_version, asof_utc, sources:[{logical_name, sha256, bytes, record_count, kinds}], lineage:[{derived_from_sha256, transform, code_sha256}], clock_semantics:{received, first_received, imported_at, state_validated_at, source_timestamp_semantics}, known_limitations:[...], exclusions:[{kind:"pre_r7_split_minute", count:15, evidence_sha256}], completeness:{archive_window_complete:false|true, matrix_planned, matrix_valid, matrix_tradable}, inspected_dates_hash}`.

Logical names replace absolute paths, so manifests are public-safe.

### 5.4 Result schema `hypolab.result/1`

`{attempt_id, manifest_hash, outcome_class: "positive_signal"|"negative_result"|"insufficient_data", strength: "development_only"|"exploratory"|"confirmatory", arms:{<arm>:{decisions, entries, entry_dates, events, refusals:{code:n}, scenarios:{"<shift>:<mode>":{entries, unsupported, capital_rejected, locked_cash, graded_cash, gross_pnl, fees, net_pnl, roi_gross_notional, roi_cash_outlay, roi_peak_locked, unknown_bounds:[lo,hi], max_drawdown, ci95:[lo,hi]|null}}}}, baselines:{...paired...}, multiplicity:{...}, data_quality:{...}, limitations:[...], result_sha256}`.

All money values are Decimal strings. Times are UTC epoch seconds as Decimal strings.

### 5.5 Determinism and recoverability

- Inputs are sorted by `(available_at, id)` before processing (as `core` and `CompactAsOf` do). Iteration over dicts and sets is always sorted.
- Decimal arithmetic at precision 50 (`localcontext` in the kernels). No floats in money paths. Floats appear only in the probability mechanisms, which already exist and are hashed.
- No wall-clock value in any economic output. Wall times live only in registry and lifecycle records.
- Seeds are derived as `sha256(seed ‖ purpose ‖ unit)`. Threads are fixed to 1 (`pyarrow use_threads=False`, BLAS/OMP threads = 1).
- **Phase checkpoints:** `selection.json`, `executions.json` and `evaluation.json` are each written atomically (temp file + rename). `resume` verifies the manifest hash and the hashes of completed phases, then continues from the first incomplete phase. A completed phase is never recomputed in place; a mismatch aborts with `checkpoint_hash_mismatch`.

### 5.6 Illustrated run (NOT executed; every value is a placeholder)

```text
$ python -m scripts.hypolab hypothesis register hx-ensno-001.json
{"registered":"HX-ENSNO-001@1.0.0","sha256":"<64hex>","configs":2}

$ python -m scripts.hypolab data suitability --hypothesis HX-ENSNO-001@1.0.0 \
    --split SS-COMPACT-01 --manifest dm-compact-<date>.json
{"part":"validation","events_planned":"<n>","usable":"<n>",
 "refusals":{"cohort_transition_unverified":"<n>","excluded_cohort_minute":"<n>",
             "missing_fresh_asof_family":"<n>","missing_own_no_quote":"<n>"}}

$ python -m scripts.hypolab run plan ... --config <config_id>  -> att-01H...
$ python -m scripts.hypolab run execute --attempt att-01H...
$ python -m scripts.hypolab run freeze  --attempt att-01H...
{"selection_sha256":"<64hex>","labels_opened":false}
$ python -m scripts.hypolab run evaluate --attempt att-01H...
$ python -m scripts.hypolab report render --hypothesis HX-ENSNO-001@1.0.0
```

The illustrative `report.json` excerpt below uses symbolic values only:

```json
{"outcome_class":"insufficient_data","strength":"exploratory",
 "reason":"graded_entry_dates < 10",
 "arms":{"HX-ENSNO-001:min_gap=0.05":{"entries":"N","entry_dates":"D",
   "scenarios":{"0.01:USD":{"net_pnl":"X","roi_cash_outlay":"X/C","ci95":null}}}},
 "labels":["full_fill_assumed","observed_fill=false","depth_checked=false"]}
```

---

## 6. Hetzner runner design

### 6.1 Principles

- **Research-only snapshot:** each run gets a **new** dated directory under the existing research root (named by logical role, never an absolute path in public text). The runner refuses if the directory exists, the same rule as `server_ops.py stage`.
- The code bundle and manifest are copied in and their hashes verified after copy. Inputs are referenced **read-only**: evidence databases are opened with `mode=ro` and `query_only=ON` (`S/adapter.py`), Parquet is read through committed catalogs only (`server_replay.committed_rows` pattern), and every input is hash-verified before use.
- **No production mutation:** no collector restart or configuration change, no timer or scheduler unit, no package install, no new credentials, no network acquisition. Existing operational file hashes are compared before and after the run (the `close_server.py` `operational_hashes` pattern), and the result is recorded in the receipt.

### 6.2 Resource bounds for the initial smoke (proposed, enforced in two layers)

| Bound | Outer (process manager) | Inner (in-process guard) |
|---|---|---|
| 1 process | Transient unit with task limit; no subprocess spawning in code | `multiprocessing` disallowed; assertion at start |
| 1 CPU thread | CPU quota 100 %; nice 15 | `OMP/OPENBLAS/MKL_NUM_THREADS=1`, `pyarrow use_threads=False` |
| 2 GiB memory | Memory max 2 GiB | Batch iteration (2,048-row batches as in `committed_rows`); RSS check per batch → abort `memory_guard` |
| 10 min wall | Runtime max 600 s | Monotonic deadline checks per phase (the pattern in `replay_rest15`) |
| 1 GiB output | — | Writer byte accounting across all outputs; abort at the cap with partial outputs marked `partial` |
| ≥ 20 GB free | Pre-launch check | Re-check every 30 s and before each write; abort if `free − remaining_output_budget < 20 GB` |
| Collector health | Pre-launch: health heartbeat fresh, not stopped, queue below threshold (the `server_ops` guard) | Re-check per phase; abort `collector_unhealthy` (read-only) |

The process manager is a transient unit created through the system's process manager, as the existing `server_ops.py` does with a 1,800 s limit; the smoke shortens this to 600 s. It persists nothing and creates no timer. Whether this transient unit counts as acceptable "non-scheduler" host usage, and whether the job may continue to run as the current privileged user, are **operator decisions** (§8.8).

### 6.3 Lifecycle semantics

- `runner stage`: create the directory, copy the bundle, verify hashes, write `stage.receipt.json`. No launch.
- `runner launch`: run the pre-launch checks, start the transient unit named `hypolab-<attempt_id>`, write `launch.receipt.json` with the proposed bounds.
- `runner status`: read unit state (active, sub-state, result, exit status, main PID, peak memory) and the progress file. Read-only.
- `runner stop`: graceful terminate, then forced kill after 30 s, through the transient unit only. Records `stopped_by_operator`, and the attempt journal marks `aborted`.
- `runner collect`: copy back **only** small derived outputs (manifest, selection hash, executions, evaluation, report, receipts), each within its own size cap. Bulk data never leaves the server.
- `runner cleanup --attempt ID`: removes only temporary files the attempt created inside its own directory (listed in `owned_files.json`). It never removes inputs, other attempts, frozen outputs or receipts. Retention or deletion of whole run directories is a separate operator decision.

### 6.4 Proposed versus measured

Every receipt has two blocks. `proposed_bounds` is copied from the manifest. `measured` holds `elapsed_s, exit_status, peak_memory_bytes, cpu_seconds, output_bytes, free_bytes_before/after, collector_health_before/after, operational_hashes_unchanged`. Reports quote `measured` values only from receipts. **This specification contains no measured values.** The only prior measured operations evidence is in the inputs: the extractions closed at their IO budgets (`data_contract.md`). It is cited as context, not as evidence for this runner. If a bound is insufficient, the run stops, reports `bound_exceeded:<which>` with its measurement, and proposes a revised research limit for operator approval. It never self-extends.

---

## 7. Report

### 7.1 Structure (`report.md`, with a matching `report.json`)

1. **Header:** hypothesis ID@version and hash, attempt IDs, manifest hashes, code commit, data as-of, split part, evidence floor, **strength label** (development-only / exploratory / confirmatory).
2. **Verdict:** one of **positive signal / negative result / insufficient data**, plus the predeclared rule text and which clause fired.
3. **Counts:** event-days planned, eligible, decided and entered; distinct market dates; trades per arm; P0/P1/P2/P3 payout grade counts; refusals by code and layer; paired exclusions.
4. **Economics per arm × fee mode × price stress:** gross PnL (before fees), fees, net PnL, cash outlay; **ROI on three named denominators**: gross notional ($1 × entries), cash outlay (includes USD fees), peak locked capital. Graded vs ungraded, unknown-payout bounds, max drawdown, max concurrent locked cash.
5. **Baselines:** B0–B4 side by side; paired difference with date-cluster CI; B2 null rank.
6. **Uncertainty:** date-cluster bootstrap CIs (or "not computed: < 10 graded dates"); per-date PnL table.
7. **Multiplicity:** configs tried (hypothesis, family), versions, unseal events, Holm-adjusted status.
8. **Data quality:** matrix planned/valid/tradable/unknown counts, excluded pre-r7 minutes, `cohort_transition_unverified` count, fee/terms disagreements, stale inputs, between-poll unknowns (REST15).
9. **Limits:** the fixed labels (conditional full fill, no depth, minimum-order flag counts, Gamma ≠ on-chain, weather certification status, partial projection, inspected dates), plus a free-text section that is never empty.
10. **Provenance appendix:** all attempt records, including failures.

### 7.2 Outcome classification (defaults proposed; fixed per hypothesis at registration)

- **Insufficient data** if any of these hold: fewer than `min_entry_dates` (default 20) P2-graded entry dates, or fewer than `min_entries` (default 30); fewer than 10 graded dates (no bootstrap); required adapter blocked; more than 50 % of entries P0; or a nondeterminism or integrity incident.
- **Positive signal** only if all of these hold: not insufficient; the primary metric's 95 % date-cluster CI lower bound is > 0 under **both** fee modes at the registered stress (default ask + 0.01); the paired difference versus the main matched baseline has CI lower bound > 0; and, if confirmatory, Holm-adjusted significance.
- **Negative result** if not insufficient and either the primary CI upper bound is ≤ 0 or the paired difference CI upper bound is ≤ 0.
- Anything else is **inconclusive**. It is reported under "insufficient data" with the sub-reason `ci_spans_zero`.
- **Strength:** confirmatory only on an unsealed, untouched test split with one config. Exploratory on validation or walk-forward. Development-only on any inspected date (all REST15/H4 results).
- **Mandatory sentence:** "A positive signal here is a research finding under conditional hypothetical full-fill assumptions; it is not a profit forecast and does not prove executability."

---

## 8. Reuse and migration plan

### 8.1 Reuse map (exact files)

| Existing file | Role in the lab | Treatment |
|---|---|---|
| `R/small_order.py` | Canonical $1 minute-mode kernel (`_account`, `_validate_quote`, `simulate_one_dollar`) | **Vendored unchanged**, hash-pinned |
| `S/small_order_rest_v3.py` | REST15 sweep kernel (first sweep, +60/+1,200, inventory, intervening metadata) | Vendored unchanged |
| `R/core.py` | `Record`, `AsOfView`, `Exposure`, `complementary_joint_bounds`, legacy `ReplayEngine` | Vendored unchanged; `Record`/`AsOfView` reused, engine kept as `legacy_depth/1` |
| `R/signals.py` | Mechanisms: `interval_probability`, `classify_revision`, `persistent_target_family`, `canonical_target_hash`, `two_regime`, `local_memory`, `remaining_maximum` | Vendored unchanged; a new `price_reaction` goes in a **new** file |
| `R/run.py` | `forecasts`, `probabilities`, `coherent_bins`, `best_gap` helpers | Pure helpers extracted by import only; no edits |
| `R/compact_matrix.py` | Matrix acceptance for N-COMPACT | Vendored unchanged |
| `src/compact_replay.py` | As-of state semantics for N-COMPACT | Logic reused through an adapter wrapper; `buy_one_dollar` diagnostic only |
| `src/server_replay.py` | L2 replay (`committed_rows`, `Replay`) | Not in $1 path; `committed_rows` integrity pattern reused for catalog reads |
| `S/adapter.py` (identical to `R/adapter.py`) | `Evidence` read-only views | Wrapped by L-REST15 / L-PROJ |
| `S/replay_rest15.py` | Reference REST15 v3 runner | **Equivalence oracle** (§8.4) |
| `S/build_index.py` | Metadata ID catalogue | Input to L-REST15 (existing index file, hash-pinned) |
| `R/extract.py`, `R/resume_extract.py` | Projection producers | Not re-run; their outputs are L-PROJ inputs |
| `R/skill_metrics.py` | Forecast skill census | Secondary report section |
| `R/available_coverage.py`, `S/cadence_tokens.py`, `S/diagnose.py` | Coverage/cadence diagnostics | Inform suitability; not re-executed by default |
| `R/freeze.py`, `R/server_ops.py`, `R/close_server.py` | Freeze and ops patterns | Patterns re-specified in `hypolab.registry` / `hypolab.runner` with no hard-coded hosts or keys |
| `R/protocol*.json`, `S/protocol_rest15_v3.json` | Prior registrations | Imported as **legacy registered hypotheses** (read-only) |

### 8.2 Smallest practical module structure (proposed, in the wea_ther repo)

```text
src/hypolab/
  __init__.py
  schema.py        # hypothesis/split/manifest/result validation + canonical hashing
  clocks.py        # availability rule, AsOfView construction, freshness checks
  adapters/
    base.py        # OwnQuote, Refusal enum, adapter protocol
    rest15.py      # wraps Evidence + metadata index + sweep clustering
    projection.py  # forecast/metadata/METAR rows + h4_exact set
    compact.py     # CompactAsOf-semantics state + compact_matrix acceptance + exclusions
  execution.py     # dispatches to vendored kernels; portfolios, capital, bounds
  baselines.py     # B0-B4, pairing, seeded draws
  splits.py        # split sets, walk-forward folds, seal/unseal checks
  registry.py      # hash-chained attempts/inspected/unseal journal, lock
  evaluate.py      # label join after freeze, metrics, bootstrap
  report.py        # markdown/json rendering, selective-reporting guard
  runner.py        # stage/launch/status/stop/collect/cleanup (no hard-coded hosts)
  vendor/          # unchanged kernels from section 8.1, plus VENDOR.json with SHA-256s
  mechanisms_new.py # price_reaction and other new pure signals
scripts/hypolab.py # CLI entry (argparse, mutually exclusive groups)
tests/hypolab/     # section 8.6
```

The vendored files keep their flat import style. `vendor/__init__.py` adds the vendor directory to the import path **only** inside the package, so the existing `from small_order import ...` lines work without edits and the file hashes stay identical.

### 8.3 Dependency and prerequisite risks

1. **Missing modules:** `src/server_replay.py` imports `src.continuous_weather.Book` and `src.server_store` (`packed`, `sha`); `src/compact_replay.py` imports `src.server_store.packed`. These are **not in the snapshot**. The compact adapter must either import them from the actual repository at a pinned commit (manifest-recorded) or reimplement `packed` and prove byte equality by test. Operator decision: which commit of wea_ther `src/` is canonical.
2. **Python version:** the kernels use `hashlib.file_digest` (Python ≥ 3.11) while the repository rule says 3.10+. The lab must pin ≥ 3.11 or add a shim. Operator decision.
3. **Duplicated files:** the `R/` and `S/` copies of `adapter.py`, `core.py`, `signals.py`, `run.py`, `small_order.py`, `extract.py` and `skill_metrics.py` are byte-identical by hash. Vendor them once and record both origins.
4. **pyarrow version** on the server venv must match the manifest. The runner reads the version and refuses on mismatch.
5. **Hard-coded server paths and module-level constants** in `S/replay_rest15.py`, `R/run.py` and the ops scripts: the lab passes logical paths through the manifest and never edits the originals. Equivalence runs execute the original scripts in a sandbox copy, never in place.
6. **The 640 exact H4 inputs and the 41 payout vectors** are asserted by the brief but not enumerated in the snapshot. Their manifests must be produced by the collection/research owner before H4 or P1/P2 evaluation.
7. **Pre-r7 exclusion list and r7 audit record** must exist as hash-bound files before N-COMPACT can run.

### 8.4 Backward compatibility and equivalence strategy

- **Kernel equivalence:** the vendored kernels must pass their original test suites unchanged (`R/test_small_order.py`, `S/test_small_order_rest_v3.py`, `R/test_core.py`, `R/test_signals.py`, `R/test_compact_matrix.py`, `R/test_adapter.py`, `R/test_skill_metrics.py`, `R/test_runner.py`, `S/test_replay_rest15.py`). The original test-file hashes are pinned.
- **REST15 v3 replay equivalence:** on the frozen REST15 development inputs, `hypolab` running the legacy-registered `NONSCALP-REST15-EXPLORATORY-v3` must reproduce `selection.frozen.json`, `census.json` and the arm summaries **byte-for-byte**, or field-equal after canonical serialization. Wall-clock fields like `elapsed_seconds` are excluded. Any difference blocks migration.
- **Fixture equivalence:** each existing handwritten accounting fixture (e.g. `test_handwritten_dollar_fee_accounting_payout_bounds_and_cost_reserves`, `test_handwritten_price_stress_recalculates_one_dollar_quantity_and_fees`) is re-run through `hypolab.execution` and must yield identical Decimal strings.
- **No meaning change:** a legacy protocol's field semantics (e.g. "first subsequent retained sweep") are copied into its legacy registration verbatim. The lab never reinterprets them.

### 8.5 Staged implementation plan (each stage needs operator approval; none is authorized by this spec)

| Stage | Content | Exit criterion |
|---|---|---|
| S0 | Vendor kernels, `VENDOR.json`, run the original tests | All original tests pass; hashes match the manifest |
| S1 | `schema`, `registry`, `splits` (local only, synthetic) | Chain/lock/seal tests pass; legacy protocols registered |
| S2 | `clocks` + three adapters on synthetic fixtures | Clock, leakage, refusal and own-NO tests pass |
| S3 | `execution` + `baselines` + capital/bounds | Fixture equivalence; baseline arithmetic tests |
| S4 | `evaluate` + `report` | Outcome classification tests; selective-reporting guard |
| S5 | CLI; REST15 v3 equivalence in a local sandbox on copied small derived inputs, or on the server under S6 bounds | Byte-equivalent reproduction |
| S6 | Runner; **one** smoke on the server under the §6.2 bounds, on a development split only | Receipt with measured bounds; operational hashes unchanged |
| S7 | Independent review: reproduce, inspect holdout/selection provenance, verify no collector mutation | Reviewer report naming the exact commit |

### 8.6 Meaningful tests (synthetic fixtures; `tmp_path`/`monkeypatch` style)

- **Clocks and future leakage**
  - T-CLK-1: a record with `received ≤ cutoff` but `imported_at > cutoff` is invisible.
  - T-CLK-2: `first_received > cutoff` is invisible.
  - T-CLK-3: `model_time` earlier than cutoff with receipt later stays invisible.
  - T-CLK-4: a source timestamp after receipt is rejected.
  - T-CLK-5: a DST day across a local-day boundary (extends `test_new_zealand_dst_local_day_clock`).
  - T-CLK-6: an unchanged price with an old change time is valid only with a healthy heartbeat; a cached replay cannot refresh it.
- **Labels:** T-LEAK-1: `evaluate` without a `selection_frozen` event refuses. T-LEAK-2: the adapter API exposes no label path (introspection test). T-LEAK-3: a walk-forward calibration label available after the fold start is excluded.
- **NO pricing:** T-NO-1: the NO entry uses the NO token's ask even when `1 − YES_bid` is cheaper. T-NO-2: a missing NO cell with YES present gives `missing_own_no_quote`, with no complement (mirrors `test_missing_no_tail_remains_missing_even_with_yes_present`).
- **Fees and terms**
  - T-FEE-1: fees disabled gives zero fee.
  - T-FEE-2: handwritten CTF vs USD cash and net shares.
  - T-FEE-3: `compact_replay` unrounded fee vs `_account` differ by ≤ 0.00001 per $1.
  - T-FEE-4: unknown or disagreeing terms refuse.
  - T-FEE-5: terms older than 6 h refuse.
  - T-FEE-6: fee-rate sensitivity is labelled and excluded from headline numbers.
- **Gaps and cohorts**
  - T-GAP-1: a gap between signal and entry rejects.
  - T-GAP-2: an epoch change rejects even when the entry quote is clean.
  - T-COH-1: a pre-r7 excluded minute is classified `excluded_known_invalid_cohort`, not a gap.
  - T-COH-2: a span containing a cohort-layout transition refuses with `cohort_transition_unverified`.
  - T-COH-3: skew > 5 s refuses.
  - T-COH-4: a duplicate cell cannot inflate coverage.
- **Payouts**
  - T-PAY-1: a P1/P2 binding mismatch gives P0 with bounds.
  - T-PAY-2: P2 PnL is computed without weather certification.
  - T-PAY-3: cash is never released below P3.
  - T-PAY-4: a hypothesis with `weather_certification_required=true` is refused when W is absent.
  - T-PAY-5: complementary bounds cover the hedged legs.
- **First entry:** T-FE-1: a bad first candidate with a good later one is rejected. T-FE-2: the first candidate outside the window is not replaced. T-FE-3: the second decision on the same (arm, event) gives `event_attempt_budget_exhausted`.
- **Splits:** T-SPL-1: a test range overlapping inspected dates refuses. T-SPL-2: a sealed record read without unseal refuses. T-SPL-3: a second unseal refuses. T-SPL-4: walk-forward folds respect the embargo.
- **Attempt journal:** T-JRN-1: a mutated past record fails `registry verify`. T-JRN-2: a crash mid-run leaves `abandoned`, and the history is kept. T-JRN-3: concurrent writers are blocked by the lock. T-JRN-4: rerunning an identical manifest with a different result logs `nondeterminism_detected`.
- **Baseline arithmetic:** T-BAS-1: B0 is exactly zero. T-BAS-2: the paired difference equals the treatment minus the baseline per unit by hand. T-BAS-3: paired exclusions are listed. T-BAS-4: the seeded B2 draw is reproducible.
- **Reproducibility:** T-REP-1: the same manifest twice gives an identical `result_sha256`. T-REP-2: shuffled input order gives an identical result. T-REP-3: the REST15 v3 equivalence oracle passes.
- **Refusal classification:** T-REF-1: every refusal code maps to exactly one layer. T-REF-2: an unknown code fails the schema. T-REF-3: report counts sum to decisions.
- **Outcome classes:** T-OUT-1: below 10 dates gives insufficient data without a CI. T-OUT-2: a CI fully above zero in only one fee mode is not positive. T-OUT-3: an upper bound ≤ 0 gives a negative result. T-OUT-4: a report missing a journaled arm refuses to render.

### 8.7 Acceptance for each later stage

The stage's tests are green, `registry verify` passes, a fresh clone reproduces from the manifest, and no file outside `src/hypolab/`, `scripts/hypolab.py` or `tests/hypolab/` changed.

### 8.8 Decisions requiring operator resolution

1. The canonical wea_ther commit supplying `src.server_store` and `src.continuous_weather` for compact adapter imports.
2. Python ≥ 3.11 pin, versus a shim for `hashlib.file_digest`.
3. Whether outcome-blind QA counting on test dates (daily audits) keeps those dates "untouched".
4. Defaults for `min_entry_dates` (20), `min_entries` (30), embargo (1 market date), test start (registration + 1 market date), and family-wise α (0.05).
5. The P2 definition of a "reliable" Gamma vector, specifically the required stability window before evaluation.
6. Conditions under which `cohort_transition_unverified` may be relaxed. Proposal: after one audited live transition is observed and validated.
7. Whether minimum-order applicability can be documented per market or protocol version to enable the compliant sensitivity.
8. Runner execution context: a transient process-manager unit (non-persistent, no timer) and the privilege level. A dedicated unprivileged account would be an access change and needs explicit approval.
9. Retention policy for run directories after collection.
10. Approval of the S0–S7 stages and the single S6 smoke.

---

## Tradeoffs

- **Vendoring unchanged kernels versus refactoring.** Vendoring preserves hash-provable equivalence and prior fixture meaning, at the cost of awkward flat imports and two windows (REST15 vs compact) that cannot share code. I chose provenance over elegance.
- **Typed refusals versus coverage thresholds.** A per-unit refusal census is verbose but honest. It lets a narrow hypothesis run on whatever data truly supports it, and it blocks none by fiat. The cost is reports with many counters.
- **Strict first-entry freeze.** This understates achievable PnL whenever a later quote would have been fine. It is still correct, because the alternative is selection on the outcome-correlated price path.
- **Holding full cash until P3** grossly understates capital efficiency, since no P3 exists today. It avoids recycling on unverified marks, and ROI is shown on three denominators so the reader sees the effect.
- **Hard sealing of test data** slows research. Prospective collection is needed before anything is confirmatory, so realistically no confirmatory verdict for weeks. This is unavoidable, because every existing date is already inspected.
- **Keeping below-minimum fills in the main analysis** honours the user-selected hypothetical mode but weakens executability relevance. The flag counts and the compliant sensitivity mitigate this.

## Three strongest risks

1. **Insufficient independent sample.** With $1 binary payoffs and date-clustered correlation, 20+ graded test dates may still give CIs spanning zero. The likely honest output for months is "insufficient data", and pressure to relax minimums or reuse development dates is the main leakage threat. Mitigation: registry-enforced inspected ledger, one-shot unseal, and minimums fixed at registration.
2. **Hidden cohort or clock defects in the compact archive.** Only one post-r7 cohort window is verified and no live transition has been observed. A silent defect, such as mis-cohorted NO tokens or validation timestamps refreshed by cached state, would contaminate every compact result. Mitigation: `cohort_transition_unverified` refusals, exclusion lists, heartbeat rules, and matrix acceptance per run. Residual risk remains until a transition is audited.
3. **Payout evidence weaker than it looks.** P1/P2 Gamma vectors are not on-chain proof. A systematic binding or resolution discrepancy would bias conditional PnL. Mitigation: strict literal binding, P-level labelling, unknown bounds always shown, and no cash recycling. A full fix needs P3 evidence that does not exist yet.

Secondary risks: missing `src.*` dependencies blocking S2; REST15 equivalence failing because of undocumented environment drift; and runner bounds proving too tight for the matrix validation of a full test window. In that last case the runner stops and reports, and does not expand its own limits.

## How this design can be falsified

- **Reproducibility claim:** fails if two runs of an identical manifest give different `result_sha256`, or if the REST15 v3 oracle cannot be reproduced byte-equivalently from frozen inputs.
- **Leakage claim:** fails if a test constructs a record with any availability clock after cutoff that a mechanism can observe, or if `evaluate` can run without a prior frozen selection, or if a sealed test record can be read without an `unseal` event.
- **Own-side pricing claim:** fails if any NO entry's ask is not traceable to a NO-token record, through the `selected_quote_id` lineage.
- **First-entry claim:** fails if any filled execution's quote is not the first in-window candidate for its decision.
- **No-overwrite claim:** fails if any journal or registry record can be altered without `registry verify` failing, or if a rerun replaces an existing output directory.
- **Suitability claim:** fails if a hypothesis is blocked by a criterion that its own registration does not require (a hidden universal threshold), or allowed despite a required input being absent.
- **Economic labelling claim:** fails if any report presents a hypothetical full fill, a Gamma-graded payout, or a development-date result as an observed fill, an on-chain payout or an independent validation.
- **Strategy level:** the design is working as intended if it returns "negative result" or "insufficient data" for every hypothesis when that is what the evidence says. It would be shown wrong if a confirmatory "positive signal" later failed on newer prospective dates under the identical frozen version. That would show the controls were insufficient, and the lab must record the failure and learn from it.