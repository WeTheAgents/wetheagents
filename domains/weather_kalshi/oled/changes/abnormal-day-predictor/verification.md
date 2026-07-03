# Verification — Abnormal-Day Predictor

Date: 2026-07-03

## Acceptance criteria (spec.md)

- [x] Labels hand-checked on 3 events:
  - Madrid 2026-06-29: run_max 89.6°F@15:00 → 93.2°F@17:00, winner +2 brackets → rise=1 ✓
  - Hong Kong 2026-06-29: plateau from 13:00, winner −1 (WU basis down) → rise=0 ✓
    (basis losses correctly excluded from the rise label)
  - Warsaw 2026-03-20: diff=−5 — March basis/coverage anomaly, lands in the separate
    basis bucket (5.2% of events), does not contaminate rise labels ✓
- [x] Leak-freedom by construction: rise_lag1 requires previous *calendar* day;
  city_rate fitted only on dates ≤ 2026-06-15; market features cut at D−1 20:00 local
  (candle timestamps); peak_hour_clim uses full archive (structural constant, noted);
  warming uses D−1 realized METAR + D−1 evening market prices.
- [x] L1 verdict (test > 2026-06-15, n=487 events): flag separates
  P(rise)=53.8% vs 20.6%. Strategy A: kept +93.5% (n=154) vs skipped −18.0% (n=198),
  baseline +30.8% (n=352). Strategy B: filter immaterial (+1.3% vs −0.8%).
- [x] L2 verdict: on flagged days, delayed A@17:00 = +19.8% (n=124);
  above-bracket buy @15:00 = +8.1% (n=199, sign flips to −46.8% on clean days).
  Rejected variant recorded: reversing B at 16:00 does NOT work (−51%).
- [x] Report reports/abnormal_day_report.html built and sent.

## Caveats carried into the report

Test window ≈ 2.5 weeks; single season; candle≈mid prices; flag thresholds fixed
a priori (0.5 / entropy median / +2°) and not tuned on test; ens/nbm/TAF features
are June-only and excluded from the flag.

## Key structural insight

Most of the phenomenon is climatological city timing (Madrid 85% vs Hong Kong 0%),
i.e. the scalp system should get per-city entry hours regardless of the flag;
the flag adds weather-regime dynamics (persistence 54%/23%, warming) on top.
