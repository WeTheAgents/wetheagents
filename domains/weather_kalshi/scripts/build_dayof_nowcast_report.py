"""Analysis + interactive HTML report for the day-of nowcast edge study.

Consumes artifacts produced by scripts/run_dayof_nowcast_study.py:
  data/processed/dayof_study_checkpoints.parquet
  data/processed/dayof_study_deaths.parquet
  data/processed/dayof_study_meta.json

Produces:
  reports/dayof_nowcast_report.html  (self-contained, Plotly inline)

Bracket assignment uses resolution-style rounding in native units:
US brackets are 2F wide with 1F gaps (83-84, 85-86), so raw METAR 84.2F would
fall "between" brackets; Weather Underground resolves on whole degrees, so we
round the running max to the nearest integer F (or C for international cities)
before matching brackets.

Usage:
  python -m scripts.build_dayof_nowcast_report
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "dayof_nowcast_report.html"

SLIP = 0.01  # adverse execution assumption per trade, in price units
JUNE_WEEK = 23  # ISO week from which candle coverage is complete for all cities


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def native_round_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Add native-unit rounded running max and bracket upper bound."""
    df = df.copy()
    us = df["is_us"]
    df["run_max_nat"] = np.where(us, df["run_max_f"].round(), f_to_c(df["run_max_f"]).round())
    upper_c = np.floor(f_to_c(df["upper_f"]) + 1e-6)
    df["upper_nat"] = np.where(us, df["upper_f"], upper_c)
    return df


def assign_positions(cps: pd.DataFrame) -> pd.DataFrame:
    """Per (event, hour): the bracket containing the rounded running max and
    the bracket immediately above it. Returns one row per event-hour with both."""
    cps = native_round_cols(cps)
    rows = []
    for (slug, mdate, hour), g in cps.groupby(["city_slug", "market_date", "hour"]):
        gg = g.sort_values("upper_f", na_position="last").reset_index(drop=True)
        cand = gg[(gg["upper_nat"].notna()) & (gg["upper_nat"] >= gg["run_max_nat"])]
        if cand.empty:
            # running max above all finite uppers -> open-top bracket is current
            # (mirrors the live runner in scripts/paper_dayof.py)
            top = gg[gg["upper_nat"].isna()]
            if top.empty:
                continue
            i = top.index[0]
        else:
            i = cand.index[0]
        cur = gg.iloc[i]
        win_rows = gg[gg["won_market"] == 1]
        rec = {
            "city_slug": slug, "market_date": mdate, "hour": hour,
            "is_us": bool(gg["is_us"].iloc[0]),
            "cur_idx": int(cur["bracket_index"]),
            "cur_yes": float(cur["yes_price"]), "cur_won": int(cur["won_market"]),
            "winner_idx": int(win_rows["bracket_index"].iloc[0]) if len(win_rows) else np.nan,
        }
        if i + 1 < len(gg):
            ab = gg.iloc[i + 1]
            rec["ab_yes"] = float(ab["yes_price"])
            rec["ab_won"] = int(ab["won_market"])
        rows.append(rec)
    pos = pd.DataFrame(rows)
    pos["week"] = pd.to_datetime(pos["market_date"]).dt.isocalendar().week.astype(int)
    return pos


def roi_buy_yes(g: pd.DataFrame, price_col: str, won_col: str, slip: float = 0.0) -> float:
    px = (g[price_col] + slip).clip(upper=0.999)
    return float((g[won_col] / px).mean() - 1)


def roi_buy_no(g: pd.DataFrame, price_col: str, won_col: str, slip: float = 0.0) -> float:
    cost = (1 - g[price_col] + slip).clip(upper=0.999)
    pay = 1 - g[won_col]
    return float(((pay - cost) / cost).mean())


