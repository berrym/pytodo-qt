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
      new Response(
        JSON.stringify(
          model.error
            ? { error: model.error }
            : model.current
              ? { current: model.current }
              : { updated_at: "after " + change },
        ),
        { status: model.status || 200 },
      );
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
  const env = Object.assign(
    {
      disk: disk,
      calls: [],
      toasts: [],
      draws: 0,
      undo: [],
      refusedAs: [],
    },
    options,
  );
  // The line of the task sheet that says what became of an edit.
  env.indicator = {
    textContent: "",
    className: "",
    isConnected: true,
    appendChild(label) {
      env.indicator.textContent += label;
    },
  };
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
      // Stores the queue; env.draws counts the times the list is drawn
      // again for it.
      "function saveOfflineQueue(queue, quiet) { env.disk.queue = queue.slice(); if (!quiet) env.draws += 1; }",
      // Ids in the order they are made, by any copy on the device.
      "function newItemId() { env.disk.ids += 1; return 'made-' + env.disk.ids; }",
      "var Date = { now: function () { return 1795200000000 + env.now; } };",
      "function storedTimeOf() { return null; }",
      "function tokenRefused(sentAs) { env.refusedAs.push(sentAs); pinScreenUp = true; }",
      "function pushOfflineUndo() { env.undo.push('step'); }",
      "function clearOfflineUndo() { env.undo.push('cleared'); }",
      functionText("waitingChanges"),
      functionText("queueWaitsFromHere"),
      functionText("enqueueOfflineEdit"),
      functionText("sendOrQueue"),
      functionText("queueChange"),
      // The task sheet: its line for what became of an edit, and what
      // it knows of a task.
      "var document = { getElementById: function (id) { return id === 'detail-save-indicator' ? env.indicator : null; } };",
      "var saveDebounceTimer = null;",
      "var pendingItemFields = {};",
      "var lastSavedFields = null;",
      "function getItemUpdatedAt(itemId) { return env.timeUnknown ? undefined : 5; }",
      "function updateCachedItemTimestamp(itemId, at) { env.calls.push('seen at ' + at); }",
      "function showDetailConflict(itemId, current) { env.calls.push('conflict with ' + JSON.stringify(current)); }",
      "function createUnsentLabel() { return 'Not sent'; }",
      functionText("flushPendingItemFields"),
      functionText("sendItemFields"),
      functionText("saveItemFieldForce"),
      // The board: a card picked up to be moved.
      "var moveMode = env.moving || null;",
      "var cachedBoardData = { board_columns: ['To Do', 'Doing', 'Done'] };",
      "function exitMoveMode() { moveMode = null; }",
      functionText("executeDrop"),
      "var changeFates = {};",
      functionText("changeSent"),
      functionText("queueRunsEnded"),
      functionText("readyQueuedChange"),
      "function authHeaders(extra) { return Object.assign({ Authorization: 'Bearer token' }, extra || {}); }",
      "async function serverFetch(url, opts) { return env.fetch(url, opts || {}); }",
      "function showToast(text) { env.toasts.push(text); }",
      // A read of the list is counted as it begins, as the page's own
      // does (connection.test.js).
      "var listReadsBegun = 0;",
      "async function refreshCurrentList() { listReadsBegun += 1; env.calls.push('refreshCurrentList'); if (env.listRead) await env.listRead(); }",
      "function showQueuedChanges() { env.calls.push('showQueuedChanges'); }",
      "function updatePendingBadge() {}",
      "function updateConnectionIndicator() {}",
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
      "var queueNoticeKept = null;",
      functionText("followStoredQueue"),
      functionText("showStoredQueue"),
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
      "  change: sendOrQueue,",
      "  edit: sendItemFields,",
      "  editLater: function (itemId, fields) { pendingItemFields[itemId] = fields; },",
      "  flush: flushPendingItemFields,",
      "  force: saveItemFieldForce,",
      "  lastSaved: function () { return lastSavedFields; },",
      "  drop: executeDrop,",
      "  undo: undoQueuedDelete,",
      "  running: function () { return replayRunning; },",
      // The browser's word that another copy stored the queue.
      "  notice: followStoredQueue,",
      "  readList: refreshCurrentList,",
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

// Changes that have waited for the server, each with the id the page
// gave it; id null for one queued by an earlier version of the page.
const withId = (name, id, timestamp, fields) =>
  JSON.stringify(
    Object.assign(
      id === null ? {} : { [name]: id || "given-" + timestamp },
      fields,
    ),
  );
