const test = require('node:test');
const assert = require('node:assert/strict');
const { compute, atr, options, periodLines } = require('../frontend/indicators/smc.js');

function market(n = 1000) {
  let seed = 42, close = 100;
  const random = () => { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 2 ** 32; };
  return Array.from({ length: n }, (_, i) => {
    const open = close;
    close += (random() - 0.5) * 4;
    return { time: 1700000000 + i * 900, open, close, high: Math.max(open, close) + random(), low: Math.min(open, close) - random(), volume: 10 };
  });
}

test('ATR uses an SMA seed followed by Wilder smoothing', () => {
  const bars = [{high: 11, low: 9, close: 10}, {high: 12, low: 9, close: 11}, {high: 14, low: 10, close: 13}, {high: 18, low: 12, close: 15}];
  const values = atr(bars, 3);
  assert(Number.isNaN(values[0]) && Number.isNaN(values[1]));
  assert.equal(values[2], 3);
  assert.equal(values[3], 4);
});

test('future candles do not alter confirmed structure events', () => {
  const bars = market();
  const all = compute(bars).events;
  for (const count of [100, 200, 400, 700]) {
    assert.deepEqual(compute(bars.slice(0, count)).events, all.filter(e => e.index < count));
  }
  assert(all.some(e => e.type === 'BOS'));
  assert(all.some(e => e.type === 'CHoCH'));
  assert(all.some(e => e.type === 'EQH' || e.type === 'EQL'));
});

test('unconfirmed structures roll back when the live candle stops crossing', () => {
  const bars = market();
  const event = compute(bars).events.find(e => e.scope === 'internal' && e.type === 'BOS');
  const live = bars.slice(0, event.index + 1);
  assert(compute(live).events.some(e => e.index === event.index && e.type === event.type));
  live[live.length - 1] = { ...live.at(-1), close: live.at(-2).close };
  assert(!compute(live).events.some(e => e.index === event.index && e.type === event.type && e.scope === event.scope));
});

test('order blocks select a historical candle and obey display limits', () => {
  const bars = market();
  const result = compute(bars, { internalCount: 2, swingBlocks: true, swingCount: 1 });
  assert.equal(result.internalBlocks.length, 2);
  assert(result.swingBlocks.length <= 1);
  for (const block of [...result.internalBlocks, ...result.swingBlocks]) {
    assert(block.from < block.created);
    assert.equal(block.top, bars[block.from].high);
    assert.equal(block.bottom, bars[block.from].low);
  }
});

test('Close mitigation preserves a zone that is broken only by a wick', () => {
  const bars = market();
  let prefix, block;
  for (let n = 200; n < bars.length; n++) {
    const candidate = compute(bars.slice(0, n), { internalCount: 20 }).internalBlocks[0];
    if (candidate?.bias === 1 && bars[n - 1].close > candidate.top) {
      prefix = bars.slice(0, n); block = candidate; break;
    }
  }
  assert(block);
  const previous = prefix.at(-1);
  prefix.push({ ...previous, time: previous.time + 900, open: previous.close, high: previous.close + 0.1, low: block.bottom - 1 });
  const hasZone = cfg => compute(prefix, { internalCount: 20, ...cfg }).internalBlocks.some(b => b.from === block.from && b.created === block.created);
  assert.equal(hasZone({ mitigation: 'High/Low' }), false);
  assert.equal(hasZone({ mitigation: 'Close' }), true);
});

test('FVG detects a three-candle imbalance and deletes it after mitigation', () => {
  const bars = [
    {time:0, open:100, high:101, low:99, close:100},
    {time:60, open:100, high:104, low:100, close:103},
    {time:120, open:104, high:105, low:103, close:104},
  ];
  const cfg = { fvg: true, fvgAuto: false };
  const gap = compute(bars, cfg).boxes.find(b => b.text === 'FVG');
  assert.equal(gap.top, 103);
  assert.equal(gap.bottom, 101);
  bars.push({time:180, open:104, high:104, low:100, close:101});
  assert(!compute(bars, cfg).boxes.some(b => b.text === 'FVG'));
});

test('Present mode retains only the latest drawing per structure direction', () => {
  const bars = market();
  const historical = compute(bars);
  const present = compute(bars, {mode:'Present'});
  const structures = present.lines.filter(l => l.text === 'BOS' || l.text === 'CHoCH');
  assert(structures.length <= 4);
  assert(historical.lines.length > present.lines.length);
});

test('disabled indicator clears all drawings and malformed settings are bounded', () => {
  const result = compute(market(), {enabled:false});
  assert.equal(result.lines.length + result.boxes.length + result.labels.length, 0);
  assert.equal(options({swingLength:-1, internalCount:100}).swingLength, 10);
  assert.equal(options({internalCount:100}).internalCount, 20);
  assert.equal(options({mitigation:'garbage'}).mitigation, 'High/Low');
});

test('previous-period levels use fetched extrema beyond the loaded chart history', () => {
  const bars = market(10);
  const period = {time:bars[0].time-86400, end:bars[0].time, high:150, low:80};
  const lines = periodLines(bars, {daily:period}, options({daily:true}));
  assert.deepEqual(lines.map(l => [l.text,l.price]), [['PDH',150],['PDL',80]]);
  assert(lines[0].from < 0);
});
