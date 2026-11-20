const toast = document.querySelector('#toast');
const tag = document.querySelector('#chart-tag');
const note = document.querySelector('#chart-note');
const legend = document.querySelector('#ohlc-legend');

// Binance spot market-data-only endpoints. No API key is used.
const REST = 'https://data-api.binance.vision';
const SOCKET = 'wss://data-stream.binance.vision/ws';
const SYMBOL = 'BTCUSDT';
// Lightweight Charts renders timestamps as UTC; shifting by +5:30 makes the axis read in IST.
const IST_OFFSET = 19800;
// Each timeframe opens on its latest `count` candles; 4x that is loaded for scrolling back.
const RANGES = {
  '5m': { resolution: '5m', seconds: 300, count: 120 },
  '15m': { resolution: '15m', seconds: 900, count: 120 },
  '1h': { resolution: '1h', seconds: 3600, count: 120 },
  '4h': { resolution: '4h', seconds: 14400, count: 120 },
};
const TIMEFRAME_KEY = 'cryptox.timeframe';
const UP = '#46d39a';
const DOWN = '#f16f82';

let range = RANGES['15m'];
let candles = [];
let socket = null;
let socketRetry = 0;
let socketRetryTimer = null;
let lastUpdate = 0;
let loadToken = 0;

const chart = LightweightCharts.createChart(document.querySelector('#tv-chart'), {
  autoSize: true,
  layout: {
    background: { type: 'solid', color: 'transparent' },
    textColor: '#7d8696',
    fontFamily: "'DM Mono', monospace",
    fontSize: 10,
  },
  grid: { vertLines: { color: '#191e27' }, horzLines: { color: '#191e27' } },
  crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  rightPriceScale: { borderColor: '#222833' },
  timeScale: { borderColor: '#222833', timeVisible: true, secondsVisible: false, rightOffset: 4 },
});
const candleSeries = chart.addCandlestickSeries({
  upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN, borderVisible: false,
  priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
});
candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } });
const volumeSeries = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false });
volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

const SMC_SETTINGS_KEY = 'cryptox.smc.v1';
let smcOptions = SmartMoneyConcepts.options();
try {
  smcOptions = SmartMoneyConcepts.options(JSON.parse(localStorage.getItem(SMC_SETTINGS_KEY) || '{}'));
} catch { /* Use Pine defaults when storage is unavailable or invalid. */ }
const smcOverlay = new SmartMoneyConcepts.Overlay();
candleSeries.attachPrimitive(smcOverlay);
const periodLevels = {};
const periodRequests = new Set();
const periodErrors = new Set();

function renderSMC(repaintCandles = false) {
  const data = SmartMoneyConcepts.compute(candles, smcOptions);
  data.lines.push(...SmartMoneyConcepts.periodLines(candles, periodLevels, smcOptions));
  smcOverlay.setData(data);
  if (repaintCandles || (smcOptions.enabled && smcOptions.colorCandles)) {
    candleSeries.setData(candles.map((bar, i) => ({
      ...toChart(bar),
      ...(smcOptions.enabled && smcOptions.colorCandles ? { color: data.colors[i], wickColor: data.colors[i], borderColor: data.colors[i] } : {}),
    })));
  }
  const status = document.querySelector('#smc-status');
  const missingLevels = ['daily', 'weekly', 'monthly'].filter(key => smcOptions[key] && !periodLevels[key]);
  status.textContent = !smcOptions.enabled ? 'Hidden' : !candles.length ? 'Waiting for candles…'
    : `${data.internalBlocks.length + data.swingBlocks.length} order blocks · ${data.lines.filter(l => l.text === 'BOS' || l.text === 'CHoCH').length} structures`
      + (candles.length < 200 ? ' · ATR warming up' : '')
      + (missingLevels.length ? ` · ${missingLevels.some(key => periodErrors.has(key)) ? 'Previous levels unavailable; retrying' : 'Loading previous levels…'}` : '');
}

async function loadPeriodLevels() {
  if (!smcOptions.enabled) return;
  await Promise.all([['daily', '1d'], ['weekly', '1w'], ['monthly', '1M']].map(async ([key, interval]) => {
    if (!smcOptions[key] || periodRequests.has(key) || (periodLevels[key]?.expiresAt > Date.now() / 1000)) return;
    periodRequests.add(key);
    try {
      const response = await fetch(`${REST}/api/v3/klines?symbol=${SYMBOL}&interval=${interval}&limit=2`);
      const body = await response.json();
      if (!response.ok || !Array.isArray(body) || body.length < 2) throw new Error('Previous period unavailable');
      const previous = body[body.length - 2], current = body[body.length - 1];
      periodLevels[key] = { time: previous[0] / 1000, end: (previous[6] + 1) / 1000, high: Number(previous[2]), low: Number(previous[3]), expiresAt: (current[6] + 1) / 1000 };
      periodErrors.delete(key);
    } catch {
      periodErrors.add(key);
    } finally {
      periodRequests.delete(key);
    }
  }));
  renderSMC();
}

