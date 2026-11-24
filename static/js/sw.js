/**
 * Service Worker for EcoKleenFarms - Enables super fast loading on slow connections
 *
 * Features:
 * - Caches static assets (CSS, JS, fonts, images) for instant loading
 * - Network-first strategy for API calls and dynamic content
 * - Cache-first strategy for static assets
 * - Offline fallback support
 * - Background sync for pending requests
 *
 * NOTE (hard refresh when offline): A hard refresh (Ctrl+Shift+R / Shift+F5) bypasses
 * the service worker by design (spec). The browser may show its "dinosaur" / offline
 * page briefly. Use normal refresh or navigate via links when offline to stay in the app.
 */

const CACHE_NAME = 'cityprints-v26';
const STATIC_CACHE = 'static-v26';
const DYNAMIC_CACHE = 'dynamic-v26';
const FONT_CACHE = 'fonts-v26';
const API_CACHE = 'api-v26';

// Auth paths: we cache the login/register PAGE (GET) so it loads offline; POST (actual login) is never cached
function isAuthSensitivePath(pathname) {
  if (!pathname.startsWith('/auth/')) return false;
  const sensitive = [
    '/auth/login', '/auth/logout', '/auth/register',
    '/auth/password_reset', '/auth/reset/', '/auth/password-change-required'
  ];
  return sensitive.some(function (p) {
    return pathname === p || pathname === p + '/' || pathname.startsWith(p + '/');
  });
}

// Static assets to cache immediately (app shell)
const STATIC_ASSETS = [
  '/',
  '/auth/login/',
  '/auth/register/',
  '/dashboard/',
  '/dashboard/landing/',
  '/dashboard/company-profile/',
  '/auth/profile/',
  '/auth/security/',
  '/auth/security/team/',
  '/static/css/material-dashboard.min.css',
  '/static/css/nucleo-icons.css',
  '/static/css/nucleo-svg.css',
  '/static/js/core/bootstrap.min.js',
  '/static/js/core/popper.min.js',
  '/static/js/material-dashboard.min.js',
  '/static/js/currency-utils.js',
  '/static/img/favicon.png?v=6',
  '/static/img/favicon.ico',
  '/favicon.ico',
  '/static/img/apple-icon.png?v=6',
  '/static/img/logo-ct.png',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/icon-maskable-192.png',
  '/static/img/icon-maskable-512.png',
  '/manifest.webmanifest',
];

// Fallback URLs for navigation when offline and exact URL not cached (try these in order)
const NAV_FALLBACK_URLS = [
  '/auth/login/',
  '/auth/register/',
  '/dashboard/landing/',
  '/dashboard/',
  '/dashboard/company-profile/',
  '/auth/profile/',
  '/auth/security/',
  '/auth/security/team/',
  '/attendance/',
  '/attendance/dashboard',
  '/attendance/devices',
  '/invoices/',
  '/clients/',
  '/expense/',
  '/requisitions/',
  '/receipts/',
  '/waybills/',
  '/quotations/',
  '/job-orders/',
  '/inventory/',
  '/accounting/',
  '/hr-staff/',
  '/messaging/',
  '/mailing/',
  '/notifications/',
  '/',
];

// Font URLs to cache
const FONT_URLS = [
  'https://fonts.googleapis.com',
  'https://fonts.gstatic.com',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome',
];

