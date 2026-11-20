// What the web page's service worker answers an API read with
// (src/pytodo_qt/web/static/sw.js): the server's answer, stored on its
// way, or the stored one, marked so that the page can tell, where the
// server gives none or none in time.
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

// The worker's script run against a store, a network and a clock of
// the test's own. serverAnswers is called for each request that
// reaches the network: it returns the server's answer or a promise of
// it, or throws for none. Time stands still until advance(milliseconds)
// moves it.
function worker(serverAnswers) {
  const clock = { now: 1795000000000, timers: [], next: 1 };
  const setTimeout = (run, wait) => {
    clock.timers.push({ id: clock.next, at: clock.now + wait, run: run });
    return clock.next++;
  };
  const clearTimeout = (id) => {
    clock.timers = clock.timers.filter((timer) => timer.id !== id);
  };
  const FakeDate = { now: () => clock.now, parse: Date.parse };
  // Lets what was waiting on a promise go on.
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  async function advance(milliseconds) {
    const until = clock.now + milliseconds;
    await settle();
    for (;;) {
      const due = clock.timers
        .filter((timer) => timer.at <= until)
        .sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      clock.timers = clock.timers.filter((timer) => timer !== due);
      clock.now = due.at;
      due.run();
      await settle();
    }
    clock.now = until;
    await settle();
  }
  const stores = {};
  const broken = { open: false, match: false };
  const caches = {
    async open(name) {
      if (broken.open) throw new Error("the store cannot be opened");
      const entries = (stores[name] = stores[name] || new Map());
      return {
        async match(request) {
          if (broken.match) throw new Error("the store cannot be read");
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
    "setTimeout",
    "clearTimeout",
    "Date",
    source +
      "\nreturn { networkFirst: networkFirst, store: store," +
      " SOURCE_HEADER: SOURCE_HEADER, STORED_AT_HEADER: STORED_AT_HEADER," +
      " STORED_AFTER: STORED_AFTER, STORED_SOON_AFTER: STORED_SOON_AFTER," +
      " SLOW_FOR: SLOW_FOR };",
  )(self, caches, fetch, setTimeout, clearTimeout, FakeDate);

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
    clock: clock,
    advance: advance,
    broken: broken,
    // Starts a read and says what has become of it so far: "waiting",
    // or the answer.
    begin(url) {
      const made = event(url);
      listeners.fetch(made);
      const state = { outcome: "waiting", event: made };
      made.answer.then((answer) => {
        state.outcome = answer;
      });
      return state;
    },
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
  await sw.read("/api/lists");

  up = false;
  const answer = await sw.read("/api/lists");
  assert.equal(answer.status, 200);
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), "store");
  assert.equal(Number(answer.headers.get(sw.STORED_AT_HEADER)), sw.clock.now);
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

// --- A server that keeps a read waiting ---

// A network whose answers come when the test lets them: answers() gives
// the next waiting read the server's answer, fails() ends it without.
function slowServer() {
  const waiting = [];
  const serverAnswers = () =>
    new Promise((resolve, reject) => {
      waiting.push({ resolve: resolve, reject: reject });
    });
  serverAnswers.answers = (body) => waiting.shift().resolve(json(body));
  serverAnswers.fails = () =>
    waiting.shift().reject(new TypeError("Failed to fetch"));
  serverAnswers.waiting = waiting;
  return serverAnswers;
}

// A worker that has stored an answer for the address and whose server
// then keeps reads waiting.
async function withStored(url, body) {
  const server = slowServer();
  const sw = worker(server);
  const first = sw.begin(url);
  await sw.advance(0);
  server.answers(body);
  await sw.advance(0);
  assert.notEqual(first.outcome, "waiting");
  await first.event.settled();
  return { sw: sw, server: server };
}

test("the waits agree: the stored answer comes before the page gives a read up", () => {
  const sw = worker(down);
  const page = fs
    .readFileSync(
      path.join(
        __dirname,
        "..",
        "..",
        "src",
        "pytodo_qt",
        "web",
        "static",
        "app.js",
      ),
      "utf8",
    )
    .replace(/\r\n/g, "\n");
  const deadline = (name) =>
    Number(new RegExp("var " + name + " = (\\d+);").exec(page)[1]);
  assert.ok(sw.STORED_AFTER < deadline("PROBE_DEADLINE"));
  assert.ok(sw.STORED_AFTER < deadline("READ_DEADLINE"));
  assert.ok(sw.STORED_SOON_AFTER < sw.STORED_AFTER);
});

test("a read kept waiting is given the stored answer after 3 s, not before", async () => {
  const { sw } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(read.outcome, "waiting");
  await sw.advance(1);
  assert.notEqual(read.outcome, "waiting");
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), "store");
  assert.deepEqual(await read.outcome.json(), { lists: ["Home"] });
});

