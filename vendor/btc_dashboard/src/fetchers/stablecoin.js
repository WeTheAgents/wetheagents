'use strict';

const { httpGet, nowIso, pctChange, formatPct } = require('./_util');

const SOURCE = 'DefiLlama';

async function fetchStablecoin() {
  const json = await httpGet('https://stablecoins.llama.fi/stablecoincharts/all', { json: true });
  if (!Array.isArray(json) || json.length === 0) {
    throw new Error('DefiLlama: empty stablecoin chart');
  }

  // Each point: { date: unix_sec, totalCirculating: { peggedUSD: number, ... }, ... }
  const points = json
    .map((p) => {
      const date = new Date(Number(p.date) * 1000).toISOString().slice(0, 10);
      const total =
        (p.totalCirculating && (p.totalCirculating.peggedUSD || p.totalCirculating.total)) ||
        p.totalCirculatingUSD ||
        null;
      return total != null ? { date, value: Number(total) } : null;
    })
    .filter(Boolean);

  if (points.length < 30) {
    throw new Error('DefiLlama: not enough points for 30d trend');
  }

  const latest = points[points.length - 1];
  const ago30 = points[points.length - 31] || points[0];
  const change30 = pctChange(ago30.value, latest.value);

  let signal;
  if (change30 != null && change30 > 2) signal = 'bullish';
  else if (change30 != null && change30 < 0) signal = 'bearish';
  else signal = 'neutral';

  const displayValue = `$${(latest.value / 1e9).toFixed(0)}B`;
  const contextMap = {
    bullish: `Капитализация $${(latest.value / 1e9).toFixed(0)}B, рост ${formatPct(change30)} за 30д — dry powder накапливается.`,
    bearish: `Капитализация $${(latest.value / 1e9).toFixed(0)}B, падение ${formatPct(change30)} за 30д — ликвидность уходит.`,
    neutral: `Капитализация $${(latest.value / 1e9).toFixed(0)}B, изменение ${formatPct(change30)} за 30д — без резких движений.`
  };

  return {
    value: latest.value,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: points.slice(-30).map((p) => ({ ts: p.date, value: p.value })),
    source: SOURCE,
    source_updated: latest.date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchStablecoin, SOURCE };
