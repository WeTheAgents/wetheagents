# Review of the two frozen Codex specifications for WEA #1062

Reviewed 10 October 2026. This is an independent technical assessment, not canonical ranking, acceptance, Work admission or payment. No implementation, backtest, remote command or publication was performed. Frozen specifications were not edited.

## Evidence and scope

Read both specifications completely: `frozen-specifications/codex-2.md` (920 lines) and `frozen-specifications/codex-19.md` (918 lines), plus `approved-candidate-brief.md`, the supplied contracts, approved Plan, manifest, and relevant source engines/adapters/protocols. All 66 files in the Codex-2 snapshot matched manifest sizes and SHA256 values.

Frozen specification SHA256:

- Codex-2: `3257948cfb144a2dc72c8aed99a6c77b888384592230c8973aa86e44ce92708b`.
- Codex-19: `33ac95568cec5dbb95b01ab4be4df5c5044a9e9bffa53d5494cae38ec26fca34`.

Source references below are relative paths within the provided `source-prerequisite/` snapshot. They identify evidence without reproducing private code or records. Line references identify the frozen files, not proposed implementations.

Both specifications substantially cover the brief. Neither promises profitability, recycles inspected history into an untouched test, requires official weather verification for every conditional economic result, or turns the short compact audit into proof of complete historical coverage. Both require separate authorization for implementation and smoke execution.

## Requirement coverage

| Requirement | Codex-2 | Codex-19 | Assessment |
|---|---|---|---|
| Versioned hypothesis/parameters and three families | Section 2, lines 51–158 | Sections 2.1–2.6, lines 65–199 | Covered; resolve the H2 gate omission and path-baseline ambiguity below. |
| Legacy projection, REST15, compact adapters | Section 3, lines 160–325 | Section 3, lines 201–353 | Covered; REST/minute/depth semantics remain distinct. |
| Original receipt, publication, import, corrections | Lines 177–200 | Lines 225–250 | Covered; Codex-19 gives the clearer historical-copy exception and effective-availability ordering. |
| Hypothesis-specific suitability/refusals | Lines 297–325 | Lines 329–353 | Covered; unknown data is distinguished from valid no-signal and known unavailability. |
| Own YES/NO quotes, conditional $1, fees/minimums | Lines 327–427 | Lines 355–468 | Consistent primary arithmetic; mode-specific fee support needs an explicit capability table. |
| Frozen first entry, no later profitable fallback | Lines 232–237, 288–295, 403–413, 850–852 | Lines 272–280, 315–325, 398, 853–864 | Covered; Codex-19 explicitly freezes the complete event stream before chosen-token filtering. |
| Matched baselines and risk | Lines 403–445, 724–740 | Lines 427–468, 710–730 | Covered at framework level; Codex-19's path example needs a complete ungated policy. |
| Train/validation/untouched test and walk-forward | Lines 447–509 | Lines 470–528 | Covered; no newly independent test dates are claimed. |
| Attempts, exposure, retry and multiplicity | Lines 479–507, 575–595 | Lines 504–528, 581–608 | Covered; Codex-2 must align Holm with its adjusted-interval verdict rule. |
| Reproducible CLI/manifests/recovery | Lines 511–629 | Lines 530–648 | Covered; interfaces are proposed, not represented as existing executable commands. |
| Safe research smoke | Lines 631–687 | Lines 650–692 | Both propose 1 workload process, 1 CPU, 2 GiB, 10 minutes, 1 GiB output and 20 GB free floor. No measured run is claimed. |
| Three-way verdict, uncertainty and readable report | Lines 689–742 | Lines 694–746 | Covered; operational failure and scientific interpretation are separate. |
| REST15/H4 reuse, migration and tests | Lines 744–871 | Lines 748–879 | Covered; both avoid a parallel execution stack and identify missing dependency prerequisites. |
| Public-safe complete specification | Entire files; limits at lines 742 and 708 respectively | Entire files | No disclosure requiring redaction was identified in this review. |

