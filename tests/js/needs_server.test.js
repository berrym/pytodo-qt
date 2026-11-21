// The controls that need the server: creating, renaming and deleting a
// list, a column's name, limit and deletion, a board layout, the sort
// order, a restore from the trash, and the server's Undo and Redo.
// While the server cannot be reached they look disabled, say why, and
// do nothing (needsServer, showWhetherAvailable, showServerOnlyControls,
// refuseWithoutServer, updateUndoButtons and renderContextActions in
// src/pytodo_qt/web/static/app.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins for the page's elements.
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

// An element of the page, as far as these functions use one.
function element(tag) {
  const made = {
    tagName: (tag || "button").toUpperCase(),
    classes: new Set(),
    attributes: {},
    children: [],
    listeners: {},
    textContent: "",
    title: "",
    disabled: false,
    className: "",
  };
  made.classList = {
    add: (name) => made.classes.add(name),
    toggle(name, on) {
      if (on) made.classes.add(name);
      else made.classes.delete(name);
    },
    contains: (name) => made.classes.has(name),
  };
  made.setAttribute = (name, value) => {
    made.attributes[name] = value;
  };
  made.removeAttribute = (name) => {
    delete made.attributes[name];
  };
  made.appendChild = (child) => {
    made.children.push(child);
    child.parent = made;
    return child;
  };
  made.addEventListener = (name, listener) => {
    made.listeners[name] = listener;
  };
  // Every element under this one, itself not counted.
  made.all = () =>
    made.children.flatMap((child) => [child].concat(child.all()));
  const named = (child, selector) =>
    selector === "[data-needs-server]"
      ? "data-needs-server" in child.attributes
      : child.className.split(" ").includes(selector.slice(1)) ||
        child.classes.has(selector.slice(1));
  made.querySelector = (selector) =>
    made.all().filter((child) => named(child, selector))[0] || null;
  made.querySelectorAll = (selector) =>
    made.all().filter((child) => named(child, selector));
  // The nearest element, this one included, that is not available.
  made.closest = () => {
    for (let at = made; at; at = at.parent) {
      if (at.classes.has("needs-server-off")) return at;
    }
    return null;
  };
  return made;
}

// The page as far as these functions go. options:
//   connected  whether the server is taken for present
//   undo, redo the steps of changes still waiting in the page
//   server     what the server says of its own undo and redo
function page(options) {
  const env = Object.assign(
    { connected: true, undo: [], redo: [], server: {}, toasts: [], did: [] },
    options,
  );
  env.body = element("body");
  env.undoBtn = env.body.appendChild(element());
  env.redoBtn = env.body.appendChild(element());
  env.document = {
    createElement: (tag) => element(tag),
    querySelectorAll: (selector) => env.body.querySelectorAll(selector),
  };
  return new Function(
    "env",
    [
      "var serverConnected = env.connected;",
      "var document = env.document;",
      "var undoBtn = env.undoBtn, redoBtn = env.redoBtn;",
      "var offlineUndoStack = env.undo, offlineRedoStack = env.redo;",
      "var serverUndoState = env.server;",
      "function showToast(text) { env.toasts.push(text); }",
      "function offlineUndoAction() { env.did.push('undo in the page'); }",
      "function offlineRedoAction() { env.did.push('redo in the page'); }",
      "async function serverOnly(path) { env.did.push(path); return { ok: false }; }",
      "function haptic() {}",
      "function closeContextMenu() { env.menuClosed = true; }",
      "function showContextMenu() {}",
      constantText("NEEDS_SERVER"),
      functionText("needsServer"),
      functionText("showWhetherAvailable"),
      functionText("showServerOnlyControls"),
      functionText("createNeedsServerNote"),
      functionText("withoutServer"),
      functionText("refuseWithoutServer"),
      functionText("undoIsOffline"),
      functionText("updateUndoButtons"),
      functionText("onUndo"),
      functionText("onRedo"),
      functionText("renderContextActions"),
      "return {",
      "  env: env,",
      "  needsServer: needsServer,",
      "  show: showServerOnlyControls,",
      "  note: createNeedsServerNote,",
      "  refuse: refuseWithoutServer,",
      "  undoButtons: updateUndoButtons,",
      "  undo: onUndo,",
      "  redo: onRedo,",
      "  withoutServer: withoutServer,",
      "  menu: renderContextActions,",
      "  reason: NEEDS_SERVER,",
      "  connection: function (there) { serverConnected = there; },",
      "};",
    ].join("\n"),
  )(env);
}

