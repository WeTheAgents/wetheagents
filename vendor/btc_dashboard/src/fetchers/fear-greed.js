'use strict';

const { httpGet, nowIso } = require('./_util');

const SOURCE = 'alternative.me';

async function fetchFearGreed() {
  const json = await httpGet('https://api.alternative.me/fng/?limit=30&format=json', { json: true });
  if (!json || !Array.isArray(json.data) || json.data.length === 0) {
    throw new Error('alternative.me: empty data');
  }
  // API returns newest-first.
  const latest = json.data[0];
  const value = Number(latest.value);
  const classification = latest.value_classification || '';

  let signal;
  if (value < 25) signal = 'bullish';
  else if (value > 75) signal = 'bearish';
  else signal = 'neutral';

  // Build 30-day sparkline (reverse to oldest-first)
  const history = json.data
    .slice()
    .reverse()
    .map((d) => ({
      ts: new Date(parseInt(d.timestamp, 10) * 1000).toISOString().slice(0, 10),
      value: Number(d.value)
    }));

  const ctxMap = {
    bullish: `${value} — ${classification}. Extreme fear historically overlaps with accumulation zones.`,
    bearish: `${value} — ${classification}. Euphoria zone — caution.`,
    neutral: `${value} — ${classification}. Neutral range, waiting for a shift.`
  };

  return {
    value,
    display_value: `${value} — ${classification}`,
    signal,
    state: 'ok',
    context: ctxMap[signal],
    history,
    source: SOURCE,
    source_updated: new Date(parseInt(latest.timestamp, 10) * 1000).toISOString().slice(0, 10),
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchFearGreed, SOURCE };