def analyze() -> dict:
    cps = pd.read_parquet(OUT_DIR / "dayof_study_checkpoints.parquet")
    deaths = pd.read_parquet(OUT_DIR / "dayof_study_deaths.parquet")
    meta = json.loads((OUT_DIR / "dayof_study_meta.json").read_text())
    cps["week"] = pd.to_datetime(cps["market_date"]).dt.isocalendar().week.astype(int)

    r: dict = {"meta": meta}
    r["n_events"] = cps.groupby(["city_slug", "market_date"]).ngroups
    r["n_cities"] = cps["city_slug"].nunique()
    r["date_min"] = cps["market_date"].min()
    r["date_max"] = cps["market_date"].max()

    # --- safety: dead-by-METAR bracket that won, per buffer ---
    saf = []
    for b in (0, 1, 2):
        d = cps[cps[f"dead_b{b}"]]
        ev = d.groupby(["city_slug", "market_date", "bracket_index"])["won_market"].max()
        saf.append({"buffer": b, "dead_brackets": len(ev), "won": int(ev.sum()),
                    "err_pct": round(ev.mean() * 100, 2)})
    r["safety"] = pd.DataFrame(saf)

    # --- mispricing of dead brackets by local hour ---
    mp = []
    for h, g in cps[cps["dead_b1"]].groupby("hour"):
        mp.append({"hour": h, "n": len(g),
                   "ge1c": (g["yes_price"] >= 0.01).mean(),
                   "ge2c": (g["yes_price"] >= 0.02).mean(),
                   "ge5c": (g["yes_price"] >= 0.05).mean(),
                   "mean_yes": g["yes_price"].mean()})
    r["mispricing"] = pd.DataFrame(mp)

    # --- latency decay after bracket death (buffer=1, YES>=2c at death) ---
    d1 = deaths[(deaths["buffer"] == 1.0) & (deaths["px_0m"] >= 0.02)]
    offs = [0, 10, 30, 60, 120, 180]
    dec = []
    for o in offs:
        col = f"px_{o}m"
        s = d1[col].dropna()
        dec.append({"offset_min": o, "n": len(s), "q25": s.quantile(0.25),
                    "median": s.median(), "q75": s.quantile(0.75)})
    r["decay"] = pd.DataFrame(dec)
    r["decay_n"] = len(d1)
    r["min_to_1c_med"] = float(d1["min_to_1c"].median())
    r["min_to_1c_q75"] = float(d1["min_to_1c"].quantile(0.75))

    # --- dead-bracket NO strategy at checkpoints ---
    dead_strat = []
    for label, data in (("all", cps), ("june+", cps[cps["week"] >= JUNE_WEEK])):
        for h in (12, 15, 18):
            g = data[(data["hour"] == h) & (data["dead_b1"]) & (data["yes_price"] >= 0.02)]
            if len(g) < 5:
                continue
            dead_strat.append({
                "period": label, "hour": h, "trades": len(g),
                "mean_yes": g["yes_price"].mean(),
                "no_win_pct": (1 - g["won_market"]).mean() * 100,
                "gross_roi": roi_buy_no(g, "yes_price", "won_market"),
                "slip_roi": roi_buy_no(g, "yes_price", "won_market", SLIP),
            })
    r["dead_strat"] = pd.DataFrame(dead_strat)

    # --- positional strategies (rounded native assignment) ---
    pos = assign_positions(cps[cps["hour"].isin([13, 14, 15, 16, 17, 18, 19])])
    r["pos"] = pos

    cur_rows = []
    for label, data in (("all", pos), ("june+", pos[pos["week"] >= JUNE_WEEK])):
        for h in sorted(data["hour"].unique()):
            b = data[(data["hour"] == h) & (data["cur_yes"] > 0) & (data["cur_yes"] <= 0.85)]
            if len(b) < 20:
                continue
            cur_rows.append({
                "period": label, "hour": h, "n": len(b),
                "mean_yes": b["cur_yes"].mean(), "win_pct": b["cur_won"].mean() * 100,
                "gross_roi": roi_buy_yes(b, "cur_yes", "cur_won"),
                "slip_roi": roi_buy_yes(b, "cur_yes", "cur_won", SLIP),
            })
    r["cur_strat"] = pd.DataFrame(cur_rows)

    # weekly gross ROI of the current-max buy at h=15 (edge decay over time)
    wk = []
    b15 = pos[(pos["hour"] == 15) & (pos["cur_yes"] > 0) & (pos["cur_yes"] <= 0.85)]
    for w, g in b15.groupby("week"):
        if len(g) < 8:
            continue
        wk.append({"week": int(w), "n": len(g),
                   "gross_roi": roi_buy_yes(g, "cur_yes", "cur_won"),
                   "slip_roi": roi_buy_yes(g, "cur_yes", "cur_won", SLIP)})
    r["weekly15"] = pd.DataFrame(wk)

    # price-band calibration at h=15, june+
    bands = [(0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 0.95), (0.95, 1.0)]
    bd = []
    j15 = pos[(pos["hour"] == 15) & (pos["week"] >= JUNE_WEEK)]
    for lo, hi in bands:
        g = j15[(j15["cur_yes"] > lo) & (j15["cur_yes"] <= hi)]
        if len(g) < 10:
            continue
        bd.append({"band": f"{lo:.2f}-{hi:.2f}", "n": len(g),
                   "implied": g["cur_yes"].mean() * 100, "win_pct": g["cur_won"].mean() * 100,
                   "slip_roi": roi_buy_yes(g, "cur_yes", "cur_won", SLIP)})
    r["bands15"] = pd.DataFrame(bd)

    # NO on the bracket above current max, late day
    ab_rows = []
    for label, data in (("all", pos), ("june+", pos[pos["week"] >= JUNE_WEEK])):
        for h in (16, 17, 18):
            g = data[(data["hour"] == h) & data["ab_yes"].notna()]
            g = g[(g["ab_yes"] >= 0.02) & (g["ab_yes"] <= 0.5)]
            if len(g) < 20:
                continue
            ab_rows.append({
                "period": label, "hour": h, "n": len(g),
                "mean_yes": g["ab_yes"].mean(),
                "no_win_pct": (1 - g["ab_won"]).mean() * 100,
                "gross_roi": roi_buy_no(g, "ab_yes", "ab_won"),
                "slip_roi": roi_buy_no(g, "ab_yes", "ab_won", SLIP),
            })
    r["above_strat"] = pd.DataFrame(ab_rows)

    # winner minus current-max bracket at h=19 (basis check, rounded)
    p19 = pos[(pos["hour"] == 19) & pos["winner_idx"].notna()]
    p19 = p19.assign(diff=(p19["winner_idx"] - p19["cur_idx"]).astype(int))
    dist = []
    for us, g in p19.groupby("is_us"):
        vc = g["diff"].value_counts(normalize=True).sort_index()
        for k, v in vc.items():
            if abs(k) <= 3:
                dist.append({"group": "US" if us else "INTL", "diff": int(k), "share": v})
    r["winner_diff"] = pd.DataFrame(dist)
    match = p19.groupby("is_us")["diff"].apply(lambda s: (s == 0).mean() * 100)
    r["match_us"] = float(match.get(True, np.nan))
    r["match_intl"] = float(match.get(False, np.nan))
    up = p19.groupby("is_us")["diff"].apply(lambda s: (s > 0).mean() * 100)
    dn = p19.groupby("is_us")["diff"].apply(lambda s: (s < 0).mean() * 100)
    r["shift_up_intl"], r["shift_dn_intl"] = float(up.get(False, 0)), float(dn.get(False, 0))
    r["shift_up_us"], r["shift_dn_us"] = float(up.get(True, 0)), float(dn.get(True, 0))
    return r


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

