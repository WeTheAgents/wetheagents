'use strict';

const { fetchYahooDaily, fetchFredSeries, nowIso, toSparkline } = require('./_util');

const SOURCE = 'Yahoo ^VIX → FRED VIXCLS';

async function fetchVix() {
  let series;
  let sourceUsed = 'Yahoo ^VIX';
  try {
    series = await fetchYahooDaily('^VIX', { range: '3mo' });
    if (!series || series.length < 5) throw new Error('empty Yahoo VIX series');
  } catch (err) {
    // Fallback to FRED
    series = await fetchFredSeries('VIXCLS', { from: '2025-01-01' });
    sourceUsed = 'FRED VIXCLS';
  }

  if (!series || series.length === 0) throw new Error('VIX: no data from any source');

  const latest = series[series.length - 1].value;

  let signal;
  if (latest < 20) signal = 'bullish';
  else if (latest > 30) signal = 'bearish';
  else signal = 'neutral';

  const contextMap = {
    bullish: `VIX ${latest.toFixed(1)} — calm, risk-on environment for BTC.`,
    bearish: `VIX ${latest.toFixed(1)} — stress mode, risk assets under pressure.`,
    neutral: `VIX ${latest.toFixed(1)} — neutral, neither panic nor euphoria.`
  };

  return {
    value: latest,
    display_value: latest.toFixed(1),
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(series, 30),
    source: sourceUsed,
    source_updated: series[series.length - 1].date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchVix, SOURCE };