const tick = (timestamp, item, id) => ({
  path: "/items/" + item + "/toggle",
  opts: { method: "PATCH", body: withId("change_id", id, timestamp, {}) },
  timestamp: timestamp,
  waiting: true,
});
const remove = (timestamp, item, id) => ({
  path: "/items/" + item,
  opts: { method: "DELETE", body: withId("change_id", id, timestamp, {}) },
  timestamp: timestamp,
  waiting: true,
});
const add = (timestamp, text, id) => ({
  path: "/lists/" + LIST + "/items",
  opts: {
    method: "POST",
    body: withId("id", id, timestamp, { reminder: text }),
  },
  timestamp: timestamp,
  waiting: true,
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

test("a change that has its id keeps it", async () => {
  const disk = device([add(1, "Buy milk"), tick(2, ITEM_A)]);
  const network = server();
  await page(disk, network).send();
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body)),
    [{ id: "given-1", reminder: "Buy milk" }, { change_id: "given-2" }],
  );
  assert.equal(disk.ids, 0);
});

test("a tick without an id is given one, and stored with it, before it is sent", async () => {
  // Queued by an earlier version of the page.
  const disk = device([tick(1, ITEM_A, null)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  assert.equal(JSON.parse(disk.queue[0].opts.body).change_id, "made-1");
  assert.equal(disk.queue[0].sent, true);
  made.silent();
  await run;
  network.slow = false;
  made.found();
  await made.send();
  assert.deepEqual(
    network.bodies.map((body) => JSON.parse(body).change_id),
    ["made-1", "made-1"],
  );
});

test("a change is marked as sent in the stored queue before its request is made", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  let storedWhenSent = null;
  const send = network.fetch;
  network.fetch = (url, opts) => {
    if (opts.method === "PATCH") storedWhenSent = disk.queue[0].sent;
    return send(url, opts);
  };
  const made = page(disk, network);
  await made.send();
  assert.equal(storedWhenSent, true);
  // The undo steps of the page hold the queue as it was before that.
  assert.deepEqual(made.env.undo, ["cleared"]);
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

// --- One way to the server ---
//
// A change is put into the queue first and sent from it at once. Sent
// past the queue, as it was while the server answered, it was lost with
// a page loaded again, and overtook changes that were still waiting.

const toggle = { method: "PATCH", body: "{}" };
const ofItem = (item) => "/items/" + item + "/toggle";

test("a change made while the server answers is in the stored queue while it is on its way", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const done = made.change(ofItem(ITEM_A), toggle);
  await settled();
  assert.equal(disk.queue.length, 1);
  assert.equal(disk.queue[0].sent, true);
  assert.equal(JSON.parse(disk.queue[0].opts.body).change_id, "made-1");
  // Not shown as "Not sent": the server is answering it.
  assert.equal(disk.queue[0].waiting, undefined);
  network.answer();
  assert.equal(await done, "sent");
  assert.deepEqual(disk.queue, []);
  // Whoever made the change says what became of it; the run says nothing.
  assert.deepEqual(made.env.toasts, []);
  assert.deepEqual(made.env.undo, ["cleared"]);
});

test("a change the server refuses as out of date says so, and the list is read", async () => {
  const disk = device([]);
  const network = server();
  network.status = 409;
  const made = page(disk, network);
  assert.equal(await made.change(ofItem(ITEM_A), toggle), "conflict");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.toasts, ["Updated elsewhere \u2014 refreshing"]);
  assert.ok(made.env.calls.includes("refreshCurrentList"));
});

test("a change the server will not accept shows the server's reason", async () => {
  const disk = device([]);
  const network = server();
  network.status = 400;
  network.error = "Invalid column name";
  const made = page(disk, network);
  assert.equal(await made.change(ofItem(ITEM_A), toggle), "refused");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.toasts, ["Invalid column name"]);
});

test("a change made without the server waits, is shown, and can be taken back", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network, { connected: false });
  const step = {};
  assert.equal(await made.change(ofItem(ITEM_A), toggle, step), "queued");
  assert.deepEqual(network.received, []);
  assert.equal(disk.queue.length, 1);
  assert.equal(disk.queue[0].waiting, true);
  assert.equal(disk.queue[0].sent, undefined);
  assert.deepEqual(step.before, []);
  assert.equal(step.after.length, 1);
  assert.deepEqual(made.env.undo, ["step"]);
  assert.deepEqual(made.env.calls, ["sendQueueAgainSoon"]);
});

