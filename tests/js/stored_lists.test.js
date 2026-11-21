// Every list is kept for use without the server (#121): the page reads
// and stores each list whose stored copy is not the list as the server
// now has it (storeLists, storeListAnswer in
// src/pytodo_qt/web/static/app.js; listCopyIsCurrent in
// offline-queue.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins for the server and for IndexedDB.
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
  const match = new RegExp("  var " + name + " = \\d+;").exec(source);
  assert.ok(match, name + " is in app.js");
  return match[0];
}

const DAY = 86400000;
const NOW = 1800000000000;

// The page as far as storing lists goes. options:
//   current   the id of the list on screen
//   kept      the copies in IndexedDB, {id: {stamp, savedAt}}
//   answers   what a read of each list gives, {id: answer}; an answer
//             is "silent" (no answer), "gone" (the server's 404),
//             "stored" (from the service worker's store), or a list
//   database  false where IndexedDB cannot be had
function page(options) {
  const env = Object.assign(
    { current: "one", kept: {}, answers: {}, reads: [], puts: [], walks: 0 },
    options,
  );
  env.connected = true;
  env.pinScreenUp = false;
  env.now = NOW;
  env.database = options.database === false ? null : {};
  return new Function(
    "env",
    [
      "var QueueRules = env.QueueRules;",
      "var currentListId = env.current;",
      "var serverConnected = true, pinScreenUp = false;",
      "var Date = { now: function () { return env.now; } };",
      // IndexedDB, as far as it is used here: one walk over the stored
      // lists, and puts.
      "async function openIDB() {",
      "  if (env.database === null) return null;",
      "  return { transaction: function () { return { objectStore: function () { return {",
      "    put: function (record) { env.puts.push(record); },",
      "    openCursor: function () {",
      "      env.walks += 1;",
      "      var ids = Object.keys(env.kept), at = 0, walk = { result: null };",
      "      function step() {",
      "        walk.result = at < ids.length ? { value: Object.assign({ listId: ids[at] }, env.kept[ids[at]]), continue: function () { at += 1; step(); } } : null;",
      "        walk.onsuccess();",
      "      }",
      "      setTimeout(step, 0);",
      "      return walk;",
      "    },",
      "  }; } }; } };",
      "}",
      "async function apiAnswer(path) {",
      "  var id = path.slice('/lists/'.length);",
      "  env.reads.push(id);",
      "  if (env.onRead) await env.onRead(id);",
      "  serverConnected = env.connected; pinScreenUp = env.pinScreenUp;",
      "  var answer = env.answers[id];",
      "  if (answer === 'silent') throw new TypeError('Failed to fetch');",
      "  if (answer === 'made up') { var none = new Error('offline'); none.status = 503; none.notTheServers = true; throw none; }",
      "  if (answer === 'gone') { var gone = new Error('List not found'); gone.status = 404; gone.notTheServers = false; throw gone; }",
      "  if (answer === 'stored') return { data: { items: [], stamp: 'old' }, savedAt: 5 };",
      "  return { data: answer, savedAt: null };",
      "}",
      "var storedCopies = null;",
      constantText("LIST_COPY_RENEWED_AFTER"),
      "var storingLists = false;",
      "var listsToStore = null;",
      functionText("storeListAnswer"),
      functionText("readStoredCopies"),
      functionText("storeLists"),
      "return {",
      "  env: env,",
      "  storeLists: storeLists,",
      "  storeListAnswer: storeListAnswer,",
      "  copies: function () { return storedCopies; },",
      "  choose: function (id) { currentListId = id; },",
      "  renewedAfter: LIST_COPY_RENEWED_AFTER,",
      "};",
    ].join("\n"),
  )(Object.assign(env, { QueueRules: QueueRules }));
}

const list = (stamp, ids) => ({
  name: "A list",
  updated_at: 7,
  board_columns: ["To Do", "Done"],
  wip_limits: { "To Do": 3 },
  stamp: stamp,
  items: (ids || ["a"]).map((id) => ({ id: id })),
});
const lists = (stamps) =>
  Object.keys(stamps).map((id) => ({ id: id, stamp: stamps[id] }));

test("a list is renewed after a day, the interval of the sweep", () => {
  assert.equal(page({}).renewedAfter, DAY);
});

test("every list not on screen is read and stored whole", async () => {
  const made = page({
    answers: { two: list("s2", ["x", "y"]), three: list("s3") },
  });
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  // The list on screen is read, and stored, by its own reads.
  assert.deepEqual(made.env.reads, ["two", "three"]);
  assert.deepEqual(made.env.puts, [
    {
      listId: "two",
      name: "A list",
      updated_at: 7,
      items: [{ id: "x" }, { id: "y" }],
      board_columns: ["To Do", "Done"],
      wip_limits: { "To Do": 3 },
      stamp: "s2",
      savedAt: NOW,
    },
    {
      listId: "three",
      name: "A list",
      updated_at: 7,
      items: [{ id: "a" }],
      board_columns: ["To Do", "Done"],
      wip_limits: { "To Do": 3 },
      stamp: "s3",
      savedAt: NOW,
    },
  ]);
});

