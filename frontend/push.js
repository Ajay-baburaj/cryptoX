// Push-notification controls: asks permission, registers this browser with Firebase Cloud Messaging
// and tells the server its token. Needs HTTPS or http://localhost (browser rule for service workers).
import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js';
import { getMessaging, getToken, deleteToken, onMessage } from 'https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging.js';

const toggle = document.querySelector('#push-toggle');
const testButton = document.querySelector('#push-test');
const KEY = 'cryptox.push.token';
const label = (text) => { toggle.querySelector('.lbl').textContent = text; };
const say = (text) => (typeof showToast === 'function' ? showToast(text) : console.log(text));

async function post(url, body) {
  const response = await window.cryptoApiFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  if (response.status === 401) { window.location.href = '/login'; throw new Error('signed out'); }
  if (!response.ok) throw new Error(`${url} → ${response.status}`);
  return response.json();
}

async function init() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
  if (!window.isSecureContext) {
    toggle.hidden = false;
    label('Notifications need localhost or HTTPS');
    toggle.disabled = true;
    return;
  }
  const config = window.CryptoXConfig?.firebase || await (await fetch('/firebase-config')).json();
  if (!config.messagingSenderId) return; // push not configured: keep the controls hidden
  const messaging = getMessaging(initializeApp(config, 'push'));
  const registration = await navigator.serviceWorker.register('/sw.js');
  toggle.hidden = false;

  const enabled = () => Notification.permission === 'granted' && !!localStorage.getItem(KEY);
  const refresh = () => {
    label(Notification.permission === 'denied' ? 'Notifications blocked in browser' : enabled() ? 'Notifications on' : 'Enable notifications');
    toggle.classList.toggle('on', enabled());
    toggle.disabled = Notification.permission === 'denied';
    testButton.hidden = !enabled();
  };

  async function subscribe() {
    await navigator.serviceWorker.ready;
    // Use the project's public Web Push certificate when configured.
    const token = await getToken(messaging, { serviceWorkerRegistration: registration,
      ...(config.vapidKey ? { vapidKey: config.vapidKey } : {}) });
    if (!token) throw new Error('no token');
    await post('/api/push/register', { token });
    localStorage.setItem(KEY, token);
  }

  toggle.addEventListener('click', async () => {
    toggle.disabled = true;
    try {
      if (enabled()) {
        await post('/api/push/unregister', { token: localStorage.getItem(KEY) });
        await deleteToken(messaging).catch(() => {});
        localStorage.removeItem(KEY);
        say('Trade notifications turned off for this browser.');
      } else {
        if ((await Notification.requestPermission()) !== 'granted') { say('Notification permission was not granted.'); return; }
        await subscribe();
        say('Trade notifications enabled. You will be notified when a paper trade opens or closes.');
      }
    } catch (error) {
      say(`Could not change notifications: ${error.message}`);
    } finally {
      refresh();
    }
  });

  testButton.addEventListener('click', async () => {
    try {
      const { sent, failed, registered } = await post('/api/push/test');
      say(!registered ? 'No registered browsers yet.' : failed
        ? `Firebase accepted ${sent}; ${failed} failed. Check the server logs.`
        : `Firebase accepted ${sent} notification(s). Check your browser for delivery.`);
    } catch (error) { say(`Test failed: ${error.message}`); }
  });

  // Page open and focused: FCM hands the message to the page instead of the service worker.
  onMessage(messaging, (payload) => {
    const d = payload.data || {};
    say(`${d.title || 'CryptoX'} — ${d.body || ''}`);
  });

  if (enabled()) await subscribe().catch(() => localStorage.removeItem(KEY)); // refresh a rotated token
  refresh();
}

init().catch((error) => console.warn('push setup skipped:', error));