test("a change that went out and got no answer waits, and is not taken back by an Undo in the page", async () => {
  // The server may have applied it.
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const step = {};
  const done = made.change(ofItem(ITEM_A), toggle, step);
  await settled();
  network.lose();
  assert.equal(await done, "queued");
  assert.equal(disk.queue.length, 1);
  assert.equal(disk.queue[0].sent, true);
  assert.equal(disk.queue[0].waiting, true);
  // The notice of the change still has what it needs to say so.
  assert.equal(step.after.length, 1);
  assert.equal(made.env.undo.includes("step"), false);
  assert.ok(made.env.draws > 0);
});

test("a change given up when the server falls silent is kept in the same way", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const done = made.change(ofItem(ITEM_A), toggle);
  await settled();
  made.silent();
  assert.equal(await done, "queued");
  assert.equal(disk.queue[0].waiting, true);
  assert.equal(network.waiting[0].givenUp, true);
});

test("a new change goes out after the changes that are waiting, not past them", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  const made = page(disk, network);
  assert.equal(
    await made.change("/items/" + ITEM_A, {
      method: "PUT",
      body: JSON.stringify({ priority: 1, updated_at: 5 }),
    }),
    "sent",
  );
  assert.deepEqual(network.received, [TICK_A, "PUT /items/" + ITEM_A]);
  // The edit goes on from the time the tick's answer gave.
  assert.equal(JSON.parse(network.bodies[1]).updated_at, "after " + TICK_A);
  // The tick had waited: the run tells of it, once it has ended.
  await settled();
  assert.deepEqual(made.env.toasts, [
    "Syncing 1 offline change...",
    "All changes synced",
  ]);
});

test("a change made while a run is under way is sent, and its maker told", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  const done = made.change(ofItem(ITEM_B), toggle);
  await settled();
  network.answer();
  await settled();
  network.answer();
  assert.equal(await done, "sent");
  await run;
  assert.deepEqual(network.received, [TICK_A, TICK_B]);
});

test("a second tick takes back a tick that is waiting and has not gone out", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network, { connected: false });
  await made.change(ofItem(ITEM_A), toggle);
  assert.equal(await made.change(ofItem(ITEM_A), toggle), "queued");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(network.received, []);
});

test("a second tick that takes a waiting tick back sends nothing, with the server there", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  const made = page(disk, network);
  assert.equal(await made.change(ofItem(ITEM_A), toggle), "queued");
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(network.received, []);
});

test("a second tick does not take back a tick that is on its way: both go out", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const first = made.change(ofItem(ITEM_A), toggle);
  await settled();
  const second = made.change(ofItem(ITEM_A), toggle);
  await settled();
  assert.equal(disk.queue.length, 2);
  network.answer();
  await settled();
  network.answer();
  assert.deepEqual(await Promise.all([first, second]), ["sent", "sent"]);
  assert.deepEqual(network.received, [TICK_A, TICK_A]);
  const ids = network.bodies.map((body) => JSON.parse(body).change_id);
  assert.notEqual(ids[0], ids[1]);
});

test("another copy of the page sends the change: its maker hears that it is sent", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const other = page(disk, network);
  const made = page(disk, network);
  // The other copy holds the lock, asking the server for a change of
  // its own.
  const others = other.change(ofItem(ITEM_B), toggle);
  await settled();
  const done = made.change(ofItem(ITEM_A), toggle);
  await settled();
  network.answer();
  await settled();
  network.answer();
  assert.equal(await others, "sent");
  assert.equal(await done, "sent");
  assert.deepEqual(network.received, [TICK_B, TICK_A]);
  assert.deepEqual(disk.queue, []);
});

// --- What a run says ---

test("a run that leaves changes marks them as waiting, and they are drawn", async () => {
  const disk = device([]);
  const network = server();
  network.status = 503;
  const made = page(disk, network);
  assert.equal(await made.change(ofItem(ITEM_A), toggle), "queued");
  assert.equal(disk.queue[0].waiting, true);
  assert.ok(made.env.draws >= 2);
  // Nothing had waited when the run began: it says nothing.
  assert.deepEqual(made.env.toasts, []);
});

test("a run tells of the changes that had waited, not of one made a moment ago", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.status = 409;
  const made = page(disk, network);
  assert.equal(await made.change(ofItem(ITEM_B), toggle), "conflict");
  await settled();
  assert.deepEqual(made.env.toasts, [
    "Syncing 1 offline change...",
    "Updated elsewhere \u2014 refreshing",
    "1 change conflicted (data updated elsewhere)",
  ]);
});

