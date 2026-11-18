// Order-block mitigation paper strategies (1h / 15m / 5m): renders /api/ob/{tf} (see src/execution/ob1h_engine.py).
// The timeframe tabs switch which engine's account, position and watchlist are shown.
// Loaded after app.js and reuses its `candleSeries` to draw the open position's levels on the chart.
(() => {
  const $ = (id) => document.querySelector(`#${id}`);
  const chips = [$('ob1h-chip')];
  const usd = (v, d = 2) => `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  const signed = (v, d = 2) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
  const px = (v) => Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const ist = (iso, withDate = true) => {
    const d = new Date(iso);
    const t = d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
    return withDate ? `${d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' })} ${t}` : t;
  };
  const held = (h) => (h < 1 ? `${Math.round(h * 60)}m` : h < 48 ? `${h.toFixed(1)}h` : `${(h / 24).toFixed(1)}d`);
  const sideClass = (side) => (side === 'long' ? 'buy' : 'sell');
  const cls = (v) => (v >= 0 ? 'positive-text' : 'negative-text');
  const reasonText = { initial_stop: 'Initial stop hit', trailing_stop: 'Trailing stop hit' };
  const TFS = ['1h', '15m', '5m'];
  let tf = '1h';
  try { if (TFS.includes(localStorage.getItem('ob-tf'))) tf = localStorage.getItem('ob-tf'); } catch { /* storage unavailable */ }
  let loadSeq = 0;

  function setChip(state, text) {
    chips.forEach((chip) => {
      chip.className = `live-tag ${state}`;
      chip.lastChild.textContent = text;
    });
  }

  function renderStats(d) {
    const a = d.account;
    const s = d.stats;
    const p = d.position;
    // Metrics strip in the strategy section
    $('ob1h-r').textContent = s.trades ? `${signed(s.avg_r)}R` : '—';
    $('ob1h-pf').textContent = s.profit_factor === null ? '—' : s.profit_factor.toFixed(2);
    $('ob1h-dd').textContent = `${s.max_drawdown_pct.toFixed(1)}%`;
    $('ob1h-fees').textContent = usd(s.fees);
    $('ob1h-hold').textContent = s.trades ? held(s.avg_hold_hours) : '—';
    $('ob1h-ls').textContent = `${s.long_trades} / ${s.short_trades}`;
    $('ob1h-n').textContent = `${s.trades} (${s.wins}W · ${s.losses}L)`;
  }

  function ladder(p) {
    const levels = [
      ['e-stop', 'SL', p.stop], ['e-init', 'init SL', p.initial_stop], ['e-entry', 'entry', p.entry], ['e-mark', 'now', p.mark_price],
    ].filter((l) => l[2] !== null && l[2] !== undefined);
    const lo = Math.min(...levels.map((l) => l[2]));
    const hi = Math.max(...levels.map((l) => l[2]));
    const span = hi - lo || 1;
    const at = (v) => 4 + ((v - lo) / span) * 92;
    return `<div class="ob1h-ladder">${levels.map(([c, label, v]) => `<i class="${c}" style="left:${at(v)}%"></i><em class="${c}" style="left:${at(v)}%">${label}</em>`).join('')}</div>`;
  }

  function renderPosition(d) {
    const box = $('ob1h-position');
    const p = d.position;
    $('ob1h-pos-count').textContent = p ? 1 : 0;
    if (!p) {
      const armed = d.watchlist.filter((w) => w.status === 'armed' && w.distance_pct !== null)
        .sort((a, b) => Math.abs(a.distance_pct) - Math.abs(b.distance_pct))[0];
      $('ob1h-pos-sub').textContent = 'Flat — waiting for a first revisit of an armed block';
      box.innerHTML = `<div class="ob1h-empty">No open position. The bot holds at most one trade at a time.${armed
        ? `<br>Nearest armed block: <b>${armed.action}</b> at <b>$${px(armed.entry_level)}</b> (${armed.distance_pct >= 0 ? '+' : ''}${armed.distance_pct.toFixed(2)}% from price) with the stop at <b>$${px(armed.planned_stop)}</b>.`
        : '<br>No armed blocks right now.'}</div>`;
      return;
    }
    $('ob1h-pos-sub').textContent = 'Live paper trade, marked to the latest Binance price';
    const moves = p.stop_moves.length
      ? `<div class="ob1h-moves-title">STOP TRAIL · ${p.stop_moves.length} MOVE${p.stop_moves.length > 1 ? 'S' : ''}</div><ul class="ob1h-moves">${[...p.stop_moves].reverse().map((m) => `<li><span>${ist(m.time)} IST</span><b>$${px(m.stop)}</b></li>`).join('')}</ul>`
      : `<div class="ob1h-moves-title">STOP TRAIL</div><div class="ob1h-empty">Stop still at the initial level beyond the order block. It will trail on each closed ${d.timeframe} candle${d.config.trail_activate_r > 0 ? ` once it is ${d.config.trail_activate_r}R in profit` : ''}.</div>`;
    box.innerHTML = `<div class="ob1h-pos-head"><span class="side-pill ${sideClass(p.side)}">${p.side.toUpperCase()}</span>`
      + `<span class="zone">${p.side === 'short' ? 'Bearish' : 'Bullish'} OB $${px(p.zone_bottom)} – $${px(p.zone_top)} · formed ${ist(p.zone_created)} IST</span>`
      + `<span class="neutral-tag">${p.trailing ? 'TRAILING' : 'INITIAL STOP'}</span></div>${ladder(p)}`
      + '<div class="ob1h-kv">'
      + `<div><span>Entry price</span><strong>$${px(p.entry)}</strong><small>${ist(p.entry_time)} IST</small></div>`
      + `<div><span>Mark price</span><strong>${p.mark_price ? `$${px(p.mark_price)}` : '—'}</strong></div>`
      + `<div><span>Unrealized P&amp;L</span><strong class="${cls(p.unrealized_pnl || 0)}">${p.unrealized_pnl === null ? '—' : `${signed(p.unrealized_pnl)} USDT`}</strong><small>${p.unrealized_pct === null ? '' : `${signed(p.unrealized_pct)}% · ${signed(p.unrealized_r)}R`}</small></div>`
      + `<div><span>Size</span><strong>${p.qty.toFixed(5)} BTC</strong><small>${usd(p.notional, 0)} notional</small></div>`
      + `<div><span>Initial stop-loss</span><strong>$${px(p.initial_stop)}</strong><small>${p.side === 'short' ? 'above' : 'below'} the block</small></div>`
      + `<div><span>Current stop-loss</span><strong class="${p.trailing ? 'positive-text' : ''}">$${px(p.stop)}</strong><small>${p.risk_to_stop_pct === null ? '' : `${p.risk_to_stop_pct.toFixed(2)}% from price`}</small></div>`
      + `<div><span>Risk at entry</span><strong>${usd(p.risk_usd)}</strong><small>1R</small></div>`
      + `<div><span>Best / worst since entry</span><strong>$${px(p.best)}</strong><small>$${px(p.worst)}</small></div>`
      + `</div>${moves}`;
  }

  function renderRules(d) {
    const c = d.config;
    $('ob1h-rules').innerHTML = `<li><b>Order blocks:</b> LuxAlgo SMC internal blocks on <b>${d.timeframe}</b> candles (swing 50, ATR-200 filter, newest five, ${c.mitigation === 'wick' ? 'high/low' : 'close'} invalidation).</li>`
      + '<li><b>Bearish block revisited → SHORT.</b> First time price rises into the block’s lower edge.</li>'
      + '<li><b>Bullish block revisited → LONG.</b> First time price falls into the block’s upper edge.</li>'
      + `<li><b>Stop-loss</b> beyond the far edge: <b>above</b> a bearish block, below a bullish one, plus <code>${c.stop_buffer_atr}×ATR(14)</code>.</li>`
      + `<li><b>No target. Trail on every closed ${d.timeframe} candle${c.trail_activate_r > 0 ? ` once a candle closes ${c.trail_activate_r}R in profit` : ''}:</b> stop follows the ${c.trail_lookback === 1 ? 'previous candle’s' : `last ${c.trail_lookback} candles’`} ${'high (short) / low (long)'} ± <code>${c.trail_buffer_atr}×ATR</code>; it only ever tightens.</li>`
      + `<li><b>Fill:</b> market at the next 1m open after the touch. One block, one trade; one position at a time.</li>`
      + `<li><b>Sizing:</b> risk ${c.risk_pct}% of equity per trade (cap ${c.max_notional_x}× notional). Costs: ${(c.fee_per_side * 100).toFixed(2)}% fee + ${(c.slippage_per_side * 100).toFixed(2)}% slippage per side.</li>`
      + '<li class="note">Research on this rule set found no after-cost edge (backtests 2024–2026 all negative). It is here to be observed, not trusted.</li>';
  }

  function renderWatchlist(d) {
    $('ob1h-watch-count').textContent = d.watchlist.length;
    $('ob1h-watch').innerHTML = d.watchlist.length ? d.watchlist.map((w) => {
      const dist = w.distance_pct === null ? '—' : `${w.distance_pct >= 0 ? '+' : ''}${w.distance_pct.toFixed(2)}%`;
      return `<tr><td><span class="side-pill ${w.side === 'bearish' ? 'sell' : 'buy'}">${w.side.toUpperCase()}</span></td>`
        + `<td><b>${w.action}</b></td><td>$${px(w.bottom)} – $${px(w.top)}</td><td>$${px(w.entry_level)}</td><td>$${px(w.planned_stop)}</td>`
        + `<td>${dist}</td><td>${ist(w.created)}</td><td><span class="status-pill ${w.status}">${w.status.toUpperCase()}</span></td></tr>`;
    }).join('') : '<tr><td colspan="8" class="table-loading">No active blocks.</td></tr>';
  }

  function renderCurve(d) {
    const pts = d.equity_curve;
    const box = $('ob1h-curve');
    if (pts.length < 2) {
      box.innerHTML = '<div class="ob1h-empty">The curve appears after the first closed trade.</div>';
      return;
    }
    const w = 560;
    const h = 150;
    const vals = pts.map((p) => p.balance);
    const lo = Math.min(...vals);
    const hi = Math.max(...vals);
    const span = hi - lo || 1;
    const xy = pts.map((p, i) => [8 + (i / (pts.length - 1)) * (w - 16), h - 14 - ((p.balance - lo) / span) * (h - 28)]);
    const up = vals[vals.length - 1] >= vals[0];
    const color = up ? '#47d7a0' : '#ff7283';
    const base = h - 14 - ((vals[0] - lo) / span) * (h - 28);
    box.innerHTML = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Equity curve">`
      + `<line x1="0" x2="${w}" y1="${base}" y2="${base}" stroke="#2a313d" stroke-dasharray="3 4"/>`
      + `<polyline fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke" points="${xy.map((p) => p.join(',')).join(' ')}"/></svg>`;
  }

  function renderEvents(d) {
    $('ob1h-events').innerHTML = d.events.length ? d.events.map((e) => {
      const text = {
        signal: `${e.side.toUpperCase()} signal · block $${px(e.zone_bottom)}–$${px(e.zone_top)} revisited`,
        entry: `${e.side.toUpperCase()} filled at $${px(e.price)} · stop $${px(e.stop)}`,
        trail: `${e.side.toUpperCase()} stop trailed to $${px(e.stop)}`,
        exit: `${e.side.toUpperCase()} closed at $${px(e.price)} · ${reasonText[e.reason] || e.reason} · ${signed(e.pnl)} USDT`,
        skipped: `${e.side.toUpperCase()} entry skipped · ${e.reason}`,
      }[e.type] || e.type;
      return `<li><time>${ist(e.time)}</time><span class="kind ${e.type}">${e.type.toUpperCase()}</span><span>${text}</span></li>`;
    }).join('') : '<li class="ob1h-empty">No activity since the bot started.</li>';
  }

  // Open-position levels on the main chart.
  let lines = [];
  function drawChartLines(d) {
    if (typeof candleSeries === 'undefined') return;
    lines.forEach((l) => candleSeries.removePriceLine(l));
    lines = [];
    const p = d.position;
    if (!p) return;
    const add = (price, color, title, style) => lines.push(candleSeries.createPriceLine({
      price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title,
    }));
    add(p.entry, '#9c83ff', `${p.side.toUpperCase()} entry`, 0);
    add(p.stop, '#ee8292', p.trailing ? 'Trailing SL' : 'SL', 2);
    if (p.trailing) add(p.initial_stop, '#7a4a54', 'Initial SL', 1);
  }

  async function load() {
    try {
      const seq = ++loadSeq;
      const response = await window.cryptoApiFetch(`/api/ob/${tf}`);
      if (response.status === 401) {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`; // session expired
        return;
      }
      if (!response.ok) throw new Error(response.status);
      const d = await response.json();
      if (seq !== loadSeq) return; // a newer tab switch is in flight
      const name = `${d.timeframe.toUpperCase()} order-block mitigation`;
      $('ob1h-title').textContent = name;
      $('ob1h-pos-title').textContent = name;
      $('ob1h-watch-tf').textContent = d.timeframe;
      if (d.status === 'starting') {
        setChip('loading', 'WARMING UP');
        return;
      }
      setChip(d.status === 'ok' ? 'live' : 'down', d.status === 'ok' ? `LIVE · ${d.mark_price ? `$${px(d.mark_price)}` : ''}` : 'DEGRADED');
      $('ob1h-subtitle').textContent = `Paper trading since ${ist(d.started_at)} IST · Binance ${d.symbol} · bearish block revisited → short, bullish → long, stop beyond the block, trailed every candle`;
      renderStats(d);
      renderPosition(d);
      renderRules(d);
      renderWatchlist(d);

      renderCurve(d);
      renderEvents(d);
      drawChartLines(d);
    } catch {
      setChip('down', 'OFFLINE');

    }
  }

  function select(next) {
    if (!TFS.includes(next)) return;
    tf = next;
    try { localStorage.setItem('ob-tf', tf); } catch { /* storage unavailable */ }
    document.querySelectorAll('#ob-tf-tabs button').forEach((b) => {
      b.classList.toggle('selected', b.dataset.tf === tf);
      b.setAttribute('aria-selected', String(b.dataset.tf === tf));
    });
    setChip('loading', 'LOADING');
    load();
  }
  document.querySelectorAll('#ob-tf-tabs button').forEach((b) => b.addEventListener('click', () => select(b.dataset.tf)));
  window.obSelectTimeframe = select;

  select(tf);
  window.setInterval(load, 10000);
})();
