'use strict';

const BASE = window.API_BASE ?? '';

const refreshBtn = document.getElementById('refreshBtn');
const verdictEl = document.getElementById('verdict');
const verdictScore = document.getElementById('verdictScore');
const verdictLabel = document.getElementById('verdictLabel');
const verdictAlerts = document.getElementById('verdictAlerts');
const verdictUpdated = document.getElementById('verdictUpdated');
const btcPriceEl = document.getElementById('btcPrice');
const historyBox = document.getElementById('historyChartBox');
const historyChart = document.getElementById('historyChart');

const tierEls = {
  t1: document.getElementById('tier1'),
  t2: document.getElementById('tier2'),
  t3: document.getElementById('tier3')
};

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtNumber(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${Number(n).toFixed(digits)}`;
}

function fmtPrice(meta) {
  if (!meta) return '—';
  const usd = meta.usd ? `$${Math.round(meta.usd).toLocaleString('en-US')}` : '—';
  const eur = meta.eur ? `(€${Math.round(meta.eur).toLocaleString('en-US')})` : '';
  const c24 = meta.change_24h != null ? fmtNumber(meta.change_24h, 1) + '%' : '—';
  const c7 = meta.change_7d != null ? fmtNumber(meta.change_7d, 1) + '%' : '—';
  const cls24 = meta.change_24h > 0 ? 'up' : meta.change_24h < 0 ? 'down' : '';
  const cls7 = meta.change_7d > 0 ? 'up' : meta.change_7d < 0 ? 'down' : '';
  return `<strong>BTC: ${usd}</strong> ${eur} · 24h: <span class="${cls24}">${c24}</span> · 7d: <span class="${cls7}">${c7}</span>`;
}

function cardHtml(ind) {
  const state = ind.state || 'no_data';
  const signal = ind.signal || 'neutral';
  const marker =
    state === 'broken_scraper'
      ? '<span class="broken-badge"></span>'
      : state === 'no_data'
      ? '<span class="dot no_data"></span>'
      : `<span class="dot ${signal}"></span>`;

  const updated = ind.source_updated ? escapeHtml(ind.source_updated) : '—';
  const source = ind.source ? escapeHtml(ind.source) : '—';
  const eduHtml = ind.education
    ? `<details class="card__edu">
         <summary>Why this matters</summary>
         <p><strong>What is it?</strong> ${escapeHtml(ind.education.what)}</p>
         <p><strong>Why it matters for BTC:</strong> ${escapeHtml(ind.education.why)}</p>
       </details>`
    : '';

  return `
    <article class="card state-${state}" data-id="${ind.id}">
      <div class="card__head">
        <div class="card__name">${marker}${escapeHtml(ind.name)}</div>
        <div class="card__value">${escapeHtml(ind.display_value || '—')}</div>
      </div>
      <div class="card__context">${escapeHtml(ind.context || '')}</div>
      <div class="card__spark" data-spark></div>
      <div class="card__meta">${source} · ${updated}</div>
      ${eduHtml}
    </article>
  `;
}

function renderTier(tierKey, indicators) {
  const host = tierEls[tierKey];
  if (!host) return;
  host.innerHTML = indicators.map(cardHtml).join('');
  indicators.forEach((ind) => {
    const cardEl = host.querySelector(`.card[data-id="${ind.id}"]`);
    if (!cardEl) return;
    const sparkEl = cardEl.querySelector('[data-spark]');
    const color = Sparkline.SIGNAL_COLOR[ind.signal] || Sparkline.SIGNAL_COLOR.accent;
    Sparkline.render(sparkEl, ind.history || [], { color });
  });
}

function renderVerdict(score, alerts, updatedAt) {
  const colorClass = `verdict--${score.color || 'gray'}`;
  verdictEl.className = `verdict ${colorClass}`;
  verdictScore.textContent = `${score.bullish} / ${score.available}`;
  verdictLabel.textContent = score.verdict || '';
  if (alerts && alerts.length) {
    verdictAlerts.innerHTML = `⚠ ${alerts.length} scraper(s) broken: ${alerts.map(escapeHtml).join(' · ')}`;
  } else {
    verdictAlerts.innerHTML = '';
  }
  verdictUpdated.textContent = `Updated: ${new Date(updatedAt).toLocaleString('en-US')}`;
}

async function loadHistory() {
  try {
    const res = await fetch(`${BASE}/api/history?days=90`);
    if (!res.ok) return;
    const { points } = await res.json();
    if (!Array.isArray(points) || points.length < 7) {
      historyBox.hidden = true;
      return;
    }
    historyBox.hidden = false;
    Sparkline.renderHistory(historyChart, points);
  } catch (err) {
    console.warn('history load failed', err);
    historyBox.hidden = true;
  }
}

async function load(force = false) {
  refreshBtn.disabled = true;
  refreshBtn.textContent = 'Loading…';
  try {
    const res = await fetch(force ? `${BASE}/api/refresh` : `${BASE}/api/dashboard`, {
      method: force ? 'POST' : 'GET'
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    btcPriceEl.innerHTML = fmtPrice(data.btc_price);
    renderVerdict(data.score, data.alerts, data.updated_at);
    renderTier('t1', data.tiers.t1);
    renderTier('t2', data.tiers.t2);
    renderTier('t3', data.tiers.t3);
    await loadHistory();
  } catch (err) {
    console.error(err);
    verdictLabel.textContent = `Failed to load: ${err.message}`;
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = 'Refresh';
  }
}

refreshBtn.addEventListener('click', () => load(true));
load(false);
