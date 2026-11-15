// Rules of the web page's offline queue (src/pytodo_qt/web/static/offline-queue.js).
// Run by tests/test_web_pwa.py with `node --test`.
"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");

const rules = require(
  path.join(__dirname, "..", "..", "src", "pytodo_qt", "web", "static", "offline-queue.js"),
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
  assert.equal(rules.newTimestamp([change(900, "/items/" + ITEM_A, "DELETE")], 1000), 1000);
});

test("newTimestamp never repeats a queued change's time", () => {
  const queue = [change(1000, "/items/" + ITEM_A, "DELETE")];
  assert.equal(rules.newTimestamp(queue, 1000), 1001);
  // A clock set back, or a change put back out of order by redo.
  const unordered = [change(1005, "/items/" + ITEM_A, "DELETE"), change(1002, "/items/" + ITEM_B, "DELETE")];
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
  assert.equal(rules.nextToSend(queue, { 1: true, 3: true }, held).timestamp, 4);
  assert.equal(rules.nextToSend(queue, { 1: true, 3: true, 4: true }, held), null);
});

test("withUpdatedAt replaces the time a change was based on", () => {
  const opts = change(1, "/items/" + ITEM_A, "PUT", { priority: 1, updated_at: 100 }).opts;
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
  const noTime = change(1, "/lists/" + LIST + "/items", "POST", { reminder: "New" }).opts;
  assert.equal(rules.withUpdatedAt(noTime, 250), noTime);
  const notJson = { method: "PUT", body: "not json" };
  assert.equal(rules.withUpdatedAt(notJson, 250), notJson);
  assert.equal(rules.withUpdatedAt(undefined, 250), undefined);
});
