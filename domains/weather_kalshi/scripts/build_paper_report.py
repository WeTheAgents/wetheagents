"""HTML report for the day-of paper-trading pipeline.

Reads:
  data/paper/book_sweeps.parquet   (ad-hoc executability sweeps)
  data/paper/paper_trades.jsonl    (paper ledger, books embedded)
  data/paper/paper_runs.jsonl      (run traces)

Writes:
  reports/paper_trading_report.html  (self-contained, Plotly inline, Russian prose)

Rerun any time: python -m scripts.build_paper_report
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "data" / "paper"
REPORT = ROOT / "reports" / "paper_trading_report.html"

DECISION_HOURS = (13.0, 18.0)  # local hours relevant to strategy windows
PALETTE = dict(blue="#2563eb", red="#dc2626", green="#059669", gray="#6b7280", amber="#d97706")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load() -> dict:
    d = {}
    d["sweeps"] = (pd.read_parquet(PAPER_DIR / "book_sweeps.parquet")
                   if (PAPER_DIR / "book_sweeps.parquet").exists() else pd.DataFrame())
    d["trades"] = read_jsonl(PAPER_DIR / "paper_trades.jsonl")
    d["runs"] = read_jsonl(PAPER_DIR / "paper_runs.jsonl")
    return d


def fig_spread(s: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for role, color in [("curmax", PALETTE["blue"]), ("above", PALETTE["amber"]),
                        ("favorite", PALETTE["green"])]:
        g = s[s["role"] == role]["spread"].dropna() * 100
        fig.add_trace(go.Box(y=g, name=role, marker_color=color, boxmean=True))
    fig.update_layout(title="Спред bid-ask по ролям брекетов (все города, ¢)",
                      yaxis_title="Спред, ¢", height=380, template="plotly_white")
    return fig


def fig_slippage(s: pd.DataFrame) -> go.Figure:
    cm = s[s["role"] == "curmax"]
    ab = s[s["role"] == "above"]
    yes_slip = ((cm["yes100_avg"] - cm["mid"]) * 100).dropna()
    no_slip = ((ab["no100_avg"] - (1 - ab["mid"])) * 100).dropna()
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=yes_slip, name="Стратегия A: YES $100 на curmax",
                               marker_color=PALETTE["blue"], opacity=0.7, nbinsx=30))
    fig.add_trace(go.Histogram(x=no_slip, name="Стратегия B: NO $100 на above",
                               marker_color=PALETTE["amber"], opacity=0.7, nbinsx=30))
    fig.add_vline(x=1.0, line_color=PALETTE["red"], line_dash="dash",
                  annotation_text="1¢ — допущение бэктеста")
    fig.update_layout(title="Слиппедж симулированного филла $100 против mid-цены",
                      xaxis_title="Слиппедж, ¢", yaxis_title="Число стаканов",
                      barmode="overlay", height=380, template="plotly_white")
    return fig


def fig_pnl(settled: pd.DataFrame) -> go.Figure | None:
    if settled.empty:
        return None
    settled = settled.sort_values("ts_utc")
    settled["cum_pnl"] = settled["pnl"].cumsum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=settled["ts_utc"], y=settled["cum_pnl"],
                             mode="lines+markers", line=dict(color=PALETTE["green"])))
    fig.add_hline(y=0, line_color=PALETTE["gray"])
    fig.update_layout(title="Накопленный paper P&L, $ (ставка $100 на сделку)",
                      xaxis_title="Дата", yaxis_title="$", height=380, template="plotly_white")
    return fig


def html_table(rows: list[list], header: list[str]) -> str:
    th = "".join(f"<th>{h}</th>" for h in header)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def render(d: dict) -> str:
    s = d["sweeps"]
    trades = d["trades"]
    runs = d["runs"]

    # decision-hour subset
    sd = s[(s["local_hour"] >= DECISION_HOURS[0]) & (s["local_hour"] <= DECISION_HOURS[1])] if not s.empty else s

    figs = {}
    if not s.empty:
        figs["spread"] = fig_spread(s)
        figs["slip"] = fig_slippage(s)
    tdf = pd.DataFrame([{k: v for k, v in t.items() if k != "book"} for t in trades]) if trades else pd.DataFrame()
    settled = pd.DataFrame()
    if not tdf.empty and "settled" in tdf.columns:
        st = tdf[tdf["settled"].notna()]
        if not st.empty:
            settled = pd.DataFrame([{**r, "pnl": r["settled"]["pnl"]} for r in st.to_dict("records")])
    pnl_fig = fig_pnl(settled)
    if pnl_fig is not None:
        figs["pnl"] = pnl_fig

    fig_html, first = {}, True
    for k, f in figs.items():
        fig_html[k] = pio.to_html(f, include_plotlyjs="inline" if first else False,
                                  full_html=False, config={"displaylogo": False})
        first = False

    # executability summary numbers
    def q(series, p):
        series = series.dropna()
        return f"{series.quantile(p) * 100:.1f}" if len(series) else "—"

    exec_rows = []
    for label, sub in [("Все города/часы", s), (f"Часы решения {DECISION_HOURS[0]:.0f}–{DECISION_HOURS[1]:.0f} лок.", sd)]:
        if sub.empty:
            continue
        cm, ab = sub[sub["role"] == "curmax"], sub[sub["role"] == "above"]
        exec_rows.append([
            label, len(cm),
            q(cm["spread"], 0.5), q((cm["yes100_avg"] - cm["mid"]), 0.5),
            f"{cm['yes100_complete'].mean() * 100:.0f}%" if len(cm) else "—",
            q(ab["no100_avg"] - (1 - ab["mid"]), 0.5),
            f"{ab['no100_complete'].mean() * 100:.0f}%" if len(ab) else "—",
        ])
    exec_t = html_table(exec_rows, ["Срез", "N стаканов", "Медианный спред curmax, ¢",
                                    "Слиппедж YES $100 (A), ¢", "Заполняемость A",
                                    "Слиппедж NO $100 (B), ¢", "Заполняемость B"])

    # ledger table
    ledger_rows = []
    for t in trades[-50:]:
        rm = t.get("run_max") or {}
        fill = f"{t.get('fill_avg_price'):.3f}" if t.get("fill_avg_price") is not None else "—"
        settled_s = f"{t['settled']['pnl']:+.0f}$" if t.get("settled") else t["status"]
        ledger_rows.append([
            t["ts_utc"][:16], t["strategy"], t["city_slug"], t["market_date"],
            t.get("question", "—")[:60] if t.get("question") else "—",
            rm.get("rounded_native", "—"),
            f"{t.get('best_bid'):.3f}" if t.get("best_bid") is not None else "—",
            f"{t.get('best_ask'):.3f}" if t.get("best_ask") is not None else "—",
            fill, t.get("skip_reason") or "", settled_s,
        ])
    ledger_t = html_table(ledger_rows, ["UTC", "Стратегия", "Город", "Дата рынка", "Брекет",
                                        "Max", "Bid", "Ask", "Fill", "Причина скипа", "Статус"])

    # run health
    trade_runs = [r for r in runs if r["mode"] == "trade"]
    run_rows = [[r["ts_utc"][:16], len(r.get("considered", [])), r.get("traded", 0),
                 "; ".join(r.get("errors", []))[:80]] for r in trade_runs[-20:]]
    runs_t = html_table(run_rows, ["UTC", "Городов в окне", "Сделок", "Ошибки"])

    n_settled = len(settled)
    total_pnl = settled["pnl"].sum() if n_settled else 0.0
    pnl_block = (fig_html.get("pnl", "") if n_settled else
                 '<p class="note">Расчётов пока нет — первые сделки рассчитываются на следующий '
                 'день после локального конца дня (+3 ч). Раздел заполнится автоматически, '
                 'перезапусти отчёт: <code>python -m scripts.build_paper_report</code>.</p>')

    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Paper Trading — day-of стратегии</title>
<style>
 body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 1080px; margin: 0 auto;
        padding: 24px; color: #1f2937; line-height: 1.55; }}
 h1 {{ font-size: 1.6em; }} h2 {{ margin-top: 2em; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
 table {{ border-collapse: collapse; margin: 12px 0; font-size: 0.85em; }}
 th, td {{ border: 1px solid #d1d5db; padding: 5px 9px; text-align: right; }}
 th {{ background: #f3f4f6; }} td:nth-child(-n+5) {{ text-align: left; }}
 .note {{ background: #eff6ff; border-radius: 6px; padding: 10px 16px; font-size: 0.93em; }}
 .warn {{ background: #fffbeb; border-left: 4px solid #d97706; padding: 10px 16px; margin: 10px 0; }}
 code {{ background: #f3f4f6; padding: 1px 5px; border-radius: 3px; }}
</style></head><body>

<h1>Paper trading: day-of стратегии на Polymarket</h1>
<p><i>Отчёт собран {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} ·
сделок в леджере: {len(trades)} · рассчитано: {n_settled} · P&L: {total_pnl:+.0f}$ ·
sweep-стаканов: {len(s)}</i></p>

<h2>1. Что это</h2>
<p>Автоматический пейпер-трейдинг двух стратегий из исследования
<i>day-of nowcasting</i> (2026-07-03), <b>без реальных денег</b> — только чтение рынка
и симуляция филлов по реальному стакану CLOB:</p>
<ul>
<li><b>Стратегия A (скальп v2)</b> — купить YES на $100 в брекете текущего максимума
METAR (пропуск, если ask &gt; 85¢). Час входа пер-городской: на чистых днях —
скользящий медианный час установления максимума h*₅₀ (12–17, пересчёт из METAR
каждые ≤30 дней, окно 60 дней), на «флагованных» днях (предиктор ненормального дня:
база города / прогнозный прогрев / персистентность×энтропия) — 17:00.
Бэктест OOS: чистые +65%, флагованные@17 +47–71%.</li>
<li><b>Стратегия B</b> — в 16:30–16:45 местного купить NO на $100 на брекет НАД текущим
максимумом (если YES bid в диапазоне 2–50¢). Бэктест: +4–6% за сделку.</li>
</ul>
<p>Windows-задача <code>dayof-paper-trade</code> запускает раннер каждые 15 минут:
он находит города, у которых местное время в окне, тянет живой METAR (AWC),
определяет целевой брекет, снимает стакан и записывает симулированную сделку в
<code>data/paper/paper_trades.jsonl</code> (со встроенным снапшотом стакана).
Расчёт — на следующий день по резолюции рынка.
Остановить: <code>schtasks /delete /tn dayof-paper-trade /f</code>.</p>

<h2>2. Исполнимость: что показывают реальные стаканы</h2>
<p>Ключевой вопрос к бэктесту: реалистично ли допущение «слиппедж 1¢»?</p>
{exec_t}
{fig_html.get('slip', '')}
<div class="warn"><b>Первый честный ответ: для стратегии A допущение 1¢ оптимистично.</b>
Медианный слиппедж симулированного филла $100 против mid — несколько центов, у трети
стаканов хуже. Часть sweep-замеров сделана ночью по местному времени (тонкие книги) —
решающими будут стаканы, записанные самими сделками в окнах 15:00/16:30. Для стратегии B
(NO по цене ~90–95¢) слиппедж в центах мал, там допущение выглядит реалистичным.</div>
{fig_html.get('spread', '')}

<h2>3. Леджер сделок</h2>
{ledger_t if ledger_rows else '<p class="note">Сделок пока нет.</p>'}
<p class="note">«Скип» — тоже результат: например, <code>ask_above_0.85</code> означает,
что рынок уже сам оценил брекет текущего максимума выше 85¢ — по правилам стратегии
входа нет. Так мы измеряем и частоту реальных возможностей.</p>

<h2>4. P&amp;L</h2>
{pnl_block}

<h2>5. Здоровье прогонов</h2>
{runs_t if run_rows else '<p class="note">Прогонов пока нет.</p>'}

<h2>6. Критерий go / no-go</h2>
<p>Через 2–3 недели накопления: стратегия остаётся в плюсе по <b>реальным филлам</b>
(не mid!), заполняемость $100 ≥ 80%, и ошибок базиса не больше, чем в бэктесте
(0.55%). Тогда — минимальный реальный размер. Иначе — закрываем ветку, данные
остаются для исследований.</p>

<p><i>Артефакты: scripts/paper_dayof.py · scripts/build_paper_report.py ·
src/clob_book.py · data/paper/ · spec: oled/changes/dayof-paper-trading/</i></p>
</body></html>"""
    return html


def main() -> None:
    d = load()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(d), encoding="utf-8")
    print(f"Report written: {REPORT}")


if __name__ == "__main__":
    main()
