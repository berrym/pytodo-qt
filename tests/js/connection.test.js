// How the web page tells whether the server answers, and what it says
// while it does not (serverFetch and its deadline, serverAnswered,
// serverSilent, the question put over the WebSocket and the notice, in
// src/pytodo_qt/web/static/app.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text and run
// against stand-ins for the rest of the page.
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

// A WebSocket as far as the page asks one whether the server is there.
function socket() {
  const made = {
    readyState: 1,
    sent: [],
    closed: false,
    onopen() {},
    onmessage() {},
    onclose() {},
    onerror() {},
    send(text) {
      if (made.sendFails) throw new Error("the socket is not open");
      made.sent.push(text);
    },
    close() {
      made.closed = true;
      made.readyState = 3;
    },
  };
  return made;
}

function numberOf(name) {
  return Number(/\d+/.exec(constantText(name).split("=")[1])[0]);
}

// How often an open WebSocket is asked whether the server is there, and
// how long the server has to say anything.
const PING = numberOf("WS_PING_INTERVAL");
const PONG = numberOf("WS_PONG_DEADLINE");

// An element of the page, as far as the notice uses one.
function element() {
  const made = {
    hidden: false,
    textContent: "",
    classList: {
      toggle(name, on) {
        assert.equal(name, "hidden");
        made.hidden = on;
      },
    },
  };
  return made;
}

// The page's connection state with stand-ins around it. options:
//   connected    the state the page starts in
//   ready        whether the page has finished starting
//   deviceOnline what the browser says of the device's network
//   lastSync     the time of the server's last answer for the list
//   fetch        the network
//   socket       the page's WebSocket
//   hidden       whether the page is out of view
//   token        the token the device holds ("" for none)
//   pin          what is typed into the PIN screen
//   ownRefresh   true to run the page's own refreshCurrentList and
//                showLoginScreen; what is drawn is listed in env.drawn
//   ownSockets   true to run the page's own connectWebSocket,
//                scheduleReconnect and probeServer against WebSockets
//                of the test's making, listed in env.sockets
// Time stands still until env.advance(milliseconds) moves it.
function page(options) {
  const env = Object.assign(
    {
      connected: true,
      ready: true,
      deviceOnline: true,
      lastSync: 0,
      socket: null,
      hidden: false,
      ownSockets: false,
      ownRefresh: false,
    },
    options,
  );
  env.calls = [];
  env.drawn = [];
  env.stored = { items: [{ id: "kept" }], savedAt: 1795124040000 };
  env.sockets = [];
  env.WebSocket = function (url) {
    const made = socket();
    made.readyState = 0;
    made.url = url;
    // As the browser does it: open, a message, or closed.
    made.opens = () => {
      made.readyState = 1;
      made.onopen();
    };
    made.says = (message) => made.onmessage({ data: JSON.stringify(message) });
    made.closes = () => {
      made.readyState = 3;
      if (made.onclose) made.onclose();
    };
    made.close = () => {
      made.closed = true;
      made.closes();
    };
    env.sockets.push(made);
    return made;
  };
  env.WebSocket.CONNECTING = 0;
  env.WebSocket.OPEN = 1;
  env.banner = element();
  env.text = element();
  // What the page keeps on the device: its token, the service worker
  // and the worker's stores.
  const kept = {
    pytodo_auth_token: env.token === undefined ? "token" : env.token,
  };
  env.pinInput = { value: env.pin || "", focus() {} };
  env.pinError = { textContent: "" };
  env.pinButton = { disabled: false, textContent: "Connect" };
  env.localStorage = {
    getItem: (key) => (key in kept ? kept[key] : null),
    setItem: (key, value) => {
      kept[key] = value;
    },
    removeItem: (key) => {
      delete kept[key];
    },
  };
  env.workers = ["worker"];
  env.stores = ["pytodo-static-1", "pytodo-data"];
  env.caches = {
    keys: async () => env.stores.slice(),
    delete: async (name) => {
      env.stores = env.stores.filter((store) => store !== name);
    },
  };
  env.navigator = {
    onLine: env.deviceOnline,
    serviceWorker: {
      controller: {},
      getRegistrations: async () =>
        env.workers.map(() => ({
          unregister: async () => {
            env.workers = [];
          },
        })),
    },
  };
  env.document = { hidden: env.hidden };
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
  const called = (name) =>
    "function " + name + "() { env.calls.push('" + name + "'); }";
  return new Function(
    "env",
    [
      "var serverConnected = env.connected;",
      "var appReady = env.ready;",
      "var dataSavedAt = null;",
      "var lastSyncTime = env.lastSync;",
      "var navigator = env.navigator;",
      "var document = env.document;",
      "var fetch = env.fetch;",
      "var setTimeout = env.setTimeout;",
      "var clearTimeout = env.clearTimeout;",
      "var WebSocket = env.WebSocket;",
      "var location = { protocol: 'https:', host: 'planner.test:8080' };",
      "var API = '/api';",
      "var viewMode = 'list';",
      "var serverAnswers = 0;",
      "var wsReconnectTimer = null;",
      "var wsConnectTimer = null;",
      "var pollTimer = env.polling ? 1 : null;",
      "var AUTH_TOKEN_KEY = 'pytodo_auth_token';",
      "var localStorage = env.localStorage;",
      "var caches = env.caches;",
      "function getAuthToken() { return env.localStorage.getItem('pytodo_auth_token') || ''; }",
      "function init() { env.calls.push('init'); }",
      functionText("authHeaders"),
      "var pinScreenUp = false;",
      env.ownRefresh
        ? functionText("showLoginScreen")
        : "function showLoginScreen() { env.calls.push('showLoginScreen'); pinScreenUp = true; }",
      functionText("startPage"),
      "function onServerPageVersion(version) { env.calls.push('version ' + version); }",
      constantText("WS_MAX_DELAY"),
      constantText("WS_MAX_DELAY_IN_VIEW"),
      constantText("WS_CONNECT_DEADLINE"),
      "var offlineBanner = env.banner;",
      "var offlineBannerText = env.text;",
      "var wsReconnectDelay = env.ownSockets ? 1000 : 30000;",
      "var ws = env.socket;",
      "var wsPingTimer = null;",
      "var wsPongTimer = null;",
      constantText("SOURCE_HEADER"),
      constantText("STORED_AT_HEADER"),
      constantText("READ_DEADLINE"),
      constantText("PROBE_DEADLINE"),
      constantText("WS_PING_INTERVAL"),
      constantText("WS_PONG_DEADLINE"),
      called("clearOfflineUndo"),
      called("updateConnectionIndicator"),
      called("updatePendingBadge"),
      called("startPolling"),
      called("stopPolling"),
      called("replayOfflineQueue"),
      env.ownRefresh
        ? functionText("refreshCurrentList")
        : called("refreshCurrentList"),
      "var currentListId = 'list-1';",
      "var serverItems = [];",
      "var cachedItems = [];",
      "var serverBoardData = null;",
      "var loginScreen = null, appContainer = null;",
      "var loginPinInput = env.pinInput, loginError = env.pinError, loginBtn = env.pinButton;",
      "function setAuthToken(token) { env.localStorage.setItem('pytodo_auth_token', token); }",
      env.ownRefresh
        ? functionText("hideLoginScreen")
        : "function hideLoginScreen() { env.calls.push('hideLoginScreen'); pinScreenUp = false; }",
      constantText("SIGN_IN_DEADLINE"),
      functionText("signIn"),
      "var console = { error: function () {} };",
      "function renderItems() {}",
      "function cacheListItems(id, items) { env.calls.push('cacheListItems'); }",
      "function showQueuedChanges() { env.drawn.push(serverItems.map(function (i) { return i.id; }).join(',')); }",
      "function refreshBoard() {}",
      "function refreshLists() {}",
      "function markSynced() { env.calls.push('markSynced'); }",
      "async function getCachedListRecord() { return env.stored; }",
      constantText("LIST_READ_AGAIN_AFTER"),
      "var listReadAgainTimer = null;",
      functionText("readListAgainSoon"),
      called("fetchUndoState"),
      env.ownSockets
        ? functionText("connectWebSocket")
        : called("connectWebSocket"),
      env.ownSockets
        ? functionText("scheduleReconnect")
        : called("scheduleReconnect"),
      env.ownSockets ? functionText("probeServer") : called("probeServer"),
      functionText("disconnectWebSocket"),
      functionText("pageViewChanged"),
      functionText("api"),
      functionText("apiAnswer"),
      functionText("webSocketOpen"),
      functionText("stopPinging"),
      functionText("waitToPing"),
      functionText("pingServer"),
      functionText("dropWebSocket"),
      functionText("storedTimeOf"),
      functionText("serverFetch"),
      functionText("serverAnswered"),
      functionText("serverSilent"),
      functionText("resumeWithServer"),
      functionText("waitForServer"),
      functionText("showConnection"),
      functionText("connectionNotice"),
      functionText("savedWhen"),
      functionText("setDataSavedAt"),
      "return {",
      "  env: env,",
      "  serverFetch: serverFetch,",
      "  serverAnswered: serverAnswered,",
      "  serverSilent: serverSilent,",
      "  showConnection: showConnection,",
      "  setDataSavedAt: setDataSavedAt,",
      "  storedTimeOf: storedTimeOf,",
      "  connectionNotice: connectionNotice,",
      "  savedWhen: savedWhen,",
      "  apiAnswer: apiAnswer,",
      "  refreshCurrentList: refreshCurrentList,",
      "  showLoginScreen: showLoginScreen,",
      "  startPage: startPage,",
      "  signIn: signIn,",
      "  hideLoginScreen: hideLoginScreen,",
      "  pinScreenUp: function () { return pinScreenUp; },",
      "  connectWebSocket: connectWebSocket,",
      "  scheduleReconnect: scheduleReconnect,",
      "  disconnectWebSocket: disconnectWebSocket,",
      "  pageViewChanged: pageViewChanged,",
      "  waitToPing: waitToPing,",
      "  pingServer: pingServer,",
      "  stopPinging: stopPinging,",
      "  connected: function () { return serverConnected; },",
      "  delay: function () { return wsReconnectDelay; },",
      "  socket: function () { return ws; },",
      "  replaceSocket: function (other) { ws = other; },",
      "};",
    ].join("\n"),
  )(env);
}