// A press on an element, as the document hears it first.
function press(made, target) {
  const event = {
    target: target,
    prevented: false,
    stopped: false,
    preventDefault() {
      event.prevented = true;
    },
    stopPropagation() {
      event.stopped = true;
    },
  };
  made.refuse(event);
  return event;
}

const off = (control) => ({
  looks: control.classes.has("needs-server-off"),
  says: control.attributes["aria-disabled"] || null,
});

test("with the server a control that needs it is as any other", () => {
  const made = page({ connected: true });
  const control = made.needsServer(made.env.body.appendChild(element()));
  assert.deepEqual(off(control), { looks: false, says: null });
  const pressed = press(made, control);
  assert.equal(pressed.stopped, false);
  assert.equal(pressed.prevented, false);
  assert.deepEqual(made.env.toasts, []);
});

test("without the server it looks disabled, says so to assistive technology, and is no disabled button", () => {
  const made = page({ connected: false });
  const control = made.needsServer(made.env.body.appendChild(element()));
  assert.deepEqual(off(control), { looks: true, says: "true" });
  // A disabled button would say nothing when it is pressed.
  assert.equal(control.disabled, false);
});

test("pressed without the server it does nothing, and says why", () => {
  const made = page({ connected: false });
  const control = made.needsServer(made.env.body.appendChild(element()));
  const pressed = press(made, control);
  assert.equal(pressed.stopped, true);
  assert.equal(pressed.prevented, true);
  assert.deepEqual(made.env.toasts, [
    "Not available while the server can't be reached",
  ]);
});

test("a press on something inside the control is the control's", () => {
  // The icon of a menu action, for one.
  const made = page({ connected: false });
  const control = made.needsServer(made.env.body.appendChild(element()));
  const icon = control.appendChild(element("span"));
  assert.equal(press(made, icon).stopped, true);
  assert.equal(made.env.toasts.length, 1);
});

test("a press on anything else is left alone", () => {
  const made = page({ connected: false });
  made.needsServer(made.env.body.appendChild(element()));
  const other = made.env.body.appendChild(element());
  assert.equal(press(made, other).stopped, false);
  // What is no element has nothing to ask.
  assert.equal(press(made, {}).stopped, false);
  assert.equal(press(made, null).stopped, false);
  assert.deepEqual(made.env.toasts, []);
});

test("the controls follow the connection: lost, and found again", () => {
  const made = page({ connected: true });
  const first = made.needsServer(made.env.body.appendChild(element()));
  const second = made.needsServer(made.env.body.appendChild(element()));
  const other = made.env.body.appendChild(element());
  made.connection(false);
  made.show();
  assert.deepEqual(off(first), { looks: true, says: "true" });
  assert.deepEqual(off(second), { looks: true, says: "true" });
  assert.deepEqual(off(other), { looks: false, says: null });
  made.connection(true);
  made.show();
  assert.deepEqual(off(first), { looks: false, says: null });
  assert.deepEqual(off(second), { looks: false, says: null });
  assert.equal(press(made, first).stopped, false);
});

test("the line at the top of a sheet is shown while the server cannot be reached", () => {
  const made = page({ connected: false });
  const note = made.env.body.appendChild(made.note("Lists can't be changed."));
  assert.equal(note.textContent, "Lists can't be changed.");
  assert.equal(note.className, "needs-server-note");
  assert.equal(note.classes.has("hidden"), false);
  made.connection(true);
  made.show();
  assert.equal(note.classes.has("hidden"), true);
  made.connection(false);
  made.show();
  assert.equal(note.classes.has("hidden"), false);
  // Made with the server there, it is hidden from the start.
  made.connection(true);
  assert.equal(made.note("x").classes.has("hidden"), true);
});

