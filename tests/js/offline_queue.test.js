// Rules of the web page's offline queue (src/pytodo_qt/web/static/offline-queue.js).
// Run by tests/test_web_pwa.py with `node --test`.
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");

const rules = require(
  path.join(
    __dirname,
    "..",
    "..",
    "src",
    "pytodo_qt",
    "web",
    "static",
    "offline-queue.js",
  ),
);

const ITEM_A = "11111111-1111-1111-1111-111111111111";
const ITEM_B = "22222222-2222-2222-2222-222222222222";
const LIST = "33333333-3333-3333-3333-333333333333";

function change(timestamp, itemPath, method, body) {
  const opts = { method: method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  return { path: itemPath, opts: opts, timestamp: timestamp };
}

test("itemIdOf names the item of an item request", () => {
  assert.equal(rules.itemIdOf("/items/" + ITEM_A), ITEM_A);
  assert.equal(rules.itemIdOf("/items/" + ITEM_A + "/toggle"), ITEM_A);
  assert.equal(rules.itemIdOf("/items/" + ITEM_A + "/move"), ITEM_A);
});

test("itemIdOf has no item for a request about a list", () => {
  assert.equal(rules.itemIdOf("/lists/" + LIST + "/items"), null);
  assert.equal(rules.itemIdOf("/lists/" + LIST), null);
  assert.equal(rules.itemIdOf(""), null);
  assert.equal(rules.itemIdOf(undefined), null);
});

test("newTimestamp is the current time when no queued change has it", () => {
  assert.equal(rules.newTimestamp([], 1000), 1000);
  assert.equal(
    rules.newTimestamp([change(900, "/items/" + ITEM_A, "DELETE")], 1000),
    1000,
  );
});

test("newTimestamp never repeats a queued change's time", () => {
  const queue = [change(1000, "/items/" + ITEM_A, "DELETE")];
  assert.equal(rules.newTimestamp(queue, 1000), 1001);
  // A clock set back, or a change put back out of order by redo.
  const unordered = [
    change(1005, "/items/" + ITEM_A, "DELETE"),
    change(1002, "/items/" + ITEM_B, "DELETE"),
  ];
  assert.equal(rules.newTimestamp(unordered, 1000), 1006);
});

test("replyOutcome: an accepted change is sent", () => {
  assert.equal(rules.replyOutcome(200), "sent");
  assert.equal(rules.replyOutcome(201), "sent");
  assert.equal(rules.replyOutcome(204), "sent");
});

test("replyOutcome: 409 is a conflict", () => {
  assert.equal(rules.replyOutcome(409), "conflict");
});

test("replyOutcome: a change the server will never accept is refused", () => {
  for (const status of [400, 403, 404, 405, 410, 413, 422]) {
    assert.equal(rules.replyOutcome(status), "refused", String(status));
  }
});

test("replyOutcome: a change that may succeed later is kept", () => {
  for (const status of [undefined, null, 401, 408, 429, 500, 502, 503, 504]) {
    assert.equal(rules.replyOutcome(status), "kept", String(status));
  }
});

test("nextToSend takes the queued changes in order", () => {
  const queue = [
    change(1, "/items/" + ITEM_A + "/toggle", "PATCH"),
    change(2, "/items/" + ITEM_B, "DELETE"),
  ];
  assert.equal(rules.nextToSend(queue, {}, {}).timestamp, 1);
  assert.equal(rules.nextToSend(queue, { 1: true }, {}).timestamp, 2);
  assert.equal(rules.nextToSend(queue, { 1: true, 2: true }, {}), null);
  assert.equal(rules.nextToSend([], {}, {}), null);
});

test("nextToSend passes over the changes behind a kept change to the same item", () => {
  const queue = [
    change(1, "/items/" + ITEM_A + "/toggle", "PATCH"),
    change(2, "/items/" + ITEM_A, "PUT", { priority: 1 }),
    change(3, "/items/" + ITEM_B, "DELETE"),
    change(4, "/lists/" + LIST + "/items", "POST", { reminder: "New" }),
  ];
  const held = { [ITEM_A]: true };
  assert.equal(rules.nextToSend(queue, { 1: true }, held).timestamp, 3);
  assert.equal(
    rules.nextToSend(queue, { 1: true, 3: true }, held).timestamp,
    4,
  );
  assert.equal(
    rules.nextToSend(queue, { 1: true, 3: true, 4: true }, held),
    null,
  );
});

test("withUpdatedAt replaces the time a change was based on", () => {
  const opts = change(1, "/items/" + ITEM_A, "PUT", {
    priority: 1,
    updated_at: 100,
  }).opts;
  const patched = rules.withUpdatedAt(opts, 250);
  assert.deepEqual(JSON.parse(patched.body), { priority: 1, updated_at: 250 });
  assert.equal(patched.method, "PUT");
  assert.deepEqual(patched.headers, { "Content-Type": "application/json" });
  // The queued change itself is left as it was.
  assert.deepEqual(JSON.parse(opts.body), { priority: 1, updated_at: 100 });
});

test("withUpdatedAt leaves a request alone that carries no such time", () => {
  const noBody = { method: "PATCH" };
  assert.equal(rules.withUpdatedAt(noBody, 250), noBody);
  const noTime = change(1, "/lists/" + LIST + "/items", "POST", {
    reminder: "New",
  }).opts;
  assert.equal(rules.withUpdatedAt(noTime, 250), noTime);
  const notJson = { method: "PUT", body: "not json" };
  assert.equal(rules.withUpdatedAt(notJson, 250), notJson);
  assert.equal(rules.withUpdatedAt(undefined, 250), undefined);
});

// --- What is queued -------------------------------------------------------

const tick = (ts, id, base) =>
  change(
    ts,
    "/items/" + id + "/toggle",
    "PATCH",
    base === undefined ? undefined : { updated_at: base },
  );
const update = (ts, id, fields) => change(ts, "/items/" + id, "PUT", fields);
const move = (ts, id, column, base) =>
  change(ts, "/items/" + id + "/move", "PATCH", {
    column: column,
    updated_at: base,
  });
const remove = (ts, id) =>
  change(ts, "/items/" + id, "DELETE", { updated_at: 100 });
const add = (ts, text) =>
  change(ts, "/lists/" + LIST + "/items", "POST", {
    reminder: text,
    parse_nlp: true,
  });
const stamps = (queue) => queue.map((queued) => queued.timestamp);

test("kindOf names what a queued change does", () => {
  assert.equal(rules.kindOf(tick(1, ITEM_A)), "toggle");
  assert.equal(rules.kindOf(update(1, ITEM_A, { priority: 1 })), "update");
  assert.equal(rules.kindOf(move(1, ITEM_A, "Done", 100)), "move");
  assert.equal(rules.kindOf(remove(1, ITEM_A)), "delete");
  assert.equal(rules.kindOf(add(1, "New")), "add");
});

test("kindOf has no name for a request the queue has no rule for", () => {
  assert.equal(
    rules.kindOf(change(1, "/items/" + ITEM_A + "/restore", "PATCH")),
    null,
  );
  assert.equal(
    rules.kindOf(
      change(1, "/items/" + ITEM_A + "/parent", "PATCH", { parent_id: null }),
    ),
    null,
  );
  assert.equal(rules.kindOf(change(1, "/lists/" + LIST, "DELETE")), null);
  assert.equal(
    rules.kindOf(change(1, "/lists", "POST", { name: "New" })),
    null,
  );
  assert.equal(rules.kindOf({ path: "/items/" + ITEM_A }), null);
});

test("withChange: a first tick is queued", () => {
  const queue = rules.withChange([], tick(1, ITEM_A, 100));
  assert.deepEqual(stamps(queue), [1]);
});

test("withChange: a second tick on the same task takes the first back", () => {
  const queue = rules.withChange([tick(1, ITEM_A, 100)], tick(2, ITEM_A, 100));
  assert.deepEqual(queue, []);
});

test("withChange: a third tick is queued again", () => {
  let queue = rules.withChange([], tick(1, ITEM_A, 100));
  queue = rules.withChange(queue, tick(2, ITEM_A, 100));
  queue = rules.withChange(queue, tick(3, ITEM_A, 100));
  assert.deepEqual(stamps(queue), [3]);
});

test("withChange: a tick on another task is left alone", () => {
  const queue = rules.withChange([tick(1, ITEM_A, 100)], tick(2, ITEM_B, 100));
  assert.deepEqual(stamps(queue), [1, 2]);
});

test("withChange: a tick takes back an earlier tick with other changes after it", () => {
  const before = [
    tick(1, ITEM_A, 100),
    update(2, ITEM_A, { priority: 1, updated_at: 100 }),
    tick(3, ITEM_B, 100),
  ];
  const queue = rules.withChange(before, tick(4, ITEM_A, 100));
  assert.deepEqual(stamps(queue), [2, 3]);
});

test("withChange: a field update following a field update is merged, the later value winning", () => {
  const before = [update(1, ITEM_A, { priority: 1, updated_at: 100 })];
  let queue = rules.withChange(
    before,
    update(2, ITEM_A, { priority: 3, updated_at: 100 }),
  );
  queue = rules.withChange(
    queue,
    update(3, ITEM_A, {
      recurrence_type: "daily",
      recurrence_interval: 1,
      updated_at: 100,
    }),
  );
  assert.deepEqual(stamps(queue), [1]);
  assert.deepEqual(JSON.parse(queue[0].opts.body), {
    priority: 3,
    updated_at: 100,
    recurrence_type: "daily",
    recurrence_interval: 1,
  });
  assert.equal(queue[0].opts.method, "PUT");
});

test("withChange: a merged update keeps the time the first was based on", () => {
  const queue = rules.withChange(
    [update(1, ITEM_A, { priority: 1, updated_at: 100 })],
    update(2, ITEM_A, { priority: 3, updated_at: 180 }),
  );
  assert.equal(JSON.parse(queue[0].opts.body).updated_at, 100);
});

test("withChange: a field update after a tick is not merged across it", () => {
  const before = [
    update(1, ITEM_A, { priority: 1, updated_at: 100 }),
    tick(2, ITEM_A, 100),
  ];
  const queue = rules.withChange(
    before,
    update(3, ITEM_A, { recurrence_type: "weekly", updated_at: 100 }),
  );
  assert.deepEqual(stamps(queue), [1, 2, 3]);
  assert.deepEqual(JSON.parse(queue[0].opts.body), {
    priority: 1,
    updated_at: 100,
  });
});

test("withChange: updates to different tasks are not merged", () => {
  const queue = rules.withChange(
    [update(1, ITEM_A, { priority: 1, updated_at: 100 })],
    update(2, ITEM_B, { priority: 3, updated_at: 100 }),
  );
  assert.deepEqual(stamps(queue), [1, 2]);
});

test("withChange: a move following a move replaces its column", () => {
  const queue = rules.withChange(
    [move(1, ITEM_A, "In Progress", 100)],
    move(2, ITEM_A, "Done", 100),
  );
  assert.deepEqual(stamps(queue), [1]);
  assert.deepEqual(JSON.parse(queue[0].opts.body), {
    column: "Done",
    updated_at: 100,
  });
});

test("withChange: a move and a field update are kept apart", () => {
  const queue = rules.withChange(
    [update(1, ITEM_A, { priority: 1, updated_at: 100 })],
    move(2, ITEM_A, "Done", 100),
  );
  assert.deepEqual(stamps(queue), [1, 2]);
});

test("withChange: a delete takes the earlier changes to the task with it", () => {
  const before = [
    tick(1, ITEM_A, 100),
    tick(2, ITEM_B, 100),
    update(3, ITEM_A, { priority: 1, updated_at: 100 }),
  ];
  const queue = rules.withChange(before, remove(4, ITEM_A));
  assert.deepEqual(stamps(queue), [2, 4]);
});

test("withChange: an added task is queued as it is, twice if added twice", () => {
  let queue = rules.withChange([], add(1, "Milk"));
  queue = rules.withChange(queue, add(2, "Milk"));
  assert.deepEqual(stamps(queue), [1, 2]);
});

test("withChange leaves the given queue and its changes as they were", () => {
  const first = update(1, ITEM_A, { priority: 1, updated_at: 100 });
  const before = [first];
  const frozen = JSON.stringify(before);
  rules.withChange(before, update(2, ITEM_A, { priority: 3, updated_at: 100 }));
  rules.withChange(before, tick(3, ITEM_A, 100));
  rules.withChange(before, remove(4, ITEM_A));
  assert.equal(JSON.stringify(before), frozen);
  assert.equal(before[0], first);
});

// --- One earlier step taken back -------------------------------------------

test("withStepTakenBack: a queued delete is taken out", () => {
  const before = [tick(1, ITEM_B, 100)];
  const after = rules.withChange(before, remove(2, ITEM_A));
  assert.deepEqual(stamps(rules.withStepTakenBack(after, before, after)), [1]);
});

test("withStepTakenBack: the changes a delete took with it are put back where they were", () => {
  const before = [
    tick(1, ITEM_A, 100),
    tick(2, ITEM_B, 100),
    update(3, ITEM_A, { priority: 1, updated_at: 100 }),
  ];
  const after = rules.withChange(before, remove(4, ITEM_A));
  const queue = rules.withStepTakenBack(after, before, after);
  assert.deepEqual(stamps(queue), [1, 2, 3]);
  assert.equal(queue[2], before[2]);
});

test("withStepTakenBack: changes made since the step stay", () => {
  const before = [update(1, ITEM_A, { priority: 1, updated_at: 100 })];
  const after = rules.withChange(before, remove(2, ITEM_A));
  let queue = rules.withChange(after, tick(3, ITEM_B, 100));
  queue = rules.withChange(queue, add(4, "Milk"));
  assert.deepEqual(
    stamps(rules.withStepTakenBack(queue, before, after)),
    [1, 3, 4],
  );
});

test("withStepTakenBack: a delete that is no longer queued cannot be taken back", () => {
  const before = [tick(1, ITEM_B, 100)];
  const after = rules.withChange(before, remove(2, ITEM_A));
  // Sent, with everything before it.
  assert.equal(rules.withStepTakenBack([], before, after), null);
  // Sent while a later change still waits.
  assert.equal(
    rules.withStepTakenBack([tick(3, ITEM_B, 100)], before, after),
    null,
  );
});

test("withStepTakenBack: a removed task waiting to be added is put back in its place", () => {
  const before = [add(1, "Milk"), add(2, "Bread"), add(3, "Eggs")];
  const after = before.filter((queued) => queued.timestamp !== 2);
  const queue = after.concat([tick(4, ITEM_A, 100)]);
  const result = rules.withStepTakenBack(queue, before, after);
  assert.deepEqual(stamps(result), [1, 2, 3, 4]);
  assert.equal(result[1], before[1]);
});

test("withStepTakenBack: a step already taken back is not taken back twice", () => {
  const before = [add(1, "Milk")];
  const after = [];
  const once = rules.withStepTakenBack(after, before, after);
  assert.deepEqual(stamps(once), [1]);
  assert.equal(rules.withStepTakenBack(once, before, after), null);
});

test("withStepTakenBack leaves the given queues as they were", () => {
  const before = [update(1, ITEM_A, { priority: 1, updated_at: 100 })];
  const after = rules.withChange(before, remove(2, ITEM_A));
  const queue = rules.withChange(after, tick(3, ITEM_B, 100));
  const frozen = JSON.stringify([queue, before, after]);
  rules.withStepTakenBack(queue, before, after);
  assert.equal(JSON.stringify([queue, before, after]), frozen);
});

// --- What is shown --------------------------------------------------------

const COLUMNS = ["To Do", "In Progress", "Done"];

function task(id, fields) {
  return Object.assign(
    {
      id: id,
      reminder: "Task " + id.slice(0, 1),
      complete: false,
      priority: 2,
      board_column: "To Do",
      time_spent: 0,
      is_recurring: false,
      recurrence_type: null,
      recurrence_interval: 1,
      recurrence_display: "",
      updated_at: 100,
    },
    fields,
  );
}

test("withQueuedChanges: with nothing queued the items are shown as sent, unmarked", () => {
  const items = [task(ITEM_A), task(ITEM_B, { complete: true })];
  const shown = rules.withQueuedChanges(items, [], COLUMNS);
  assert.deepEqual(shown, items);
  assert.equal(shown[0].unsent, undefined);
});

test("withQueuedChanges: a queued tick is shown, and marked", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A), task(ITEM_B)],
    [tick(1, ITEM_A, 100)],
    [],
  );
  assert.equal(shown[0].complete, true);
  assert.equal(shown[0].unsent, true);
  assert.equal(shown[1].complete, false);
  assert.equal(shown[1].unsent, undefined);
});

