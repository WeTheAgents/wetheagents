# MLB Rule Changes 2022-2026: Impact on Statistics & Betting

> Source: Research compilation, Feb 2026. Critical for adjusting backtest models (historical data ends 2021).

## Timeline Summary

| Year | Key Changes |
|------|-------------|
| 2022 | Reverted to normal rules post-COVID. Baseline year. |
| 2023 | **Pitch clock, shift ban, bigger bases** — biggest changes in decades |
| 2024 | Pitch clock tweak (18s with runners), mound visits reduced to 4 |
| 2025 | Shift violation = auto first base + advancement, replay expansion |
| 2026-27 | Automated Ball-Strike (ABS) challenge system announced |

---

## 1. Pitch Clock (2023+)

- **2023**: 15s bases empty, 20s with runners
- **2024**: 15s bases empty, 18s with runners (reduced)
- Max 2 step-offs before penalty

**Impact:**
- Runs/game: **+0.5-0.7** (8.6 → 9.1-9.3)
- Game duration: **-24 min** (3:06 → 2:42, lowest since 1984)
- Pitcher fatigue increases late-game scoring

**Betting:** Favors OVER on totals. F5 less affected than full game.

---

## 2. Defensive Shift Ban (2023+)

- Min 4 infielders on dirt, 2 on each side of 2nd base
- **2025**: Violation = automatic first base + runner advancement (was just auto ball)

**Impact:**
- Batting avg: **+5 pts** (.243 → .248 in 2023)
- BABIP: **+7 pts** (.290 → .297)
- **Left-handed hitters: +10 pts BA**, pulled grounders/liners +36 pts
- Right-handed hitters: minimal change
- **2024 regression**: BA dropped to .240 (lowest since 1968!) — shift ban effect plateaued

**Betting:** Left-handed heavy lineups gained edge. Player hit props for lefties more valuable.

---

## 3. Bigger Bases (2023+)

- 15" → 18" square (home plate unchanged)
- Reduces distance between bases by ~4.5"

**Impact:**
- Stolen bases/game: **+28%** (1.4 → 1.8)
- SB success rate: **75.4% → 80.2%** (historic high)
- Total SBs: 2,486 → 3,503 (second-most in 100+ years)
- **2024: no regression** — sustained at higher levels

**Betting:** SB props dramatically more valuable. More runners in scoring position → higher YRFI rates.

---

## 4. Ghost Runner / Extra Innings (permanent since 2020)

- Auto runner at 2nd base to start each extra inning
- Regular season only (postseason = traditional rules)

**Impact:**
- Extra innings resolve faster (~1 inning shorter)
- ~420 innings of gameplay saved over 2020-22

**Betting:** Heavy OVER bias in extra innings. Both teams likely to score quickly.

---

## 5. 7-Inning Doubleheaders (2020-2021 ONLY)

- **Discontinued in 2022.** Only affects our 2021 data.
- Each DH game = 7 innings instead of 9.
- **Already filtered out** in our dataset (double-headers removed).

---

## 6. 2026-27: Automated Ball-Strike (ABS) Challenge System

- 2 challenges per team per game
- Batter/pitcher/catcher can challenge by tapping cap/helmet
- **Not yet in effect** (announced, coming 2026-27 season)
- Impact unknown — may standardize strike zone, potentially reducing walks

---

## Cumulative Statistical Shift (2022 → 2023)

| Metric | 2022 | 2023 | Change |
|--------|------|------|--------|
| Runs/Game | 8.6 | 9.1-9.3 | **+0.5-0.7** |
| Batting Average | .243 | .248 | +5 pts |
| BABIP | .290 | .297 | +7 pts |
| Stolen Bases/Game | 1.4 | 1.8 | **+28%** |
| SB Success Rate | 75.4% | 80.2% | +4.8 pts |
| Game Duration | 3:06 | 2:42 | **-24 min** |

**2024 WARNING:** BA regressed to .240 (8 pts drop from 2023). Scoring boost may normalize.

---

## Implications for Our Backtest

Our data covers 2010-2021. Live trading starts April 2026. Key adjustments:

1. **Game Totals (O/U):** +0.5-0.7 runs/game systematic shift since 2023. Historical O/U lines will be LOWER than current.
2. **YRFI:** Higher frequency in 2023+ due to more runs + more SBs + shift ban hits. Adjust baseline rates upward.
3. **F5 Totals:** Partially affected (pitch clock fatigue less relevant in first 5 innings, but shift ban and SBs still apply).
4. **Moneyline/Spread:** Left-handed heavy lineups gained 5-10 points BA advantage.
5. **Stolen Base Props:** Completely different landscape — 2023+ data needed for any SB-related betting.
6. **Run Line:** More scoring = more variance = run line outcomes may shift.

### Key Takeaway

Historical backtest (2010-2021) provides **directional** validation of strategies, but absolute numbers (hit rates, ROI) will need calibration for the 2023+ environment. The pitch clock and shift ban represent a **structural regime change** in MLB — comparable to the steroid era shift but in reverse (rule-driven rather than player-driven).
