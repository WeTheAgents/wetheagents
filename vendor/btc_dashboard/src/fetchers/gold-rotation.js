'use strict';

const { fetchYahooDaily, nowIso, pctChange, formatPct, toSparkline } = require('./_util');

const SOURCE = 'Yahoo (GC=F, GLD)';

// Simplified gold→BTC rotation signal.
// For MVP we track gold trend only (falling gold after a run-up = rotation window opens).
// Full version would also cross-reference BTC ETF inflows (see etf-flows fetcher),
// but to keep this indicator standalone and non-brittle, we use gold alone here.
async function fetchGoldRotation() {
  const gold = await fetchYahooDaily('GC=F', { range: '6mo' });
  if (!gold.length) throw new Error('Yahoo: empty gold series');

  const latest = gold[gold.length - 1].value;
  const ago30 = gold[gold.length - 22] || gold[0];
  const ago90 = gold[gold.length - 66] || gold[0];

  const change30d = pctChange(ago30.value, latest);
  const change90d = pctChange(ago90.value, latest);

  // Bullish: gold was up (90d) but is now stalling/falling (30d) — classic rotation setup.
  // Bearish: gold rising on both horizons — safe-haven dominance, BTC lags.
  // Neutral: everything else.
  let signal;
  if (change90d != null && change90d > 5 && change30d != null && change30d < 0) {
    signal = 'bullish';
  } else if (change30d != null && change30d > 3 && change90d != null && change90d > 0) {
    signal = 'bearish';
  } else {
    signal = 'neutral';
  }

  const displayValue = `$${Math.round(latest).toLocaleString('en-US')} / oz`;

  const contextMap = {
    bullish: `Gold $${Math.round(latest)}, ${formatPct(change30d)} (30d) after ${formatPct(change90d)} (90d). Rally losing steam → historical rotation lag into BTC: 4–7 months.`,
    bearish: `Gold $${Math.round(latest)}, ${formatPct(change30d)} (30d), ${formatPct(change90d)} (90d). Safe-haven mode — BTC typically lags.`,
    neutral: `Gold $${Math.round(latest)}, ${formatPct(change30d)} (30d), ${formatPct(change90d)} (90d). Rotation hasn't kicked in.`
  };

  return {
    value: latest,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(gold, 30),
    source: SOURCE,
    source_updated: gold[gold.length - 1].date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchGoldRotation, SOURCE };
