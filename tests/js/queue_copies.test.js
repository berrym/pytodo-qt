// The queue of changes not yet sent is stored twice, in localStorage
// and in IndexedDB, with a counter, and the page starts from the later
// copy (storeQueue, keepQueueCopy, restoreQueue and settleQueueCopies in
// src/pytodo_qt/web/static/app.js; the rule is savedIsNewer in
// offline-queue.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins for the browser's two stores.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const QueueRules = require("../../src/pytodo_qt/web/static/offline-queue.js");

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
      "app.js",
    ),
    "utf8",
  )
  .replace(/\r\n/g, "\n");

function functionText(name) {
  let start = source.indexOf("  function " + name + "(");
  if (start === -1) start = source.indexOf("  async function " + name + "(");
  assert.notEqual(start, -1, name + " is in app.js");
  const end = source.indexOf("\n  }\n", start);
  assert.notEqual(end, -1, "the end of " + name + " is found");
  return source.slice(start, end + 5);
}

function constantText(name) {
  const match = new RegExp("  var " + name + ' = (?:"[^"]*"|\\d+);').exec(
    source,
  );
  assert.ok(match, name + " is in app.js");
  return match[0];
}

// Lets what was waiting on a promise go on.
const settled = () => new Promise((resolve) => setImmediate(resolve));

// IndexedDB as far as the page uses it for the queue: databases by
// name, each with stores of records by key. A request is answered on a
// later turn, as the browser answers it; while disk.held is true the
// answers wait until disk.release().
function database(disk) {
  const waiting = [];
  const later = (run) => {
    if (disk.held) waiting.push(run);
    else setImmediate(run);
  };
  disk.release = () => {
    disk.held = false;
    waiting.splice(0).forEach((run) => setImmediate(run));
  };
  disk.transactions = [];
  return {
    open(name, version) {
      if (disk.refused) throw new Error("no database in this browser");
      const request = {};
      later(() => {
        if (disk.broken) {
          if (request.onerror) request.onerror();
          return;
        }
        const fresh = !(name in disk.databases);
        const stores = (disk.databases[name] = disk.databases[name] || {});
        request.result = {
          createObjectStore(store) {
            stores[store] = stores[store] || {};
          },
          transaction(store, mode, options) {
            if (options && disk.noDurability) {
              throw new TypeError("no such option in this browser");
            }
            assert.ok(store in stores, "the store " + store + " exists");
            disk.transactions.push({ mode: mode, options: options });
            return {
              objectStore() {
                return {
                  get(key) {
                    const read = {};
                    later(() => {
                      read.result = stores[store][key];
                      if (read.onsuccess) read.onsuccess();
                    });
                    return read;
                  },
                  put(value, key) {
                    assert.equal(mode, "readwrite");
                    stores[store][key] = JSON.parse(JSON.stringify(value));
                    disk.writes += 1;
                  },
                };
              },
            };
          },
        };
        assert.equal(version, 1);
        if (fresh && request.onupgradeneeded) request.onupgradeneeded();
        if (request.onsuccess) request.onsuccess();
      });
      return request;
    },
  };
}

// What a device has stored: disk.local is localStorage, disk.databases
// IndexedDB. A page made on the same disk is the page opened again.
function device(local, copy) {
  const disk = {
    local: Object.assign({}, local),
    databases: {},
    writes: 0,
    held: false,
  };
  if (copy !== undefined)
    disk.databases.pytodo_queue = { copy: { queue: copy } };
  return disk;
}

// The copy in IndexedDB, as stored.
function copyOn(disk) {
  const stores = disk.databases.pytodo_queue;
  return stores && stores.copy.queue;
}

