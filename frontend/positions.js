// Shared rendering for open positions and P&L colouring (manual trading + all-strategies view).
window.PaperUI = (() => {
  const num = n => n !== null && n !== undefined && Number.isFinite(Number(n));
  const fmt = n => num(n) ? Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}) : '—';
  const signed = n => !num(n) ? '—' : `${Number(n) > 0 ? '+' : Number(n) < 0 ? '−' : ''}${fmt(Math.abs(n))}`;
  const tone = n => !num(n) || Number(n) === 0 ? 'flat' : Number(n) > 0 ? 'profit' : 'loss';
  const time = s => s ? new Date(s).toLocaleString('en-IN', {timeZone:'Asia/Kolkata', day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', hour12:false}) : '—';
  const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };
  const sidePill = side => node('span', side.toUpperCase(), `side-pill ${side}`);

  function setPnl(card, p) {
    const value = card.querySelector('.pos-pnl-value'), pct = card.querySelector('.pos-pnl-pct'), mark = card.querySelector('.pos-mark');
    value.textContent = `${signed(p.unrealized_pnl)} ${p.currency}`;
    pct.textContent = num(p.unrealized_pct) ? `${signed(p.unrealized_pct)}%` : '';
    if (mark) mark.textContent = fmt(p.mark_price);
    card.classList.remove('profit', 'loss', 'flat');
    card.classList.add(tone(p.unrealized_pnl));
  }

  function positionCard(p) {
    const card = node('article', '', 'pos-card');
    card.dataset.id = p.id || p.entry_time;
    const head = node('div', '', 'pos-head');
    const title = node('div', '', 'pos-title');
    title.append(sidePill(p.side), node('b', `${p.quantity ?? p.qty} BTC`), node('span', p.strategy_name, 'pos-strategy'));
    head.append(title);
    const pnl = node('div', '', 'pos-pnl');
    pnl.append(node('strong', '', 'pos-pnl-value'), node('span', '', 'pos-pnl-pct'), node('small', 'Net unrealized'));
    const grid = node('dl', '', 'pos-fields');
    const fields = [['Entry', fmt(p.entry)], ['Mark', fmt(p.mark_price), 'pos-mark'], ['Stop', fmt(p.stop), 'loss'], ['Target', fmt(p.target), 'profit']];
    if (p.trail_pct !== undefined) fields.push(['Trail', p.trail_pct === null ? 'Off' : `${p.trail_pct}% · ${fmt(p.trailing_stop)}`]);
    fields.push(['Opened', `${time(p.entry_time)} IST`]);
    for (const [label, value, cls] of fields) {
      const item = node('div', '');
      item.append(node('dt', label), node('dd', value, cls));
      grid.append(item);
    }
    card.append(head, pnl, grid);
    setPnl(card, p);
    return card;
  }

  return {fmt, signed, tone, time, node, sidePill, positionCard, setPnl};
})();
