'use strict';

const fs = require('fs');
const path = require('path');

const HISTORY_FILE = path.join(__dirname, '..', 'data', 'history.jsonl');
const DEDUP_WINDOW_MS = 60 * 60 * 1000; // 1 hour

function ensureDir() {
  const dir = path.dirname(HISTORY_FILE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function readAllLines() {
  if (!fs.existsSync(HISTORY_FILE)) return [];
  const raw = fs.readFileSync(HISTORY_FILE, 'utf8');
  if (!raw.trim()) return [];
  return raw.split('\n').filter((line) => line.trim().length > 0);
}

function parseLine(line) {
  try {
    return JSON.parse(line);
  } catch (_) {
    return null;
  }
}

async function appendHistory(entry) {
  ensureDir();
  const lines = readAllLines();

  // Dedup: if the previous entry is within DEDUP_WINDOW_MS, replace it.
  if (lines.length > 0) {
    const last = parseLine(lines[lines.length - 1]);
    if (last && last.ts) {
      const age = new Date(entry.ts).getTime() - new Date(last.ts).getTime();
      if (age >= 0 && age < DEDUP_WINDOW_MS) {
        lines[lines.length - 1] = JSON.stringify(entry);
        fs.writeFileSync(HISTORY_FILE, lines.join('\n') + '\n');
        return;
      }
    }
  }

  fs.appendFileSync(HISTORY_FILE, JSON.stringify(entry) + '\n');
}

async function readHistory({ days = 90 } = {}) {
  const lines = readAllLines();
  if (lines.length === 0) return [];
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return lines
    .map(parseLine)
    .filter((e) => e && e.ts && new Date(e.ts).getTime() >= cutoff)
    .map((e) => ({
      ts: e.ts,
      ratio: e.ratio,
      bullish: e.bullish,
      available: e.available
    }));
}

module.exports = { appendHistory, readHistory };
