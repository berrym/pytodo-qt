/* PyTodo-Qt service worker: keeps the page usable without the server. */

// The server replaces the placeholder with a hash of the page's files
// when it serves this script. The script therefore changes whenever any
// of them changes, and the browser installs it again.
var CACHE_VERSION = "__ASSET_VERSION__";
var STATIC_CACHE = "pytodo-static-" + CACHE_VERSION;
// API responses, kept across versions so that an update of the page
// does not discard what can be shown offline.
var DATA_CACHE = "pytodo-data";
var STATIC_ASSETS = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png",
];

if (self.location.protocol === "http:") {
  // A worker is for HTTPS. One registered over plain HTTP removes
  // itself and its caches.
  self.addEventListener("install", function () {
    self.skipWaiting();
  });
  self.addEventListener("activate", function (event) {
    event.waitUntil(removeSelf());
  });
} else {
  self.addEventListener("install", onInstall);
  self.addEventListener("activate", onActivate);
  self.addEventListener("fetch", onFetch);
}

function removeSelf() {
  return caches
    .keys()
    .then(function (names) {
      return Promise.all(
        names.map(function (name) {
          return caches.delete(name);
        }),
      );
    })
    .then(function () {
      return self.registration.unregister();
    })
    .then(function () {
      return self.clients.matchAll();
    })
    .then(function (clients) {
      clients.forEach(function (client) {
        client.postMessage({ type: "http-upgrade-needed" });
      });
    });
}

// --- Install: store the page's files under this version ---
function onInstall(event) {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(function (cache) {
      // "reload" goes past the browser's own HTTP cache: the files
      // stored under this version must be the ones it was computed
      // from. The install fails, and the previous worker stays, unless
      // every file is fetched.
      return cache.addAll(
        STATIC_ASSETS.map(function (url) {
          return new Request(url, { cache: "reload" });
        }),
      );
    }),
  );
  self.skipWaiting();
}

// --- Activate: drop the caches of earlier versions ---
function onActivate(event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (names) {
        return Promise.all(
          names
            .filter(function (name) {
              return name !== STATIC_CACHE && name !== DATA_CACHE;
            })
            .map(function (name) {
              return caches.delete(name);
            }),
        );
      })
      .then(function () {
        return self.clients.claim();
      }),
  );
}

// --- Fetch ---
function onFetch(event) {
  var request = event.request;
  // Writes go to the network; app.js queues them when offline.
  if (request.method !== "GET") return;

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API reads: network-first, fall back to the last response stored.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(request));
    return;
  }

  // The page's own files: cache-first.
  if (STATIC_ASSETS.indexOf(url.pathname) !== -1) {
    event.respondWith(cacheFirst(request));
  }
  // Anything else goes to the network untouched.
}

async function cacheFirst(request) {
  var cache = await caches.open(STATIC_CACHE);
  var cached = await cache.match(request, { ignoreSearch: true });
  return cached || fetch(request);
}

async function networkFirst(request) {
  try {
    var response = await fetch(request);
    if (response.ok) {
      var cache = await caches.open(DATA_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    var stored = await caches.open(DATA_CACHE);
    var cached = await stored.match(request);
    return (
      cached ||
      new Response(JSON.stringify({ error: "Offline", status: 503 }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      })
    );
  }
}
