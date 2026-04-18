#!/usr/bin/env node
/**
 * Build a static snapshot of btc_dashboard into docs/btc/.
 *
 * Runs in two places:
 *   - GitHub Actions (.github/workflows/btc-snapshot.yml) — daily cron.
 *   - Locally, for iterating on the builder itself.
 *
 * Layout:
 *   REPO_ROOT/
 *     vendor/btc_dashboard/   (vendored upstream src — btc_dashboard is private
 *                              so GH Actions can't cross-checkout it)
 *     scripts/btc_snapshot_build.js  (this file)
 *     docs/btc/               (generated — committed)
 *     data/btc_history.jsonl  (append-only history — committed)
 *
 * The script is idempotent: running it twice in the same hour replaces the
 * previous history point (dedup window = 1h) and rewrites docs/btc/ files.
 */
'use strict';

const fs   = require('fs');
const path = require('path');

const REPO  = path.resolve(__dirname, '..');
const DASH  = path.join(REPO, 'vendor', 'btc_dashboard');
const OUT   = path.join(REPO, 'docs', 'btc');
const HIST  = path.join(REPO, 'data', 'btc_history.jsonl');

const DEDUP_WINDOW_MS = 60 * 60 * 1000; // 1 hour

function assertReplace(original, replaced, label) {
  if (original === replaced) {
    throw new Error(
      `[btc-snapshot] replacement '${label}' did not match — btc_dashboard ` +
      `source drifted. Fix the builder.`
    );
  }
  return replaced;
}

async function main() {
  if (!fs.existsSync(DASH)) {
    throw new Error(`vendored btc_dashboard not found at ${DASH}`);
  }

  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(path.dirname(HIST), { recursive: true });

  // ── 1. Build fresh data via engine.buildDashboard ──────────────────────
  const { buildDashboard } = require(path.join(DASH, 'src', 'engine.js'));
  const data = await buildDashboard({ force: true });

  // ── 1b. Inject static educational content per indicator ────────────────
  const education = JSON.parse(
    fs.readFileSync(path.join(__dirname, 'btc_education.json'), 'utf8')
  );
  for (const tier of Object.values(data.tiers)) {
    for (const ind of tier) {
      if (education[ind.id]) {
        ind.education = education[ind.id];
      }
    }
  }

  fs.writeFileSync(
    path.join(OUT, 'dashboard.json'),
    JSON.stringify(data, null, 2) + '\n'
  );
  console.log(`[btc-snapshot] built ${data.score.bullish}/${data.score.available} @ ${data.updated_at}`);

  // ── 2. Append history point (with 1h dedup) ────────────────────────────
  const point = {
    ts:        data.updated_at,
    ratio:     data.score.ratio,
    bullish:   data.score.bullish,
    available: data.score.available,
  };

  let lines = [];
  if (fs.existsSync(HIST)) {
    lines = fs.readFileSync(HIST, 'utf8')
      .split('\n')
      .filter((s) => s.trim().length > 0);
  }

  const last = lines.length > 0 ? JSON.parse(lines[lines.length - 1]) : null;
  if (last && last.ts) {
    const age = new Date(point.ts).getTime() - new Date(last.ts).getTime();
    if (age >= 0 && age < DEDUP_WINDOW_MS) {
      lines[lines.length - 1] = JSON.stringify(point);
    } else {
      lines.push(JSON.stringify(point));
    }
  } else {
    lines.push(JSON.stringify(point));
  }
  fs.writeFileSync(HIST, lines.join('\n') + '\n');

  // ── 3. Emit docs/btc/history.json (last 90 days) ───────────────────────
  const cutoff = Date.now() - 90 * 24 * 60 * 60 * 1000;
  const recent = lines
    .map((s) => {
      try { return JSON.parse(s); } catch { return null; }
    })
    .filter((p) => p && p.ts && new Date(p.ts).getTime() >= cutoff)
    .map((p) => ({
      ts: p.ts,
      ratio: p.ratio,
      bullish: p.bullish,
      available: p.available,
    }));
  fs.writeFileSync(
    path.join(OUT, 'history.json'),
    JSON.stringify({ points: recent }, null, 2) + '\n'
  );

  // ── 4. Copy static assets verbatim ─────────────────────────────────────
  const PUBLIC = path.join(DASH, 'src', 'public');
  for (const f of ['style.css', 'sparkline.js']) {
    fs.copyFileSync(path.join(PUBLIC, f), path.join(OUT, f));
  }

  // ── 5. Patch index.html (drop API_BASE script, neutralize Refresh btn) ─
  let html = fs.readFileSync(path.join(PUBLIC, 'index.html'), 'utf8');
  // Match the API_BASE script tag into a variable so no <script> literal
  // appears directly in the replace() call on html. html is read from a local
  // vendor file (vendor/btc_dashboard/src/public/index.html) — not user input.
  const apiBaseTag = (html.match(/<script>window\.API_BASE[^<]*<\/script>/) || [])[0];
  html = assertReplace(
    html,
    apiBaseTag ? html.replace(apiBaseTag, '<!-- static snapshot: no API_BASE -->') : html,
    'index.html: remove API_BASE script'
  );
  // Refresh button already hidden in source (<span hidden>), no patch needed.
  fs.writeFileSync(path.join(OUT, 'index.html'), html);

  // ── 6. Patch app.js: /api/* → local json files ─────────────────────────
  let js = fs.readFileSync(path.join(PUBLIC, 'app.js'), 'utf8').replace(/\r\n/g, '\n');

  // 6a. Drop BASE const
  js = assertReplace(
    js,
    js.replace(
      "const BASE = window.API_BASE ?? '';",
      '// static snapshot: data is served next to this file, no BASE prefix'
    ),
    'app.js: drop BASE const'
  );

  // 6b. Redirect the dashboard/refresh fetch to dashboard.json (GET)
  const fetchBlock =
    '    const res = await fetch(force ? `${BASE}/api/refresh` : `${BASE}/api/dashboard`, {\n' +
    "      method: force ? 'POST' : 'GET'\n" +
    '    });';
  js = assertReplace(
    js,
    js.replace(fetchBlock, "    const res = await fetch('dashboard.json');"),
    'app.js: redirect dashboard fetch'
  );

  // 6c. Redirect the history fetch
  js = assertReplace(
    js,
    js.replace(
      "fetch(`${BASE}/api/history?days=90`)",
      "fetch('history.json')"
    ),
    'app.js: redirect history fetch'
  );

  fs.writeFileSync(path.join(OUT, 'app.js'), js);

  console.log(`[btc-snapshot] wrote ${OUT}`);
  console.log(`[btc-snapshot] history now has ${lines.length} point(s)`);
}

main().catch((err) => {
  console.error('[btc-snapshot] FAILED:', err);
  process.exit(1);
});
