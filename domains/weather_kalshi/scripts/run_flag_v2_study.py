"""Flag v2: abnormal-day predictor trained on deep LOCAL data (no API calls).

Correction to the earlier "May is unrecoverable" finding: market RESOLUTIONS for
April-May are indeed absent locally, but everything needed to TRAIN the day-ahead
flag exists locally for the whole period:
  - labels rise15            : METAR only (hourly archive since Mar 9)
  - mkt_entropy/upside/modal : candles cover D-1 20:00 local for ~100% of events
                               in ALL weeks (sparse May candles are concentrated
                               in early market life - exactly what day-ahead needs)
  - forecast warming/spread  : data/raw/snapshots/*.parquet - daily ensemble
                               forecasts (days_ahead 0-6) since Mar 25

This lets us tune flag thresholds honestly on train (Mar 25 - Jun 15) and keep
the June+ market test untouched.

Outputs:
  data/processed/flag_v2_train_panel.parquet
  reports/flag_v2_report.html

Usage: python -m scripts.run_flag_v2_study [--no-rebuild]
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_dayof_nowcast_report import assign_positions  # noqa: E402
from scripts.run_abnormal_day_study import market_evening_features  # noqa: E402
from scripts.run_dayof_nowcast_study import load_city_meta  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
PANEL_PATH = OUT / "flag_v2_train_panel.parquet"
REPORT = ROOT / "reports" / "flag_v2_report.html"

TRAIN_START, TRAIN_CUTOFF = "2026-03-25", "2026-06-15"
SLIP = 0.01


def load_snapshot_forecasts() -> pd.DataFrame:
    """Day-ahead ensemble forecast per (city, target_date): the days_ahead=1 row
    from the previous day's snapshot."""
    want = ["slug", "target_date", "days_ahead", "ens_mean", "ens_spread"]
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "raw" / "snapshots" / "*.parquet"))):
        s = pd.read_parquet(f)
        if not set(want).issubset(s.columns):
            continue
        s = s.loc[s["days_ahead"] == 1, want]
        rows.append(s)
    fc = pd.concat(rows, ignore_index=True)
    fc["target_date"] = fc["target_date"].astype(str).str[:10]
    fc = fc.drop_duplicates(subset=["slug", "target_date"], keep="last")
    return fc.rename(columns={"slug": "city_slug", "ens_mean": "fc_mean_nat",
                              "ens_spread": "fc_spread"})


def build_panel() -> pd.DataFrame:
    days = pd.read_parquet(OUT / "metar_day_table.parquet")  # from city timing study
    days["date"] = pd.to_datetime(days["local_date"])
    days = days.sort_values(["city_slug", "date"]).reset_index(drop=True)

    # persistence lag (consecutive calendar days only)
    days["lag1"] = days.groupby("city_slug")["rise15"].shift(1)
    lagd = days.groupby("city_slug")["date"].shift(1)
    days.loc[(days["date"] - lagd).dt.days != 1, "lag1"] = np.nan

    # previous-day realized max (native, METAR)
    days["prev_max_nat"] = days.groupby("city_slug")["day_max_nat"].shift(1)
    days.loc[(days["date"] - lagd).dt.days != 1, "prev_max_nat"] = np.nan

    # day-ahead ensemble forecast (local snapshots)
    fc = load_snapshot_forecasts()
    days = days.merge(fc, left_on=["city_slug", "local_date"],
                      right_on=["city_slug", "target_date"], how="left")
    days["fc_warm"] = days["fc_mean_nat"] - days["prev_max_nat"]

    # market evening features (candles at D-1 20:00 local) - works for May too
    meta = load_city_meta()
    ev = market_evening_features(days, meta)
    days = days.merge(ev.rename(columns={"market_date": "local_date"}),
                      on=["city_slug", "local_date"], how="left")

    days.to_parquet(PANEL_PATH, index=False)
    print(f"panel: {len(days)} city-days, fc coverage="
          f"{days['fc_warm'].notna().mean():.2%}, "
          f"evening-mkt coverage={days['mkt_entropy'].notna().mean():.2%}")
    return days


