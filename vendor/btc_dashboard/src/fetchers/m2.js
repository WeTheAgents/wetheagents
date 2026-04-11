'use strict';

const { fetchFredSeries, nowIso, pctChange, formatPct, toSparkline } = require('./_util');

const SOURCE = 'FRED (M2SL)';

async function fetchM2() {
  // US M2, monthly. For MVP we use US M2 as a proxy for global M2 trend direction.
  const series = await fetchFredSeries('M2SL', { from: '2020-01-01' });
  if (series.length < 4) throw new Error('FRED M2SL: not enough data');

  const latest = series[series.length - 1];
  const threeMonthsAgo = series[series.length - 4] || series[0];
  const change3m = pctChange(threeMonthsAgo.value, latest.value);

  let signal;
  if (change3m != null && change3m > 1) signal = 'bullish';
  else if (change3m != null && change3m < 0) signal = 'bearish';
  else signal = 'neutral';

  // M2SL is in billions USD; convert to trillions for display.
  const displayValue = `$${(latest.value / 1000).toFixed(1)}T (US)`;

  const contextMap = {
    bullish: `M2 растёт ${formatPct(change3m)} за 3 мес. При лаге 84 дня позитивный импульс дойдёт до BTC через ~3 месяца.`,
    bearish: `M2 падает ${formatPct(change3m)} за 3 мес — негативно для BTC на горизонте ~3 месяца.`,
    neutral: `M2 ${formatPct(change3m)} за 3 мес — вяло. Нет чёткого сигнала.`
  };

  return {
    value: latest.value,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(series, 24), // last 24 months
    source: SOURCE,
    source_updated: latest.date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchM2, SOURCE };