function syncSMCControls() {
  document.querySelector('#smc-enabled').checked = smcOptions.enabled;
  document.querySelectorAll('[data-smc]').forEach(input => {
    if (input.type === 'checkbox') input.checked = smcOptions[input.dataset.smc];
    else input.value = smcOptions[input.dataset.smc];
  });
}

function saveSMCOptions() {
  smcOptions = SmartMoneyConcepts.options(smcOptions);
  try { localStorage.setItem(SMC_SETTINGS_KEY, JSON.stringify(smcOptions)); } catch { /* Optional preference. */ }
  syncSMCControls();
  renderSMC(true);
  loadPeriodLevels();
}

syncSMCControls();
document.querySelector('#smc-enabled').addEventListener('change', event => {
  smcOptions.enabled = event.target.checked;
  saveSMCOptions();
});
document.querySelector('#smc-settings').addEventListener('submit', event => event.preventDefault());
document.querySelector('#smc-settings').addEventListener('change', event => {
  const input = event.target;
  if (!input.dataset.smc) return;
  if (!input.checkValidity()) { input.reportValidity(); return; }
  smcOptions[input.dataset.smc] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
  saveSMCOptions();
});
document.querySelector('#smc-reset').addEventListener('click', () => {
  smcOptions = SmartMoneyConcepts.options();
  saveSMCOptions();
});
document.querySelector('#smc-settings-toggle').addEventListener('click', event => {
  const settings = document.querySelector('#smc-settings');
  settings.hidden = !settings.hidden;
  event.currentTarget.setAttribute('aria-expanded', String(!settings.hidden));
});

const chartPanel = document.querySelector('#markets');
const fullscreenButton = document.querySelector('#chart-fullscreen');
function syncFullscreen() {
  const expanded = document.fullscreenElement === chartPanel || chartPanel.classList.contains('fullscreen-fallback');
  fullscreenButton.setAttribute('aria-pressed', String(expanded));
  fullscreenButton.setAttribute('aria-label', expanded ? 'Exit chart fullscreen' : 'Enter chart fullscreen');
  fullscreenButton.title = expanded ? 'Exit fullscreen (Esc)' : 'Fullscreen chart';
  fullscreenButton.querySelector('span').textContent = expanded ? 'Exit fullscreen' : 'Fullscreen';
  document.body.classList.toggle('chart-expanded', expanded);
  requestAnimationFrame(() => smcOverlay.requestUpdate?.());
}
fullscreenButton.addEventListener('click', async () => {
  if (document.fullscreenElement === chartPanel) {
    await document.exitFullscreen();
  } else if (chartPanel.classList.contains('fullscreen-fallback')) {
    chartPanel.classList.remove('fullscreen-fallback');
  } else {
    try {
      if (!chartPanel.requestFullscreen) throw new Error('Fullscreen API unavailable');
      await chartPanel.requestFullscreen();
    } catch {
      chartPanel.classList.add('fullscreen-fallback');
    }
  }
  syncFullscreen();
});
document.addEventListener('fullscreenchange', syncFullscreen);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && chartPanel.classList.contains('fullscreen-fallback')) {
    chartPanel.classList.remove('fullscreen-fallback');
    syncFullscreen();
    fullscreenButton.focus();
  }
});

