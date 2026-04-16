'use strict';

const https = require('https');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { Resolver } = require('dns').promises;
const undici = require('undici');

const DEFAULT_TIMEOUT_MS = 15000;
const DEFAULT_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'Chrome/122.0.0.0 Safari/537.36';

// Upstream HTTP proxy config shared with the boobase sibling repo.
// Read lazily and cached. Falls back to env var PROXY_URL if the file is
// absent, or to a sensible default template if the file exists but lacks
// the requested country.
const BOOBASE_PROXIES_FILE = 'D:\\GitHub\\boobase\\configs\\proxies.json';
let _proxyDb = null;

function loadProxyDb() {
  if (_proxyDb !== null) return _proxyDb;
  try {
    if (fs.existsSync(BOOBASE_PROXIES_FILE)) {
      _proxyDb = JSON.parse(fs.readFileSync(BOOBASE_PROXIES_FILE, 'utf8'));
      return _proxyDb;
    }
  } catch (err) {
    console.warn('[proxy] failed to read proxies.json:', err.message);
  }
  _proxyDb = {};
  return _proxyDb;
}

// Resolve proxy URL for a country code (e.g. "US", "GB"). Returns null for
// "DIRECT" or when no config is available.
function getProxyUrl(country) {
  if (!country || country === 'DIRECT') return null;
  const cc = country.toUpperCase();
  const db = loadProxyDb();
  if (db[cc]) return db[cc];
  const tpl = db._default;
  if (tpl) return tpl.replace('{country}', cc);
  return null;
}

// Cached ProxyAgent instances per country so we don't rebuild them on every
// request.
const _proxyAgents = new Map();
function getProxyAgent(country) {
  if (!country) return null;
  if (_proxyAgents.has(country)) return _proxyAgents.get(country);
  const url = getProxyUrl(country);
  if (!url) {
    _proxyAgents.set(country, null);
    return null;
  }
  const agent = new undici.ProxyAgent({
    uri: url,
    requestTls: { servername: undefined }
  });
  _proxyAgents.set(country, agent);
  return agent;
}

// Public DNS resolvers, used as fallback when the system resolver returns
// loopback or otherwise blocks a hostname (DNS-level filters, hosts file, etc.)
const PUBLIC_DNS = ['1.1.1.1', '1.0.0.1', '8.8.8.8'];

let _resolver;
function getResolver() {
  if (!_resolver) {
    _resolver = new Resolver();
    _resolver.setServers(PUBLIC_DNS);
  }
  return _resolver;
}

// Fetch via https.request with a manually-resolved IP + SNI. Used to bypass
// system DNS filters. Follows up to 3 redirects.
async function httpGetDnsBypass(url, opts = {}, redirects = 3) {
  const u = new URL(url);
  const ips = await getResolver().resolve4(u.hostname);
  if (!ips || ips.length === 0) throw new Error(`DNS: no A records for ${u.hostname}`);

  return new Promise((resolve, reject) => {
    const headers = {
      Host: u.hostname,
      'User-Agent': DEFAULT_UA,
      Accept: opts.accept || 'application/json',
      ...(opts.headers || {})
    };
    const req = https.request(
      {
        host: ips[0],
        servername: u.hostname,
        port: u.port || 443,
        path: u.pathname + u.search,
        method: 'GET',
        headers,
        timeout: opts.timeout || DEFAULT_TIMEOUT_MS
      },
      (res) => {
        const status = res.statusCode || 0;
        // Follow redirects
        if (status >= 300 && status < 400 && res.headers.location && redirects > 0) {
          res.resume();
          const next = new URL(res.headers.location, url).toString();
          httpGetDnsBypass(next, opts, redirects - 1).then(resolve, reject);
          return;
        }
        if (status < 200 || status >= 300) {
          res.resume();
          reject(new Error(`HTTP ${status} @ ${url}`));
          return;
        }
        let data = '';
        res.setEncoding('utf8');
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          try {
            resolve(opts.json ? JSON.parse(data) : data);
          } catch (err) {
            reject(new Error(`JSON parse failed: ${err.message}`));
          }
        });
      }
    );
    req.on('timeout', () => {
      req.destroy(new Error('request timeout'));
    });
    req.on('error', reject);
    req.end();
  });
}

