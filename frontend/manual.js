(() => {
  const $ = id => document.getElementById(id);
  const ui = window.PaperUI, {fmt, signed, tone, time, node} = ui;
  const form = $('manual-order');
  const box = $('manual-positions');
  let snapshot, busy=false, editingId=null;

  function message(text, error=false) {
    $('manual-message').textContent=text;
    $('manual-message').classList.toggle('negative-text',error);
  }
  function live() { return snapshot?.status==='ok' && Date.now()-Date.parse(snapshot.last_update)<15000; }
  function buttons() {
    form.querySelectorAll('button').forEach(b=>b.disabled=busy||!live());
    box.querySelectorAll('button').forEach(b=>b.disabled=busy||!live());
  }
  function values(f) {
    return Object.fromEntries([...new FormData(f)].map(([k,v])=>[k,v===''?null:Number(v)]));
  }
  function openEditor(card,p,edit) {
    editingId=p.id;
    const editor=document.createElement('form');editor.className='manual-form';
    for(const [name,label] of [['stop','Stop-loss (USDT)'],['target','Take-profit (USDT)'],['trail_pct','Trailing distance (%)']]) {
      const l=node('label',label),input=document.createElement('input');
      input.name=name;input.type='number';input.min='0.000001';input.step='any';input.value=p[name]??'';input.placeholder='Blank disables';
      if(name==='trail_pct')input.max='99.999';l.append(input);editor.append(l);
    }
    const save=node('button','Save protection','button button-primary');save.type='submit';
    const cancel=node('button','Cancel','button button-muted');cancel.type='button';cancel.onclick=()=>{editingId=null;render(snapshot);};
    editor.append(save,cancel);
    editor.onsubmit=event=>{event.preventDefault();action('update',{...values(editor),position_id:p.id});};
    card.append(editor);edit.hidden=true;
  }
  function card(p) {
    const c=ui.positionCard(p),actions=node('div','','manual-actions');
    const edit=node('button','Edit SL / TP / Trail','button button-muted');edit.type='button';edit.onclick=()=>openEditor(c,p,edit);
    const close=node('button','Close position','button manual-sell');close.type='button';close.onclick=()=>action('close',{position_id:p.id});
    actions.append(edit,close);c.append(actions);
    return c;
  }
  function renderPositions(positions) {
    const editing=editingId?[...box.children].find(c=>c.dataset.id===editingId):null;
    const open=editing?positions.find(p=>p.id===editingId):null;
    if(!open) {
      editingId=null;
      box.replaceChildren(...positions.map(card));
      if(!positions.length)box.append(node('p','No manual positions. Set a quantity and optional protection, then Buy or Sell.','strategy-note'));
      return;
    }
    // Replace the cards around an in-progress edit so its inputs keep focus as prices refresh.
    [...box.children].forEach(c=>{if(c!==editing)c.remove();});
    ui.setPnl(editing,open);
    const index=positions.indexOf(open);
    editing.before(...positions.slice(0,index).map(card));
    editing.after(...positions.slice(index+1).map(card));
  }
  function renderOrders(trades) {
    const body=$('manual-orders');body.replaceChildren();
    for(const t of trades.slice(0,10)) {
      const row=document.createElement('tr'),side=node('td','');side.append(ui.sidePill(t.side));
      const toneClass=tone(t.pnl);
      row.append(side,node('td',`${t.quantity} BTC`),node('td',fmt(t.entry)),node('td',fmt(t.exit)),node('td',time(t.exit_time)),node('td',t.exit_reason),node('td',`${signed(t.ret_pct)}%`,toneClass),node('td',`${signed(t.pnl)} USDT`,toneClass));
      body.append(row);
    }
    if(!trades.length){const row=node('tr',''),cell=node('td','No closed manual orders yet.');cell.colSpan=8;row.append(cell);body.append(row);}
  }
  function render(data) {
    snapshot=data;
    const a=data.account;
    const account=$('manual-account');account.replaceChildren(`Price ${fmt(data.mark_price)} USDT · Equity ${fmt(a.equity)} USDT · Available ${fmt(a.available)} USDT · P&L `,node('span',`${signed(a.pnl)} USDT`,tone(a.pnl)),` · ${data.positions.length} open · ${live()?'LIVE':'FEED UNAVAILABLE'}`);
    renderPositions(data.positions);renderOrders(data.trades);buttons();
  }
  async function action(kind,body) {
    if(busy)return;
    busy=true;buttons();message('Processing paper order…');
    try {
      const r=await window.cryptoApiFetch(`/api/manual/${kind}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await r.json();if(!r.ok)throw Error(data.error||'Paper order failed');
      editingId=null;render(data);message({open:'Paper position opened.',update:'Protection updated.',close:'Paper position closed.'}[kind]);
      window.dispatchEvent(new Event('paper-account-updated'));
    } catch(error) {message(error.message,true);}
    finally {busy=false;buttons();}
  }
  form.addEventListener('submit',event=>{event.preventDefault();action('open',{...values(form),side:event.submitter?.value||'long'});});
  async function load() {
    if(busy)return;
    try {const r=await window.cryptoApiFetch('/api/manual');if(!r.ok)throw Error('Manual account unavailable');const data=await r.json();if(!busy)render(data);}
    catch {snapshot=null;$('manual-account').textContent='Manual account offline. Reconnecting…';buttons();}
  }
  $('refresh').addEventListener('click',load);load();setInterval(load,2000);
})();
