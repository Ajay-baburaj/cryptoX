// Service worker for Firebase Cloud Messaging web push. The server sends data-only messages
// ({title, body, tag, url}); this turns them into system notifications and opens the dashboard on click.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    const raw = event.data ? event.data.json() : {};
    payload = raw.data || raw.notification || raw; // FCM wraps custom data under `data`
  } catch {
    payload = { title: 'Delta Desk', body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(self.registration.showNotification(payload.title || 'Delta Desk', {
    body: payload.body || '',
    tag: payload.tag || 'deltadesk',
    renotify: true,
    data: { url: payload.url || '/' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        if ('navigate' in client) await client.navigate(target).catch(() => {});
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