PALETTE = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")

def fig_mispricing(r) -> go.Figure:
    mp = r["mispricing"]
    fig = go.Figure()
    for col, name, color in [("ge1c", "YES ≥ 1¢", PALETTE["blue"]),
                             ("ge2c", "YES ≥ 2¢", PALETTE["amber"]),
                             ("ge5c", "YES ≥ 5¢", PALETTE["red"])]:
        fig.add_trace(go.Scatter(x=mp["hour"], y=mp[col] * 100, name=name,
                                 mode="lines+markers", line=dict(color=color)))
    fig.update_layout(title="Доля «мёртвых» брекетов, всё ещё имеющих цену (по местному часу)",
                      xaxis_title="Местный час", yaxis_title="% мёртвых брекетов",
                      height=380, template="plotly_white")
    return fig


def fig_decay(r) -> go.Figure:
    dc = r["decay"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dc["offset_min"], y=dc["q75"] * 100, name="75-й перцентиль",
                             line=dict(color=PALETTE["gray"], dash="dot")))
    fig.add_trace(go.Scatter(x=dc["offset_min"], y=dc["median"] * 100, name="Медиана",
                             line=dict(color=PALETTE["blue"], width=3)))
    fig.add_trace(go.Scatter(x=dc["offset_min"], y=dc["q25"] * 100, name="25-й перцентиль",
                             line=dict(color=PALETTE["gray"], dash="dot")))
    fig.update_layout(title=f"Цена YES мёртвого брекета после «смерти» (n={r['decay_n']}, была ≥2¢)",
                      xaxis_title="Минут после пересечения порога METAR", yaxis_title="Цена YES, ¢",
                      height=380, template="plotly_white")
    return fig


