#!/usr/bin/env python3
"""Generate the MLB Betting Strategy Handbook static site."""
import html as h
import os, textwrap

OUT = os.path.dirname(os.path.abspath(__file__))

# ── Sidebar (shared) ──────────────────────────────────────────────────────────
PAGES = [
    ("index.html",      "Dashboard"),
    ("strategies.html",  "Strategies"),
    ("dead-ends.html",   "Dead Ends"),
    ("data.html",        "Data & Pipeline"),
    ("models.html",      "Models & LLM"),
    ("timeline.html",    "Research Timeline"),
    ("season.html",      "2026 Season Plan"),
]

def sidebar(active):
    links = ""
    for href, label in PAGES:
        cls = ' class="active"' if href == active else ""
        links += f'      <li><a href="{href}"{cls}>{label}</a></li>\n'
    return f"""<aside class="sidebar">
  <div class="brand">MLB Betting</div>
  <div class="brand-sub">Strategy Handbook &mdash; April 2026</div>
  <nav class="nav-section">
    <div class="nav-section-title">Pages</div>
    <ul class="nav-list">
{links}    </ul>
  </nav>
  <div class="nav-section">
    <div class="nav-section-title">Quick Stats</div>
    <div style="font-size:.82rem;color:var(--muted);line-height:1.8">
      31 research sessions<br>
      21 seasons of data<br>
      4 live strategies<br>
      ~194 bets / season<br>
      ~15-20% blended ROI
    </div>
  </div>
</aside>"""

