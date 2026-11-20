// How the queue of changes not yet sent is sent: one run at a time
// across every open copy of the page, by a Web Lock; a run asked for
// during a run; a change on its way given up when the server falls
// silent; and the undo of a queued delete (replayOfflineQueue,
// withQueueLock, sendQueuedChanges, giveUpQueuedSend and
// undoQueuedDelete in src/pytodo_qt/web/static/app.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins: a stored queue and a lock that the copies of the
// page share, and a server that answers when the test lets it.
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
const settled = async () => {
  for (let turn = 0; turn < 5; turn++) {
    await new Promise((resolve) => setImmediate(resolve));
  }
};

// The browser's locks, as far as the page uses them: one holder of a
// name at a time, the others in the order they asked.
function lockManager() {
  const manager = { held: {}, waiting: {}, asked: [] };
  manager.request = (name, run) =>
    new Promise((resolve, reject) => {
      manager.asked.push(name);
      // As the browser does it: the lock is given back, and to the
      // next that asked, before the one that held it hears the outcome.
      const release = () => {
        manager.held[name] = false;
        const next = (manager.waiting[name] || []).shift();
        if (next) next();
      };
      const start = () => {
        manager.held[name] = true;
        Promise.resolve()
          .then(run)
          .then(
            (value) => {
              release();
              resolve(value);
            },
            (error) => {
              release();
              reject(error);
            },
          );
      };
      if (manager.held[name]) {
        (manager.waiting[name] = manager.waiting[name] || []).push(start);
      } else {
        start();
      }
    });
  return manager;
}

// What the copies of the page on one device share.
function device(queue) {
  return { queue: queue.slice(), locks: lockManager(), ids: 0 };
}