// Last-resort path for sources that detect Node's TLS fingerprint (JA3) as a
// bot — Cloudflare "Just a moment" challenge being the primary culprit.
// Spawns the system `curl` binary (OpenSSL fingerprint, different from
// undici/BoringSSL) and streams the body back. Honours opts.proxy and
// opts.headers just like httpGet.
function httpGetViaCurl(url, opts = {}) {
  return new Promise((resolve, reject) => {
    const args = ['-sS', '--max-time', String(Math.ceil((opts.timeout || DEFAULT_TIMEOUT_MS) / 1000))];

    if (opts.proxy) {
      const proxyUrl = getProxyUrl(opts.proxy);
      if (!proxyUrl) {
        reject(new Error(`curl: proxy not configured for "${opts.proxy}"`));
        return;
      }
      args.push('-x', proxyUrl);
    }

    const headers = {
      'User-Agent': DEFAULT_UA,
      Accept: opts.accept || '*/*',
      ...(opts.headers || {})
    };
    for (const [k, v] of Object.entries(headers)) {
      args.push('-H', `${k}: ${v}`);
    }

    args.push(url);

    // `curl` is what Git Bash / MinGW ships. On Windows outside Git Bash it
    // might be `curl.exe`. We try `curl` first; if ENOENT, caller should have
    // a fallback.
    const child = spawn('curl', args, { windowsHide: true });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (c) => (stdout += c));
    child.stderr.on('data', (c) => (stderr += c));
    child.on('error', (err) => reject(new Error(`curl spawn failed: ${err.message}`)));
    child.on('close', (code) => {
      if (code !== 0) {
        reject(new Error(`curl exited ${code}: ${stderr.trim() || 'no stderr'}`));
        return;
      }
      try {
        resolve(opts.json ? JSON.parse(stdout) : stdout);
      } catch (err) {
        reject(new Error(`curl JSON parse failed: ${err.message}`));
      }
    });
  });
}