test("a select is disabled as the browser does it: its list opens before a click is heard", () => {
  const made = page({ connected: false });
  const select = made.needsServer(made.env.body.appendChild(element("select")));
  assert.equal(select.disabled, true);
  assert.deepEqual(off(select), { looks: true, says: "true" });
  made.connection(true);
  made.show();
  assert.equal(select.disabled, false);
  assert.deepEqual(off(select), { looks: false, says: null });
});

test("a change begun with the server and finished without it is refused with the reason", () => {
  // A name being typed, a question being answered.
  const made = page({ connected: true });
  assert.equal(made.withoutServer(), false);
  assert.deepEqual(made.env.toasts, []);
  made.connection(false);
  assert.equal(made.withoutServer(), true);
  assert.deepEqual(made.env.toasts, [made.reason]);
});

// --- Menu actions ---

test("a menu action that needs the server says why under its label", () => {
  const made = page({ connected: false });
  const menu = made.env.body.appendChild(element("div"));
  let tapped = 0;
  made.menu(menu, [
    { label: "Rename", needsServer: true, onTap: () => tapped++ },
    { label: "Open", onTap: () => tapped++ },
  ]);
  const [rename, open] = menu.children;
  assert.deepEqual(off(rename), { looks: true, says: "true" });
  const reason = rename.querySelector(".needs-server-reason");
  assert.equal(reason.textContent, made.reason);
  assert.equal(reason.classes.has("hidden"), false);
  // The other action is as it was, and has no such line.
  assert.deepEqual(off(open), { looks: false, says: null });
  assert.equal(open.querySelector(".needs-server-reason"), null);
  // Pressed, the first is refused before its own listener is reached.
  assert.equal(press(made, rename).stopped, true);
  assert.equal(press(made, open).stopped, false);
});

test("with the server the reason is not shown, and comes when the server is lost", () => {
  const made = page({ connected: true });
  const menu = made.env.body.appendChild(element("div"));
  made.menu(menu, [{ label: "Rename", needsServer: true, onTap() {} }]);
  const rename = menu.children[0];
  const reason = rename.querySelector(".needs-server-reason");
  assert.deepEqual(off(rename), { looks: false, says: null });
  assert.equal(reason.classes.has("hidden"), true);
  made.connection(false);
  made.show();
  assert.deepEqual(off(rename), { looks: true, says: "true" });
  assert.equal(reason.classes.has("hidden"), false);
});

// --- Undo and Redo ---

const button = (btn) => ({
  off: btn.classes.has("needs-server-off"),
  disabled: btn.disabled,
  title: btn.title,
});

test("with the server, Undo and Redo are the server's", () => {
  const made = page({
    connected: true,
    server: { can_undo: true, undo_text: "Add item", can_redo: false },
  });
  made.undoButtons();
  assert.deepEqual(button(made.env.undoBtn), {
    off: false,
    disabled: false,
    title: "Undo: Add item",
  });
  assert.deepEqual(button(made.env.redoBtn), {
    off: false,
    disabled: true,
    title: "Redo",
  });
});

test("without the server and with no step in the page, Undo and Redo need the server and say so", () => {
  const made = page({
    connected: false,
    server: { can_undo: true, can_redo: true },
  });
  made.undoButtons();
  for (const btn of [made.env.undoBtn, made.env.redoBtn]) {
    assert.deepEqual(button(btn), {
      off: true,
      disabled: false,
      title: made.reason,
    });
    assert.equal(btn.attributes["aria-disabled"], "true");
    assert.equal(press(made, btn).stopped, true);
  }
});

test("a step of a change still waiting in the page can be taken back without the server", () => {
  const made = page({ connected: false, undo: [{}], redo: [] });
  made.undoButtons();
  assert.deepEqual(button(made.env.undoBtn), {
    off: false,
    disabled: false,
    title: "Undo (offline)",
  });
  // Nothing to put back: disabled as a button with nothing to do is.
  assert.deepEqual(button(made.env.redoBtn), {
    off: false,
    disabled: true,
    title: "Redo",
  });
  assert.equal(press(made, made.env.undoBtn).stopped, false);
});