def tune_flag(train: pd.DataFrame) -> dict:
    """Small grid over transparent OR-rule thresholds, objective on TRAIN only:
    maximize separation subject to reasonable flag rate."""
    # city rate from the first part of train to avoid self-reference
    early = train[train["date"] <= "2026-05-15"]
    rate = early.groupby("city_slug")["rise15"].agg(["mean", "size"])
    rate = rate[rate["size"] >= 15]["mean"]
    train = train.copy()
    train["city_rate"] = train["city_slug"].map(rate)
    late = train[train["date"] > "2026-05-15"]  # tuning slice, disjoint from rate fit

    best = None
    ent_q75 = train["mkt_entropy"].quantile(0.75)
    ent_med = train["mkt_entropy"].median()
    for cr_cut in (0.4, 0.5, 0.6):
        for warm_cut in (1.0, 2.0, 3.0):
            for ent_cut, ent_name in ((ent_med, "median"), (ent_q75, "q75"), (None, "none")):
                def mkflag(df):
                    f = (df["city_rate"] >= cr_cut) | (df["fc_warm"] >= warm_cut)
                    if ent_cut is None:
                        f = f | (df["lag1"] == 1)
                    else:
                        f = f | ((df["lag1"] == 1) & (df["mkt_entropy"] >= ent_cut))
                    return f.fillna(False)
                fl = mkflag(late)
                frate = fl.mean()
                if not 0.25 <= frate <= 0.55:
                    continue
                sep = late[fl]["rise15"].mean() - late[~fl]["rise15"].mean()
                cand = {"cr_cut": cr_cut, "warm_cut": warm_cut, "ent": ent_name,
                        "ent_cut": ent_cut, "flag_rate": frate, "sep": sep,
                        "rate_map": rate}
                if best is None or cand["sep"] > best["sep"]:
                    best = cand
    return best


def evaluate(days: pd.DataFrame) -> dict:
    r: dict = {}
    days = days.copy()
    days["date"] = pd.to_datetime(days["local_date"])
    train = days[(days["date"] >= TRAIN_START) & (days["date"] <= TRAIN_CUTOFF)]
    r["n_train"] = len(train)

    best = tune_flag(train)
    r["best"] = {k: v for k, v in best.items() if k != "rate_map"}
    rate = best["rate_map"]

    # refit city_rate on FULL train for the test-time flag
    rate_full = train.groupby("city_slug")["rise15"].agg(["mean", "size"])
    rate_full = rate_full[rate_full["size"] >= 20]["mean"]

    def mkflag(df, rmap):
        f = (df["city_slug"].map(rmap) >= best["cr_cut"]) | (df["fc_warm"] >= best["warm_cut"])
        if best["ent_cut"] is None:
            f = f | (df["lag1"] == 1)
        else:
            f = f | ((df["lag1"] == 1) & (df["mkt_entropy"] >= best["ent_cut"]))
        return f.fillna(False)

    # market test (> cutoff): labels + prices from the market checkpoint dataset
    lab = pd.read_parquet(OUT / "abnormal_features.parquet")
    lab["date"] = pd.to_datetime(lab["market_date"])
    feat = days[["city_slug", "local_date", "lag1", "fc_warm", "mkt_entropy"]]
    lab2 = lab.merge(feat, left_on=["city_slug", "market_date"],
                     right_on=["city_slug", "local_date"], how="left",
                     suffixes=("", "_v2"))
    lab2["mkt_entropy"] = lab2["mkt_entropy_v2"].fillna(lab2["mkt_entropy"])
    lab2["flag_v2"] = mkflag(lab2, rate_full)
    test = lab2[lab2["date"] > TRAIN_CUTOFF].copy()
    r["test_n"] = len(test)
    r["flag_rate_test"] = float(test["flag_v2"].mean())
    r["p_rise_fl"] = float(test[test["flag_v2"]]["rise"].mean())
    r["p_rise_cl"] = float(test[~test["flag_v2"]]["rise"].mean())

    def roi_yes(g, pc, wc):
        if len(g) == 0:
            return np.nan
        px = (g[pc] + SLIP).clip(upper=0.999)
        return float((g[wc] / px).mean() - 1)

    fl, cl = test[test["flag_v2"]], test[~test["flag_v2"]]
    a_cl = cl[(cl["cur_yes"] > 0) & (cl["cur_yes"] <= 0.85)]
    a_fl = fl[(fl["cur_yes"] > 0) & (fl["cur_yes"] <= 0.85)]
    l2b = fl.dropna(subset=["cur_yes17"])
    l2b = l2b[(l2b["cur_yes17"] > 0) & (l2b["cur_yes17"] <= 0.85)]
    r["A_kept"] = {"n": len(a_cl), "roi": roi_yes(a_cl, "cur_yes", "cur_won")}
    r["A_skip"] = {"n": len(a_fl), "roi": roi_yes(a_fl, "cur_yes", "cur_won")}
    r["L2b"] = {"n": len(l2b), "win": float(l2b["cur_won17"].mean()) if len(l2b) else np.nan,
                "roi": roi_yes(l2b, "cur_yes17", "cur_won17")}

    # feature availability/quality on the deep train
    r["fc_lift"] = train.dropna(subset=["fc_warm"]).assign(
        b=lambda d: pd.cut(d["fc_warm"], [-30, -1, 0, 1, 2, 30])).groupby(
        "b", observed=True)["rise15"].agg(["size", "mean"])
    r["train"] = train
    return r