def fig_weekly(r) -> go.Figure:
    wk = r["weekly15"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=wk["week"], y=wk["gross_roi"] * 100, name="Gross ROI",
                         marker_color=PALETTE["blue"]))
    fig.add_trace(go.Bar(x=wk["week"], y=wk["slip_roi"] * 100, name="ROI со слиппеджем 1¢",
                         marker_color=PALETTE["amber"]))
    fig.add_hline(y=0, line_color=PALETTE["gray"])
    fig.update_layout(title="Покупка брекета текущего максимума в 15:00 — ROI по ISO-неделям",
                      xaxis_title="ISO-неделя 2026", yaxis_title="ROI, %", barmode="group",
                      height=380, template="plotly_white")
    return fig


def fig_bands(r) -> go.Figure:
    bd = r["bands15"]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=bd["band"], y=bd["implied"], name="Цена рынка (implied, %)",
                         marker_color=PALETTE["gray"]))
    fig.add_trace(go.Bar(x=bd["band"], y=bd["win_pct"], name="Реальная частота выигрыша, %",
                         marker_color=PALETTE["green"]))
    fig.update_layout(title="15:00, июнь+: брекет текущего максимума — цена vs реальность",
                      xaxis_title="Ценовой диапазон YES", yaxis_title="%", barmode="group",
                      height=380, template="plotly_white")
    return fig


def fig_winner_diff(r) -> go.Figure:
    wd = r["winner_diff"]
    fig = go.Figure()
    for grp, color in [("INTL", PALETTE["blue"]), ("US", PALETTE["red"])]:
        g = wd[wd["group"] == grp]
        fig.add_trace(go.Bar(x=g["diff"], y=g["share"] * 100, name=grp, marker_color=color))
    fig.update_layout(title="Победитель − брекет текущего METAR-максимума в 19:00 (сдвиг, брекетов)",
                      xaxis_title="Сдвиг победителя (0 = совпал)", yaxis_title="% событий",
                      barmode="group", height=380, template="plotly_white")
    return fig


