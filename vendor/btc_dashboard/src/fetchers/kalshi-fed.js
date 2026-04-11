'use strict';

const { httpGet, fetchFredSeries, nowIso } = require('./_util');

const SOURCE = 'Kalshi (KXFED via US proxy)';

// Kalshi prediction market for Fed funds rate after the next FOMC meeting.
// The API is geo-blocked (CloudFront) outside the US, so we route through
// the shared boobase upstream proxy with US exit.
//
// Market structure: one event per FOMC meeting (e.g. KXFED-26APR), containing
// ~11 cumulative-threshold markets of the form "Will the upper bound be above
// X% after the meeting?" Each market trades Yes/No; last_price_dollars is in
// [0, 1] and equals P(rate > X).
//
// To convert cumulative CDF into cut/hold/hike probabilities we need the
// current target upper bound. We fetch it from FRED DFEDTARU (free, no key).
//
//   Let U = current upper bound.
//   P(cut)  = P(rate < U) = P(rate ≤ U - 0.25) = 1 - yes(T{U - 0.25})
//   P(hold) = P(rate = U) = yes(T{U - 0.25}) - yes(T{U})
//   P(hike) = P(rate > U) = yes(T{U})
//
// Signal:
//   P(cut)  ≥ 0.50 → bullish
//   P(hike) ≥ 0.20 → bearish
//   otherwise       → neutral
async function fetchKalshiFed() {
  // 1. Get current Fed upper bound.
  const dfedtaru = await fetchFredSeries('DFEDTARU', { from: '2025-01-01' });
  if (dfedtaru.length === 0) throw new Error('FRED DFEDTARU: empty');
  const currentUpper = dfedtaru[dfedtaru.length - 1].value;

  // 2. Find the next FOMC event. Kalshi uses event_ticker=KXFED-YYMMM where
  //    the strike_date is the meeting date. Filter to events in the future,
  //    sort by date ascending, pick nearest.
  const events = await httpGet(
    'https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXFED&limit=50',
    { json: true, proxy: 'US' }
  );
  const evList = Array.isArray(events.events) ? events.events : [];
  if (evList.length === 0) throw new Error('Kalshi: no KXFED events returned');

  const now = Date.now();
  const upcoming = evList
    .filter((e) => e.strike_date && new Date(e.strike_date).getTime() > now)
    .sort((a, b) => new Date(a.strike_date) - new Date(b.strike_date));
  if (upcoming.length === 0) throw new Error('Kalshi: no upcoming KXFED events');

  const event = upcoming[0];
  const eventTicker = event.event_ticker;
  const meetingDate = new Date(event.strike_date).toISOString().slice(0, 10);

  // 3. Fetch all markets for this event.
  const marketsResp = await httpGet(
    `https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=${encodeURIComponent(eventTicker)}&limit=50`,
    { json: true, proxy: 'US' }
  );
  const markets = Array.isArray(marketsResp.markets) ? marketsResp.markets : [];
  if (markets.length === 0) throw new Error(`Kalshi: no markets for ${eventTicker}`);

  // 4. Build a threshold → P(rate > threshold) map from last_price (which is
  //    the last trade price; falls back to mid of bid/ask if no trades yet).
  const cdf = new Map();
  for (const m of markets) {
    const strike = Number(m.floor_strike);
    if (Number.isNaN(strike)) continue;
    const last = Number(m.last_price_dollars);
    const bid = Number(m.yes_bid_dollars);
    const ask = Number(m.yes_ask_dollars);
    let p;
    if (Number.isFinite(last) && last > 0) {
      p = last;
    } else if (Number.isFinite(bid) && Number.isFinite(ask) && ask > 0) {
      p = (bid + ask) / 2;
    } else {
      continue;
    }
    cdf.set(strike, p);
  }

  if (cdf.size === 0) throw new Error('Kalshi: no priced markets found');

  // 5. Compute the three probabilities from the CDF.
  const lowerThreshold = round2(currentUpper - 0.25);
  const pAboveLower = cdf.has(lowerThreshold) ? cdf.get(lowerThreshold) : null;
  const pAboveCurrent = cdf.has(currentUpper) ? cdf.get(currentUpper) : null;

  if (pAboveLower == null || pAboveCurrent == null) {
    throw new Error(
      `Kalshi: missing threshold markets for upper=${currentUpper} (need T${lowerThreshold} and T${currentUpper})`
    );
  }

  const pCut = Math.max(0, 1 - pAboveLower);
  const pHold = Math.max(0, pAboveLower - pAboveCurrent);
  const pHike = Math.max(0, pAboveCurrent);

  let signal;
  if (pCut >= 0.5) signal = 'bullish';
  else if (pHike >= 0.2) signal = 'bearish';
  else signal = 'neutral';

  const monthName = extractMonth(eventTicker);
  const displayValue =
    `P(cut)=${(pCut * 100).toFixed(0)}% · hold=${(pHold * 100).toFixed(0)}% · hike=${(pHike * 100).toFixed(0)}%`;

  const contextMap = {
    bullish: `Заседание ${monthName} (${meetingDate}): Kalshi закладывает снижение с вероятностью ${(pCut * 100).toFixed(0)}% (тек. верхняя ${currentUpper}%). Бычий для BTC.`,
    bearish: `Заседание ${monthName} (${meetingDate}): Kalshi даёт ${(pHike * 100).toFixed(0)}% на повышение (тек. верхняя ${currentUpper}%). Ястребиный фон.`,
    neutral: `Заседание ${monthName} (${meetingDate}): Kalshi закладывает ${(pHold * 100).toFixed(0)}% hold (тек. верхняя ${currentUpper}%).`
  };

  return {
    value: { pCut, pHold, pHike, currentUpper, meetingDate, eventTicker },
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

function round2(x) {
  return Math.round(x * 100) / 100;
}

function extractMonth(eventTicker) {
  // KXFED-26APR → "Apr"
  const m = /-\d\d([A-Z]{3})$/.exec(eventTicker);
  if (!m) return '—';
  const map = {
    JAN: 'Jan', FEB: 'Feb', MAR: 'Mar', APR: 'Apr', MAY: 'May', JUN: 'Jun',
    JUL: 'Jul', AUG: 'Aug', SEP: 'Sep', OCT: 'Oct', NOV: 'Nov', DEC: 'Dec'
  };
  return map[m[1]] || m[1];
}

module.exports = { fetch: fetchKalshiFed, SOURCE };
