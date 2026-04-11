'use strict';

const { httpGet, nowIso } = require('./_util');

const SOURCE = 'Farside Investors';

// Farside publishes the BTC spot ETF flow table as HTML at https://farside.co.uk/btc/
// We parse the last column (Total) of the last ~30 data rows.
// If the HTML structure changes, this throws — engine.js marks state=broken_scraper.
function parseFarsideHtml(html) {
  // Find all <table> blocks and pick the biggest — that's the flow table.
  const tableMatch = html.match(/<table[\s\S]*?<\/table>/gi);
  if (!tableMatch) throw new Error('no <table> element found');

  let tableHtml = null;
  let biggest = 0;
  for (const t of tableMatch) {
    if (t.length > biggest && /IBIT/.test(t)) {
      biggest = t.length;
      tableHtml = t;
    }
  }
  if (!tableHtml) throw new Error('Farside flow table not found (no IBIT marker)');

  const rows = [];
  const rowRe = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
  let m;
  while ((m = rowRe.exec(tableHtml)) !== null) {
    const cells = [];
    const cellRe = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
    let c;
    while ((c = cellRe.exec(m[1])) !== null) {
      // Strip HTML tags, normalize nbsp, collapse whitespace.
      const text = c[1]
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
      cells.push(text);
    }
    if (cells.length > 0) rows.push(cells);
  }

  if (rows.length < 5) throw new Error(`too few rows parsed: ${rows.length}`);

  // Farside layout as of 2026:
  //   row 0: group header — last cell = "Total", rest empty
  //   row 1: ETF ticker names — first cell empty, last cell empty
  //   row 2: "Fee" row
  //   row 3+: date rows (col 0 = date, last col = total)
  //   plus a final "Total" summary row we should skip.
  //
  // We use fixed column indices: Date = 0, Total = last cell.
  const dateCol = 0;

  // Find the first data row: first row whose first cell matches a date.
  const dateRe = /^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$/;
  const flows = [];
  for (const row of rows) {
    const dateRaw = row[dateCol];
    const totalRaw = row[row.length - 1];
    if (!dateRaw || !totalRaw) continue;
    if (!dateRe.test(dateRaw)) continue;
    const num = parseFarsideNumber(totalRaw);
    if (num == null) continue;
    flows.push({ date: normalizeFarsideDate(dateRaw), value: num });
  }

  if (flows.length < 7) throw new Error(`too few flow rows parsed: ${flows.length}`);
  return flows;
}

function parseFarsideNumber(raw) {
  // Numbers look like "471.0", "-38.8", "(38.8)" for negatives, or "-" for
  // missing. Accounting notation "(x)" means negative; detect the parens
  // BEFORE stripping them.
  const trimmed = String(raw).trim().replace(/[,\s]/g, '');
  if (!trimmed || trimmed === '-') return 0;
  const isNegative = /^\(.*\)$/.test(trimmed);
  const stripped = trimmed.replace(/^\(|\)$/g, '');
  const n = Number(stripped);
  if (!Number.isFinite(n)) return null;
  return isNegative ? -n : n;
}

function normalizeFarsideDate(raw) {
  const [d, mon, y] = raw.split(/\s+/);
  const months = {
    Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06',
    Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12'
  };
  const mm = months[mon.slice(0, 3)];
  if (!mm) return raw;
  return `${y}-${mm}-${d.padStart(2, '0')}`;
}

async function fetchEtfFlows() {
  // Farside sits behind Cloudflare bot detection. Two requirements:
  //   1. Exit from a US (or at least non-blocked) IP — via the shared
  //      upstream proxy with US username.
  //   2. Full browser-like header set — otherwise the edge returns 403.
  // Cloudflare fingerprints Node's TLS stack (undici/BoringSSL) as a bot and
  // serves the "Just a moment…" challenge even with perfect headers. The
  // system's `curl` (OpenSSL) gets through cleanly, so we shell out via the
  // curl: true routing in httpGet — still honours the same proxy/headers.
  const html = await httpGet('https://farside.co.uk/btc/', {
    accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    proxy: 'US',
    curl: true,
    headers: {
      'User-Agent':
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9',
      'sec-fetch-dest': 'document',
      'sec-fetch-mode': 'navigate',
      'sec-fetch-site': 'none',
      'upgrade-insecure-requests': '1'
    }
  });
  const flows = parseFarsideHtml(html); // throws → broken_scraper

  // Sort chronologically (oldest first) — Farside page is newest-first
  flows.sort((a, b) => a.date.localeCompare(b.date));

  const last7 = flows.slice(-7);
  const sum7 = last7.reduce((s, f) => s + f.value, 0);
  const last21 = flows.slice(-21);
  const sum21 = last21.reduce((s, f) => s + f.value, 0);

  let signal;
  if (sum7 > 0 && sum21 > 0) signal = 'bullish';
  else if (sum7 < 0 && sum21 < 0) signal = 'bearish';
  else signal = 'neutral';

  const displayValue = `${sum7 >= 0 ? '+' : ''}$${sum7.toFixed(0)}M (7d)`;

  const contextMap = {
    bullish: `Приток $${sum7.toFixed(0)}M за 7д, $${sum21.toFixed(0)}M за 21д. Институционалы набирают позицию через спот-ETF.`,
    bearish: `Оттоки ${sum7.toFixed(0)}M за 7д, ${sum21.toFixed(0)}M за 21д. Давление на продажу от ETF-инвесторов.`,
    neutral: `7д: ${sum7 >= 0 ? '+' : ''}$${sum7.toFixed(0)}M, 21д: ${sum21 >= 0 ? '+' : ''}$${sum21.toFixed(0)}M. Смешанные потоки.`
  };

  return {
    value: sum7,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: flows.slice(-30).map((f) => ({ ts: f.date, value: f.value })),
    source: SOURCE,
    source_updated: flows[flows.length - 1].date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchEtfFlows, SOURCE };