def page(title, active, body, subtitle=""):
    sub = f'<div class="subtitle">{subtitle}</div>' if subtitle else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} &mdash; MLB Betting Handbook</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<div class="layout">
{sidebar(active)}
<div class="main">
  <div class="page-header">
    <h1>{title}</h1>
    {sub}
  </div>
{body}
</div>
</div>
<script src="assets/app.js"></script>
</body>
</html>"""

def tag(status):
    cls = {"live":"live","validated":"validated","dead":"dead","research":"research","paused":"paused"}.get(status,"research")
    return f'<span class="tag tag--{cls}"><span class="tag-dot"></span> {status.upper()}</span>'

def metric(label, value, sub="", color=""):
    cls = f" metric--{color}" if color else ""
    s = f'<div class="metric-sub">{sub}</div>' if sub else ""
    return f'<div class="metric{cls}"><div class="metric-label">{label}</div><div class="metric-value">{value}</div>{s}</div>'

# ── STRATEGY DATA ──────────────────────────────────────────────────────────────

LIVE = [
    {
        "id": "tier1-bullpen-day",
        "name": "Tier 1: Away Bullpen Day",
        "status": "live",
        "market": "ML + RL +1.5",
        "volume": "~24 / season",
        "winrate": "74.2% ML / 83.7% RL",
        "roi": "+63.9% ML / +31.2% RL",
        "roi_num": 63.9,
        "sharpe": "N/A",
        "seasons_tested": "11 (2014-2025)",
        "sessions": "26, 27, 29",
        "filters": "home_is_bullpen_day = True\naway_has_starter = True\nedge > 0.05",
        "rationale": "When the home team uses a bullpen day (opener or no designated starter, max IP < 4), the away team with a real starter has a massive structural advantage. Bullpen days typically mean the home team's rotation is stressed, creating a predictable mismatch. This is the single strongest predictor found across all research: 11/11 seasons profitable, 74.2% moneyline win rate at average dog odds of ~2.20.",
        "caveats": "Low volume (~24 games/season). Bullpen day detection relies on retrosheet pitcher logs with IP < 4 innings threshold. In 2026 live detection uses ESPN probable starters + historical bullpen patterns. Some scheduled bullpen days may be changed last-minute.",
        "evidence": "264 games across 2014-2025. No single losing season. Dog ML: 196W/68L = 74.2% WR at 2.20 avg odds = +63.9% ROI. RL +1.5: 221/264 = 83.7% cover at 1.57 avg odds = +31.2% ROI. Walk-forward validated on 2024-2025 holdout.",
    },
    {
        "id": "tier2-fatigue-gap",
        "name": "Tier 2: Bullpen Fatigue Gap",
        "status": "live",
        "market": "RL +1.5",
        "volume": "~25 / season",
        "winrate": "72.2% cover",
        "roi": "+11.2%",
        "roi_num": 11.2,
        "sharpe": "~0.6",
        "seasons_tested": "10 (2014-2025 excl BP days)",
        "sessions": "26, 27",
        "filters": "away_bp_3d <= 6 (rested bullpen)\nhome_bp_3d >= 8 (tired bullpen)\nNOT bullpen day (starter vs starter)",
        "rationale": "Even when both teams have starters, bullpen workload imbalance matters. If the home bullpen pitched 8+ innings in the last 3 days while the away bullpen is rested (<=6 IP in 3 days), the away team has a late-game relief advantage. This creates a Run Line edge: the away team stays competitive or wins close, covering +1.5 more often.",
        "caveats": "Edge is smaller than Tier 1 (~11% vs ~31% ROI). Works best in combination with other signals. The 3-day IP window is somewhat arbitrary but validated across multiple thresholds.",
        "evidence": "~275 games across non-bullpen-day universe. 72.2% RL cover at ~1.57 odds = +11.2% ROI. 8/10 walk-forward folds positive. Complementary to Tier 1 (zero game overlap).",
    },
    {
        "id": "tier3-pitcher-advantage",
        "name": "Tier 3: Away Pitcher Advantage",
        "status": "live",
        "market": "RL +1.5",
        "volume": "~8 / season",
        "winrate": "79.0% cover",
        "roi": "+24.7%",
        "roi_num": 24.7,
        "sharpe": "~0.9",
        "seasons_tested": "10 (2014-2025)",
        "sessions": "27, 29",
        "filters": "away_sp_fip_short <= 3.5\nstarter_depth_diff <= -1.0\nbp_ip_3d_home >= 8",
        "rationale": "Triple filter: (1) away starter in excellent recent form (FIP <= 3.5 over last 5 starts), (2) away starter goes significantly deeper than home starter (depth diff <= -1.0 innings), (3) home bullpen already tired (8+ IP in 3 days). This creates compounding mismatch: quality starter + deep innings + tired opposing relief. The away team dominates the middle and late innings.",
        "caveats": "Very low volume (~8 games/season). High variance due to small samples in any single season. Strongly correlated with Tier 2 (shares bp_ip_3d filter). TRAIN +29.2%, TEST +21.0% shows some decay but remains profitable.",
        "evidence": "81 games across 2014-2025. 79.0% RL cover. Train/test split: TRAIN 64 games +29.2% ROI, TEST 17 games +21.0% ROI. 8/10 walk-forward folds positive. Starter-only variant (no BP filter): 135 games, 71.9% cover, +12.3% ROI.",
    },
    {
        "id": "fav-rl-minus15",
        "name": "Fav -1.5 Run Line",
        "status": "live",
        "market": "RL -1.5",
        "volume": "~137 / season",
        "winrate": "49.8% TRAIN / 47.9% TEST",
        "roi": "+19.6% TRAIN / +15.0% TEST",
        "roi_num": 15.0,
        "sharpe": "~0.8",
        "seasons_tested": "5 (2021-2025)",
        "sessions": "25, 29",
        "filters": "implied_prob >= 0.62 AND < 0.75\nstarter_fip_diff <= -0.2\npower_rate_diff >= 0",
        "rationale": "Favorites win by 2+ runs more often than odds imply when three conditions align: (1) moderate-to-strong favorite (62-75% implied, avoiding extreme lines), (2) clear pitching edge (FIP diff <= -0.2), (3) at least equal offensive power (power_rate_diff >= 0). The key insight is that RL -1.5 has 4x better economics than +1.5: avg odds 2.40 with 41.7% breakeven (vs 1.57 / 63.7% for +1.5). A modest filter pushes cover from 40.8% baseline to 49.8%.",
        "caveats": "Only validated on 2021-2025 (5 seasons). Earlier seasons lack reliable RL odds data. The 2025 OOS test showed +15.0% (decent but weaker than train). September is a known weak zone. RL odds are estimated at 2.40 average (actual DraftKings odds vary per game).",
        "evidence": "TRAIN: 548 games (2021-2024), 49.8% cover, +19.6% ROI. TEST: 121 games (2025), 47.9% cover, +15.0% ROI. Earlier analysis with different filters failed badly (Session 4: -4.25% ROI baseline). Optional LLM layer (Analyst + Momentum genome) for refinement available but not required.",
    },
]

VALIDATED = [
    {
        "id": "s3-dual-away-ml",
        "name": "S3-Dual: Away ML Underdog",
        "status": "validated",
        "market": "ML (dog)",
        "volume": "~54 / season",
        "winrate": "49.0%",
        "roi": "+17.9%",
        "roi_num": 17.9,
        "sharpe": "0.983",
        "seasons_tested": "21 (2004-2025)",
        "sessions": "6, 7, 8, 9",
        "filters": "Dual-Regime:\n1H (May-Jun): rpi_diff <= -0.01, elo_diff <= 15, edge < -0.05\n2H (Jul-Oct): rpi_diff <= 0, elo_diff <= 30, edge < -0.05",
        "rationale": "Away underdogs are mispriced when team quality metrics (RPI, Elo) are close but the market prices the home team as a clear favorite (edge < -0.05 means market overvalues home). May-June requires stricter filters because early-season ratings are noisier. The dual-regime approach adapts to seasonal information quality.",
        "caveats": "Not in live 2026 portfolio because it requires model-based edge calculation (CatBoost P(home)). The S3 strategies were developed earlier and later superseded by the bullpen-day family which has cleaner signals. Could be activated if bullpen strategies underperform.",
        "evidence": "398 bets across 21 seasons. 49.0% WR at avg dog odds ~2.15. MaxDD 15.6%. Only losing season: 2010 (-4.7%). 8-fold cross-validation: 6/8 folds positive. Sharpe 0.983 (best risk-adjusted of all ML strategies).",
    },
    {
        "id": "under-totals-ml",
        "name": "UNDER Totals (ML Model)",
        "status": "validated",
        "market": "O/U (Under)",
        "volume": "~100-530 / season",
        "winrate": "55.6-70.4%",
        "roi": "+6.1% to +34.3%",
        "roi_num": 34.3,
        "sharpe": "0.52-1.05",
        "seasons_tested": "11 (2010-2021)",
        "sessions": "10, 15, 19, 20",
        "filters": "P(under) >= 0.52: auto-bet (1x stake)\nP(under) >= 0.55: auto-bet (2x stake)\nP(under) 0.51-0.52: LLM gate (0.5x)\nP(under) < 0.51: skip",
        "rationale": "UNDER is structurally easier to predict than OVER because pitching converges (aces hold, bullpens manage) while offense diverges (random HR barrages). The CatBoost+Ridge ensemble on 21 pitcher/bullpen features captures this asymmetry. Platt calibration was removed (inflated bets), using raw ensemble probabilities.",
        "caveats": "Not in live 2026 portfolio because: (1) requires real-time O/U line from Polymarket (not yet integrated for totals), (2) OVER model completely failed (AUC 0.50), suggesting market may be efficient on totals. LLM expansion zone (P 0.51-0.52) showed +15% ROI on 110 games but needs more validation.",
        "evidence": "P>=0.55: 1,178 bets, 70.4% hit, +34.3% ROI (nuclear zone). P>=0.52: 7,221 bets, 55.6% hit, +6.1% ROI. LLM gate: 61 filtered bets from 110, 60.7% hit, +15.0% ROI. Walk-forward across 11 seasons.",
    },
    {
        "id": "away-rl-plus15-fip",
        "name": "Away RL +1.5 (1H + FIP edge)",
        "status": "validated",
        "market": "RL +1.5",
        "volume": "~91 / season",
        "winrate": "63.8% cover",
        "roi": "+11.8%",
        "roi_num": 11.8,
        "sharpe": "1.233",
        "seasons_tested": "11 (2010-2021)",
        "sessions": "9, 11",
        "filters": "1H season only (May-Jun)\nedge > 0.10\nFIP filter > 0.5 variant: 612 bets, +12.5%",
        "rationale": "Inverted edge signal: when the model says the favorite is overpriced (edge > 0.10), games tend to be tighter than expected. The away dog +1.5 covers in these tight games. Works best in 1st half when early-season pitching matchups create wider edges.",
        "caveats": "Superseded by the bullpen-day family which has cleaner mechanistic explanations. The edge > 0.10 filter depends on CatBoost model calibration. Season split (1H only) loses volume.",
        "evidence": "1,006 bets (1H + edge > 0.10), 63.8% cover, +11.8% ROI, Sharpe 1.233. FIP variant: 612 bets, +12.5% ROI, 8/11 folds positive. Zero overlap with S3-dual (opposite edge directions).",
    },
]

DEAD = [
    {"name":"Favorite ML Flat","reason":"Vig eats 4-5%. WR 56-60% required, achieved ~54-56%. Consistently -3% to -5% ROI across all filter combinations.","sessions":"4, 6, 9","market":"ML"},
    {"name":"Favorite RL -1.5 (unfiltered)","reason":"Baseline 42.3% cover, needs 50% at 2.3 odds. Gap is 8 percentage points &mdash; no filter closes it without obliterating volume.","sessions":"4","market":"RL -1.5"},
    {"name":"Favorite Series Dogon","reason":"Gap -2.2pp vs breakeven 82.7%. Favorites don't win BOTH games in a series reliably enough. Achievable max: 80.5%.","sessions":"9","market":"ML series"},
    {"name":"Series Dogon + Pitcher Features","reason":"Martingale risk profile with +3-5% ROI &mdash; worst of both worlds. When it loses, it loses big (double-stake on G2 gone). Superseded by strategies with cleaner mechanistic edges and 3-6x higher ROI. Not worth the variance.","sessions":"2, 3","market":"ML series"},
    {"name":"Home Underdog +1.5 RL","reason":"Odds too low (1.61-1.72). Breakeven 58-62% but cover peaks at 54.6%. No filter combination profitable. Home dogs just lose by too much.","sessions":"11","market":"RL +1.5"},
    {"name":"Home Underdog ML","reason":"WR peaks at 50.3%, breakeven ~50.5%. No margin at any threshold.","sessions":"11","market":"ML"},
    {"name":"F5 (First 5 Innings) ML","reason":"Push rate 14.8% kills edge. -19.8% to -23.1% ROI. F5 market is structurally unprofitable for ML bets.","sessions":"4","market":"F5 ML"},
    {"name":"OVER Totals (ML Model)","reason":"AUC 0.50 &mdash; no signal. Tested: UNDER inversion, dedicated model (22 features), minimal model (11 features). Offensive explosions are inherently unpredictable. Market prices recreational OVER bias.","sessions":"20","market":"O/U Over"},
    {"name":"NRFI ML Classifier","reason":"Base rate 49.2% (myth was 57%). 18 PA per half-inning = structural noise ceiling. AUC 0.52 is the limit. Best ROI: +5.6% on 122 bets (3/5 seasons). Not reliable.","sessions":"21, 22","market":"NRFI"},
    {"name":"Coinflip Zone (Momentum + Structure Duel)","reason":"40.5% accuracy, -22.1% ROI. Experts cancel each other: 80% away bias, confidence miscalibration (0.65-0.75 conf = 20% accuracy). Zero expert diversity.","sessions":"13, 14, 23, 24","market":"ML (even)"},
    {"name":"Savant Bullpen Statcast","reason":"Market already prices Statcast data (public since 2015). xwOBA mismatch: 53% WR at -0.2% ROI. Fatigue signals are ANTI-predictive (-5% to -13%). CatBoost importance: 1.74%.","sessions":"28","market":"ML"},
    {"name":"Away RL +1.5 (real odds)","reason":"Session 4 discovered real odds are 1.57 (not 1.87 assumed). At 1.57, breakeven is 63.7% but baseline cover is 60.2%. Gap too wide. Only works with specific filters (bullpen day, fatigue).","sessions":"4, 9","market":"RL +1.5"},
    {"name":"LLM UNDER Gate &mdash; zone [0.52-0.53)","reason":"718 games, gpt-5.4 neutral scorer + blind card (O/U line removed, league averages for calibration). Correlation(predicted_total, actual) = +0.087; MAE 3.83 worse than naive constant 8.87 (3.78). Scorer systematically underpredicts by 1-2 runs. Promising sub-strategies (gap&gt;=2.0 = 56% hit, ceil_gap&gt;=0.5 = 67% hit, DA=UNDER combo = 54%) collapse on 2024-2025 holdout. A/B test also proved any league-avg banner in the card anchors the LLM (+0.34 runs shift). Zone is dead; return to P&gt;=0.53 auto-bet.","sessions":"30, 31","market":"O/U Under"},
]

TIMELINE = [
    ("Feb 12", "2, 3", "research", "Data pipeline + Series Dogon", "Team features, pitcher proxy layer. Dogon +5.21% ROI (TEST). First profitable strategy."),
    ("Feb 13", "4", "dead", "Exhaustive market scan", "RL, F5, ML favorites all tested and killed. Only dogon + pitcher survives."),
    ("Feb 15", "5", "research", "Retrosheet integration", "75,950 pitcher game logs. 99.91% odds match rate. Anti-leak entering-game features."),
    ("Mar 18", "6", "validated", "SBR dataset + Away underdog discovery", "S3 strategy found: +9.9% ROI, Sharpe 0.81. S4 bullpen variant: +20.6% ROI."),
    ("Mar 19", "7, 8", "validated", "Duplicate fix + September discovery", "88.5% duplicate rows found and fixed. September is POSITIVE (+22.2%). S3-Dual: +17.9%."),
    ("Mar 19", "9", "validated", "21-season validation + RL discovery", "S3-Dual + Away RL +1.5 portfolio. Home underdog confirmed dead."),
    ("Mar 20", "10", "validated", "UNDER totals model", "P(u)>=0.55: +34.3% ROI. OVER breakeven. Bullpen filters boost hit rate."),
    ("Mar 20", "11", "dead", "Home underdog killed", "RL +1.5 and ML both dead. Portfolio correlation: zero overlap, -0.025 daily corr."),
    ("Mar 21", "12", "research", "LLM Expert framework", "Feature cards, offense/bullpen context, expert duel initialization."),
    ("Mar 21", "13", "research", "Coinflip zone", "Symmetric cards, CF-specific logic. Batch v1 failed (experts follow model blindly)."),
    ("Mar 22", "14", "research", "Feature pipeline complete", "171 features total. CF zone shows 80% accuracy on Jul 4 sample (small)."),
    ("Mar 22", "15", "validated", "UNDER calibration", "P(u)>=0.60: +42-61% ROI (nuclear). LLM expansion: 10W-1L, +73.5% ROI."),
    ("Mar 23", "16", "dead", "OVER pipeline built &amp; killed", "OVER P>=0.55: 3W-0L (tiny). Entropy asymmetry discovered. OVER dropped."),
    ("Mar 23", "17", "research", "ML retrain planning", "Feature candidates for SPEC/UNDER models identified. Coverage gaps mapped."),
    ("Mar 23", "19", "validated", "UNDER V3 overhaul", "Platt removed. P>=0.52: +6.1%. LLM gate: 61 bets, +15.0%. Production tiering set."),
    ("Mar 23", "20", "dead", "OVER ML definitively dead", "3 model variants: AUC 0.50 each. Offensive explosions = noise."),
    ("Mar 24", "21, 22", "dead", "NRFI killed", "Base rate 49.2% (not 57%). AUC 0.52 structural ceiling. 18 PA = noise."),
    ("Mar 24", "23", "research", "Coinflip zone research plan", "7-phase plan. CF-specific genomes designed."),
    ("Mar 26", "24", "dead", "CF duel killed", "40.5% accuracy, -22.1% ROI. Momentum genome toxic. Requires fundamental rebuild."),
    ("Mar 26", "25", "live", "Fav -1.5 Run Line", "TRAIN +19.6%, TEST +15.0%. impl 62-75% + FIP + power filters. 137 games/season."),
    ("Mar 27", "26", "live", "Bullpen Day discovery", "11/11 seasons profitable. 83.7% RL cover. Strongest signal ever found."),
    ("Mar 27", "27", "live", "Pitcher advantage expansion", "Tier 3: 79.0% cover, +24.7% ROI. Complete away dog portfolio: T1+T2+T3."),
    ("Apr 3", "28", "dead", "Savant Statcast tested", "Market already prices it. Fatigue is anti-predictive. Infrastructure kept."),
    ("Apr 12", "29", "live", "Go-live", "Picks generator, IO safety, data pipeline insurance. System operational."),
    ("Apr 14", "30", "validated", "UNDER re-validation 2021-2025", "P&gt;=0.53: +10.6% ROI across 5 seasons. build_ou_features bug fixed (missing retrosheet enrichment). P&gt;=0.55 improved +30.8% &rarr; +37.2%."),
    ("Apr 15", "31", "dead", "LLM UNDER Gate zone [0.52-0.53) killed", "718 games, gpt-5.4 neutral scorer + blind card. Correlation(pred, actual) = 0.087, MAE worse than naive 8.87. Promising sub-strategies (gap&gt;=2.0, DA=UNDER combo) collapsed on 2024-2025 holdout. Zone is dead; return to P&gt;=0.53 auto-bet."),
]

BUGS = [
    ("Duplicate rows (88.5%)", "Session 6 validation inflated ROI", "Fixed bullpen_features dedup (session 8)", "Critical"),
    ("September filtered incorrectly", "Lost +22% signal in away underdog", "Removed filter, validated positive (session 7)", "High"),
    ("Retrosheet enrichment missing", "2022-2025 inning data unavailable", "Single import line added (session 25)", "Medium"),
    ("Platt calibration inflated P(u)", "65% of 0.55+ bets actually <0.55", "Removed, uses raw ensemble (session 19)", "High"),
    ("SBR odds parser (awaySpread)", "Bimodal distribution, 2.5+ odds", "Fixed to awaySpread == 1.5 only (session 26)", "High"),
    ("Bullpen parquet overwrite", "2014-2025 history wiped on backfill", "Dual-path: pitchers/ vs pitchers_2026/ (session 29)", "Critical"),
    ("Pitcher data loss (Mar 26-Apr 5)", "535 rows instead of 1,800", "Backfilled + atomic writes + sidecar JSONs (session 29)", "Critical"),
]

# ── PAGE BUILDERS ──────────────────────────────────────────────────────────────

def build_index():
    body = f"""
  <div class="metrics">
    {metric("Live Strategies","4","In production for 2026","green")}
    {metric("Validated (Reserve)","4","Ready to activate","blue")}
    {metric("Dead Ends","13","Tested & rejected","red")}
    {metric("Research Sessions","31","Feb 12 &mdash; Apr 15, 2026","yellow")}
  </div>

  <div class="section">
    <div class="section-title">Current Portfolio</div>
    <div class="section-desc">Four strategies in production for the 2026 MLB season, targeting Polymarket. All validated on historical data with walk-forward testing.</div>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Strategy</th><th>Market</th><th class="num">Volume</th><th class="num">Win/Cover</th><th class="num">ROI</th><th>Status</th>
      </tr></thead>
      <tbody>