test("withQueuedChanges: a queued tick on a complete task shows it incomplete", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A, { complete: true })],
    [tick(1, ITEM_A, 100)],
    [],
  );
  assert.equal(shown[0].complete, false);
  assert.equal(shown[0].unsent, true);
});

test("withQueuedChanges: the tick taken back leaves the task as the server has it", () => {
  let queue = rules.withChange([], tick(1, ITEM_A, 100));
  queue = rules.withChange(queue, tick(2, ITEM_A, 100));
  const shown = rules.withQueuedChanges([task(ITEM_A)], queue, []);
  assert.equal(shown[0].complete, false);
  assert.equal(shown[0].unsent, undefined);
});

test("withQueuedChanges: a ticked task goes to the last column, as at the server", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A, { board_column: "In Progress" })],
    [tick(1, ITEM_A, 100)],
    COLUMNS,
  );
  assert.equal(shown[0].board_column, "Done");
});

test("withQueuedChanges: an unticked task leaves the last column", () => {
  const done = { complete: true, board_column: "Done" };
  let shown = rules.withQueuedChanges(
    [task(ITEM_A, done)],
    [tick(1, ITEM_A, 100)],
    COLUMNS,
  );
  assert.equal(shown[0].board_column, "To Do");
  shown = rules.withQueuedChanges(
    [task(ITEM_A, Object.assign({ time_spent: 60 }, done))],
    [tick(1, ITEM_A, 100)],
    COLUMNS,
  );
  assert.equal(shown[0].board_column, "In Progress");
  shown = rules.withQueuedChanges(
    [task(ITEM_A, Object.assign({ time_spent: 60 }, done))],
    [tick(1, ITEM_A, 100)],
    ["Inbox", "Doing", "Review", "Done"],
  );
  assert.equal(shown[0].board_column, "Doing");
  shown = rules.withQueuedChanges(
    [task(ITEM_A, Object.assign({ time_spent: 60 }, done))],
    [tick(1, ITEM_A, 100)],
    ["To Do", "Done"],
  );
  assert.equal(shown[0].board_column, "To Do");
});

