'use strict';

const fs = require('fs');
const path = require('path');
const { appendHistory } = require('./history');

const CACHE_FILE = path.join(__dirname, '..', 'data', 'cache.json');

// TTL in milliseconds per tier
const TTL = {
  t1: 60 * 60 * 1000,            // 1 hour
  t2: 6 * 60 * 60 * 1000,        // 6 hours
  t3: 24 * 60 * 60 * 1000        // 24 hours
};

// Indicator registry — fixed order matters for UI rendering.
// Each entry: { id, name, tier, module, optional label }
const INDICATORS = [
  // Tier 1 — daily
  { id: 'etf_flows',         name: 'BTC spot ETF net flows',  tier: 't1', module: './fetchers/etf-flows' },
  { id: 'fear_greed',        name: 'Fear & Greed Index',      tier: 't1', module: './fetchers/fear-greed' },
  { id: 'stablecoin',        name: 'Stablecoin supply',       tier: 't1', module: './fetchers/stablecoin' },
  { id: 'polymarket_fed',    name: 'Fed decision (Polymarket)', tier: 't1', module: './fetchers/polymarket-fed' },
  { id: 'kalshi_fed',        name: 'Fed decision (Kalshi)',   tier: 't1', module: './fetchers/kalshi-fed' },
  { id: 'polymarket_btc_price', name: 'BTC price bias (Polymarket)', tier: 't1', module: './fetchers/polymarket-btc-price' },

  // Tier 2 — weekly
  { id: 'm2',                name: 'Global M2 (лаг 84d)',     tier: 't2', module: './fetchers/m2' },
  { id: 'btc_vs_200dma',     name: 'BTC vs 200-day MA',       tier: 't2', module: './fetchers/btc-vs-200dma' },
  { id: 'vix',               name: 'VIX',                     tier: 't2', module: './fetchers/vix' },
  { id: 'treasury_2y',       name: '2-Year Treasury yield',   tier: 't2', module: './fetchers/treasury-2y' },
  { id: 'cpi',               name: 'CPI YoY',                 tier: 't2', module: './fetchers/cpi' },

  // Tier 3 — monthly
  { id: 'gold_rotation',     name: 'Gold → BTC rotation',     tier: 't3', module: './fetchers/gold-rotation' },
  { id: 'copper_gold',       name: 'Copper/Gold ratio',       tier: 't3', module: './fetchers/copper-gold' }
];

function readCache() {
  try {
    if (!fs.existsSync(CACHE_FILE)) return {};
    const raw = fs.readFileSync(CACHE_FILE, 'utf8');
    return raw.trim() ? JSON.parse(raw) : {};
  } catch (err) {
    console.warn('[cache] read failed:', err.message);
    return {};
  }
}

function writeCache(cache) {
  try {
    const dir = path.dirname(CACHE_FILE);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2));
  } catch (err) {
    console.warn('[cache] write failed:', err.message);
  }
}

function isFresh(entry, tier) {
  if (!entry || !entry.fetched_at) return false;
  const age = Date.now() - new Date(entry.fetched_at).getTime();
  return age < TTL[tier];
}

function normalizeResult(ind, result) {
  const base = {
    id: ind.id,
    name: ind.name,
    tier: ind.tier
  };
  if (!result || typeof result !== 'object') {
    return {
      ...base,
      state: 'no_data',
      signal: 'neutral',
      value: null,
      display_value: '—',
      context: 'нет данных',
      history: [],
      source: '—',
      source_updated: null,
      fetched_at: new Date().toISOString(),
      error: 'empty result'
    };
  }
  return {
    ...base,
    state: result.state || 'ok',
    signal: result.signal || 'neutral',
    value: result.value != null ? result.value : null,
    display_value: result.display_value || '—',
    context: result.context || '',
    history: Array.isArray(result.history) ? result.history : [],
    source: result.source || '—',
    source_updated: result.source_updated || null,
    fetched_at: result.fetched_at || new Date().toISOString(),
    error: result.error || null
  };
}

