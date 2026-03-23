# Building a weather prediction market trading system with biased ML triage and LLM debate

**A hybrid architecture combining regime-dependent ML models with multi-agent LLM debate can exploit systematic forecast biases in Kalshi's temperature markets, where thin liquidity and retail-dominated order books create persistent mispricings.** The system maps proven meteorological bias-correction techniques (MOS, EMOS) onto a sports-prediction-inspired segmentation framework, routes each forecast through specialized ML experts, then passes disagreements to an LLM debate layer for final probability estimation. This report synthesizes actionable findings across market structure, data sources, model architecture, and trading strategy—including specific URLs, formulas, and design recommendations.

---

## Kalshi temperature markets offer 17+ cities with exploitable structure

Kalshi's daily temperature markets cover **17 cities** for daily high temperature and **7 cities** for daily low temperature, all resolving against the **NWS Daily Climate Report (CLI product)** at specific weather stations. NYC (Central Park/KNYC) leads with ~$144K daily volume; Miami (~$99K), LA (~$73K), Austin (~$58K), and Chicago (~$57K) follow. Total daily temperature volume across all markets runs **$700K–$1M+**.

Each city's market splits into **6 mutually exclusive brackets**: four inner brackets of 2°F width centered on the forecast high, plus two open-ended tail brackets. Contracts pay $1.00 if the temperature falls in that range, $0.00 otherwise. Prices range $0.01–$0.99, so bracket prices across all six should sum to approximately $1.00. Markets open at **10:00 AM ET the day before** and settle at **10:00 AM ET the following morning** once the NWS CLI report publishes.

**Resolution mechanics create exploitable nuances.** The NWS uses **Local Standard Time (LST), not clock time during DST**—meaning during daylight saving, the high-temperature recording window runs 1:00 AM to 12:59 AM local, not midnight-to-midnight. Many retail traders don't know this. Resolution uses the specific station (Central Park for NYC, Midway Airport for Chicago, Miami International for Miami, Austin-Bergstrom for Austin), and micro-climate effects at these stations can diverge from general city forecasts. If the CLI high temperature is inconsistent with METAR observations, settlement delays to 12:00 PM ET—creating additional information asymmetry.

Fee structure favors makers: **taker fees** follow `ceil(0.07 × C × P × (1-P))`, maxing at ~$0.02/contract at mid-market (~1.75%), while **maker fees** are roughly one-quarter of taker fees. The UCD study (Whelan et al., 2026) analyzing 300,000+ Kalshi contracts found **makers earn systematically higher returns than takers** across all categories. This means limit orders should be strongly preferred.

The most actionable edge indicator from existing research: a **favorite-longshot bias** where low-probability brackets (<10¢) lose 60%+ of invested money, while high-probability brackets earn small positive returns. This mirrors the "upset" segment in the biased-expert framework.

---

## The data pipeline starts with IEM MOS Archive—the single most critical resource

Building the biased expert system requires paired datasets of **forecasts and actual observations**. The Iowa Environmental Mesonet (IEM) MOS Archive at `mesonet.agron.iastate.edu/mos/` is the single most valuable resource, providing GFS MOS forecasts paired with observations for thousands of US stations from **December 2003 to real-time**. It includes GFS MOS, NAM MOS, GFS LAMP, GFS Extended (MEX), and the National Blend of Models (NBE/NBX), accessible via CSV/JSON APIs. This eliminates the need to manually align forecast and observation datasets.

For raw observations, **GHCN-Daily** provides daily TMAX/TMIN from 100,000+ stations via NOAA's Climate Data Online API (`ncdc.noaa.gov/cdo-web/webservices/v2`) and AWS Open Data (`s3://noaa-ghcn-pds/`). The **Integrated Surface Database (ISD)** adds hourly resolution from 35,000+ stations, also on AWS (`s3://noaa-isd-pds/`). For Kalshi-specific station data, the **Iowa Environmental Mesonet ASOS archive** (`mesonet.agron.iastate.edu/ASOS/`) provides 1-minute observations at airport stations matching Kalshi's resolution sources.

Raw GFS ensemble forecasts—essential for computing model spread and regime indicators—are archived on **NCAR's Research Data Archive** (`gdex.ucar.edu/datasets/d084001/`, 614 TB of 0.25° grids from 2021-present) and mirrored on AWS (`noaa-gfs-bdp-pds.s3.amazonaws.com`). ECMWF's **ERA5 reanalysis** (`cds.climate.copernicus.eu`) provides the gridded "truth" layer for regime classification using 500mb geopotential height fields, accessible via Python's `cdsapi` package. For real-time ensemble data, the **Open-Meteo API** (`open-meteo.com`) provides free access to the 31-member GFS ensemble—the same source used by the most successful open-source Kalshi trading bot.