function answer(headers, status) {
  return new Response("{}", { status: status || 200, headers: headers || {} });
}

const FROM_STORE = {
  "X-Pytodo-Source": "store",
  "X-Pytodo-Stored-At": "1795124040000",
};

// --- What an answer says of the server ---

test("an answer without the worker's mark is the server's", () => {
  assert.equal(page().storedTimeOf(answer()), null);
});

test("an answer from the worker's store has the time it was stored", () => {
  assert.equal(page().storedTimeOf(answer(FROM_STORE)), 1795124040000);
});

test("a stored answer of unknown time, and one made up, have the time 0", () => {
  const made = page();
  assert.equal(
    made.storedTimeOf(
      answer({ "X-Pytodo-Source": "store", "X-Pytodo-Stored-At": "0" }),
    ),
    0,
  );
  assert.equal(
    made.storedTimeOf(answer({ "X-Pytodo-Source": "none" }, 503)),
    0,
  );
});

// --- The state follows the answers ---

test("an answer from the store means the server did not answer", async () => {
  const made = page({ fetch: async () => answer(FROM_STORE) });
  const resp = await made.serverFetch("/api/lists", {});
  assert.equal(resp.status, 200);
  assert.equal(made.connected(), false);
  assert.equal(made.env.banner.hidden, false);
});

test("a request that fails means the server did not answer", async () => {
  const made = page({
    fetch: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  await assert.rejects(made.serverFetch("/api/lists", {}), TypeError);
  assert.equal(made.connected(), false);
});

test("the server's own answer means it is there, a refusal included", async () => {
  for (const status of [200, 401, 409, 500]) {
    const made = page({
      connected: false,
      fetch: async () => answer({}, status),
    });
    await made.serverFetch("/api/lists", {});
    assert.equal(made.connected(), true, "after a " + status);
    assert.equal(made.env.banner.hidden, true);
  }
});

test("the browser's word that the device is online is not an answer", async () => {
  const made = page({
    deviceOnline: true,
    fetch: async () => answer(FROM_STORE),
  });
  await made.serverFetch("/api/status", {});
  assert.equal(made.connected(), false);
});

// --- What the page does at a change of state ---

test("when the server stops answering nothing more is asked at intervals", () => {
  const made = page({ connected: true });
  made.serverSilent();
  assert.deepEqual(
    made.env.calls.filter((name) => !name.startsWith("update")),
    ["stopPolling", "scheduleReconnect"],
  );
});

test("when the server answers again the queue is sent and the list read", () => {
  const made = page({ connected: false });
  made.serverAnswered();
  assert.deepEqual(
    made.env.calls.filter((name) => !name.startsWith("update")),
    [
      "clearOfflineUndo",
      "connectWebSocket",
      "startPolling",
      "replayOfflineQueue",
      "refreshCurrentList",
      "fetchUndoState",
    ],
  );
  // The next wait for the WebSocket starts short again.
  assert.equal(made.delay(), 1000);
});

test("with the WebSocket open nothing is asked at intervals", () => {
  const made = page({ connected: false, socket: socket() });
  made.serverAnswered();
  assert.equal(made.env.calls.includes("startPolling"), false);
});

test("an answer in the state the page is in changes nothing", () => {
  const up = page({ connected: true });
  up.serverAnswered();
  assert.deepEqual(up.env.calls, []);
  const silent = page({ connected: false });
  silent.serverSilent();
  assert.deepEqual(silent.env.calls, []);
});

test("while the page is starting only the state and the notice change", () => {
  // The start itself reads the lists, and goes on from the state it
  // finds when it is done.
  const made = page({ connected: true, ready: false });
  made.serverSilent();
  assert.equal(made.connected(), false);
  assert.equal(made.env.banner.hidden, false);
  assert.equal(made.env.calls.includes("scheduleReconnect"), false);
  made.serverAnswered();
  assert.equal(made.env.calls.includes("refreshCurrentList"), false);
});

// --- The notice ---

const NOON = new Date(2026, 10, 19, 12, 0);

test("the notice names the server while the device has a network", () => {
  assert.equal(
    page().connectionNotice(true, 0, NOON),
    "Can't reach the server.",
  );
});

test("the notice says offline when the device has no network", () => {
  assert.equal(page().connectionNotice(false, 0, NOON), "Offline.");
});

test("the notice says when the data shown was saved", () => {
  const made = page();
  assert.equal(
    made.connectionNotice(true, new Date(2026, 10, 19, 9, 5).getTime(), NOON),
    "Can't reach the server. Showing data saved at 09:05.",
  );
  assert.equal(
    made.connectionNotice(true, new Date(2026, 10, 18, 16, 34).getTime(), NOON),
    "Can't reach the server. Showing data saved at 16:34 yesterday.",
  );
  assert.equal(
    made.connectionNotice(
      false,
      new Date(2026, 10, 18, 16, 34).getTime(),
      NOON,
    ),
    "Offline. Showing data saved at 16:34 yesterday.",
  );
});

test("yesterday is the day before, however few hours ago", () => {
  const made = page();
  const justAfterMidnight = new Date(2026, 10, 19, 0, 10);
  assert.equal(
    made.savedWhen(new Date(2026, 10, 18, 23, 50), justAfterMidnight),
    "at 23:50 yesterday",
  );
  assert.equal(
    made.savedWhen(new Date(2026, 10, 19, 0, 5), justAfterMidnight),
    "at 00:05",
  );
});

test("an earlier day is named, with its year when that is another", () => {
  const made = page();
  const earlier = new Date(2026, 10, 14, 8, 0);
  assert.equal(
    made.savedWhen(earlier, NOON),
    "on " +
      earlier.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      }) +
      " at 08:00",
  );
  const lastYear = new Date(2025, 11, 30, 8, 0);
  assert.equal(
    made.savedWhen(lastYear, NOON),
    "on " +
      lastYear.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      }) +
      " at 08:00",
  );
});