test("Undo and Redo follow the connection with the other controls", () => {
  const made = page({ connected: true, server: { can_undo: true } });
  made.undoButtons();
  // Nothing to put back at the server: a disabled button.
  assert.equal(made.env.redoBtn.disabled, true);
  made.connection(false);
  made.show();
  assert.equal(made.env.undoBtn.classes.has("needs-server-off"), true);
  // No longer a disabled button, which would say nothing when pressed.
  assert.equal(made.env.redoBtn.disabled, false);
  assert.equal(press(made, made.env.redoBtn).stopped, true);
  made.connection(true);
  made.show();
  assert.deepEqual(button(made.env.undoBtn), {
    off: false,
    disabled: false,
    title: "Undo",
  });
  assert.equal(made.env.undoBtn.attributes["aria-disabled"], undefined);
});

test("Undo and Redo by key ask the server only while it is there", async () => {
  // The keys do not pass the buttons.
  const made = page({ connected: false });
  await made.undo();
  await made.redo();
  assert.deepEqual(made.env.did, []);
  assert.deepEqual(made.env.toasts, [made.reason, made.reason]);
  made.connection(true);
  await made.undo();
  await made.redo();
  assert.deepEqual(made.env.did, ["/undo", "/redo"]);
});

test("Undo and Redo by key take a waiting change back without the server", async () => {
  const made = page({ connected: false, undo: [{}] });
  await made.undo();
  await made.redo();
  assert.deepEqual(made.env.did, ["undo in the page", "redo in the page"]);
  assert.deepEqual(made.env.toasts, []);
});

// --- The sort order ---

// The page as far as saving and reading the sort order goes. `answers`
// are what becomes of each save, in order: "no answer" (the request
// failed or was given up; serverOnly has told the person), or what the
// server answered: {status, body}. `read` is what a read of the order
// gives.
function sorting(answers, read) {
  const env = {
    toasts: [],
    shown: [],
    sent: [],
    synced: 0,
    labels: 0,
    answers: answers,
    read: read,
  };
  return new Function(
    "env",
    [
      'var API = "/api";',
      "var currentSortTiers = [{ dimension: 'completion', reverse: false }, { dimension: 'due_date', reverse: false }, { dimension: 'priority', reverse: false }];",
      "var sortUpdatedAt = 1;",
      "var confirmedSortTiers = JSON.stringify(currentSortTiers);",
      // A change sent straight to the server (connection.test.js).
      "async function serverOnly(path, opts) {",
      "  env.sent.push(JSON.parse(opts.body).tiers.map(function (tier) { return tier.dimension; }));",
      "  var answer = env.answers.shift();",
      "  if (answer === 'no answer') { var none = new Error('no answer'); none.noAnswer = true; throw none; }",
      "  if (answer.status !== 200) { var refused = new Error('refused'); refused.status = answer.status; refused.body = answer.body || {}; throw refused; }",
      "  return answer.body || {};",
      "}",
      "function authHeaders(headers) { return headers; }",
      "async function serverFetch() { if (!env.read) throw new TypeError('Failed to fetch'); return { ok: true, json: async function () { return env.read; } }; }",
      "function syncSortSheetUI() { env.synced += 1; }",
      "function updateSortButtonLabel() { env.labels += 1; }",
      "function showToast(text) { env.toasts.push(text); }",
      "function showSortOrder() { env.shown.push(currentSortTiers[0].dimension); }",
      functionText("saveSortTiers"),
      functionText("fetchSortTiers"),
      "return {",
      "  env: env,",
      "  choose: function (dimension) { currentSortTiers[0].dimension = dimension; saveSortTiers(); },",
      "  read: fetchSortTiers,",
      "  first: function () { return currentSortTiers[0].dimension; },",
      "  stamp: function () { return sortUpdatedAt; },",
      "};",
    ].join("\n"),
  )(env);
}

const settled = () => new Promise((resolve) => setTimeout(resolve, 0));
const tiers = (first) => [
  { dimension: first, reverse: false },
  { dimension: "due_date", reverse: false },
  { dimension: "priority", reverse: false },
];

