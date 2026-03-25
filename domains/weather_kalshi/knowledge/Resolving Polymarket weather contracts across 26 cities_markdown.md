# Resolving Polymarket weather contracts across 26 cities

**No single API perfectly replaces Weather Underground for Polymarket resolution.** Polymarket resolves nearly all weather contracts — both US and international — via Weather Underground's daily history pages, using the highest temperature recorded at a specific airport station. The WU API was deprecated in 2019, making scraping (via headless browser) the only free way to match the resolution source exactly. For a practical API-based fallback, **Visual Crossing** is the strongest option: it uses actual station observations, covers all cities globally, and offers a free tier of 1,000 records/day. Open-Meteo, despite being free and keyless, returns model/reanalysis data — not station observations — and will regularly diverge from WU by **1–3°F**, disqualifying it for contract-resolution precision.

## Polymarket resolves via two sources, not one

A critical finding: Polymarket uses **Weather Underground for the vast majority of cities** but switches to **NOAA's weather.gov timeseries** for Tel Aviv and Taipei. The resolution rules are explicit and consistent across markets:

For WU-based markets, the exact template reads: *"This market will resolve to the temperature range that contains the highest temperature recorded at the [Station Name]... The resolution source for this market will be information from Wunderground, specifically the highest temperature recorded for all times on this day."* US cities resolve in **whole degrees Fahrenheit**; international cities in **whole degrees Celsius**. No rounding is performed — WU already reports whole-degree values.

For Tel Aviv (LLBG) and Taipei (RCTP), Polymarket uses NOAA instead: *"specifically the highest reading under the 'Temp' column on the specified date once information is finalized for all hours on that date, available here: weather.gov/wrh/timeseries?site=LLBG."* This NOAA endpoint displays METAR observations and shows a table of hourly temperature readings. The practical implication is that any automated system must handle **two resolution pipelines** — WU scraping for ~24 cities and NOAA for Tel Aviv and Taipei.

One additional caveat: Polymarket temporarily delisted Hong Kong weather markets because Weather Underground could not provide historical data for VHHH. The markets were reinstated, but this signals that **WU's international data reliability can be spotty** for certain stations.

## Complete station code mapping from Polymarket's own rules

The table below shows the exact ICAO codes Polymarket references in its resolution criteria. These are definitive — using a different station will produce different temperatures.

| City | ICAO | Airport | Resolution Source | Unit |
|------|------|---------|-------------------|------|
| **NYC** | KLGA | LaGuardia | Weather Underground | °F |
| **Chicago** | KORD | O'Hare International | Weather Underground | °F |
| **Miami** | KMIA | Miami International | Weather Underground | °F |
| **Los Angeles** | KLAX | LAX | Weather Underground | °F |
| **Houston** | KHOU | Hobby Airport | Weather Underground | °F |
| **Dallas** | KDFW | DFW International | Weather Underground | °F |
| **Denver** | KDEN | Denver International | Weather Underground | °F |
| **Seattle** | KSEA | Seattle-Tacoma | Weather Underground | °F |
| **Atlanta** | KATL | Hartsfield-Jackson | Weather Underground | °F |
| **San Francisco** | KSFO | SFO | Weather Underground | °F |
| **Austin** | KAUS | Austin-Bergstrom | Weather Underground | °F |
| **Hong Kong** | VHHH | HK International | Weather Underground | °C |
| **Taipei** | RCTP | Taoyuan International | **NOAA weather.gov** | °C |
| **Tel Aviv** | LLBG | Ben Gurion International | **NOAA weather.gov** | °C |
| **London** | EGLC | London City Airport | Weather Underground | °C |
| **Tokyo** | RJTT | Haneda | Weather Underground | °C |
| **Seoul** | RKSI | Incheon International | Weather Underground | °C |
| **Singapore** | WSSS | Changi | Weather Underground | °C |
| **Paris** | LFPG | Charles de Gaulle | Weather Underground | °C |
| **Toronto** | CYYZ | Pearson International | Weather Underground | °C |
| **São Paulo** | — | (confirm exact station) | Weather Underground | °C |
| **Buenos Aires** | SAEZ | Ezeiza International | Weather Underground | °C |
| **Shanghai** | ZSPD | Pudong International | Weather Underground | °C |
| **Beijing** | ZBAA | Capital International | Weather Underground | °C |
| **Madrid** | LEMD | Barajas | Weather Underground | °C |
| **Warsaw** | EPWA | Chopin Airport | Weather Underground | °C |

**Watch out for WU's default station quirks.** When navigating by city name, WU sometimes defaults to a different airport: Toronto defaults to CYTZ (Billy Bishop) instead of CYYZ; São Paulo defaults to SBMT (Campo de Marte) instead of the major airports; Tel Aviv defaults to LLSD (Sde Dov, a closed airport). Always query by explicit ICAO code.

## Why Open-Meteo fails for this use case

Open-Meteo is free, keyless, and covers every city on Earth — but it fundamentally reports **model and reanalysis data, not station observations**. The Historical Weather API uses ERA5 reanalysis at **25 km grid resolution**, while the Forecast API's `past_days` parameter uses NWP model outputs (HRRR, GFS, ECMWF IFS). Open-Meteo's own documentation acknowledges this distinction: forecasts are described as *"nearly as accurate as direct measurements"* and *"closely mirror local measurements"* — language that confirms they are not the measurements themselves.