test("the notice shows the time of the stored tasks on screen", () => {
  const made = page({ connected: true });
  made.serverSilent();
  made.setDataSavedAt(new Date(2026, 10, 18, 16, 34).getTime());
  assert.match(made.env.text.textContent, /Showing data saved .*16:34/);
});

test("tasks the server gave are as old as its last answer", () => {
  // The server answered, the list was drawn, and then it stopped.
  const made = page({
    connected: true,
    lastSync: new Date(2026, 10, 18, 16, 34).getTime(),
  });
  made.serverSilent();
  assert.match(made.env.text.textContent, /Showing data saved .*16:34/);
});

// --- A read that gets no answer ---

// A network on which a request waits until it is given up.
function noAnswer(seen) {
  return (url, opts) =>
    new Promise((resolve, reject) => {
      seen.push(opts);
      if (opts && opts.signal) {
        opts.signal.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      }
    });
}

test("a read with no answer is given up at its deadline", async () => {
  const made = page({ fetch: noAnswer([]) });
  const read = made.serverFetch("/api/lists", {});
  let outcome = "waiting";
  read.catch((error) => {
    outcome = error.name;
  });
  made.env.advance(9999);
  await null;
  assert.equal(outcome, "waiting");
  assert.equal(made.connected(), true);
  made.env.advance(1);
  await assert.rejects(read, { name: "AbortError" });
  assert.equal(made.connected(), false);
  assert.equal(made.env.banner.hidden, false);
});

test("the question whether the server is there has a shorter deadline", async () => {
  const made = page({ fetch: noAnswer([]) });
  const probe = made.serverFetch("/api/status", {}, 5000);
  made.env.advance(5000);
  await assert.rejects(probe, { name: "AbortError" });
  assert.equal(made.connected(), false);
});

test("a change has no deadline", async () => {
  // Giving one up says nothing of whether the server has made it.
  const seen = [];
  const made = page({ fetch: noAnswer(seen) });
  made.serverFetch("/api/items/1/toggle", { method: "PATCH" });
  made.serverFetch("/api/lists/1/items", { method: "post" });
  await null;
  assert.equal(seen[0].signal, undefined);
  assert.equal(seen[1].signal, undefined);
  assert.deepEqual(made.env.timers, []);
  made.env.advance(600000);
  assert.equal(made.connected(), true);
});

test("a read given its own way to be given up keeps it", async () => {
  const seen = [];
  const made = page({ fetch: noAnswer(seen) });
  const own = new AbortController();
  made.serverFetch("/api/lists", { signal: own.signal });
  await null;
  assert.equal(seen[0].signal, own.signal);
  assert.deepEqual(made.env.timers, []);
});

test("an answer in time is the server's, whatever the deadline does after", async () => {
  const made = page({ connected: false, fetch: async () => answer() });
  const resp = await made.serverFetch("/api/lists", {});
  made.env.advance(60000);
  assert.equal(made.connected(), true);
  assert.deepEqual(await resp.json(), {});
});

test("the caller's options are left as they were", async () => {
  const opts = { headers: { Authorization: "Bearer x" } };
  const made = page({ fetch: async () => answer() });
  await made.serverFetch("/api/lists", opts);
  assert.deepEqual(Object.keys(opts), ["headers"]);
});

// --- The question put over the WebSocket ---

test("an open socket is asked after the interval, and not before", () => {
  const open = socket();
  const made = page({ socket: open });
  made.waitToPing();
  made.env.advance(PING - 1);
  assert.deepEqual(open.sent, []);
  made.env.advance(1);
  assert.deepEqual(open.sent, ["ping"]);
});

test("a socket that says nothing by the deadline is given up", () => {
  const open = socket();
  const made = page({ socket: open });
  made.waitToPing();
  made.env.advance(PING + PONG - 1);
  assert.equal(open.closed, false);
  assert.equal(made.connected(), true);
  made.env.advance(1);
  assert.equal(open.closed, true);
  assert.equal(made.socket(), null);
  assert.equal(made.connected(), false);
  assert.equal(made.env.banner.hidden, false);
  // Nothing more is to follow from the socket itself.
  assert.equal(open.onclose, null);
  assert.equal(open.onmessage, null);
  // The server is tried again.
  assert.ok(made.env.calls.includes("scheduleReconnect"));
  assert.ok(made.env.calls.includes("stopPolling"));
});

test("anything the server says in time keeps the socket", () => {
  const open = socket();
  const made = page({ socket: open });
  made.waitToPing();
  made.env.advance(PING);
  // The page's onmessage starts the wait again for whatever arrives.
  made.env.advance(PONG - 1000);
  made.waitToPing();
  made.env.advance(PONG);
  assert.equal(open.closed, false);
  assert.equal(made.connected(), true);
  // And it is asked again an interval after that answer.
  made.env.advance(PING - PONG);
  assert.deepEqual(open.sent, ["ping", "ping"]);
});

test("a page out of view asks nothing", () => {
  // The browser holds its timers back there; a late one would pass
  // for a server that does not answer.
  const open = socket();
  const made = page({ socket: open, hidden: true });
  made.waitToPing();
  made.env.advance(600000);
  assert.deepEqual(open.sent, []);
  assert.equal(made.connected(), true);
});

test("a page that goes out of view drops the question it had put", () => {
  const open = socket();
  const made = page({ socket: open });
  made.waitToPing();
  made.env.advance(PING);
  assert.deepEqual(open.sent, ["ping"]);
  made.stopPinging();
  made.env.advance(600000);
  assert.equal(open.closed, false);
  assert.equal(made.connected(), true);
});

test("back in view, the server is asked at once", () => {
  const open = socket();
  const made = page({ socket: open });
  made.pingServer();
  assert.deepEqual(open.sent, ["ping"]);
  made.env.advance(PONG);
  assert.equal(open.closed, true);
  assert.equal(made.connected(), false);
});

test("a socket that cannot be written to is given up", () => {
  const open = socket();
  open.sendFails = true;
  const made = page({ socket: open });
  made.pingServer();
  assert.equal(made.socket(), null);
  assert.equal(made.connected(), false);
});

test("a socket that is not open is not asked", () => {
  const connecting = socket();
  connecting.readyState = 0;
  const made = page({ socket: connecting });
  made.pingServer();
  assert.deepEqual(connecting.sent, []);
  assert.deepEqual(made.env.timers, []);
  const none = page();
  none.pingServer();
  assert.deepEqual(none.env.timers, []);
});

test("a socket replaced meanwhile is not given up for the old one", () => {
  const old = socket();
  const made = page({ socket: old });
  made.pingServer();
  const next = socket();
  made.replaceSocket(next);
  made.env.advance(PONG);
  assert.equal(next.closed, false);
  assert.equal(made.socket(), next);
  assert.equal(made.connected(), true);
});

// --- Requests that end out of turn ---

test("a read given up after the server has answered another says nothing", async () => {
  // Sent down a connection that had died; a later read was answered.
  let calls = 0;
  const seen = [];
  const hangs = noAnswer(seen);
  const made = page({
    fetch: (url, opts) => (++calls === 1 ? hangs(url, opts) : answer()),
  });
  const old = made.serverFetch("/api/lists/1", {});
  made.env.advance(3000);
  await made.serverFetch("/api/lists/1", {});
  made.env.advance(7000);
  await assert.rejects(old, { name: "AbortError" });
  assert.equal(made.connected(), true);
  // The notice was never shown.
  assert.equal(made.env.text.textContent, "");
});

test("a stored answer that arrives after the server's own says nothing", async () => {
  let release;
  let calls = 0;
  const made = page({
    fetch: () =>
      ++calls === 1
        ? new Promise((resolve) => {
            release = () => resolve(answer(FROM_STORE));
          })
        : answer(),
  });
  const old = made.serverFetch("/api/lists/1", {});
  await made.serverFetch("/api/status", {});
  release();
  await old;
  assert.equal(made.connected(), true);
});

