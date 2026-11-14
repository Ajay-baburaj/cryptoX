(() => {
  let hosted;
  const module = () => hosted ||= import('/hosted-auth.js');
  window.cryptoApiFetch = (path, options) => window.CryptoXConfig
    ? module().then(m => m.apiFetch(path, options)) : fetch(path, options);
  if (!window.CryptoXConfig || location.pathname.startsWith('/login')) return;
  document.documentElement.style.visibility = 'hidden';
  module().then(m => m.requireUser()).then(user => {
    if (user) document.documentElement.style.visibility = '';
  }).catch(() => location.replace('/login'));
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelector('form[action="/logout"]')?.addEventListener('submit', async event => {
      event.preventDefault();
      await (await module()).logout();
    });
  });
})();