async function runFetcher(ind) {
  const mod = require(ind.module);
  try {
    const raw = await mod.fetch();
    return normalizeResult(ind, raw);
  } catch (err) {
    console.warn(`[fetcher:${ind.id}]`, err.message);
    // Distinguish scraper breakage from generic network errors:
    const isScraperFile = ['etf_flows'].includes(ind.id);
    return normalizeResult(ind, {
      state: isScraperFile ? 'broken_scraper' : 'no_data',
      signal: 'neutral',
      display_value: isScraperFile ? 'SCRAPER BROKEN' : 'нет данных',
      context: isScraperFile
        ? 'HTML-структура источника изменилась. Нужно починить парсер.'
        : `Источник не отвечает: ${err.message}`,
      source: mod.SOURCE || '—',
      fetched_at: new Date().toISOString(),
      error: String(err.message || err)
    });
  }
}

async function collectIndicators({ force }) {
  const cache = readCache();
  const out = await Promise.all(
    INDICATORS.map(async (ind) => {
      if (!force && isFresh(cache[ind.id], ind.tier)) {
        return cache[ind.id];
      }
      const result = await runFetcher(ind);
      cache[ind.id] = result;
      return result;
    })
  );
  writeCache(cache);
  return out;
}

function computeScore(indicators) {
  const ok = indicators.filter((i) => i.state === 'ok');
  const bullish = ok.filter((i) => i.signal === 'bullish').length;
  const available = ok.length;
  const ratio = available > 0 ? bullish / available : 0;

  let verdict, color;
  if (available === 0) {
    verdict = 'Нет данных';
    color = 'gray';
  } else if (ratio >= 0.65) {
    verdict = 'Окно для входа — зелёный свет';
    color = 'green';
  } else if (ratio >= 0.45) {
    verdict = 'Подготовка к покупке — DCA малыми частями';
    color = 'yellow';
  } else if (ratio >= 0.25) {
    verdict = 'Смешанно — держать порох сухим';
    color = 'orange';
  } else {
    verdict = 'Макро против — ждать';
    color = 'red';
  }

  return { bullish, available, ratio, verdict, color };
}

function buildAlerts(indicators) {
  return indicators
    .filter((i) => i.state === 'broken_scraper')
    .map((i) => `${i.name}: ${i.context || 'скрейпер сломан'}`);
}

function splitByTier(indicators) {
  return {
    t1: indicators.filter((i) => i.tier === 't1'),
    t2: indicators.filter((i) => i.tier === 't2'),
    t3: indicators.filter((i) => i.tier === 't3')
  };
}

async function buildDashboard({ force }) {
  const indicators = await collectIndicators({ force });
  const score = computeScore(indicators);
  const alerts = buildAlerts(indicators);

  // BTC price pulled from btc_vs_200dma result if available (it fetches market_chart).
  const btcInd = indicators.find((i) => i.id === 'btc_vs_200dma');
  const btcPrice = (btcInd && btcInd.state === 'ok' && btcInd.value && typeof btcInd.value === 'object' && btcInd.value.price_meta)
    ? btcInd.value.price_meta
    : null;

  const response = {
    updated_at: new Date().toISOString(),
    score,
    btc_price: btcPrice,
    tiers: splitByTier(indicators),
    alerts
  };

  // Persist score history (with 1h dedup inside history.js)
  try {
    const signals = {};
    for (const i of indicators) signals[i.id] = i.signal;
    await appendHistory({
      ts: response.updated_at,
      bullish: score.bullish,
      available: score.available,
      ratio: score.ratio,
      signals
    });
  } catch (err) {
    console.warn('[history] append failed:', err.message);
  }

  return response;
}

async function forceRefresh() {
  return buildDashboard({ force: true });
}

module.exports = { buildDashboard, forceRefresh, INDICATORS };
