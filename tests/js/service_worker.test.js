// What the web page's service worker answers an API read with
// (src/pytodo_qt/web/static/sw.js): the server's answer, stored on its
// way, or the stored one, marked so that the page can tell.
// Run by tests/test_web_pwa.py with `node --test`.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

// Lines end in a line feed here whatever the checkout gave them.
const source = fs
  .readFileSync(
    path.join(
      __dirname,
      "..",
      "..",
      "src",
      "pytodo_qt",
      "web",
      "static",
      "sw.js",
    ),
    "utf8",
  )
  .replace(/\r\n/g, "\n");

const ORIGIN = "https://planner.test:8080";

// The worker's script run against a store and a network of the test's
// own. serverAnswers is called for each request that reaches the
// network: it returns the server's answer, or throws for none.
function worker(serverAnswers) {
  const stores = {};
  const caches = {
    async open(name) {
      const entries = (stores[name] = stores[name] || new Map());
      return {
        async match(request) {
          const stored = entries.get(request.url);
          return stored ? stored.clone() : undefined;
        },
        async put(request, response) {
          entries.set(request.url, response);
        },
      };
    },
  };
  const listeners = {};
  const self = {
    location: { protocol: "https:", origin: ORIGIN },
    addEventListener(name, listener) {
      listeners[name] = listener;
    },
  };
  const fetched = [];
  async function fetch(request) {
    fetched.push(request.url);
    return serverAnswers(request);
  }
  const names = new Function(
    "self",
    "caches",
    "fetch",
    source +
      "\nreturn { networkFirst: networkFirst, store: store," +
      " SOURCE_HEADER: SOURCE_HEADER, STORED_AT_HEADER: STORED_AT_HEADER };",
  )(self, caches, fetch);

  // An event as the browser gives the worker, with what the worker did
  // with it.
  function event(url, method) {
    const waits = [];
    const made = {
      request: new Request(ORIGIN + url, { method: method || "GET" }),
      answer: null,
      waitUntil(promise) {
        waits.push(promise);
      },
      respondWith(promise) {
        made.answer = promise;
      },
      settled() {
        return Promise.all(waits);
      },
    };
    return made;
  }

  return Object.assign(names, {
    caches: caches,
    listeners: listeners,
    fetched: fetched,
    event: event,
    // Reads an address through the worker, as the page does.
    async read(url) {
      const made = event(url);
      listeners.fetch(made);
      const answer = await made.answer;
      await made.settled();
      return answer;
    },
  });
}

function json(body, init) {
  return new Response(
    JSON.stringify(body),
    Object.assign(
      { status: 200, headers: { "Content-Type": "application/json" } },
      init,
    ),
  );
}

function down() {
  throw new TypeError("Failed to fetch");
}

test("the server's answer reaches the page without a mark", async () => {
  const sw = worker(() => json({ lists: ["Home"] }));
  const answer = await sw.read("/api/lists");
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), null);
  assert.equal(answer.headers.get(sw.STORED_AT_HEADER), null);
  assert.deepEqual(await answer.json(), { lists: ["Home"] });
});

test("without the server the stored answer is given, marked, with its time", async () => {
  let up = true;
  const sw = worker(() => (up ? json({ lists: ["Home"] }) : down()));
  const before = Date.now();
  await sw.read("/api/lists");
  const after = Date.now();

  up = false;
  const answer = await sw.read("/api/lists");
  assert.equal(answer.status, 200);
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), "store");
  const storedAt = Number(answer.headers.get(sw.STORED_AT_HEADER));
  assert.ok(storedAt >= before && storedAt <= after);
  assert.equal(answer.headers.get("Content-Type"), "application/json");
  assert.deepEqual(await answer.json(), { lists: ["Home"] });
});

test("the stored answer can be given more than once", async () => {
  let up = true;
  const sw = worker(() => (up ? json({ n: 1 }) : down()));
  await sw.read("/api/status");
  up = false;
  assert.deepEqual(await (await sw.read("/api/status")).json(), { n: 1 });
  assert.deepEqual(await (await sw.read("/api/status")).json(), { n: 1 });
});

test("a later answer of the server replaces the stored one", async () => {
  let body = { n: 1 };
  let up = true;
  const sw = worker(() => (up ? json(body) : down()));
  await sw.read("/api/status");
  body = { n: 2 };
  await sw.read("/api/status");
  up = false;
  assert.deepEqual(await (await sw.read("/api/status")).json(), { n: 2 });
});

test("an answer stored before times were kept has the server's date", async () => {
  const sw = worker(down);
  const cache = await sw.caches.open("pytodo-data");
  await cache.put(
    new Request(ORIGIN + "/api/lists"),
    json({}, { headers: { Date: "Wed, 18 Nov 2026 21:34:00 GMT" } }),
  );
  const answer = await sw.read("/api/lists");
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), "store");
  assert.equal(
    Number(answer.headers.get(sw.STORED_AT_HEADER)),
    Date.UTC(2026, 10, 18, 21, 34, 0),
  );
});

test("an answer stored with no date has the time 0", async () => {
  const sw = worker(down);
  const cache = await sw.caches.open("pytodo-data");
  await cache.put(new Request(ORIGIN + "/api/lists"), json({}));
  const answer = await sw.read("/api/lists");
  assert.equal(answer.headers.get(sw.STORED_AT_HEADER), "0");
});

test("with nothing stored the answer made up says so", async () => {
  const sw = worker(down);
  const answer = await sw.read("/api/lists");
  assert.equal(answer.status, 503);
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), "none");
  assert.deepEqual(await answer.json(), { error: "Offline", status: 503 });
});

test("a refusal of the server is passed on and not stored", async () => {
  let up = true;
  const sw = worker(() =>
    up ? json({ error: "Authentication required" }, { status: 401 }) : down(),
  );
  const refused = await sw.read("/api/lists");
  assert.equal(refused.status, 401);
  assert.equal(refused.headers.get(sw.SOURCE_HEADER), null);
  up = false;
  assert.equal((await sw.read("/api/lists")).status, 503);
});

test("an address that is neither the page's nor the API's is left to the network", () => {
  const sw = worker(down);
  const made = sw.event("/ca.pem");
  sw.listeners.fetch(made);
  assert.equal(made.answer, null);
  assert.deepEqual(sw.fetched, []);
});

test("a change is left to the network", () => {
  const sw = worker(down);
  const made = sw.event("/api/items/1/toggle", "PATCH");
  sw.listeners.fetch(made);
  assert.equal(made.answer, null);
});
