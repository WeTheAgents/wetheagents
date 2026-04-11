'use strict';

const { fetchFredSeries, nowIso, toSparkline } = require('./_util');

const SOURCE = 'FRED (CPIAUCSL)';

// CPI YoY calculation: take the level 12 months ago vs current.
// Bullish: YoY is falling for 2+ consecutive months (disinflation).
// Bearish: YoY is rising for 2+ consecutive months (reinflation).
function yoySeries(series) {
  // series entries are monthly levels.
  const yoy = [];
  for (let i = 12; i < series.length; i++) {
    const cur = series[i];
    const prev = series[i - 12];
    if (!cur || !prev || prev.value === 0) continue;
    const value = ((cur.value - prev.value) / prev.value) * 100;
    yoy.push({ date: cur.date, value });
  }
  return yoy;
}

async function fetchCpi() {
  const series = await fetchFredSeries('CPIAUCSL', { from: '2022-01-01' });
  if (series.length < 15) throw new Error('FRED CPIAUCSL: not enough data');

  const yoy = yoySeries(series);
  if (yoy.length < 3) throw new Error('CPI: not enough YoY data');

  const latest = yoy[yoy.length - 1];
  const prev1 = yoy[yoy.length - 2];
  const prev2 = yoy[yoy.length - 3];

  const fallingStreak = latest.value < prev1.value && prev1.value < prev2.value;
  const risingStreak = latest.value > prev1.value && prev1.value > prev2.value;

  let signal;
  if (fallingStreak) signal = 'bullish';
  else if (risingStreak) signal = 'bearish';
  else signal = 'neutral';

  const displayValue = `${latest.value.toFixed(1)}% YoY`;

  const contextMap = {
    bullish: `CPI ${latest.value.toFixed(1)}% (${prev2.value.toFixed(1)} → ${prev1.value.toFixed(1)} → ${latest.value.toFixed(1)}). Дезинфляция 2+ мес, путь к смягчению ФРС.`,
    bearish: `CPI ${latest.value.toFixed(1)}% (${prev2.value.toFixed(1)} → ${prev1.value.toFixed(1)} → ${latest.value.toFixed(1)}). Реинфляция — снижает вероятность смягчения.`,
    neutral: `CPI ${latest.value.toFixed(1)}%. Без чёткого тренда.`
  };

  return {
    value: latest.value,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(yoy, 12),
    source: SOURCE,
    source_updated: latest.date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchCpi, SOURCE };