// A server that takes changes. While slow is true a change waits until
// the test answers it (answer) or the connection is lost (lose); one
// that the page gives up is marked.
function server() {
  const model = {
    received: [],
    bodies: [],
    reads: 0,
    waiting: [],
    slow: false,
    up: true,
  };
  model.fetch = (url, opts) => {
    const method = opts.method || "GET";
    if (!model.up) return Promise.reject(new TypeError("Failed to fetch"));
    if (method === "GET") {
      model.reads += 1;
      return Promise.resolve(new Response("{}", { status: 200 }));
    }
    const change = method + " " + url.replace("/api", "");
    model.received.push(change);
    model.bodies.push(opts.body);
    const reply = () =>
      new Response(JSON.stringify({ updated_at: "after " + change }), {
        status: model.status || 200,
      });
    if (!model.slow) return Promise.resolve(reply());
    return new Promise((resolve, reject) => {
      const held = { change: change, givenUp: false };
      held.answer = () => resolve(reply());
      held.lose = () => reject(new TypeError("Failed to fetch"));
      model.waiting.push(held);
      if (opts.signal) {
        opts.signal.addEventListener("abort", () => {
          held.givenUp = true;
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      }
    });
  };
  model.answer = () => model.waiting.shift().answer();
  model.lose = () => model.waiting.shift().lose();
  return model;
}

// One open copy of the page. options:
//   connected  false for a copy that takes the server for silent
//   noLocks    true for a browser without the Web Locks API
//   listRead   what a read of the list waits for
// Time stands still until env.advance(milliseconds) moves it.
function page(disk, network, options) {
  const env = Object.assign({ disk: disk, calls: [], toasts: [] }, options);
  env.QueueRules = QueueRules;
  env.fetch = network.fetch;
  env.now = 0;
  env.timers = [];
  let nextTimer = 1;
  env.setTimeout = (run, wait) => {
    env.timers.push({ id: nextTimer, at: env.now + wait, run: run });
    return nextTimer++;
  };
  env.clearTimeout = (id) => {
    env.timers = env.timers.filter((timer) => timer.id !== id);
  };
  env.advance = (milliseconds) => {
    const until = env.now + milliseconds;
    for (;;) {
      const due = env.timers
        .filter((timer) => timer.at <= until)
        .sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      env.timers = env.timers.filter((timer) => timer !== due);
      env.now = due.at;
      due.run();
    }
    env.now = until;
  };
  return new Function(
    "env",
    [
      "var serverConnected = env.connected !== false;",
      "var pinScreenUp = false;",
      "var API = '/api';",
      "var navigator = { locks: env.noLocks ? undefined : env.disk.locks };",
      "var QueueRules = env.QueueRules;",
      "var setTimeout = env.setTimeout;",
      "var clearTimeout = env.clearTimeout;",
      constantText("PROBE_DEADLINE"),
      constantText("QUEUE_LOCK"),
      constantText("QUEUED_SEND_ASKED_AFTER"),
      "var queuedSendWatch = null;",
      // Asks the server whether it is there; what follows from no
      // answer is tested in connection.test.js.
      "function probeServer() { env.calls.push('probeServer at ' + env.now); }",
      functionText("watchQueuedSend"),
      "function getOfflineQueue() { return env.disk.queue.slice(); }",
      "function saveOfflineQueue(queue) { env.disk.queue = queue.slice(); }",
      // Ids in the order they are made, by any copy on the device.
      "function newItemId() { env.disk.ids += 1; return 'made-' + env.disk.ids; }",
      functionText("giveQueuedAddAnId"),
      "function authHeaders(extra) { return Object.assign({}, extra || {}); }",
      "async function serverFetch(url, opts) { return env.fetch(url, opts || {}); }",
      "function showToast(text) { env.toasts.push(text); }",
      "async function refreshCurrentList() { env.calls.push('refreshCurrentList'); if (env.listRead) await env.listRead(); }",
      "function sendQueueAgainSoon() { env.calls.push('sendQueueAgainSoon'); }",
      "function takeBackQueuedStep(step) {",
      "  var there = env.disk.queue.some(function (e) { return e.timestamp === step; });",
      "  if (there) env.disk.queue = env.disk.queue.filter(function (e) { return e.timestamp !== step; });",
      "  env.calls.push(there ? 'taken back' : 'no longer queued');",
      "  return there;",
      "}",
      "async function restoreDeletedItem(id) { env.calls.push('restored at the server'); }",
      "var replayRunning = false;",
      "var replayAskedFor = false;",
      "var queuedSend = null;",
      functionText("removeQueuedChange"),
      functionText("withQueueLock"),
      functionText("replayOfflineQueue"),
      functionText("giveUpQueuedSend"),
      functionText("sendQueuedChanges"),
      functionText("showQueueRun"),
      functionText("undoQueuedDelete"),
      "return {",
      "  env: env,",
      "  send: replayOfflineQueue,",
      "  undo: undoQueuedDelete,",
      "  running: function () { return replayRunning; },",
      "  onItsWay: function () { return queuedSend !== null; },",
      // As serverSilent and serverAnswered leave the page.
      "  silent: function () { serverConnected = false; giveUpQueuedSend(); },",
      "  found: function () { serverConnected = true; },",
      "};",
    ].join("\n"),
  )(env);
}

const ITEM_A = "11111111-1111-1111-1111-111111111111";
const ITEM_B = "22222222-2222-2222-2222-222222222222";
const LIST = "33333333-3333-3333-3333-333333333333";

const tick = (timestamp, item) => ({
  path: "/items/" + item + "/toggle",
  opts: { method: "PATCH", body: "{}" },
  timestamp: timestamp,
});
const remove = (timestamp, item) => ({
  path: "/items/" + item,
  opts: { method: "DELETE" },
  timestamp: timestamp,
});
// A task waiting to be added, with the id the page gave it; null for
// one queued by an earlier version of the page, which gave none.
const add = (timestamp, text, id) => ({
  path: "/lists/" + LIST + "/items",
  opts: {
    method: "POST",
    body: JSON.stringify(
      id === null
        ? { reminder: text }
        : { id: id || "given-" + timestamp, reminder: text },
    ),
  },
  timestamp: timestamp,
});

const TICK_A = "PATCH /items/" + ITEM_A + "/toggle";
const TICK_B = "PATCH /items/" + ITEM_B + "/toggle";
const ADD = "POST /lists/" + LIST + "/items";

// --- One copy ---

test("a run sends each queued change once, under the lock, and reads the list after it", async () => {
  const disk = device([tick(1, ITEM_A), add(2, "Buy milk")]);
  const network = server();
  const made = page(disk, network);
  await made.send();
  assert.deepEqual(network.received, [TICK_A, ADD]);
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(disk.locks.asked, ["pytodo-queue-send"]);
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
  assert.deepEqual(made.env.toasts, [
    "Syncing 2 offline changes...",
    "All changes synced",
  ]);
  assert.deepEqual(made.env.calls, [
    "refreshCurrentList",
    "sendQueueAgainSoon",
  ]);
});

test("the server is asked with a read before the first change", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  await page(disk, network).send();
  assert.equal(network.reads, 1);
});

test("an empty queue asks for no lock and nothing of the server", async () => {
  const disk = device([]);
  const network = server();
  await page(disk, network).send();
  assert.deepEqual(disk.locks.asked, []);
  assert.equal(network.reads, 0);
});

test("the lock is given back before the list is read", async () => {
  // A server slow to answer that read must not keep another copy waiting.
  const disk = device([tick(1, ITEM_A)]);
  let listIsRead;
  const made = page(disk, server(), {
    listRead: () =>
      new Promise((resolve) => {
        listIsRead = resolve;
      }),
  });
  const run = made.send();
  await settled();
  assert.ok(made.env.calls.includes("refreshCurrentList"));
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
  // The run is still this copy's own until the list is read.
  assert.equal(made.running(), true);
  listIsRead();
  await run;
  assert.equal(made.running(), false);
});

test("a run whose read gets no answer gives the lock back, and keeps the changes", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.up = false;
  const made = page(disk, network);
  await made.send();
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
  assert.equal(disk.queue.length, 1);
  assert.deepEqual(made.env.toasts, []);
  assert.deepEqual(made.env.calls, ["sendQueueAgainSoon"]);
});

