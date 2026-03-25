# Beating Polymarket weather brackets: a systematic edge framework

**The single highest-impact move is replacing your monthly-average sigma with the NBM's day-specific probabilistic output, which provides calibrated percentiles from ~203 ensemble members updated hourly — free, via NOMADS.** This alone closes most of the gap between your model's 2–5°F sigma and the market's implied 0.7–0.85°F, because on quiet high-pressure days NBM sigma genuinely drops to ~1.2–1.5°F, while on frontal days it widens to 4°F+. The market's overconfidence is real but *regime-dependent*: it misprice tails most severely during transitional weather, and your edge concentrates there. Layering real-time METAR tracking, model-update latency arbitrage, and ML-based conditional sigma estimation on top of NBM creates a multi-layered system where each component adds 5–20% CRPS improvement.

---

## The NBM is your most important upgrade — and it's free

The National Blend of Models is the single most underappreciated data source for this use case. NBM blends **31+ model systems** (GFS, GEFS, NAM, HRRR, ECMWF IFS and ensemble, Canadian GEM/GEPS, and others) into a calibrated probabilistic forecast with ~203 equally-weighted ensemble members. Critically, it outputs **day-specific percentiles** (1st through 99th) and **standard deviations** for MaxT — exactly the flow-dependent sigma your model lacks.

NBM data is available via NOMADS GRIB2 at `https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/`, AWS Open Data, and through the Herbie Python library (`pip install herbie-data`). The QMD (Quantile-Mapped Dressed) files contain the probabilistic output. Text bulletins with station-specific percentiles are also available. **NBM updates hourly**, giving you fresh uncertainty estimates 24 times per day — far more frequently than GFS MOS.

To compute bracket probabilities directly from NBM percentiles: fit a smooth distribution to the reported percentiles (1st, 5th, 10th, 25th, 50th, 75th, 90th, 95th, 99th), then integrate over each 2°F bracket. Alternatively, estimate σ from the percentile spread as **σ ≈ (P90 − P10) / 2.56**. This approach captures day-specific uncertainty without any historical calibration step — NBM has already done the multi-model blending and bias correction.

For independent cross-validation, the **ECMWF ensemble** (51 members) became fully open data on October 1, 2025 under CC-BY-4.0 at `https://data.ecmwf.int/`. Combined with GEFS (21 members from NOMADS), you have 72+ independent ensemble members. The **Open-Meteo Ensemble API** (`https://ensemble-api.open-meteo.com/v1/ensemble`) provides the simplest unified access: one JSON call returns all ensemble members from GEFS, ECMWF, ICON, GEM, and UKMO simultaneously, interpolated to any lat/lon.

**Implementation: weekend build.** Download NBM QMD for your three stations, extract percentiles, fit bracket probabilities. Compare against Polymarket prices. Expected improvement over monthly-average Gaussian: **20–40% CRPS reduction** based on literature comparisons of flow-dependent vs. climatological spread.

---

## Polymarket resolves from Weather Underground — know your exact stations

A critical and often-overlooked detail: Polymarket weather markets resolve using **Weather Underground daily history pages** for specific ICAO stations. The exact resolution sources are:

