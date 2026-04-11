'use strict';

const { httpGet, nowIso } = require('./_util');

const SOURCE = 'CoinGecko → Binance';

async function fetchBtcVs200Dma() {
  // Historical daily prices for 200 days — enough for a 200d MA.
  // CoinGecko free tier aggressively rate-limits (10–30 req/min), so we
  // fall back to CoinCap if that fails.
  const prices = await fetchHistoricalPrices();
  if (!prices || prices.length < 30) {
    throw new Error('no historical price source returned enough points');
  }

  const latest = prices[prices.length - 1].value;
  const ma200 = prices.reduce((s, p) => s + p.value, 0) / prices.length;
  const diffPct = ((latest - ma200) / ma200) * 100;

  let signal;
  if (diffPct >= 0) signal = 'bullish';
  else if (diffPct <= -10) signal = 'bearish';
  else signal = 'neutral';

  // Also pull price + 24h/7d change for header. 7d comes from local history,
  // USD/EUR/24h come from whichever price source responds.
  const ago7 = prices[prices.length - 8] || prices[0];
  const change7d = ((latest - ago7.value) / ago7.value) * 100;
  const ago1 = prices[prices.length - 2] || prices[0];
  const change24hFallback = ((latest - ago1.value) / ago1.value) * 100;

  let priceMeta = {
    usd: latest,
    eur: null,
    change_24h: change24hFallback,
    change_7d: change7d
  };
  try {
    const simple = await httpGet(
      'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,eur&include_24hr_change=true',
      { json: true }
    );
    if (simple && simple.bitcoin) {
      priceMeta = {
        usd: simple.bitcoin.usd,
        eur: simple.bitcoin.eur,
        change_24h: simple.bitcoin.usd_24h_change,
        change_7d: change7d
      };
    }
  } catch (_) {
    // Keep the local-derived fallback above.
  }

  const displayValue = `$${Math.round(latest).toLocaleString('en-US')} (${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}% to MA200)`;

  const contextMap = {
    bullish: `Price ≥ 200-day MA ($${Math.round(ma200).toLocaleString('en-US')}). Above the accumulation zone — bullish regime.`,
    bearish: `Price ${Math.abs(diffPct).toFixed(1)}% below the 200-day MA. Deep under institutional cost basis.`,
    neutral: `Price slightly below the 200-day MA ($${Math.round(ma200).toLocaleString('en-US')}) — edge of the accumulation zone.`
  };

  return {
    value: { price: latest, ma200, diff_pct: diffPct, price_meta: priceMeta },
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: prices.slice(-30),
    source: SOURCE,
    source_updated: prices[prices.length - 1].ts,
    fetched_at: nowIso()
  };
}

async function fetchHistoricalPrices() {
  // Primary: CoinGecko market_chart
  try {
    const url = 'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=200&interval=daily';
    const hist = await httpGet(url, { json: true });
    if (hist && Array.isArray(hist.prices) && hist.prices.length >= 30) {
      return hist.prices.map(([ts, p]) => ({
        ts: new Date(ts).toISOString().slice(0, 10),
        value: Number(p)
      }));
    }
  } catch (_) {
    // fall through
  }
  // Fallback: Binance daily klines. No key, no rate limit at our volume.
  // Returns [[openTime, open, high, low, close, volume, ...], ...]
  try {
    const url = 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=200';
    const klines = await httpGet(url, { json: true });
    if (Array.isArray(klines) && klines.length >= 30) {
      return klines.map((k) => ({
        ts: new Date(Number(k[0])).toISOString().slice(0, 10),
        value: Number(k[4]) // close price
      }));
    }
  } catch (_) {
    // fall through
  }
  return null;
}

module.exports = { fetch: fetchBtcVs200Dma, SOURCE };