// --- Two copies ---

test("two copies asked at the same moment: each change reaches the server once", async () => {
  const disk = device([tick(1, ITEM_A), add(2, "Buy milk")]);
  const network = server();
  network.slow = true;
  const first = page(disk, network);
  const second = page(disk, network);
  const runs = [first.send(), second.send()];
  await settled();
  // The first has the lock and its first change on its way; the second
  // waits, and has asked the server nothing.
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(network.reads, 1);
  network.answer();
  await settled();
  assert.deepEqual(network.received, [TICK_A, ADD]);
  network.answer();
  await Promise.all(runs);
  assert.deepEqual(network.received, [TICK_A, ADD]);
  assert.deepEqual(disk.queue, []);
  // The second found the queue sent: it asks the server nothing of its
  // own and says nothing, but reads the list, which it left alone
  // while it waited.
  assert.equal(network.reads, 1);
  assert.deepEqual(second.env.toasts, []);
  assert.deepEqual(second.env.calls, [
    "refreshCurrentList",
    "sendQueueAgainSoon",
  ]);
});

test("a copy that waited and finds the queue as it was does not read the list for it", async () => {
  // The first copy's run sent nothing: its read of the server got no
  // answer.
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.up = false;
  const first = page(disk, network);
  const second = page(disk, network);
  await Promise.all([first.send(), second.send()]);
  assert.equal(second.env.calls.includes("refreshCurrentList"), false);
  assert.equal(disk.queue.length, 1);
});

test("a copy that gets the lock after a run that left changes sends those", async () => {
  // The first copy's run ends with a change the server would not take
  // for now; the second copy's run follows it.
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  network.status = 503;
  const first = page(disk, network);
  const second = page(disk, network);
  const runs = [first.send(), second.send()];
  await settled();
  network.answer();
  await settled();
  network.status = 200;
  network.answer();
  await Promise.all(runs);
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
  assert.deepEqual(disk.queue, []);
});