const quotePrice = (value, digits = 2) => `${value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })} USDT`;
const toChart = (bar) => ({ time: bar.time + IST_OFFSET, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
const toVolume = (bar) => ({ time: bar.time + IST_OFFSET, value: bar.volume, color: bar.close >= bar.open ? '#46d39a55' : '#f16f8255' });

function timeLabel(seconds) {
  return new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    .format(new Date(seconds * 1000));
}

function setStatus(state, text) {
  tag.className = `live-tag ${state}`;
  tag.lastChild.textContent = { live: 'LIVE', stale: 'DELAYED', down: 'OFFLINE', '': 'CONNECTING' }[state];
  if (text) note.textContent = text;
}

function showLegend(bar) {
  if (!bar) {
    legend.innerHTML = '';
    return;
  }
  const change = ((bar.close - bar.open) / bar.open) * 100;
  const cls = bar.close >= bar.open ? 'up' : 'down';
  legend.innerHTML = `<span>${SYMBOL} · ${range.resolution}</span>`
    + `<span>O <b>${quotePrice(bar.open)}</b></span><span>H <b>${quotePrice(bar.high)}</b></span>`
    + `<span>L <b>${quotePrice(bar.low)}</b></span><span>C <b class="${cls}">${quotePrice(bar.close)}</b></span>`
    + `<span class="${cls}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span>`
    + `<span>Vol <b>${bar.volume.toLocaleString('en-US')} BTC</b></span>`;
}

async function loadCandles(resetView = false) {
  const token = ++loadToken;
  // Seed ATR(200) and swing structure; the view still opens on the latest 120 bars.
  const bars = 1000;
  const url = `${REST}/api/v3/klines?symbol=${SYMBOL}&interval=${range.resolution}&limit=${bars}`;
  try {
    const response = await fetch(url);
    const body = await response.json();
    if (!response.ok || !Array.isArray(body) || !body.length) throw new Error(body.msg || 'no candles returned');
    if (token !== loadToken) return;
    candles = body.map((c) => ({ time: Math.floor(c[0] / 1000), open: Number(c[1]), high: Number(c[2]), low: Number(c[3]), close: Number(c[4]), volume: Number(c[5]) }))
      .sort((a, b) => a.time - b.time);
    candleSeries.setData(candles.map(toChart));
    volumeSeries.setData(candles.map(toVolume));
    renderSMC();
    loadPeriodLevels();
    if (resetView) {
      chart.timeScale().setVisibleLogicalRange({ from: candles.length - range.count, to: candles.length + 3 });
    }
    lastUpdate = Date.now();
    document.querySelector('#chart-resolution').textContent = `${range.resolution} candles`;
    document.querySelector('#last-price').textContent = quotePrice(candles[candles.length - 1].close);
    showLegend(candles[candles.length - 1]);
  } catch (error) {
    if (token !== loadToken) return;
    setStatus('down', `Could not load candles from Binance (${error.message}). Retrying…`);
  }
}

// Buy/sell markers for every paper strategy's trades (ob1h/ob15m/ob5m, manual, OB-rejection).
// Prices and timing come from each strategy's own venue (mostly Delta BTCUSD), plotted here
// against Binance BTCUSDT spot for a single shared timeline; treat marker price as approximate.
const tradeMarkersToggle = document.querySelector('#trade-markers-enabled');
const tradeMarkersStatus = document.querySelector('#trade-markers-status');
let tradeMarkers = [];

function isoToChartTime(iso) {
  return Math.floor(new Date(iso).getTime() / 1000) + IST_OFFSET;
}

function tradeToMarkers(t) {
  const long = t.side === 'long';
  const label = t.strategy_name || t.strategy_id || 'strategy';
  const markers = [{
    time: isoToChartTime(t.entry_time), position: long ? 'belowBar' : 'aboveBar',
    color: long ? UP : DOWN, shape: long ? 'arrowUp' : 'arrowDown',
    text: `${long ? 'BUY' : 'SELL'} · ${label}`,
  }];
  if (t.exit_time) {
    const pnl = [t.ret_pct, t.pnl_pct, t.unrealized_pct].find(Number.isFinite);
    markers.push({
      time: isoToChartTime(t.exit_time), position: long ? 'aboveBar' : 'belowBar',
      color: Number.isFinite(pnl) ? (pnl >= 0 ? UP : DOWN) : '#7d8696', shape: 'circle',
      text: `EXIT · ${label}${Number.isFinite(pnl) ? ` ${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%` : ''}`,
    });
  }
  return markers;
}

function applyTradeMarkers() {
  candleSeries.setMarkers(tradeMarkersToggle.checked ? tradeMarkers : []);
}

async function loadTradeMarkers() {
  try {
    const response = await window.cryptoApiFetch('/api/trades?limit=500');
    if (!response.ok) throw new Error(`status ${response.status}`);
    const { trades } = await response.json();
    tradeMarkers = trades.flatMap(tradeToMarkers).sort((a, b) => a.time - b.time);
    tradeMarkersStatus.textContent = `${trades.length} trade${trades.length === 1 ? '' : 's'} marked`;
    applyTradeMarkers();
  } catch (error) {
    tradeMarkersStatus.textContent = 'Trade markers unavailable';
  }
}
tradeMarkersToggle.addEventListener('change', applyTradeMarkers);
loadTradeMarkers();
window.setInterval(loadTradeMarkers, 30000);

async function loadTicker() {
  try {
    const response = await fetch(`${REST}/api/v3/ticker/24hr?symbol=${SYMBOL}`);
    const t = await response.json();
    if (!response.ok) throw new Error(t.msg || 'ticker request failed');
    const change = Number(t.priceChange);
    const pct = Number(t.priceChangePercent);
    const el = document.querySelector('#day-change');
    el.className = change >= 0 ? 'positive-text' : 'negative-text';
    el.textContent = `${change >= 0 ? '+' : '−'}${quotePrice(Math.abs(change))} (${Math.abs(pct).toFixed(2)}%)`;
    document.querySelector('#day-range').textContent = `· H ${quotePrice(Number(t.highPrice))} · L ${quotePrice(Number(t.lowPrice))}`;
  } catch {
    // The candle feed still works without the 24h stats; try again on the next tick.
  }
}

function connectSocket() {
  window.clearTimeout(socketRetryTimer);
  if (socket) {
    socket.onclose = null;
    socket.onmessage = null;
    socket.close();
  }
  const interval = range.resolution;
  socket = new WebSocket(`${SOCKET}/${SYMBOL.toLowerCase()}@kline_${interval}`);
  socket.onopen = () => {
    socketRetry = 0;
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.e !== 'kline' || message.s !== SYMBOL || message.k?.i !== range.resolution || !candles.length) return;
    const k = message.k;
    const bar = { time: Math.floor(k.t / 1000), open: Number(k.o), high: Number(k.h), low: Number(k.l), close: Number(k.c), volume: Number(k.v) };
    const last = candles[candles.length - 1];
    if (bar.time < last.time) return;
    if (bar.time === last.time) candles[candles.length - 1] = bar;
    else candles.push(bar);
    candleSeries.update(toChart(bar));
    volumeSeries.update(toVolume(bar));
    renderSMC();
    lastUpdate = Date.now();
    document.querySelector('#last-price').textContent = quotePrice(bar.close);
    if (!legend.dataset.hovering) showLegend(bar);
  };
  socket.onclose = () => {
    // Reconnect with backoff; REST polling below keeps the chart moving meanwhile.
    socketRetry = Math.min(socketRetry + 1, 6);
    socketRetryTimer = window.setTimeout(connectSocket, 1000 * 2 ** socketRetry);
  };
}

function refreshStatus() {
  const age = (Date.now() - lastUpdate) / 1000;
  if (!lastUpdate) return;
  if (socket?.readyState === WebSocket.OPEN && age < 90) setStatus('live', `Live · Binance BTCUSDT spot · updated ${timeLabel(lastUpdate / 1000)} IST`);
  else if (age < 300) setStatus('stale', `Reconnecting · last update ${timeLabel(lastUpdate / 1000)} IST`);
  else setStatus('down', 'Feed offline · retrying');
}

function selectRange(name) {
  range = RANGES[name];
  try {
    localStorage.setItem(TIMEFRAME_KEY, name);
  } catch {
    // Remembering the timeframe is a convenience; private windows may block storage.
  }
  candles = [];
  lastUpdate = 0;
  setStatus('', 'Connecting to Binance BTCUSDT feed…');
  candleSeries.setData([]);
  volumeSeries.setData([]);
  renderSMC();
  document.querySelectorAll('.range-tabs button').forEach((button) => button.classList.toggle('selected', button.dataset.range === name));
  loadCandles(true);
  connectSocket();
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 2600);
}

chart.subscribeCrosshairMove((param) => {
  const point = param.time ? candles.find((c) => c.time + IST_OFFSET === param.time) : null;
  if (point) {
    legend.dataset.hovering = '1';
    showLegend(point);
  } else {
    delete legend.dataset.hovering;
    showLegend(candles[candles.length - 1]);
  }
});
document.querySelectorAll('.range-tabs button').forEach((button) => button.addEventListener('click', () => selectRange(button.dataset.range)));
document.querySelector('#refresh').addEventListener('click', () => {
  loadCandles();
  loadTicker();
  showToast('Reloaded BTCUSDT candles from Binance.');
});

let savedTimeframe = null;
try {
  savedTimeframe = localStorage.getItem(TIMEFRAME_KEY);
} catch {
  savedTimeframe = null;
}
selectRange(RANGES[savedTimeframe] ? savedTimeframe : '15m');
loadTicker();
window.setInterval(loadTicker, 30000);
window.setInterval(loadPeriodLevels, 60000);
window.setInterval(refreshStatus, 2000);
// REST fallback: if the socket has gone quiet, re-pull candles so the chart never freezes.
window.setInterval(() => {
  if (Date.now() - lastUpdate > 60000) loadCandles();
}, 30000);
