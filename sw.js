// NYC Airport Radar — service worker (v2.7)
// Sayt qobig'ini keshlaydi: ilova tez ochiladi, oflayn ham qobiq ko'rinadi.
// Jonli ma'lumotlar (TomTom, AirLabs) har doim tarmoqdan olinadi.
const CACHE = 'nyc-radar-v3.29';
const CORE = ['/', 'index.html', 'manifest.json', 'icon.svg', 'icon-180.png', 'icon-512.png', 'vendor/leaflet.css', 'vendor/leaflet.js'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;

  // Sahifa (index.html): avval tarmoq — yangi versiya darhol kelsin; tarmoq bo'lmasa kesh.
  // Tarmoq 3 soniyada javob bermasa — keshdagi sahifa ko'rsatiladi (osilib qolmaslik uchun).
  // Keshlash faqat muvaffaqiyatli (r.ok) javoblarda.
  if (e.request.mode === 'navigate') {
    e.respondWith(
      Promise.race([
        fetch(e.request),
        new Promise((_, reject) => setTimeout(() => reject(new Error('navigate timeout')), 3000))
      ])
        .then(r => {
          if (r.ok) {
            const c = r.clone();
            caches.open(CACHE).then(cache => cache.put(e.request, c));
          }
          return r;
        })
        .catch(() => caches.match('index.html'))
    );
    return;
  }

  // Statik fayllar: keshdan tez, orqa fonda yangilanadi.
  e.respondWith(
    caches.match(e.request).then(hit => {
      const net = fetch(e.request)
        .then(r => {
          if (r.ok) {
            const c = r.clone();
            caches.open(CACHE).then(cache => cache.put(e.request, c));
          }
          return r;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});