test("a copy that takes the server for silent when it gets the lock asks nothing", async () => {
  const disk = device([tick(1, ITEM_A), tick(2, ITEM_B)]);
  const network = server();
  network.slow = true;
  const first = page(disk, network);
  const second = page(disk, network);
  const runs = [first.send(), second.send()];
  await settled();
  // The server falls silent: both copies notice, and the first gives
  // its change up.
  first.silent();
  second.silent();
  await Promise.all(runs);
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(network.reads, 1);
  assert.equal(disk.queue.length, 2);
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
});

test("without the Web Locks API the copies send as they did before", async () => {
  // Both read the same change as the next, and both send it.
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const first = page(disk, network, { noLocks: true });
  const second = page(disk, network, { noLocks: true });
  const runs = [first.send(), second.send()];
  await settled();
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
  network.answer();
  network.answer();
  await Promise.all(runs);
  assert.deepEqual(disk.queue, []);
});

// --- A run asked for during a run ---

test("a run asked for during a run follows when that one ends", async () => {
  // The first run stops because its change got no answer. The server
  // answers again meanwhile, and a run is asked for: nothing else
  // would send what the first run left.
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.send(); // asked for during the run
  network.slow = false;
  network.lose();
  await run;
  await settled();
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
  assert.deepEqual(disk.queue, []);
  // The run that followed is the one that leaves the queue to its
  // own tries.
  assert.deepEqual(
    made.env.calls.filter((name) => name === "sendQueueAgainSoon"),
    ["sendQueueAgainSoon"],
  );
});

test("it is asked for once, however often", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.send();
  made.send();
  made.send();
  network.slow = false;
  network.lose();
  await run;
  await settled();
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
});

test("no run follows one that was not asked for, or that sent everything", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  network.lose();
  await run;
  await settled();
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(disk.queue.length, 1);
  assert.deepEqual(made.env.calls.slice(-1), ["sendQueueAgainSoon"]);

  const sent = device([tick(1, ITEM_A)]);
  const quick = server();
  quick.slow = true;
  const other = page(sent, quick);
  const all = other.send();
  await settled();
  other.send();
  quick.answer();
  await all;
  await settled();
  assert.deepEqual(quick.received, [TICK_A]);
  assert.equal(quick.reads, 1);
  // The run ends as any other: the queue's own tries start short again.
  assert.deepEqual(other.env.calls.slice(-1), ["sendQueueAgainSoon"]);
});

test("no run follows while the server is taken for silent", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.send();
  made.silent();
  await run;
  await settled();
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(network.reads, 1);
  // The lock is not asked for a second time either.
  assert.equal(disk.locks.asked.length, 1);
  assert.deepEqual(made.env.calls.slice(-1), ["sendQueueAgainSoon"]);
});

test("a run that was asked for is not asked for ever after", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.send();
  network.slow = false;
  network.lose();
  await run;
  await settled();
  assert.deepEqual(disk.queue, []);
  // A later run that leaves a change is followed by none.
  disk.queue = [tick(2, ITEM_B)];
  network.received.length = 0;
  network.status = 503;
  await made.send();
  await settled();
  assert.deepEqual(network.received, [TICK_B]);
  assert.equal(disk.queue.length, 1);
});

// --- The server falls silent with a change on its way ---