// One open copy of the page on a device. Time stands still until
// env.advance(milliseconds) moves it.
function page(disk, options) {
  const env = Object.assign({ disk: disk, calls: [], now: 0 }, options);
  env.QueueRules = QueueRules;
  env.localStorage = {
    getItem: (key) => (key in disk.local ? disk.local[key] : null),
    setItem: (key, value) => {
      disk.local[key] = String(value);
    },
  };
  env.indexedDB = database(disk);
  env.timers = [];
  env.setTimeout = (run, wait) => {
    env.timers.push({ at: env.now + wait, run: run });
  };
  env.advance = (milliseconds) => {
    env.now += milliseconds;
    const due = env.timers.filter((timer) => timer.at <= env.now);
    env.timers = env.timers.filter((timer) => timer.at > env.now);
    due.forEach((timer) => timer.run());
  };
  const called = (name) =>
    "function " + name + "() { env.calls.push('" + name + "'); }";
  return new Function(
    "env",
    [
      "var localStorage = env.localStorage;",
      "var indexedDB = env.indexedDB;",
      "var setTimeout = env.setTimeout;",
      "var QueueRules = env.QueueRules;",
      "var Date = { now: function () { return 1795200000000 + env.now; } };",
      "var replayRunning = Boolean(env.sending);",
      'var OFFLINE_QUEUE_KEY = "pytodo_offline_queue";',
      constantText("QUEUE_COUNTER_KEY"),
      constantText("QUEUE_DB_NAME"),
      constantText("QUEUE_STORE"),
      constantText("QUEUE_RECORD"),
      constantText("QUEUE_COPY_WITHIN"),
      "var queueDb = null;",
      called("updatePendingBadge"),
      called("updateConnectionIndicator"),
      called("showQueuedChanges"),
      called("clearOfflineUndo"),
      called("refreshCurrentList"),
      functionText("getOfflineQueue"),
      functionText("saveOfflineQueue"),
      functionText("queueCounter"),
      functionText("storeQueue"),
      functionText("openQueueDb"),
      functionText("keepQueueCopy"),
      functionText("readQueueCopy"),
      functionText("restoreQueue"),
      functionText("settleQueueCopies"),
      functionText("followStoredQueue"),
      "return {",
      "  env: env,",
      "  queue: getOfflineQueue,",
      "  counter: queueCounter,",
      "  save: saveOfflineQueue,",
      "  restore: restoreQueue,",
      "  keep: keepQueueCopy,",
      "};",
    ].join("\n"),
  )(env);
}

const A = { path: "/items/a/toggle", opts: { method: "POST" }, timestamp: 1 };
const B = { path: "/items/b/toggle", opts: { method: "POST" }, timestamp: 2 };
const C = { path: "/items/c/toggle", opts: { method: "POST" }, timestamp: 3 };

function local(n, queue) {
  const stored = { pytodo_offline_queue: JSON.stringify(queue) };
  if (n !== null) stored.pytodo_offline_queue_n = String(n);
  return stored;
}

// --- Every save goes to both ---

test("a save writes the queue and a counter one higher to both stores", async () => {
  const disk = device(local(4, [A]));
  const made = page(disk);
  made.save([A, B]);
  // localStorage at once: the page reads it in the same breath.
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(made.counter(), 5);
  await settled();
  await settled();
  await settled();
  const copy = copyOn(disk);
  assert.equal(copy.n, 5);
  assert.deepEqual(copy.queue, [A, B]);
  assert.equal(copy.savedAt, 1795200000000);
});

test("the queue's own stored form is as before: the list of changes", () => {
  // An earlier version of the page, open in another tab, reads it.
  const disk = device({});
  page(disk).save([A]);
  assert.equal(disk.local.pytodo_offline_queue, JSON.stringify([A]));
  assert.equal(disk.local.pytodo_offline_queue_n, "1");
});

test("a queue stored before there was a counter counts from 0", async () => {
  const disk = device(local(null, [A]));
  const made = page(disk);
  assert.equal(made.counter(), 0);
  made.save([A, B]);
  assert.equal(made.counter(), 1);
});

test("a counter that cannot be read counts from 0", () => {
  const made = page(device({ pytodo_offline_queue_n: "not a number" }));
  assert.equal(made.counter(), 0);
});

test("an emptied queue is saved like any other", async () => {
  const disk = device(local(7, [A]), { n: 7, queue: [A] });
  const made = page(disk);
  made.save([]);
  await settled();
  await settled();
  await settled();
  assert.deepEqual(copyOn(disk).queue, []);
  assert.equal(copyOn(disk).n, 8);
});

