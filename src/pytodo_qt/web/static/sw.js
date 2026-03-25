/* PyTodo-Qt Service Worker — Offline caching and edit queue */

// Refuse to run over insecure HTTP — unregister and clear caches
if (self.location.protocol === "http:") {
  self.addEventListener("install", function () { self.skipWaiting(); });
  self.addEventListener("activate", function (event) {
    event.waitUntil(
      caches.keys().then(function (names) {
        return Promise.all(names.map(function (n) { return caches.delete(n); }));
      }).then(function () {
        return self.registration.unregister();
      }).then(function () {
        return self.clients.matchAll();
      }).then(function (clients) {
        clients.forEach(function (c) { c.postMessage({ type: "http-upgrade-needed" }); });
      })
    );
  });
  // Stop here — do not register caches for HTTP origins
  return;
}

var CACHE_VERSION = "v23";
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

async function cacheFirst(request) {
  var cached = await caches.match(request);
  if (cached) return cached;
  var response = await fetch(request);
  if (response.ok) {
    var cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request) {
  try {
    var response = await fetch(request);
    if (response.ok) {
      var cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    var cached = await caches.match(request);
    return cached || new Response(
      JSON.stringify({ error: "Offline", status: 503 }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}