test("a tick on its way is given up: its run ends, the lock is free, the change stays", async () => {
  const disk = device([tick(1, ITEM_A), tick(2, ITEM_B)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  assert.equal(disk.locks.held["pytodo-queue-send"], true);
  const onItsWay = network.waiting[0];
  made.silent();
  await run;
  assert.equal(onItsWay.givenUp, true);
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
  assert.equal(made.running(), false);
  // The change after it was not tried: it would have waited as well.
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(disk.queue.length, 2);
  assert.deepEqual(made.env.toasts.slice(-1), ["2 changes still pending"]);
});

test("a delete, an edit and a move on their way are given up in the same way", async () => {
  const changes = [
    remove(1, ITEM_A),
    {
      path: "/items/" + ITEM_A,
      opts: { method: "PUT", body: "{}" },
      timestamp: 1,
    },
    {
      path: "/items/" + ITEM_A + "/move",
      opts: { method: "PATCH", body: "{}" },
      timestamp: 1,
    },
  ];
  for (const change of changes) {
    const disk = device([change]);
    const network = server();
    network.slow = true;
    const made = page(disk, network);
    const run = made.send();
    await settled();
    made.silent();
    await run;
    assert.equal(network.waiting[0].givenUp, true, change.opts.method);
    assert.equal(disk.queue.length, 1);
  }
});

test("an added task on its way is given up like any other change", async () => {
  // It carries its id: sent again, it is the same task to the server.
  const disk = device([add(1, "Buy milk")]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  const onItsWay = network.waiting[0];
  made.silent();
  await run;
  assert.equal(onItsWay.givenUp, true);
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
  assert.equal(disk.queue.length, 1);
  // The next run sends the same id.
  network.slow = false;
  made.found();
  await made.send();
  assert.deepEqual(network.received, [ADD, ADD]);
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body).id),
    ["given-1", "given-1"],
  );
  assert.deepEqual(disk.queue, []);
});

// --- An add queued by an earlier version of the page ---
//
// It has no id. Sent as it is, a second delivery would be a second
// task: it is given an id, and stored with it, before it is sent.

test("an add without an id is given one, and stored with it, before it is sent", async () => {
  const disk = device([add(1, "Buy milk", null)]);
  const network = server();
  let storedWhenSent = null;
  const send = network.fetch;
  network.fetch = (url, opts) => {
    if (opts.method === "POST") {
      storedWhenSent = JSON.parse(disk.queue[0].opts.body).id;
    }
    return send(url, opts);
  };
  const made = page(disk, network);
  await made.send();
  assert.equal(storedWhenSent, "made-1");
  assert.deepEqual(JSON.parse(network.bodies[0]), {
    reminder: "Buy milk",
    id: "made-1",
  });
  assert.deepEqual(disk.queue, []);
});

test("given up and sent again, it carries the id it was given the first time", async () => {
  const disk = device([add(1, "Buy milk", null)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.silent();
  await run;
  assert.equal(JSON.parse(disk.queue[0].opts.body).id, "made-1");
  network.slow = false;
  made.found();
  await made.send();
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body).id),
    ["made-1", "made-1"],
  );
  assert.equal(disk.ids, 1);
});

test("another copy of the page sends the id the first one stored", async () => {
  const disk = device([add(1, "Buy milk", null)]);
  const network = server();
  network.slow = true;
  const first = page(disk, network);
  const second = page(disk, network);
  const run = first.send();
  await settled();
  first.silent();
  await run;
  network.slow = false;
  await second.send();
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body).id),
    ["made-1", "made-1"],
  );
});

test("an add that has its id keeps it, and other changes are given none", async () => {
  const disk = device([add(1, "Buy milk"), tick(2, ITEM_A)]);
  const network = server();
  await page(disk, network).send();
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body)),
    [{ id: "given-1", reminder: "Buy milk" }, {}],
  );
  assert.equal(disk.ids, 0);
});

test("nothing is given up when nothing is on its way", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  const made = page(disk, network);
  made.silent();
  made.found();
  await made.send();
  // Nor is a later change given up for an earlier silence.
  assert.deepEqual(disk.queue, []);
});

test("a change that was given up is sent again by the next run", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.silent();
  await run;
  network.slow = false;
  made.found();
  await made.send();
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
  assert.deepEqual(disk.queue, []);
});

// --- A change on its way from a page that asks nothing else ---
//
// A page out of view does not ask over its WebSocket whether the
// server is there. The question is put for the change itself.

const asked = (made) =>
  made.env.calls.filter((name) => name.startsWith("probeServer"));