"""
    for s in LIVE:
        body += f"""        <tr>
          <td><a href="strategies.html#{s['id']}">{s['name']}</a></td>
          <td>{s['market']}</td>
          <td class="num">{s['volume']}</td>
          <td class="num">{s['winrate']}</td>
          <td class="num positive">+{s['roi_num']:.1f}%</td>
          <td>{tag('live')}</td>
        </tr>\n"""
    body += """      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Reserve Strategies</div>
    <div class="section-desc">Validated but not in the live portfolio. Can be activated if live strategies underperform or market conditions change.</div>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Strategy</th><th>Market</th><th class="num">Volume</th><th class="num">ROI</th><th>Status</th>
      </tr></thead>
      <tbody>
"""
    for s in VALIDATED:
        body += f"""        <tr>
          <td><a href="strategies.html#{s['id']}">{s['name']}</a></td>
          <td>{s['market']}</td>
          <td class="num">{s['volume']}</td>
          <td class="num positive">+{s['roi_num']:.1f}%</td>
          <td>{tag('validated')}</td>
        </tr>\n"""
    body += """      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Key Principles (Learned the Hard Way)</div>
    <div class="grid-2">
      <div class="callout callout--green">
        <strong>Away underdogs only.</strong> Home dogs lose by too much (RL +1.5 cover 54.6% vs 63.7% breakeven). All profitable RL strategies are away-side.
      </div>
      <div class="callout callout--green">
        <strong>Bullpen > Pitching > Offense.</strong> Bullpen workload is the strongest single predictor. Starter quality is second. Offensive signals add noise.
      </div>
      <div class="callout callout--red">
        <strong>Favorites are a trap.</strong> Market prices them within 1% of fair value. Vig eats the rest. Only profitable via RL -1.5 with strict filters.
      </div>
      <div class="callout callout--red">
        <strong>OVER is impossible.</strong> Offensive explosions are inherently unpredictable. Three separate models (inversion, dedicated, minimal) all showed AUC 0.50.
      </div>
      <div class="callout callout--blue">
        <strong>September is profitable.</strong> Tanking teams are HOME, creating opportunities for away bettors. Removing September cost +22% ROI signal.
      </div>
      <div class="callout callout--blue">
        <strong>Platt calibration lies.</strong> Isotonic regression inflated 65% of bets above threshold. Raw ensemble probabilities are more honest.
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Data Coverage</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Source</th><th>Seasons</th><th>Games</th><th>Features</th></tr></thead>
      <tbody>
        <tr><td>sports-statistics.com (xlsx)</td><td>2010-2019, 2021</td><td>~26,400</td><td>Full inning data, real closing odds</td></tr>
        <tr><td>SBR / DraftKings</td><td>2021-2025</td><td>~7,700</td><td>Real away RL odds, 100% match rate</td></tr>
        <tr><td>Retrosheet pitcher logs</td><td>2010-2025</td><td>75,950 logs</td><td>Anti-leak entering-game stats</td></tr>
        <tr><td>SDQL / ArnavSaogi</td><td>2004-2009, 2022-2025</td><td>~16,600</td><td>ML + OU (no inning scores)</td></tr>
        <tr><td>Baseball Savant (Statcast)</td><td>2015-2025</td><td>~30 cols</td><td>xwOBA, barrel rate (weak signal, kept for infra)</td></tr>
        <tr><td>ESPN Live (2026)</td><td>2026 (Apr 1+)</td><td>414 games</td><td>Real-time starters, odds, scores</td></tr>
      </tbody>
    </table></div>
  </div>
