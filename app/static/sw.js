/* Service worker: offline app shell + Web Push notifications.
 * Bump CACHE_VERSION whenever static assets change so old caches are purged. */
const CACHE_VERSION = 'cuzdanim-v3';
const APP_SHELL = [
  '/',
  '/static/styles.css',
  '/static/app.js',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];
const CDN_HOSTS = ['cdnjs.cloudflare.com'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // API calls: always network (never serve stale money data).
  if (url.pathname.startsWith('/api/')) return;

  // CDN libraries (Chart.js): cache-first so the app works offline after first load.
  if (CDN_HOSTS.includes(url.hostname)) {
    event.respondWith(
      caches.match(event.request).then((hit) => hit || fetch(event.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
        return res;
      }))
    );
    return;
  }

  // App shell: network-first with cache fallback (so updates land immediately when online).
  if (url.origin === self.location.origin) {
    event.respondWith(
      fetch(event.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then((c) => c.put(event.request, copy));
        return res;
      }).catch(() => caches.match(event.request).then((hit) => hit || caches.match('/')))
    );
  }
});

// ---- Push ---------------------------------------------------------------------
self.addEventListener('push', (event) => {
  let data = { title: 'Cüzdanım', body: 'Yeni bir mesajın var.', url: '/' };
  try { data = { ...data, ...event.data.json() }; } catch (_) { /* plain-text payload */ if (event.data) data.body = event.data.text(); }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon || '/static/icons/icon-192.png',
      badge: data.badge || '/static/icons/icon-192.png',
      tag: data.tag || 'cuzdanim',
      renotify: true,
      data: { url: data.url || '/' },
      lang: 'tr',
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((c) => c.url.startsWith(self.location.origin));
      if (existing) { existing.navigate(target); return existing.focus(); }
      return self.clients.openWindow(target);
    })
  );
});