test("an order the server takes is kept", async () => {
  const made = sorting([{ status: 200, body: { updated_at: 2 } }]);
  made.choose("priority");
  await settled();
  assert.equal(made.first(), "priority");
  assert.equal(made.stamp(), 2);
  assert.deepEqual(made.env.toasts, []);
  assert.deepEqual(made.env.shown, ["priority"]);
});

test("an order whose save gets no answer stays as chosen, and is not called a failure", async () => {
  // The server may have taken it (#122). The person was told that no
  // answer came by the sending itself.
  const made = sorting(["no answer"]);
  made.choose("priority");
  await settled();
  assert.equal(made.first(), "priority");
  assert.deepEqual(made.env.shown, ["priority"]);
  assert.deepEqual(made.env.toasts, []);
});

test("it is not the order the server has confirmed: a refusal after it goes back further", async () => {
  const made = sorting(["no answer", { status: 400 }]);
  made.choose("priority");
  await settled();
  made.choose("name");
  await settled();
  assert.equal(made.first(), "completion");
});

test("a refusal of the server puts the last confirmed order back, with a notice", async () => {
  const made = sorting([{ status: 400 }]);
  made.choose("priority");
  // Shown at once, as before.
  assert.deepEqual(made.env.shown, ["priority"]);
  await settled();
  assert.equal(made.first(), "completion");
  assert.deepEqual(made.env.shown, ["priority", "completion"]);
  assert.deepEqual(made.env.toasts, ["The sort order was not saved"]);
});

test("after an order was taken, a refused save goes back to that one", async () => {
  const made = sorting([
    { status: 200, body: { updated_at: 2 } },
    { status: 500 },
    { status: 500 },
  ]);
  made.choose("priority");
  await settled();
  // Two changes at once, both refused: neither is what is gone back to.
  made.choose("due_date");
  made.choose("name");
  await settled();
  assert.equal(made.first(), "priority");
  assert.deepEqual(
    made.env.sent.map((sent) => sent[0]),
    ["priority", "due_date", "name"],
  );
});

test("an order changed elsewhere is taken from the server, and is the confirmed one from then on", async () => {
  const theirs = [
    { dimension: "name", reverse: true },
    { dimension: "due_date", reverse: false },
    { dimension: "priority", reverse: false },
  ];
  const made = sorting([
    { status: 409, body: { current: { sort_tiers: theirs, updated_at: 7 } } },
    { status: 400 },
  ]);
  made.choose("priority");
  await settled();
  assert.equal(made.first(), "name");
  assert.equal(made.stamp(), 7);
  assert.deepEqual(made.env.toasts, [
    "Sort was changed elsewhere \u2014 refreshed",
  ]);
  made.choose("priority");
  await settled();
  assert.equal(made.first(), "name");
});

test("the order read from the server, where it is another than the one on screen, is drawn", async () => {
  // When the server is reached again after a save without an answer,
  // and at a start where the list was drawn first.
  const made = sorting(["no answer"], {
    sort_tiers: tiers("name"),
    updated_at: 9,
  });
  made.choose("priority");
  await settled();
  made.read();
  await settled();
  assert.equal(made.first(), "name");
  assert.equal(made.stamp(), 9);
  assert.deepEqual(made.env.shown, ["priority", "name"]);
  assert.equal(made.env.synced, 1);
  // It is the confirmed one: a refusal goes back to it.
  made.env.answers.push({ status: 400 });
  made.choose("priority");
  await settled();
  assert.equal(made.first(), "name");
});

test("the order read, where it is the one on screen, is not drawn again", async () => {
  const made = sorting([], { sort_tiers: tiers("completion"), updated_at: 3 });
  made.read();
  await settled();
  assert.deepEqual(made.env.shown, []);
  assert.equal(made.env.labels, 1);
  assert.equal(made.stamp(), 3);
});

test("a read of the order that gets no answer leaves the order alone", async () => {
  const made = sorting([], null);
  made.read();
  await settled();
  assert.equal(made.first(), "completion");
  assert.deepEqual(made.env.shown, []);
});