// --- The server refuses the device while the queue is sent ---

test("a change the server answers with a refusal of the token: the PIN screen, and the change is kept", async () => {
  const disk = device([tick(1, ITEM_A), tick(2, ITEM_B)]);
  const network = server();
  network.status = 401;
  const made = page(disk, network);
  await made.send();
  assert.deepEqual(made.env.refusedAs, ["Bearer token"]);
  // The change after it is not sent: it would be refused as well.
  assert.deepEqual(network.received, [TICK_A]);
  assert.equal(disk.queue.length, 2);
  assert.deepEqual(made.env.toasts, [
    "Syncing 2 offline changes...",
    "2 changes still pending",
  ]);
});

// --- A delete of a task the server no longer has ---

test('a delete answered "not found" is done: the task is gone', async () => {
  const disk = device([remove(1, ITEM_A)]);
  const network = server();
  network.status = 404;
  const made = page(disk, network);
  await made.send();
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.toasts, [
    "Syncing 1 offline change...",
    "All changes synced",
  ]);
});

test('any other change answered "not found" could not be applied', async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.status = 404;
  const made = page(disk, network);
  await made.send();
  assert.deepEqual(disk.queue, []);
  assert.deepEqual(made.env.toasts, [
    "Syncing 1 offline change...",
    "1 change could not be applied",
  ]);
});

// --- The task sheet ---
//
// An edit made in the sheet was sent past the queue, and dropped with
// "Save failed" where the server gave no answer. It goes through the
// queue as every change does, and the sheet says what became of it.

const EDIT_A = "PUT /items/" + ITEM_A;

test("an edit in the task sheet is sent through the queue, and the sheet says it is saved", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network);
  await made.edit(ITEM_A, { notes: "by Friday" });
  assert.deepEqual(network.received, [EDIT_A]);
  assert.deepEqual(JSON.parse(network.bodies[0]), {
    notes: "by Friday",
    updated_at: 5,
    change_id: "made-1",
  });
  assert.equal(made.env.indicator.textContent, "Saved \u2713");
  assert.deepEqual(made.env.calls, [
    "seen at after " + EDIT_A,
    "refreshCurrentList",
  ]);
  assert.deepEqual(disk.queue, []);
  // Nothing is said of it but in the sheet.
  assert.deepEqual(made.env.toasts, []);
});

test('without the server the edit is kept, and the sheet says "Not sent"', async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network, { connected: false });
  await made.edit(ITEM_A, { notes: "by Friday" });
  assert.deepEqual(network.received, []);
  assert.equal(made.env.indicator.textContent, "Not sent");
  assert.equal(disk.queue.length, 1);
  assert.equal(disk.queue[0].waiting, true);
  assert.equal(disk.queue[0].path, "/items/" + ITEM_A);
  assert.deepEqual(JSON.parse(disk.queue[0].opts.body), {
    notes: "by Friday",
    updated_at: 5,
  });
  assert.deepEqual(made.env.toasts, []);
});

test("an edit given up when the server falls silent is kept in the same way", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const done = made.edit(ITEM_A, { notes: "by Friday" });
  await settled();
  assert.equal(made.env.indicator.textContent, "Saving...");
  made.silent();
  await done;
  assert.equal(made.env.indicator.textContent, "Not sent");
  assert.equal(disk.queue.length, 1);
});

test("a second edit made without the server is merged into the first", async () => {
  const disk = device([]);
  const made = page(disk, server(), { connected: false });
  await made.edit(ITEM_A, { notes: "by Friday" });
  await made.edit(ITEM_A, { priority: 1 });
  assert.equal(disk.queue.length, 1);
  assert.deepEqual(JSON.parse(disk.queue[0].opts.body), {
    notes: "by Friday",
    updated_at: 5,
    priority: 1,
  });
});

test("an edit of a task changed elsewhere shows the sheet's own choice, with the task as the server has it", async () => {
  const disk = device([]);
  const network = server();
  network.status = 409;
  network.current = { id: ITEM_A, updated_at: 9, notes: "by Monday" };
  const made = page(disk, network);
  await made.edit(ITEM_A, { notes: "by Friday" });
  assert.deepEqual(made.env.calls, [
    'conflict with {"id":"' + ITEM_A + '","updated_at":9,"notes":"by Monday"}',
  ]);
  // Refresh or Force Save is offered in the sheet: no notice, and the
  // list is left as it is until one is chosen.
  assert.deepEqual(made.env.toasts, []);
  assert.deepEqual(disk.queue, []);
  // Force Save sends what was last edited.
  assert.deepEqual(made.lastSaved(), { notes: "by Friday", updated_at: 5 });
});

