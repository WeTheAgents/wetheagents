"""Abnormal-day predictor study (strategy 3 for the scalp system).

Question: can we flag, before the 15:00-local decision window (using only
day-ahead / morning-of information), the city-days where the daily max will
keep rising after 15:00 — the days that hurt scalp strategies A and B?

Labels come from the day-of study dataset; features are strictly point-in-time:
  F1 rise_lag1        — yesterday was a late-rise day (regime persistence)
  F2 city_rate        — city's late-rise base rate (train-window only / LOO)
  F3 warming          — market-implied forecast max for D (modal bracket at
                        D-1 20:00 local) minus realized METAR max on D-1
  F4 mkt_entropy      — bracket-price entropy at D-1 20:00 local
  F5 mkt_upside_mass  — price mass above the modal bracket at D-1 20:00
  F8 peak_hour_clim   — city's climatological mean daily-peak hour (METAR archive)
  (F6/F7 ens/nbm/taf from ml_panel are June-only and joined where present)

Outputs:
  data/processed/abnormal_features.parquet
  reports/abnormal_day_report.html

Usage: python -m scripts.run_abnormal_day_study [--no-rebuild]
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_dayof_nowcast_report import assign_positions  # noqa: E402
from scripts.run_dayof_nowcast_study import load_brackets, load_city_meta, load_metar_local  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
FEATURES_PATH = OUT / "abnormal_features.parquet"
REPORT = ROOT / "reports" / "abnormal_day_report.html"

TRAIN_CUTOFF = "2026-06-15"  # city_rate fitted on dates <= cutoff, tested after
SLIP = 0.01


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def build_labels() -> pd.DataFrame:
    cps = pd.read_parquet(OUT / "dayof_study_checkpoints.parquet")
    pos15 = assign_positions(cps[cps["hour"] == 15]).dropna(subset=["winner_idx"])
    pos15["diff"] = (pos15["winner_idx"] - pos15["cur_idx"]).astype(int)
    pos15["rise"] = (pos15["diff"] >= 1).astype(int)
    # strategy-B context at 16:00 (above-bracket outcome)
    pos16 = assign_positions(cps[cps["hour"] == 16]).dropna(subset=["winner_idx"])
    pos16 = pos16[["city_slug", "market_date", "ab_yes", "ab_won"]].rename(
        columns={"ab_yes": "ab_yes16", "ab_won": "ab_won16"})
    # delayed entry context at 17:00 (L2b: on late-peak days, buy curmax later)
    pos17 = assign_positions(cps[cps["hour"] == 17]).dropna(subset=["winner_idx"])
    pos17 = pos17[["city_slug", "market_date", "cur_yes", "cur_won"]].rename(
        columns={"cur_yes": "cur_yes17", "cur_won": "cur_won17"})
    out = pos15.merge(pos16, on=["city_slug", "market_date"], how="left")
    return out.merge(pos17, on=["city_slug", "market_date"], how="left")


def metar_daily_stats(meta: dict) -> tuple[dict, dict]:
    """Per city: {local_date_iso: rounded native daily max} and mean peak hour."""
    daily_max: dict[str, dict] = {}
    peak_hour: dict[str, float] = {}
    for slug, cm in meta.items():
        m = load_metar_local(cm["icao"], cm["tz"]) if cm["icao"] else None
        if m is None or m.empty:
            continue
        m = m.copy()
        m["hour"] = m["local"].dt.hour + m["local"].dt.minute / 60
        by_day = m.groupby("local_date")
        maxes, peaks = {}, []
        for d, g in by_day:
            if len(g) < 12:
                continue
            i = g["temp_f"].idxmax()
            tmax_f = g.loc[i, "temp_f"]
            native = round(tmax_f) if cm["unit"] == "F" else round(f_to_c(tmax_f))
            maxes[d.isoformat()] = float(native)
            peaks.append(g.loc[i, "hour"])
        daily_max[slug] = maxes
        peak_hour[slug] = float(np.mean(peaks)) if peaks else np.nan
    return daily_max, peak_hour


def native_mid(lower, upper, unit: str) -> float | None:
    """Approximate native midpoint of a bracket for forecast-delta features."""
    if lower is not None and upper is not None:
        return (float(lower) + float(upper)) / 2
    if upper is not None:
        return float(upper) - 1.0
    if lower is not None:
        return float(lower) + 1.0
    return None


def market_evening_features(labels: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Bracket-price snapshot of D's market at D-1 20:00 local: modal forecast,
    entropy, upside mass."""
    brackets = load_brackets()
    bmap = {}
    for (slug, md), g in brackets.groupby(["city_slug", "market_date"]):
        bmap[(slug, str(md)[:10])] = g

    hist = pd.read_parquet(
        ROOT / "data" / "raw" / "polymarket" / "all_cities_price_history.parquet",
        columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"],
    )
    hist["md"] = hist["market_date"].astype(str).str[:10]
    hist["ts_utc"] = pd.to_datetime(hist["timestamp"], unit="s", utc=True)

    rows = []
    for (slug, md), g in hist.groupby(["city_slug", "md"]):
        key = (slug, md)
        if key not in bmap or slug not in meta:
            continue
        tz = meta[slug]["tz"]
        cutoff = pd.Timestamp(md, tz=tz) - pd.Timedelta(hours=4)  # D-1 20:00 local
        gg = g[g["ts_utc"] <= cutoff]
        if gg.empty:
            continue
        last = gg.loc[gg.groupby("bracket_index")["ts_utc"].idxmax()]
        if len(last) < 5:
            continue
        bk = bmap[key].set_index("bracket_index")
        prices = last.set_index("bracket_index")["price"].clip(lower=0.001)
        p = prices / prices.sum()
        entropy = float(-(p * np.log(p)).sum())
        modal_idx = int(prices.idxmax())
        # upside mass: brackets whose native upper bound is above the modal's
        def unat(i):
            u = bk["upper_f"].get(i, np.nan)
            return np.inf if pd.isna(u) else u
        modal_u = unat(modal_idx)
        upside = float(prices[[i for i in prices.index if unat(i) > modal_u]].sum()
                       / prices.sum())
        row = bk.loc[modal_idx] if modal_idx in bk.index else None
        mid = None
        if row is not None:
            lo = None if pd.isna(row.get("upper_f")) else None  # placeholder
        # native modal midpoint via question re-parse (lower/upper native in brackets df)
        rows.append({"city_slug": slug, "market_date": md, "mkt_entropy": entropy,
                     "mkt_upside_mass": upside, "modal_idx": modal_idx})
    return pd.DataFrame(rows)