test("withQueuedChanges: queued field updates are shown", () => {
  const queue = [update(1, ITEM_A, { priority: 1, updated_at: 100 })];
  const shown = rules.withQueuedChanges([task(ITEM_A)], queue, []);
  assert.equal(shown[0].priority, 1);
  assert.equal(shown[0].unsent, true);
  // The time the page last saw from the server is not a field of the change.
  assert.equal(shown[0].updated_at, 100);
});

test("withQueuedChanges: a queued recurrence is shown in the server's words", () => {
  const cases = [
    [{ recurrence_type: "daily", recurrence_interval: 1 }, true, "Daily"],
    [{ recurrence_type: "weekly", recurrence_interval: 1 }, true, "Weekly"],
    [
      { recurrence_type: "monthly", recurrence_interval: 3 },
      true,
      "Every 3 months",
    ],
    [
      { recurrence_type: "yearly", recurrence_interval: 2 },
      true,
      "Every 2 years",
    ],
    [{ recurrence_type: null, recurrence_interval: 1 }, false, ""],
  ];
  for (const [fields, repeating, label] of cases) {
    const before = task(ITEM_A, {
      is_recurring: true,
      recurrence_type: "daily",
      recurrence_display: "Daily",
    });
    const shown = rules.withQueuedChanges(
      [before],
      [update(1, ITEM_A, fields)],
      [],
    );
    assert.equal(shown[0].is_recurring, repeating, label);
    assert.equal(shown[0].recurrence_display, label);
  }
});