test("a server that answers within the wait is the one heard", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(2000);
  server.answers({ lists: ["Home", "Work"] });
  await sw.advance(0);
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), null);
  assert.deepEqual(await read.outcome.json(), { lists: ["Home", "Work"] });
  // Nothing is left to fire.
  assert.deepEqual(sw.clock.timers, []);
});

test("the server's answer that comes too late is stored all the same", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(3000);
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), "store");
  // The worker is kept alive for it.
  let kept = false;
  read.event.settled().then(() => {
    kept = true;
  });
  await sw.advance(2000);
  assert.equal(kept, false);
  server.answers({ lists: ["Home", "Work"] });
  await sw.advance(0);
  assert.equal(kept, true);

  // The next read kept waiting is given the newer answer.
  await sw.advance(60000);
  const next = sw.begin("/api/lists");
  await sw.advance(3000);
  assert.deepEqual(await next.outcome.json(), { lists: ["Home", "Work"] });
});

test("a read that ends without an answer after the stored one was given is no error", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(3000);
  server.fails();
  await sw.advance(0);
  await read.event.settled();
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), "store");
});

test("after a read kept waiting, the next ones wait 0.3 s for 10 s", async () => {
  const { sw } = await withStored("/api/lists", { lists: ["Home"] });
  sw.begin("/api/lists");
  await sw.advance(3000);

  const soon = sw.begin("/api/lists");
  await sw.advance(299);
  assert.equal(soon.outcome, "waiting");
  await sw.advance(1);
  assert.equal(soon.outcome.headers.get(sw.SOURCE_HEADER), "store");

  // Each read kept waiting starts the 10 s again: this one begins after
  // the first 10 s are over, within the 10 s of the read before it.
  await sw.advance(9900);
  const still = sw.begin("/api/lists");
  await sw.advance(300);
  assert.notEqual(still.outcome, "waiting");

  // 10 s after the last of them a read waits the 3 s again.
  await sw.advance(10000);
  const later = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(later.outcome, "waiting");
  await sw.advance(1);
  assert.notEqual(later.outcome, "waiting");
});

test("a server that is back answers within the short wait, and is heard", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  sw.begin("/api/lists");
  await sw.advance(3000);

  const read = sw.begin("/api/lists");
  await sw.advance(100);
  // The read kept waiting before is first in line; this one is next.
  server.waiting.pop().resolve(json({ lists: ["Home", "Work"] }));
  await sw.advance(0);
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), null);
  assert.deepEqual(await read.outcome.json(), { lists: ["Home", "Work"] });

  // The server is no longer taken for slow: the next read kept
  // waiting has the whole 3 s.
  const next = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(next.outcome, "waiting");
});

test("with nothing stored a read waits for the server, however long", async () => {
  const server = slowServer();
  const sw = worker(server);
  const read = sw.begin("/api/lists/7");
  await sw.advance(120000);
  assert.equal(read.outcome, "waiting");
  server.answers({ items: [] });
  await sw.advance(0);
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), null);
});

test("with nothing stored a read that fails late gets the answer made up", async () => {
  const server = slowServer();
  const sw = worker(server);
  const read = sw.begin("/api/lists/7");
  await sw.advance(75000);
  server.fails();
  await sw.advance(0);
  assert.equal(read.outcome.status, 503);
  assert.equal(read.outcome.headers.get(sw.SOURCE_HEADER), "none");
});