test("a list whose stored copy has the server's stamp is not read", async () => {
  const made = page({
    kept: {
      two: { stamp: "s2", savedAt: NOW - 1000 },
      three: { stamp: "old", savedAt: NOW - 1000 },
    },
    answers: { three: list("s3") },
  });
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  assert.deepEqual(made.env.reads, ["three"]);
  // And not at the next answer to /lists either: it is stored now.
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  assert.deepEqual(made.env.reads, ["three"]);
  // What is stored is read from IndexedDB once.
  assert.equal(made.env.walks, 1);
});

test("a list that changes at the server is read again", async () => {
  const made = page({ answers: { two: list("s2") } });
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  made.env.answers.two = list("s2b");
  await made.storeLists(lists({ one: "s1", two: "s2b" }));
  assert.deepEqual(made.env.reads, ["two", "two"]);
  assert.equal(made.env.puts[1].stamp, "s2b");
});

test("a copy a day old is read again though it is still the list", async () => {
  const made = page({
    kept: { two: { stamp: "s2", savedAt: NOW - DAY } },
    answers: { two: list("s2") },
  });
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  assert.deepEqual(made.env.reads, ["two"]);
  assert.equal(made.env.puts[0].savedAt, NOW);
});

test("a copy stored before stamps were kept is read again", async () => {
  const made = page({
    kept: { two: { savedAt: NOW - 1000 } },
    answers: { two: list("s2") },
  });
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  assert.deepEqual(made.env.reads, ["two"]);
});

test("the round ends where the server gives no answer", async () => {
  for (const none of ["silent", "made up", "stored"]) {
    const made = page({ answers: { two: none, three: list("s3") } });
    await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
    assert.deepEqual(made.env.reads, ["two"], none);
    assert.deepEqual(made.env.puts, [], none);
    // The next answer to /lists starts another.
    made.env.answers.two = list("s2");
    await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
    assert.deepEqual(made.env.reads, ["two", "two", "three"], none);
  }
});

test("a list the server no longer has is passed over", async () => {
  const made = page({ answers: { two: "gone", three: list("s3") } });
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  assert.deepEqual(made.env.reads, ["two", "three"]);
  assert.deepEqual(
    made.env.puts.map((record) => record.listId),
    ["three"],
  );
});

test("nothing is read once the server is taken for silent", async () => {
  const made = page({ answers: { two: list("s2"), three: list("s3") } });
  made.env.onRead = () => {
    made.env.connected = false;
  };
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  assert.deepEqual(made.env.reads, ["two"]);
});

test("nothing is read or stored behind the PIN screen", async () => {
  const made = page({ answers: { two: list("s2"), three: list("s3") } });
  // The server refuses the device while the first read is on its way.
  made.env.onRead = () => {
    made.env.pinScreenUp = true;
  };
  await made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  assert.deepEqual(made.env.reads, ["two"]);
  assert.deepEqual(made.env.puts, []);
});

test("lists given while a round runs are gone through when it ends", async () => {
  const made = page({ answers: { two: list("s2"), three: list("s3") } });
  let given = false;
  made.env.onRead = () => {
    if (given) return;
    given = true;
    // A list was added at the server meanwhile.
    made.storeLists(lists({ one: "s1", two: "s2", three: "s3" }));
  };
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  // One read at a time, and none twice.
  assert.deepEqual(made.env.reads, ["two", "three"]);
});

test("the list on screen when its turn comes is passed over", async () => {
  const made = page({ answers: { one: list("s1"), two: list("s2") } });
  made.choose("two");
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  assert.deepEqual(made.env.reads, ["one"]);
});

test("without IndexedDB a list is read once all the same", async () => {
  // The service worker has the answer; the list is not read again at
  // every answer to /lists.
  const made = page({ database: false, answers: { two: list("s2") } });
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  assert.deepEqual(made.env.reads, ["two"]);
  assert.deepEqual(made.env.puts, []);
});

test("the list on screen, stored by its own read, is known as stored", async () => {
  const made = page({ answers: { one: list("s1"), two: list("s2") } });
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  await made.storeListAnswer("one", list("s1"));
  // Another list is chosen: the one left has its copy.
  made.choose("two");
  await made.storeLists(lists({ one: "s1", two: "s2" }));
  assert.deepEqual(made.env.reads, ["two"]);
});