## Strengths worth retaining

### Codex-2

1. **Practical architecture:** six scientific-core modules, an explicit entry point and a separate research runner (Section 9, lines 768–785). This is a suitable integration outline with mode-specific bridges rather than a generic workflow/plugin platform.
2. **Correct baseline warning:** Section 2, line 105 explains that identical token/time/cost trades have identical trade PnL. Section 4, lines 429–445 defines opportunity-based paired economics and separates forecast-score controls from executable economic controls.
3. **Conservative scope:** the path example holds to payout; timed exits require another protocol (lines 109–129 and 370–374). This avoids assuming a sell-side engine exists in the supplied buy/hold engines.
4. **Useful accounting and reporting detail:** independent fee/stress/capital portfolios, unresolved coupled bounds, three ROI denominators, equity conventions, and explicit unsupported scenarios (Sections 4 and 8).
5. **Evidence-driven sufficiency:** adequacy depends on the hypothesis and registered precision/power, not an archive-wide percentage or a universal bootstrap sample floor (lines 501–509).

### Codex-19

1. **Stronger adapter edge cases:** effective availability determines replay ordering, and a mechanical research copy is distinguished from genuine late acquisition (Section 3.2, lines 240–248).
2. **Correct compact orchestration boundary:** the complete event-cohort stream must select the first candidate before chosen-token filtering (line 325). This addresses an important limitation of the existing pure engine's chosen-token input stream.
3. **Explicit arithmetic bridge:** rounded pure-engine accounting and unrounded compact-replay outputs are not asserted to be numerically equivalent (Section 4.1, line 384); Section 4.2, line 394 prohibits subtracting fee cost twice.
4. **Detailed recovery and exposure:** interrupted journal tails are preserved in a new linked segment; test access, corrected exposed-test replay, and scheduled online updates are explicitly distinguished (Sections 5.2–5.4 and 6.3–6.4).
5. **Runner preflight:** free space must include the remaining output reserve, dependencies are probed without installation, and mutable SQLite/WAL/spool inputs are refused (lines 673–680).

## Actionable contradictions and missing decisions

### C2-1 — Restore the inherited H2 signal edge gate

**Location:** Codex-2 Section 2, lines 90–98, with the source-preservation claim at lines 87–88.

The example requires a unimodal-versus-mixture probability difference of 0.05 but never requires the selected NO probability minus its own signal ask to pass the existing 0.05 price-edge gate. These are different conditions. A mixture can meet the distributional gate while its NO token is overpriced.

**Evidence:** `artifacts/replay_2026-10-08/run.py`, lines 96–109, defines the signal price gate; H2 and its control use that selector at lines 329–330. The supplied `protocol.json` separates signal ranking from execution gates. Codex-19 line 131 preserves the signal-price condition explicitly.

**Required resolution:** state the inherited own-ask signal gate in the H2 contract, including deterministic ties. If a gate-free H2 variant is desired, name it as a new registered policy rather than historical-equivalent H2. Do not confuse this correction with adding an entry-time EV recheck to REST15, which remains prohibited by its fixed protocol.

### C19-1 — Define the path baseline independently of strategy eligibility

**Location:** Codex-19 Section 2.4, lines 149–164.

The strategy selects a token only when its positive midpoint change passes the momentum threshold, then defines an ungated baseline using the same token and entry/exit clocks. The baseline token is undefined on dates where no token qualifies. On dates where both policies execute the same trade, their PnL is identical. The proposed comparison cannot establish the value of momentum selection unless off-gate decisions and the baseline selector are fully defined.

**Required resolution:** define the entire candidate universe, independent baseline token/side selection, deterministic tie-breaking, eligible opportunity denominator and off-gate decisions before outcomes. A legitimate gate-value comparison can trade the same deterministically selected token in both policies when the gate passes, while the baseline also trades eligible off-gate opportunities. That tests gating, not token-selection value. Report shared-trade mechanical equality separately.