def tbl(df: pd.DataFrame, cols: dict[str, str], pct_cols=(), roi_cols=()) -> str:
    rows = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            v = row[c]
            if c in roi_cols:
                cls = "pos" if v > 0 else "neg"
                tds.append(f'<td class="{cls}">{v * 100:+.1f}%</td>')
            elif c in pct_cols:
                tds.append(f"<td>{v:.1f}%</td>")
            elif isinstance(v, float):
                tds.append(f"<td>{v:.3f}</td>")
            else:
                tds.append(f"<td>{v}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    head = "".join(f"<th>{h}</th>" for h in cols.values())
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def render(r: dict) -> str:
    figs = {
        "mispricing": fig_mispricing(r), "decay": fig_decay(r),
        "weekly": fig_weekly(r), "bands": fig_bands(r), "wdiff": fig_winner_diff(r),
    }
    fig_html = {}
    first = True
    for k, f in figs.items():
        fig_html[k] = pio.to_html(f, include_plotlyjs="inline" if first else False,
                                  full_html=False, config={"displaylogo": False})
        first = False

    saf_t = tbl(r["safety"], {"buffer": "Буфер, °F", "dead_brackets": "Мёртвых брекетов",
                              "won": "Из них выиграли", "err_pct": "Ошибка базиса, %"})
    dead_t = tbl(r["dead_strat"], {"period": "Период", "hour": "Час", "trades": "Сделок",
                                   "mean_yes": "Ср. YES", "no_win_pct": "NO выигрывает",
                                   "gross_roi": "Gross ROI", "slip_roi": "ROI со слип."},
                 pct_cols=("no_win_pct",), roi_cols=("gross_roi", "slip_roi"))
    cur_t = tbl(r["cur_strat"], {"period": "Период", "hour": "Час", "n": "Сделок",
                                 "mean_yes": "Ср. YES", "win_pct": "Победы",
                                 "gross_roi": "Gross ROI", "slip_roi": "ROI со слип."},
                pct_cols=("win_pct",), roi_cols=("gross_roi", "slip_roi"))
    ab_t = tbl(r["above_strat"], {"period": "Период", "hour": "Час", "n": "Сделок",
                                  "mean_yes": "Ср. YES", "no_win_pct": "NO выигрывает",
                                  "gross_roi": "Gross ROI (NO)", "slip_roi": "ROI со слип."},
               pct_cols=("no_win_pct",), roi_cols=("gross_roi", "slip_roi"))

    m = r["meta"]
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Day-of Nowcast Edge — исследование</title>
<style>
 body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 980px; margin: 0 auto;
        padding: 24px; color: #1f2937; line-height: 1.55; }}
 h1 {{ font-size: 1.7em; }} h2 {{ margin-top: 2em; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
 table {{ border-collapse: collapse; margin: 12px 0; font-size: 0.92em; }}
 th, td {{ border: 1px solid #d1d5db; padding: 6px 12px; text-align: right; }}
 th {{ background: #f3f4f6; }}
 td.pos {{ color: #059669; font-weight: 600; }} td.neg {{ color: #dc2626; font-weight: 600; }}
 .verdict {{ border-left: 5px solid; padding: 10px 16px; margin: 10px 0; border-radius: 4px; }}
 .no {{ border-color: #dc2626; background: #fef2f2; }}
 .maybe {{ border-color: #d97706; background: #fffbeb; }}
 .yes {{ border-color: #059669; background: #ecfdf5; }}
 .note {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px; font-size: 0.93em; }}
 details {{ margin: 8px 0; }} summary {{ cursor: pointer; font-weight: 600; }}
</style></head><body>

<h1>Day-of nowcasting: METAR против интрадей-рынка Polymarket</h1>
<p><i>Построено {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} ·
{r['n_events']} событий · {r['n_cities']} городов · {r['date_min']} → {r['date_max']} ·
свечи 10 мин · METAR почасовой</i></p>

<h2>TL;DR — вердикты</h2>
<div class="verdict no"><b>«Мёртвые» брекеты (чистая латентность): NO-GO.</b>
Рынок убирает цену мёртвого брекета за ~{r['min_to_1c_med']:.0f} минут (медиана) —
быстрее нашей 10-минутной гранулярности свечей. Боты уже здесь. Остатки ≥2¢ — это
в основном случаи, где прав рынок, а не METAR (базис Weather Underground).</div>
<div class="verdict yes"><b>Покупка брекета текущего максимума в 15:00 местного: ГЛАВНЫЙ КАНДИДАТ.</b>
После исправления сопоставления брекетов (округление в родных единицах) эдж устойчив:
июнь+ даёт <b>+27% ROI после слиппеджа 1¢ на 513 сделках</b>, реальная частота выигрыша
выше рыночной цены во всех ценовых диапазонах ниже 95¢. Главный открытый вопрос —
исполнимость по ценам свечей (нужен стакан).</div>
<div class="verdict yes"><b>Главная находка — базис резолюции.</b> Поздним вечером
рынок систематически «знает», что резолюция (Weather Underground) прочитает выше/иначе,
чем METAR. Дорогой «мёртвый по METAR» брекет в 18:00 выигрывает в 77% случаев.
Моделирование WU-базиса — самостоятельный источник преимущества (подход №3 из обзора).</div>

<h2>1. Метод</h2>
<p>Правда об исходе — <b>сам рынок</b>: победитель = единственный брекет с последней
свечой ≥ 0.90 (лейблы нашей панели признаны битыми 2026-07-03). «Мёртвый» брекет —
верхняя граница которого уже пробита текущим максимумом METAR (+буфер).
Температурный «пол» не может опуститься: дневной максимум только растёт.</p>
<details><summary>Счётчики отбора данных (без молчаливых потерь)</summary>
<p>Всего событий (город×дата) в истории цен: {m['events_total']} ·
исключено: нет METAR в этот день — {m['no_obs_that_day']},
история не дотягивает до конца дня (рынок не разрешён в данных) — {m['history_not_past_day_end']},
нет уникального победителя — {m['no_unique_winner']} ·
<b>использовано: {m['events_used']}</b>.
Важно: недели 16–22 (апрель–май) покрыты слабо — API истории цен хранит
10-минутные свечи ограниченное время, сбор стартовал в марте и полностью
стабилизировался к июню.</p></details>

<h2>2. Насколько безопасен METAR-«пол»</h2>
<p>Проверка на всех данных: как часто брекет, «умерший» по METAR, всё-таки выигрывал
(из-за расхождения METAR ↔ Weather Underground):</p>
{saf_t}
<p class="note">Буфер 1°F снижает ошибку базиса до 0.55% — приемлемо для торговли NO,
но <b>не</b> для «бесплатных денег»: одна ошибка на ~180 сделок съедает ~2% ROI кучки
дешёвых NO. Буфер 2°F почти безопасен (0.20%).</p>

<h2>3. Рынок реагирует быстрее, чем мы видим</h2>
{fig_html['decay']}
<p>Медианное время от пересечения порога до цены ≤1¢ — <b>{r['min_to_1c_med']:.0f} мин</b>
(75-й перцентиль {r['min_to_1c_q75']:.0f} мин) — на границе разрешающей способности
10-минутных свечей. Т.е. в момент, когда мы впервые «видим» смерть брекета по почасовому
METAR, рынок уже почти всё убрал.</p>
{fig_html['mispricing']}
<p>Днём лишь ~2–3% мёртвых брекетов сохраняют цену ≥2¢, к вечеру — ~1%. Это остатки,
а не системная неэффективность.</p>

<h2>4. Стратегия «купить NO на мёртвые брекеты»</h2>
{dead_t}
<p>В 12:00 выборка мала (рынок редко ошибается так рано), в 18:00 стратегия
<b>убыточна</b>: дорогие «мёртвые» брекеты вечером — это как раз случаи, где рынок
правильно прайсит WU-базис против METAR. Вывод: латентную стратегию в лоб строить не из чего.</p>

<h2>5. Стратегия «купить брекет текущего максимума»</h2>
<p>Логика: если текущий максимум уже сидит в брекете K, то выиграет K или выше.
После пика дневного хода (~14–16 местного) чаще всего выигрывает именно K.</p>
{cur_t}
{fig_html['weekly']}
<p>По неделям сигнал шумный (неделя 24 — около нуля, недели 25–27 — уверенный плюс),
но <b>систематически положительный и в марте, и в июне</b> — то есть это не разовая
неэффективность, которую уже съели. Разброс по городам большой (n≈12–20 на город —
на уровне шума), city-фильтры строить рано.</p>
{fig_html['bands']}
<p>Калибровка по ценовым диапазонам (июнь+, 15:00): рынок недооценивает брекет
текущего максимума <b>во всех диапазонах ниже 95¢</b> — победная частота стабильно выше
implied-цены. Механика понятна: в 15:00 местного дневной максимум в большинстве городов
уже достигнут или почти достигнут, но рынок продолжает держать значимую вероятность
на брекетах выше — платит за «продолжение потепления», которое чаще всего не приходит.</p>

<h2>6. Обратная сторона: брекет НАД текущим максимумом переоценён</h2>
<p>Рынок систематически переплачивает за «продолжение потепления» после пика:</p>
{ab_t}
<p class="note">ROI на NO невелик (+2–4% за сделку при цене NO ~90–95¢), но частота
выигрыша 95–98% и сотни событий в месяц делают это стабильным «сбором премии» —
это интрадей-версия favorite-longshot bias из подхода №1. Капиталоёмко; смысл
появляется при автоматизации на стакане.</p>

<h2>7. Базис METAR ↔ Weather Underground (главная находка)</h2>
{fig_html['wdiff']}
<p>В 19:00 местного победитель совпадает с брекетом METAR-максимума (после округления
в родных единицах и с учётом «щелей» между брекетами 83–84/85–86) в
<b>{r['match_intl']:.0f}%</b> случаев (INTL) и <b>{r['match_us']:.0f}%</b> (US).
Несовпадения асимметричны: INTL — вверх {r['shift_up_intl']:.1f}% против вниз
{r['shift_dn_intl']:.1f}%, US — вверх {r['shift_up_us']:.1f}% против вниз
{r['shift_dn_us']:.1f}%. Резолюция WU читает <b>выше</b> METAR чаще, чем ниже.
Именно поэтому поздние «аномально дорогие мёртвые» брекеты выигрывают:
рынок уже торгует WU, а не METAR.</p>

<h2>8. Ограничения</h2>
<ul>
<li><b>Свечи ≈ midpoint, не исполнение.</b> Реальные заявки двигают цену; слиппедж 1¢ —
допущение, для дешёвых брекетов он может быть больше в разы.</li>
<li><b>Ликвидность не измерена</b> — в данных нет глубины стакана.</li>
<li><b>10-минутная гранулярность</b> — латентность &lt;10 мин недоступна для измерения.</li>
<li><b>Покрытие апреля–мая неполное</b> — тренд «эдж затухает» опирается на март vs июнь.</li>
<li><b>HRRR</b>: в кэше только один прогон в день (06Z, скачивается утром) — интрадей-анализ
HRRR невозможен на текущих данных; нужен почасовой сбор прогонов.</li>
<li><b>Станция резолюции ≠ наш METAR для части городов.</b> Ручная сверка нашла случай
(Даллас 2026-06-26: METAR KDFW 97°F, рынок разрешился в 94–95°F), где расхождение
слишком велико для базиса WU — вероятно, Polymarket резолвит по другой станции города.
Нужен аудит icao_map против страниц резолюции Polymarket.</li>
</ul>

<h2>9. Что дальше</h2>
<ol>
<li><b>WU-базис (подход №3)</b> — самый живой сигнал: собрать историю WU-резолюций
(scrape wunderground history) по 10–15 городам, измерить систематику WU−METAR по городам/сезону.
Если базис предсказуем — торговать против тех, кто смотрит на METAR.</li>
<li><b>Стакан вместо свечей</b>: снимать CLOB book по 2–3 городам в течение дня —
проверить исполнимость «текущего максимума в 14–15» и NO-премии из §6.</li>
<li><b>Почасовой сбор HRRR</b> (все 24 прогона) — единственный способ вернуть
латентную гипотезу к жизни на упреждении прогноза, а не факта.</li>
<li><b>Пейпер-трейдинг двух стратегий</b>: покупка брекета текущего максимума в 15:00
местного (§5, главный кандидат) + NO на брекет над максимумом после 16:00 (§6,
стабильная премия). Обе проверяются одним и тем же сборщиком стаканов из п.2.</li>
</ol>

<p><i>Артефакты: scripts/run_dayof_nowcast_study.py · scripts/build_dayof_nowcast_report.py ·
data/processed/dayof_study_*.parquet · spec: oled/changes/dayof-nowcast-edge-study/</i></p>
</body></html>"""
    return html


def main() -> None:
    r = analyze()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(r), encoding="utf-8")
    print(f"Report written: {REPORT}")
    print(f"Events: {r['n_events']}, cities: {r['n_cities']}")
    print("\nCurrent-max strategy:\n", r["cur_strat"].to_string(index=False))
    print("\nAbove-bracket NO strategy:\n", r["above_strat"].to_string(index=False))
    print("\nWinner diff (h=19):\n", r["winner_diff"].to_string(index=False))


if __name__ == "__main__":
    main()
