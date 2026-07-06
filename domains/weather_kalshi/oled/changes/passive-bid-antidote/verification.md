# Verification — Passive-Bid Adverse Selection Antidote

Date: 2026-07-06

## Acceptance criteria (spec.md)

- [x] R1: live ledger reproduced — P(fill|loss)=100% (16/16), P(fill|win)=27% (3/11),
      total −$373. 2×2: won&filled 3, won&unfilled 8, lost&filled 16, lost&unfilled 0.
- [x] R2: intraday 2h slope separates at scale (n≈4600): flat → 15% rise, still-climbing
      → 42%, monotonic to 68%+ at +5°. Morning forecast (NBM/ens) does NOT separate
      (gate 28% vs 34%). Documented in report §2.
- [x] R3: `locked` gate defined and applied (slope ≤ 0 AND entry ≥ city peak hour).
- [x] R4: gated-passive sim (n=728; test n=351). Test: ungated P(fill|loss)=0.75,
      P(win|fill)=0.31, −$2.76/trade → gated 0.50 / 0.41 / −$1.80. Excluded (still-climbing)
      worst: 0.86 / 0.28 / −$3.14. Gate halves adverse selection.
- [x] R5: profitable niche found — gated × entry-price 0.5–0.85: P(win|fill)=0.79,
      **+$0.85/trade** (test, n=34). Loss decomposition (test filled losers, n=146):
      rise-losses 79% (weather-gateable), basis-losses 21% (WU≠METAR). Basis ceiling:
      gated w/o basis-losses = **+$2.23/trade** vs −$1.80 now.
- [x] R6: `reports/passive_antidote_report.html` built; all numbers from the script.

## Method notes / honesty

- Fill model on the historical candle path: a passive bid at entry_price − 1¢ is deemed
  filled if any later candle ≤ bid before resolution. This faithfully reproduces the
  live behaviour (a resting bid fills as a loser collapses toward 0) but has no order-book
  depth — it is a single-price-series proxy, not a book simulation.
- The `locked` gate is fixed-15:00 for the historical sim (checkpoint data granularity);
  the live runner would evaluate the slope at each city's actual h*50 entry hour.
- Small n in the positive cells (34–60 trades), single season (summer), test ~2.5 weeks,
  live n=27 directional only. Not overclaimed.

## Winner-no-fill / market-efficiency check (operator-driven, added)

Question: do winner-no-fill trades coincide with the market repricing the winner UP —
i.e. is the lock/deceleration signal already priced, so a passive bid below entry can't
catch winners? Reconstructed post-entry best_ask run-up (snapshots) + pre-entry 2h slope
(METAR) per settled trade:
- WON+nofill (n=8): ask ran up **+20¢** after we placed (up to +62¢, Tokyo); WON+fill +26¢;
  LOST+fill only +7¢ (price came DOWN to our bid → we filled).
- The market reprices locking-in winners in real time → passive-below structurally misses
  them; the market's efficiency at the lock IS the source of our adverse selection.
- Not a clean single "deceleration oscillator" (several winner-no-fills entered while still
  climbing), but the net effect holds.
- Marketable-at-ask on live A trades: −$245 vs passive −$331 — still deep negative (entry
  price already encodes P(win); favorites win but pay little, longshots pay but rarely win).
- Live "locked" cell (slope≤0): n=7, win 29% — the historical +$0.85 niche is NOT confirmed
  live (0 live trades landed in the gated 0.5–0.85 cell).

## Verdict recorded in report (revised, honest)

Passive-ungated is structurally dead. The intraday slope gate reduces adverse selection
(P(fill|loss) 0.75→0.50) but does NOT flip P&L positive, and the historical profitable
niche is not confirmed live. The market already trades the lock/deceleration faster than
our signal becomes actionable. The only theoretical opening is SPEED: sub-hourly obs
(5-min ASOS/SPECI) + immediate marketable execution to front-run the repricing; plus a
resolution-station audit (removes ~20% basis losses without weather). If sub-hourly shows
no lead, the edge is not harvestable at our horizon → close the scalp theme on these contracts.

## Codex review — 3 findings (P2×2, P3), all fixed

- [P2] hardcoded PASSIVE_DIR → env-overridable (PASSIVE_PAPER_DIR) with graceful fallback.
- [P2] render() accessed live['ct'] on empty ledger → live.get() guards + live_ok flag.
- [P3] bid ≤ 0 before 1/bid → skip bids ≤ 0.005.
Domain suite green (21 passed) after fixes.