test("withQueuedChanges: a queued move is shown, with the completion that goes with the last column", () => {
  let shown = rules.withQueuedChanges(
    [task(ITEM_A)],
    [move(1, ITEM_A, "In Progress", 100)],
    COLUMNS,
  );
  assert.equal(shown[0].board_column, "In Progress");
  assert.equal(shown[0].complete, false);
  assert.equal(shown[0].unsent, true);
  shown = rules.withQueuedChanges(
    [task(ITEM_A)],
    [move(1, ITEM_A, "Done", 100)],
    COLUMNS,
  );
  assert.equal(shown[0].complete, true);
  shown = rules.withQueuedChanges(
    [task(ITEM_A, { complete: true, board_column: "Done" })],
    [move(1, ITEM_A, "To Do", 100)],
    COLUMNS,
  );
  assert.equal(shown[0].complete, false);
});

test("withQueuedChanges: a move to a column the list does not have is not shown", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A)],
    [move(1, ITEM_A, "Nowhere", 100)],
    COLUMNS,
  );
  assert.equal(shown[0].board_column, "To Do");
});

test("withQueuedChanges: a task with a queued delete is not shown", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A), task(ITEM_B)],
    [remove(1, ITEM_A)],
    [],
  );
  assert.deepEqual(
    shown.map((item) => item.id),
    [ITEM_B],
  );
});