test("a server that refuses at once is not taken for slow", async () => {
  let up = true;
  const sw = worker(() => (up ? json({ n: 1 }) : down()));
  await sw.read("/api/status");
  up = false;
  const refused = sw.begin("/api/status");
  await sw.advance(0);
  assert.equal(refused.outcome.headers.get(sw.SOURCE_HEADER), "store");
  assert.deepEqual(sw.clock.timers, []);
});

test("after a refusal a read kept waiting has the whole 3 s", async () => {
  let server = () => json({ n: 1 });
  const sw = worker((request) => server(request));
  await sw.read("/api/status");
  server = down;
  await sw.read("/api/status");
  server = () => new Promise(() => {});
  const next = sw.begin("/api/status");
  await sw.advance(2999);
  assert.equal(next.outcome, "waiting");
  await sw.advance(1);
  assert.equal(next.outcome.headers.get(sw.SOURCE_HEADER), "store");
});

test("a read kept waiting shortens the wait of a read of another address", async () => {
  // A page that starts without the server reads several things in turn.
  const server = slowServer();
  const sw = worker(server);
  for (const url of ["/api/lists", "/api/lists/7"]) {
    const first = sw.begin(url);
    await sw.advance(0);
    server.answers({ at: url });
    await sw.advance(0);
    await first.event.settled();
  }
  sw.begin("/api/lists");
  await sw.advance(3000);

  const other = sw.begin("/api/lists/7");
  await sw.advance(299);
  assert.equal(other.outcome, "waiting");
  await sw.advance(1);
  assert.equal(other.outcome.headers.get(sw.SOURCE_HEADER), "store");
  assert.deepEqual(await other.outcome.json(), { at: "/api/lists/7" });

  // An answer for one address ends the short wait for the other too.
  const back = sw.begin("/api/lists/7");
  await sw.advance(100);
  server.waiting.pop().resolve(json({ at: "new" }));
  await sw.advance(0);
  assert.equal(back.outcome.headers.get(sw.SOURCE_HEADER), null);
  const next = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(next.outcome, "waiting");
});

test("an answer that comes too late ends the slow period", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(3000);
  server.answers({ lists: ["Home", "Work"] });
  await sw.advance(0);
  await read.event.settled();
  const next = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(next.outcome, "waiting");
});

test("an answer that is not ok ends the slow period", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  sw.begin("/api/lists");
  await sw.advance(3000);
  const read = sw.begin("/api/lists");
  await sw.advance(100);
  server.waiting.pop().resolve(json({ error: "x" }, { status: 401 }));
  await sw.advance(0);
  assert.equal(read.outcome.status, 401);
  const next = sw.begin("/api/lists");
  await sw.advance(2999);
  assert.equal(next.outcome, "waiting");
});

test("a read that fails late does not end the slow period", async () => {
  const { sw, server } = await withStored("/api/lists", { lists: ["Home"] });
  const read = sw.begin("/api/lists");
  await sw.advance(3000);
  server.fails();
  await sw.advance(0);
  await read.event.settled();
  const next = sw.begin("/api/lists");
  await sw.advance(300);
  assert.notEqual(next.outcome, "waiting");
});

test("a store that cannot be read does not keep the server's answer from the page", async () => {
  for (const what of ["open", "match"]) {
    const sw = worker(() => json({ lists: ["Home"] }));
    sw.broken[what] = true;
    const answer = await sw.read("/api/lists");
    assert.equal(answer.status, 200, what);
    assert.equal(answer.headers.get(sw.SOURCE_HEADER), null);
    assert.deepEqual(await answer.json(), { lists: ["Home"] });
  }
});

test("a store that cannot be read, and no server: the answer made up", async () => {
  const sw = worker(down);
  sw.broken.open = true;
  const answer = await sw.read("/api/lists");
  assert.equal(answer.status, 503);
  assert.equal(answer.headers.get(sw.SOURCE_HEADER), "none");
});

test("what is stored for one address is not given for another", async () => {
  const { sw } = await withStored("/api/lists", { lists: ["Home"] });
  const other = sw.begin("/api/lists/7");
  await sw.advance(60000);
  assert.equal(other.outcome, "waiting");
});