test("with no answer since, the first read given up makes the server silent", async () => {
  const made = page({ fetch: noAnswer([]) });
  const first = made.serverFetch("/api/lists/1", {});
  const second = made.serverFetch("/api/lists/1", {});
  made.env.advance(10000);
  await assert.rejects(first);
  await assert.rejects(second);
  assert.equal(made.connected(), false);
});

test("an answer whose body is cut off at the deadline makes the server silent", async () => {
  // The fetch gives the answer; its body never ends.
  const made = page({
    fetch: (url, opts) =>
      Promise.resolve({
        status: 200,
        ok: true,
        headers: new Headers(),
        json: () =>
          new Promise((resolve, reject) => {
            opts.signal.addEventListener("abort", () =>
              reject(
                new DOMException("The operation was aborted.", "AbortError"),
              ),
            );
          }),
      }),
  });
  const read = made.apiAnswer("/lists/1");
  await null;
  await null;
  await null;
  assert.equal(made.connected(), true);
  made.env.advance(10000);
  await assert.rejects(read, { name: "AbortError" });
  assert.equal(made.connected(), false);
});

test("an answer that is not JSON is the caller's matter, not the server's silence", async () => {
  const made = page({
    fetch: async () => new Response("<html>", { status: 200 }),
  });
  await assert.rejects(made.apiAnswer("/lists/1"), SyntaxError);
  assert.equal(made.connected(), true);
});

test("when the server answers again a try that was waiting is dropped", () => {
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: noAnswer([]),
  });
  made.scheduleReconnect();
  assert.equal(made.env.timers.length, 1);
  made.serverAnswered();
  // The try now under way is the page's only WebSocket; no timer is
  // left from the wait before.
  assert.equal(made.env.sockets.length, 1);
  const waits = made.env.timers.map((timer) => timer.at - made.env.now);
  assert.deepEqual(waits, [10000]); // the time this WebSocket has to open
});

// --- The WebSocket's own events ---

// A page whose WebSocket has just opened.
function connected(options) {
  const made = page(
    Object.assign({ ownSockets: true, fetch: async () => answer() }, options),
  );
  made.connectWebSocket();
  made.env.sockets[0].opens();
  made.env.calls.length = 0;
  return made;
}

// --- The start of the page ---
//
// The PIN screen is for the server's own refusal. A server that cannot
// be reached says nothing of the token, and a PIN typed then could not
// be checked.

// What the device keeps is as it was: the service worker, its stores
// and the token.
function nothingLost(made, token) {
  assert.deepEqual(made.env.workers, ["worker"]);
  assert.deepEqual(made.env.stores, ["pytodo-static-1", "pytodo-data"]);
  assert.equal(
    made.env.localStorage.getItem("pytodo_auth_token"),
    token === undefined ? "token" : token,
  );
}

// The ways a start gets no answer of the server's own.
const NO_ANSWER = {
  "a request that fails": () => async () => {
    throw new TypeError("Failed to fetch");
  },
  "an answer from the worker's store": () => async () => answer(FROM_STORE),
  "the answer the worker makes up": () => async () =>
    answer({ "X-Pytodo-Source": "none" }, 503),
};

for (const [what, network] of Object.entries(NO_ANSWER)) {
  test(
    "a start with a token and " + what + " goes on to the page",
    async () => {
      const made = page({ fetch: network() });
      await made.startPage();
      assert.ok(made.env.calls.includes("init"));
      assert.equal(made.env.calls.includes("showLoginScreen"), false);
      assert.equal(made.connected(), false);
      nothingLost(made);
    },
  );

  test(
    "a start without a token and " + what + " goes on to the page",
    async () => {
      // The PIN screen comes up when the server is there to check a PIN.
      const made = page({ token: "", fetch: network() });
      await made.startPage();
      assert.ok(made.env.calls.includes("init"));
      assert.equal(made.env.calls.includes("showLoginScreen"), false);
      assert.equal(made.connected(), false);
      // What an earlier pairing left on the device is still there.
      nothingLost(made, "");
    },
  );
}

test("a start whose first read is given up keeps what the device has stored", async () => {
  // The server keeps the request waiting, as a computer put to sleep
  // does. The token is as good as it was.
  for (const token of ["token", ""]) {
    const made = page({ token: token, fetch: noAnswer([]) });
    const start = made.startPage();
    made.env.advance(10000);
    await start;
    assert.ok(made.env.calls.includes("init"));
    assert.equal(made.env.calls.includes("showLoginScreen"), false);
    assert.equal(made.connected(), false);
    nothingLost(made, token);
  }
});

test("a start the server answers goes on to the page", async () => {
  const sent = [];
  const made = page({
    fetch: async (url, opts) => {
      sent.push(opts.headers.Authorization);
      return answer();
    },
  });
  await made.startPage();
  assert.deepEqual(sent, ["Bearer token"]);
  assert.ok(made.env.calls.includes("init"));
  assert.equal(made.env.calls.includes("showLoginScreen"), false);
  assert.equal(made.connected(), true);
});

test("a start the server answers with a fault of its own goes on to the page", async () => {
  // It has not refused the token.
  for (const status of [500, 503, 404]) {
    const made = page({ fetch: async () => answer({}, status) });
    await made.startPage();
    assert.ok(made.env.calls.includes("init"), "after a " + status);
    assert.equal(made.env.calls.includes("showLoginScreen"), false);
    nothingLost(made);
  }
});

test("a start the server refuses asks for the PIN and forgets the token", async () => {
  const made = page({ fetch: async () => answer({}, 401) });
  await made.startPage();
  assert.ok(made.env.calls.includes("showLoginScreen"));
  assert.equal(made.env.calls.includes("init"), false);
  assert.equal(made.env.localStorage.getItem("pytodo_auth_token"), null);
  // What is stored is not touched here.
  assert.deepEqual(made.env.workers, ["worker"]);
  assert.deepEqual(made.env.stores, ["pytodo-static-1", "pytodo-data"]);
});

test("a start without a token asks for the PIN when the server wants one", async () => {
  const sent = [];
  const made = page({
    token: "",
    fetch: async (url, opts) => {
      sent.push(opts.headers);
      return answer({}, 401);
    },
  });
  await made.startPage();
  assert.ok(made.env.calls.includes("showLoginScreen"));
  assert.equal(made.env.calls.includes("init"), false);
  // No token is sent where there is none.
  assert.deepEqual(sent, [undefined]);
  nothingLost(made, "");
});

test("a start without a token goes on to the page where the server wants none", async () => {
  const made = page({ token: "", fetch: async () => answer() });
  await made.startPage();
  assert.ok(made.env.calls.includes("init"));
  assert.equal(made.env.calls.includes("showLoginScreen"), false);
});

test("a refusal that is not the server's own does not bring up the PIN screen", async () => {
  // No such answer is made today; the rule is the page's all the same.
  const marked = { "X-Pytodo-Source": "store", "X-Pytodo-Stored-At": "0" };
  const made = page({ fetch: async () => answer(marked, 401) });
  await made.startPage();
  assert.equal(made.env.calls.includes("showLoginScreen"), false);
  assert.equal(made.env.localStorage.getItem("pytodo_auth_token"), "token");
  await assert.rejects(made.apiAnswer("/lists"));
  assert.equal(made.env.calls.includes("showLoginScreen"), false);
});

test("a read the server refuses brings up the PIN screen", async () => {
  const made = page({ fetch: async () => answer({}, 401) });
  await assert.rejects(made.apiAnswer("/lists"), { status: 401 });
  assert.ok(made.env.calls.includes("showLoginScreen"));
});

// --- The PIN screen ---