- **NYC → KLGA** (LaGuardia Airport), not Central Park (KNYC): `wunderground.com/history/daily/us/ny/new-york-city/KLGA`
- **Chicago → KORD** (O'Hare International), not Midway (KMDW): `wunderground.com/history/daily/us/il/chicago/KORD`
- **Miami → KMIA** (Miami International): `wunderground.com/history/daily/us/fl/miami/KMIA`

The metric is the **calendar-day maximum temperature** (midnight-to-midnight local time), rounded to whole °F. This creates a subtle but exploitable rounding edge: ASOS sensors record temperature in 0.1°C, which WU converts and rounds to whole °F. A reading of 18.4°C (65.12°F) and 18.9°C (65.6°F) both round to **66°F** — understanding the °C-to-°F mapping at bracket boundaries matters. The community tool **wethr.net** provides a purpose-built ASOS-to-°F converter for exactly this purpose.

Station-specific biases create persistent forecast errors. **KLGA** sits on Flushing Bay with Long Island Sound exposure — sea breeze onset (detectable as a wind shift to E/SE in METAR) can drop temperatures **9–10°F** on summer afternoons, and GFS frequently misses this. LaGuardia runs **2–4°F warmer** than Central Park on hot days due to runway asphalt, so forecasts referencing "NYC" from Central Park climatology will underpredict KLGA highs. **KORD** is within the Lake Michigan breeze penetration zone (~15 miles from shore); the lake suppresses highs by approximately **5°F** in spring/early summer when water temperatures remain in the 40s–50s°F range, and GFS at 28km resolution handles this poorly. **KMIA** is the most predictable of the three stations — narrow temperature variability in a maritime tropical airmass — but summer afternoon thunderstorms can cut highs short if they fire unusually early.

---

## Model-update latency arbitrage is the proven profitable strategy

The most documented edge in Polymarket weather markets is **latency arbitrage** — buying brackets after a model update shifts the forecast but before the market reprices. Trader "Hans323" extracted **$1.11 million** from a single London weather market using exactly this approach: monitoring weather APIs, detecting forecast changes, and buying massive positions in the minutes-to-hours window before market adjustment.

The timing windows are well-defined. GFS runs initialize at 00Z/06Z/12Z/18Z with output available **~3.5–5.5 hours later**. The 12Z GFS — the most impactful for next-day forecasts — starts posting around **5:00 PM ET**. ECMWF 12Z data arrives around 6–8 PM ET. HRRR updates every hour with output available in ~1.5 hours, providing the highest-frequency signal. NBM updates hourly. The **06Z GFS** (completing ~3–4 AM ET) represents the least-watched update window, with overnight Polymarket liquidity at its lowest.

The practical implementation: poll HRRR/NBM outputs hourly via NOMADS or Open-Meteo. When the updated forecast shifts the expected high by ≥1°F compared to current market pricing, compute new bracket probabilities and place trades. Several open-source bots already operate this way — the GitHub repository `suislanchez/polymarket-kalshi-weather-bot` uses a 31-member GFS ensemble from Open-Meteo, trades when edge exceeds 8%, and has generated up to $1.8K profit with a $100/trade cap using **15% fractional Kelly** sizing.

A complementary real-time edge: **intraday METAR monitoring**. ASOS stations report roughly every 5 minutes. If KLGA reads 82°F at 11 AM with 4+ hours of heating remaining and the forecast high is 82°F, higher brackets are underpriced. Access real-time METARs via the Aviation Weather Center API (`aviationweather.gov/api/data/metar?ids=KLGA&format=json`, free, ~5-minute latency) or the NWS API (`api.weather.gov/stations/KLGA/observations/latest`).

---

## ML post-processing turns day-specific sigma from good to excellent

While NBM percentiles provide a strong day-specific sigma baseline, ML post-processing can squeeze additional edge by learning **nonlinear patterns in forecast errors** that NBM's linear blending misses. The literature documents consistent improvements.

The most practical approach is **XGBoostLSS** (or LightGBMLSS), which extends gradient boosting to output full conditional distributions — both location (μ) and scale (σ) parameters simultaneously — optimized directly on CRPS loss. It supports Gaussian, Student-t, and other distributions natively. **NGBoost** achieved **39% CRPS reduction vs. raw ensemble and 7.5% vs. EMOS** for 2m max temperature. Neural network distributional regression (Rasp & Lerch, 2018) also outperforms classical EMOS, with the advantage coming from auxiliary predictor variables and nonlinear relationships.

The features that matter most for predicting day-specific forecast error magnitude, ranked by importance:

- **Ensemble spread** (single most predictive variable for conditional variance)
- **Recent forecast errors** at the station (autoregressive: yesterday's error predicts today's — the SAR-SEMOS approach achieves **97% CRPS improvement** over standard EMOS by modeling this)
- **Forecast anomaly** (forecast minus climatology — extreme departures have larger errors)
- **Run-to-run forecast consistency** (large changes between consecutive model runs signal uncertainty)
- **Cloud cover forecast and actual cloud state** (radiation budget uncertainty)
- **Wind speed and direction** (frontal proximity, sea/lake breeze probability)
- **Pressure tendency** (rapid changes indicate dynamic weather)
- **Day of year** (seasonal error characteristics)

Temperature forecast errors are **not perfectly Gaussian**. Studies find heavier tails than Gaussian (especially in winter with arctic outbreaks) and positive skewness in max temperature residuals. Switching from Gaussian to **Student-t** distribution improves tail bracket probabilities substantially with only one additional parameter. XGBoostLSS supports Student-t natively.

For training data, IEM archives GFS MOS, observations, and other products going back decades at `mesonet.agron.iastate.edu/mos/`. The `EUPPBench` benchmark dataset provides a ready-made training framework with code for all major methods at `github.com/EUPP-benchmark`. A **weekend prototype** using XGBoostLSS with 5–10 features trained on 3+ years of IEM data would already beat the monthly-average Gaussian approach. A **production system** (2–4 weeks) adds full feature engineering, ensemble spread integration, and proper time-series cross-validation.

---

## The market's overconfidence creates a structural tail-buying edge

The market's implied sigma of 0.7–0.85°F vs. calibrated sigma of 2–5°F represents a **3–7× overconfidence in forecast precision**. Academic research on prediction markets confirms this pattern: the Whelan (2025) study of 300,000+ Kalshi contracts found that contracts priced below 10¢ win far less often than 10% — investors buying these longshots **lose over 60% of their money**. However, the Polymarket weather market exhibits a different, potentially more exploitable pattern: the center bracket is overpriced (market too confident in the point forecast) while tail brackets are **underpriced relative to true probability**.

Consider the math: with a market-implied σ of 0.85°F, a bracket 4°F from the center gets ~0.1% probability. With a calibrated σ of 3°F (typical for a frontal day), that same bracket gets **~12% probability** — a 120:1 mispricing. Even on quiet days where σ genuinely narrows to 1.5°F, the 4°F-away bracket still has ~3% true probability vs. near-zero market pricing.

The optimal strategy is regime-dependent. **High-uncertainty days** (frontal passages, arctic outbreaks, sea breeze ambiguity) offer the widest mispricings because the market doesn't adequately widen its distribution. **Low-uncertainty days** (stable high pressure, light winds, clear skies) are where the market is closest to correct, and edges are thinnest. Detecting the regime in advance — via ensemble spread, NBM sigma, or synoptic pattern classification — tells you *when* to bet aggressively and when to sit out.

Weather regimes producing the largest forecast errors include **frontal timing uncertainty** (where a ±3–6 hour timing error can shift the high by 5–15°F), **cloud cover uncertainty** (overcast vs. clear sky can mean 5–10°F), and **boundary effects** (lake breeze at KORD in spring, sea breeze at KLGA in summer). NWS Area Forecast Discussions, accessible free via `api.weather.gov/products/types/AFD/locations/OKX` (NYC), `/LOT` (Chicago), `/MFL` (Miami), contain qualitative uncertainty signals — phrases like "low confidence" or "model disagreement" flag high-uncertainty days.

For bet sizing across 11 mutually exclusive brackets, the **multi-outcome Kelly criterion** is more aggressive than applying Kelly independently to each bracket. Whelan's analytical solution shows the optimal allocation across all brackets simultaneously can even include negative-expectation hedges. Practical implementations cap at **15–25% fractional Kelly** and $75–100 per trade given parameter uncertainty.

---

## Recommended implementation roadmap, ordered by edge-per-effort

**Tier 1 — This weekend (highest ROI):**
1. Replace monthly-average sigma with **NBM day-specific percentiles**. Download QMD data via Herbie or NOMADS. Compute bracket probabilities from the NBM percentile spread. Compare against Polymarket prices daily.
2. Set up **real-time METAR polling** for KLGA, KORD, KMIA via the Aviation Weather Center API. Build a simple tracker comparing current temperature trajectory to forecast high.
3. Monitor **model update timing** — set alerts for when 12Z GFS and ECMWF data becomes available (~5 PM and 6–8 PM ET). Check for significant forecast shifts vs. current market pricing.

**Tier 2 — Two to four weeks (significant additional edge):**
4. Build an **XGBoostLSS model** with Student-t distribution, trained on 5+ years of GFS MOS forecasts vs. KLGA/KORD/KMIA observations (from IEM archives). Key features: NBM sigma, GEFS spread, forecast anomaly, recent verification errors, wind direction, cloud cover.
5. Implement **automated latency arbitrage**: poll HRRR/NBM hourly, recompute bracket probabilities, place trades via Polymarket API when edge exceeds 8%.
6. Add **multi-model ensemble spread** from Open-Meteo Ensemble API (GEFS + ECMWF + ICON + GEM in one call) as a feature and cross-check on NBM.

**Tier 3 — One to three months (optimization):**
7. Weather regime classification using k-means on 500mb height anomalies, as a categorical feature in the ML model. ERA5 reanalysis provides the training data.
8. Station-specific seasonal models: KORD lake breeze detection (spring/summer E/NE wind + cold lake SST), KLGA sea breeze detection, KMIA early thunderstorm detection via GOES satellite.
9. NLP parsing of NWS AFDs for qualitative uncertainty signals ("low confidence," "significant model spread") as an additional feature.

## Conclusion

The core insight is that Polymarket weather markets suffer from a **structural overconfidence problem**, not a forecast accuracy problem. The market's point estimate is often excellent — it tracks the multi-model consensus closely. But it dramatically underestimates the *width* of the probability distribution, systematically underpricing tail brackets. Your edge doesn't come from a better point forecast; it comes from a **better-calibrated uncertainty estimate**.

NBM day-specific sigma is the foundation because it provides exactly what your monthly-average Gaussian cannot: a flow-dependent uncertainty estimate that widens during frontal passages and narrows during stable regimes. ML post-processing (XGBoostLSS with ensemble spread and autoregressive error terms) refines this further. Real-time observation tracking and model-update latency arbitrage add tactical edges on top of the strategic probabilistic advantage. The most profitable days will be those where the weather regime produces high uncertainty — frontal timing ambiguity, sea/lake breeze events, cloud cover uncertainty — and the market hasn't widened its distribution to match. Focus your capital there.