test("withQueuedChanges: changes are applied in the order they were made", () => {
  const queue = [
    update(1, ITEM_A, { priority: 1, updated_at: 100 }),
    tick(2, ITEM_A, 100),
    update(3, ITEM_A, { priority: 3, updated_at: 100 }),
  ];
  const shown = rules.withQueuedChanges([task(ITEM_A)], queue, []);
  assert.equal(shown[0].priority, 3);
  assert.equal(shown[0].complete, true);
});

test("withQueuedChanges: a change to a task that is not in the list is passed over", () => {
  const queue = [
    tick(1, ITEM_B, 100),
    add(2, "New"),
    change(3, "/items/" + ITEM_A + "/restore", "PATCH"),
  ];
  const items = [task(ITEM_A)];
  assert.deepEqual(rules.withQueuedChanges(items, queue, []), items);
});

test("withQueuedChanges leaves the given items as they were", () => {
  const items = [task(ITEM_A), task(ITEM_B)];
  const frozen = JSON.stringify(items);
  rules.withQueuedChanges(
    items,
    [tick(1, ITEM_A, 100), remove(2, ITEM_B)],
    COLUMNS,
  );
  assert.equal(JSON.stringify(items), frozen);
});

test("withQueuedChanges: no items, nothing shown", () => {
  assert.deepEqual(
    rules.withQueuedChanges([], [tick(1, ITEM_A, 100)], COLUMNS),
    [],
  );
  assert.deepEqual(rules.withQueuedChanges(null, [], COLUMNS), []);
});