test("the right PIN stores the token and starts the page", async () => {
  const sent = [];
  const made = page({
    token: "",
    pin: " 123456 ",
    fetch: async (url, opts) => {
      sent.push([url, opts.method || "GET", opts.body]);
      if (url === "/api/status") return answer({}, 401);
      return new Response(JSON.stringify({ token: "new-token" }), {
        status: 200,
      });
    },
  });
  await made.signIn();
  // The server is asked with a read before the PIN is sent.
  assert.deepEqual(sent, [
    ["/api/status", "GET", undefined],
    ["/api/auth", "POST", '{"pin":"123456"}'],
  ]);
  assert.equal(made.env.localStorage.getItem("pytodo_auth_token"), "new-token");
  assert.ok(made.env.calls.includes("hideLoginScreen"));
  assert.ok(made.env.calls.includes("init"));
  assert.equal(made.env.pinButton.disabled, false);
  assert.equal(made.env.pinButton.textContent, "Connect");
});

test("a PIN the server refuses shows what the server says", async () => {
  const made = page({
    token: "",
    pin: "123456",
    fetch: async (url) =>
      url === "/api/status"
        ? answer({}, 401)
        : new Response(JSON.stringify({ error: "Invalid PIN" }), {
            status: 403,
          }),
  });
  await made.signIn();
  assert.equal(made.env.pinError.textContent, "Invalid PIN");
  assert.equal(made.env.calls.includes("init"), false);
  // No token is stored for it.
  assert.equal(made.env.localStorage.getItem("pytodo_auth_token"), "");
  assert.equal(made.env.pinButton.disabled, false);
});

test("a PIN sent to a server that is gone says so, and nothing stored is touched", async () => {
  const made = page({
    token: "",
    pin: "123456",
    fetch: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  await made.signIn();
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
  assert.deepEqual(made.env.workers, ["worker"]);
  assert.deepEqual(made.env.stores, ["pytodo-static-1", "pytodo-data"]);
  assert.equal(made.env.calls.includes("init"), false);
  // The PIN can be sent again.
  assert.equal(made.env.pinButton.disabled, false);
  assert.equal(made.env.pinButton.textContent, "Connect");
});

test("a server that keeps the read before the PIN waiting gets the message after 5 s", async () => {
  // A server that is not there can keep a request waiting for more
  // than a minute; the person is waiting at the button.
  const seen = [];
  const hangs = noAnswer([]);
  const made = page({
    token: "",
    pin: "123456",
    fetch: (url, opts) => {
      seen.push(url);
      return hangs(url, opts);
    },
  });
  const sent = made.signIn();
  await settled();
  assert.equal(made.env.pinButton.disabled, true);
  assert.equal(made.env.pinButton.textContent, "Connecting...");
  made.env.advance(4999);
  await settled();
  assert.equal(made.env.pinButton.disabled, true);
  made.env.advance(1);
  await sent;
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
  assert.equal(made.env.pinButton.disabled, false);
  assert.equal(made.env.pinButton.textContent, "Connect");
  // The PIN was not sent.
  assert.deepEqual(seen, ["/api/status"]);
  assert.equal(made.env.calls.includes("init"), false);
  nothingLost(made, "");
});

test("a PIN the server keeps waiting is given up after 10 s, with the message", async () => {
  const hangs = noAnswer([]);
  const made = page({
    token: "",
    pin: "123456",
    fetch: (url, opts) =>
      url === "/api/status"
        ? Promise.resolve(answer({}, 401))
        : hangs(url, opts),
  });
  const sent = made.signIn();
  await settled();
  made.env.advance(9999);
  await settled();
  assert.equal(made.env.pinButton.disabled, true);
  made.env.advance(1);
  await sent;
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
  assert.equal(made.env.pinButton.disabled, false);
  assert.equal(made.env.calls.includes("init"), false);
});

test("a read before the PIN that is answered from the store is no answer", async () => {
  const seen = [];
  const made = page({
    token: "",
    pin: "123456",
    fetch: async (url) => {
      seen.push(url);
      return answer(FROM_STORE);
    },
  });
  await made.signIn();
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
  assert.deepEqual(seen, ["/api/status"]);
});

test("the read before the PIN carries no token, and asks for no stored answer", async () => {
  // The device holds no token, or one the server has refused. And what
  // the service worker has stored would be no answer to the question.
  const carried = [];
  const made = page({
    pin: "123456",
    fetch: async (url, opts) => {
      carried.push(
        url +
          " " +
          JSON.stringify((opts && opts.headers) || {}) +
          " " +
          opts.cache,
      );
      return url === "/api/status"
        ? answer({}, 401)
        : new Response(JSON.stringify({ token: "new-token" }), { status: 200 });
    },
  });
  await made.signIn();
  assert.equal(carried[0], "/api/status {} no-store");
});

test("a PIN answered in time is not given up afterward", async () => {
  const made = page({
    token: "",
    pin: "123456",
    fetch: async () =>
      new Response(JSON.stringify({ token: "new-token" }), { status: 200 }),
  });
  await made.signIn();
  made.env.advance(60000);
  await settled();
  assert.equal(made.env.pinError.textContent, "");
  assert.equal(made.env.localStorage.getItem("pytodo_auth_token"), "new-token");
});

test("a PIN of fewer than four characters is not sent", async () => {
  for (const pin of ["", "12", "123", "   "]) {
    let sent = 0;
    const made = page({
      token: "",
      pin: pin,
      fetch: async () => {
        sent += 1;
        return answer();
      },
    });
    await made.signIn();
    assert.equal(sent, 0);
    assert.equal(made.env.pinButton.disabled, false);
  }
});

test("an earlier message on the PIN screen goes when a PIN is sent", async () => {
  const made = page({
    token: "",
    pin: "123456",
    fetch: async () =>
      new Response(JSON.stringify({ token: "new-token" }), { status: 200 }),
  });
  made.env.pinError.textContent = "Invalid PIN";
  await made.signIn();
  assert.equal(made.env.pinError.textContent, "");
});

test("the WebSocket is opened at the page's address, with the token", () => {
  const made = page({ ownSockets: true });
  made.connectWebSocket();
  assert.equal(
    made.env.sockets[0].url,
    "wss://planner.test:8080/ws?token=token",
  );
  // A second call while that one connects starts no other.
  made.connectWebSocket();
  assert.equal(made.env.sockets.length, 1);
});

test("a WebSocket that opens is the server's answer, and is asked after the interval", () => {
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: async () => answer(),
  });
  made.connectWebSocket();
  const opened = made.env.sockets[0];
  opened.opens();
  assert.equal(made.connected(), true);
  assert.ok(made.env.calls.includes("stopPolling"));
  assert.ok(made.env.calls.includes("replayOfflineQueue"));
  made.env.advance(PING);
  assert.deepEqual(opened.sent, ["ping"]);
});

test("the server's answer to the question keeps the WebSocket", () => {
  const made = connected();
  const open = made.env.sockets[0];
  made.env.advance(PING);
  made.env.advance(PONG - 1000);
  open.says({ event: "pong" });
  made.env.advance(PONG);
  assert.equal(open.closed, false);
  assert.equal(made.socket(), open);
  assert.equal(made.connected(), true);
  // Asked again an interval after the answer.
  made.env.advance(PING - PONG);
  assert.deepEqual(open.sent, ["ping", "ping"]);
});

test("anything else the server sends counts as its answer too", () => {
  const made = connected();
  const open = made.env.sockets[0];
  made.env.advance(PING);
  open.says({ event: "refresh" });
  assert.ok(made.env.calls.includes("refreshCurrentList"));
  made.env.advance(PONG);
  assert.equal(open.closed, false);
});

test("no answer to the question: the WebSocket is given up and another tried", () => {
  const made = connected({ fetch: noAnswer([]) });
  const dead = made.env.sockets[0];
  made.env.advance(PING + PONG);
  assert.equal(made.connected(), false);
  assert.equal(made.env.banner.hidden, false);
  assert.equal(dead.closed, true);
  // The first new try comes a second later.
  made.env.advance(1000);
  assert.equal(made.env.sockets.length, 2);
});

test("a message while the server was taken for silent brings the page back", () => {
  const made = connected();
  made.serverSilent();
  assert.equal(made.connected(), false);
  made.env.sockets[0].says({ event: "pong" });
  assert.equal(made.connected(), true);
  assert.equal(made.env.banner.hidden, true);
});