"""
    return page("Dashboard", "index.html", body, "MLB Betting Strategy Handbook &mdash; Season 2026")


def build_strategy_card(s):
    """Build a single strategy card HTML."""
    return f"""
    <div class="card" id="{s['id']}" data-strat-item="{s['name']} {s['market']} {s['status']}" data-status="{s['status']}" data-market="{s['market'].split()[0].lower()}">
      <div class="card-header">
        <div class="card-title">{s['name']}</div>
        {tag(s['status'])}
      </div>
      <div class="strat-meta">
        <div class="strat-field"><div class="strat-field-label">Market</div><div class="strat-field-value">{s['market']}</div></div>
        <div class="strat-field"><div class="strat-field-label">Volume</div><div class="strat-field-value">{s['volume']}</div></div>
        <div class="strat-field"><div class="strat-field-label">Win / Cover</div><div class="strat-field-value">{s['winrate']}</div></div>
        <div class="strat-field"><div class="strat-field-label">ROI</div><div class="strat-field-value text-green">{s['roi']}</div></div>
        <div class="strat-field"><div class="strat-field-label">Sharpe</div><div class="strat-field-value">{s['sharpe']}</div></div>
        <div class="strat-field"><div class="strat-field-label">Seasons</div><div class="strat-field-value">{s['seasons_tested']}</div></div>
        <div class="strat-field"><div class="strat-field-label">Sessions</div><div class="strat-field-value">{s['sessions']}</div></div>
      </div>
      <div class="strat-rationale">{s['rationale']}</div>
      <div class="strat-filters"><code>{h.escape(s['filters'])}</code></div>
      <details class="mt-16">
        <summary>Evidence</summary>
        <div class="detail-body">{s['evidence']}</div>
      </details>
      <details>
        <summary>Caveats</summary>
        <div class="detail-body">{s['caveats']}</div>
      </details>
    </div>
