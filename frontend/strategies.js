(() => {
  const $ = id => document.getElementById(id);
  const fmt = n => Number.isFinite(n) ? n.toLocaleString('en-US',{maximumFractionDigits:2,minimumFractionDigits:2}) : '—';
  const time = s => s ? new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
  const node = (tag,text,className) => {const n=document.createElement(tag);n.textContent=text;if(className)n.className=className;return n;};
  let strategies=[];
  function renderTrades() {
    const filter=$('strategy-filter').value;
    const trades=strategies.filter(s=>!filter||s.strategy_id===filter).flatMap(s=>s.trades).sort((a,b)=>Date.parse(b.exit_time)-Date.parse(a.exit_time));
    $('all-trades-count').textContent=`${trades.length} closed paper trades`;
    const body=$('all-trades');body.replaceChildren();
    for(const t of trades.slice(0,500)) {
      const row=document.createElement('tr');
      const ui=window.PaperUI,ret=t.ret_pct ?? t.net_return*100,tone=ui.tone(t.pnl);
      row.append(node('td',t.strategy_name),node('td',`${t.symbol} · ${t.venue}`));
      const side=node('td','');side.append(ui.sidePill(t.side));row.append(side);
      row.append(node('td',`${fmt(t.entry)} · ${time(t.entry_time)}`),node('td',`${fmt(t.exit)} · ${time(t.exit_time)}`),node('td',t.exit_reason),node('td',`${ui.signed(ret)}%`,tone),node('td',`${ui.signed(t.pnl)} ${t.currency}`,tone),node('td',`${fmt(t.fees)} ${t.currency}`),node('td',t.data_quality||'—'));body.append(row);
    }
    if(!trades.length){const row=node('tr',''),cell=node('td','No closed trades for this selection.');cell.colSpan=10;row.append(cell);body.append(row);}
    if(trades.length>500)$('all-trades-count').textContent+= ' · showing latest 500';
  }
  function render() {
    const list=$('strategy-list'),positions=$('all-positions');list.replaceChildren();positions.replaceChildren();
    const previous=$('strategy-filter').value;
    $('strategy-filter').replaceChildren(new Option('All strategies',''));
    for(const s of strategies) {
      $('strategy-filter').append(new Option(s.strategy_name,s.strategy_id));
      const card=node('article','','strategy-card');card.append(node('h3',s.strategy_name),node('p',`${s.venue} · ${s.symbol} · ${s.status.toUpperCase()}`),node('p',s.validation,'validation'));
      const pnl=node('p','');pnl.append(`Equity ${fmt(s.account.equity)} ${s.currency} · P&L `,node('span',`${window.PaperUI.signed(s.account.pnl)} ${s.currency}`,window.PaperUI.tone(s.account.pnl)),` · Closed trades ${s.stats.trades} · Win rate ${s.stats.trades?fmt(s.stats.win_rate)+'%':'not available'}`);card.append(pnl);
      card.append(node('p',s.rules),node('p',`Started: ${time(s.started_at)} IST · Feed update: ${time(s.last_update)} IST`));
      if(s.timeframe&&/^ob.*_mitigation$/.test(s.strategy_id)){const a=node('a','Order-block details');a.href='#strategy';a.addEventListener('click',()=>window.obSelectTimeframe?.(s.timeframe));card.append(a);}
      list.append(card);
      for(const p of s.positions)positions.append(window.PaperUI.positionCard(p));
    }
    if([...$('strategy-filter').options].some(o=>o.value===previous))$('strategy-filter').value=previous;
    const open=strategies.reduce((a,s)=>a+s.positions.length,0);
    if(!open)positions.append(node('p','No open positions across the paper strategies.','strategy-note'));
    const ob=strategies.find(s=>s.strategy_id==='ob1h_mitigation'),manual=strategies.find(s=>s.strategy_id==='manual_paper');
    $('stat-balance').textContent=ob?`${fmt(ob.account.equity)} USDT`:'—';
    $('stat-start').textContent=ob?`P&L ${fmt(ob.account.pnl)} USDT`:'';
    $('stat-pnl').textContent=manual?`${fmt(manual.account.equity)} USDT`:'—';
    $('stat-pnl-pct').textContent=manual?`P&L ${window.PaperUI.signed(manual.account.pnl)}`:'';$('stat-pnl-pct').className=manual?window.PaperUI.tone(manual.account.pnl):'';
    const n=strategies.reduce((a,s)=>a+s.stats.trades,0),wins=strategies.reduce((a,s)=>a+s.stats.wins,0),losses=strategies.reduce((a,s)=>a+s.stats.losses,0);
    $('stat-winrate').textContent=n?`${fmt(wins/n*100)}%`:'—';$('stat-wins').textContent=`${wins} wins`;$('stat-losses').textContent=`${losses} losses`;
    $('stat-positions').textContent=`${open} open`;$('stat-positions-detail').textContent='Independent paper accounts';
    $('paper-status-chip').textContent=strategies.every(s=>s.status==='ok')?'PAPER ENGINES LIVE':'CHECK STRATEGY STATUS';
    renderTrades();
  }
  async function load(){try{const r=await window.cryptoApiFetch('/api/strategies');if(!r.ok)throw Error(r.status);strategies=(await r.json()).strategies;render();}catch{$('paper-status-chip').textContent='STRATEGIES OFFLINE';}}
  $('strategy-filter').addEventListener('change',renderTrades);$('refresh').addEventListener('click',load);
  window.addEventListener('paper-account-updated',load);
  load();setInterval(load,10000);
})();