test("the greeting names the version of the page the server has", () => {
  const made = connected();
  made.env.sockets[0].says({ event: "hello", page_version: "abc" });
  assert.ok(made.env.calls.includes("version abc"));
});

test("a WebSocket the server closes: the server is asked, and tried again", async () => {
  const asked = [];
  const made = connected({
    fetch: async (url) => {
      asked.push(url);
      return answer();
    },
  });
  made.env.sockets[0].closes();
  assert.equal(made.socket(), null);
  assert.deepEqual(asked, ["/api/status"]);
  // Until the WebSocket is back the list is asked for at intervals.
  assert.ok(made.env.calls.includes("startPolling"));
  made.env.advance(1000);
  assert.equal(made.env.sockets.length, 2);
});

test("a WebSocket that has not opened by its deadline is closed", () => {
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: noAnswer([]),
  });
  made.connectWebSocket();
  const slow = made.env.sockets[0];
  made.env.advance(9999);
  assert.equal(slow.closed, false);
  made.env.advance(1);
  assert.equal(slow.closed, true);
  assert.equal(made.socket(), null);
});

test("a WebSocket that opened in time is left alone at that deadline", () => {
  const made = connected();
  const open = made.env.sockets[0];
  // The server goes on answering meanwhile.
  for (let passed = 0; passed < 10000; passed += 2000) {
    made.env.advance(2000);
    open.says({ event: "pong" });
  }
  assert.equal(open.closed, false);
  assert.equal(made.socket(), open);
});

test("an old WebSocket's late close does not disturb the one after it", () => {
  const made = connected();
  const first = made.env.sockets[0];
  const late = first.onclose;
  made.disconnectWebSocket();
  made.connectWebSocket();
  const second = made.env.sockets[1];
  second.opens();
  late();
  assert.equal(made.socket(), second);
  made.env.advance(PING);
  assert.deepEqual(second.sent, ["ping"]);
});

// --- Trying again while the server is silent ---