def render(r: dict) -> None:
    import plotly.graph_objects as go
    import plotly.io as pio
    C = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")

    t = r["fc_lift"].reset_index()
    f1 = go.Figure(go.Bar(x=t["b"].astype(str), y=t["mean"] * 100,
                          text=t["size"], marker_color=C["blue"]))
    f1.update_layout(title="P(поздний день) по прогнозному прогреву (ансамбль D−1, train апр–июнь)",
                     xaxis_title="fc_warm: прогноз(D) − факт(D−1), °нативные",
                     yaxis_title="%", height=380, template="plotly_white")
    fh = pio.to_html(f1, include_plotlyjs="inline", full_html=False,
                     config={"displaylogo": False})
    b = r["best"]
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Флаг v2 — обучение на глубоких локальных данных</title>
<style>
 body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 960px; margin: 0 auto;
        padding: 24px; color: #1f2937; line-height: 1.55; }}
 h1 {{ font-size: 1.5em; }} h2 {{ margin-top: 1.8em; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
 table {{ border-collapse: collapse; margin: 12px 0; font-size: 0.92em; }}
 th, td {{ border: 1px solid #d1d5db; padding: 6px 12px; text-align: right; }}
 th {{ background: #f3f4f6; }} td:first-child {{ text-align: left; }}
 td.pos {{ color: #059669; font-weight: 600; }} td.neg {{ color: #dc2626; font-weight: 600; }}
 .verdict {{ border-left: 5px solid #059669; background: #ecfdf5; padding: 10px 16px;
            margin: 10px 0; border-radius: 4px; }}
 .note {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px; font-size: 0.93em; }}
</style></head><body>

<h1>Флаг v2: обучение углублено до конца марта — только локальные данные</h1>
<p><i>Train: {TRAIN_START} → {TRAIN_CUTOFF} ({r['n_train']} city-days) ·
тест: рынок &gt; {TRAIN_CUTOFF} (n={r['test_n']}) · слиппедж 1¢ · без единого API-вызова</i></p>

<div class="verdict"><b>Поправка к прежнему выводу «май невосстановим».</b>
Резолюции рынка за май действительно нигде не сохранены (свечи обрываются до
резолюции — это подтвердилось). Но всё, что нужно для <i>обучения</i> флага,
локально есть за весь период: METAR-лейблы (с 9 марта), вечерние D−1 цены брекетов
(свечи покрывают вечер накануне в ~100% событий всех недель — редкие майские свечи
сконцентрированы именно в ранней жизни рынка), и — находка — ежедневные
<b>ансамблевые прогнозы «на завтра»</b> в data/raw/snapshots/ с 25 марта
(139 членов мультимодели). Прежний рыночный суррогат «прогрева» заменён настоящим
прогнозным.</div>

<h2>1. Новая фича: прогнозный прогрев</h2>
{fh}
<p>Прогноз ансамбля на завтра минус сегодняшний факт — монотонный предиктор:
от ~20% (похолодание) до ~45–50% (прогрев ≥ +2°).</p>

<h2>2. Тюнинг порогов — теперь честный</h2>
<p>Раньше пороги выбирались «на глаз» без train-валидации. Теперь сетка порогов
оценена на train-срезе {TRAIN_START}–{TRAIN_CUTOFF} (city_rate — по ранней части,
тюнинг — по поздней, тест не тронут). Выбрано: city_rate ≥ {b['cr_cut']},
прогнозный прогрев ≥ {b['warm_cut']:.0f}°, персистентность
{'с фильтром энтропии (' + b['ent'] + ')' if b['ent'] != 'none' else 'без фильтра'}.
Train-сепарация: {b['sep']*100:.0f} п.п. при доле флага {b['flag_rate']*100:.0f}%.</p>

<h2>3. Out-of-sample результат (рынок &gt; {TRAIN_CUTOFF})</h2>
<table><thead><tr><th>Метрика</th><th>Флаг v1 (прежний)</th><th><b>Флаг v2</b></th></tr></thead>
<tbody>
<tr><td>P(rise | флаг) / P(rise | чисто)</td><td>51% / 24%</td>
<td><b>{r['p_rise_fl']*100:.0f}% / {r['p_rise_cl']*100:.0f}%</b></td></tr>
<tr><td>Доля флагованных</td><td>44%</td><td>{r['flag_rate_test']*100:.0f}%</td></tr>
<tr><td>A@15 чистые дни: n / ROI</td><td>165 / +66%</td>
<td><b>{r['A_kept']['n']} / {r['A_kept']['roi']*100:+.0f}%</b></td></tr>
<tr><td>A@15 флагованные (отсечено)</td><td>187 / −1%</td>
<td>{r['A_skip']['n']} / {r['A_skip']['roi']*100:+.0f}%</td></tr>
<tr><td>L2b @17:00 флагованные: n / ROI</td><td>112 / +47%</td>
<td><b>{r['L2b']['n']} / {r['L2b']['roi']*100:+.0f}%</b></td></tr>
</tbody></table>

<h2>4. Ограничения</h2>
<ul>
<li>Рыночные P&amp;L-симуляции по-прежнему только на июньском+ тесте — цены решающих
часов за апрель–май не существуют нигде (не только у нас: их не хранит и API).</li>
<li>Снапшоты прогнозов начинаются 25 марта; первые 2 недели марта — без fc-фич.</li>
<li>Тест ~2.5 недели; накопление продолжается автоматически.</li>
</ul>

<p><i>Артефакты: scripts/run_flag_v2_study.py ·
data/processed/flag_v2_train_panel.parquet · spec: oled/changes/city-timing-study/</i></p>
</body></html>"""
    REPORT.write_text(html, encoding="utf-8")
    print(f"Report written: {REPORT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()
    days = (pd.read_parquet(PANEL_PATH) if args.no_rebuild and PANEL_PATH.exists()
            else build_panel())
    r = evaluate(days)
    print(f"\ntrain n={r['n_train']}, best rule: {r['best']}")
    print(f"test n={r['test_n']}, flag rate={r['flag_rate_test']:.2%}")
    print(f"P(rise|flag)={r['p_rise_fl']:.3f} vs P(rise|clean)={r['p_rise_cl']:.3f}")
    print(f"A kept:  {r['A_kept']}")
    print(f"A skip:  {r['A_skip']}")
    print(f"L2b @17: {r['L2b']}")
    print("\nfc_warm lift (train):")
    print(r["fc_lift"].to_string())
    render(r)


if __name__ == "__main__":
    main()
