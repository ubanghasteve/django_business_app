/**
 * Service Worker for offline-first: cache static assets, network-first for API.
 * - Cache-first: CSS, JS, templates, static assets
 * - Network-first: API requests (/api/v1/, /api/)
 */
'use strict';

const CACHE_STATIC = 'offline-first-static-v1';
const CACHE_PAGES = 'offline-first-pages-v1';

// Cache-first for static assets (CSS, JS, images, fonts under /static/)
self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names.filter(function (n) {
          return n !== CACHE_STATIC && n !== CACHE_PAGES;
        }).map(function (n) { return caches.delete(n); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var request = event.request;
  var url = new URL(request.url);

  // Non-GET: do not cache (e.g. POST to API)
  if (request.method !== 'GET') {
    return;
  }

  // API: network-first (try network, fallback to cache only for GET if we ever cache responses)
  if (url.pathname.indexOf('/api/') === 0) {
    event.respondWith(networkFirst(request));
    return;
  }

  // Static assets: cache-first
  if (url.pathname.indexOf('/static/') === 0 || url.pathname.indexOf('/media/') === 0) {
    event.respondWith(staticCacheFirst(request));
    return;
  }

  // HTML pages (templates): network-first so fresh content; cache for offline
  if (request.headers.get('accept') && request.headers.get('accept').indexOf('text/html') !== -1) {
    event.respondWith(networkFirst(request, CACHE_PAGES));
    return;
  }
});

function staticCacheFirst(request) {
  return caches.match(request).then(function (cached) {
    if (cached) return cached;
    return fetch(request).then(function (response) {
      if (response && response.ok && response.type === 'basic') {
        var clone = response.clone();
        caches.open(CACHE_STATIC).then(function (cache) {
          cache.put(request, clone);
        });
      }
      return response;
    }).catch(function () {
      return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
    });
  });
}

function networkFirst(request, cacheName) {
  return fetch(request).then(function (response) {
    if (response && response.ok && response.type === 'basic' && cacheName) {
      var clone = response.clone();
      caches.open(cacheName).then(function (cache) {
        cache.put(request, clone);
      });
    }
    return response;
  }).catch(function () {
    if (cacheName) {
      return caches.match(request).then(function (cached) {
        return cached || new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
      });
    }
    return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
  });
}