test("a change on its way for 3 s: the server is asked whether it is there, and every 5 s after", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.env.advance(2999);
  assert.deepEqual(asked(made), []);
  made.env.advance(1);
  assert.deepEqual(asked(made), ["probeServer at 3000"]);
  made.env.advance(4999);
  assert.deepEqual(asked(made), ["probeServer at 3000"]);
  made.env.advance(1);
  made.env.advance(5000);
  assert.deepEqual(asked(made), [
    "probeServer at 3000",
    "probeServer at 8000",
    "probeServer at 13000",
  ]);
  network.answer();
  await run;
});

test("a change that is answered ends the asking", async () => {
  const disk = device([tick(1, ITEM_A), tick(2, ITEM_B)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.env.advance(2000);
  network.answer();
  await settled();
  // The second change is on its way now, and has its own 3 s.
  made.env.advance(2999);
  assert.deepEqual(asked(made), []);
  made.env.advance(1);
  assert.deepEqual(asked(made), ["probeServer at 5000"]);
  assert.equal(made.onItsWay(), true);
  network.answer();
  await run;
  assert.equal(made.onItsWay(), false);
  made.env.advance(60000);
  assert.deepEqual(asked(made), ["probeServer at 5000"]);
  assert.deepEqual(made.env.timers, []);
});

test("a change that is given up, or lost, ends the asking", async () => {
  for (const ends of ["given up", "lost"]) {
    const disk = device([tick(1, ITEM_A)]);
    const network = server();
    network.slow = true;
    const made = page(disk, network);
    const run = made.send();
    await settled();
    if (ends === "given up") made.silent();
    else network.lose();
    await run;
    made.env.advance(60000);
    assert.deepEqual(asked(made), [], ends);
    assert.deepEqual(made.env.timers, []);
  }
});

test("an added task on its way is asked about as any other change is", async () => {
  const disk = device([add(1, "Buy milk")]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.env.advance(3000);
  assert.deepEqual(asked(made), ["probeServer at 3000"]);
  network.answer();
  await run;
});

test("a change answered at once is not asked about", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  const made = page(disk, network);
  await made.send();
  made.env.advance(60000);
  assert.deepEqual(asked(made), []);
});

// --- Undo of a queued delete ---

test("a queued delete that no run is sending is taken back at once", async () => {
  const disk = device([remove(7, ITEM_A)]);
  const made = page(disk, server());
  await made.undo(7, ITEM_A, "Call the bank");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.calls, ["taken back"]);
  assert.deepEqual(made.env.toasts, ["Call the bank restored"]);
  assert.equal(disk.locks.held["pytodo-queue-send"], false);
});

test("while another copy sends the queue, the undo waits for that run to end", async () => {
  // The delete is on its way from the other copy: which of the two
  // applies is known when its answer has come.
  const disk = device([remove(7, ITEM_A)]);
  const network = server();
  network.slow = true;
  const sending = page(disk, network);
  const undoing = page(disk, network);
  const run = sending.send();
  await settled();
  const undo = undoing.undo(7, ITEM_A, "Call the bank");
  await settled();
  assert.deepEqual(undoing.env.calls, []);
  network.answer();
  await run;
  await undo;
  // The server has deleted the task: it is asked to restore it.
  assert.deepEqual(undoing.env.calls, [
    "no longer queued",
    "restored at the server",
  ]);
});

test("the undo's request to the server is made with the lock given back", async () => {
  const disk = device([]);
  const made = page(disk, server());
  let held = null;
  const calls = made.env.calls;
  calls.push = function (name) {
    if (name === "restored at the server") {
      held = disk.locks.held["pytodo-queue-send"];
    }
    return Array.prototype.push.call(this, name);
  };
  await made.undo(7, ITEM_A, "Call the bank");
  assert.equal(held, false);
});

test("without the Web Locks API the undo works as before", async () => {
  const disk = device([remove(7, ITEM_A)]);
  const made = page(disk, server(), { noLocks: true });
  await made.undo(7, ITEM_A, "Call the bank");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.toasts, ["Call the bank restored"]);
});