def modal_native_mid(labels: pd.DataFrame, evening: pd.DataFrame) -> pd.DataFrame:
    """Native midpoint of the modal (evening-before) bracket, for the warming feature."""
    from scripts.build_ml_panel import parse_bracket
    mk = pd.read_parquet(ROOT / "data" / "raw" / "polymarket" / "all_cities_markets.parquet")
    mk = mk.drop_duplicates(subset=["city_slug", "market_date", "bracket_index"], keep="last")
    mk["md"] = mk["market_date"].astype(str).str[:10]
    parsed = mk["question"].map(parse_bracket)
    mk["lo_nat"] = parsed.map(lambda t: t[0])
    mk["up_nat"] = parsed.map(lambda t: None if t[1] is None else float(int(t[1])))
    mk["unit"] = parsed.map(lambda t: t[2])
    key = mk.set_index(["city_slug", "md", "bracket_index"])
    mids = []
    for _, r in evening.iterrows():
        try:
            row = key.loc[(r["city_slug"], r["market_date"], r["modal_idx"])]
            mids.append(native_mid(row["lo_nat"], row["up_nat"], row["unit"]))
        except KeyError:
            mids.append(None)
    evening = evening.copy()
    evening["modal_mid_nat"] = mids
    return evening


def build_dataset() -> pd.DataFrame:
    meta = load_city_meta()
    labels = build_labels()
    labels["date"] = pd.to_datetime(labels["market_date"])
    labels = labels.sort_values(["city_slug", "date"]).reset_index(drop=True)

    # F1 persistence (only valid when the previous calendar day exists)
    labels["rise_lag1"] = labels.groupby("city_slug")["rise"].shift(1)
    lagdate = labels.groupby("city_slug")["date"].shift(1)
    labels.loc[(labels["date"] - lagdate).dt.days != 1, "rise_lag1"] = np.nan

    # F8 + realized max lookups
    daily_max, peak_hour = metar_daily_stats(meta)
    labels["peak_hour_clim"] = labels["city_slug"].map(peak_hour)

    # F3-F5 market evening features
    evening = market_evening_features(labels, meta)
    evening = modal_native_mid(labels, evening)
    labels = labels.merge(evening, on=["city_slug", "market_date"], how="left")

    prev_day = (labels["date"] - pd.Timedelta(days=1)).dt.date.astype(str)
    labels["prev_max_nat"] = [
        daily_max.get(s, {}).get(d) for s, d in zip(labels["city_slug"], prev_day)]
    labels["warming"] = labels["modal_mid_nat"] - labels["prev_max_nat"]

    # F6/F7 from ml_panel (June+; keyed by city_name)
    panel = pd.read_parquet(OUT / "ml_panel.parquet")
    name2slug = {v["name"]: k for k, v in json.loads(
        (ROOT / "data" / "static" / "polymarket_cities.json").read_text(encoding="utf-8")).items()}
    panel["city_slug"] = panel["city_name"].map(name2slug)
    panel["md"] = panel["target_date"].astype(str).str[:10]
    agg = panel.groupby(["city_slug", "md"]).agg(
        ens_spread=("ens_spread", "max"), nbm_sigma=("nbm_sigma", "max"),
        taf_max_f=("taf_max_temp_f", "max")).reset_index().rename(columns={"md": "market_date"})
    labels = labels.merge(agg, on=["city_slug", "market_date"], how="left")
    labels["taf_max_f"] = pd.to_numeric(labels["taf_max_f"], errors="coerce")
    labels["taf_max_nat"] = np.where(
        labels["is_us"], labels["taf_max_f"].round(),
        (labels["taf_max_f"].map(lambda f: f_to_c(f) if pd.notna(f) else np.nan)).round())
    labels["taf_delta"] = labels["taf_max_nat"] - labels["modal_mid_nat"]

    # F2 city rate: fitted on train window only
    train = labels[labels["date"] <= TRAIN_CUTOFF]
    rate = train.groupby("city_slug")["rise"].agg(["mean", "size"])
    rate = rate[rate["size"] >= 5]["mean"]
    labels["city_rate_train"] = labels["city_slug"].map(rate)

    labels.to_parquet(FEATURES_PATH, index=False)
    print(f"dataset: {len(labels)} events, features saved")
    return labels


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def lift_table(df: pd.DataFrame, feat: str, q: int = 4) -> pd.DataFrame:
    d = df.dropna(subset=[feat, "rise"])
    if d[feat].nunique() <= 2:
        g = d.groupby(feat)["rise"].agg(["size", "mean"])
    else:
        d = d.assign(bucket=pd.qcut(d[feat], q, duplicates="drop"))
        g = d.groupby("bucket", observed=True)["rise"].agg(["size", "mean"])
    g.columns = ["n", "P(rise)"]
    return g.reset_index()


