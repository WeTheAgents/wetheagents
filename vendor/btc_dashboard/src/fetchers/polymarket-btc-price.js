'use strict';

const { httpGet, nowIso } = require('./_util');

const SOURCE = 'Polymarket (Gamma)';

// Polymarket runs monthly "What price will Bitcoin hit in <Month>?" events.
// Each event contains ~20 YES/NO markets of the form "↑ $XXk" and "↓ $YYk",
// where YES means "BTC touches this price at least once before the event
// end date". We convert these into a directional sentiment bias:
//
//   closest_up   = smallest UP bucket above current price
//   closest_down = largest DOWN bucket below current price
//   bias         = P(yes, closest_up) - P(yes, closest_down)
//
// Signal:
//   bias >  +0.20 → bullish (market thinks upside touch is much more likely)
//   bias <  -0.20 → bearish
//   otherwise     → neutral
async function fetchPolymarketBtcPrice() {
  // 1. Discover nearest "What price will Bitcoin hit in <month>?" event.
  const events = await httpGet(
    'https://gamma-api.polymarket.com/events?closed=false&limit=100&tag_slug=bitcoin',
    { json: true }
  );
  if (!Array.isArray(events)) throw new Error('Polymarket: bad events response');

  const candidates = events
    .filter((e) => /^what price will bitcoin hit in /i.test(e.title || ''))
    .filter((e) => e.endDate && new Date(e.endDate) > new Date())
    .sort((a, b) => new Date(a.endDate) - new Date(b.endDate));

  if (candidates.length === 0) {
    throw new Error('Polymarket: no upcoming "What price will Bitcoin hit in …" event');
  }

  const event = candidates[0];
  const markets = Array.isArray(event.markets) ? event.markets : [];
  if (markets.length === 0) throw new Error('Polymarket: event has no markets');

  // 2. Parse markets into {direction, target, pYes}.
  const buckets = [];
  for (const m of markets) {
    const title = String(m.groupItemTitle || '');
    const mUp = /↑\s*\$?([\d,]+)/i.exec(title);
    const mDn = /↓\s*\$?([\d,]+)/i.exec(title);
    const dir = mUp ? 'up' : mDn ? 'down' : null;
    if (!dir) continue;
    const target = Number((mUp || mDn)[1].replace(/,/g, ''));
    if (!Number.isFinite(target) || target <= 0) continue;

    const prices = parsePrices(m.outcomePrices);
    const outcomes = parseOutcomes(m.outcomes);
    const yesIdx = outcomes.findIndex((o) => /yes/i.test(o));
    const pYes = yesIdx >= 0 && Number.isFinite(Number(prices[yesIdx])) ? Number(prices[yesIdx]) : null;
    if (pYes == null) continue;

    buckets.push({ direction: dir, target, pYes });
  }

  if (buckets.length < 4) throw new Error(`Polymarket: too few parseable buckets (${buckets.length})`);

  // 3. Get current BTC price. CoinGecko free tier rate-limits aggressively
  // (10–30 req/min per IP), so we try it first and fall back to CoinCap.
  const current = await fetchBtcUsd();

  // 4. Find closest UP bucket strictly above current, closest DOWN bucket strictly below.
  const upsAbove = buckets
    .filter((b) => b.direction === 'up' && b.target > current)
    .sort((a, b) => a.target - b.target);
  const downsBelow = buckets
    .filter((b) => b.direction === 'down' && b.target < current)
    .sort((a, b) => b.target - a.target);

  if (upsAbove.length === 0 || downsBelow.length === 0) {
    throw new Error(
      `Polymarket: missing up/down bucket around current (${current}). ups=${upsAbove.length}, downs=${downsBelow.length}`
    );
  }

  const closestUp = upsAbove[0];
  const closestDown = downsBelow[0];
  const bias = closestUp.pYes - closestDown.pYes;

  let signal;
  if (bias > 0.2) signal = 'bullish';
  else if (bias < -0.2) signal = 'bearish';
  else signal = 'neutral';

  const displayValue =
    `+$${fmtK(closestUp.target)}: ${(closestUp.pYes * 100).toFixed(0)}% · -$${fmtK(closestDown.target)}: ${(closestDown.pYes * 100).toFixed(0)}%`;

  const biasPct = (bias * 100).toFixed(0);
  const contextMap = {
    bullish: `Market prices ${(closestUp.pYes * 100).toFixed(0)}% chance of hitting $${fmtK(closestUp.target)} vs ${(closestDown.pYes * 100).toFixed(0)}% for $${fmtK(closestDown.target)} (bias +${biasPct}%). Bullish sentiment.`,
    bearish: `Market prices ${(closestDown.pYes * 100).toFixed(0)}% chance of hitting $${fmtK(closestDown.target)} vs ${(closestUp.pYes * 100).toFixed(0)}% for $${fmtK(closestUp.target)} (bias ${biasPct}%). Bearish sentiment.`,
    neutral: `Nearby levels: +$${fmtK(closestUp.target)} ${(closestUp.pYes * 100).toFixed(0)}%, -$${fmtK(closestDown.target)} ${(closestDown.pYes * 100).toFixed(0)}% (bias ${biasPct}%). Neutral.`
  };

  return {
    value: {
      current,
      closestUp: { target: closestUp.target, p: closestUp.pYes },
      closestDown: { target: closestDown.target, p: closestDown.pYes },
      bias,
      slug: event.slug
    },
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: [],
    source: SOURCE,
    source_updated: new Date().toISOString().slice(0, 10),
    fetched_at: nowIso()
  };
}

function parsePrices(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(Number);
  if (typeof raw === 'string') {
    try { return JSON.parse(raw).map(Number); } catch (_) { return []; }
  }
  return [];
}

function parseOutcomes(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch (_) { return []; }
  }
  return [];
}

function fmtK(n) {
  return (n / 1000).toFixed(0) + 'K';
}

async function fetchBtcUsd() {
  // Primary: CoinGecko simple price
  try {
    const simple = await httpGet(
      'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd',
      { json: true }
    );
    const p = simple && simple.bitcoin && Number(simple.bitcoin.usd);
    if (Number.isFinite(p) && p > 0) return p;
  } catch (_) {
    // fall through
  }
  // Fallback: Binance spot ticker (no key, no rate limit at our volume).
  try {
    const b = await httpGet('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT', { json: true });
    const p = b && Number(b.price);
    if (Number.isFinite(p) && p > 0) return p;
  } catch (_) {
    // fall through
  }
  throw new Error('all BTC price sources failed (CoinGecko, Binance)');
}

module.exports = { fetch: fetchPolymarketBtcPrice, SOURCE };
