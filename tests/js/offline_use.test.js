// Offline use (#75): what became of the page's service worker, what
// the page's Settings say of it, and the notice given once per device
// where the browser refused the worker (offlineUseText, refusalWords,
// showOfflineUse, workerIs and tellOfflineUseOnce in
// src/pytodo_qt/web/static/app.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins for the page's elements and storage.
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
  const start = source.indexOf("  function " + name + "(");
  assert.notEqual(start, -1, name + " is in app.js");
  const end = source.indexOf("\n  }\n", start);
  assert.notEqual(end, -1, "the end of " + name + " is found");
  return source.slice(start, end + 5);
}

function constantText(name) {
  const match = new RegExp("  var " + name + ' = "[^"]*";').exec(source);
  assert.ok(match, name + " is in app.js");
  return match[0];
}

// A line of the page's Settings.
function line() {
  const made = { textContent: "", hidden: true };
  made.classList = {
    toggle(name, on) {
      assert.equal(name, "hidden");
      made.hidden = on;
    },
  };
  return made;
}

// The page as far as offline use goes. options:
//   ready      whether the page has started
//   pin        whether the PIN screen is up
//   told       what the device has stored of an earlier notice
function page(options) {
  const env = Object.assign({ ready: true, pin: false, toasts: [] }, options);
  env.kept = {};
  if (env.told) env.kept.pytodo_offline_use_told = env.told;
  env.lines = {
    "settings-offline-use": line(),
    "settings-offline-why": line(),
    "settings-offline-how": line(),
  };
  return new Function(
    "env",
    [
      "var appReady = env.ready, pinScreenUp = env.pin;",
      "var document = { getElementById: function (id) { return env.lines[id] || null; } };",
      "var localStorage = {",
      "  getItem: function (key) { return key in env.kept ? env.kept[key] : null; },",
      "  setItem: function (key, value) { env.kept[key] = value; },",
      "  removeItem: function (key) { delete env.kept[key]; },",
      "};",
      "function showToast(text) { env.toasts.push(text); }",
      constantText("OFFLINE_TOLD_KEY"),
      "var workerFound = null;",
      functionText("offlineUseText"),
      functionText("refusalWords"),
      functionText("showOfflineUse"),
      functionText("workerIs"),
      functionText("tellOfflineUseOnce"),
      "return {",
      "  env: env,",
      "  text: offlineUseText,",
      "  words: refusalWords,",
      "  show: showOfflineUse,",
      "  workerIs: workerIs,",
      "  tell: tellOfflineUseOnce,",
      "  started: function () { appReady = true; pinScreenUp = false; },",
      "};",
    ].join("\n"),
  )(env);
}

const MEANING =
  " This page can't be opened without the server on this device." +
  " Tasks on screen and changes you make while it is open are kept.";
const NOTICE = "Offline use isn't available on this device. See More for why.";
// As Chrome words it on a device that does not trust the certificate.
const CHROME =
  "Failed to register a ServiceWorker for scope ('https://192.168.1.20:8443/')" +
  " with script ('https://192.168.1.20:8443/sw.js'): An SSL certificate error" +
  " occurred when fetching the script.";
const refused = (made, message) => ({
  state: "refused",
  words: made.words(new Error(message)),
});

// --- What the Settings say ---

test("until the worker's fate is known the row says so, and gives no reason", () => {
  assert.deepEqual(page({}).text(null), {
    value: "Checking…",
    why: "",
    how: "",
  });
});

test("a worker that is installed: available, and nothing more", () => {
  assert.deepEqual(page({}).text({ state: "on", words: "" }), {
    value: "Available",
    why: "",
    how: "",
  });
});

test("a refusal over the certificate says so, what it means, and what makes it available", () => {
  const made = page({});
  assert.deepEqual(made.text(refused(made, CHROME)), {
    value: "Not available",
    why: "This device does not trust the server's certificate." + MEANING,
    how:
      "To make it available, install the app's certificate: on the" +
      " computer, in PyTodo-Qt choose Tools → Mobile Setup and" +
      " follow Trusted Connect.",
  });
});

test("any other refusal is given in the browser's words, with no step that may not help", () => {
  const made = page({});
  assert.deepEqual(made.text(refused(made, "The operation is insecure.")), {
    value: "Not available",
    why: "The browser refused it: The operation is insecure." + MEANING,
    how: "",
  });
});