// Install event - Cache static assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing Service Worker...');
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        // Cache each asset individually to handle failures gracefully
        return Promise.allSettled(
          STATIC_ASSETS.map(url => 
            cache.add(url).catch(err => console.log('[SW] Failed to cache:', url))
          )
        );
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - Clean up old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating Service Worker...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== STATIC_CACHE && name !== DYNAMIC_CACHE && name !== FONT_CACHE && name !== API_CACHE)
          .map((name) => {
            console.log('[SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - Serve from cache or network
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip admin - never cache
  // if (url.pathname.startsWith('/admin/')) {
  //   return;
  // }


   // Skip admin - never cache
  if (url.pathname === '/admin' || url.pathname.startsWith('/admin/')) {
    return;
  }
  

  // Notifications API - never cache so badge and list stay real-time accurate
  if (url.pathname.indexOf('/notifications/api/') !== -1) {
    return;
  }

  // Inventory product report JSON - never cache so real-time refresh works
  if (url.pathname.indexOf('/inventory/product/') !== -1 && url.pathname.indexOf('/report/') !== -1 && url.searchParams.get('format') === 'json') {
    return;
  }

  // Auth pages (login, register, etc.): cache GET so they load offline; POST (actual login) is never cached
  // Previously skipped entirely, which caused Chrome's dinosaur when visiting /auth/login/ offline

  // GET /api/ - network-first with cache fallback so lists, badge, stats work offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(apiNetworkFirst(request));
    return;
  }

  // Handle font requests - Network first (avoids serving stale/bad cached fonts)
  if (FONT_URLS.some(fontUrl => request.url.includes(fontUrl))) {
    event.respondWith(fontNetworkFirst(request));
    return;
  }

  // Handle static assets - Cache first strategy
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/media/')) {
    event.respondWith(staticCacheFirst(request));
    return;
  }

  // /favicon.ico - serve from cached static favicon to avoid 503 when offline
  if (url.pathname === '/favicon.ico') {
    event.respondWith(faviconFallback(request));
    return;
  }

  // Waybills: explicit network-first (same as HTML doc handling below, kept for clarity).
  if (url.pathname === '/waybills' || url.pathname === '/waybills/' || url.pathname.startsWith('/waybills/')) {
    event.respondWith(networkFirstForPages(request));
    return;
  }

  // Attendance: network-first, never cache (always fresh to avoid stale/error pages and back-nav issues)
  if (url.pathname.startsWith('/attendance/')) {
    event.respondWith(networkFirstNoCache(request));
    return;
  }

  // Same-origin HTML document requests (dashboard, invoices, list pages, etc.): always network-first
  // so a different user/company never sees a cached page from the previous session. When offline we fall back to cache.
  const isHtmlDoc = request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
  if (isHtmlDoc && url.origin === self.location.origin) {
    event.respondWith(networkFirstForPages(request));
    return;
  }

  // All other same-origin GETs (e.g. non-HTML): stale-while-revalidate
  event.respondWith(staleWhileRevalidate(request));
});

// Favicon: serve cached /static/img/favicon.png when /favicon.ico is requested offline
async function faviconFallback(request) {
  const staticFaviconUrl = self.location.origin + '/static/img/favicon.png';
  let cached = await caches.match(staticFaviconUrl);
  if (!cached) {
    try {
      const cache = await caches.open(STATIC_CACHE);
      cached = await cache.match(staticFaviconUrl);
    } catch (e) {}
  }
  if (cached) return cached;
  try {
    const net = await fetch(staticFaviconUrl);
    if (net.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(staticFaviconUrl, net.clone());
    }
    return net;
  } catch (e) {
    return new Response('', { status: 204, statusText: 'No Content' });
  }
}

// Cache-first strategy for static assets
async function staticCacheFirst(request) {
  const cachedResponse = await caches.match(request);
  if (cachedResponse) {
    return cachedResponse;
  }

  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    console.log('[SW] Network failed for:', request.url);
    return new Response('Offline - Asset not available', { status: 503 });
  }
}

// Network-first for fonts - always try fresh, use cache only when offline
// Use mode: 'cors' and credentials: 'omit' to avoid CORS issues with Google Fonts
async function fontNetworkFirst(request) {
  try {
    const networkResponse = await fetch(request.url, { 
      mode: 'cors',
      credentials: 'omit'  // Don't send cookies - fixes CORS wildcard issue
    });
    if (networkResponse.ok) {
      const cache = await caches.open(FONT_CACHE);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) return cachedResponse;
    console.log('[SW] Font fetch failed (offline):', request.url);
    return new Response('', { status: 503 });
  }
}

