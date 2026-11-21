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
const ITEM_C = "44444444-4444-4444-4444-444444444444";
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
      parent_id: null,
      provisional: true,
      unsent: true,
    },
    {
      id: "unsent-3",
      queued_at: 3,
      reminder: "Bread",
      parent_id: null,
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

// --- A task added with an id of the page's (#117) ---

const subtask = (ts, text, parent, id) =>
  change(ts, "/lists/" + LIST + "/items", "POST", {
    id: id || "id-" + ts,
    reminder: text,
    parent_id: parent,
  });

test("addIdOf: the id an add carries, and none for an add of an earlier version", () => {
  assert.equal(rules.addIdOf(subtask(1, "Oat", ITEM_A, "abc")), "abc");
  assert.equal(rules.addIdOf(add(1, "Milk")), null);
  assert.equal(
    rules.addIdOf(
      change(1, "/lists/" + LIST + "/items", "POST", { id: "", reminder: "x" }),
    ),
    null,
  );
  assert.equal(
    rules.addIdOf(
      change(1, "/lists/" + LIST + "/items", "POST", { id: 7, reminder: "x" }),
    ),
    null,
  );
});

// --- The id a change is known by, and the marks on it (#76) ---

const sent = (queued) => Object.assign({}, queued, { sent: true });
const waiting = (queued) => Object.assign({}, queued, { waiting: true });
const bodyOf = (queued) => JSON.parse(queued.opts.body);
const edit = (ts, id, fields) => change(ts, "/items/" + id, "PUT", fields);

test("hasItsId: an add by its id, a change to a task by its change id", () => {
  assert.equal(rules.hasItsId(subtask(1, "Oat", ITEM_A, "abc")), true);
  assert.equal(rules.hasItsId(add(1, "Milk")), false);
  assert.equal(rules.hasItsId(tick(1, ITEM_A, 100)), false);
  assert.equal(
    rules.hasItsId(edit(1, ITEM_A, { change_id: "c1", priority: 1 })),
    true,
  );
  assert.equal(rules.changeIdOf(edit(1, ITEM_A, { change_id: "c1" })), "c1");
  assert.equal(rules.changeIdOf(edit(1, ITEM_A, { change_id: 7 })), null);
  // A request of no known kind has no id to have.
  assert.equal(rules.hasItsId(change(1, "/lists/" + LIST, "DELETE")), true);
});

test("withItsId gives a change the id of its kind, and leaves one that has it", () => {
  assert.equal(bodyOf(rules.withItsId(add(1, "Milk"), "new")).id, "new");
  const ticked = rules.withItsId(tick(1, ITEM_A, 100), "new");
  assert.deepEqual(bodyOf(ticked), { updated_at: 100, change_id: "new" });
  const has = edit(1, ITEM_A, { change_id: "kept", priority: 1 });
  assert.equal(rules.withItsId(has, "new"), has);
  // The change given is left as it was.
  const before = tick(1, ITEM_A, 100);
  rules.withItsId(before, "new");
  assert.deepEqual(bodyOf(before), { updated_at: 100 });
});

test("withItsId: a change without a body gets one, and says what it is", () => {
  const bare = {
    path: "/items/" + ITEM_A,
    opts: { method: "DELETE" },
    timestamp: 1,
  };
  const given = rules.withItsId(bare, "new");
  assert.deepEqual(bodyOf(given), { change_id: "new" });
  assert.equal(given.opts.headers["Content-Type"], "application/json");
  assert.equal(bare.opts.body, undefined);
  // A type that is named already stands.
  const typed = rules.withItsId(
    {
      path: "/items/" + ITEM_A,
      opts: { method: "DELETE", headers: { "Content-Type": "text/x" } },
      timestamp: 1,
    },
    "new",
  );
  assert.equal(typed.opts.headers["Content-Type"], "text/x");
});

test("readyToSend marks the change as sent, and gives it its id where it has none", () => {
  const queue = [add(1, "Milk"), tick(2, ITEM_A, 100), add(3, "Bread")];
  let made = 0;
  const ready = rules.readyToSend(queue, 2, () => "made-" + ++made);
  assert.deepEqual(stamps(ready), [1, 2, 3]);
  assert.equal(ready[1].sent, true);
  assert.equal(bodyOf(ready[1]).change_id, "made-1");
  assert.equal(ready[0], queue[0]);
  assert.equal(ready[2], queue[2]);
  // The queue given is left as it was.
  assert.equal(queue[1].sent, undefined);
});

test("readyToSend makes no id for a change that has one, and leaves one that is ready", () => {
  const has = edit(1, ITEM_A, { change_id: "kept", priority: 1 });
  let made = 0;
  const ready = rules.readyToSend([has], 1, () => "made-" + ++made);
  assert.equal(made, 0);
  assert.equal(bodyOf(ready[0]).change_id, "kept");
  assert.equal(ready[0].sent, true);
  const again = rules.readyToSend(ready, 1, () => "made-" + ++made);
  assert.equal(again[0], ready[0]);
  assert.equal(made, 0);
  // A change that is not in the queue: nothing is touched.
  assert.deepEqual(
    rules.readyToSend(ready, 9, () => "x"),
    ready,
  );
});

test("waitingOf: the changes that are shown; allWaiting marks them all", () => {
  const queue = [waiting(tick(1, ITEM_A, 100)), tick(2, ITEM_B, 100)];
  assert.deepEqual(stamps(rules.waitingOf(queue)), [1]);
  const marked = rules.allWaiting(queue);
  assert.deepEqual(stamps(rules.waitingOf(marked)), [1, 2]);
  assert.equal(marked[0], queue[0]);
  assert.equal(queue[1].waiting, undefined);
  // Where every change is marked, the queue itself comes back.
  assert.equal(rules.allWaiting(marked), marked);
  assert.equal(rules.allWaiting([]).length, 0);
});

// --- A change that has gone out is delivered as it is ---

test("withChange: a second tick does not take back a tick that has gone out", () => {
  const out = sent(tick(1, ITEM_A, 100));
  const queue = rules.withChange([out], tick(2, ITEM_A, 100));
  assert.deepEqual(stamps(queue), [1, 2]);
  // A third takes the second back, which has not gone out.
  assert.deepEqual(stamps(rules.withChange(queue, tick(3, ITEM_A, 100))), [1]);
});

test("withChange: an edit is not merged into an edit that has gone out", () => {
  const out = sent(edit(1, ITEM_A, { change_id: "c1", priority: 1 }));
  const queue = rules.withChange(
    [out],
    edit(2, ITEM_A, { change_id: "c2", notes: "x" }),
  );
  assert.deepEqual(stamps(queue), [1, 2]);
  assert.deepEqual(bodyOf(queue[0]), { change_id: "c1", priority: 1 });
  assert.deepEqual(bodyOf(queue[1]), { change_id: "c2", notes: "x" });
});

test("withChange: an edit merged into one that has not gone out keeps that one's id", () => {
  const queue = rules.withChange(
    [edit(1, ITEM_A, { change_id: "c1", priority: 1 })],
    edit(2, ITEM_A, { change_id: "c2", notes: "x" }),
  );
  assert.deepEqual(stamps(queue), [1]);
  assert.deepEqual(bodyOf(queue[0]), {
    change_id: "c1",
    priority: 1,
    notes: "x",
  });
});

test("withChange: a delete leaves a change to the task that has gone out, and drops the others", () => {
  const queue = rules.withChange(
    [
      sent(edit(1, ITEM_A, { change_id: "c1", priority: 1 })),
      edit(2, ITEM_A, { change_id: "c2", notes: "x" }),
      tick(3, ITEM_B, 100),
    ],
    remove(4, ITEM_A),
  );
  assert.deepEqual(stamps(queue), [1, 3, 4]);
});

test("carrierOf: the queued change that carries a change after it was put into the queue", () => {
  const own = tick(5, ITEM_A, 100);
  assert.equal(rules.carrierOf(rules.withChange([], own), own), 5);
  // Merged into an earlier edit that has not gone out.
  const merged = edit(6, ITEM_A, { notes: "x" });
  assert.equal(
    rules.carrierOf(
      rules.withChange([edit(2, ITEM_A, { priority: 1 })], merged),
      merged,
    ),
    2,
  );
  // Not into one that has: it is in the queue by itself.
  assert.equal(
    rules.carrierOf(
      rules.withChange([sent(edit(2, ITEM_A, { priority: 1 }))], merged),
      merged,
    ),
    6,
  );
  // A second tick that took the first back is carried by none.
  const second = tick(7, ITEM_A, 100);
  assert.equal(
    rules.carrierOf(rules.withChange([tick(3, ITEM_A, 100)], second), second),
    null,
  );
  // Nor by a tick of the same task that has gone out and stays.
  const third = tick(8, ITEM_A, 100);
  assert.equal(
    rules.carrierOf(
      rules.withChange(
        [sent(tick(3, ITEM_A, 100)), tick(4, ITEM_A, 100)],
        third,
      ),
      third,
    ),
    null,
  );
  // An edit of another task, or a change of another kind, is no carrier.
  assert.equal(
    rules.carrierOf([edit(2, ITEM_B, { priority: 1 }), tick(3, ITEM_A, 100)], {
      path: "/items/" + ITEM_A,
      opts: { method: "PUT", body: "{}" },
      timestamp: 9,
    }),
    null,
  );
});

test("withStepTakenBack: a change that has gone out is not taken back", () => {
  // The server may have applied it.
  const before = [];
  const after = [tick(1, ITEM_A, 100)];
  assert.deepEqual(rules.withStepTakenBack(after, before, after), []);
  assert.equal(rules.withStepTakenBack([sent(after[0])], before, after), null);
});

test("replyOutcome: a delete of a task the server no longer has is done", () => {
  assert.equal(rules.replyOutcome(404, "delete"), "sent");
  assert.equal(rules.replyOutcome(404, "toggle"), "refused");
  assert.equal(rules.replyOutcome(404), "refused");
  assert.equal(rules.replyOutcome(409, "delete"), "conflict");
});

test("queuedAdds: a subtask waiting to be added names the task it was added to", () => {
  const rows = rules.queuedAdds([subtask(1, "Oat", ITEM_A)], LIST);
  assert.deepEqual(rows, [
    {
      id: "unsent-1",
      queued_at: 1,
      reminder: "Oat",
      parent_id: ITEM_A,
      provisional: true,
      unsent: true,
    },
  ]);
});

// --- The subtasks of a task that is deleted ---

test("withQueuedChanges: the subtasks of a deleted task go to the top level", () => {
  // As the server puts them there when it deletes the task.
  const items = [
    task(ITEM_A),
    task(ITEM_B, { parent_id: ITEM_A }),
    task(ITEM_C, { parent_id: ITEM_A }),
  ];
  const shown = rules.withQueuedChanges(items, [remove(1, ITEM_A)], COLUMNS);
  assert.deepEqual(
    shown.map((item) => [item.id, item.parent_id]),
    [
      [ITEM_B, null],
      [ITEM_C, null],
    ],
  );
  // The tasks given are left as they were.
  assert.equal(items[1].parent_id, ITEM_A);
});

test("withQueuedChanges: the subtasks of another task stay where they are", () => {
  const items = [
    task(ITEM_A),
    task(ITEM_B),
    task(ITEM_C, { parent_id: ITEM_B }),
  ];
  const shown = rules.withQueuedChanges(items, [remove(1, ITEM_A)], COLUMNS);
  assert.deepEqual(
    shown.map((item) => [item.id, item.parent_id || null]),
    [
      [ITEM_B, null],
      [ITEM_C, ITEM_B],
    ],
  );
});

test("boardWithQueuedChanges: the subtasks of a deleted card become cards of their own", () => {
  const parent = task(ITEM_A, {
    subtasks: [
      task(ITEM_B, { parent_id: ITEM_A, board_column: "In Progress" }),
      task(ITEM_C, { parent_id: ITEM_A, board_column: "" }),
    ],
  });
  const sent = board({ "To Do": [parent], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [remove(1, ITEM_A)]);
  // Each in its column; in the first where it has none.
  assert.deepEqual(
    shown.columns["To Do"].map((card) => [card.id, card.parent_id]),
    [[ITEM_C, null]],
  );
  assert.deepEqual(
    shown.columns["In Progress"].map((card) => [card.id, card.parent_id]),
    [[ITEM_B, null]],
  );
  // The board given is left as it was.
  assert.equal(sent.columns["To Do"][0].subtasks[0].parent_id, ITEM_A);
});

test("boardWithQueuedChanges: a subtask deleted with its task is no card", () => {
  const parent = task(ITEM_A, {
    subtasks: [task(ITEM_B, { parent_id: ITEM_A })],
  });
  const sent = board({ "To Do": [parent], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [
    remove(1, ITEM_B),
    remove(2, ITEM_A),
  ]);
  assert.deepEqual(shown.columns["To Do"], []);
});

// --- A subtask waiting to be added, on the board ---

test("boardWithQueuedChanges: a waiting subtask is listed in its task's card, not as a card", () => {
  const parent = task(ITEM_A, {
    subtasks: [task(ITEM_B, { parent_id: ITEM_A })],
  });
  const sent = board({
    "To Do": [task(ITEM_C)],
    "In Progress": [parent],
    Done: [],
  });
  const shown = rules.boardWithQueuedChanges(sent, [subtask(5, "Oat", ITEM_A)]);
  assert.deepEqual(
    shown.columns["To Do"].map((card) => card.id),
    [ITEM_C],
  );
  const subtasks = shown.columns["In Progress"][0].subtasks;
  assert.deepEqual(
    subtasks.map((sub) => [sub.id, Boolean(sub.provisional)]),
    [
      [ITEM_B, false],
      ["unsent-5", true],
    ],
  );
  // The board given is left as it was.
  assert.equal(sent.columns["In Progress"][0].subtasks.length, 1);
});

test("boardWithQueuedChanges: a waiting subtask of a card with no subtasks yet", () => {
  const sent = board({ "To Do": [task(ITEM_A)], "In Progress": [], Done: [] });
  const shown = rules.boardWithQueuedChanges(sent, [subtask(5, "Oat", ITEM_A)]);
  assert.deepEqual(
    shown.columns["To Do"][0].subtasks.map((sub) => sub.id),
    ["unsent-5"],
  );
});

test("boardWithQueuedChanges: a waiting subtask whose task is not shown is a card at the top", () => {
  // The task was deleted in the page after the subtask was added, or
  // is no card of the board.
  const sent = board({
    "To Do": [task(ITEM_A), task(ITEM_C)],
    "In Progress": [],
    Done: [],
  });
  const shown = rules.boardWithQueuedChanges(sent, [
    subtask(5, "Oat", ITEM_A),
    remove(6, ITEM_A),
  ]);
  assert.deepEqual(
    shown.columns["To Do"].map((card) => card.id),
    ["unsent-5", ITEM_C],
  );
  // Taken back, the delete leaves the subtask in its task's card again.
  const back = rules.boardWithQueuedChanges(sent, [subtask(5, "Oat", ITEM_A)]);
  assert.deepEqual(
    back.columns["To Do"].map((card) => card.id),
    [ITEM_A, ITEM_C],
  );
  assert.equal(back.columns["To Do"][0].subtasks[0].id, "unsent-5");
});

test("a delete of a task leaves a subtask waiting to be added to it in the queue", () => {
  // The subtask is sent with the rest: the server adds it at the top
  // level where its task is gone by then.
  const queue = rules.withChange(
    [subtask(5, "Oat", ITEM_A)],
    remove(6, ITEM_A),
  );
  assert.deepEqual(stamps(queue), [5, 6]);
  assert.equal(JSON.parse(queue[0].opts.body).parent_id, ITEM_A);
});

// --- Where a waiting task is drawn in the list ---

test("placedAdds: a waiting subtask goes under its task, any other waiting task to the top", () => {
  const waiting = rules.queuedAdds(
    [add(1, "Milk"), subtask(2, "Oat", ITEM_A), subtask(3, "Rye", ITEM_A)],
    LIST,
  );
  const placed = rules.placedAdds(waiting, [ITEM_A, ITEM_B]);
  assert.deepEqual(
    placed.atTop.map((row) => row.id),
    ["unsent-1"],
  );
  assert.deepEqual(
    placed.under[ITEM_A].map((row) => row.id),
    ["unsent-2", "unsent-3"],
  );
  assert.deepEqual(placed.under[ITEM_B], []);
});

test("placedAdds: a subtask whose task is not among the top-level tasks shown is at the top", () => {
  // Its task was deleted in the page meanwhile, or is itself a subtask.
  const waiting = rules.queuedAdds([subtask(2, "Oat", ITEM_C)], LIST);
  const placed = rules.placedAdds(waiting, [ITEM_A]);
  assert.deepEqual(
    placed.atTop.map((row) => row.id),
    ["unsent-2"],
  );
  assert.deepEqual(placed.under, { [ITEM_A]: [] });
});

test("placedAdds: nothing waiting, and no task shown", () => {
  assert.deepEqual(rules.placedAdds([], []), { atTop: [], under: {} });
});

// --- The board of a list (#121) ---

const BOARD_COLUMNS = ["To Do", "Doing", "Done"];
const BOARD_LIST = "99999999-9999-9999-9999-999999999999";
const boardCard = (id, column, parent) => ({
  id: id,
  board_column: column,
  parent_id: parent || null,
});
// A list as the server answers it.
const listOf = (limits, items, columns) => ({
  id: BOARD_LIST,
  name: "Home",
  updated_at: 77,
  board_columns: columns || BOARD_COLUMNS,
  wip_limits: limits,
  items: items,
});
const idsIn = (board) =>
  Object.keys(board.columns).map((name) => [
    name,
    board.columns[name].map((one) => one.id),
  ]);

test("boardOfList: each task is a card in its column, in the order given", () => {
  const board = rules.boardOfList(
    listOf({ Doing: 2 }, [
      boardCard("a", "Doing"),
      boardCard("b", "To Do"),
      boardCard("c", "Doing"),
    ]),
  );
  assert.deepEqual(idsIn(board), [
    ["To Do", ["b"]],
    ["Doing", ["a", "c"]],
    ["Done", []],
  ]);
});

test("boardOfList: the board has the list's id, name, time of change, columns and limits", () => {
  // The id places the tasks waiting to be added; the time of change
  // goes with a change to the columns.
  const board = rules.boardOfList(listOf({ Doing: 2 }, []));
  assert.deepEqual(board, {
    id: BOARD_LIST,
    name: "Home",
    board_columns: BOARD_COLUMNS,
    wip_limits: { Doing: 2 },
    updated_at: 77,
    columns: { "To Do": [], Doing: [], Done: [] },
  });
});

test("boardOfList: a task whose column is not one of the list's is in the first", () => {
  const board = rules.boardOfList(
    listOf({}, [
      boardCard("a", "Backlog"),
      boardCard("b", ""),
      boardCard("c", undefined),
      // The name of something every object has is no column.
      boardCard("d", "toString"),
    ]),
  );
  assert.deepEqual(idsIn(board), [
    ["To Do", ["a", "b", "c", "d"]],
    ["Doing", []],
    ["Done", []],
  ]);
});

test("boardOfList: a subtask is no card, and stands under its parent whatever its column", () => {
  const board = rules.boardOfList(
    listOf({}, [
      boardCard("p", "Doing"),
      boardCard("s1", "Done", "p"),
      boardCard("q", "To Do"),
      boardCard("s2", "To Do", "p"),
    ]),
  );
  assert.deepEqual(idsIn(board), [
    ["To Do", ["q"]],
    ["Doing", ["p"]],
    ["Done", []],
  ]);
  assert.deepEqual(
    board.columns.Doing[0].subtasks.map((one) => one.id),
    ["s1", "s2"],
  );
  assert.deepEqual(board.columns["To Do"][0].subtasks, []);
});

test("boardOfList: the tasks given are not altered", () => {
  const items = [boardCard("p", "Doing"), boardCard("s", "Doing", "p")];
  const before = JSON.stringify(items);
  rules.boardOfList(listOf({}, items));
  assert.equal(JSON.stringify(items), before);
});

test("boardOfList: a list without columns has no cards", () => {
  const board = rules.boardOfList(listOf({}, [boardCard("a", "Doing")], []));
  assert.deepEqual(board.columns, {});
  assert.deepEqual(board.board_columns, []);
});

test("boardOfList: an answer without columns, limits or tasks is a board without them", () => {
  assert.deepEqual(rules.boardOfList({ id: BOARD_LIST }), {
    id: BOARD_LIST,
    name: undefined,
    board_columns: [],
    wip_limits: {},
    updated_at: undefined,
    columns: {},
  });
});

test("boardOfList: the queued changes are applied to it as to the server's board", () => {
  const board = rules.boardOfList(
    listOf({}, [
      Object.assign(boardCard(ITEM_A, "To Do"), { complete: false }),
    ]),
  );
  const shown = rules.boardWithQueuedChanges(board, [tick(1, ITEM_A, 100)]);
  assert.deepEqual(
    shown.columns.Done.map((one) => one.id),
    [ITEM_A],
  );
});

test("boardOfList: a task waiting to be added is a card of it, a waiting subtask stands in its task's card", () => {
  const board = rules.boardOfList(listOf({}, [boardCard(ITEM_A, "Doing")]));
  const queue = [
    {
      path: "/lists/" + BOARD_LIST + "/items",
      opts: {
        method: "POST",
        body: JSON.stringify({ id: "new-1", reminder: "Buy milk" }),
      },
      timestamp: 1,
      waiting: true,
    },
    {
      path: "/lists/" + BOARD_LIST + "/items",
      opts: {
        method: "POST",
        body: JSON.stringify({
          id: "new-2",
          reminder: "Find the form",
          parent_id: ITEM_A,
        }),
      },
      timestamp: 2,
      waiting: true,
    },
  ];
  const shown = rules.boardWithQueuedChanges(board, queue);
  assert.deepEqual(
    shown.columns["To Do"].map((one) => one.reminder),
    ["Buy milk"],
  );
  assert.deepEqual(
    shown.columns.Doing[0].subtasks.map((one) => one.reminder),
    ["Find the form"],
  );
});

// --- The copy of a list kept for use without the server (#121) ---

const ONE_DAY = 86400000;

test("listCopyIsCurrent: a copy with the server's stamp, stored within the day", () => {
  const kept = { stamp: "abc", savedAt: 1000 };
  assert.equal(rules.listCopyIsCurrent(kept, "abc", 1000, ONE_DAY), true);
  assert.equal(
    rules.listCopyIsCurrent(kept, "abc", 1000 + ONE_DAY - 1, ONE_DAY),
    true,
  );
});

test("listCopyIsCurrent: no copy, another stamp, or none at all", () => {
  assert.equal(rules.listCopyIsCurrent(undefined, "abc", 1000, ONE_DAY), false);
  assert.equal(
    rules.listCopyIsCurrent(
      { stamp: "abd", savedAt: 1000 },
      "abc",
      1000,
      ONE_DAY,
    ),
    false,
  );
  // A copy stored before stamps were kept, and a server that gives
  // none: neither says that the copy is the list.
  assert.equal(
    rules.listCopyIsCurrent({ savedAt: 1000 }, undefined, 1000, ONE_DAY),
    false,
  );
});

test("listCopyIsCurrent: a copy a day old is read again, so that none is swept", () => {
  const kept = { stamp: "abc", savedAt: 1000 };
  assert.equal(
    rules.listCopyIsCurrent(kept, "abc", 1000 + ONE_DAY, ONE_DAY),
    false,
  );
});

test("listCopyIsCurrent: a time of storing that is yet to come is none", () => {
  const kept = { stamp: "abc", savedAt: 5000 };
  assert.equal(rules.listCopyIsCurrent(kept, "abc", 1000, ONE_DAY), false);
});