"""


def build_strategies():
    cards = ""
    for s in LIVE:
        cards += build_strategy_card(s)
    for s in VALIDATED:
        cards += build_strategy_card(s)

    body = f"""
  <div class="filters" data-strat-root>
    <input class="filter-input" data-strat-search placeholder="Search strategies...">
    <select class="filter-select" data-strat-status>
      <option value="">All Statuses</option>
      <option value="live">Live</option>
      <option value="validated">Validated</option>
    </select>
    <select class="filter-select" data-strat-market>
      <option value="">All Markets</option>
      <option value="ml">ML (Moneyline)</option>
      <option value="rl">RL (Run Line)</option>
      <option value="o/u">O/U (Totals)</option>
    </select>
  {cards}
  </div>
"""
    return page("Strategies", "strategies.html", body, "All tested strategies &mdash; live, validated, and reserve")


def build_dead_ends():
    rows = ""
    for d in DEAD:
        rows += f"""    <div class="card">
      <div class="card-header">
        <div class="card-title">{d['name']}</div>
        {tag('dead')}
        <span class="text-muted text-sm">Sessions: {d['sessions']}</span>
        <span class="text-muted text-sm">&bull; {d['market']}</span>
      </div>
      <div class="strat-rationale">{d['reason']}</div>
    </div>\n"""

    body = f"""
  <div class="callout callout--red">
    <strong>13 approaches tested and killed.</strong> Each dead end represents hours of research, feature engineering, and backtesting. They are documented here so we never revisit them without new evidence.
  </div>
  {rows}

  <div class="section mt-16">
    <div class="section-title">Why These Failed &mdash; Common Patterns</div>
    <div class="grid-3">
      <div class="card mb-0">
        <div class="card-title text-sm">Vig Trap</div>
        <div class="text-muted text-sm mt-8">Favorite ML, Home Dog, F5 ML. Market prices are close to fair; the 4-5% vig makes breakeven impossible. Need either extreme mispricing or a structural edge to overcome.</div>
      </div>
      <div class="card mb-0">
        <div class="card-title text-sm">Signal Ceiling</div>
        <div class="text-muted text-sm mt-8">NRFI (18 PA = noise), CF zone (experts cancel), OVER (entropy). Some markets have fundamental noise floors that no model can break through.</div>
      </div>
      <div class="card mb-0">
        <div class="card-title text-sm">Market Efficiency</div>
        <div class="text-muted text-sm mt-8">Savant Statcast (public since 2015), Favorite ML (sharp money). When data is public and widely used, the market already prices it in.</div>
      </div>
    </div>
  </div>