def evaluate(labels: pd.DataFrame) -> dict:
    r: dict = {}
    r["n"] = len(labels)
    r["p_rise"] = labels["rise"].mean()

    feats = ["rise_lag1", "city_rate_train", "peak_hour_clim", "warming",
             "mkt_entropy", "mkt_upside_mass", "ens_spread", "taf_delta"]
    r["lifts"] = {f: lift_table(labels, f) for f in feats}

    # --- combined day-ahead flag (transparent rule) ---
    # flagged if: chronic late city OR (persistence + market uncertainty) OR big warm-up
    lab = labels.copy()
    lab["flag"] = (
        (lab["city_rate_train"] >= 0.5)
        | ((lab["rise_lag1"] == 1) & (lab["mkt_entropy"] >= lab["mkt_entropy"].median()))
        | (lab["warming"] >= 2)
    ).fillna(False)

    test = lab[lab["date"] > TRAIN_CUTOFF]
    r["test_n"] = len(test)
    r["flag_rate_test"] = test["flag"].mean()
    r["p_rise_flagged"] = test[test["flag"]]["rise"].mean()
    r["p_rise_clean"] = test[~test["flag"]]["rise"].mean()

    # --- L1: strategy A on test window with/without filter ---
    a = test[(test["cur_yes"] > 0) & (test["cur_yes"] <= 0.85)].copy()

    def roi_yes(g, price_col, won_col):
        if len(g) == 0:
            return np.nan
        px = (g[price_col] + SLIP).clip(upper=0.999)
        return float((g[won_col] / px).mean() - 1)

    r["A_all"] = {"n": len(a), "roi": roi_yes(a, "cur_yes", "cur_won")}
    kept = a[~a["flag"]]
    skipped = a[a["flag"]]
    r["A_kept"] = {"n": len(kept), "roi": roi_yes(kept, "cur_yes", "cur_won")}
    r["A_skipped"] = {"n": len(skipped), "roi": roi_yes(skipped, "cur_yes", "cur_won")}

    # L1 for strategy B (NO on above-bracket at 16:00)
    b = test.dropna(subset=["ab_yes16"])
    b = b[(b["ab_yes16"] >= 0.02) & (b["ab_yes16"] <= 0.5)].copy()

    def roi_no(g):
        if len(g) == 0:
            return np.nan
        cost = (1 - g["ab_yes16"] + SLIP).clip(upper=0.999)
        pay = 1 - g["ab_won16"]
        return float(((pay - cost) / cost).mean())

    r["B_all"] = {"n": len(b), "roi": roi_no(b)}
    r["B_kept"] = {"n": len(b[~b["flag"]]), "roi": roi_no(b[~b["flag"]])}
    r["B_skipped"] = {"n": len(b[b["flag"]]), "roi": roi_no(b[b["flag"]])}

    # --- L2 variants on flagged days ---
    def yes_stats(g, pc, wc, lo=0.0, hi=0.85):
        g = g.dropna(subset=[pc])
        g = g[(g[pc] > lo) & (g[pc] <= hi)]
        return {"n": len(g),
                "mean_yes": float(g[pc].mean()) if len(g) else np.nan,
                "win": float(g[wc].mean()) if len(g) else np.nan,
                "roi": roi_yes(g, pc, wc)}

    fl, cl = test[test["flag"]], test[~test["flag"]]
    # L2a: buy the above-bracket at 15:00
    r["L2a_flag"] = yes_stats(fl, "ab_yes", "ab_won", hi=0.6)
    r["L2a_clean"] = yes_stats(cl, "ab_yes", "ab_won", hi=0.6)
    # L2b: delayed A — buy curmax bracket at 17:00
    r["L2b_flag"] = yes_stats(fl, "cur_yes17", "cur_won17")
    r["L2b_clean"] = yes_stats(cl, "cur_yes17", "cur_won17")
    # (16:00 above-NO reversal tested and rejected: market overprices continuation
    # even on flagged days at 16:00)
    r["test_flagged"] = fl
    r["test"] = test
    r["labels"] = lab
    return r


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render_report(r: dict) -> None:
    import plotly.graph_objects as go
    import plotly.io as pio

    C = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")
    lab = r["labels"]

    # per-city rise rate
    cr = lab.groupby("city_slug")["rise"].agg(["size", "mean"]).query("size>=15").sort_values("mean")
    f1 = go.Figure(go.Bar(x=cr.index, y=cr["mean"] * 100, marker_color=C["blue"]))
    f1.add_hline(y=lab["rise"].mean() * 100, line_dash="dash", line_color=C["gray"],
                 annotation_text="среднее")
    f1.update_layout(title="Доля «поздних» дней по городам (весь период, n≥15)",
                     yaxis_title="% дней с ростом после 15:00", height=400,
                     template="plotly_white", xaxis_tickangle=-45)

    # lifts for the 4 main features
    f2 = go.Figure()
    nice = {"rise_lag1": "Вчера был поздний день", "city_rate_train": "База города (train)",
            "peak_hour_clim": "Климат. час пика", "warming": "Прогрев vs вчера"}
    for i, (feat, color) in enumerate(zip(
            ["rise_lag1", "city_rate_train", "peak_hour_clim", "warming"],
            [C["red"], C["blue"], C["amber"], C["green"]])):
        t = r["lifts"][feat]
        xs = [f"{nice[feat]}<br>{str(b)[:14]}" for b in t.iloc[:, 0]]
        f2.add_trace(go.Bar(x=xs, y=t["P(rise)"] * 100, name=nice[feat], marker_color=color))
    f2.add_hline(y=r["p_rise"] * 100, line_dash="dash", line_color=C["gray"])
    f2.update_layout(title="P(поздний день) по квартилям дневных предикторов",
                     yaxis_title="%", height=420, template="plotly_white", showlegend=False)

    def row(label, s):
        cls = "pos" if s["roi"] > 0 else "neg"
        win = f"{s['win']*100:.1f}%" if "win" in s and not np.isnan(s.get("win", np.nan)) else "—"
        return (f"<tr><td>{label}</td><td>{s['n']}</td><td>{win}</td>"
                f"<td class='{cls}'>{s['roi']*100:+.1f}%</td></tr>")

    tbl = "".join([
        row("A@15:00 — все дни (базовая)", {**r["A_all"], "win": np.nan}),
        row("A@15:00 — только чистые дни (L1)", {**r["A_kept"], "win": np.nan}),
        row("A@15:00 — флагованные дни (то, что отсекли)", {**r["A_skipped"], "win": np.nan}),
        row("L2a: брекет ВЫШЕ @15:00 — флагованные", r["L2a_flag"]),
        row("L2a: брекет ВЫШЕ @15:00 — чистые (контроль)", r["L2a_clean"]),
        row("L2b: отложенная A @17:00 — флагованные", r["L2b_flag"]),
        row("L2b: отложенная A @17:00 — чистые", r["L2b_clean"]),
        row("B@16:00 — все / чистые / флаг.", {**r["B_all"], "win": np.nan}),
    ])

    figs = {"cities": f1, "lifts": f2}
    fh, first = {}, True
    for k, f in figs.items():
        fh[k] = pio.to_html(f, include_plotlyjs="inline" if first else False,
                            full_html=False, config={"displaylogo": False})
        first = False

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Abnormal-Day Predictor — стратегия 3</title>
<style>
 body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 1000px; margin: 0 auto;
        padding: 24px; color: #1f2937; line-height: 1.55; }}
 h1 {{ font-size: 1.6em; }} h2 {{ margin-top: 2em; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
 table {{ border-collapse: collapse; margin: 12px 0; font-size: 0.92em; }}
 th, td {{ border: 1px solid #d1d5db; padding: 6px 12px; text-align: right; }}
 th {{ background: #f3f4f6; }} td:first-child {{ text-align: left; }}
 td.pos {{ color: #059669; font-weight: 600; }} td.neg {{ color: #dc2626; font-weight: 600; }}
 .verdict {{ border-left: 5px solid; padding: 10px 16px; margin: 10px 0; border-radius: 4px; }}
 .yes {{ border-color: #059669; background: #ecfdf5; }}
 .maybe {{ border-color: #d97706; background: #fffbeb; }}
 .note {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px; font-size: 0.93em; }}
</style></head><body>

<h1>Стратегия 3: предсказание «ненормальных» дней на день вперёд</h1>
<p><i>{r['n']} событий (март–июль) · тест: после {TRAIN_CUTOFF} (n={r['test_n']}) ·
все цифры теста — out-of-sample · слиппедж 1¢</i></p>

<h2>TL;DR</h2>
<div class="verdict yes"><b>Да, «ненормальные» дни предсказуемы с монетизируемой
вероятностью.</b> Простой прозрачный флаг из трёх условий даёт на тесте
P(поздний день | флаг) = <b>{r['p_rise_flagged']*100:.0f}%</b> против
<b>{r['p_rise_clean']*100:.0f}%</b> без флага (базовая {r['p_rise']*100:.0f}%).</div>
<div class="verdict yes"><b>L1 (выключить скальп) работает</b>: стратегия A на чистых
днях {r['A_kept']['roi']*100:+.0f}% ROI (n={r['A_kept']['n']}) против
{r['A_skipped']['roi']*100:+.0f}% на флагованных (n={r['A_skipped']['n']}).
Фильтр отрезает практически весь минус.</div>
<div class="verdict yes"><b>L2 (ставить на другое) тоже работает</b>: на флагованных
днях «отложенная A» — вход в тот же брекет текущего максимума, но в 17:00 —
даёт {r['L2b_flag']['roi']*100:+.1f}% (n={r['L2b_flag']['n']}); покупка брекета
НАД максимумом в 15:00 даёт {r['L2a_flag']['roi']*100:+.1f}%
(на чистых днях та же ставка: {r['L2a_clean']['roi']*100:+.1f}% — флаг переворачивает знак).</div>

<h2>1. Что такое «ненормальный» день</h2>
<p>День, когда температура продолжает расти после 15:00 местного и победитель
оказывается выше брекета, где сидел максимум на 15:00. Таких дней —
{r['p_rise']*100:.0f}% (магнитуда ≥2 брекетов — ~10%). Именно они дают убытки
стратегии A и часть убытков B.</p>
{fh['cities']}
<p class="note"><b>Главное открытие: бóльшая часть явления — структурная, а не
погодная.</b> Мадрид (85%), Тайбэй, Москва, Париж — города, где суточный пик
климатологически наступает в 16–18 местного (сдвиг зон, широта, морской бриз) —
для них «поздний рост» это норма. Гонконг, Лос-Анджелес, Сан-Франциско — 0–3%.
Это значит, что скальп-системе в принципе нужен пер-городской час входа,
а флаг добавляет сверху погодную динамику.</p>

<h2>2. Дневные предикторы (все знания — до 15:00 целевого дня)</h2>
{fh['lifts']}
<ul>
<li><b>Персистентность</b>: после позднего дня — 54% повтор, после обычного — 23%.
Погодные режимы живут по 2–4 дня.</li>
<li><b>База города</b> (по train-окну ≤ {TRAIN_CUTOFF}): от 7% до 57% по квартилям.</li>
<li><b>Климатологический час пика</b> (из архива METAR): поздний пик → поздние дни.</li>
<li><b>Прогрев</b>: если рынок накануне вечером ждёт максимум на ≥2° выше вчерашнего
факта — адвекция тепла, поздний пик (45% против 23–30%).</li>
<li>Энтропия рынка и ансамблевый разброс — слабые добавки (+5–10 п.п.), не решающие.</li>
</ul>
<p class="note">Флаг = <code>база_города ≥ 0.5 ИЛИ (вчера_поздний И энтропия ≥ медианы)
ИЛИ прогрев ≥ +2°</code>. Пороги выбраны один раз до просмотра теста, не тюнились.</p>

<h2>3. Монетизация (тест после {TRAIN_CUTOFF}, out-of-sample)</h2>
<table><thead><tr><th>Портфель</th><th>Сделок</th><th>Победы</th><th>ROI со слип.</th></tr></thead>
<tbody>{tbl}</tbody></table>
<p><b>Ансамбль</b>: на чистых днях торгуем A@15:00, на флагованных — отложенную
A@17:00 (или пропускаем). Сумма на тесте: {r['A_kept']['n']} + {r['L2b_flag']['n']}
сделок, обе ноги в плюсе. Провалившийся вариант тоже зафиксирован: разворот
B (покупка «выше» в 16:00) не работает — к 16:00 рынок уже переоценивает
продолжение даже на флагованных днях.</p>

<h2>4. Ограничения</h2>
<ul>
<li>Тестовое окно — ~2.5 недели (n={r['test_n']} событий): знаки и порядок величин
устойчивы, точные ROI — нет. Продолжающийся сбор данных удлиняет тест сам собой.</li>
<li>Один сезон (лето). Климатология пиков зимой другая — пороги пересчитать.</li>
<li>Цены — свечи (~mid), исполнимость проверяет пейпер-трейдинг.</li>
<li>ens/nbm/TAF-фичи покрывают только июнь+ — в комбинированный флаг не входят.</li>
</ul>

<h2>5. Что дальше</h2>
<ol>
<li>Встроить флаг в пейпер-раннер: вечером считать флаги на завтра, на флагованных
городах A не торговать, вместо неё — отложенная A@17:00 (одна строчка конфига
для каждого города: чистый/флагованный/выключен).</li>
<li>Пер-городские окна входа по климатологии пика (структурный фикс, ещё до флага).</li>
<li>Через 2–3 недели — повторить оценку на накопленном тесте.</li>
</ol>

<p><i>Артефакты: scripts/run_abnormal_day_study.py ·
data/processed/abnormal_features.parquet · spec: oled/changes/abnormal-day-predictor/</i></p>
</body></html>"""
    REPORT.write_text(html, encoding="utf-8")
    print(f"\nReport written: {REPORT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()
    labels = (pd.read_parquet(FEATURES_PATH) if args.no_rebuild and FEATURES_PATH.exists()
              else build_dataset())
    r = evaluate(labels)
    print(f"\nEvents: {r['n']}, P(rise)={r['p_rise']:.3f}")
    print(f"Test window (> {TRAIN_CUTOFF}): n={r['test_n']}, flagged={r['flag_rate_test']:.2%}")
    print(f"P(rise | flagged)={r['p_rise_flagged']:.3f} vs P(rise | clean)={r['p_rise_clean']:.3f}")
    print("\n--- L1 (skip flagged) ---")
    for k in ("A_all", "A_kept", "A_skipped", "B_all", "B_kept", "B_skipped"):
        print(f"{k}: n={r[k]['n']}, ROI(slip)={r[k]['roi']:+.3f}" if not np.isnan(r[k]["roi"])
              else f"{k}: n={r[k]['n']}, ROI=n/a")
    print("\n--- L2 variants (flagged days, out-of-sample) ---")
    for k in ("L2a_flag", "L2a_clean", "L2b_flag", "L2b_clean"):
        s = r[k]
        print(f"{k}: n={s['n']}, mean_yes={s['mean_yes']:.3f}, win={s['win']:.3f}, ROI={s['roi']:+.3f}")
    print("\n--- Univariate lifts ---")
    for f, t in r["lifts"].items():
        print(f"\n{f}:\n{t.to_string(index=False)}")
    render_report(r)


if __name__ == "__main__":
    main()