**Documented systematic biases to exploit include**: GFS cold bias of **1.5–1.8°C at 00 UTC** (NCEP Office Note 520); ECMWF underestimation of diurnal amplitude by **1–2K in summer**; consistent geographic biases where the Americas are predicted too cold while North Africa runs too warm; and station-specific effects like urban heat island underrepresentation, coastal sea-breeze aliasing in coarse models, and cold air damming along the Appalachians. IBM's bias correction study found GFS biases are "fairly consistent with time," enabling stable training targets—and bias correction alone reduced MAE by ~50%.

---

## Three-segment triage maps baseball logic onto weather regimes

The baseball analogy—training separate models on "favorite wins big," "close game," and "upset" segments—maps naturally onto weather forecast verification patterns. The segmentation uses three factors: **weather regime stability**, **ensemble spread relative to climatology**, and **historical forecast error magnitude** for the current conditions.

**Segment A ("Favorite wins big"): Quiescent, high-confidence regimes.** Persistent high-pressure patterns with clear skies, large ensemble agreement (spread below climatological 25th percentile), no nearby frontal boundaries, and well-sampled climatological conditions. MOS excels here. Feature indicators include low ensemble spread, high regime persistence probability, no precipitation forecast, and large distance from nearest front. Strategy: consensus forecasts are reliable, and market prices likely reflect true probabilities. **Limited edge, but high confidence for baseline positioning.**

**Segment B ("Close game"): Transitional, moderate-uncertainty scenarios.** Moderate ensemble spread (near climatological mean), regime transitions occurring or imminent, frontal passages expected within 12–24 hours, and cloud cover changes affecting the diurnal cycle. EMOS/BMA calibration provides genuine probabilistic edge here because raw ensemble spread is systematically **underdispersive (overconfident)**. The calibrated uncertainty from EMOS often differs meaningfully from market-implied probability.

**Segment C ("Upset"): Conditions historically prone to forecast failure.** Cold air damming events, snow cover transitions, sea-breeze effects at coastal stations, temperature inversions under calm clear nights, near-record temperatures, and post-precipitation soil moisture anomalies. Ensemble spread is typically high, and model members disagree on the regime classification. **This is where maximum prediction market edge exists.** The NWS Oklahoma study showed MOS forecast errors >10°F are much more likely warm (too high) than cold, creating directional bias that can be systematically exploited. During the 2022 UK heatwave, NWP models produced improbably high temperatures due to overdrying of modeled soils—illustrating how physical process errors create predictable forecast failures.

