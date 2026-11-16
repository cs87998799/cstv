/* Sarah TV service worker: offline page + notifications + push */
const V = 'sarah-v1';
const SHELL = ['./offline.html', './manifest.webmanifest', './icon-192.png', './icon-512.png'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request; if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (r.mode === 'navigate') {          // পেজ খোলা: নেট না থাকলে অফলাইন পেজ
    e.respondWith(fetch(r).catch(() => caches.match('./offline.html')));
    return;
  }
  if (u.origin === location.origin && /\.(png|webmanifest|ico|svg)$/.test(u.pathname)) {   // আইকন/ম্যানিফেস্ট: cache-first
    e.respondWith(caches.match(r).then(h => h || fetch(r).then(res => { const cp = res.clone(); caches.open(V).then(c => c.put(r, cp)); return res; })));
  }
});
function show(d) {
  d = d || {};
  return self.registration.showNotification(d.title || 'Sarah TV', {
    body: d.body || '', tag: d.tag || 'sarah', icon: d.icon || './icon-192.png', badge: './icon-192.png',
    vibrate: [250, 120, 250], renotify: true, data: { url: d.url || './' }
  });
}
self.addEventListener('push', e => {      // সার্ভার থেকে পুশ এলে (নেট থাকলে, সাইট বন্ধ থাকলেও)
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(show(d));
});
self.addEventListener('message', e => { if (e.data && e.data.type === 'notify') e.waitUntil(show(e.data)); });
self.addEventListener('notificationclick', e => {
  e.notification.close(); const url = (e.notification.data && e.notification.data.url) || './';
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    for (const c of cs) { if ('focus' in c) return c.focus(); }
    return self.clients.openWindow(url);
  }));
});