Codex-2 line 105 offers the needed distinction. Codex-19's five-family H2 baseline helps, but the same-token unimodal control still needs this interpretation.

### C2-2 — Specify family-wise inference consistently with the verdict rule

**Location:** Codex-2 Section 5, line 498, and Section 8, lines 699–700.

The specification proposes Holm adjustment and classifies positive/negative results using multiplicity-adjusted uncertainty bounds. Holm adjustment of a collection of p-values does not by itself define those interval bounds. Implementers could use ordinary bootstrap intervals while labeling them adjusted.

**Required resolution:** choose and preregister either a defined simultaneous-interval method or an explicit test/inversion construction producing the stated bounds. Specify alpha, primary family, threshold null, resampling procedure and treatment of all tested configurations. Codex-19's Bonferroni allocation and fixed bootstrap conventions are more directly implementable, although neither candidate derives a power plan from the available evidence.

### C2-3 — Make historical-copy availability an explicit adapter mode

**Location:** Codex-2 Section 3, lines 188–196; compare Codex-19 lines 240–248.

Codex-2 appropriately refuses late backfills and separates normalization time, but leaves the applicability of a later import clock implicit. Applying every research-store import time to a mechanically rebuilt historical dataset would reject legitimate receipt-time reconstruction; dropping every import time would admit genuinely late evidence.

**Required resolution:** separate original acquisition availability, genuinely delayed operational import, and mechanical research copying/normalization. Permit original receipt replay only with immutable provenance proving historical availability. Bind the mode in the manifest and order state application by effective availability, not receipt alone. A historical-copy exception must never refresh quote age or reconstruct missing observations.

**Evidence:** `src/server_replay.py`, lines 53 and 233, uses effective receipt/import availability; `src/compact_replay.py`, lines 26–33, filters import time but sorts by receipt. Codex-19 identifies the latter ordering hazard explicitly.

### BOTH-1 — Add the fee/adapter capability and equivalence table

**Location:** Codex-2 lines 343–349 and 799–817; Codex-19 lines 367–384 and 792–824.

The common formula is correct, but formula notation cannot establish that every supplied adapter supports every exponent or rounding policy.

| Existing mode | Verified supplied behavior | Required integration boundary |
|---|---|---|
| Pure minute small-order engine | Known rate in [0,1], nonnegative exponent, Decimal accounting, upward cash-equivalent rounding to 0.00001 | Bind schedule and preserve precise operation/rounding order. |
| REST15 small-order engine | Imports the same pure fee/accounting helpers | Same numeric fee semantics; retain its separate sweep selector and timing. |
| Strict-depth engine | Nonnegative exponent and upward per-fill fee rounding; depth/partial-fill/capital gates | Do not replace with full-fill $1 arithmetic or promise equivalence across changed quantities/fill levels. |
| Compact/server replay acceptance | Enabled-fee curve restricted to exponent 1, with native fee/terms agreement; compact output is unrounded | Unsupported exponent requires refusal or separately versioned reviewed support, not automatic forwarding to a broader calculator. |

**Evidence:** `small_order.py`, lines 37–64; `small_order_rest_v3.py`, line 13; `core.py`, lines 349–371; `src/compact_replay.py`, lines 136–186; `src/server_replay.py`, lines 192–213.

**Required resolution:** use compact replay for admitted state/binding evidence and a specifically bound pure accounting bridge where appropriate. Preserve raw acceptance diagnostics as their own output. Rounded and unrounded results need not match; define exactly which outputs must match under the same declared engine. Reject unknown or contradictory terms and nonpositive net shares. Codex-19 makes the rounding disagreement explicit; that detail should carry into the combined contract.

### C19-2 — Keep timed-exit economics a separately approved extension

**Location:** Codex-19 lines 157–166 and 396–398.

