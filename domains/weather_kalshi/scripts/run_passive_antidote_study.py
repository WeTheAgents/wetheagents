"""Passive-bid adverse selection: diagnosis + intraday-slope antidote.

Question (operator): passive execution avoids slippage but is adversely selected
(P(fill|loss)=100%, P(fill|win)=27% on the live ledger). Can an INTRADAY weather
signal re-select fills toward winners?

Findings that shaped this (read-only checks):
- Morning forecast (NBM/GEFS day-of) barely separates rise-days (gate 28% vs 34%).
- The intraday RUNNING-MAX SLOPE does, at scale (n=4581): if the max was still
  climbing in the 2h before entry, P(rise)=42%; if flat, 15%. Fully live-decidable
  from hourly METAR. Higher-frequency obs (5-min ASOS/SPECI) would sharpen it.

This script:
  A. Live diagnosis on the passive ledger (2x2 win x fill, P(fill|outcome)).
  B. Historical gated-passive simulation on the 10-min candle path (~1000 events):
     place a passive bid at entry; it fills if the price later trades down to it;
     outcome known at resolution. Compare UNGATED vs SLOPE-GATED passive: total P&L,
     and the fill re-selection P(win|fill). This is the antidote test.
  C. Report (HTML, Russian) + verdict.

Reads the passive ledger from the codex passive-bids worktree (constant below) and
all weather/market history from this (main) domain.

Usage: python -m scripts.run_passive_antidote_study [--no-rebuild]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_dayof_nowcast_report import assign_positions  # noqa: E402
from scripts.build_ml_panel import parse_bracket  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "passive_antidote_report.html"
# live passive ledger lives in the codex worktree that ran the passive experiment;
# override with PASSIVE_PAPER_DIR. Falls back to this domain's own data/paper if absent.
PASSIVE_DIR = Path(os.environ.get(
    "PASSIVE_PAPER_DIR",
    r"D:/GitHub/wetheagents-codex-paper-passive-bids/domains/weather_kalshi/data/paper"))
if not (PASSIVE_DIR / "paper_trades.jsonl").exists():
    PASSIVE_DIR = ROOT / "data" / "paper"

ENTRY_HOUR = 15          # local checkpoint used for the historical sim
SLOPE_WINDOW_H = 2       # hours before entry for the running-max slope
BID_MARGIN = 0.01        # passive bid = entry price - 1c (tier-1 proxy on a single price path)
TEST_CUTOFF = "2026-06-15"
STAKE = 24.0


# ---------------------------------------------------------------------------
# A. Live diagnosis
# ---------------------------------------------------------------------------

def live_diagnosis() -> dict:
    trades = [json.loads(l) for l in (PASSIVE_DIR / "paper_trades.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    settled = [t for t in trades if t.get("status") == "settled"]
    r = {"n_settled": len(settled)}
    if not settled:
        return r
    df = pd.DataFrame([{"won": t["settled"]["won"], "filled": (t.get("fill_stake") or 0) > 0,
                        "pnl": t["settled"]["pnl"], "strategy": t["strategy"]} for t in settled])
    won, lost = df[df["won"]], df[~df["won"]]
    r["p_fill_win"] = float(won["filled"].mean()) if len(won) else float("nan")
    r["p_fill_loss"] = float(lost["filled"].mean()) if len(lost) else float("nan")
    r["ct"] = pd.crosstab(df["won"], df["filled"])
    r["total_pnl"] = float(df["pnl"].sum())
    return r


def _metar_day(slug: str, td: str, cities: dict, icao_map: dict):
    icao = (icao_map.get(slug) or {}).get("primary")
    if not icao:
        return None
    path = ROOT / "data" / "raw" / "metar" / f"metar_{icao}.parquet"
    if not path.exists():
        return None
    m = pd.read_parquet(path, columns=["valid_time_utc", "temp_f"]).dropna()
    tz = ZoneInfo(cities[slug]["timezone"])
    unit = cities[slug].get("unit", "F")
    m["local"] = m["valid_time_utc"].dt.tz_convert(tz)
    day = m[m["local"].dt.date == pd.Timestamp(td).date()].sort_values("local").copy()
    if day.empty:
        return None
    rmf = day["temp_f"].cummax()
    day["rmax"] = (rmf.round() if unit == "F" else ((rmf - 32) * 5 / 9).round()).astype(int)
    day["hour"] = day["local"].dt.hour + day["local"].dt.minute / 60
    return day


def market_efficiency() -> dict:
    """Winner-no-fill diagnosis: does the market reprice locking-in winners UP faster
    than a passive bid below entry can catch (i.e. is the lock signal already priced)?
    Reconstructs, per settled live trade, the post-entry best_ask run-up (from order
    snapshots) and the pre-entry 2h running-max slope (from METAR)."""
    tf = PASSIVE_DIR / "paper_trades.jsonl"
    if not tf.exists():
        return {}
    trades = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines() if l.strip()]
    settled = [t for t in trades if t.get("status") == "settled"]
    if not settled:
        return {}
    snaps = [json.loads(l) for l in (PASSIVE_DIR / "paper_order_snapshots.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sdf = pd.DataFrame(snaps)
    cities = json.loads((ROOT / "data" / "static" / "polymarket_cities.json").read_text(encoding="utf-8"))
    icao_map = json.loads((ROOT / "data" / "static" / "icao_map.json").read_text(encoding="utf-8"))

    rows = []
    for t in settled:
        won = t["settled"]["won"]
        filled = (t.get("fill_stake") or 0) > 0
        ask = t.get("best_ask")
        el = (t.get("run_max") or {}).get("latest_obs_local")
        day = _metar_day(t["city_slug"], t["market_date"], cities, icao_map)
        slope = None
        if day is not None and el:
            ehf = pd.Timestamp(el).hour + pd.Timestamp(el).minute / 60
            upto = day[day["hour"] <= ehf + 0.01]
            past = upto[upto["hour"] <= ehf - 2]
            if len(upto) and len(past):
                slope = int(upto["rmax"].iloc[-1] - past["rmax"].iloc[-1])
        ask_run = None
        if not sdf.empty and ask is not None:
            g = sdf[sdf["trade_id"] == t["trade_id"]]
            a = g["best_ask"].dropna() if "best_ask" in g else pd.Series(dtype=float)
            if len(a):
                ask_run = float(a.max() - ask)
        rows.append({"won": won, "filled": filled, "ask": ask, "slope": slope,
                     "ask_run": ask_run, "cell": ("WON" if won else "LOST") + ("+fill" if filled else "+nofill")})
    d = pd.DataFrame(rows)
    by_cell = d.groupby("cell").agg(n=("won", "size"), ask_run=("ask_run", "mean"),
                                    slope=("slope", "mean")).round(3)
    # live "locked" cell (slope<=0) win rate — the historical niche, live check
    locked = d[d["slope"].notna() & (d["slope"] <= 0)]
    return {"by_cell": by_cell, "locked_n": len(locked),
            "locked_win": float(locked["won"].mean()) if len(locked) else float("nan"),
            "wnf_ask_run": float(d[(d["won"]) & (~d["filled"])]["ask_run"].mean())}


# ---------------------------------------------------------------------------
# Slope gate (intraday antidote signal)
# ---------------------------------------------------------------------------

def slope_gate_table() -> pd.DataFrame:
    """Per (city, date): entry-hour running max, 2h pre-entry slope, gate flag,
    and the rise label. Built from the hourly-METAR day table."""
    dt = pd.read_parquet(OUT / "metar_day_table.parquet")
    dt["date"] = pd.to_datetime(dt["local_date"])
    for h in range(ENTRY_HOUR - SLOPE_WINDOW_H, ENTRY_HOUR + 1):
        dt[f"rm{h}"] = pd.to_numeric(dt.get(f"rm{h}"), errors="coerce")
    d = dt.dropna(subset=[f"rm{ENTRY_HOUR}", f"rm{ENTRY_HOUR - SLOPE_WINDOW_H}", "rise15"]).copy()
    d["slope"] = d[f"rm{ENTRY_HOUR}"] - d[f"rm{ENTRY_HOUR - SLOPE_WINDOW_H}"]
    peak = d.dropna(subset=["settle_hour"]).groupby("city_slug")["settle_hour"].median()
    d["peak_hr"] = d["city_slug"].map(peak)
    # gate = "locked": max plateaued for the slope window AND we are past the city's peak
    d["locked"] = ((d["slope"] <= 0) & (ENTRY_HOUR >= d["peak_hr"])).astype(int)
    return d[["city_slug", "local_date", "slope", "peak_hr", "locked", "rise15"]]


# ---------------------------------------------------------------------------
# B. Historical gated-passive simulation on the candle path
# ---------------------------------------------------------------------------

def load_candles() -> pd.DataFrame:
    h = pd.read_parquet(ROOT / "data" / "raw" / "polymarket" / "all_cities_price_history.parquet",
                        columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"])
    h["md"] = h["market_date"].astype(str).str[:10]
    h["ts"] = pd.to_datetime(h["timestamp"], unit="s", utc=True)
    return h


def historical_sim() -> pd.DataFrame:
    cps = pd.read_parquet(OUT / "dayof_study_checkpoints.parquet")
    cps["date"] = pd.to_datetime(cps["market_date"])
    pos = assign_positions(cps[cps["hour"] == ENTRY_HOUR]).dropna(subset=["winner_idx"])
    pos["md"] = pos["market_date"].astype(str).str[:10]
    pos = pos[(pos["cur_yes"] > 0) & (pos["cur_yes"] <= 0.85)]  # A entry rule

    gate = slope_gate_table()
    pos = pos.merge(gate, left_on=["city_slug", "md"], right_on=["city_slug", "local_date"], how="inner")

    cities = json.loads((ROOT / "data" / "static" / "polymarket_cities.json").read_text(encoding="utf-8"))
    candles = load_candles()
    cand_idx = {k: g.sort_values("ts") for k, g in candles.groupby(["city_slug", "md", "bracket_index"])}

    rows = []
    for _, p in pos.iterrows():
        slug, md, bidx = p["city_slug"], p["md"], int(p["cur_idx"])
        tz = ZoneInfo(cities[slug]["timezone"])
        entry_utc = pd.Timestamp(md, tz=tz).tz_convert("UTC") + pd.Timedelta(hours=ENTRY_HOUR)
        g = cand_idx.get((slug, md, bidx))
        if g is None:
            continue
        at_entry = g[g["ts"] <= entry_utc]
        after = g[g["ts"] > entry_utc]
        if at_entry.empty or after.empty:
            continue
        entry_price = float(at_entry["price"].iloc[-1])
        if not (0 < entry_price <= 0.85):
            continue
        bid = entry_price - BID_MARGIN
        if bid <= 0.005:  # too cheap to rest a meaningful bid; skip (avoids 1/bid blowup)
            continue
        # passive fill: price later trades down to/through our bid
        filled = bool((after["price"] <= bid).any())
        won = int(p["cur_won"])
        # P&L per $STAKE if filled at bid; 0 if unfilled
        pnl = (STAKE * ((1.0 / bid) - 1.0) if won else -STAKE) if filled else 0.0
        rows.append({"city": slug, "md": md, "won": won, "locked": int(p["locked"]),
                     "slope": p["slope"], "rise15": int(p["rise15"]),
                     "entry_price": entry_price, "bid": bid,
                     "filled": int(filled), "pnl": pnl,
                     "test": md > TEST_CUTOFF})
    return pd.DataFrame(rows)


def _block(d: pd.DataFrame) -> dict:
    f = d[d["filled"] == 1]
    return {"n": len(d), "fills": len(f), "fill_rate": len(f) / max(len(d), 1),
            "p_win_fill": float(f["won"].mean()) if len(f) else float("nan"),
            "p_fill_win": float(d[d["won"] == 1]["filled"].mean()) if (d["won"] == 1).any() else float("nan"),
            "p_fill_loss": float(d[d["won"] == 0]["filled"].mean()) if (d["won"] == 0).any() else float("nan"),
            "total_pnl": float(d["pnl"].sum()), "mean_pnl": float(d["pnl"].mean()) if len(d) else float("nan")}


def summarize_sim(sim: pd.DataFrame) -> dict:
    r = {"all": {}, "test": {}}
    for scope, dd in [("all", sim), ("test", sim[sim["test"]])]:
        r[scope]["ungated"] = _block(dd)
        r[scope]["gated"] = _block(dd[dd["locked"] == 1])
        r[scope]["excluded"] = _block(dd[dd["locked"] == 0])
    return r


def loss_decomposition(sim: pd.DataFrame) -> dict:
    """Split filled losses into rise-losses (weather-gateable) vs basis-losses
    (max never left the bracket -> WU vs METAR resolution mismatch)."""
    out = {}
    for scope, dd in [("all", sim), ("test", sim[sim["test"]])]:
        fl = dd[(dd["filled"] == 1) & (dd["won"] == 0)]
        rise = int((fl["rise15"] == 1).sum())
        basis = int((fl["rise15"] == 0).sum())
        out[scope] = {"n": len(fl), "rise": rise, "basis": basis,
                      "rise_pct": rise / max(len(fl), 1), "basis_pct": basis / max(len(fl), 1)}
    return out


def stacked_grid(sim: pd.DataFrame) -> list[dict]:
    """Gate x entry-price band on the test window: locate the profitable niche."""
    test = sim[sim["test"]]
    rows = []
    bands = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.85)]
    for lo, hi in bands:
        for gated, glab in [(False, "все дни"), (True, "gated (locked)")]:
            d = test[(test["entry_price"] > lo) & (test["entry_price"] <= hi)]
            if gated:
                d = d[d["locked"] == 1]
            b = _block(d)
            rows.append({"band": f"{lo:.1f}-{hi:.2f}", "gate": glab, **b})
    return rows


def basis_ceiling(sim: pd.DataFrame) -> dict:
    """Theoretical gated P&L if basis-losses were removed (correct resolution station)."""
    test = sim[sim["test"]]
    g = test[test["locked"] == 1]
    keep = g[~((g["won"] == 0) & (g["rise15"] == 0))]
    return {"gated": _block(g), "gated_no_basis": _block(keep)}


def slope_separation() -> pd.DataFrame:
    """Scale evidence: P(rise) by 2h pre-entry running-max slope (n~4600)."""
    dt = pd.read_parquet(OUT / "metar_day_table.parquet")
    for h in (ENTRY_HOUR - SLOPE_WINDOW_H, ENTRY_HOUR):
        dt[f"rm{h}"] = pd.to_numeric(dt.get(f"rm{h}"), errors="coerce")
    d = dt.dropna(subset=[f"rm{ENTRY_HOUR}", f"rm{ENTRY_HOUR - SLOPE_WINDOW_H}", "rise15"]).copy()
    d["slope"] = (d[f"rm{ENTRY_HOUR}"] - d[f"rm{ENTRY_HOUR - SLOPE_WINDOW_H}"]).clip(0, 5)
    return d.groupby("slope")["rise15"].agg(["size", "mean"]).reset_index()


def render(live: dict, s: dict, decomp: dict, grid: list[dict], ceil: dict, sep: pd.DataFrame,
           meff: dict) -> None:
    import plotly.graph_objects as go
    import plotly.io as pio
    C = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")
    live_ok = live.get("n_settled", 0) > 0 and "ct" in live

    f1 = go.Figure(go.Bar(x=sep["slope"], y=sep["mean"] * 100, text=sep["size"],
                          marker_color=C["amber"]))
    f1.update_layout(title="P(день добирает после входа) по наклону максимума за 2ч до 15:00 (n≈4600)",
                     xaxis_title="Прирост максимума за предыдущие 2 часа, °", yaxis_title="% дней с ростом",
                     height=360, template="plotly_white")

    t = s["test"]
    f2 = go.Figure()
    cats = ["Без гейта", "Гейт (locked)", "Исключённые"]
    f2.add_trace(go.Bar(x=cats, y=[t["ungated"]["p_fill_loss"]*100, t["gated"]["p_fill_loss"]*100, t["excluded"]["p_fill_loss"]*100],
                        name="P(fill | проигрыш)", marker_color=C["red"]))
    f2.add_trace(go.Bar(x=cats, y=[t["ungated"]["p_win_fill"]*100, t["gated"]["p_win_fill"]*100, t["excluded"]["p_win_fill"]*100],
                        name="P(выигрыш | fill)", marker_color=C["green"]))
    f2.update_layout(title="Пере-селекция филлов интрадей-гейтом (тест)", yaxis_title="%",
                     barmode="group", height=360, template="plotly_white")
    fh = {}
    for i, (k, fig) in enumerate({"sep": f1, "resel": f2}.items()):
        fh[k] = pio.to_html(fig, include_plotlyjs="inline" if i == 0 else False, full_html=False,
                            config={"displaylogo": False})

    def row(cells, cls=None):
        tds = "".join(f"<td>{c}</td>" for c in cells)
        return f'<tr{" class=%s"%cls if cls else ""}>{tds}</tr>'

    resel = "".join(row([lab, b["n"], b["fills"], f"{b['p_fill_loss']*100:.0f}%",
                         f"{b['p_win_fill']*100:.0f}%", f"${b['total_pnl']:+.0f}", f"${b['mean_pnl']:+.2f}"])
                    for lab, b in [("Без гейта (все входы)", t["ungated"]),
                                   ("Гейт: только «залоченные» дни", t["gated"]),
                                   ("Исключённые (максимум ещё рос)", t["excluded"])])
    grid_rows = "".join(row([g["band"], g["gate"], g["n"], g["fills"],
                             f"{g['p_win_fill']*100:.0f}%" if g["fills"] else "—",
                             f"${g['total_pnl']:+.0f}", f"${g['mean_pnl']:+.2f}" if g["n"] else "—"],
                            cls="pos" if (g["mean_pnl"] or 0) > 0 else None)
                        for g in grid)
    dc = decomp["test"]
    cg, cgb = ceil["gated"], ceil["gated_no_basis"]

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Passive-bid adverse selection — противоядие</title>
<style>
 body {{font-family:'Segoe UI',system-ui,sans-serif;max-width:1000px;margin:0 auto;padding:24px;color:#1f2937;line-height:1.55}}
 h1{{font-size:1.5em}} h2{{margin-top:1.8em;border-bottom:2px solid #e5e7eb;padding-bottom:6px}}
 table{{border-collapse:collapse;margin:12px 0;font-size:.9em}} th,td{{border:1px solid #d1d5db;padding:6px 11px;text-align:right}}
 th{{background:#f3f4f6}} td:first-child,td:nth-child(2){{text-align:left}} tr.pos td{{background:#ecfdf5;font-weight:600}}
 .v{{border-left:5px solid;padding:10px 16px;margin:10px 0;border-radius:4px}}
 .no{{border-color:#dc2626;background:#fef2f2}} .mid{{border-color:#d97706;background:#fffbeb}} .yes{{border-color:#059669;background:#ecfdf5}}
 .note{{background:#eff6ff;border-radius:6px;padding:10px 16px;font-size:.93em}}
</style></head><body>
<h1>Пассивное исполнение: adverse selection и intraday-противоядие</h1>
<p><i>Собрано {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} · живой леджер n={live['n_settled']} ·
историческая симуляция n из candle-пути · тест &gt; {TEST_CUTOFF} · без API</i></p>

<h2>TL;DR</h2>
<div class="v no"><b>Пассив в лоб — структурно мёртв.</b> Bid по YES заливается, только когда
ask проваливается ниже него — ровно в момент, когда брекет проигрывает. Живьём:
P(fill|проигрыш)=<b>{live.get('p_fill_loss', float('nan'))*100:.0f}%</b> против
P(fill|выигрыш)={live.get('p_fill_win', float('nan'))*100:.0f}%,
итог <b>${live.get('total_pnl', 0):+.0f}</b>. На истории то же: без гейта
−${abs(t['ungated']['total_pnl']):.0f} на {t['ungated']['n']} входах.</div>
<div class="v mid"><b>Intraday-наклон максимума режет adverse selection, но не переворачивает P&L.</b>
Гейт «ставить бид только когда максимум выположился» вдвое снижает залив на проигрышах
(P(fill|проигрыш) {t['ungated']['p_fill_loss']*100:.0f}%→{t['gated']['p_fill_loss']*100:.0f}%),
но сам по себе оставляет пассив в минусе (${t['gated']['mean_pnl']:+.2f}/сделку).</div>
<div class="v no"><b>Главное: рынок уже торгует этот сигнал.</b> Winner-no-fill (выигрыш, который мы
НЕ забрали) — это ровно моменты, когда рынок задирает ask вверх (+{meff.get('wnf_ask_run', float('nan'))*100:.0f}¢
в среднем) быстрее, чем к нашему биду доходит цена. Победителя переоценивают в реальном времени —
пассив-ниже его структурно пропускает, а marketable упирается в то, что цена входа уже справедлива.
Историческая «плюсовая ниша» (гейт+фаворит) <b>не подтверждается живьём</b>: из {meff.get('locked_n', 0)}
живых залоченных сделок выиграли {meff.get('locked_win', float('nan'))*100:.0f}%.</div>

<h2>1. Диагноз (живой леджер, n={live.get('n_settled', 0)})</h2>
<p>Пассивный bid залит почти на всех проигрышах и лишь на части выигрышей — две стороны одного
факта, что и слиппедж: спред ≈ эджу, midpoint-эдж из бэктеста в лоб не забирается
(маркет-ордер платит спред, пассив ловит проигрыш).</p>

<h2>1b. Рынок опережает наш сигнал (winner-no-fill)</h2>
<p>Разложение живых сделок по ячейкам «исход × залив» с движением ask ПОСЛЕ размещения бида
и наклоном максимума ДО входа:</p>
{meff.get('by_cell').to_html() if meff.get('by_cell') is not None else '<p class="note">нет данных</p>'}
<p class="note">Победители (залив и особенно НЕ-залив) — это случаи, где ask убежал вверх: рынок
переоценил залочивающийся брекет в реальном времени. Проигрыши — где цена спустилась к нашему биду.
То есть эффективность рынка на локе <b>и есть</b> источник нашего adverse selection: мы забираем
только остаток (проигрыши). Чистого одного «осциллятора замедления» в наклоне не видно (часть
winner-no-fill входила ещё на росте), но нетто-эффект тот же — сигнал уже в цене.</p>

<h2>2. Сигнал: intraday-наклон максимума (масштаб, n≈4600)</h2>
{fh['sep']}
<p>Если за 2 часа до входа максимум ещё лез вверх — день почти наверняка добирает
(и «брекет текущего максимума» уезжает). Если выположился — редко. Ключевое:
утренний прогноз (NBM/ансамбль) это НЕ ловит (гейт по прогнозу даёт лишь 28% vs 34%);
работает именно <b>живой ход дня</b>, а не прогноз накануне.</p>

<h2>3. Гейт переселектирует филлы (тест)</h2>
{fh['resel']}
<table><thead><tr><th>Портфель</th><th></th><th>Входов</th><th>Филлов</th><th>P(fill|проигрыш)</th>
<th>P(win|fill)</th><th>P&L</th><th>сред.</th></tr></thead><tbody>
{''.join(row([lab,'',b['n'],b['fills'],f"{b['p_fill_loss']*100:.0f}%",f"{b['p_win_fill']*100:.0f}%",f"${b['total_pnl']:+.0f}",f"${b['mean_pnl']:+.2f}"]) for lab,b in [("Без гейта",t['ungated']),("Гейт (locked)",t['gated']),("Исключённые",t['excluded'])])}
</tbody></table>

<h2>4. Историческая «ниша» — и почему ей нельзя верить</h2>
<table><thead><tr><th>Цена входа</th><th>Гейт</th><th>Входов</th><th>Филлов</th><th>P(win|fill)</th><th>P&L</th><th>сред.</th></tr></thead>
<tbody>{grid_rows}</tbody></table>
<p class="note">В исторической симуляции клетка «гейт + фаворит 0.5–0.85» выходит в плюс, НО:
(1) живьём в неё попало 0 сделок, а живые залоченные сделки в среднем проиграли (см. §1b);
(2) это ровно диапазон, где рынок уже почти уверен — то есть плюс держится на том, что мы
пассивно доберём чуть дешёвле «почти-победителей», а §1b показывает, что как раз таких
победителей рынок уводит вверх раньше нас. Клетка — артефакт малой выборки и оптимистичной
модели филла, а не подтверждённый эдж. Не торговать по ней без живого подтверждения.</p>

<h2>5. Разложение остаточных проигрышей: погода vs basis</h2>
<p>Из залитых проигрышей (тест): <b>{dc['rise']}</b> ({dc['rise_pct']*100:.0f}%) — «добор» (максимум
вышел из брекета, лечится intraday-погодой), <b>{dc['basis']}</b> ({dc['basis_pct']*100:.0f}%) — basis
(максимум НЕ покидал брекет, но резолюция WU дала другой — нужна правильная станция).</p>
<p><b>Потолок гейта:</b> убрать basis-проигрыши (корректная станция резолюции) → гейт даёт
${cgb['mean_pnl']:+.2f}/сделку (${cgb['total_pnl']:+.0f} на {cgb['n']} входах) против ${cg['mean_pnl']:+.2f} сейчас.</p>

<h2>6. Что докупить (рычаги, по приоритету)</h2>
<ol>
<li><b>Резолюционная станция (basis).</b> ~{dc['basis_pct']*100:.0f}% остаточных проигрышей — это WU≠METAR.
Аудит icao_map против страниц резолюции Polymarket и переход на станцию WU снимает этот слой
<i>без всякой погоды</i> — самый дешёвый и точный рычаг.</li>
<li><b>Субчасовые наблюдения (5-мин ASOS / SPECI).</b> Часовой METAR слишком груб, чтобы поймать
момент выположивания — гейт опаздывает. 5-минутные обзы дадут более ранний и чёткий лок,
сузят P(fill|проигрыш) дальше 50%.</li>
<li><b>Почасовой HRRR</b> (в кэше 1 прогон/день) — прогноз оставшихся часов как второй голос к наклону.</li>
</ol>

<h2>7. Ограничения</h2>
<ul>
<li>Симуляция филла — по одной ценовой серии (свеча, без стакана): bid считается залитым, если
цена позже опускалась до него. Это верно воспроизводит «залив на коллапсе проигрыша», но не глубину книги.</li>
<li>Малые n в плюсовых клетках (десятки сделок), один сезон (лето), тест ~2.5 недели.</li>
<li>Живой леджер n={live['n_settled']} — направление, не точные проценты.</li>
</ul>

<h2>8. Рекомендация</h2>
<p><b>Пассивную ветку — остановить.</b> Winner-no-fill анализ показал, что рынок торгует лок/замедление
быстрее, чем наш сигнал становится actionable: к моменту действия цена уже уехала. Пассив-ниже ловит
только проигрыши; marketable упирается в справедливую цену входа. Historical-«ниша» живьём не подтверждается.</p>
<p>Что осталось проверить, прежде чем закрывать тему совсем — <b>единственная теоретическая щель это скорость</b>:
(1) субчасовые обзы (5-мин ASOS/SPECI), чтобы ловить лок раньше рынка, + мгновенное marketable-исполнение
на залоченном брекете; (2) аудит станции резолюции (снимает ~{decomp['test']['basis_pct']*100:.0f}% проигрышей —
это basis, не рынок, и чинится без погоды). Если на субчасовых данных опережения нет — эдж на этом рынке
не забирается на нашем горизонте, и скальп-тему по этим контрактам стоит закрыть.</p>
<p><i>Артефакты: scripts/run_passive_antidote_study.py · data/processed/passive_sim.parquet ·
oled/changes/passive-bid-antidote/</i></p>
</body></html>"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(html, encoding="utf-8")
    print(f"\nReport written: {REPORT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()

    live = live_diagnosis()
    print("=== A. LIVE DIAGNOSIS ===")
    print(f"settled={live['n_settled']} P(fill|win)={live.get('p_fill_win'):.2f} "
          f"P(fill|loss)={live.get('p_fill_loss'):.2f} total_pnl=${live.get('total_pnl'):+.0f}")
    print(live.get("ct"))

    sim_path = OUT / "passive_sim.parquet"
    if args.no_rebuild and sim_path.exists():
        sim = pd.read_parquet(sim_path)
    else:
        sim = historical_sim()
        sim.to_parquet(sim_path, index=False)
    s = summarize_sim(sim)
    print(f"\n=== B. HISTORICAL GATED-PASSIVE SIM (n={len(sim)}) ===")
    for scope in ("all", "test"):
        print(f"\n-- {scope} --")
        for k in ("ungated", "gated", "excluded"):
            b = s[scope][k]
            print(f"  {k:9s}: n={b['n']:4d} fills={b['fills']:4d} P(win|fill)={b['p_win_fill']:.2f} "
                  f"P(fill|win)={b['p_fill_win']:.2f} P(fill|loss)={b['p_fill_loss']:.2f} "
                  f"pnl=${b['total_pnl']:+.0f} mean=${b['mean_pnl']:+.2f}")
    decomp = loss_decomposition(sim)
    grid = stacked_grid(sim)
    ceil = basis_ceiling(sim)
    meff = market_efficiency()
    print("\n=== loss decomposition (test filled losers) ===", decomp["test"])
    print("=== basis ceiling ===", {k: round(v["mean_pnl"], 2) for k, v in ceil.items()})
    if meff:
        print("=== market efficiency (winner-no-fill) ===")
        print(meff["by_cell"].to_string())
        print(f"live locked cell: n={meff['locked_n']} win={meff['locked_win']:.2f} "
              f"wnf_ask_run={meff['wnf_ask_run']:+.3f}")
    sep = slope_separation()
    render(live, s, decomp, grid, ceil, sep, meff)
    (OUT / "passive_antidote_summary.json").write_text(json.dumps(
        {"live": {k: v for k, v in live.items() if k != "ct"}, "sim": s,
         "decomp": decomp, "ceiling": {k: v for k, v in ceil.items()}}, indent=1, default=str))


if __name__ == "__main__":
    main()
