/*
 * Smart Money Concepts — JavaScript adaptation of the supplied LuxAlgo Pine v5 indicator.
 * Original © LuxAlgo. Adaptation licensed CC BY-NC-SA 4.0 (non-commercial, share-alike).
 * https://creativecommons.org/licenses/by-nc-sa/4.0/
 * Source: ./luxalgo-smc.pine. Recomputed from loaded candles on every live update so that
 * an unconfirmed candle's structures roll back when its price changes, as Pine does.
 */
(function (root) {
  'use strict';
  const defaults = Object.freeze({
    enabled: true, mode: 'Historical', style: 'Colored', colorCandles: false,
    internal: true, swing: true, internalBull: 'All', internalBear: 'All',
    swingBull: 'All', swingBear: 'All', confluence: false,
    swingPoints: false, swingLength: 50, strongWeak: true,
    internalBlocks: true, internalCount: 5, swingBlocks: false, swingCount: 5,
    blockFilter: 'Atr', mitigation: 'High/Low', equal: true, equalLength: 3,
    equalThreshold: 0.1, fvg: false, fvgAuto: true, fvgExtend: 1,
    daily: false, weekly: false, monthly: false, zones: false,
  });
  const isNumber = Number.isFinite;
  const pivot = () => ({ level: NaN, last: NaN, index: 0, crossed: false });
  const structure = () => ({ leg: 0, high: pivot(), low: pivot(), bias: 0, blocks: [] });

  function options(values = {}) {
    const out = { ...defaults };
    for (const [key, value] of Object.entries(values)) {
      if (!(key in defaults)) continue;
      if (typeof defaults[key] === 'boolean') out[key] = typeof value === 'boolean' ? value : defaults[key];
      else out[key] = value;
    }
    for (const [key, min, max] of [['swingLength', 10, 200], ['internalCount', 1, 20], ['swingCount', 1, 20], ['equalLength', 1, 50], ['fvgExtend', 0, 100]]) {
      out[key] = isNumber(Number(out[key])) ? Math.max(min, Math.min(max, Math.round(Number(out[key])))) : defaults[key];
    }
    out.equalThreshold = isNumber(Number(out.equalThreshold)) ? Math.max(0, Math.min(0.5, Number(out.equalThreshold))) : defaults.equalThreshold;
    for (const [key, choices] of Object.entries({mode: ['Historical', 'Present'], style: ['Colored', 'Monochrome'], blockFilter: ['Atr', 'Cumulative Mean Range'], mitigation: ['High/Low', 'Close'], internalBull: ['All', 'BOS', 'CHoCH'], internalBear: ['All', 'BOS', 'CHoCH'], swingBull: ['All', 'BOS', 'CHoCH'], swingBear: ['All', 'BOS', 'CHoCH']})) {
      if (!choices.includes(out[key])) out[key] = defaults[key];
    }
    return out;
  }

  function atr(bars, length = 200) {
    let seed = 0, average = NaN;
    return bars.map((bar, i) => {
      const previous = i ? bars[i - 1].close : bar.close;
      const tr = Math.max(bar.high - bar.low, Math.abs(bar.high - previous), Math.abs(bar.low - previous));
      if (i < length) seed += tr;
      if (i === length - 1) average = seed / length;
      else if (i >= length) average = (average * (length - 1) + tr) / length;
      return average;
    });
  }

  function compute(bars, values = {}) {
    const cfg = options(values);
    const result = { lines: [], labels: [], boxes: [], colors: [], events: [], internalBlocks: [], swingBlocks: [], bias: 0 };
    if (!bars.length || !cfg.enabled) return result;
    const bull = cfg.style === 'Monochrome' ? '#b2b5be' : '#089981';
    const bear = cfg.style === 'Monochrome' ? '#5d606b' : '#f23645';
    const color = bias => bias === 1 ? bull : bear;
    const internal = structure(), swing = structure(), equal = structure();
    const trailing = { top: NaN, bottom: NaN, topIndex: 0, bottomIndex: 0, index: 0 };
    const averages = atr(bars);
    const highs = [], lows = [], gaps = [];
    let trSum = 0, deltaSum = 0, trailingDisplay = null, trailingBias = 0;
    const add = (collection, item, key) => {
      if (cfg.mode === 'Present' && key) {
        const previous = collection.findIndex(x => x.key === key);
        if (previous >= 0) collection.splice(previous, 1);
      }
      collection.push({ ...item, key });
      if (collection.length > 500) collection.shift();
    };
    const event = (i, type, bias, scope) => {
      result.events.push({ time: bars[i].time, index: i, type, bias, scope });
    };
    const updatePivot = (state, length, i, kind) => {
      if (i < length) return;
      const p = i - length;
      let highest = -Infinity, lowest = Infinity;
      for (let j = p + 1; j <= i; j++) {
        highest = Math.max(highest, bars[j].high);
        lowest = Math.min(lowest, bars[j].low);
      }
      const next = bars[p].high > highest ? 0 : bars[p].low < lowest ? 1 : state.leg;
      if (next === state.leg) return;
      state.leg = next;
      const isLow = next === 1;
      const pv = isLow ? state.low : state.high;
      const level = isLow ? bars[p].low : bars[p].high;
      if (kind === 'equal' && Math.abs(pv.level - level) < cfg.equalThreshold * averages[i]) {
        const text = isLow ? 'EQL' : 'EQH';
        add(result.lines, { from: pv.index, to: p, price: pv.level, endPrice: level, text, color: color(isLow ? 1 : -1), dash: [2, 3], above: !isLow }, text);
        event(i, text, isLow ? 1 : -1, 'equal');
      }
      pv.last = pv.level;
      pv.level = level;
      pv.index = p;
      pv.crossed = false;
      if (kind === 'swing') {
        if (isLow) { trailing.bottom = level; trailing.bottomIndex = p; }
        else { trailing.top = level; trailing.topIndex = p; }
        trailing.index = p;
        if (cfg.swingPoints) {
          const text = isLow ? (level < pv.last ? 'LL' : 'HL') : (level > pv.last ? 'HH' : 'LH');
          add(result.labels, { index: p, price: level, text, color: color(isLow ? 1 : -1), above: !isLow }, isLow ? 'swingLow' : 'swingHigh');
        }
      }
    };
    const displayStructure = (state, prior, i, isInternal) => {
      if (!i) return;
      const b = bars[i], prev = bars[i - 1];
      const scope = isInternal ? 'internal' : 'swing';
      for (const bias of [1, -1]) {
        const pv = bias === 1 ? state.high : state.low;
        const previousLevel = bias === 1 ? prior.high : prior.low;
        const crosses = bias === 1 ? b.close > pv.level && prev.close <= previousLevel : b.close < pv.level && prev.close >= previousLevel;
        const swingLevel = bias === 1 ? swing.high.level : swing.low.level;
        // Preserve the supplied Pine expression, including open - low inside math.min.
        const upperWick = b.high - Math.max(b.close, b.open);
        const confluence = bias === 1 ? upperWick > Math.min(b.close, b.open - b.low) : upperWick < Math.min(b.close, b.open - b.low);
        if (!crosses || pv.crossed || (isInternal && (!isNumber(swingLevel) || pv.level === swingLevel || (cfg.confluence && !confluence)))) continue;
        const text = state.bias === -bias ? 'CHoCH' : 'BOS';
        pv.crossed = true;
        state.bias = bias;
        event(i, text, bias, scope);
        const filter = cfg[`${scope}${bias === 1 ? 'Bull' : 'Bear'}`];
        if (cfg[scope] && (filter === 'All' || filter === text)) {
          add(result.lines, { from: pv.index, to: i, price: pv.level, text, color: color(bias), dash: isInternal ? [4, 3] : [], above: bias === 1, small: isInternal }, `${scope}-${bias}`);
        }
        if (cfg[`${scope}Blocks`]) {
          let selected = pv.index;
          for (let j = pv.index + 1; j < i; j++) {
            if (bias === 1 ? lows[j] < lows[selected] : highs[j] > highs[selected]) selected = j;
          }
          state.blocks.unshift({ from: selected, top: highs[selected], bottom: lows[selected], bias, created: i, scope });
          if (state.blocks.length > 100) state.blocks.pop();
        }
      }
    };
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i], prev = bars[i - 1];
      const tr = Math.max(b.high - b.low, prev ? Math.abs(b.high - prev.close) : 0, prev ? Math.abs(b.low - prev.close) : 0);
      trSum += tr;
      const volatility = cfg.blockFilter === 'Atr' ? averages[i] : trSum / i;
      const volatile = b.high - b.low >= 2 * volatility;
      highs.push(volatile ? b.low : b.high);
      lows.push(volatile ? b.high : b.low);
      // Pine paints using the trend from before this bar's structure evaluation.
      result.colors.push(color(internal.bias));
      if (cfg.strongWeak || cfg.zones) {
        trailing.top = Math.max(b.high, trailing.top);
        trailing.bottom = Math.min(b.low, trailing.bottom);
        if (trailing.top === b.high) trailing.topIndex = i;
        if (trailing.bottom === b.low) trailing.bottomIndex = i;
        trailingDisplay = { ...trailing };
        trailingBias = swing.bias;
      }
      const priorInternal = { high: internal.high.level, low: internal.low.level };
      const priorSwing = { high: swing.high.level, low: swing.low.level };
      updatePivot(swing, cfg.swingLength, i, 'swing');
      updatePivot(internal, 5, i, 'internal');
      if (cfg.equal) updatePivot(equal, cfg.equalLength, i, 'equal');
      if (cfg.internal || cfg.internalBlocks || cfg.colorCandles) displayStructure(internal, priorInternal, i, true);
      if (cfg.swing || cfg.swingBlocks || cfg.strongWeak) displayStructure(swing, priorSwing, i, false);
      for (const state of [internal, swing]) {
        // Pine iterates/removes forward; preserve its removal order.
        for (let j = 0; j < state.blocks.length; j++) {
          const block = state.blocks[j];
          const broken = block.bias === 1 ? (cfg.mitigation === 'Close' ? b.close : b.low) < block.bottom : (cfg.mitigation === 'Close' ? b.close : b.high) > block.top;
          if (broken) {
            event(i, 'OB breakout', block.bias, block.scope);
            state.blocks.splice(j, 1);
          }
        }
      }
      if (cfg.fvg) {
        for (let j = 0; j < gaps.length; j++) {
          const gap = gaps[j];
          if (gap.bias === 1 ? b.low < gap.bottom : b.high > gap.top) gaps.splice(j, 1);
        }
        const delta = prev ? (prev.close - prev.open) / (prev.open * 100) : NaN;
        if (isNumber(delta)) deltaSum += Math.abs(delta);
        if (i >= 2) {
          const threshold = cfg.fvgAuto ? deltaSum / i * 2 : 0;
          const earlier = bars[i - 2];
          const bias = b.low > earlier.high && prev.close > earlier.high && delta > threshold ? 1 : b.high < earlier.low && prev.close < earlier.low && -delta > threshold ? -1 : 0;
          if (bias) {
            gaps.unshift({ from: i - 1, to: i + cfg.fvgExtend, top: bias === 1 ? b.low : b.high, bottom: bias === 1 ? earlier.high : earlier.low, bias, text: 'FVG', color: cfg.style === 'Monochrome' ? color(bias) : bias === 1 ? '#00ff68' : '#ff0008' });
            event(i, 'FVG', bias, 'gap');
          }
          if (gaps.length > 250) gaps.pop();
        }
      }
    }
    result.internalBlocks = internal.blocks.slice(0, cfg.internalCount);
    result.swingBlocks = swing.blocks.slice(0, cfg.swingCount);
    result.bias = internal.bias;
    for (const block of [...result.internalBlocks, ...result.swingBlocks]) {
      const c = cfg.style === 'Monochrome' ? color(block.bias) : block.scope === 'internal' ? (block.bias === 1 ? '#3179f5' : '#f77c80') : (block.bias === 1 ? '#1848cc' : '#b22833');
      result.boxes.push({ ...block, to: Infinity, color: c, text: `${block.scope === 'internal' ? 'i' : 's'}OB`, border: block.scope === 'swing' });
    }
    result.boxes.push(...gaps.map(g => ({ ...g, border: true, midline: true })));
    const last = bars.length - 1;
    if (trailingDisplay) {
      const t = trailingDisplay;
      if (cfg.strongWeak) {
        if (isNumber(t.top)) result.lines.push({ from: t.topIndex, to: last + 20, price: t.top, text: trailingBias === -1 ? 'Strong High' : 'Weak High', color: bear, edge: true, above: true });
        if (isNumber(t.bottom)) result.lines.push({ from: t.bottomIndex, to: last + 20, price: t.bottom, text: trailingBias === 1 ? 'Strong Low' : 'Weak Low', color: bull, edge: true, above: false });
      }
      if (cfg.zones && isNumber(t.top) && isNumber(t.bottom)) {
        result.boxes.unshift(
          { from: t.index, to: last, top: t.top, bottom: 0.95*t.top + 0.05*t.bottom, color: bear, text: 'Premium' },
          { from: t.index, to: last, top: 0.525*t.top + 0.475*t.bottom, bottom: 0.525*t.bottom + 0.475*t.top, color: '#878b94', text: 'Equilibrium' },
          { from: t.index, to: last, top: 0.95*t.bottom + 0.05*t.top, bottom: t.bottom, color: bull, text: 'Discount' },
        );
      }
    }
    return result;
  }

  // Previous D/W/M candles are fetched independently: a 5m chart need not contain a full month.
  function periodLines(bars, periods, cfg) {
    if (!bars.length || !cfg.enabled) return [];
    const lines = [], last = bars.length - 1, step = bars.length > 1 ? bars[1].time - bars[0].time : 60;
    for (const [key, label] of [['daily', 'D'], ['weekly', 'W'], ['monthly', 'M']]) {
      if (!cfg[key] || !periods[key]) continue;
      const period = periods[key];
      const within = bars.map((b, index) => ({ ...b, index })).filter(b => b.time >= period.time && b.time < period.end);
      for (const [field, suffix] of [['high', 'H'], ['low', 'L']]) {
        const exact = within.find(b => Math.abs(b[field] - period[field]) < 1e-8);
        const from = exact ? exact.index : Math.min(0, (period.time - bars[0].time) / step);
        lines.push({ from, to: last + 20, price: period[field], text: `P${label}${suffix}`, color: '#6292ff', dash: [], edge: true, above: suffix === 'H' });
      }
    }
    return lines;
  }

  class Overlay {
    constructor() {
      this.data = { boxes: [], lines: [], labels: [] };
      this.views = [
        { zOrder: () => 'bottom', renderer: () => ({ draw: target => this.draw(target, true) }) },
        { zOrder: () => 'normal', renderer: () => ({ draw: target => this.draw(target, false) }) },
      ];
    }
    attached({chart, series, requestUpdate}) { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; }
    detached() { this.requestUpdate = null; this.chart = null; this.series = null; }
    paneViews() { return this.views; }
    updateAllViews() {}
    setData(data) { this.data = data; this.requestUpdate?.(); }
    draw(target, background) {
      if (!this.chart || !this.series) return;
      target.useMediaCoordinateSpace(({context: ctx, mediaSize: size}) => {
        const x = index => index === Infinity ? size.width : this.chart.timeScale().logicalToCoordinate(index);
        const y = price => this.series.priceToCoordinate(price);
        ctx.save();
        ctx.beginPath(); ctx.rect(0, 0, size.width, size.height); ctx.clip();
        const label = (text, px, py, color, above = true, align = 'center', small = false) => {
          if (![px, py].every(isNumber) || py < -20 || py > size.height + 20) return;
          ctx.font = `${small ? 9 : 10}px sans-serif`;
          const width = ctx.measureText(text).width;
          const left = Math.max(3, Math.min(size.width - width - 3, align === 'right' ? px - width : px - width / 2));
          const top = py + (above ? -15 : 3);
          ctx.fillStyle = '#11151cdd'; ctx.fillRect(left - 2, top, width + 4, 13);
          ctx.fillStyle = color; ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText(text, left, top + 1);
        };
        if (background) {
          for (const box of this.data.boxes) {
            const left = x(box.from), right = x(box.to), top = y(box.top), bottom = y(box.bottom);
            if (![left, right, top, bottom].every(isNumber) || right < 0 || left > size.width) continue;
            const l = Math.max(0, left), r = Math.min(size.width, right), t = Math.max(0, Math.min(top, bottom)), b = Math.min(size.height, Math.max(top, bottom));
            if (b < t) continue;
            ctx.fillStyle = box.color + '33'; ctx.fillRect(l, t, r - l, Math.max(1, b - t));
            ctx.strokeStyle = box.color + '88'; ctx.lineWidth = 1; ctx.setLineDash([]);
            if (box.border) ctx.strokeRect(l, t, r - l, b - t);
            if (box.midline) { ctx.beginPath(); ctx.moveTo(l, (top + bottom)/2); ctx.lineTo(r, (top + bottom)/2); ctx.stroke(); }
          }
        } else {
          for (const box of this.data.boxes) {
            const left = x(box.from), right = x(box.to), top = y(Math.max(box.top, box.bottom));
            if (![left, right, top].every(isNumber) || right < 0 || left > size.width || right - left < 28) continue;
            label(box.text, Math.min(size.width - 5, right - 5), top, box.color, false, 'right', true);
          }
          for (const line of this.data.lines) {
            const left = x(line.from), right = x(line.to), price = y(line.price), end = y(line.endPrice ?? line.price);
            if (![left, right, price, end].every(isNumber) || right < 0 || left > size.width) continue;
            ctx.strokeStyle = line.color; ctx.lineWidth = 1; ctx.setLineDash(line.dash || []);
            ctx.beginPath(); ctx.moveTo(left, price); ctx.lineTo(right, end); ctx.stroke();
            label(line.text, line.edge ? Math.min(right, size.width - 5) : (left + right)/2, end, line.color, line.above, line.edge ? 'right' : 'center', line.small);
          }
          for (const item of this.data.labels) {
            const px = x(item.index);
            if (px !== null && px >= 0 && px <= size.width) label(item.text, px, y(item.price), item.color, item.above);
          }
        }
        ctx.restore();
      });
    }
  }
  const api = { defaults, options, atr, compute, periodLines, Overlay };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SmartMoneyConcepts = api;
})(typeof window !== 'undefined' ? window : globalThis);