The daily `temperature_2m_max` is computed as the maximum of hourly model values across a grid cell, not from an actual thermometer reading at a specific airport. This creates three systematic problems for contract resolution. First, **ERA5 tends to underestimate daily maxima** by 0.5–1.7°C according to peer-reviewed validation studies. Second, the 25 km grid smooths out urban heat islands and airport-specific microclimate effects. Third, brief temperature spikes captured by METAR observations (and thus by WU) may be missed entirely by hourly model snapshots. Expected discrepancies run **1–3°F on typical days**, potentially larger during frontal passages or extreme heat events. For a contract where the threshold is 90°F and WU reports 91°F, Open-Meteo might report 88°F — a costly mismatch.

Open-Meteo remains useful as a **free sanity check** or for building forecast models, but it cannot serve as a resolution-grade source.

## Visual Crossing is the strongest API alternative

Visual Crossing's Timeline API is the best single API for this use case, though it still won't perfectly match WU on every day. Its key advantage: it returns **actual weather station observations** (marked `source: "obs"` in responses) drawn from NOAA ISD, MADIS, GHCN-D, and partner networks comprising **100,000+ stations globally**. The `tempmax` field directly provides the daily maximum temperature.

The free tier allows **1,000 records/day** — querying 26 cities for one day's daily data costs just 26 records, leaving massive headroom. The API is straightforward:

```
https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/
{lat},{lon}/{date}/{date}?key={KEY}&unitGroup=us&include=days&elements=tempmax,tempmin,stations
```

You can set `maxStations=1` to restrict data to the single closest weather station, reducing interpolation effects. By querying with the exact airport coordinates (matching Polymarket's ICAO station), you maximize the likelihood of hitting the same underlying METAR data that feeds Weather Underground. The response includes a `stations` field showing which stations contributed to the observation, enabling verification.

**Where Visual Crossing may diverge from WU:** Visual Crossing interpolates between up to 3 nearby stations by default (weighted by distance). Weather Underground reports the raw reading from a single named station. If the airport station has a data gap, Visual Crossing might fill it from a nearby station and report a slightly different value. Additionally, Visual Crossing and WU use **different data pipelines** — Visual Crossing ingests NOAA ISD and MADIS, while WU has its own proprietary network including personal weather stations not in MADIS. The divergence is typically small (under 1°F for major airports) but not guaranteed to be zero.

## The practical architecture: WU scraping + API fallback

Given the constraints, the recommended architecture uses a **two-layer approach**:

- **Primary source: Weather Underground scraping via headless browser** (Playwright or Selenium). This is the only way to guarantee exact match with Polymarket's resolution. The URL pattern is `wunderground.com/history/daily/{ICAO}/date/{YYYY-M-D}`. The critical caveat: the data is JavaScript-rendered — simple HTTP requests return blank tables. You must execute JS to extract the "Max Temp" value from the daily summary. For Tel Aviv and Taipei, scrape NOAA's `weather.gov/wrh/timeseries?site={ICAO}` instead, extracting the highest "Temp" column value for the date.

- **Fallback API: Visual Crossing Timeline API.** Use this when WU scraping fails (blocked, JS changes, station outage). Query by airport coordinates with `maxStations=1` and `include=days`. Cross-check the `stations` field to confirm the correct airport station contributed. Accept results only when the contributing station matches the Polymarket ICAO code.

- **Secondary verification: NOAA weather.gov/wrh/timeseries.** This endpoint accepts international ICAO codes and displays decoded METAR data in a table. It's already Polymarket's resolution source for two cities and could potentially serve as a lightweight verification layer for all 26 stations, since METAR reports are the upstream data source for both WU and Visual Crossing.

## Ruling out the other candidates

**WeatherAPI.com and WorldWeatherOnline** are immediately disqualified: their FAQ explicitly states *"our historical weather data is made up of forecast data and not from actuals."* Archived forecasts can diverge significantly from observed temperatures.

**Tomorrow.io** offers global coverage but its historical archive uses reanalysis-model-based data, creating the same fundamental problem as Open-Meteo. The free tier is limited to ~500 calls/day, and the data won't match station observations with the needed precision.

**OpenWeatherMap** requires a credit card for historical data access via One Call API 3.0, provides only hourly data (requiring you to compute daily max yourself), and uses model-based outputs. Bulk historical data requires expensive paid plans ($180–950/month).

**NOAA ISD/GSOD** provides the raw station observations that feed most other services, making it theoretically the most authoritative source. However, it has a **1–3 day data lag**, complex file formats, no geocoding, and requires manual station ID mapping. For daily contract resolution where timeliness matters, this lag is problematic. It works well as a delayed verification source but not as a primary daily feed.

## Conclusion

The uncomfortable truth is that **Polymarket chose a data source (Weather Underground) with no API**, making exact-match automation inherently fragile. No third-party API can guarantee matching WU's reported values within ±0.5°F on every day for every city, because each service processes the same upstream METAR data through different pipelines with different interpolation, QC, and rounding decisions.

The pragmatic recommendation is to **scrape Weather Underground as the primary source** using a headless browser, with **Visual Crossing as the best API fallback** and **NOAA weather.gov/wrh/timeseries as a lightweight verification layer**. Visual Crossing's station-observation-based data, free tier capacity, and global coverage make it the strongest single API if you must choose just one — but build in validation against WU whenever possible. Open-Meteo, despite its appeal as a free, keyless service, returns fundamentally different data (model outputs, not observations) and should only be used for forecasting, never for resolution verification.