test("a save draws the list again, unless it is asked not to", () => {
  const made = page(device({}));
  made.save([A]);
  assert.deepEqual(made.env.calls, [
    "updatePendingBadge",
    "updateConnectionIndicator",
    "showQueuedChanges",
  ]);
  made.env.calls.length = 0;
  made.save([A, B], true);
  assert.deepEqual(made.env.calls, [
    "updatePendingBadge",
    "updateConnectionIndicator",
  ]);
});

test("the write to IndexedDB is asked to be on disk before it is done", async () => {
  const disk = device({});
  page(disk).save([A]);
  await settled();
  await settled();
  assert.deepEqual(disk.transactions, [
    { mode: "readwrite", options: { durability: "strict" } },
  ]);
});

test("a browser that does not take that request is written to all the same", async () => {
  const disk = device({});
  disk.noDurability = true;
  page(disk).save([A]);
  await settled();
  await settled();
  await settled();
  assert.deepEqual(copyOn(disk).queue, [A]);
});

test("two copies of the page: a save that arrives late does not replace a later one", async () => {
  const disk = device(local(4, [A]));
  const first = page(disk);
  const second = page(disk);
  first.save([A, B]); // counter 5
  second.save([A, B, C]); // counter 6
  // The second copy's write arrives first.
  await second.keep(6, [A, B, C]);
  await settled();
  await settled();
  await first.keep(5, [A, B]);
  await settled();
  await settled();
  assert.equal(copyOn(disk).n, 6);
  assert.deepEqual(copyOn(disk).queue, [A, B, C]);
});

test("without IndexedDB the queue is stored as it was before", async () => {
  for (const fault of ["refused", "broken"]) {
    const disk = device({});
    disk[fault] = true;
    const made = page(disk);
    made.save([A]);
    await settled();
    await settled();
    assert.deepEqual(made.queue(), [A], fault);
    assert.equal(made.counter(), 1);
    assert.equal(disk.writes, 0);
  }
});

// --- The start of the page ---

test("a browser killed before localStorage was on disk: the page starts from IndexedDB", async () => {
  // Two changes were made after the last write that reached the disk.
  const disk = device(local(4, [A]), { n: 6, queue: [A, B, C] });
  const made = page(disk);
  await made.restore();
  assert.deepEqual(made.queue(), [A, B, C]);
  assert.equal(made.counter(), 6);
  // Nothing was drawn or read for it: the page has not started.
  assert.deepEqual(made.env.calls, []);
});

test("changes that had been sent do not come back: an emptied queue is the later copy", async () => {
  // localStorage on disk still holds the queue from before it was sent.
  const disk = device(local(4, [A, B]), { n: 6, queue: [] });
  const made = page(disk);
  await made.restore();
  assert.deepEqual(made.queue(), []);
  assert.equal(made.counter(), 6);
});

test("the same counter in both: nothing is changed and nothing written", async () => {
  const disk = device(local(6, [A, B]), { n: 6, queue: [A, B] });
  const made = page(disk);
  await made.restore();
  await settled();
  await settled();
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(made.counter(), 6);
  assert.equal(disk.writes, 0);
});

test("IndexedDB behind localStorage is brought up to it", async () => {
  // A write to IndexedDB that failed, or never arrived.
  const disk = device(local(6, [A, B]), { n: 4, queue: [A] });
  const made = page(disk);
  await made.restore();
  await settled();
  await settled();
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(copyOn(disk).n, 6);
  assert.deepEqual(copyOn(disk).queue, [A, B]);
});

test("a device that comes from an earlier version: its queue is kept, and copied", async () => {
  const disk = device(local(null, [A, B]));
  const made = page(disk);
  await made.restore();
  await settled();
  await settled();
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(copyOn(disk).n, 0);
  assert.deepEqual(copyOn(disk).queue, [A, B]);
});

