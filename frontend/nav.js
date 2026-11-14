(() => {
  const views = {overview: document.querySelector('#view-overview'), trades: document.querySelector('#trades'), strategies: document.querySelector('#strategies')};
  const items = [...document.querySelectorAll('.nav-item')];
  function route() {
    const hash = location.hash || '#overview';
    const key = hash === '#trades' ? 'trades' : hash === '#strategies' ? 'strategies' : 'overview';
    for (const [name, el] of Object.entries(views)) el.hidden = name !== key;
    const title = {overview:'Overview',trades:'Trade history',strategies:'Strategies'}[key];
    document.querySelector('.page-heading h1').textContent = title;
    document.querySelector('.crumb b').textContent = title;
    items.forEach(a => a.classList.toggle('active', a.hash === (hash === '#markets' || hash === '#manual-trading' ? hash : `#${key}`)));
    if (hash === '#markets' || hash === '#strategy' || hash === '#manual-trading') document.getElementById(hash.slice(1))?.scrollIntoView();
    else window.scrollTo({top:0});
  }
  addEventListener('hashchange',route);route();
})();