test("Force Save sends the edit again on the task's present state", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network);
  await made.edit(ITEM_A, { notes: "by Friday" });
  await made.force(ITEM_A, { notes: "by Friday", force: true, updated_at: 9 });
  assert.deepEqual(JSON.parse(network.bodies[1]), {
    notes: "by Friday",
    force: true,
    updated_at: 9,
    change_id: "made-2",
  });
  assert.equal(made.env.indicator.textContent, "Saved \u2713");
  // What Force Save would send again is the edit, not itself.
  assert.deepEqual(made.lastSaved(), { notes: "by Friday", updated_at: 5 });
});

test("an edit the server will not accept shows the server's reason in the sheet", async () => {
  const disk = device([]);
  const network = server();
  network.status = 400;
  network.error = "Invalid due date";
  const made = page(disk, network);
  await made.edit(ITEM_A, { due_date: "soon" });
  assert.equal(made.env.indicator.textContent, "Save failed: Invalid due date");
  assert.deepEqual(disk.queue, []);
});

test("a task whose time the page does not know is edited without one", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network, { timeUnknown: true });
  await made.edit(ITEM_A, { notes: "x" });
  assert.deepEqual(JSON.parse(network.bodies[0]), {
    notes: "x",
    change_id: "made-1",
  });
});

test("a sheet that was closed meanwhile is not written to", async () => {
  const disk = device([]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const done = made.edit(ITEM_A, { notes: "by Friday" });
  await settled();
  // Closed, or opened for another task: its line is another one.
  made.env.indicator.isConnected = false;
  made.env.indicator.textContent = "of another task";
  network.answer();
  await done;
  assert.equal(made.env.indicator.textContent, "of another task");
  assert.ok(made.env.calls.includes("refreshCurrentList"));
});

test("the edits the sheet has waiting are all in the queue before the first is answered", async () => {
  // As the page goes out of view: it may not come back.
  const disk = device([]);
  const made = page(disk, server(), { connected: false });
  made.editLater(ITEM_A, { notes: "one" });
  made.editLater(ITEM_B, { notes: "two" });
  const flushed = made.flush();
  assert.deepEqual(
    disk.queue.map((queued) => queued.path),
    ["/items/" + ITEM_A, "/items/" + ITEM_B],
  );
  await flushed;
  // Nothing is left waiting in the page.
  await made.flush();
  assert.equal(disk.queue.length, 2);
});

test("an edit that was waiting in the sheet is sent once, however often the sheet is flushed", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network);
  made.editLater(ITEM_A, { notes: "one" });
  await made.flush();
  await made.flush();
  assert.deepEqual(network.received, [EDIT_A]);
});

// --- A card moved on the board ---

const MOVE_A = "PATCH /items/" + ITEM_A + "/move";
const moving = (from) => ({ itemId: ITEM_A, sourceColumn: from });

test("a card dropped on a column is sent through the queue", async () => {
  const disk = device([]);
  const network = server();
  const made = page(disk, network, { moving: moving("To Do") });
  await made.drop("Doing");
  assert.deepEqual(network.received, [MOVE_A]);
  assert.deepEqual(JSON.parse(network.bodies[0]), {
    column: "Doing",
    updated_at: 5,
    change_id: "made-1",
  });
  assert.deepEqual(made.env.toasts, ['Moved to "Doing"']);
  assert.ok(made.env.calls.includes("refreshCurrentList"));
});

test("without the server the move is kept, and the notice says so", async () => {
  // "Move failed" before, and the card went back to its column.
  const disk = device([]);
  const network = server();
  const made = page(disk, network, {
    connected: false,
    moving: moving("To Do"),
  });
  await made.drop("Done");
  assert.deepEqual(network.received, []);
  assert.equal(disk.queue.length, 1);
  assert.equal(disk.queue[0].waiting, true);
  assert.deepEqual(made.env.toasts, ['Moved to "Done" (completed) (offline)']);
  // Drawn again with the card in its new column.
  assert.ok(made.env.draws > 0);
});

test("a move out of the last column says the task is no longer done", async () => {
  const made = page(device([]), server(), { moving: moving("Done") });
  await made.drop("To Do");
  assert.deepEqual(made.env.toasts, ['Moved to "To Do" (marked incomplete)']);
});