// Route a request through an upstream HTTP proxy (undici.fetch + ProxyAgent).
// Used for geo-blocked sources — pass { proxy: 'US' } in opts.
async function httpGetViaProxy(url, opts = {}) {
  const agent = getProxyAgent(opts.proxy);
  if (!agent) throw new Error(`proxy not configured for country "${opts.proxy}"`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeout || DEFAULT_TIMEOUT_MS);
  try {
    const res = await undici.fetch(url, {
      dispatcher: agent,
      signal: controller.signal,
      headers: {
        'User-Agent': DEFAULT_UA,
        Accept: opts.accept || '*/*',
        ...(opts.headers || {})
      },
      redirect: 'follow'
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${res.statusText} @ ${url} (via ${opts.proxy})`);
    }
    return opts.raw ? res : (opts.json ? res.json() : res.text());
  } finally {
    clearTimeout(timeout);
  }
}

// Standard fetch with auto-fallback to DNS bypass if the OS resolver is
// poisoned (fetch fails with ENOTFOUND / connection refused on 127.0.0.1).
// If opts.proxy is set, skips the standard fetch and routes through the
// configured upstream proxy.
async function httpGet(url, opts = {}) {
  if (opts.curl) {
    return httpGetViaCurl(url, opts);
  }
  if (opts.proxy) {
    return httpGetViaProxy(url, opts);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeout || DEFAULT_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: {
        'User-Agent': DEFAULT_UA,
        Accept: opts.accept || '*/*',
        ...(opts.headers || {})
      },
      redirect: 'follow'
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${res.statusText} @ ${url}`);
    }
    return opts.raw ? res : (opts.json ? res.json() : res.text());
  } catch (err) {
    // Fallback: transient network failure OR OS-level DNS block. We cover
    // both by retrying via https.request + public DNS:
    //   - ECONNRESET / ECONNREFUSED: upstream reset — retry on a new socket
    //   - ENOTFOUND / 127.0.0.1 loopback: local DNS poisoning — resolve
    //     through 1.1.1.1 and bypass the OS resolver
    //   - ConnectTimeoutError: undici gave up dialling, try again with
    //     native https.request which has different retry characteristics
    const msg = (err && err.cause && err.cause.message) || err.message || '';
    const isNetworkFailure =
      /fetch failed|ECONNREFUSED|ECONNRESET|ENOTFOUND|EAI_AGAIN|other side closed|socket hang up/i.test(msg) ||
      /ConnectTimeoutError/i.test(String(err.cause));
    if (isNetworkFailure) {
      try {
        return await httpGetDnsBypass(url, opts);
      } catch (err2) {
        // Last-gasp retry: same path, fresh socket, short back-off.
        await new Promise((r) => setTimeout(r, 400));
        return httpGetDnsBypass(url, opts);
      }
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

// FRED free CSV endpoint (no key required)
function fredCsvUrl(seriesId, { from } = {}) {
  const params = new URLSearchParams({
    id: seriesId,
    cosd: from || '2015-01-01'
  });
  return `https://fred.stlouisfed.org/graph/fredgraph.csv?${params.toString()}`;
}

// Parse FRED CSV: "DATE,VALUE"
// Returns array of {date: 'YYYY-MM-DD', value: number} — skipping "." (missing) values.
function parseFredCsv(csv) {
  const lines = csv.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const out = [];
  for (let i = 1; i < lines.length; i++) {
    const parts = lines[i].split(',');
    if (parts.length < 2) continue;
    const date = parts[0].trim();
    const raw = parts[1].trim();
    if (!date || raw === '' || raw === '.') continue;
    const num = Number(raw);
    if (Number.isNaN(num)) continue;
    out.push({ date, value: num });
  }
  return out;
}

async function fetchFredSeries(seriesId, opts = {}) {
  const csv = await httpGet(fredCsvUrl(seriesId, opts), { accept: 'text/csv' });
  return parseFredCsv(csv);
}

// Yahoo Finance v8 chart API — no key, interval=1d
async function fetchYahooDaily(symbol, { range = '1y' } = {}) {
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    `?interval=1d&range=${range}&events=history`;
  const json = await httpGet(url, { json: true, accept: 'application/json' });
  const result = json && json.chart && json.chart.result && json.chart.result[0];
  if (!result) throw new Error(`Yahoo: empty result for ${symbol}`);
  const ts = result.timestamp || [];
  const closes = (result.indicators && result.indicators.quote && result.indicators.quote[0] && result.indicators.quote[0].close) || [];
  const out = [];
  for (let i = 0; i < ts.length; i++) {
    if (closes[i] == null || Number.isNaN(closes[i])) continue;
    out.push({
      date: new Date(ts[i] * 1000).toISOString().slice(0, 10),
      value: Number(closes[i])
    });
  }
  return out;
}

// Helpers
function pctChange(oldVal, newVal) {
  if (oldVal == null || newVal == null || oldVal === 0) return null;
  return ((newVal - oldVal) / Math.abs(oldVal)) * 100;
}

function formatPct(v, digits = 1) {
  if (v == null || Number.isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(digits)}%`;
}

function nowIso() {
  return new Date().toISOString();
}

// Slice last N points from an array of {date,value}, condensed to just {ts, value}.
function toSparkline(series, n) {
  return series
    .slice(-n)
    .map((p) => ({ ts: p.date, value: p.value }));
}

module.exports = {
  httpGet,
  fetchFredSeries,
  fetchYahooDaily,
  pctChange,
  formatPct,
  nowIso,
  toSparkline
};
