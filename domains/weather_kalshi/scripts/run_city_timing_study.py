"""City timing study: METAR-only training extension + per-city entry hours.

Direction 1: April–May market winners are unrecoverable (CLOB retention + our
candles end pre-resolution), but the rise label is market-free: it needs only
hourly METAR. This gives ~4-5k city-days of training labels (Mar 9 – Jul 2).

Direction 2: per-city optimal entry hour from the settle-hour distribution
(earliest hour whose running max equals the daily max), fitted on METAR train
(<= Jun 15), evaluated OOS on market checkpoint prices (> Jun 15).

Outputs:
  data/processed/metar_day_table.parquet
  reports/city_timing_report.html

Usage: python -m scripts.run_city_timing_study [--no-rebuild]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_dayof_nowcast_report import assign_positions  # noqa: E402
from scripts.run_dayof_nowcast_study import load_city_meta, load_metar_local  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "processed"
DAY_TABLE = OUT / "metar_day_table.parquet"
REPORT = ROOT / "reports" / "city_timing_report.html"

TRAIN_CUTOFF = "2026-06-15"
SETTLE_Q = 0.65          # h* = earliest hour with P(settled by h) >= this
FALLBACK_HOUR = 16
SLIP = 0.01
HOURS = list(range(10, 22))


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


# ---------------------------------------------------------------------------
# R1: METAR-only day table
# ---------------------------------------------------------------------------

def build_day_table() -> pd.DataFrame:
    meta = load_city_meta()
    rows = []
    for slug, cm in meta.items():
        if not cm["icao"]:
            continue
        m = load_metar_local(cm["icao"], cm["tz"])
        if m is None or m.empty:
            continue
        m = m.copy()
        m["hour_f"] = m["local"].dt.hour + m["local"].dt.minute / 60
        for d, g in m.groupby("local_date"):
            if len(g) < 12:
                continue
            g = g.sort_values("local")
            run = g["temp_f"].cummax()
            to_nat = (lambda f: round(f)) if cm["unit"] == "F" else (lambda f: round(f_to_c(f)))
            day_max_nat = to_nat(g["temp_f"].max())
            rec = {"city_slug": slug, "local_date": d.isoformat(), "is_us": cm["unit"] == "F",
                   "day_max_nat": float(day_max_nat), "n_obs": len(g)}
            for h in HOURS:
                upto = run[g["hour_f"] <= h]
                rec[f"rm{h}"] = float(to_nat(upto.iloc[-1])) if len(upto) else np.nan
            # settle hour: earliest checkpoint whose rounded running max == day max
            settle = next((h for h in HOURS if rec.get(f"rm{h}") == day_max_nat), None)
            rec["settle_hour"] = settle
            rec["rise15"] = int(rec.get("rm15") is not None and day_max_nat > rec["rm15"])
            rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_parquet(DAY_TABLE, index=False)
    print(f"METAR day table: {len(df)} city-days, {df['city_slug'].nunique()} cities, "
          f"{df['local_date'].min()} -> {df['local_date'].max()}")
    return df


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(days: pd.DataFrame) -> dict:
    r: dict = {}
    days = days.copy()
    days["date"] = pd.to_datetime(days["local_date"])
    train = days[days["date"] <= TRAIN_CUTOFF]
    r["n_days"] = len(days)
    r["n_train"] = len(train)

    # market labels for validation + portfolios
    lab = pd.read_parquet(OUT / "abnormal_features.parquet")
    lab["date"] = pd.to_datetime(lab["market_date"])

    # R2: agreement between METAR-only rise15 and market rise (June+ overlap)
    mv = lab.merge(days[["city_slug", "local_date", "rise15", "settle_hour"]],
                   left_on=["city_slug", "market_date"], right_on=["city_slug", "local_date"])
    both = mv.dropna(subset=["rise15"])
    r["n_overlap"] = len(both)
    r["agreement"] = float((both["rise"] == both["rise15"]).mean())
    r["confusion"] = pd.crosstab(both["rise"], both["rise15"], normalize="all")

    # R3: refit flag components on METAR train
    rate_m = train.groupby("city_slug")["rise15"].agg(["mean", "size"])
    rate_m = rate_m[rate_m["size"] >= 20]["mean"]
    r["city_rate_metar"] = rate_m

    days = days.sort_values(["city_slug", "date"])
    days["lag1"] = days.groupby("city_slug")["rise15"].shift(1)
    lagd = days.groupby("city_slug")["date"].shift(1)
    days.loc[(days["date"] - lagd).dt.days != 1, "lag1"] = np.nan
    tr = days[days["date"] <= TRAIN_CUTOFF].dropna(subset=["lag1"])
    r["persistence_metar"] = {
        "after_rise": float(tr[tr["lag1"] == 1]["rise15"].mean()),
        "after_calm": float(tr[tr["lag1"] == 0]["rise15"].mean()),
        "n": len(tr)}

    # rebuild flag on market test rows with METAR-based city_rate + METAR lag
    lab2 = lab.merge(days[["city_slug", "local_date", "lag1"]].rename(
        columns={"lag1": "lag1_metar"}), left_on=["city_slug", "market_date"],
        right_on=["city_slug", "local_date"], how="left")
    lab2["city_rate_metar"] = lab2["city_slug"].map(rate_m)
    ent_med = lab2["mkt_entropy"].median()
    lab2["flag_metar"] = ((lab2["city_rate_metar"] >= 0.5)
                          | ((lab2["lag1_metar"] == 1) & (lab2["mkt_entropy"] >= ent_med))
                          | (lab2["warming"] >= 2)).fillna(False)
    lab2["flag_old"] = ((lab2["city_rate_train"] >= 0.5)
                        | ((lab2["rise_lag1"] == 1) & (lab2["mkt_entropy"] >= ent_med))
                        | (lab2["warming"] >= 2)).fillna(False)
    test = lab2[lab2["date"] > TRAIN_CUTOFF].copy()
    r["test_n"] = len(test)

    def roi_yes(g, pc, wc):
        if len(g) == 0:
            return np.nan
        px = (g[pc] + SLIP).clip(upper=0.999)
        return float((g[wc] / px).mean() - 1)

    def flag_stats(col):
        fl, cl = test[test[col]], test[~test[col]]
        a_fl = fl[(fl["cur_yes"] > 0) & (fl["cur_yes"] <= 0.85)]
        a_cl = cl[(cl["cur_yes"] > 0) & (cl["cur_yes"] <= 0.85)]
        l2b = fl.dropna(subset=["cur_yes17"])
        l2b = l2b[(l2b["cur_yes17"] > 0) & (l2b["cur_yes17"] <= 0.85)]
        return {"flag_rate": float(test[col].mean()),
                "p_rise_fl": float(fl["rise"].mean()), "p_rise_cl": float(cl["rise"].mean()),
                "A_kept_n": len(a_cl), "A_kept_roi": roi_yes(a_cl, "cur_yes", "cur_won"),
                "A_skip_n": len(a_fl), "A_skip_roi": roi_yes(a_fl, "cur_yes", "cur_won"),
                "L2b_n": len(l2b), "L2b_roi": roi_yes(l2b, "cur_yes17", "cur_won17")}

    r["flag_old_stats"] = flag_stats("flag_old")
    r["flag_metar_stats"] = flag_stats("flag_metar")

    # ------------------------------------------------------------------
    # R4: per-city entry hour from METAR train settle-hour distribution
    # ------------------------------------------------------------------
    def hstar_for(q: float) -> dict:
        hs = {}
        for slug, g in train.dropna(subset=["settle_hour"]).groupby("city_slug"):
            if len(g) < 15:
                hs[slug] = FALLBACK_HOUR
                continue
            cdf = g["settle_hour"].value_counts(normalize=True).sort_index().cumsum()
            h = next((int(k) for k, p in cdf.items() if p >= q), FALLBACK_HOUR)
            hs[slug] = min(max(h, 12), 19)
        return hs

    hstar50, hstar65 = hstar_for(0.5), hstar_for(0.65)
    r["hstar"] = hstar50  # recommended variant

    cps = pd.read_parquet(OUT / "dayof_study_checkpoints.parquet")
    cps["date"] = pd.to_datetime(cps["market_date"])
    test_cps = cps[cps["date"] > TRAIN_CUTOFF]
    pos_by_hour = {h: assign_positions(test_cps[test_cps["hour"] == h]).dropna(subset=["winner_idx"])
                   for h in range(12, 20)}
    flag_map = dict(zip(zip(test["city_slug"], test["market_date"]), test["flag_metar"]))

    def portfolio(hour_of, day_filter=None):
        rows, seen = [], set()
        for h, pos in pos_by_hour.items():
            for _, p in pos.iterrows():
                key = (p["city_slug"], p["market_date"])
                if hour_of(p["city_slug"]) != h or key in seen:
                    continue
                if day_filter and not day_filter(key):
                    continue
                seen.add(key)
                rows.append(p)
        pf = pd.DataFrame(rows)
        if pf.empty:
            return {"n": 0, "win": np.nan, "mean_yes": np.nan, "roi": np.nan}
        pf = pf[(pf["cur_yes"] > 0) & (pf["cur_yes"] <= 0.85)]
        return {"n": len(pf), "win": float(pf["cur_won"].mean()) if len(pf) else np.nan,
                "mean_yes": float(pf["cur_yes"].mean()) if len(pf) else np.nan,
                "roi": roi_yes(pf, "cur_yes", "cur_won")}

    clean = lambda key: not flag_map.get(key, False)   # noqa: E731
    flagged = lambda key: flag_map.get(key, False)     # noqa: E731

    r["pf_fixed15"] = portfolio(lambda s: 15)
    r["pf_fixed15_clean"] = portfolio(lambda s: 15, clean)
    r["pf_h50"] = portfolio(lambda s: hstar50.get(s, FALLBACK_HOUR))
    r["pf_h50_clean"] = portfolio(lambda s: hstar50.get(s, FALLBACK_HOUR), clean)
    r["pf_h65"] = portfolio(lambda s: hstar65.get(s, FALLBACK_HOUR))
    r["pf_17_flagged"] = portfolio(lambda s: 17, flagged)
    r["train_settle"] = train
    r["days"] = days
    return r


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def render(r: dict) -> None:
    import plotly.graph_objects as go
    import plotly.io as pio
    C = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")

    # settle-hour distribution for a few contrasting cities
    tr = r["train_settle"].dropna(subset=["settle_hour"])
    f1 = go.Figure()
    for slug, color in [("madrid", C["red"]), ("moscow", C["amber"]),
                        ("nyc", C["blue"]), ("hong-kong", C["green"])]:
        g = tr[tr["city_slug"] == slug]["settle_hour"]
        if len(g):
            f1.add_trace(go.Histogram(x=g, name=f"{slug} (n={len(g)})", opacity=0.6,
                                      histnorm="probability", nbinsx=12, marker_color=color))
    f1.update_layout(title="Час установления дневного максимума (train, METAR)",
                     xaxis_title="Местный час", yaxis_title="Доля дней", barmode="overlay",
                     height=380, template="plotly_white")

    hs = pd.Series(r["hstar"]).sort_values()
    f2 = go.Figure(go.Bar(x=hs.index, y=hs.values, marker_color=C["blue"]))
    f2.add_hline(y=15, line_dash="dash", line_color=C["gray"], annotation_text="глобальные 15:00")
    f2.update_layout(title="h*₅₀(город): медианный час установления дневного максимума (train)",
                     yaxis_title="Местный час входа", height=400, template="plotly_white",
                     xaxis_tickangle=-45)

    fo, fm = r["flag_old_stats"], r["flag_metar_stats"]
    p15, p15c = r["pf_fixed15"], r["pf_fixed15_clean"]
    h50, h50c, h65, f17 = r["pf_h50"], r["pf_h50_clean"], r["pf_h65"], r["pf_17_flagged"]

    def prow(label, s, extra=""):
        cls = "pos" if s["roi"] > 0 else "neg"
        return (f"<tr><td>{label}{extra}</td><td>{s['n']}</td>"
                f"<td>{s.get('win', np.nan)*100:.1f}%</td>"
                f"<td>{s.get('mean_yes', np.nan)*100:.0f}¢</td>"
                f"<td class='{cls}'>{s['roi']*100:+.1f}%</td></tr>")

    figs = {"settle": f1, "hstar": f2}
    fh, first = {}, True
    for k, f in figs.items():
        fh[k] = pio.to_html(f, include_plotlyjs="inline" if first else False,
                            full_html=False, config={"displaylogo": False})
        first = False

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>City Timing — тюнинг часа входа и расширение train</title>
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
 .no {{ border-color: #dc2626; background: #fef2f2; }}
 .note {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px; font-size: 0.93em; }}
</style></head><body>

<h1>Тюнинг часа входа по городам + углубление обучающих данных</h1>
<p><i>METAR-таблица: {r['n_days']} city-days ({r['days']['local_date'].min()} →
{r['days']['local_date'].max()}) · train ≤ {TRAIN_CUTOFF} ({r['n_train']} дней) ·
тест — рыночные данные &gt; {TRAIN_CUTOFF} (n={r['test_n']} событий) · слиппедж 1¢</i></p>

<h2>TL;DR</h2>
<div class="verdict no"><b>Май восстановить нельзя.</b> CLOB API уже не отдаёт
апрель–май (ретеншн), а наши свечи тех недель обрываются до резолюции —
победитель неопределим (0–5% событий с полной историей).</div>
<div class="verdict yes"><b>Но train углублён другим путём: лейбл «позднего дня»
не требует рынка.</b> Он вычислим из одного METAR (максимум дня против максимума
к 15:00), а почасовой METAR есть с 9 марта по все 45 станциям →
{r['n_train']} обучающих city-days вместо ~600 рыночных. Согласие METAR-лейбла с
рыночным на пересечении: <b>{r['agreement']*100:.0f}%</b> (n={r['n_overlap']}).</div>
<div class="verdict yes"><b>Пер-городской час стоит тюнить, но мягко — он добавляет
объём, а не эдж на сделку.</b> Медианный час установления максимума (h*₅₀, диапазон
12–17 по городам) на чистых днях даёт {h50c['roi']*100:+.0f}% на {h50c['n']} сделках
против {p15c['roi']*100:+.0f}% на {p15c['n']} у фиксированных 15:00 — тот же ROI,
<b>+{(h50c['n']/max(p15c['n'],1)-1)*100:.0f}% покрытия</b>. Жёсткий поздний вход
(h*₆₅) размывает эдж до {h65['roi']*100:+.0f}%: уверенность покупается по худшей
цене. Лучший ансамбль: <b>A@h*₅₀ на чистых ({h50c['roi']*100:+.0f}%, n={h50c['n']})
+ A@17:00 на флагованных ({f17['roi']*100:+.0f}%, n={f17['n']})</b>.</div>

<h2>1. Направление 1: глубже 15 июня</h2>
<p>Хронология данных: свечи недель 11–13 (март) в основном полные — они уже в
исследовании; недели 14–22 (апрель–май) собраны частично (бэкфилл июня успел
захватить только довиндовые торги, резолюционные свечи истекли из API);
с недели 23 (июнь) сбор ежедневный и полный. Проверено живым запросом:
прайс-история майских токенов сегодня возвращает пусто.</p>
<p>Решение — METAR-only лейблы для обучения структурных компонент
(база города, персистентность): train вырос в ~7 раз. Персистентность на METAR-train:
после позднего дня {r['persistence_metar']['after_rise']*100:.0f}% против
{r['persistence_metar']['after_calm']*100:.0f}% после обычного
(n={r['persistence_metar']['n']}).</p>
<table><thead><tr><th>Флаг (тест &gt; {TRAIN_CUTOFF})</th><th>P(rise|флаг)</th>
<th>P(rise|чисто)</th><th>A чистые: n / ROI</th><th>A флаг.: n / ROI</th>
<th>L2b @17: n / ROI</th></tr></thead><tbody>
<tr><td>Старый (рыночный city_rate)</td><td>{fo['p_rise_fl']*100:.0f}%</td>
<td>{fo['p_rise_cl']*100:.0f}%</td><td>{fo['A_kept_n']} / {fo['A_kept_roi']*100:+.0f}%</td>
<td>{fo['A_skip_n']} / {fo['A_skip_roi']*100:+.0f}%</td>
<td>{fo['L2b_n']} / {fo['L2b_roi']*100:+.0f}%</td></tr>
<tr><td><b>Новый (METAR city_rate + METAR lag)</b></td><td>{fm['p_rise_fl']*100:.0f}%</td>
<td>{fm['p_rise_cl']*100:.0f}%</td><td>{fm['A_kept_n']} / {fm['A_kept_roi']*100:+.0f}%</td>
<td>{fm['A_skip_n']} / {fm['A_skip_roi']*100:+.0f}%</td>
<td>{fm['L2b_n']} / {fm['L2b_roi']*100:+.0f}%</td></tr>
</tbody></table>

<h2>2. Направление 2: пер-городской час входа</h2>
{fh['settle']}
<p>Распределения радикально разные: в Гонконге максимум установлен к 13–14,
в Мадриде — к 17–18. Правило: h*(город) = самый ранний час, к которому максимум
уже установлен в заданной доле train-дней (только METAR, никаких цен) —
проверены квантили 50% и 65%.</p>
{fh['hstar']}
<table><thead><tr><th>Портфель (тест, OOS)</th><th>Сделок</th><th>Победы</th>
<th>Ср. цена</th><th>ROI со слип.</th></tr></thead><tbody>
{prow("A@15:00 все дни (базовая)", p15)}
{prow("A@15:00 только чистые дни", p15c)}
{prow("A@h*₅₀(город) все дни", h50)}
{prow("<b>A@h*₅₀(город) чистые дни</b>", h50c)}
{prow("A@h*₆₅(город) все дни (слишком поздно)", h65)}
{prow("<b>A@17:00 флагованные дни</b> (вторая нога)", f17)}
</tbody></table>
<p class="note"><b>Вывод по таймингу</b>: час входа = компромисс «пик уже установлен»
(выше винрейт) против «рынок ещё не допрайсил» (ниже цена). Медиана установления
(h*₅₀) — оптимум: тот же ROI на сделку, что у 15:00, но на четверть больше
проходящих сделок, потому что «ранние» города (Гонконг 13:00, Токио 14:00) торгуются
до того, как их брекет уходит за 85¢. Позднее (h*₆₅) — уверенность уже в цене.
На флагованных днях тайминг не спасает вход «в момент» — там работает
фиксированное позднее окно 17:00.</p>

<h2>3. Ограничения</h2>
<ul>
<li>Тест всё ещё ~2.5 недели; каждое утро сбора удлиняет его автоматически.</li>
<li>h* фиксирован на лето; сезонный пересчёт обязателен (солнце садится раньше —
пики сдвигаются).</li>
<li>METAR-лейбл несёт базис ±1 брекет против резолюции WU — на структурные
компоненты влияет слабо (согласие {r['agreement']*100:.0f}%).</li>
</ul>

<h2>4. Рекомендуемая конфигурация скальп-системы v2</h2>
<ol>
<li>Чистые дни: вход A по h*₅₀(город) — медианный час установления максимума
(диапазон 12–17, таблица в отчёте; пересчёт из METAR одной командой).</li>
<li>Флагованные дни (METAR-обученный флаг): вход A в 17:00 фиксированно.</li>
<li>B-нога без изменений (16:30), она к флагу нечувствительна.</li>
</ol>

<p><i>Артефакты: scripts/run_city_timing_study.py ·
data/processed/metar_day_table.parquet · spec: oled/changes/city-timing-study/</i></p>
</body></html>"""
    REPORT.write_text(html, encoding="utf-8")
    print(f"Report written: {REPORT}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()
    days = (pd.read_parquet(DAY_TABLE) if args.no_rebuild and DAY_TABLE.exists()
            else build_day_table())
    r = evaluate(days)
    print(f"\nDays: {r['n_days']} (train {r['n_train']}), label agreement={r['agreement']:.3f} (n={r['n_overlap']})")
    print("Confusion (market rise x metar rise15):")
    print(r["confusion"].to_string())
    print(f"\nPersistence METAR train: {r['persistence_metar']}")
    print("\nFlag old :", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r["flag_old_stats"].items()})
    print("Flag METAR:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r["flag_metar_stats"].items()})
    print("\nh*50 per city:", dict(sorted(r["hstar"].items(), key=lambda kv: kv[1])))
    print("\nPortfolios OOS:")
    for k in ("pf_fixed15", "pf_fixed15_clean", "pf_h50", "pf_h50_clean",
              "pf_h65", "pf_17_flagged"):
        print(f"  {k}: {r[k]}")
    render(r)


if __name__ == "__main__":
    main()
