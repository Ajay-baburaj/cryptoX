(() => {
  const status = document.querySelector('#btc-signal-status');
  const container = document.querySelector('#btc-signal-market');
  const clock = document.querySelector('#btc-clock');
  const names = {bias:'4H · Market bias', structure_1h:'1H · Structure', setup_15m:'15m · Setup',
    trigger_5m:'5m · Entry trigger', derivatives:'Derivatives', macro_flows:'Macro & flows', sentiment:'News & sentiment'};
  const labels = {close:'Price',ema50:'EMA 50',adx:'ADX',atr_pct:'ATR %',range_low:'Range low',range_high:'Range high',
    zone_support_high:'Support',zone_resistance_low:'Resistance',
    momentum:'Momentum %',ema20:'EMA 20',rsi:'RSI',macd_hist:'MACD histogram',rvol:'Relative volume',
    funding_rate:'Funding %',oi_change_1h:'OI change %',taker_ratio:'Taker ratio',event_blackout:'Event blackout',
    etf_net_flow_usd:'ETF flow ($)',headlines_6h:'Headlines · 6h',security_headlines:'Security headlines',fear_greed:'Fear & Greed'};
  const sides = {LONG:'Bullish',SHORT:'Bearish',NEUTRAL:'Neutral',up:'Bullish',down:'Bearish',range:'Ranging',mixed:'Mixed',unknown:'Warming up'};
  const time = stamp => new Date(stamp).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function card(agent) {
    const node = el('article',null,'agent-card');
    const reading = sides[agent.trend || agent.direction] || 'Unavailable';
    node.append(el('h3',names[agent.agent]),el('strong',reading,'agent-side '+({Bullish:'agent-up',Bearish:'agent-down'}[reading] || '')));
    if (agent.volatility) node.append(el('p',agent.volatility+' volatility'));
    node.append(el('p','Agent view · '+sides[agent.direction]+' · '+agent.reason.replaceAll('_',' ')));
    const list = el('dl');
    for (const [key,v] of Object.entries(agent.metrics)) {
      let value = 'Unavailable';
      if (Number.isFinite(v)) {
        const n = ['momentum','funding_rate','oi_change_1h'].includes(key) ? v*100 : v;
        value = key==='event_blackout' ? (v?'Active':'Clear') : n.toLocaleString('en-IN',{maximumFractionDigits:key==='funding_rate'?4:2});
      }
      const row = el('div'); const label = el('dt',labels[key]);
      if (['fear_greed','etf_net_flow_usd'].includes(key) && agent.sources?.[key]) label.append(el('small',agent.sources[key],'agent-provider'));
      row.append(label,el('dd',value)); list.append(row);
    }
    node.append(list); return node;
  }
  async function refresh() {
    try {
      const response = await window.cryptoApiFetch('/api/btc-signal');
      if (!response.ok) throw new Error();
      const signal = await response.json();
      if (!signal.agent_details?.length || !(Date.now()-Date.parse(signal.observed_at)<150000)) throw new Error();
      clock.textContent = 'Updated '+time(signal.observed_at)+' IST · Every minute';
      status.textContent = '5m decision · '+({FLAT:'No trade',LONG:'Long',SHORT:'Short',WATCH:'Watch'}[signal.action] || signal.action)+
        ' · '+signal.reason.replaceAll('_',' ')+' · Confirmed '+time(signal.timestamp)+' IST';
      const grid=el('div',null,'agent-grid'), contextGrid=el('div',null,'agent-grid');
      const context=el('details',null,'agent-context');
      context.open=container.querySelector('details')?.open ?? true;
      context.append(el('summary','Context agents'),contextGrid);
      for (const a of signal.agent_details) (['derivatives','macro_flows','sentiment'].includes(a.agent)?contextGrid:grid).append(card(a));
      container.replaceChildren(grid,context,el('p','Rule-based agents · Indicator previews use the latest completed minute. Entry decisions use closed 5m candles.','agent-note'));
    } catch {
      container.replaceChildren(); clock.textContent='Awaiting update';
      status.textContent='Waiting for fresh Delta Exchange agent readings.';
    } finally { setTimeout(refresh,15000); }
  }
  refresh();
})();
