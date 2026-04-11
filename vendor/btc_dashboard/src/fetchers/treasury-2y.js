'use strict';

const { fetchFredSeries, nowIso, toSparkline } = require('./_util');

const SOURCE = 'FRED (DGS2, DFF)';

async function fetchTreasury2y() {
  const [dgs2, dff] = await Promise.all([
    fetchFredSeries('DGS2', { from: '2024-01-01' }),
    fetchFredSeries('DFF', { from: '2024-01-01' })
  ]);

  if (dgs2.length < 10) throw new Error('FRED DGS2: not enough data');

  const latest2y = dgs2[dgs2.length - 1];
  const month1Ago = dgs2[dgs2.length - 22] || dgs2[0]; // ~22 trading days
  const latestFF = dff.length ? dff[dff.length - 1].value : null;

  const change30d = latest2y.value - month1Ago.value; // in percentage points
  const belowFF = latestFF != null && latest2y.value < latestFF;

  let signal;
  if (belowFF || change30d < -0.1) signal = 'bullish';
  else if (!belowFF && change30d > 0.1) signal = 'bearish';
  else signal = 'neutral';

  const displayValue = `${latest2y.value.toFixed(2)}%`;

  const contextMap = {
    bullish: `2Y доходность ${latest2y.value.toFixed(2)}%, ${change30d >= 0 ? '+' : ''}${change30d.toFixed(2)}pp за 30д. ${
      belowFF ? `Ниже Fed Funds (${latestFF.toFixed(2)}%) — рынок закладывает снижение ставки.` : 'Снижается — ожидания смягчения.'
    }`,
    bearish: `2Y доходность ${latest2y.value.toFixed(2)}%, ${change30d >= 0 ? '+' : ''}${change30d.toFixed(2)}pp за 30д. Выше Fed Funds и растёт — ожидания ужесточения.`,
    neutral: `2Y доходность ${latest2y.value.toFixed(2)}%. Без чёткого сдвига ожиданий.`
  };

  return {
    value: latest2y.value,
    display_value: displayValue,
    signal,
    state: 'ok',
    context: contextMap[signal],
    history: toSparkline(dgs2, 30),
    source: SOURCE,
    source_updated: latest2y.date,
    fetched_at: nowIso()
  };
}

module.exports = { fetch: fetchTreasury2y, SOURCE };
