# Deep Research: How to Beat Weather Prediction Markets

## Context

We are building a system to trade weather temperature prediction markets on Polymarket. Each day, three US cities (NYC, Chicago, Miami) have markets with 11 mutually exclusive 2°F brackets for the daily high temperature. Example: "Will the highest temperature in Chicago be between 50-51°F on March 24?" Markets trade with $200-330K daily volume per city.

**Our current model (CRPSigma):** Takes the NWS GFS MOS point forecast and wraps it with a CRPS-optimized Gaussian uncertainty (sigma), calibrated per station-month on 22 years of historical forecast errors. This produces bracket probabilities via Gaussian CDF integration.

**The problem:** The market is 3-7x more confident than our model. Market-implied sigma is 0.7-0.85°F; our model gives 2-5°F. The market uses day-of multi-model information and is well-calibrated on average. Our historical-average sigma cannot compete on center bracket pricing.

**The question:** What approaches, data sources, models, or techniques can give us a forecasting edge — specifically, the ability to assign bracket probabilities that are better-calibrated than the market, even occasionally?

## Research Questions

### 1. Day-of uncertainty estimation
The biggest gap: our sigma is a monthly average (all Marches over 22 years), but day-to-day uncertainty varies enormously. Some days the forecast is highly confident (stable airmass, clear skies); others are deeply uncertain (frontal timing, convective potential).

- What publicly available data sources provide **day-of forecast uncertainty** signals?
  - NWS ensemble spread (GEFS, NAEFS) — are these available via IEM or other public APIs?
  - ECMWF ensemble spread — any public access? ERA5?
  - NWS probabilistic forecasts (NBM — National Blend of Models)?
  - Weather model "spaghetti plots" or ensemble agreement metrics?
- How do operational EMOS/BMA post-processing systems estimate day-specific sigma?
- Are there published studies on **conditional** forecast uncertainty (sigma as a function of weather regime, season, synoptic pattern)?

### 2. Multi-model ensembles
GFS MOS alone is one model's interpretation. The market likely aggregates information from multiple models.

- What free, publicly accessible NWP (numerical weather prediction) model outputs exist for US surface temperature forecasts?
  - GFS, NAM, HRRR, ECMWF (any public subset), Canadian GEM, UKMO?
  - Where can we download them? API endpoints? NOMADS? IEM?
- How much improvement does multi-model ensemble averaging give over single-model forecasts for day-ahead high temperature?
- Is there published calibration data on which models perform best for NYC (KLGA), Chicago (KORD), and Miami (KMIA)?
- What is the National Blend of Models (NBM) and how does it combine multiple models? Is NBM data accessible?

### 3. Market microstructure edge
The edge may not be in the forecast itself, but in how the market prices uncertainty.

- **Favorite-longshot bias**: Do prediction markets systematically overprice center (likely) outcomes and underprice tails? What does the academic literature say about weather prediction markets specifically?
- **Calibration decay**: How quickly do market prices adjust when forecasts change? Is there a lag between a forecast flip and market price adjustment?
- **Time-of-day patterns**: When are markets most efficient? Are prices at 2 AM (low liquidity) less calibrated than at market close?
- **Volume-weighted pricing**: Low-liquidity brackets (tails) may have wider bid-ask spreads. Is there structural overpricing of YES on tails due to retail gamblers, or underpricing due to illiquidity?

### 4. Regime-dependent calibration
Some weather patterns are inherently harder to forecast. Can we identify those regimes ahead of time?

- What weather regimes produce the largest GFS MOS errors for surface temperature?
  - Frontal passages (timing uncertainty → temperature uncertainty)
  - Arctic outbreaks (boundary layer coupling, mesoscale effects)
  - Sea breeze / lake effect (KLGA coastal, KORD lake-adjacent)
  - Post-frontal clear sky radiation (large diurnal swing, hard to nail)
  - Tropical moisture surges (KMIA)
- Are there published studies on synoptic-pattern-dependent forecast skill for US surface temperatures?
- Can ERA5 reanalysis or weather typing (k-means on 500mb heights, SLP patterns) provide a usable regime signal?

### 5. Machine learning approaches
Can ML models learn patterns in forecast errors that our simple Gaussian model misses?

- What features beyond raw forecast temperature are predictive of forecast error magnitude?
  - Ensemble spread, forecast-minus-climatology, recent forecast trend, wind speed/direction, cloud cover, frontal proximity
- Have gradient boosted models (XGBoost, LightGBM, CatBoost) been successfully applied to MOS-style post-processing?
- Is there published work on using ML for probabilistic temperature forecasting in the EMOS/BMA tradition?
- Neural network approaches (EMOS-Net, distributional regression) — do they beat classical EMOS?

### 6. Alternative data sources
What non-traditional data could add signal?

- **Weather station sensor data**: real-time airport observations (METAR) vs forecast — can we detect when the day is tracking warmer/colder than forecast before the market fully prices it?
- **Satellite data**: cloud cover, snow cover (albedo), sea surface temperature — any that are accessible and predictive?
- **Weather model run timing**: GFS runs at 00Z/06Z/12Z/18Z. When the 12Z run updates the forecast, does the market instantly adjust or lag?
- **Social media / weather enthusiast signals**: weather Twitter, forecast discussion forums — is there signal in the "weather community consensus" that leads the market?

### 7. Specific to our three markets
Any station-specific effects we can exploit?

- **KLGA (LaGuardia, NYC)**: urban heat island, East River proximity, sea breeze from Long Island Sound — how do these affect GFS MOS accuracy?
- **KORD (O'Hare, Chicago)**: Lake Michigan effect, urban-rural gradient, winter arctic outbreaks — when is GFS MOS systematically wrong?
- **KMIA (Miami International)**: tropical stability, trade wind regime, summer afternoon thunderstorm cooling — does our -0.4% CRPSigma improvement compound here?

## Output Format Requested

For each research question, provide:
1. **Key findings** with specific data sources, URLs, API endpoints where applicable
2. **Quantitative estimates** of potential improvement (e.g., "ensemble spread reduces CRPS by X%")
3. **Accessibility assessment**: free/paid, API availability, data latency
4. **Implementation complexity**: can we build this in a weekend or does it need months?
5. **Recommended priority** for our specific use case (3-city, day-ahead, 2°F bracket weather market)

Prioritize approaches with the highest expected edge per unit of implementation effort.