// Network-first for GET /api/ - cache response for offline (badge, lists, dashboard stats, etc.)
async function apiNetworkFirst(request) {
  const cache = await caches.open(API_CACHE);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok && networkResponse.type === 'basic') {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await cache.match(request);
    if (cachedResponse) return cachedResponse;
    // Return valid JSON error so pages don't break (e.g. badge expects JSON)
    return new Response(JSON.stringify({ error: 'offline', unread_count: 0 }), {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// Network-first for /attendance/*: always fetch fresh, never cache. Prevents stale/error pages and back-nav issues.
async function networkFirstNoCache(request) {
  const cache = await caches.open(DYNAMIC_CACHE);
  try {
    const networkResponse = await fetch(request);
    return networkResponse;
  } catch (error) {
    const cachedResponse = await cache.match(request) || await cache.match(normalizedRequest(request));
    if (cachedResponse) return cachedResponse;
    const isHtml = request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
    if (isHtml) {
      const fallback = await getCachedFallback(cache, request);
      if (fallback) return fallback;
    }
    throw error;
  }
}

// Network-first for HTML/app pages: always try network so different user/company gets fresh content.
// On success we cache for offline fallback; on failure we serve cache if available.
async function networkFirstForPages(request) {
  const cache = await caches.open(DYNAMIC_CACHE);
  const normReq = normalizedRequest(request);
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok && networkResponse.type === 'basic') {
      const vary = networkResponse.headers.get('Vary');
      if (!vary || !vary.includes('*')) {
        cache.put(normReq, networkResponse.clone()).catch(function () {});
      }
    }
    return networkResponse;
  } catch (error) {
    const cachedResponse = await cache.match(normReq) || await cache.match(request);
    if (cachedResponse) return cachedResponse;
    const isHtml = request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
    if (isHtml) {
      const fallback = await getCachedFallback(cache, request);
      if (fallback) return fallback;
    }
    throw error;
  }
}

// Normalize same-origin URL for cache key (trailing slash for pathname) so /dashboard and /dashboard/ match
function normalizedRequest(request) {
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return request;
  if (url.pathname !== '/' && !url.pathname.endsWith('/')) {
    url.pathname += '/';
    return new Request(url.href, { method: request.method, headers: request.headers, mode: request.mode, credentials: request.credentials });
  }
  return request;
}

// Timeout for HTML fetches so slow server does not hang the page (fall back to cache or offline page)
const HTML_FETCH_TIMEOUT_MS = 8000;

function fetchWithTimeout(request, timeoutMs) {
  return Promise.race([
    fetch(request),
    new Promise(function (_, reject) {
      setTimeout(function () { reject(new Error('timeout')); }, timeoutMs);
    })
  ]);
}

// Stale-while-revalidate for HTML pages (fast with fresh updates)
async function staleWhileRevalidate(request) {
  const cache = await caches.open(DYNAMIC_CACHE);
  const normReq = normalizedRequest(request);
  let cachedResponse = await cache.match(normReq) || await cache.match(request);
  // For /auth/login/ and /auth/register/, also try base URL (no query) so ?next=... requests hit cache
  if (!cachedResponse) {
    const url = new URL(request.url);
    if (url.origin === self.location.origin && (url.pathname.startsWith('/auth/login') || url.pathname.startsWith('/auth/register'))) {
      const basePath = url.pathname.endsWith('/') ? url.pathname : url.pathname + '/';
      const baseUrl = url.origin + basePath;
      cachedResponse = await cache.match(baseUrl) || await caches.open(STATIC_CACHE).then(function(c) { return c.match(baseUrl); }).catch(function() { return null; });
    }
  }

  const isHtml = request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
  const fetchReq = isHtml ? fetchWithTimeout(request, HTML_FETCH_TIMEOUT_MS) : fetch(request);

  const fetchPromise = fetchReq
    .then((networkResponse) => {
      if (networkResponse.ok && networkResponse.type === 'basic') {
        // Cache API rejects responses with Vary: *; skip putting those
        const vary = networkResponse.headers.get('Vary');
        if (!vary || !vary.includes('*')) {
          cache.put(normReq, networkResponse.clone()).catch(function () {});
        }
      }
      return networkResponse;
    })
    .catch(async () => {
      // Network failed or timeout (offline/slow): return cached if available
      if (cachedResponse) return cachedResponse;
      // For navigation/document requests, try fallback URLs so user sees a cached app page
      if (isHtml) {
        const fallback = await getCachedFallback(cache, request);
        if (fallback) return fallback;
      }
      const html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Offline</title></head><body><p>You are offline. Open this page again when back online.</p><p class="text-muted" style="margin-top:1em;font-size:0.9em;">Tip: If you saw the browser\'s offline page (e.g. after a hard refresh), use normal refresh or click a link to return to the app.</p></body></html>';
      return new Response(html, { status: 503, statusText: 'Service Unavailable', headers: { 'Content-Type': 'text/html' } });
    });

  return cachedResponse || fetchPromise;
}

// When offline and exact URL not cached, try fallback URLs so dashboard/app still loads
async function getCachedFallback(cache, originalRequest) {
  const url = new URL(originalRequest.url);
  if (url.origin !== self.location.origin) return null;
  const pathname = url.pathname;
  for (const path of NAV_FALLBACK_URLS) {
    // Don't serve register when user asked for login (or vice versa)
    if (pathname.startsWith('/auth/login') && path.startsWith('/auth/register')) continue;
    if (pathname.startsWith('/auth/register') && path.startsWith('/auth/login')) continue;
    const fallbackUrl = url.origin + path;
    let res = await cache.match(fallbackUrl);
    if (!res) {
      try {
        const staticCache = await caches.open(STATIC_CACHE);
        res = await staticCache.match(fallbackUrl);
      } catch (e) {}
    }
    if (res) return res;
  }
  return null;
}

// Listen for messages from the main thread
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }

  if (event.data === 'clearCache') {
    caches.keys().then((names) => {
      names.forEach((name) => caches.delete(name));
    });
  }

  // Clear only app/page caches (dynamic + API) so next login gets fresh content for the new user/company
  if (event.data === 'clearAppCaches') {
    caches.delete(DYNAMIC_CACHE).catch(function () {});
    caches.delete(API_CACHE).catch(function () {});
  }
});

console.log('[SW] Service Worker loaded');