test("a copy in IndexedDB that cannot be made out is not taken", async () => {
  for (const copy of [
    { n: 9 },
    { n: "9", queue: [] },
    { queue: [C] },
    "text",
  ]) {
    const disk = device(local(4, [A]), copy);
    const made = page(disk);
    await made.restore();
    assert.deepEqual(made.queue(), [A]);
    assert.equal(made.counter(), 4);
  }
});

test("a start without IndexedDB goes on with localStorage at once", async () => {
  for (const fault of ["refused", "broken"]) {
    const disk = device(local(4, [A]));
    disk[fault] = true;
    const made = page(disk);
    await made.restore();
    assert.deepEqual(made.queue(), [A], fault);
    assert.equal(made.counter(), 4);
  }
});

// --- A database that is slow to answer ---

test("the start waits 2 s for IndexedDB, no longer", async () => {
  const disk = device(local(4, [A]), { n: 6, queue: [A, B] });
  disk.held = true;
  const made = page(disk);
  let started = false;
  made.restore().then(() => {
    started = true;
  });
  await settled();
  made.env.advance(1999);
  await settled();
  assert.equal(started, false);
  made.env.advance(1);
  await settled();
  assert.equal(started, true);
  // The page has started from what localStorage holds.
  assert.deepEqual(made.queue(), [A]);
});

test("a later copy that comes after the start is taken up, and the page follows it", async () => {
  const disk = device(local(4, [A]), { n: 6, queue: [A, B] });
  disk.held = true;
  const made = page(disk);
  const start = made.restore();
  await settled();
  made.env.advance(2000);
  await start;
  disk.release();
  await settled();
  await settled();
  await settled();
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(made.counter(), 6);
  // As for a queue stored by another copy of the page.
  assert.deepEqual(made.env.calls, [
    "clearOfflineUndo",
    "updatePendingBadge",
    "updateConnectionIndicator",
    "refreshCurrentList",
  ]);
});

test("while the queue is being sent the list is left to the end of that run", async () => {
  const disk = device(local(4, [A]), { n: 6, queue: [A, B] });
  disk.held = true;
  const made = page(disk, { sending: true });
  const start = made.restore();
  await settled();
  made.env.advance(2000);
  await start;
  disk.release();
  await settled();
  await settled();
  await settled();
  assert.deepEqual(made.queue(), [A, B]);
  assert.equal(made.env.calls.includes("refreshCurrentList"), false);
});

test("a change made here while IndexedDB was slow is the latest there is", async () => {
  const disk = device(local(4, [A]), { n: 6, queue: [A, B] });
  disk.held = true;
  const made = page(disk);
  const start = made.restore();
  await settled();
  made.env.advance(2000);
  await start;
  made.save([A, C]); // counter 5: below the copy that is yet to be read
  made.env.calls.length = 0;
  disk.release();
  for (let turn = 0; turn < 8; turn++) await settled();
  // The page's queue stands, above the copy read, in both stores.
  assert.deepEqual(made.queue(), [A, C]);
  assert.equal(made.counter(), 7);
  assert.equal(copyOn(disk).n, 7);
  assert.deepEqual(copyOn(disk).queue, [A, C]);
  assert.deepEqual(made.env.calls, []);
});

test("a copy that comes in time causes no redraw", async () => {
  const disk = device(local(4, [A]), { n: 6, queue: [A, B] });
  const made = page(disk);
  await made.restore();
  made.env.advance(5000);
  await settled();
  assert.deepEqual(made.env.calls, []);
});

// --- The page opened again ---

test("what one page saved, the next starts from, whichever store kept it", async () => {
  const disk = device({});
  const before = page(disk);
  before.save([A]);
  before.save([A, B]);
  for (let turn = 0; turn < 6; turn++) await settled();
  // The browser is killed: localStorage on disk is two saves behind.
  disk.local = {};
  const after = page(disk);
  await after.restore();
  assert.deepEqual(after.queue(), [A, B]);
  assert.equal(after.counter(), 2);
  // And it goes on counting from there.
  after.save([A, B, C]);
  assert.equal(after.counter(), 3);
});
