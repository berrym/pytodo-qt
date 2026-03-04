/* PyTodo-Qt Service Worker — Offline caching and edit queue */
var CACHE_VERSION = "v1";
var CACHE_NAME = "pytodo-" + CACHE_VERSION;
var STATIC_ASSETS = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.json"
];

// --- Install: pre-cache static assets ---
self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// --- Activate: clean up old caches ---
self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (name) { return name !== CACHE_NAME; })
          .map(function (name) { return caches.delete(name); })
      );
    })
  );
  self.clients.claim();
});

// --- Fetch: route requests through caching strategies ---
self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);

  // API write operations: network-only (app.js handles offline queue)
  if (url.pathname.startsWith("/api/") && event.request.method !== "GET") {
    event.respondWith(fetch(event.request));
    return;
  }

  // API reads: network-first, fall back to cache
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Static assets and pages: cache-first
  event.respondWith(cacheFirst(event.request));
});

function cacheFirst(request) {
  return caches.match(request).then(function (cached) {
    if (cached) return cached;
    return fetch(request).then(function (response) {
      if (response.ok) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, clone);
        });
      }
      return response;
    });
  });
}

function networkFirst(request) {
  return fetch(request)
    .then(function (response) {
      if (response.ok) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(request, clone);
        });
      }
      return response;
    })
    .catch(function () {
      return caches.match(request).then(function (cached) {
        return cached || new Response(
          JSON.stringify({ error: "Offline", status: 503 }),
          { status: 503, headers: { "Content-Type": "application/json" } }
        );
      });
    });
}