function board(columns) {
  return {
    id: LIST,
    updated_at: 500,
    board_columns: COLUMNS,
    wip_limits: {},
    columns: columns,
  };
}

test("boardWithQueuedChanges: a ticked card is shown in the last column, marked", () => {
  const sent = board({
    "To Do": [task(ITEM_A), task(ITEM_B)],
    "In Progress": [],
    Done: [],
  });
  const shown = rules.boardWithQueuedChanges(sent, [tick(1, ITEM_A, 100)]);
  assert.deepEqual(
    shown.columns["To Do"].map((card) => card.id),
    [ITEM_B],
  );
  assert.deepEqual(
    shown.columns.Done.map((card) => [card.id, card.complete, card.unsent]),
    [[ITEM_A, true, true]],
  );
  assert.equal(shown.id, LIST);
  assert.equal(shown.updated_at, 500);
});

test("boardWithQueuedChanges: a moved card is shown in its new column", () => {
  const sent = board({ "To Do": [task(ITEM_A)], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [
    move(1, ITEM_A, "In Progress", 100),
  ]);
  assert.equal(shown.columns["To Do"].length, 0);
  assert.equal(shown.columns["In Progress"][0].id, ITEM_A);
});

test("boardWithQueuedChanges: a deleted card is not shown", () => {
  const sent = board({
    "To Do": [task(ITEM_A), task(ITEM_B)],
    "In Progress": [],
    Done: [],
  });
  const shown = rules.boardWithQueuedChanges(sent, [remove(1, ITEM_B)]);
  assert.deepEqual(
    shown.columns["To Do"].map((card) => card.id),
    [ITEM_A],
  );
});

test("boardWithQueuedChanges: a card is filed under the column it is in, whatever its own field says", () => {
  // The server puts a card whose column no longer exists in the first one.
  const sent = board({
    "To Do": [task(ITEM_A, { board_column: "Removed" })],
    "In Progress": [],
    Done: [],
  });
  const shown = rules.boardWithQueuedChanges(sent, []);
  assert.equal(shown.columns["To Do"][0].id, ITEM_A);
});

test("boardWithQueuedChanges: a queued tick on a subtask is shown on its card", () => {
  const parent = task(ITEM_A, {
    subtasks: [task(ITEM_B, { parent_id: ITEM_A })],
  });
  const sent = board({ "To Do": [parent], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [tick(1, ITEM_B, 100)]);
  assert.equal(shown.columns["To Do"][0].subtasks[0].complete, true);
  assert.equal(shown.columns["To Do"][0].unsent, undefined);
});

test("boardWithQueuedChanges leaves the given board as it was, and passes on one without cards", () => {
  const sent = board({ "To Do": [task(ITEM_A)], "In Progress": [], Done: [] });
  const frozen = JSON.stringify(sent);
  rules.boardWithQueuedChanges(sent, [tick(1, ITEM_A, 100)]);
  assert.equal(JSON.stringify(sent), frozen);
  const noCards = { board_columns: COLUMNS, wip_limits: {}, columns: null };
  assert.equal(
    rules.boardWithQueuedChanges(noCards, [tick(1, ITEM_A, 100)]),
    noCards,
  );
  assert.equal(rules.boardWithQueuedChanges(null, []), null);
});

// --- Tasks waiting to be added --------------------------------------------

const OTHER_LIST = "44444444-4444-4444-4444-444444444444";

test("queuedAdds: a row for each task waiting to be added to the list, in order", () => {
  const queue = [
    add(1, "Milk tomorrow !high"),
    tick(2, ITEM_A, 100),
    add(3, "Bread"),
  ];
  assert.deepEqual(rules.queuedAdds(queue, LIST), [
    {
      id: "unsent-1",
      queued_at: 1,
      reminder: "Milk tomorrow !high",
      provisional: true,
      unsent: true,
    },
    {
      id: "unsent-3",
      queued_at: 3,
      reminder: "Bread",
      provisional: true,
      unsent: true,
    },
  ]);
});

test("queuedAdds: tasks waiting for another list are not rows of this one", () => {
  const elsewhere = change(1, "/lists/" + OTHER_LIST + "/items", "POST", {
    reminder: "Elsewhere",
  });
  assert.deepEqual(rules.queuedAdds([elsewhere], LIST), []);
  assert.equal(rules.queuedAdds([elsewhere], OTHER_LIST).length, 1);
});

test("queuedAdds: nothing waiting, no rows", () => {
  assert.deepEqual(rules.queuedAdds([], LIST), []);
  assert.deepEqual(
    rules.queuedAdds([tick(1, ITEM_A, 100), remove(2, ITEM_B)], LIST),
    [],
  );
});

test("queuedAdds: a row id cannot be taken for an item's", () => {
  const row = rules.queuedAdds([add(1700000000000, "Milk")], LIST)[0];
  assert.equal(rules.itemIdOf("/items/" + row.id), null);
});

test("withQueuedChanges does not add rows: the items stay the server's", () => {
  const shown = rules.withQueuedChanges(
    [task(ITEM_A)],
    [add(1, "Milk")],
    COLUMNS,
  );
  assert.equal(shown.length, 1);
});

test("boardWithQueuedChanges: tasks waiting to be added head the first column", () => {
  const sent = board({ "To Do": [task(ITEM_A)], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [
    add(1, "Milk"),
    add(2, "Bread"),
  ]);
  assert.deepEqual(
    shown.columns["To Do"].map((card) => card.id),
    ["unsent-1", "unsent-2", ITEM_A],
  );
  assert.equal(shown.columns["To Do"][0].provisional, true);
  assert.equal(shown.columns["In Progress"].length, 0);
});

test("boardWithQueuedChanges: tasks waiting for another list are not on this board", () => {
  const sent = board({ "To Do": [task(ITEM_A)], "In Progress": [], Done: [] });
  const elsewhere = change(1, "/lists/" + OTHER_LIST + "/items", "POST", {
    reminder: "Elsewhere",
  });
  assert.equal(
    rules.boardWithQueuedChanges(sent, [elsewhere]).columns["To Do"].length,
    1,
  );
});

// --- The queue is stored twice (#77) ---

test("savedIsNewer: the copy in IndexedDB with the higher counter is the later save", () => {
  assert.equal(rules.savedIsNewer(4, { n: 5, queue: [] }), true);
  assert.equal(
    rules.savedIsNewer(0, { n: 1, queue: [change(1, "/x", "POST")] }),
    true,
  );
});

test("savedIsNewer: an equal or lower counter is not", () => {
  assert.equal(rules.savedIsNewer(5, { n: 5, queue: [] }), false);
  assert.equal(rules.savedIsNewer(6, { n: 5, queue: [] }), false);
  assert.equal(rules.savedIsNewer(0, { n: 0, queue: [] }), false);
});

test("savedIsNewer: no copy, or one that cannot be made out, is not", () => {
  assert.equal(rules.savedIsNewer(0, null), false);
  assert.equal(rules.savedIsNewer(0, undefined), false);
  assert.equal(rules.savedIsNewer(0, { n: 3 }), false);
  assert.equal(rules.savedIsNewer(0, { n: "3", queue: [] }), false);
  assert.equal(rules.savedIsNewer(0, { n: 3, queue: "[]" }), false);
  assert.equal(rules.savedIsNewer(0, { queue: [] }), false);
});
