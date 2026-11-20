/* PyTodo-Qt service worker: keeps the page usable without the server. */

// The server replaces the placeholder with a hash of the page's files
// when it serves this script. The script therefore changes whenever any
// of them changes, and the browser installs it again.
var CACHE_VERSION = "__ASSET_VERSION__";
var STATIC_CACHE = "pytodo-static-" + CACHE_VERSION;
// API responses, kept across versions so that an update of the page
// does not discard what can be shown offline.
var DATA_CACHE = "pytodo-data";
// What the page reads on an answer to tell that the server did not give
// it: SOURCE_HEADER is "store" on an answer taken from the store here,
// and "none" on the answer made up when nothing is stored.
// STORED_AT_HEADER is the time a stored answer was stored, in
// milliseconds; "0" when it is not known. The server sends neither.
var SOURCE_HEADER = "X-Pytodo-Source";
var STORED_AT_HEADER = "X-Pytodo-Stored-At";
// How long an API read waits for the server before the stored answer
// is given in its place, in milliseconds. A server that is away
// without refusing the connection, a computer put to sleep, a device
// on another network, keeps a request waiting for a minute and more.
// Shorter than the page's own deadlines for a read (app.js), so that
// the page gets the stored answer and not a read given up.
var STORED_AFTER = 3000;
// After a read that had to be answered from the store the server is
// taken for slow for SLOW_FOR milliseconds, and a read in that time
// waits STORED_SOON_AFTER only: a page that starts without the server
// reads several things in turn. Not no wait at all: a server that is
// back answers well within it, and its answer is then the one given.
var STORED_SOON_AFTER = 300;
var SLOW_FOR = 10000;
var slowUntil = 0;
// How long the worker's own request to the server may go on, whatever
// has been given to the page meanwhile. A request that waits holds one
// of the few connections a browser makes to one server (six in
// Firefox), for a minute and more where the server's address does not
// answer; those of a page that keeps trying add up, and after the
// server is back its answers wait behind them. Longer than
// STORED_AFTER, so that a server that is only slow still has its
// answer stored; no longer than the page's deadline for a read.
var GIVEN_UP_AFTER = 8000;
var STATIC_ASSETS = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/offline-queue.js",
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
    // A read that asks for no stored answer is the network's alone. The
    // page asks in this way whether the server is there: a stored
    // answer would be no answer to that, and a request the page makes
    // itself ends when the page gives it up.
    if (request.cache === "no-store") return;
    event.respondWith(networkFirst(event));
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

// The server's answer, stored on its way to the page; or, when the
// server gives none, or none in time, the answer last stored, marked
// as such. The page takes an unmarked answer for the server's, and
// tells the person when it has none.
async function networkFirst(event) {
  var request = event.request;
  var gaveUp = new AbortController();
  var limit = setTimeout(function () {
    gaveUp.abort();
  }, GIVEN_UP_AFTER);
  var asked = fetch(request, { signal: gaveUp.signal });
  // Whatever is given to the page, the server's answer is stored when
  // it comes within GIVEN_UP_AFTER, and the worker is kept alive until
  // then: a stored answer given in its place is then the newer one
  // next time.
  event.waitUntil(
    asked
      .then(function (response) {
        // The server answers: it is not slow, or no longer.
        slowUntil = 0;
        if (response.ok) return store(request, response.clone());
      })
      .catch(function () {
        /* no answer, or a full store: the page has been answered */
      })
      .then(function () {
        clearTimeout(limit);
      }),
  );

  // A store that cannot be read is as good as empty: the read is the
  // server's to answer.
  var stored;
  try {
    var cache = await caches.open(DATA_CACHE);
    stored = await cache.match(request);
  } catch (_) {
    stored = undefined;
  }
  if (!stored) {
    // Nothing to give in its place: the read waits for the server.
    try {
      return await asked;
    } catch (_) {
      return nothingStored();
    }
  }

  var late = {};
  var timer;
  var first;
  try {
    first = await Promise.race([
      asked,
      new Promise(function (resolve) {
        timer = setTimeout(
          function () {
            resolve(late);
          },
          Date.now() < slowUntil ? STORED_SOON_AFTER : STORED_AFTER,
        );
      }),
    ]);
  } catch (_) {
    // Refused, or no network: there is nothing to wait for.
    clearTimeout(timer);
    return fromStore(stored);
  }
  clearTimeout(timer);
  if (first !== late) return first;
  slowUntil = Date.now() + SLOW_FOR;
  return fromStore(stored);
}

// Stores an answer with the time it was stored.
async function store(request, response) {
  var body = await response.blob();
  var headers = new Headers(response.headers);
  headers.set(STORED_AT_HEADER, String(Date.now()));
  var cache = await caches.open(DATA_CACHE);
  await cache.put(
    request,
    new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: headers,
    }),
  );
}

// A stored answer as the page receives it. One stored before times
// were kept has the server's own date, where that can be read.
function fromStore(stored) {
  var headers = new Headers(stored.headers);
  headers.set(SOURCE_HEADER, "store");
  if (!headers.has(STORED_AT_HEADER)) {
    var sent = Date.parse(headers.get("Date") || "");
    headers.set(STORED_AT_HEADER, String(isNaN(sent) ? 0 : sent));
  }
  return new Response(stored.body, {
    status: stored.status,
    statusText: stored.statusText,
    headers: headers,
  });
}

function nothingStored() {
  var headers = { "Content-Type": "application/json" };
  headers[SOURCE_HEADER] = "none";
  return new Response(JSON.stringify({ error: "Offline", status: 503 }), {
    status: 503,
    headers: headers,
  });
}