test("a silent server is asked after 1, 2 and 4 seconds, then every 5 while the page is in view", () => {
  // The WebSocket never opens and no request is answered.
  const asked = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: (url, opts) => {
      asked.push(made.env.now / 1000);
      return hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(200000);
  assert.deepEqual(asked.slice(0, 8), [1, 3, 7, 12, 17, 22, 27, 32]);
  // A WebSocket that hangs while it connects is closed at its deadline,
  // and another is opened at the next try.
  assert.ok(made.env.sockets.length >= 5, made.env.sockets.length + " tried");
  assert.equal(
    made.env.sockets.filter((tried) => !tried.closed).length <= 1,
    true,
  );
});

test("out of view the waits go on doubling, up to 30 seconds", () => {
  // The browser holds a hidden page's timers back anyway.
  const asked = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    hidden: true,
    fetch: (url, opts) => {
      asked.push(made.env.now / 1000);
      return hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(200000);
  assert.deepEqual(asked.slice(0, 8), [1, 3, 7, 15, 31, 61, 91, 121]);
});

test("back in view the tries start short again", () => {
  const asked = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    hidden: true,
    fetch: (url, opts) => {
      if (url === "/api/status") asked.push(made.env.now / 1000);
      return hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(100000); // tries at 1, 3, 7, 15, 31, 61 and 91; the next is due at 121
  asked.length = 0;
  made.env.document.hidden = false;
  made.pageViewChanged();
  // The try that was waiting is dropped: nothing is due at 121 s.
  assert.equal(
    made.env.timers.some((timer) => timer.at === 121000),
    false,
  );
  made.env.advance(40000);
  // From the return at 100 s: after 1, 2 and 4 seconds, then every 5,
  // one try at a time.
  assert.deepEqual(asked, [101, 103, 107, 112, 117, 122, 127, 132, 137]);
});

test("a page that goes out of view goes over to the long waits", () => {
  // The common order on a phone: in view, the server falls silent, the
  // phone is put away.
  const asked = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: (url, opts) => {
      if (url === "/api/status") asked.push(made.env.now / 1000);
      return hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(30000);
  made.env.document.hidden = true;
  made.pageViewChanged();
  made.env.advance(100000);
  assert.deepEqual(asked, [1, 3, 7, 12, 17, 22, 27, 32, 62, 92, 122]);
});

// A page in view whose server answers over HTTP while no WebSocket can
// be opened: each one made is closed at once. Returns the page and the
// times, in seconds, at which WebSockets were made.
function noWebSocket(options) {
  const made = page(
    Object.assign({ ownSockets: true, fetch: async () => answer() }, options),
  );
  const times = [];
  made.runFor = (milliseconds) => {
    for (let passed = 0; passed <= milliseconds; passed += 100) {
      for (const tried of made.env.sockets) {
        if (tried.readyState === 0) {
          times.push(Math.round(made.env.now / 100) / 10);
          tried.closes();
        }
      }
      if (passed < milliseconds) made.env.advance(100);
    }
  };
  made.connectWebSocket();
  return { made: made, times: times };
}

test("a server that answers while no WebSocket opens is tried at the long waits", () => {
  // The short waits are for a silent server: here the list is read at
  // intervals meanwhile, and every try is a request to a healthy server.
  const { made, times } = noWebSocket();
  made.runFor(100000);
  assert.deepEqual(times, [0, 1, 3, 7, 15, 31, 61, 91]);
  assert.equal(made.connected(), true);
});

test("the reads at intervals keep their beat through those tries", () => {
  const { made } = noWebSocket({ polling: true });
  made.runFor(40000);
  assert.equal(made.env.calls.includes("startPolling"), false);
  const { made: idle } = noWebSocket();
  idle.runFor(1000);
  assert.ok(idle.env.calls.includes("startPolling"));
});

test("when that server falls silent the tries start short again", () => {
  const { made, times } = noWebSocket();
  made.runFor(100000); // the next try is due at 121 s
  times.length = 0;
  made.serverSilent();
  made.runFor(20000);
  assert.deepEqual(times, [101, 103, 107, 112, 117]);
});

test("back in view while the server answers, the waits are not started over", () => {
  const { made, times } = noWebSocket();
  made.runFor(100000); // the next try is due at 121 s
  times.length = 0;
  made.env.document.hidden = true;
  made.pageViewChanged();
  made.env.document.hidden = false;
  made.pageViewChanged();
  made.runFor(40000);
  // One try at once on the return, and the one that was waiting.
  assert.deepEqual(times, [100, 121]);
});

test("each try asks the server over HTTP as well, for no stored answer", () => {
  const asked = [];
  const how = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: (url, opts) => {
      asked.push(url);
      how.push(opts.cache);
      return hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(1000);
  assert.deepEqual(asked, ["/api/status"]);
  assert.deepEqual(how, ["no-store"]);
  made.env.advance(2000);
  assert.equal(asked.length, 2);
});

test("a WebSocket that hangs while it connects does not stop the tries", () => {
  // It neither opens nor closes of itself; only its deadline ends it.
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: noAnswer([]),
  });
  made.scheduleReconnect();
  made.env.advance(1000);
  assert.equal(made.env.sockets.length, 1);
  assert.ok(made.env.timers.length >= 2, "the next try is already set");
});

test("without a network nothing is tried", () => {
  const made = page({
    connected: false,
    ownSockets: true,
    deviceOnline: false,
    fetch: noAnswer([]),
  });
  made.scheduleReconnect();
  made.env.advance(120000);
  assert.equal(made.env.sockets.length, 0);
});

test("once the server answers the tries end", async () => {
  let up = false;
  const asked = [];
  const hangs = noAnswer([]);
  const made = page({
    connected: false,
    ownSockets: true,
    fetch: (url, opts) => {
      asked.push(url);
      return up ? Promise.resolve(answer()) : hangs(url, opts);
    },
  });
  made.scheduleReconnect();
  made.env.advance(1000);
  up = true;
  made.env.advance(2000);
  // The try at 3 s is answered over HTTP.
  for (let i = 0; i < 6; i++) await null;
  assert.equal(made.connected(), true);
  made.env.sockets[made.env.sockets.length - 1].opens();
  const sockets = made.env.sockets.length;
  const requests = asked.length;
  // Up to the first question over the WebSocket nothing more is tried.
  made.env.advance(PING - 1000);
  assert.equal(made.env.sockets.length, sockets);
  assert.equal(asked.length, requests);
});

test("a WebSocket closed on purpose leaves nothing behind", () => {
  const made = connected();
  const open = made.env.sockets[0];
  made.env.advance(PING);
  made.disconnectWebSocket();
  assert.equal(open.closed, true);
  assert.equal(made.socket(), null);
  assert.deepEqual(made.env.timers, []);
  assert.equal(made.connected(), true);
  assert.equal(made.env.sockets.length, 1);
});

// --- Out of view and back ---

test("a page that goes out of view stops asking", () => {
  const made = connected();
  const open = made.env.sockets[0];
  made.env.advance(PING);
  made.env.document.hidden = true;
  made.pageViewChanged();
  made.env.advance(600000);
  assert.deepEqual(open.sent, ["ping"]);
  assert.equal(open.closed, false);
  assert.equal(made.connected(), true);
  assert.ok(made.env.calls.includes("stopPolling"));
});

test("a page that comes back into view asks at once", () => {
  const made = connected({ fetch: noAnswer([]) });
  const open = made.env.sockets[0];
  made.env.document.hidden = true;
  made.pageViewChanged();
  made.env.document.hidden = false;
  made.pageViewChanged();
  assert.deepEqual(open.sent, ["ping"]);
  assert.ok(made.env.calls.includes("refreshCurrentList"));
  // The server went while the page was out of view.
  made.env.advance(PONG);
  assert.equal(made.connected(), false);
});

test("back in view without a WebSocket, one is opened", () => {
  const made = page({ ownSockets: true, fetch: async () => answer() });
  made.pageViewChanged();
  assert.equal(made.env.sockets.length, 1);
  assert.ok(made.env.calls.includes("startPolling"));
});

// --- Stored tasks under a page that counts the server as there ---

function list(ids, headers) {
  return new Response(
    JSON.stringify({ items: ids.map((id) => ({ id: id })) }),
    { status: 200, headers: headers || {} },
  );
}

// Lets what was waiting on a promise go on.
const settled = () => new Promise((resolve) => setImmediate(resolve));

test("the server's own tasks are not read again", async () => {
  let reads = 0;
  const made = page({
    ownRefresh: true,
    fetch: async () => {
      reads += 1;
      return list(["new"]);
    },
  });
  await made.refreshCurrentList();
  assert.deepEqual(made.env.drawn, ["new"]);
  assert.ok(made.env.calls.includes("markSynced"));
  made.env.advance(60000);
  await settled();
  assert.equal(reads, 1);
});

test("stored tasks that leave the server silent are not read again here", async () => {
  // The notice shows, and the tries for a silent server take over.
  const made = page({
    ownRefresh: true,
    fetch: async () => list(["old"], FROM_STORE),
  });
  await made.refreshCurrentList();
  assert.equal(made.connected(), false);
  assert.deepEqual(made.env.drawn, ["old"]);
  assert.equal(made.env.calls.includes("markSynced"), false);
  assert.equal(made.env.calls.includes("cacheListItems"), false);
  // Nothing is set to read it again.
  assert.equal(
    made.env.timers.some((timer) => timer.at === 1000),
    false,
  );
  made.env.advance(60000);
  await settled();
  assert.deepEqual(made.env.drawn, ["old"]);
});

test("stored tasks under a page still counted as connected are read again", async () => {
  // The service worker gave the stored list for a read the server was
  // slow to answer; meanwhile the server said something else.
  let give;
  let reads = 0;
  const made = page({
    ownRefresh: true,
    fetch: () =>
      ++reads === 1
        ? new Promise((resolve) => {
            give = () => resolve(list(["old"], FROM_STORE));
          })
        : Promise.resolve(list(["new"])),
  });
  const first = made.refreshCurrentList();
  made.serverAnswered(); // the greeting on a WebSocket just opened
  give();
  await first;
  assert.equal(made.connected(), true);
  assert.deepEqual(made.env.drawn, ["old"]);

  made.env.advance(999);
  await settled();
  assert.equal(reads, 1);
  made.env.advance(1);
  await settled();
  assert.equal(reads, 2);
  assert.deepEqual(made.env.drawn, ["old", "new"]);
  assert.ok(made.env.calls.includes("markSynced"));
  // And that is the end of it.
  made.env.advance(60000);
  await settled();
  assert.equal(reads, 2);
});

test("they are read again for as long as stored ones come back", async () => {
  let reads = 0;
  let heard = () => {};
  const made = page({
    ownRefresh: true,
    fetch: async () => {
      reads += 1;
      heard(); // the server says something else during each read
      return reads < 4 ? list(["old"], FROM_STORE) : list(["new"]);
    },
  });
  heard = () => made.serverAnswered();
  await made.refreshCurrentList();
  for (let i = 0; i < 5; i++) {
    made.env.advance(1000);
    await settled();
  }
  assert.equal(reads, 4);
  assert.equal(made.env.drawn[made.env.drawn.length - 1], "new");
});

test("a read given up under a page still counted as connected is made again", async () => {
  let reads = 0;
  const hangs = noAnswer([]);
  const made = page({
    ownRefresh: true,
    fetch: (url, opts) =>
      ++reads === 1 ? hangs(url, opts) : Promise.resolve(list(["new"])),
  });
  const first = made.refreshCurrentList();
  made.env.advance(5000);
  made.serverAnswered();
  made.env.advance(5000);
  await first;
  assert.equal(made.connected(), true);
  // What the device kept is shown meanwhile.
  assert.deepEqual(made.env.drawn, ["kept"]);
  made.env.advance(1000);
  await settled();
  assert.deepEqual(made.env.drawn, ["kept", "new"]);
});

test("a list the server refuses is not asked for again", async () => {
  for (const status of [401, 404, 500]) {
    let reads = 0;
    const made = page({
      ownRefresh: true,
      fetch: async () => {
        reads += 1;
        return answer({}, status);
      },
    });
    await made.refreshCurrentList();
    made.env.advance(60000);
    await settled();
    assert.equal(reads, 1, "after a " + status);
  }
});

test("the PIN screen is not brought up again by a read that was waiting", async () => {
  let reads = 0;
  let heard = () => {};
  const made = page({
    ownRefresh: true,
    fetch: async () => {
      reads += 1;
      heard();
      return list(["old"], FROM_STORE);
    },
  });
  heard = () => made.serverAnswered();
  await made.refreshCurrentList();
  // The list is due to be read again in a second.
  assert.ok(made.env.timers.some((timer) => timer.at === 1000));
  made.showLoginScreen();
  made.env.advance(60000);
  await settled();
  assert.equal(reads, 1);
});

test("a WebSocket that opens while the list comes from the store ends with the server's list", async () => {
  // The server is back: the WebSocket opens and greets, but the read
  // it starts is answered from the store first.
  let give;
  let reads = 0;
  const made = page({
    connected: false,
    ownSockets: true,
    ownRefresh: true,
    fetch: (url) => {
      if (url !== "/api/lists/list-1") return Promise.resolve(answer());
      return ++reads === 1
        ? new Promise((resolve) => {
            give = () => resolve(list(["old"], FROM_STORE));
          })
        : Promise.resolve(list(["new"]));
    },
  });
  made.connectWebSocket();
  const opened = made.env.sockets[0];
  opened.opens();
  opened.says({ event: "hello", page_version: "" });
  give();
  await settled();
  assert.equal(made.connected(), true);
  assert.deepEqual(made.env.drawn, ["old"]);
  made.env.advance(1000);
  await settled();
  assert.equal(made.connected(), true);
  assert.equal(made.env.drawn[made.env.drawn.length - 1], "new");
});

// --- How quickly ---

test("a server that falls silent is noticed within 8 seconds, one that is back within 5", () => {
  assert.equal(PING, 5000);
  assert.equal(PONG, 3000);
  assert.equal(numberOf("WS_MAX_DELAY_IN_VIEW"), 5000);
  assert.equal(numberOf("WS_MAX_DELAY"), 30000);
});

// --- Behind the PIN screen ---
//
// The device holds no token the server accepts: whatever the page
// asked would be refused, and each refusal would come back to the PIN
// screen. Nothing tries the server until a PIN has been accepted.

// A server that knows one token: a read without it is refused, and the
// right PIN is answered with it. Every request is listed in sent, with
// the token it carried.
function pairingServer(sent, options) {
  const state = Object.assign({ up: true }, options);
  const network = async (url, opts) => {
    const carried = ((opts && opts.headers) || {}).Authorization || "none";
    sent.push(
      (opts && opts.method ? opts.method + " " : "") + url + " " + carried,
    );
    if (!state.up) throw new TypeError("Failed to fetch");
    if (url === "/api/auth") {
      return new Response(JSON.stringify({ token: "new-token" }), {
        status: 200,
      });
    }
    if (carried !== "Bearer new-token") return answer({}, 401);
    return url.startsWith("/api/lists/") ? list(["new"]) : answer();
  };
  network.state = state;
  return network;
}

// A page that has started, with the PIN screen up: its own reads,
// WebSockets and PIN screen, and no token.
function atPinScreen(options) {
  const sent = [];
  const network = pairingServer(sent);
  const made = page(
    Object.assign(
      { token: "", ownRefresh: true, ownSockets: true, fetch: network },
      options,
    ),
  );
  made.showLoginScreen();
  // What is typed once the screen is up.
  if (options && options.pin) made.env.pinInput.value = options.pin;
  sent.length = 0;
  return { made: made, sent: sent, server: network.state };
}

test("the right PIN starts the page, and nothing is asked before the token is held", async () => {
  // The page took the server for silent: its answer to the PIN is the
  // first it hears of it again.
  const { made, sent } = atPinScreen({ connected: false, pin: "123456" });
  await made.signIn();
  await settled();
  made.env.advance(2000);
  await settled();
  assert.deepEqual(sent, ["/api/status none", "POST /api/auth none"]);
  assert.equal(made.pinScreenUp(), false);
  assert.ok(made.env.calls.includes("init"));
  assert.equal(made.connected(), true);
  // No WebSocket without the token either: the start that follows
  // opens one with it.
  assert.equal(made.env.sockets.length, 0);
});

test("a PIN sent to a server that is gone starts nothing behind the PIN screen", async () => {
  const { made, sent, server } = atPinScreen({ pin: "123456" });
  server.up = false;
  await made.signIn();
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
  assert.equal(made.connected(), false);
  assert.deepEqual(made.env.timers, []);
  // The server comes back; the page leaves it alone, and what is typed.
  server.up = true;
  made.env.advance(60000);
  await settled();
  // The read that came first got no answer: the PIN was not sent.
  assert.deepEqual(sent, ["/api/status none"]);
  assert.equal(made.env.sockets.length, 0);
  assert.equal(made.env.pinInput.value, "123456");
  assert.equal(
    made.env.pinError.textContent,
    "Can't reach the server. Try again when it is back.",
  );
});

test("then the right PIN starts the page", async () => {
  const { made, sent, server } = atPinScreen({ pin: "123456" });
  server.up = false;
  await made.signIn();
  server.up = true;
  await made.signIn();
  await settled();
  made.env.advance(2000);
  await settled();
  assert.deepEqual(sent, [
    "/api/status none",
    "/api/status none",
    "POST /api/auth none",
  ]);
  assert.equal(made.pinScreenUp(), false);
  assert.equal(made.env.pinError.textContent, "");
});

test("a page that starts without the server brings the PIN screen up when the server refuses, and then is still", async () => {
  // No token, no server: the page started, and goes on trying.
  const sent = [];
  const network = pairingServer(sent, { up: false });
  const made = page({
    token: "",
    connected: false,
    ownRefresh: true,
    ownSockets: true,
    fetch: network,
  });
  made.scheduleReconnect();
  network.state.up = true;
  made.env.advance(1000);
  await settled();
  // The server refuses a WebSocket without a token.
  made.env.sockets.forEach((tried) => tried.closes());
  await settled();
  assert.equal(made.pinScreenUp(), true);

  made.env.pinInput.value = "123";
  const requests = sent.length;
  const sockets = made.env.sockets.length;
  made.env.advance(60000);
  await settled();
  assert.equal(sent.length, requests);
  assert.equal(made.env.sockets.length, sockets);
  assert.equal(made.env.pinInput.value, "123");
  const polling = made.env.calls.filter((name) => name.endsWith("Polling"));
  assert.equal(polling[polling.length - 1], "stopPolling");
});

test("the PIN screen empties its field when it comes up, not when it is up", () => {
  const made = page({ token: "", ownRefresh: true });
  made.env.pinInput.value = "left from before";
  made.env.pinError.textContent = "Invalid PIN";
  made.showLoginScreen();
  assert.equal(made.env.pinInput.value, "");
  assert.equal(made.env.pinError.textContent, "");
  made.env.pinInput.value = "1234";
  made.env.pinError.textContent = "Invalid PIN";
  made.showLoginScreen();
  assert.equal(made.env.pinInput.value, "1234");
  assert.equal(made.env.pinError.textContent, "Invalid PIN");
  made.hideLoginScreen();
  made.showLoginScreen();
  assert.equal(made.env.pinInput.value, "");
});

test("a read refused for a token the device no longer holds does not bring the PIN screen back", async () => {
  // Sent before the PIN was accepted, answered after.
  let refuse;
  const made = page({
    token: "",
    ownRefresh: true,
    fetch: () =>
      new Promise((resolve) => {
        refuse = () => resolve(answer({}, 401));
      }),
  });
  const read = made.apiAnswer("/lists");
  made.env.localStorage.setItem("pytodo_auth_token", "new-token");
  refuse();
  await assert.rejects(read, { status: 401 });
  assert.equal(made.pinScreenUp(), false);
});

test("a read refused for the token the device holds brings the PIN screen up", async () => {
  const made = page({ ownRefresh: true, fetch: async () => answer({}, 401) });
  await assert.rejects(made.apiAnswer("/lists"), { status: 401 });
  assert.equal(made.pinScreenUp(), true);
});

test("behind the PIN screen no WebSocket is opened and no try is set", () => {
  const { made } = atPinScreen();
  made.connectWebSocket();
  made.scheduleReconnect();
  assert.equal(made.env.sockets.length, 0);
  assert.deepEqual(made.env.timers, []);
  // Nor when the server is heard from, or lost.
  made.serverSilent();
  made.serverAnswered();
  assert.equal(made.env.sockets.length, 0);
  assert.deepEqual(made.env.timers, []);
  assert.equal(made.env.calls.includes("replayOfflineQueue"), false);
});

test("a page that comes back into view behind the PIN screen asks nothing", async () => {
  const { made, sent } = atPinScreen();
  made.env.document.hidden = true;
  made.pageViewChanged();
  made.env.document.hidden = false;
  made.pageViewChanged();
  await settled();
  assert.deepEqual(sent, []);
  assert.equal(made.env.sockets.length, 0);
});

test("once the PIN screen is gone the page tries the server as before", () => {
  const { made } = atPinScreen();
  made.hideLoginScreen();
  made.connectWebSocket();
  assert.equal(made.env.sockets.length, 1);
});

test("a token refused in mid-use closes the WebSocket and stops asking over it", async () => {
  // The device was removed at the desktop while its page was open.
  const made = connected({
    ownRefresh: true,
    fetch: async () => answer({}, 401),
  });
  const open = made.env.sockets[0];
  await assert.rejects(made.apiAnswer("/lists"), { status: 401 });
  assert.equal(made.pinScreenUp(), true);
  assert.equal(open.closed, true);
  assert.equal(made.socket(), null);
  // No question over the WebSocket is left to be put, and no try.
  made.env.advance(60000);
  await settled();
  assert.deepEqual(open.sent, []);
  assert.equal(made.env.sockets.length, 1);
});