**Implementation requires a regime classifier.** Train a gradient-boosted classifier on historical forecast-verification pairs to assign each incoming situation to Segment A, B, or C. The target variable is forecast error magnitude binned into terciles. Key features: ensemble spread (absolute and relative to climatological spread), current weather regime (from 500mb PCA + k-means on ERA5 data, following Lee 2023's 4-regime North American classification), distance to nearest front, snow cover, soil moisture anomaly, wind speed at surface, and trailing 7-day model bias at the station. Each segment then gets its own specialized correction model: Segment A uses standard EMOS with tight variance; Segment B uses regime-conditional EMOS/BMA with enhanced spread recalibration; Segment C uses specialized models trained exclusively on historical bust events.

The EMOS framework (Gneiting et al., 2005) provides the mathematical foundation. For temperature, it fits a Gaussian predictive distribution where the **mean** is a bias-corrected weighted sum of ensemble members and the **variance** is a linear function of ensemble variance: σ² = b₀ + b₁·S². Coefficients are fitted by minimizing the Continuous Ranked Probability Score (CRPS). Recent extensions like SAR-SEMOS (Jobst et al., 2024) that account for seasonality, trend, and autoregressive errors outperform basic EMOS by **97% in CRPS**—a massive improvement worth incorporating.

---

## The LLM debate layer adds reasoning over ML outputs, but design choices matter enormously

The most important finding from LLM forecasting research is counterintuitive: **prompt engineering has minimal to nonexistent effect on LLM forecasting performance** (Schoenegger et al., 2025, tested across frontier, reasoning, and efficient models with multiple prompt strategies including superforecaster-authored prompts). The gains come instead from retrieval quality, agent diversity, and aggregation architecture.

The strongest empirical results for LLM forecasting come from three key studies. **"Wisdom of the Silicon Crowd"** (Schoenegger, Park, Tetlock et al., Science Advances 2024) showed an ensemble of 12 diverse LLMs achieved forecasting accuracy **statistically indistinguishable from the human crowd** on Metaculus questions—and simple averaging of LLM + human forecasts outperformed either alone. **Halawi et al.** (NeurIPS 2024) built a 3-stage retrieval-reasoning-aggregation pipeline where GPT-4 neared competitive forecaster accuracy (Brier 0.179 vs. crowd 0.149), and on questions with good retrieval data, **the system outperformed the human crowd**. ForecastBench results show GPT-4.5 achieving Brier 0.101, with linear extrapolation suggesting LLMs may reach superforecaster levels before May 2027.

For the debate architecture specifically, research supports **3–5 heterogeneous agents with role-based specialization** (A-HMAD, Zhou & Chen 2025, showed 4–6% accuracy gains over homogeneous debate and 30%+ reduction in factual errors). **Debates should be limited to 1–2 rounds** (Wu et al., 2025 found diminishing returns beyond one pass; Du et al., 2023 showed 3 agents × 2 rounds was the optimal cost-performance point). **Confidence scores should be hidden between agents** to prevent cascading overconfidence.

A critical caveat: Lu (2025) found that debate/narrative formats **can degrade predictive accuracy** compared to direct structured queries. The recommended mitigation is to use debate for **reasoning generation only**, then feed debate transcripts to a separate aggregator judge that produces the final probability estimate independently.

The recommended agent roles for the weather system:

- **Agent 1 (Temperature Bull)**: Argues for the higher temperature / YES on threshold exceedance, emphasizing factors like urban heat island, clear skies, model cold biases
- **Agent 2 (Temperature Bear)**: Argues for lower temperature / NO, emphasizing cloud cover, frontal cooling, model warm biases
- **Agent 3 (Climatological Anchor)**: Anchored to historical base rates and conditional climatology for the regime
- **Agent 4 (Model Ensemble Interpreter)**: Synthesizes NWP ensemble outputs, spread-skill relationships, and weather foundation model predictions (GraphCast, Pangu-Weather, GenCast)
- **Optional Agent 5 (Contrarian)**: Challenges consensus, specifically looking for forecast bust scenarios matching Segment C conditions

Each agent receives a structured data package—not raw numbers—using the AI-Meteorologist approach (2025) of serialized weather tables with contextual metadata. The aggregation layer uses either a learned consensus optimizer (A-HMAD style) or trimmed mean (Halawi et al.), with post-hoc calibration via isotonic regression.

---

## Kelly sizing and the NO-biased strategy define practical trading execution

The Kelly criterion for binary contracts simplifies to **f* = (p − P_m) / (1 − P_m)**, where p is your estimated true probability and P_m is the market price. For a contract priced at $0.40 where your model estimates 55% true probability, full Kelly recommends 25% of bankroll. But **full Kelly is dangerously aggressive** given probability estimation uncertainty.

The most successful open-source weather bot uses **15% fractional Kelly** (0.15× full Kelly), capped at $100 per trade and 5% of bankroll per position. It requires a **minimum 8% edge** (|p − P_m| > 0.08) before entering any trade. These parameters have produced reported profits of ~$1,325 on modest capital. A practitioner analysis by Chris Dodds found that **YES trades on Kalshi weather markets almost always lose** (12–25% win rate regardless of edge cutoff), while a **NO-only strategy yielded ~86% win rate in backtesting**—aligning with the favorite-longshot bias documented academically.

Practical position sizing rules that emerge from the research:

- **Minimum viable edge of ~5%** for taker orders, ~3% for maker orders, after accounting for the fee formula `ceil(0.07 × C × P × (1−P))`
- **Maximum $100 per trade** in current liquidity conditions; weather markets can absorb ~$50–100/day per city per bracket before moving the market
- **Diversify across cities** but account for correlation—the same frontal system affects NYC, Philadelphia, and Boston simultaneously
- **Day-ahead trades after new model runs** (GFS initializes at 0z, 6z, 12z, 18z UTC, available ~3.5 hours later) offer the best edge; same-day trades have narrower margins
- **Track Brier score continuously** to evaluate probability calibration and adjust the fractional Kelly multiplier accordingly
- **Blacklist problematic city/season combinations** where your model consistently underperforms (LA marine layer, Miami convective storms)

The OU process temperature model from weather derivative pricing theory (Alaton et al., 2002; Benth & Šaltytė-Benth, 2005) provides the theoretical framework: **dT(t) = κ(θ(t) − T(t))dt + σ(t)dW(t)**, where θ(t) captures seasonal mean with Fourier harmonics and a linear warming trend. For binary Kalshi contracts, the fair price equals P(T_max > X), extracted from the calibrated CDF of the temperature distribution. Neural network approaches (Tallarico, 2024) that replace the parametric OU model with learned density estimation have shown they "materially shift derivative fair values" compared to traditional approaches.

---

## The complete system architecture, from data ingestion to trade execution

The full pipeline integrates all components into a coherent trading system:

```
[Data Ingestion Layer]
├── GFS 31-member ensemble via Open-Meteo API (real-time)
├── IEM MOS Archive (historical training data, 2003–present)
├── GHCN-Daily + ISD (observation ground truth)
├── ERA5 500mb heights (regime classification)
├── NWS CLI reports + METAR observations (resolution data)
└── Weather foundation model outputs (GraphCast, GenCast)

[Regime Classification Layer]
├── 500mb PCA + k-means → Weather regime assignment
├── Ensemble spread computation (absolute + relative to climatology)
├── Frontal analysis features (distance, advection, gradient)
└── Random Forest/XGBoost classifier → Segment A/B/C assignment

[Biased Expert ML Layer]
├── Segment A model: Standard EMOS, tight Gaussian calibration
├── Segment B model: Regime-conditional SAR-SEMOS (Jobst 2024)
├── Segment C model: Specialized bust-event bias correction
└── Output: Calibrated probability distribution for each bracket

[LLM Debate Layer (Segment B and C only)]
├── 3-4 heterogeneous agents with role-based specialization
├── Structured data packages per AI-Meteorologist approach
├── 1-2 debate rounds with hidden confidence scores
├── Aggregation: Trimmed mean + isotonic calibration
└── Output: Final probability estimate per bracket

[Trading Execution Layer]
├── Edge calculation: p_model − p_market per bracket
├── Filter: Minimum 8% edge, NO-biased preference
├── Sizing: 15% fractional Kelly, max $100, max 5% bankroll
├── Execution: Maker (limit) orders preferred
├── Risk: Correlation-adjusted portfolio Kelly across cities
└── Monitoring: Brier score tracking, drawdown limits, kill switches
```

For Segment A situations (stable, high-confidence), skip the LLM debate layer entirely—the calibrated ML output suffices and the expected edge is small. For Segment B and C, the LLM debate adds value by surfacing reasoning about conditions that statistical models may miss (unusual synoptic patterns, recent observational anomalies, station-specific micro-climate factors). The key existing tools to build on include the **Metaculus forecasting-tools** framework for LLM integration, the **suislanchez weather bot** for Kalshi API interaction and Open-Meteo data retrieval, and the **Kalshi API** (`docs.kalshi.com`) for order management.

---

## Conclusion: where the real edge lives

The strongest edge in Kalshi temperature markets comes not from better point forecasts but from **better probability calibration in specific regimes**. Three actionable insights emerge from this research that aren't obvious from surface-level analysis.

First, **the NO-biased strategy exploits a structural market inefficiency**. The favorite-longshot bias documented by Whelan et al. means tail brackets are systematically overpriced. Training Segment C models specifically on historical forecast bust conditions—then using them to identify when "unlikely" temperature outcomes are actually more probable than the market implies—is the highest-expected-value approach.

Second, **the IEM MOS Archive eliminates the hardest data engineering problem**. Most weather ML projects fail at data pipeline construction. IEM provides 20+ years of paired GFS MOS forecasts and observations, queryable via simple API calls, for every station Kalshi uses for resolution. This is the fastest path from concept to working system.

Third, **the LLM debate layer's value is marginal for routine forecasts but potentially transformative for Segment C edge cases**. Research consistently shows prompt engineering doesn't matter, but heterogeneous multi-agent debate with role specialization yields 4–6% accuracy gains on difficult cases. The system should route only genuinely uncertain situations (Segments B and C) through the computationally expensive debate layer, using the ML triage to avoid wasting inference budget on situations where statistical models alone suffice. The debate layer's real purpose is surfacing reasoning about physical processes—cold air damming, snow cover transitions, inversion formation—that statistical bias correction can't capture from features alone.