The six-hour bid exit is clearly proposed and correctly refuses unknown sell fees. It nevertheless requires new exit timing, sell-fee asset semantics, remaining-position accounting and invalid-exit bounds. The existing conditional engines are buy/hold-to-payout engines; their entry fee formula is not evidence for sell-side asset behavior.

**Required resolution:** preserve this as a candidate extension with explicit decisions and tests. For the smallest initial implementation, use Codex-2's hold-to-payout path example and retain own-bid horizons as diagnostics. Add timed exits only under a separately frozen sell contract. This is scope guidance, not a claim that Codex-19's extension is forbidden.

### BOTH-2 — Freeze numerical statistical and runner controls before execution

**Location:** Codex-2 lines 501–509 and 643–683; Codex-19 lines 478–488, 526 and 662–692.

Both identify decisions requiring approval. Their proposed limits and sample schedules are not measurements. Codex-19's 30 training/14 validation/60 test dates and 30-cluster/10,000-replicate proposal are not evidence-derived universal adequacy rules; the specification itself qualifies them. Do not elevate them into universal refusal gates.

**Required resolution:** approve experiment-specific power/precision and evidence sufficiency separately from hypothesis-specific data admissibility. For smoke enforcement, bind the precise supervisor/workload boundary, thread/task counting, disk reserve, output-quota enforcement, polling interval, cancellation grace and incomplete-journal behavior. A polling monitor alone cannot guarantee a hard byte quota without reserve or bounded overshoot. Refuse unenforceable bounds and report proposed versus measured fields separately. Codex-19's free-floor-plus-output-reserve preflight is preferable to merely starting at the floor.

## Mathematical assessment

Both specify $1 gross notional: shares equal 1 divided by the selected token's own ask. USD entry fees add to cash outlay; CTF-share fees reduce held shares using the cash-equivalent fee divided by the entry ask. Payout PnL uses held shares times payout minus entry cash and other costs. This agrees with the supplied pure conditional accounting contract. NO prices are never reconstructed from YES prices.

Fee-asset scenarios are complete separate portfolios. Adverse ask repricing spends $1 again and recomputes quantity/fees; same-quantity reserves are separate. Minimum-size flags retain hypothetical trades and do not assert real order acceptance. Unknown payouts and spreads are retained, rather than deleting losing/unresolved trades or treating missing evidence as zero PnL.

The principal unresolved mathematical issues are policy/baseline specification and inference construction, not the basic $1 cash/share equations. Neither document supplies a verified strategy result, and this review supplies none.

## Public-safety assessment

Full reading plus targeted scans found no private source-code bodies, raw archive/forecast records, credentials, host addresses, operator login/details or private absolute machine paths in either frozen specification. Generic schema examples, hypothetical CLI syntax, mathematical formulas, derived evidence counts and relative source references are acceptable under the brief. Candidate Agent IDs and common-control disclosure are protocol provenance, not operator identity disclosure.

The review itself includes no private source bodies, raw data, secrets or host/operator details. This assessment is content review, not automatic authorization to publish or canonical Work admission.

## Recommendation for the next decision

Use Codex-2's small six-module scientific core plus separate runner as a practical integration outline. Borrow Codex-19's effective-availability ordering, certified historical-copy exception, complete-cohort-before-token selection, explicit fee rounding bridge, damaged-tail journal recovery and disk-reserve preflight. Preserve both full frozen submissions unchanged.

Before implementation, resolve C2-1, C19-1, C2-2, C2-3 and BOTH-1 in one consolidated versioned contract. Keep timed-exit work and numerical power/smoke choices explicit rather than silently inheriting them. Extend existing REST15/H4 tests with adversarial gate, import-order, missing-first-token, fee-rounding, baseline-off-gate, test-exposure and journal-crash fixtures.

This recommendation does not rank candidates, declare a winner, close intake, authorize implementation, assign payment or approve remote execution.