test("a move the server refuses says the server's reason, and no more", async () => {
  const network = server();
  network.status = 400;
  network.error = "Invalid column name";
  const made = page(device([]), network, { moving: moving("To Do") });
  await made.drop("Doing");
  assert.deepEqual(made.env.toasts, ["Invalid column name"]);
});

test("a drop with no card picked up does nothing", async () => {
  const network = server();
  const made = page(device([]), network);
  await made.drop("Doing");
  assert.deepEqual(network.received, []);
});

// --- Another copy stores the queue while a run is under way (#123) ---

const reads = (made) =>
  made.env.calls.filter((call) => call === "refreshCurrentList").length;

test("outside a run a notice is followed at once: a read for a shorter queue, a redraw for another", () => {
  const made = page(device([]), server());
  made.notice(true);
  assert.deepEqual(made.env.calls, ["refreshCurrentList"]);
  made.notice(false);
  assert.deepEqual(made.env.calls, ["refreshCurrentList", "showQueuedChanges"]);
});

test("a notice while this copy waits for the lock is shown by the read at the run's end, once", async () => {
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const first = page(disk, network);
  const second = page(disk, network);
  const runs = [first.send(), second.send()];
  await settled();
  network.answer();
  // The first copy stores the queue without the change.
  second.notice(true);
  assert.deepEqual(second.env.calls, []);
  await Promise.all(runs);
  assert.deepEqual(second.env.calls, [
    "refreshCurrentList",
    "sendQueueAgainSoon",
  ]);
});

test("a notice after the run's read has begun is followed when the run ends", async () => {
  // The read drew the queue as it was before the other copy's write;
  // the run is still counted as under way while the read ends.
  const disk = device([tick(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const first = page(disk, network);
  const second = page(disk, network);
  let readEnds = null;
  second.env.listRead = () =>
    new Promise((resolve) => {
      readEnds = resolve;
    });
  const runs = [first.send(), second.send()];
  await settled();
  network.answer();
  await runs[0];
  await settled();
  // The second copy found the queue sent, and is reading the list.
  assert.equal(reads(second), 1);
  assert.equal(second.running(), true);
  second.notice(true);
  assert.equal(reads(second), 1);
  second.env.listRead = null;
  readEnds();
  await runs[1];
  assert.deepEqual(second.env.calls, [
    "refreshCurrentList",
    "refreshCurrentList",
    "sendQueueAgainSoon",
  ]);
  assert.equal(second.running(), false);
});

// A change the server answers at once: its run ends without a read of
// the list.
const atOnce = (timestamp, item) => {
  const entry = tick(timestamp, item);
  delete entry.waiting;
  return entry;
};

test("a notice during a run that ends without a read is followed when it ends", async () => {
  for (const shorter of [true, false]) {
    const disk = device([atOnce(1, ITEM_A)]);
    const network = server();
    network.slow = true;
    const made = page(disk, network);
    const run = made.send();
    await settled();
    made.notice(shorter);
    assert.deepEqual(made.env.calls, []);
    network.answer();
    await run;
    assert.equal(
      made.env.calls[0],
      shorter ? "refreshCurrentList" : "showQueuedChanges",
    );
    assert.equal(
      made.env.calls.filter((call) => call !== "sendQueueAgainSoon").length,
      1,
    );
  }
});

test("several notices in one run are followed as one, shorter if any of them was", async () => {
  const disk = device([atOnce(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.notice(true);
  made.notice(false);
  network.answer();
  await run;
  assert.deepEqual(made.env.calls, [
    "refreshCurrentList",
    "sendQueueAgainSoon",
  ]);
});

test("a run without a notice follows none, and a notice is followed once", async () => {
  const disk = device([atOnce(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  let run = made.send();
  await settled();
  made.notice(false);
  network.answer();
  await run;
  assert.deepEqual(made.env.calls, ["showQueuedChanges", "sendQueueAgainSoon"]);
  // The next run has no notice of its own.
  disk.queue = [atOnce(2, ITEM_B)];
  run = made.send();
  await settled();
  network.answer();
  await run;
  assert.deepEqual(made.env.calls, [
    "showQueuedChanges",
    "sendQueueAgainSoon",
    "sendQueueAgainSoon",
  ]);
});

test("a read of the list begun for another reason after the notice shows it as well", async () => {
  // A change notice of the server's, for one.
  const disk = device([atOnce(1, ITEM_A)]);
  const network = server();
  network.slow = true;
  const made = page(disk, network);
  const run = made.send();
  await settled();
  made.notice(true);
  made.readList();
  network.answer();
  await run;
  assert.equal(reads(made), 1);
});
