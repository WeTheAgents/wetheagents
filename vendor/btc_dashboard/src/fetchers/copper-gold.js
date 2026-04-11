'use strict';

const { fetchYahooDaily, nowIso, pctChange, formatPct, toSparkline } = require('./_util');

const SOURCE = 'Yahoo (HG=F / GC=F)';

async function fetchCopperGold() {
  const [copper, gold] = await Promise.all([
    fetchYahooDaily('HG=F', { range: '3mo' }),
    fetchYahooDaily('GC=F', { range: '3mo' })
  ]);

  if (!copper.length || !gold.length) throw new Error('Yahoo: empty copper or gold series');

  // Align by date — build ratio where both present.
  const goldByDate = new Map(gold.map((p) => [p.date, p.value]));
  const ratio = [];
  for (const p of copper) {
    const g = goldByDate.get(p.date);
    if (g == null || g === 0) continue;
    ratio.push({ date: p.date, value: p.value / g });
  }

  if (ratio.length < 25) throw new Error('copper/gold: not enough aligned points');

  const latest = ratio[ratio.length - 1].value;
  const ago30 = ratio[ratio.length - 22] || ratio[0]; // ~22 trading days ≈ 30 calendar
  const change = pctChange(ago30.value, latest);

  let signal;
  if (change != null && change > 1) signal = 'bullish';
  else if (change != null && change < -1) signal = 'bearish';
  else signal = 'neutral';

  const displayValue = `${latest.toFixed(4)}`;

  const contextMap = {
    bullish: `Copper/Gold ${latest.toFixed(4)}, ${formatPct(change)} за 30д. Медь обгоняет золото → risk-on, промышленный спрос растёт.`,
    bearish: `Copper/Gold ${latest.toFixed(4)}, ${formatPct(change)} за 30д. Золото обгоняет медь → risk-off, замедление.`,
    neutral: `Copper/Gold ${latest.toFixed(4)}, ${formatPct(change)} за 30д. Без чёткого сдвига циклического аппетита.`
  };

  return {
    value: latest,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(ratio, 30),
    source: SOURCE,
    source_updated: ratio[ratio.length - 1].date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchCopperGold, SOURCE };
