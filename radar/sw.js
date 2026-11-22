// NYC Airport Radar — service worker (v3.66)
// Sayt qobig'ini keshlaydi: ilova tez ochiladi, oflayn ham qobiq ko'rinadi.
// Jonli ma'lumotlar (TomTom, AirLabs) har doim tarmoqdan olinadi.
const CACHE = 'nyc-radar-v3.66';
const TILE_CACHE = 'nyc-radar-tiles-v3.66';
const CORE = ['./', 'index.html', 'manifest.json', 'icon.svg', 'icon-180.png', 'icon-512.png', 'icon-192.png', 'icon-512-maskable.png', 'offline.html', 'vendor/leaflet.css', 'vendor/leaflet.js', 'zones.json', 'zones-all.json', 'reports-2025.json', 'mosques.json'];
const TILE_ORIGINS = ['server.arcgisonline.com', 'api.tomtom.com'];
const TILE_MAX = 200; // keshlanadigan plitkalar soni chegarasi

self.addEventListener('install', e => {
  // v3.48: bitta fayl 404 bo'lsa ham o'rnatish to'xtamaydi (AUD-30)
  e.waitUntil(
    caches.open(CACHE).then(c => Promise.all(CORE.map(url =>
      c.add(url).catch(err => console.log('SW core cache skip:', url, err))
    ))).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE && k !== TILE_CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function trimTileCache() {
  try {
    const c = await caches.open(TILE_CACHE);
    const keys = await c.keys();
    if (keys.length > TILE_MAX) {
      for (const k of keys.slice(0, keys.length - TILE_MAX)) await c.delete(k);
    }
  } catch (e) {}
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;

  // v3.48: kruiz jadvali hech qachon SW keshidan berilmaydi — har doim tarmoq (AUD-31)
  if (url.origin === self.location.origin && url.pathname.endsWith('cruise-schedule.json')) return;

  // v3.48: xarita plitkalari (Esri + TomTom traffic) oflayn uchun keshlanadi, chegara bilan (AUD-10)
  if (TILE_ORIGINS.includes(url.hostname)) {
    e.respondWith(
      caches.open(TILE_CACHE).then(c => c.match(e.request).then(hit => {
        const net = fetch(e.request).then(r => {
          if (r.ok) { const cl = r.clone(); c.put(e.request, cl).catch(() => {}); trimTileCache(); }
          return r;
        }).catch(() => hit);
        return hit || net;
      }))
    );
    return;
  }

  if (url.origin !== self.location.origin) return;

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
            caches.open(CACHE).then(cache => cache.put(e.request, c).catch(() => {}));
          }
          return r;
        })
        .catch(() => caches.match('index.html').then(hit => hit || caches.match('offline.html')))
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
            caches.open(CACHE).then(cache => cache.put(e.request, c).catch(() => {}));
          }
          return r;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});
