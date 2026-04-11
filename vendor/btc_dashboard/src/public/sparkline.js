// Tiny SVG sparkline renderer. No dependencies.
// Usage: Sparkline.render(containerEl, [{ts, value}, ...], { color, height })
(function () {
  'use strict';

  const SIGNAL_COLOR = {
    bullish: '#3fb950',
    neutral: '#d29922',
    bearish: '#f85149',
    accent: '#58a6ff'
  };

  function render(target, points, opts = {}) {
    if (!target) return;
    if (!Array.isArray(points) || points.length < 2) {
      target.innerHTML = '';
      return;
    }
    const color = opts.color || SIGNAL_COLOR.accent;
    const width = opts.width || 220;
    const height = opts.height || 30;
    const pad = 2;

    const values = points.map((p) => Number(p.value)).filter((v) => Number.isFinite(v));
    if (values.length < 2) {
      target.innerHTML = '';
      return;
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;

    const step = (width - pad * 2) / (values.length - 1);
    const pts = values.map((v, i) => {
      const x = pad + i * step;
      const y = pad + (1 - (v - min) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    // Area fill (optional translucent)
    const areaPath = `M ${pts[0]} L ${pts.join(' L ')} L ${pad + (values.length - 1) * step},${height - pad} L ${pad},${height - pad} Z`;

    target.innerHTML =
      `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">` +
        `<path d="${areaPath}" fill="${color}" fill-opacity="0.12" />` +
        `<polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" />` +
      `</svg>`;
  }

  // Simple line chart for history: larger, with axis hints.
  function renderHistory(target, points, opts = {}) {
    if (!target) return;
    target.innerHTML = '';
    if (!Array.isArray(points) || points.length < 2) return;

    const width = opts.width || 800;
    const height = opts.height || 120;
    const padX = 30;
    const padY = 15;

    const values = points.map((p) => Number(p.ratio)).filter(Number.isFinite);
    if (values.length < 2) return;

    // Ratio is always 0..1
    const min = 0;
    const max = 1;

    const step = (width - padX * 2) / (values.length - 1);
    const pts = values.map((v, i) => {
      const x = padX + i * step;
      const y = padY + (1 - (v - min) / (max - min)) * (height - padY * 2);
      return { x, y, v };
    });

    const polyline = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

    // Threshold bands: 0.65 green, 0.45 yellow, 0.25 orange
    const yFor = (v) => padY + (1 - v) * (height - padY * 2);

    const dots = pts.map((p, i) => {
      const color = p.v >= 0.65 ? '#3fb950' : p.v >= 0.45 ? '#d29922' : p.v >= 0.25 ? '#db6d28' : '#f85149';
      return `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2.8" fill="${color}" />`;
    }).join('');

    const svg =
      `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" width="100%" height="100%">` +
        // Horizontal grid
        `<line x1="${padX}" y1="${yFor(0.65)}" x2="${width - padX}" y2="${yFor(0.65)}" stroke="#3fb950" stroke-opacity="0.2" stroke-dasharray="3 3" />` +
        `<line x1="${padX}" y1="${yFor(0.45)}" x2="${width - padX}" y2="${yFor(0.45)}" stroke="#d29922" stroke-opacity="0.2" stroke-dasharray="3 3" />` +
        `<line x1="${padX}" y1="${yFor(0.25)}" x2="${width - padX}" y2="${yFor(0.25)}" stroke="#db6d28" stroke-opacity="0.2" stroke-dasharray="3 3" />` +
        // Labels
        `<text x="4" y="${yFor(0.65) + 3}" fill="#8b949e" font-size="10">0.65</text>` +
        `<text x="4" y="${yFor(0.45) + 3}" fill="#8b949e" font-size="10">0.45</text>` +
        `<text x="4" y="${yFor(0.25) + 3}" fill="#8b949e" font-size="10">0.25</text>` +
        `<polyline points="${polyline}" fill="none" stroke="#58a6ff" stroke-width="1.6" stroke-linejoin="round" />` +
        dots +
      `</svg>`;
    target.innerHTML = svg;
  }

  window.Sparkline = { render, renderHistory, SIGNAL_COLOR };
})();