"""
    return page("Dead Ends", "dead-ends.html", body, "Strategies tested and rejected &mdash; and why")


def build_data():
    body = """
  <div class="section">
    <div class="section-title">Data Sources</div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Historical Odds (2004-2025)</div>
        <div class="text-muted text-sm mt-8">21 seasons, ~50,700 games. Three sources merged: sports-statistics.com (xlsx, 2010-2021), SDQL API (2004-2009), ArnavSaogi JSON (2022-2025). After filters: ~49,700 games, ~38,000 bettable.</div>
        <div class="strat-filters mt-16"><code>python data/download.py          # original xlsx
python data/download_historical.py  # SDQL + JSON</code></div>
      </div>
      <div class="card">
        <div class="card-title">Live 2026 Pipeline</div>
        <div class="text-muted text-sm mt-8">ESPN Scoreboard API for real-time odds (DraftKings), starters, scores. MLB Stats API for pitcher handedness. Orchestrator runs daily. Atomic writes with sidecar JSONs and audit log.</div>
        <div class="strat-filters mt-16"><code>data/fetch_2026/orchestrator.py   # daily fetch
data/fetch_2026/io_safety.py       # atomic writes
scripts/check_2026_pipeline.py     # 5 health assertions</code></div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Processing Pipeline</div>
    <pre>download.py / download_historical.py
  &darr;