test("a page not opened over HTTPS, and a browser without service workers, each say which", () => {
  const made = page({});
  assert.deepEqual(made.text({ state: "plain", words: "" }), {
    value: "Not available",
    why: "This page is not opened over HTTPS." + MEANING,
    how: "",
  });
  assert.deepEqual(made.text({ state: "none", words: "" }), {
    value: "Not available",
    why:
      "This browser does not offer it here (in a private window, for one)." +
      MEANING,
    how: "",
  });
});

test("the browser's reason is one line, without the addresses it repeats", () => {
  const made = page({});
  assert.equal(
    made.words(new Error(CHROME)),
    "Failed to register a ServiceWorker for scope with script: An SSL certificate error occurred when fetching the script",
  );
  assert.equal(made.words(new Error("  Two\n lines. ")), "Two lines");
  // What is no error, and nothing at all.
  assert.equal(made.words("refused"), "refused");
  assert.equal(made.words(undefined), "no reason given");
  assert.equal(made.words(new Error("")), "Error");
});

test("the row and its lines show what is found, and the lines are hidden where they say nothing", () => {
  const made = page({});
  const { env } = made;
  made.show();
  assert.equal(env.lines["settings-offline-use"].textContent, "Checking…");
  assert.equal(env.lines["settings-offline-why"].hidden, true);
  assert.equal(env.lines["settings-offline-how"].hidden, true);
  made.workerIs(refused(made, CHROME));
  assert.equal(env.lines["settings-offline-use"].textContent, "Not available");
  assert.equal(env.lines["settings-offline-why"].hidden, false);
  assert.ok(
    env.lines["settings-offline-why"].textContent.startsWith(
      "This device does not trust",
    ),
  );
  assert.equal(env.lines["settings-offline-how"].hidden, false);
  assert.ok(
    env.lines["settings-offline-how"].textContent.startsWith(
      "To make it available, install the app's certificate",
    ),
  );
  made.workerIs(refused(made, "The operation is insecure."));
  assert.equal(env.lines["settings-offline-why"].hidden, false);
  assert.equal(env.lines["settings-offline-how"].hidden, true);
  assert.equal(env.lines["settings-offline-how"].textContent, "");
  made.workerIs({ state: "on", words: "" });
  assert.equal(env.lines["settings-offline-use"].textContent, "Available");
  assert.equal(env.lines["settings-offline-why"].hidden, true);
});

test("a page whose Settings are not there is told all the same", () => {
  const made = page({});
  made.env.lines = {};
  made.workerIs(refused(made, CHROME));
  assert.deepEqual(made.env.toasts, [NOTICE]);
});

// --- The notice ---

test("a refusal is said once per device", () => {
  const made = page({});
  made.workerIs(refused(made, CHROME));
  assert.deepEqual(made.env.toasts, [NOTICE]);
  assert.equal(made.env.kept.pytodo_offline_use_told, "1");
  // The page is loaded again: the device has been told.
  const again = page({ told: "1" });
  again.workerIs(refused(again, CHROME));
  assert.deepEqual(again.env.toasts, []);
});

test("it is not said before the page has started, or behind the PIN screen, and is said when it has", () => {
  for (const options of [{ ready: false }, { pin: true }]) {
    const made = page(options);
    made.workerIs(refused(made, CHROME));
    assert.deepEqual(made.env.toasts, []);
    // Not marked as told: it has not been.
    assert.equal(made.env.kept.pytodo_offline_use_told, undefined);
    made.started();
    made.tell();
    assert.deepEqual(made.env.toasts, [NOTICE]);
    made.tell();
    assert.deepEqual(made.env.toasts, [NOTICE]);
  }
});

test("nothing is said where no worker was to be had, or one is installed", () => {
  for (const state of ["on", "plain", "none"]) {
    const made = page({});
    made.workerIs({ state: state, words: "" });
    assert.deepEqual(made.env.toasts, [], state);
  }
  // Nor before anything is known.
  const made = page({});
  made.tell();
  assert.deepEqual(made.env.toasts, []);
});

test("after offline use has been available, a later refusal is said again", () => {
  // The certificate was installed, and later replaced.
  const made = page({ told: "1" });
  made.workerIs({ state: "on", words: "" });
  assert.equal(made.env.kept.pytodo_offline_use_told, undefined);
  made.workerIs(refused(made, CHROME));
  assert.deepEqual(made.env.toasts, [NOTICE]);
});

test("a state other than a refusal leaves what the device was told as it is", () => {
  const made = page({ told: "1" });
  made.workerIs({ state: "none", words: "" });
  assert.equal(made.env.kept.pytodo_offline_use_told, "1");
});
