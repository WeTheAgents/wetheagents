'use strict';

const { httpGet, nowIso } = require('./_util');

const SOURCE = 'Polymarket (Gamma)';

// Polymarket Fed rate decision probabilities for the NEXT FOMC meeting.
// Strategy: pull all open events tagged "fed-rates", keep only those whose
// title matches /^Fed decision in …/ (these are single-meeting events with
// mutually exclusive outcomes like "25 bps decrease", "No change", etc.),
// sort by endDate ascending, pick the nearest one. This way the fetcher
// auto-advances to the next meeting without code changes.
async function fetchPolymarketFed() {
  const events = await httpGet(
    'https://gamma-api.polymarket.com/events?closed=false&limit=100&tag_slug=fed-rates',
    { json: true }
  );

  if (!Array.isArray(events) || events.length === 0) {
    throw new Error('Polymarket: empty events response');
  }

  const candidates = events
    .filter((e) => /^fed decision in /i.test(e.title || ''))
    .filter((e) => e.endDate && new Date(e.endDate) > new Date())
    .sort((a, b) => new Date(a.endDate) - new Date(b.endDate));

  if (candidates.length === 0) {
    throw new Error('Polymarket: no upcoming "Fed decision in …" event found');
  }

  const event = candidates[0];
  const markets = Array.isArray(event.markets) ? event.markets : [];
  if (markets.length === 0) {
    throw new Error(`Polymarket: event ${event.slug} has no markets`);
  }

  // Classify each market by its groupItemTitle into cut / hold / hike buckets.
  // The YES price of each mutually-exclusive outcome IS its probability.
  let pCut = 0;
  let pHold = 0;
  let pHike = 0;

  for (const m of markets) {
    const title = String(m.groupItemTitle || m.question || '').toLowerCase();
    const prices = parsePrices(m.outcomePrices);
    const outcomes = parseOutcomes(m.outcomes);
    // Find YES outcome index
    const yesIdx = outcomes.findIndex((o) => /yes/i.test(o));
    const yes = yesIdx >= 0 && prices[yesIdx] != null ? Number(prices[yesIdx]) : null;
    if (yes == null) continue;

    if (/(decrease|cut|hike.*cut)/i.test(title) && /decrease|cut/i.test(title)) {
      pCut += yes;
    } else if (/no change|hold|unchanged/i.test(title)) {
      pHold += yes;
    } else if (/increase|hike/i.test(title)) {
      pHike += yes;
    }
  }

  // Sanity: probabilities should sum to ~1 (mutually exclusive outcomes).
  const total = pCut + pHold + pHike;
  if (total < 0.8 || total > 1.2) {
    // Not a clean single-meeting event; bail so we don't emit a bogus signal.
    throw new Error(
      `Polymarket: probabilities don't sum to ~1 (cut=${pCut.toFixed(2)}, hold=${pHold.toFixed(2)}, hike=${pHike.toFixed(2)})`
    );
  }

  let signal;
  if (pCut >= 0.5) signal = 'bullish';
  else if (pHike >= 0.2) signal = 'bearish';
  else signal = 'neutral';

  const meetingDate = new Date(event.endDate).toISOString().slice(0, 10);
  const monthName = extractMonth(event.title);

  const displayValue =
    `P(cut)=${(pCut * 100).toFixed(0)}% · hold=${(pHold * 100).toFixed(0)}% · hike=${(pHike * 100).toFixed(0)}%`;

  const contextMap = {
    bullish: `${monthName} meeting (${meetingDate}): market prices a cut at ${(pCut * 100).toFixed(0)}%. Bullish for BTC.`,
    bearish: `${monthName} meeting (${meetingDate}): odds of a hike ${(pHike * 100).toFixed(0)}% — hawkish backdrop.`,
    neutral: `${monthName} meeting (${meetingDate}): market prices ${(pHold * 100).toFixed(0)}% hold, cut ${(pCut * 100).toFixed(0)}%. Fed most likely holds.`
  };

  return {
    value: { pCut, pHold, pHike, meetingDate, slug: event.slug, volume: event.volume },
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: [], // Polymarket prices-history requires CLOB token IDs; skipping for MVP
    source: SOURCE,
    source_updated: new Date().toISOString().slice(0, 10),
    fetched_at: nowIso()
  };
}

function parsePrices(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(Number);
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw).map(Number);
    } catch (_) {
      return [];
    }
  }
  return [];
}

function parseOutcomes(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw);
    } catch (_) {
      return [];
    }
  }
  return [];
}

function extractMonth(title) {
  const m = /in\s+(\w+)/i.exec(title || '');
  return m ? m[1] : '—';
}

module.exports = { fetch: fetchPolymarketFed, SOURCE };