data/raw/odds/*.xlsx  (standardized schema)
  &darr;
data_loader.py  &rarr;  load_all_seasons() + pair_games()
  &darr;
apply_data_filters()  (remove: 2020, missing odds/pitcher, doubleheaders)
add_derived_odds()    (decimal odds, implied probabilities)
  &darr;
features.py           (67 team features: RPI, WP, streaks, RPG)
pitcher_features.py   (32 pitcher proxy oscillators)
bullpen_features.py   (30 bullpen workload/quality features)
retrosheet_*.py       (anti-leak entering-game stats)
  &darr;
feature_card.py       (171-feature human-readable game cards)
  &darr;
model.py              (CatBoost + Ridge regime ensemble)
llm_expert.py         (Claude-based pick generation)
  &darr;
strategies/*.py       (tier filters &rarr; daily picks)
  &darr;
generate_picks_2026.py (JSON output + target pricing)</pre>
  </div>

  <div class="section">
    <div class="section-title">Hard Filters (Always Applied)</div>
    <div class="callout callout--blue">These filters are non-negotiable. Every analysis, backtest, and live pick must apply them.</div>
    <pre>games = apply_data_filters(games)   # Remove: 2020, missing odds/pitcher, doubleheaders
games = add_derived_odds(games)     # Add decimal odds, implied probabilities

# Betting filters:
bettable = games[
    ~games["involves_col"]        # NEVER bet on Colorado games
    &amp; ~games["is_extreme_line"]   # Skip extreme favorites (>300)
]
# Note: September is INCLUDED (validated profitable across 5 seasons)</pre>
  </div>

  <div class="section">
    <div class="section-title">Feature Inventory (171 total)</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Category</th><th class="num">Count</th><th>Key Features</th></tr></thead>
      <tbody>
        <tr><td>Team rolling</td><td class="num">35</td><td>RPI, WP (3/6/10/20g windows), RPG, RAPG, streaks, Elo</td></tr>
        <tr><td>Pitcher proxy</td><td class="num">32</td><td>RA/WR oscillators (short/long), 1st-inning RA, momentum</td></tr>
        <tr><td>Bullpen</td><td class="num">30</td><td>FIP, WHIP, K9, K/BB, IP (3-day), workload oscillators</td></tr>
        <tr><td>Retrosheet (entering-game)</td><td class="num">30</td><td>Starter FIP, WHIP, K/BB, HR9 (5/15 start windows), bullpen day flag</td></tr>
        <tr><td>Savant Statcast</td><td class="num">30</td><td>xwOBA, barrel rate, delta (2015+ only, weak signal)</td></tr>
        <tr><td>Late-game context</td><td class="num">5</td><td>hold_rate, close_game_wp, deficit_recovery, power_rate</td></tr>
        <tr><td>Batting splits</td><td class="num">10</td><td>vs-hand OBP (top3), K rate, effective_obp matchups</td></tr>
        <tr><td>Market context</td><td class="num">10</td><td>implied_prob, edge, odds spread, O/U line</td></tr>
        <tr><td>Schedule/travel</td><td class="num">4</td><td>rest_days, travel_miles_3d, road_trip_len, tz_changes_3d</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Critical Bugs Fixed</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Bug</th><th>Impact</th><th>Fix</th><th>Severity</th></tr></thead>
      <tbody>
"""
    for name, impact, fix, sev in BUGS:
        cls = "text-red" if sev == "Critical" else ("text-yellow" if sev == "High" else "text-muted")
        body += f'        <tr><td>{name}</td><td>{impact}</td><td>{fix}</td><td class="{cls}">{sev}</td></tr>\n'
    body += """      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Data Quirks</div>
    <div class="callout callout--red">
      <strong>home_run_line column contains MIXED data.</strong> Values -1.5 and 1.5 = actual Run Line (spread). Values 5.5+ = Over/Under total (misclassified in raw data). Always filter by <code>home_run_line.isin([-1.5, 1.5])</code> for RL analysis.
    </div>
    <div class="callout">
      <strong>SDQL/JSON seasons (2004-2009, 2022-2025) lack inning-by-inning scores.</strong> Run Line data only available for 2014+ (original) and 2022-2025 (JSON). Features requiring inning data use 2010-2021 window.
    </div>
  </div>
"""
    return page("Data & Pipeline", "data.html", body, "Data sources, processing pipeline, and feature inventory")


def build_models():
    body = """
  <div class="section">
    <div class="section-title">Three Approaches Tested in Parallel</div>
    <div class="grid-3">
      <div class="card">
        <div class="card-title">Rules-Based</div>
        <div class="text-muted text-sm mt-8">Expert criteria from legacy system: RPI, pitcher stats, form. Produces the live Tier 1/2/3 and Fav-RL strategies. Simple, interpretable, robust.</div>
        <div class="tag tag--live mt-8"><span class="tag-dot"></span> PRIMARY</div>
      </div>
      <div class="card">
        <div class="card-title">CatBoost ML</div>
        <div class="text-muted text-sm mt-8">Gradient boosting on 35+ features. Regime-split ensemble (CatBoost + Ridge). Used for UNDER totals model and S3-Dual edge calculation. AUC ~0.55 for UNDER; 0.50 for OVER/NRFI.</div>
        <div class="tag tag--validated mt-8"><span class="tag-dot"></span> RESERVE (UNDER)</div>
      </div>
      <div class="card">
        <div class="card-title">LLM Estimator</div>
        <div class="text-muted text-sm mt-8">GPT-4o-mini / Claude via API. Feature card analysis + expert reasoning. Genome evolution tracks anti-patterns. Duel system for disagreement resolution.</div>
        <div class="tag tag--paused mt-8"><span class="tag-dot"></span> PAUSED</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">ML Model Architecture</div>
    <div class="card">
      <div class="card-subtitle">src/model.py &mdash; 1,213 lines</div>
      <div class="strat-rationale mt-8">
        <strong>Regime-split ensemble:</strong> 50/50 CatBoost + Ridge regression.<br><br>
        <strong>4 regimes</strong> (outcome-based, trained separately):<br>
        &bull; M0: All games (baseline)<br>
        &bull; M2: Favorite won by 2+ (dominant)<br>
        &bull; M3: Favorite won by 1 (tight)<br>
        &bull; M4: Favorite lost (upset)<br><br>
        <strong>Training:</strong> Walk-forward validation. CatBoost depth=4, lr=0.05, 300 iterations. Ridge alphas [0.1, 1.0, 10.0, 100.0]. Isotonic calibration on validation fold (removed for UNDER model after Session 19 Platt discovery).
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">LLM Expert System</div>
    <div class="card">
      <div class="card-subtitle">src/llm_expert.py (1,399 lines) + src/llm_duel.py (971 lines) + src/llm_evolution.py (282 lines)</div>
      <div class="strat-rationale mt-8">
        <strong>Components:</strong><br>
        &bull; <strong>Feature Card Generator</strong> (src/feature_card.py, 2,100 lines): 171-feature human-readable game summary with team form, pitcher matchup, market context, red flags.<br>
        &bull; <strong>Genome:</strong> Expert knowledge representation with anti-patterns, examples, version history. Evolves weekly from outcome analysis.<br>
        &bull; <strong>Pick Generation:</strong> System prompt instructs Claude/GPT to analyze feature card, produce verdict (market, side, confidence, reasoning).<br>
        &bull; <strong>Duel System:</strong> Two experts analyze same game independently. Both agree = BET, disagree = 3rd arbiter decides winner by reasoning quality.<br>
        &bull; <strong>Evolution Engine:</strong> Weekly retrospective (high-confidence losses), monthly crossbreed, half-season promotion/pruning.
      </div>
    </div>
    <div class="callout callout--red">
      <strong>LLM results were mixed.</strong> Structure genome profitable solo (55.6% accuracy on Fav-RL). Momentum genome toxic (33.3%). Duel system's combined accuracy (40.5%) was worse than either solo. The Coinflip zone duel was killed entirely. LLM adds most value as a filter/gate on model signals (UNDER expansion zone: +15% ROI), not as a standalone predictor.
    </div>
  </div>

  <div class="section">
    <div class="section-title">Model Performance Summary</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Model</th><th>Target</th><th>Metric</th><th>Result</th><th>Status</th></tr></thead>
      <tbody>
        <tr><td>UNDER (CatBoost+Ridge V3)</td><td>P(under)</td><td>AUC / ROI</td><td>0.55+ / +6.1% to +34.3%</td><td class="text-green">Validated</td></tr>
        <tr><td>SPEC (CatBoost+Ridge)</td><td>P(home_win)</td><td>AUC</td><td>~0.55</td><td class="text-blue">Used for S3 edge</td></tr>
        <tr><td>OVER (3 variants)</td><td>P(over)</td><td>AUC</td><td>0.50 (zero signal)</td><td class="text-red">Dead</td></tr>
        <tr><td>NRFI (3 feature sets)</td><td>P(nrfi)</td><td>AUC</td><td>0.52 (structural ceiling)</td><td class="text-red">Dead</td></tr>
        <tr><td>Fav RL -1.5 (CatBoost)</td><td>P(cover)</td><td>AUC</td><td>0.517 (useless)</td><td class="text-red">Dead (rules better)</td></tr>
        <tr><td>LLM Structure (solo)</td><td>Fav RL verdict</td><td>Accuracy</td><td>55.6%</td><td class="text-yellow">Promising</td></tr>
        <tr><td>LLM Momentum (solo)</td><td>CF verdict</td><td>Accuracy</td><td>33.3%</td><td class="text-red">Toxic</td></tr>
        <tr><td>LLM Duel (Structure+Momentum)</td><td>CF verdict</td><td>Accuracy</td><td>40.5%</td><td class="text-red">Killed</td></tr>
        <tr><td>LLM UNDER Gate (session 19)</td><td>UNDER filter</td><td>ROI</td><td>+15.0% (expansion zone, 61 bets)</td><td class="text-green">Validated</td></tr>
        <tr><td>LLM UNDER Gate v2 (session 31)</td><td>Zone [0.52-0.53)</td><td>corr / ROI</td><td>corr=0.087, no robust edge, 718 games</td><td class="text-red">Dead</td></tr>
      </tbody>
    </table></div>
  </div>
"""
    return page("Models & LLM", "models.html", body, "Machine learning models and LLM expert systems")


def build_timeline():
    items = ""
    for date, sess, status, title, desc in TIMELINE:
        items += f"""      <div class="tl-item tl--{status}" data-tl-item="{status}">
        <div class="tl-date">{date} 2026 &bull; Session {sess}</div>
        <div class="tl-title">{title} {tag(status)}</div>
        <div class="tl-desc">{desc}</div>
      </div>\n"""

    body = f"""
  <div class="callout callout--blue">
    <strong>31 sessions, Feb 12 &mdash; Apr 15, 2026.</strong> From first data load to live production system. Filter by status to see the journey from exploration to go-live.
  </div>
  <div data-tl-root>
    <div class="filters">
      <select class="filter-select" data-tl-status>
        <option value="">All</option>
        <option value="live">Live</option>
        <option value="validated">Validated</option>
        <option value="dead">Dead Ends</option>
        <option value="research">Research</option>
      </select>
    </div>
    <div class="timeline">
{items}    </div>
  </div>
"""
    return page("Research Timeline", "timeline.html", body, "31 sessions of systematic research")


def build_season():
    body = """
  <div class="section">
    <div class="section-title">Season Ramp-Up Protocol</div>
    <div class="section-desc">Feature coverage depends on games played in the current season. The system scales up gradually as data accumulates.</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Period</th><th>Team Features</th><th>Pitcher Features</th><th>Action</th></tr></thead>
      <tbody>
        <tr><td><strong>W1 (Apr 1-7)</strong></td><td>100% (Elo carries over)</td><td>0%</td><td class="text-red"><strong>No bets.</strong> Collect data, shadow-run LLM experts.</td></tr>
        <tr><td><strong>W2 (Apr 8-14)</strong></td><td>100%</td><td>~8%</td><td class="text-yellow"><strong>Start betting:</strong> LLM-MULTI on team features only, 1/4 Kelly.</td></tr>
        <tr><td><strong>W3 (Apr 15-21)</strong></td><td>100%</td><td>~60%</td><td class="text-green"><strong>Full portfolio, 1/4 Kelly.</strong> First genome review (Sunday).</td></tr>
        <tr><td><strong>W4+ (Apr 22+)</strong></td><td>100%</td><td>~70%+</td><td class="text-green"><strong>Full portfolio, 1/2 Kelly.</strong> Weekly genome updates (Sundays).</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Live Production System</div>
    <div class="card">
      <div class="card-title">Daily Workflow</div>
      <div class="strat-rationale">
        1. <strong>Data fetch</strong> &mdash; <code>orchestrator.py</code> pulls ESPN scoreboard, starters, odds<br>
        2. <strong>Pipeline health</strong> &mdash; <code>check_2026_pipeline.py</code> runs 5 hard assertions<br>
        3. <strong>Pick generation</strong> &mdash; <code>generate_picks_2026.py</code> applies Tier 1/2/3 + Fav-RL filters<br>
        4. <strong>Output</strong> &mdash; JSON with picks, target pricing, feature snapshots for audit<br>
        5. <strong>Review</strong> &mdash; Human review before Polymarket order placement
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Safety Guardrails (Session 29)</div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">IO Safety Layer</div>
        <div class="text-muted text-sm mt-8">
          &bull; Atomic writes (write to tmp, rename)<br>
          &bull; Timestamped backups before every overwrite<br>
          &bull; Sidecar JSONs with metadata (generator, date_col)<br>
          &bull; JSONL audit log for all write operations<br>
          &bull; Dual-path architecture: pitchers/ (historical) vs pitchers_2026/ (live)
        </div>
      </div>
      <div class="card">
        <div class="card-title">Daily Health Check</div>
        <div class="text-muted text-sm mt-8">
          &bull; Assertion 1: No duplicate game IDs<br>
          &bull; Assertion 2: All starters have pitcher codes<br>
          &bull; Assertion 3: Odds within valid range<br>
          &bull; Assertion 4: No future dates in results<br>
          &bull; Assertion 5: Row count within expected bounds
        </div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">Portfolio Allocation</div>
    <div class="table-wrap"><table>
      <thead><tr><th>Strategy</th><th class="num">Volume</th><th class="num">Target ROI</th><th class="num">Stake</th><th>Notes</th></tr></thead>
      <tbody>
        <tr><td>Tier 1: Bullpen Day ML</td><td class="num">~24</td><td class="num positive">+63.9%</td><td class="num">2x base</td><td>Highest conviction. Both ML + RL bets.</td></tr>
        <tr><td>Tier 1: Bullpen Day RL +1.5</td><td class="num">~24</td><td class="num positive">+31.2%</td><td class="num">1x base</td><td>Lower odds, higher hit rate. Paired with ML.</td></tr>
        <tr><td>Tier 3: Pitcher Advantage</td><td class="num">~8</td><td class="num positive">+24.7%</td><td class="num">1x base</td><td>High conviction but rare.</td></tr>
        <tr><td>Fav -1.5 Run Line</td><td class="num">~137</td><td class="num positive">+15.0%</td><td class="num">1x base</td><td>Highest volume. Bulk of portfolio.</td></tr>
        <tr><td>Tier 2: Fatigue Gap</td><td class="num">~25</td><td class="num positive">+11.2%</td><td class="num">0.5x base</td><td>Lower conviction. Smaller stake.</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Early 2026 Results (Mar 26 &mdash; Apr 11)</div>
    <div class="callout">
      <strong>6 picks generated, 2 resolved.</strong> Too early for statistical significance but the system is operational and generating picks daily.
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Date</th><th>Game</th><th>Tier</th><th>Market</th><th>Result</th></tr></thead>
      <tbody>
        <tr><td>Apr 6</td><td>DET @ MIN</td><td>Tier 3</td><td>RL +1.5</td><td class="text-red">LOST (3-7, margin -4)</td></tr>
        <tr><td>Apr 11</td><td>MIN @ TOR</td><td>Tier 3</td><td>RL +1.5</td><td class="text-green">WON (7-4, margin +3)</td></tr>
      </tbody>
    </table></div>
  </div>

  <div class="section">
    <div class="section-title">Next Steps</div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">Session D (Pending)</div>
        <div class="text-muted text-sm mt-8">Polymarket order-book monitor (L2). Watch bid/ask spreads, track line movement, identify optimal entry points.</div>
      </div>
      <div class="card">
        <div class="card-title">Session E (Pending)</div>
        <div class="text-muted text-sm mt-8">Shadow pick tracking. Log all picks (including line-flipped bullpen days) without placing real bets. Build calibration dataset.</div>
      </div>
    </div>
  </div>
"""
    return page("2026 Season Plan", "season.html", body, "Ramp-up protocol, live system, and early results")


# ── GENERATE ───────────────────────────────────────────────────────────────────

def main():
    pages = [
        ("index.html",      build_index()),
        ("strategies.html",  build_strategies()),
        ("dead-ends.html",   build_dead_ends()),
        ("data.html",        build_data()),
        ("models.html",      build_models()),
        ("timeline.html",    build_timeline()),
        ("season.html",      build_season()),
    ]
    for fname, html in pages:
        path = os.path.join(OUT, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  {fname} ({len(html):,} bytes)")
    print(f"\nGenerated {len(pages)} pages in {OUT}")

if __name__ == "__main__":
    main()
