/* PyTodo-Qt Web UI — SPA with hash routing, dual view, and offline support */
(function () {
  "use strict";

  var API = "/api";
  var OFFLINE_QUEUE_KEY = "pytodo_offline_queue";
  var VIEW_MODE_KEY = "pytodo_view_mode";
  var CAL_VIEW_KEY = "pytodo_cal_view";
  var INSTALL_DISMISSED_KEY = "pytodo_install_dismissed";
  var AUTH_TOKEN_KEY = "pytodo_auth_token";
  var COLLAPSED_PARENTS_KEY = "pytodo_collapsed_parents";
  var THEME_KEY = "pytodo_theme";

  var currentListId = null;
  var cachedLists = [];
  // What the server last sent for the current list, and what the page
  // shows: the same with the queued changes applied (showQueuedChanges).
  var serverItems = [];
  var serverBoardData = null;
  var cachedItems = [];
  var cachedBoardData = null;
  var allTags = [];
  var pollTimer = null;
  var isOnline = navigator.onLine;
  var parseDebounceTimer = null;
  var saveDebounceTimer = null;
  var viewMode = localStorage.getItem(VIEW_MODE_KEY) || "list";
  var lastItemsFingerprint = "";
  var lastListsFingerprint = "";
  var lastBoardFingerprint = "";
  var lastSyncTime = 0;
  var offlineUndoStack = [];
  var offlineRedoStack = [];
  var serverUndoState = {
    can_undo: false,
    can_redo: false,
    undo_text: "",
    redo_text: "",
  };

  // Collapsed parent IDs for list view subtask toggle
  var collapsedParents = (function () {
    try {
      var stored = localStorage.getItem(COLLAPSED_PARENTS_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch (e) {
      return {};
    }
  })();

  function saveCollapsedParents() {
    try {
      localStorage.setItem(
        COLLAPSED_PARENTS_KEY,
        JSON.stringify(collapsedParents),
      );
    } catch (e) {
      /* best-effort */
    }
  }

  function toggleCollapse(parentId) {
    if (collapsedParents[parentId]) {
      delete collapsedParents[parentId];
    } else {
      collapsedParents[parentId] = true;
    }
    saveCollapsedParents();
    renderItems(cachedItems, true);
  }

  // Theme management: "system" (default), "light", or "dark"
  var currentTheme = localStorage.getItem(THEME_KEY) || "system";

  function applyTheme(theme) {
    currentTheme = theme;
    if (theme === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
    } else if (theme === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {
      /* best-effort */
    }
  }

  function cycleTheme() {
    var next =
      currentTheme === "system"
        ? "light"
        : currentTheme === "light"
          ? "dark"
          : "system";
    applyTheme(next);
    updateThemeLabel();
  }

  function getThemeLabel() {
    if (currentTheme === "light") return "Light";
    if (currentTheme === "dark") return "Dark";
    var isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    return isDark ? "Dark (system)" : "Light (system)";
  }

  function updateThemeLabel() {
    var el = document.getElementById("settings-theme");
    if (el) el.textContent = getThemeLabel();
  }

  // Apply saved theme immediately
  applyTheme(currentTheme);

  // ====================================================================
  // DOM refs
  // ====================================================================

  var offlineBanner = document.getElementById("offline-banner");
  var connectionDot = document.getElementById("connection-dot");
  var lastSyncedEl = document.getElementById("last-synced");
  var headerTitle = document.getElementById("header-title");
  var listPickerBtn = document.getElementById("list-picker-btn");
  var listPickerName = document.getElementById("list-picker-name");
  var listSheet = document.getElementById("list-sheet");
  var listSheetBody = document.getElementById("list-sheet-body");
  var listSheetClose = document.getElementById("list-sheet-close");
  var listCreateInput = document.getElementById("list-create-input");
  var listCreateBtn = document.getElementById("list-create-btn");
  var viewToggle = document.getElementById("view-toggle");
  var viewBtns = viewToggle ? viewToggle.querySelectorAll(".view-btn") : [];
  var sortBtn = document.getElementById("sort-btn");
  var sortSheet = document.getElementById("sort-sheet");
  var sortSheetClose = document.getElementById("sort-sheet-close");
  var sortTierSelects = document.querySelectorAll(".sort-tier-select");
  var sortDirBtns = document.querySelectorAll(".sort-dir-btn");
  var itemsContainer = document.getElementById("items-container");
  var emptyMsg = document.getElementById("empty-msg");
  var boardContainer = document.getElementById("board-container");
  var boardEmptyMsg = document.getElementById("board-empty-msg");
  var boardLayoutBtn = document.getElementById("board-layout-btn");
  var addSheet = document.getElementById("add-sheet");
  var addForm = document.getElementById("add-form");
  var addInput = document.getElementById("add-input");
  var addEntities = document.getElementById("add-entities");
  var addListSelect = document.getElementById("add-list-select");
  var addSheetClose = document.getElementById("add-sheet-close");
  var detailSheet = document.getElementById("detail-sheet");
  var detailBody = document.getElementById("detail-body");
  var detailClose = document.getElementById("detail-close");
  var searchInput = document.getElementById("search-input");
  var searchResults = document.getElementById("search-results");
  var searchEmpty = document.getElementById("search-empty");
  var searchTagChips = document.getElementById("search-tag-chips");
  var searchTagFilters = document.getElementById("search-tag-filters");
  var settingsStatus = document.getElementById("settings-status");
  var versionText = document.getElementById("version-text");
  var toastContainer = document.getElementById("toast-container");
  var bottomNav = document.getElementById("bottom-nav");
  var undoBtn = document.getElementById("undo-btn");
  var redoBtn = document.getElementById("redo-btn");

  // ====================================================================
  // Accessibility: keyboard & focus management
  // ====================================================================

  // Escape key closes any open sheet or context menu
  document.addEventListener("keydown", function (e) {
    // Undo/redo: Ctrl+Z / Ctrl+Shift+Z (or Cmd on Mac)
    if ((e.ctrlKey || e.metaKey) && e.key === "z") {
      e.preventDefault();
      if (e.shiftKey) {
        onRedo();
      } else {
        onUndo();
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "y") {
      e.preventDefault();
      onRedo();
      return;
    }
    if (e.key !== "Escape") return;
    // Context menu takes priority (highest z-index)
    if (activeContextMenu) {
      closeContextMenu();
      e.preventDefault();
      return;
    }
    // Cancel move mode
    if (moveMode) {
      exitMoveMode();
      e.preventDefault();
      return;
    }
    var sheets = [detailSheet, addSheet, listSheet, sortSheet];
    for (var i = 0; i < sheets.length; i++) {
      if (sheets[i] && !sheets[i].classList.contains("hidden")) {
        if (sheets[i] === detailSheet) closeDetailSheet();
        else if (sheets[i] === addSheet) closeAddSheet();
        else if (sheets[i] === listSheet) closeListSheet();
        else if (sheets[i] === sortSheet) closeSortSheet();
        e.preventDefault();
        return;
      }
    }
  });

  // Focus trap: keep Tab cycling within open sheet
  function trapFocus(sheet) {
    if (!sheet) return;
    var focusable = sheet.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    sheet._focusTrapHandler = function (e) {
      if (e.key !== "Tab") return;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    sheet.addEventListener("keydown", sheet._focusTrapHandler);
    first.focus();
  }

  function releaseFocusTrap(sheet) {
    if (!sheet || !sheet._focusTrapHandler) return;
    sheet.removeEventListener("keydown", sheet._focusTrapHandler);
    sheet._focusTrapHandler = null;
  }

  // ====================================================================
  // Sheet close animation helper
  // ====================================================================

  function animateSheetClose(sheet, afterClose) {
    if (!sheet) return;
    releaseFocusTrap(sheet);
    var reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reducedMotion) {
      sheet.classList.add("hidden");
      if (afterClose) afterClose();
      return;
    }
    sheet.classList.add("closing");
    setTimeout(function () {
      sheet.classList.remove("closing");
      sheet.classList.add("hidden");
      if (afterClose) afterClose();
    }, 200);
  }

  // ====================================================================
  // API helpers
  // ====================================================================

  function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY) || "";
  }

  function setAuthToken(token) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
  }

  function authHeaders(extra) {
    var h = Object.assign({}, extra || {});
    var token = getAuthToken();
    if (token) h["Authorization"] = "Bearer " + token;
    return h;
  }

  async function api(path, opts) {
    if (!opts) opts = {};
    opts.headers = authHeaders(opts.headers);
    var resp = await fetch(API + path, opts);
    if (resp.status === 401) {
      showLoginScreen();
      var err401 = new Error("Authentication required");
      err401.status = 401;
      err401.body = {};
      throw err401;
    }
    if (!resp.ok) {
      var body = await resp.json().catch(function () {
        return {};
      });
      var err = new Error(body.error || resp.statusText);
      err.status = resp.status;
      err.body = body;
      throw err;
    }
    return resp.json();
  }

  // ====================================================================
  // Login screen
  // ====================================================================

  var loginScreen = document.getElementById("login-screen");
  var loginPinInput = document.getElementById("login-pin-input");
  var loginBtn = document.getElementById("login-btn");
  var loginError = document.getElementById("login-error");
  var appContainer = document.getElementById("app-container");

  function showLoginScreen() {
    if (loginScreen) loginScreen.classList.remove("hidden");
    if (appContainer) appContainer.classList.add("hidden");
    if (loginPinInput) {
      loginPinInput.value = "";
      loginPinInput.focus();
    }
    if (loginError) loginError.textContent = "";
    stopPolling();
    disconnectWebSocket();
  }

  function hideLoginScreen() {
    if (loginScreen) loginScreen.classList.add("hidden");
    if (appContainer) appContainer.classList.remove("hidden");
  }

  if (loginBtn) {
    loginBtn.addEventListener("click", async function () {
      var pin = loginPinInput ? loginPinInput.value.trim() : "";
      if (!pin || pin.length < 4) return;
      if (loginError) loginError.textContent = "";
      loginBtn.disabled = true;
      loginBtn.textContent = "Connecting...";
      try {
        var resp = await fetch(API + "/auth", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pin: pin }),
        });
        if (resp.ok) {
          var data = await resp.json();
          setAuthToken(data.token);
          hideLoginScreen();
          init();
        } else {
          var err = await resp.json().catch(function () {
            return {};
          });
          if (loginError) loginError.textContent = err.error || "Invalid PIN";
        }
      } catch (e) {
        if (loginError)
          loginError.textContent =
            "Connection failed — try refreshing the page";
        // Network error during PIN — likely a stale service worker blocking
        // connections after cert change. Unregister SW so direct browser
        // requests can show the cert acceptance dialog.
        if (navigator.serviceWorker) {
          try {
            var swRegs = await navigator.serviceWorker.getRegistrations();
            for (var k = 0; k < swRegs.length; k++) {
              await swRegs[k].unregister();
            }
            var cn = await caches.keys();
            for (var m = 0; m < cn.length; m++) {
              await caches.delete(cn[m]);
            }
          } catch (swE) {
            /* best effort */
          }
        }
      }
      loginBtn.disabled = false;
      loginBtn.textContent = "Connect";
    });
  }

  if (loginPinInput) {
    loginPinInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        if (loginBtn) loginBtn.click();
      }
    });
    // Auto-submit when 6 digits entered
    loginPinInput.addEventListener("input", function () {
      if (loginPinInput.value.length === 6 && loginBtn) loginBtn.click();
    });
  }

  function getItemUpdatedAt(itemId) {
    for (var i = 0; i < cachedItems.length; i++) {
      if (cachedItems[i].id === itemId) return cachedItems[i].updated_at;
    }
    if (cachedBoardData && cachedBoardData.columns) {
      var cols = Object.keys(cachedBoardData.columns);
      for (var c = 0; c < cols.length; c++) {
        var items = cachedBoardData.columns[cols[c]];
        for (var j = 0; j < items.length; j++) {
          if (items[j].id === itemId) return items[j].updated_at;
        }
      }
    }
    return undefined;
  }

  function getListUpdatedAt(listId) {
    for (var i = 0; i < cachedLists.length; i++) {
      if (cachedLists[i].id === listId) return cachedLists[i].updated_at;
    }
    if (cachedBoardData && cachedBoardData.id === listId)
      return cachedBoardData.updated_at;
    return undefined;
  }

  function updateCachedItemTimestamp(itemId, newUpdatedAt) {
    for (var i = 0; i < cachedItems.length; i++) {
      if (cachedItems[i].id === itemId) {
        cachedItems[i].updated_at = newUpdatedAt;
        return;
      }
    }
  }

  // ====================================================================
  // IndexedDB cache (offline data persistence)
  // ====================================================================

  var IDB_NAME = "pytodo_cache";
  var IDB_VERSION = 1;
  var idb = null;

  function openIDB() {
    return new Promise(function (resolve) {
      if (idb) {
        resolve(idb);
        return;
      }
      var req = indexedDB.open(IDB_NAME, IDB_VERSION);
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        if (!db.objectStoreNames.contains("lists")) {
          db.createObjectStore("lists", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("listItems")) {
          db.createObjectStore("listItems", { keyPath: "listId" });
        }
      };
      req.onsuccess = function (e) {
        idb = e.target.result;
        resolve(idb);
      };
      req.onerror = function () {
        resolve(null);
      }; // Graceful degradation
    });
  }

  async function cacheListsData(lists) {
    var db = await openIDB();
    if (!db) return;
    try {
      var tx = db.transaction("lists", "readwrite");
      var store = tx.objectStore("lists");
      store.clear();
      lists.forEach(function (lst) {
        store.put(lst);
      });
    } catch (e) {
      /* best-effort */
    }
  }

  async function getCachedLists() {
    var db = await openIDB();
    if (!db) return null;
    return new Promise(function (resolve) {
      try {
        var tx = db.transaction("lists", "readonly");
        var req = tx.objectStore("lists").getAll();
        req.onsuccess = function () {
          resolve(req.result);
        };
        req.onerror = function () {
          resolve(null);
        };
      } catch (e) {
        resolve(null);
      }
    });
  }

  async function cacheListItems(listId, items) {
    var db = await openIDB();
    if (!db) return;
    try {
      var tx = db.transaction("listItems", "readwrite");
      tx.objectStore("listItems").put({ listId: listId, items: items });
    } catch (e) {
      /* best-effort */
    }
  }

  async function getCachedListItems(listId) {
    var db = await openIDB();
    if (!db) return null;
    return new Promise(function (resolve) {
      try {
        var tx = db.transaction("listItems", "readonly");
        var req = tx.objectStore("listItems").get(listId);
        req.onsuccess = function () {
          resolve(req.result ? req.result.items : null);
        };
        req.onerror = function () {
          resolve(null);
        };
      } catch (e) {
        resolve(null);
      }
    });
  }

  // ====================================================================
  // Offline queue
  // ====================================================================

  function getOfflineQueue() {
    try {
      return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  // Stores the queue and draws the list again, since what is shown
  // follows from it. While the queue is being sent the list is left as
  // it is (quiet): it is reloaded when the run ends.
  function saveOfflineQueue(queue, quiet) {
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
    updatePendingBadge();
    updateConnectionIndicator();
    if (!quiet) showQueuedChanges();
  }

  // Draws the current list from what the server last sent and the
  // queued changes.
  function showQueuedChanges() {
    var queue = getOfflineQueue();
    var columns = serverBoardData ? serverBoardData.board_columns : [];
    cachedItems = QueueRules.withQueuedChanges(serverItems, queue, columns);
    cachedBoardData = QueueRules.boardWithQueuedChanges(serverBoardData, queue);
    if (viewMode !== "board") {
      renderItems(cachedItems);
    } else if (cachedBoardData && cachedBoardData.columns) {
      renderBoard(cachedBoardData);
    }
    if (viewMode === "calendar") refreshCalendar();
  }

  // The rules of the queue are in offline-queue.js, loaded before this
  // script.
  var QueueRules = window.PytodoOfflineQueue;

  function enqueueOfflineEdit(path, opts) {
    var queue = getOfflineQueue();
    var change = {
      path: path,
      opts: opts,
      timestamp: QueueRules.newTimestamp(queue, Date.now()),
    };
    saveOfflineQueue(QueueRules.withChange(queue, change));
  }

  function removeFromOfflineQueue(index) {
    var queue = getOfflineQueue();
    queue.splice(index, 1);
    saveOfflineQueue(queue);
  }

  function removeQueuedChange(timestamp, quiet) {
    saveOfflineQueue(
      getOfflineQueue().filter(function (entry) {
        return entry.timestamp !== timestamp;
      }),
      quiet,
    );
  }

  // Another open copy of the page stored the queue: a second tab, or
  // the page of a tab closed a moment ago, which the browser keeps for a
  // few seconds. The browser tells every copy but the one that wrote.
  // The count, the connection dot and the list follow the stored queue.
  // The undo steps kept here hold the queue as it was before that write,
  // and putting one back would undo the other copy's work, or queue
  // again a change it has already sent; they are dropped.
  window.addEventListener("storage", function (event) {
    // A cleared storage has no key.
    if (event.key !== null && event.key !== OFFLINE_QUEUE_KEY) return;
    clearOfflineUndo();
    updatePendingBadge();
    updateConnectionIndicator();
    // A run that is sending the queue reloads the list when it ends.
    if (replayRunning) return;
    // A queue that got shorter may have been sent, and the server then
    // has newer data than this copy: the list is read again, and drawn
    // from the answer or, without the server, from the stored one.
    // Otherwise what the server last sent stands, and is drawn now.
    if (storedQueueLength(event.newValue) < storedQueueLength(event.oldValue)) {
      refreshCurrentList();
    } else {
      showQueuedChanges();
    }
  });

  function storedQueueLength(text) {
    try {
      return JSON.parse(text || "[]").length || 0;
    } catch (e) {
      return 0;
    }
  }

  // Sends a change to the server, or queues it when the server cannot
  // be reached. Resolves to what became of it:
  //   "sent"      applied by the server
  //   "queued"    kept, to be sent when the server answers again
  //   "conflict"  the item was changed elsewhere; the list is reloaded
  //   "refused"   the server will not accept it; its reason is shown
  // step, when given, receives the queue before and after a change that
  // is queued: what the Undo of a notice about that change takes back.
  async function sendOrQueue(path, opts, step) {
    if (isOnline) {
      try {
        await api(path, opts);
        return "sent";
      } catch (e) {
        var outcome = QueueRules.replyOutcome(e.status);
        if (outcome === "conflict") {
          showToast("Updated elsewhere \u2014 refreshing");
          await refreshCurrentList();
          return "conflict";
        }
        if (outcome === "refused") {
          showToast(e.message || "The change could not be saved");
          await refreshCurrentList();
          return "refused";
        }
      }
    }
    var before = getOfflineQueue();
    enqueueOfflineEdit(path, opts);
    var after = getOfflineQueue();
    pushOfflineUndo(before, after);
    if (step) {
      step.before = before;
      step.after = after;
    }
    return "queued";
  }

  var replayRunning = false;

  // Sends the queued changes. One run at a time: the browser coming
  // back online and the WebSocket reopening both ask for it.
  async function replayOfflineQueue() {
    if (replayRunning || getOfflineQueue().length === 0) return;
    replayRunning = true;
    try {
      await sendQueuedChanges();
    } finally {
      replayRunning = false;
    }
  }

  async function sendQueuedChanges() {
    var count = getOfflineQueue().length;
    showToast(
      "Syncing " + count + " offline change" + (count > 1 ? "s" : "") + "...",
    );
    var tried = {}; // timestamps of the changes sent in this run
    var heldItems = {}; // items with a change that stays queued
    var latest = {}; // item id → updated_at from the replies of this run
    var conflicts = 0;
    var refused = 0;
    for (;;) {
      // Read the stored queue each time round: a change can be queued
      // or removed while the run waits for the server.
      var entry = QueueRules.nextToSend(getOfflineQueue(), tried, heldItems);
      if (!entry) break;
      tried[entry.timestamp] = true;
      var itemId = QueueRules.itemIdOf(entry.path);
      var opts = entry.opts || {};
      if (itemId && latest[itemId] !== undefined) {
        opts = QueueRules.withUpdatedAt(opts, latest[itemId]);
      }
      opts = Object.assign({}, opts, { headers: authHeaders(opts.headers) });
      var resp;
      try {
        resp = await fetch(API + entry.path, opts);
      } catch (e) {
        // No answer: the rest would fail in the same way.
        break;
      }
      var outcome = QueueRules.replyOutcome(resp.status);
      if (outcome === "kept") {
        if (itemId) heldItems[itemId] = true;
        continue;
      }
      // Removed as soon as the server has answered, so that a page
      // closed during the run does not send the change a second time.
      removeQueuedChange(entry.timestamp, true);
      if (outcome === "conflict") conflicts++;
      if (outcome === "refused") refused++;
      if (outcome === "sent" && itemId) {
        try {
          var data = await resp.json();
          if (data && data.updated_at) latest[itemId] = data.updated_at;
        } catch (e) {
          /* no parseable body */
        }
      }
    }
    var remaining = getOfflineQueue().length;
    if (conflicts > 0) {
      showToast(
        conflicts +
          " change" +
          (conflicts > 1 ? "s" : "") +
          " conflicted (data updated elsewhere)",
      );
    }
    if (refused > 0) {
      showToast(
        refused +
          " change" +
          (refused > 1 ? "s" : "") +
          " could not be applied",
      );
    }
    if (remaining > 0) {
      showToast(
        remaining +
          " change" +
          (remaining > 1 ? "s" : "") +
          " still pending",
      );
    } else if (conflicts === 0 && refused === 0) {
      showToast("All changes synced");
    }
    await refreshCurrentList();
  }

  // Pending changes badge on nav
  function updatePendingBadge() {
    var badge = document.getElementById("nav-pending-badge");
    var queue = getOfflineQueue();
    if (badge) {
      badge.textContent = String(queue.length);
      badge.classList.toggle("hidden", queue.length === 0);
    }
  }

  function updateOnlineStatus(online) {
    isOnline = online;
    if (offlineBanner) {
      offlineBanner.classList.toggle("hidden", online);
    }
    if (online) {
      // Transitioning to online — clear offline undo stacks
      // (server-side undo takes over after queue replay)
      clearOfflineUndo();
    }
    updateConnectionIndicator();
    updatePendingBadge();
  }

  function updateConnectionIndicator() {
    if (!connectionDot) return;
    var queue = getOfflineQueue();
    var hasPending = queue.length > 0;
    connectionDot.classList.remove("online", "pending", "offline");
    if (!isOnline) {
      connectionDot.classList.add("offline");
      connectionDot.title = "Offline";
    } else if (hasPending) {
      connectionDot.classList.add("pending");
      connectionDot.title =
        queue.length + " change" + (queue.length > 1 ? "s" : "") + " pending";
    } else {
      connectionDot.classList.add("online");
      connectionDot.title = "Connected";
    }
    updateLastSyncedText();
  }

  function markSynced() {
    lastSyncTime = Date.now();
    updateConnectionIndicator();
  }

  function updateLastSyncedText() {
    if (!lastSyncedEl) return;
    if (!isOnline) {
      lastSyncedEl.textContent = "Offline";
      return;
    }
    if (lastSyncTime === 0) {
      lastSyncedEl.textContent = "";
      return;
    }
    var ago = Math.round((Date.now() - lastSyncTime) / 1000);
    if (ago < 5) {
      lastSyncedEl.textContent = "Just now";
    } else if (ago < 60) {
      lastSyncedEl.textContent = ago + "s ago";
    } else {
      var mins = Math.round(ago / 60);
      lastSyncedEl.textContent = mins + "m ago";
    }
  }

  window.addEventListener("online", function () {
    updateOnlineStatus(true);
    connectWebSocket();
    replayOfflineQueue();
    refreshCurrentList();
    startPolling();
  });

  window.addEventListener("offline", function () {
    updateOnlineStatus(false);
    stopPolling();
    disconnectWebSocket();
  });

  // ====================================================================
  // Hash routing
  // ====================================================================

  function getRoute() {
    var hash = location.hash || "#/";
    if (hash === "#" || hash === "#/") return { view: "home", id: null };
    if (hash.startsWith("#/search")) return { view: "search", id: null };
    if (hash.startsWith("#/settings")) return { view: "settings", id: null };
    if (hash.startsWith("#/item/"))
      return { view: "item", id: hash.substring(7) };
    return { view: "home", id: null };
  }

  function navigateTo(view) {
    if (view === "home") location.hash = "#/";
    else location.hash = "#/" + view;
  }

  var prevView = "home";
  var viewOrder = ["home", "search", "settings"];

  function onRouteChange() {
    var route = getRoute();
    // Update views
    document.querySelectorAll("#main > .view").forEach(function (el) {
      el.classList.remove("active", "slide-in-left", "slide-in-right");
    });
    var activeView;
    if (route.view === "item") {
      openDetailSheet(route.id);
      activeView = "home";
    } else {
      activeView = route.view;
    }
    var viewEl = document.getElementById("view-" + activeView);
    if (viewEl) {
      viewEl.classList.add("active");
      // Slide direction based on nav order
      if (activeView !== prevView) {
        var fromIdx = viewOrder.indexOf(prevView);
        var toIdx = viewOrder.indexOf(activeView);
        viewEl.classList.add(
          toIdx > fromIdx ? "slide-in-right" : "slide-in-left",
        );
      }
      prevView = activeView;
    }

    // Update nav buttons
    bottomNav.querySelectorAll(".nav-btn[data-view]").forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.view === activeView);
    });

    // Show view toggle only on home
    if (viewToggle) {
      viewToggle.classList.toggle("hidden", activeView !== "home");
    }

    // Update header title
    var titles = { home: "PyTodo-Qt", search: "Search", settings: "Settings" };
    if (headerTitle)
      headerTitle.textContent = titles[activeView] || "PyTodo-Qt";

    // Trigger view-specific actions
    if (activeView === "search") refreshSearch();
    if (activeView === "settings") refreshSettings();
  }

  window.addEventListener("hashchange", onRouteChange);

  // ====================================================================
  // View mode toggle (list <-> board)
  // ====================================================================

  function setViewMode(mode) {
    viewMode = mode;
    localStorage.setItem(VIEW_MODE_KEY, mode);

    var listView = document.getElementById("list-view");
    var boardView = document.getElementById("board-view");
    var calendarView = document.getElementById("calendar-view");
    if (listView) listView.classList.toggle("active", mode === "list");
    if (boardView) boardView.classList.toggle("active", mode === "board");
    if (calendarView)
      calendarView.classList.toggle("active", mode === "calendar");

    viewBtns.forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.view === mode);
    });

    if (mode === "board") {
      refreshBoard(true);
    } else if (mode === "calendar") {
      renderCalendar();
    } else {
      renderItems(cachedItems, true);
    }
  }

  viewBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setViewMode(btn.dataset.view);
    });
  });

  // Keyboard shortcut for desktop web users
  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey && e.shiftKey && e.key === "B") {
      e.preventDefault();
      var modes = ["list", "board", "calendar"];
      var nextIdx = (modes.indexOf(viewMode) + 1) % modes.length;
      setViewMode(modes[nextIdx]);
    }
  });

  // ====================================================================
  // Three-tier sorting (matches desktop _sort_fragment)
  // ====================================================================

  var currentSortTiers = [
    { dimension: "completion", reverse: false },
    { dimension: "due_date", reverse: false },
    { dimension: "priority", reverse: false },
  ];
  var sortUpdatedAt = 0;

  // Fetch sort tiers from API (non-blocking, falls back to defaults)
  function fetchSortTiers() {
    fetch(API + "/sort", { headers: authHeaders() })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data && data.sort_tiers && data.sort_tiers.length === 3) {
          currentSortTiers = data.sort_tiers;
          if (data.updated_at != null) sortUpdatedAt = data.updated_at;
          updateSortButtonLabel();
        }
      })
      .catch(function () {
        /* keep defaults */
      });
  }

  function updateSortButtonLabel() {
    if (!sortBtn) return;
    var dim = currentSortTiers[0].dimension;
    var labels = {
      completion: "Completion",
      due_date: "Due Date",
      priority: "Priority",
    };
    var arrow = currentSortTiers[0].reverse ? "\u2193" : "\u2191";
    sortBtn.textContent = "Sort: " + (labels[dim] || dim) + " " + arrow;
  }

  /**
   * Compute a comparable sort-key array for an item, matching the desktop
   * _sort_fragment() function exactly.
   *
   * Each tier appends one or more values to the key array. The resulting
   * arrays are compared element-by-element in sortItems().
   */
  function sortKey(item, tiers) {
    var key = [];
    for (var i = 0; i < tiers.length; i++) {
      var dim = tiers[i].dimension;
      var rev = tiers[i].reverse;
      if (dim === "completion") {
        var val = item.complete ? 1 : 0;
        key.push(rev ? -val : val);
      } else if (dim === "due_date") {
        if (!item.due_date) {
          // No date — always sorts last (regardless of reverse)
          key.push(1, 0, 0);
        } else {
          // Date ordinal from ISO string (days since epoch for comparison)
          var d = new Date(item.due_date + "T00:00:00");
          var dateOrd = Math.floor(d.getTime() / 86400000);
          var timeSecs = -1;
          if (item.due_time) {
            var parts = item.due_time.split(":");
            timeSecs =
              parseInt(parts[0], 10) * 3600 +
              parseInt(parts[1], 10) * 60 +
              (parts[2] ? parseInt(parts[2], 10) : 0);
          }
          key.push(0, rev ? -dateOrd : dateOrd, rev ? -timeSecs : timeSecs);
        }
      } else if (dim === "priority") {
        var p = item.priority || 2;
        key.push(rev ? -p : p);
      }
    }
    return key;
  }

  function sortItems(items) {
    var tiers = currentSortTiers;
    var arr = items.slice();
    arr.sort(function (a, b) {
      var ka = sortKey(a, tiers);
      var kb = sortKey(b, tiers);
      for (var i = 0; i < ka.length; i++) {
        if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
      }
      // Tie-breaker: reminder text (case-insensitive)
      return a.reminder.toLowerCase().localeCompare(b.reminder.toLowerCase());
    });
    return arr;
  }

  fetchSortTiers();

  // ====================================================================
  // Sort configuration sheet
  // ====================================================================

  function syncSortSheetUI() {
    for (var i = 0; i < sortTierSelects.length; i++) {
      sortTierSelects[i].value = currentSortTiers[i].dimension;
    }
    for (var j = 0; j < sortDirBtns.length; j++) {
      sortDirBtns[j].textContent = currentSortTiers[j].reverse
        ? "\u2193"
        : "\u2191";
    }
  }

  function openSortSheet() {
    if (!sortSheet) return;
    syncSortSheetUI();
    sortSheet.classList.remove("hidden");
    trapFocus(sortSheet);
  }

  function closeSortSheet() {
    animateSheetClose(sortSheet);
  }

  function saveSortTiers() {
    var payload = { tiers: currentSortTiers, updated_at: sortUpdatedAt };
    fetch(API + "/sort", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    })
      .then(function (r) {
        if (r.status === 409) {
          return r.json().then(function (data) {
            if (data.current && data.current.sort_tiers) {
              currentSortTiers = data.current.sort_tiers;
              if (data.current.updated_at != null)
                sortUpdatedAt = data.current.updated_at;
              syncSortSheetUI();
            }
            showToast("Sort was changed elsewhere — refreshed");
          });
        }
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data && data.updated_at != null) sortUpdatedAt = data.updated_at;
      })
      .catch(function () {
        /* best-effort save */
      });
    updateSortButtonLabel();
    // Re-render current view with new sort order
    if (viewMode === "list") {
      renderItems(cachedItems, true);
    } else if (cachedBoardData) {
      renderBoard(cachedBoardData, true);
    }
  }

  if (sortBtn) {
    sortBtn.addEventListener("click", function () {
      openSortSheet();
    });
  }

  if (sortSheetClose) sortSheetClose.addEventListener("click", closeSortSheet);
  if (sortSheet) {
    var sortBackdrop = sortSheet.querySelector(".sheet-backdrop");
    if (sortBackdrop) sortBackdrop.addEventListener("click", closeSortSheet);
  }

  // Tier dimension change with auto-swap (no duplicates)
  for (var si = 0; si < sortTierSelects.length; si++) {
    sortTierSelects[si].addEventListener(
      "change",
      (function (changedIdx) {
        return function () {
          var newDim = sortTierSelects[changedIdx].value;
          // Find if another tier already has this dimension
          for (var k = 0; k < currentSortTiers.length; k++) {
            if (k !== changedIdx && currentSortTiers[k].dimension === newDim) {
              // Swap: give the other tier the dimension we're leaving
              currentSortTiers[k].dimension =
                currentSortTiers[changedIdx].dimension;
              break;
            }
          }
          currentSortTiers[changedIdx].dimension = newDim;
          syncSortSheetUI();
          saveSortTiers();
        };
      })(si),
    );
  }

  // Direction toggle buttons
  for (var di = 0; di < sortDirBtns.length; di++) {
    sortDirBtns[di].addEventListener(
      "click",
      (function (tierIdx) {
        return function () {
          currentSortTiers[tierIdx].reverse =
            !currentSortTiers[tierIdx].reverse;
          syncSortSheetUI();
          saveSortTiers();
        };
      })(di),
    );
  }

  // Board layout preset button
  if (boardLayoutBtn) {
    boardLayoutBtn.addEventListener("click", function () {
      openPresetPicker();
    });
  }

  // ====================================================================
  // Data fingerprinting (skip re-render when unchanged)
  // ====================================================================

  function fingerprint(data) {
    return JSON.stringify(data);
  }

  // ====================================================================
  // Haptic feedback
  // ====================================================================

  function haptic(duration) {
    if (navigator.vibrate) {
      try {
        navigator.vibrate(duration || 10);
      } catch (e) {
        /* best-effort */
      }
    }
  }

  // ====================================================================
  // Context menu (reusable bottom action sheet)
  // ====================================================================

  var activeContextMenu = null;

  /**
   * Show a context menu bottom sheet.
   * @param {string} title - Title shown at the top
   * @param {Array} actions - Array of action objects:
   *   { icon, label, onTap }                — simple action
   *   { icon, label, submenu: [...] }       — opens sub-menu
   *   { divider: true }                     — separator line
   *   { icon, label, checked: true/false }  — radio/check item
   *   { icon, label, danger: true, onTap }  — destructive action
   */
  function showContextMenu(title, actions) {
    closeContextMenu();
    haptic(10);

    var overlay = document.createElement("div");
    overlay.className = "context-menu";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", title);

    var backdrop = document.createElement("div");
    backdrop.className = "context-menu-backdrop";
    backdrop.addEventListener("click", function () {
      closeContextMenu();
    });
    overlay.appendChild(backdrop);

    var content = document.createElement("div");
    content.className = "context-menu-content";

    var titleEl = document.createElement("div");
    titleEl.className = "context-menu-title";
    titleEl.textContent = title;
    content.appendChild(titleEl);

    renderContextActions(content, actions);

    var cancelBtn = document.createElement("button");
    cancelBtn.className = "context-menu-cancel";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", function () {
      closeContextMenu();
    });
    content.appendChild(cancelBtn);

    overlay.appendChild(content);
    document.body.appendChild(overlay);
    activeContextMenu = overlay;

    // Focus trap
    trapFocus(overlay);
  }

  function renderContextActions(container, actions) {
    actions.forEach(function (action) {
      if (action.divider) {
        var div = document.createElement("div");
        div.className = "context-menu-divider";
        container.appendChild(div);
        return;
      }

      var btn = document.createElement("button");
      btn.className = "context-menu-action";
      if (action.danger) btn.classList.add("danger");

      if (action.icon) {
        var icon = document.createElement("span");
        icon.className = "ctx-icon";
        icon.textContent = action.icon;
        btn.appendChild(icon);
      }

      var label = document.createElement("span");
      label.className = "ctx-label";
      label.textContent = action.label;
      btn.appendChild(label);

      if (action.checked !== undefined) {
        var check = document.createElement("span");
        check.className = "ctx-check";
        check.textContent = action.checked ? "\u2713" : "";
        btn.appendChild(check);
      }

      if (action.submenu) {
        var arrow = document.createElement("span");
        arrow.className = "ctx-arrow";
        arrow.textContent = "\u203A";
        btn.appendChild(arrow);
        btn.addEventListener("click", function () {
          haptic(5);
          showContextMenu(action.label, action.submenu);
        });
      } else if (action.onTap) {
        btn.addEventListener("click", function () {
          haptic(10);
          closeContextMenu();
          action.onTap();
        });
      }

      container.appendChild(btn);
    });
  }

  function closeContextMenu() {
    if (!activeContextMenu) return;
    var menu = activeContextMenu;
    activeContextMenu = null;
    releaseFocusTrap(menu);

    var reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reducedMotion) {
      menu.remove();
      return;
    }
    menu.classList.add("closing");
    setTimeout(function () {
      menu.remove();
    }, 150);
  }

  // ====================================================================
  // A press in progress holds the redraw
  // ====================================================================

  // The list, the board and the calendar are drawn again when their
  // data changes, and a redraw replaces every row and card. One that
  // came while a row was pressed left the release with a new element:
  // the tap opened nothing, since a click needs its press and release
  // on the same element, a swipe or a drag lost what it was moving, and
  // the long-press timer of the old row, never cancelled, opened the
  // task menu.
  //
  // While a pointer is down in one of the views, a redraw that is not
  // forced waits, and is made when the press is over. A press that did
  // not move ends with a click, by mouse and by a tap; the redraw waits
  // for it, so that the click finds the element that was pressed. A
  // long press by touch sends none, and the wait for it is bounded.
  var pressHeld = false;
  var pressByMouse = false;
  var pressMoved = false;
  var pressStartX = 0;
  var pressStartY = 0;
  var pressEndTimer = null;
  var redrawWaiting = false;
  var PRESS_MOVE_THRESHOLD = 10;
  var PRESS_CLICK_WAIT_MS = 300;

  // Whether a redraw must wait for a press to end. One that must is
  // remembered, and made by endPress.
  function redrawHeld() {
    if (!pressHeld) return false;
    redrawWaiting = true;
    return true;
  }

  function endPress() {
    clearTimeout(pressEndTimer);
    pressEndTimer = null;
    if (!pressHeld) return;
    pressHeld = false;
    if (redrawWaiting) {
      redrawWaiting = false;
      showQueuedChanges();
    }
  }

  window.addEventListener(
    "pointerdown",
    function (e) {
      // The primary button, a finger or a pen; the release of another
      // button can go to the browser's own menu.
      if (e.button !== 0) return;
      if (!e.target || !e.target.closest) return;
      if (!e.target.closest("#list-view, #board-view, #calendar-view")) return;
      clearTimeout(pressEndTimer);
      pressEndTimer = null;
      pressHeld = true;
      pressByMouse = e.pointerType === "mouse";
      pressMoved = false;
      pressStartX = e.clientX;
      pressStartY = e.clientY;
    },
    true,
  );

  window.addEventListener(
    "pointermove",
    function (e) {
      if (!pressHeld || pressMoved) return;
      if (
        Math.abs(e.clientX - pressStartX) > PRESS_MOVE_THRESHOLD ||
        Math.abs(e.clientY - pressStartY) > PRESS_MOVE_THRESHOLD
      ) {
        pressMoved = true;
      }
    },
    true,
  );

  window.addEventListener(
    "pointerup",
    function () {
      if (!pressHeld) return;
      // After the handlers of the release itself; and, for a press that
      // did not move, after the click that follows it.
      clearTimeout(pressEndTimer);
      pressEndTimer = setTimeout(
        endPress,
        pressMoved ? 0 : PRESS_CLICK_WAIT_MS,
      );
    },
    true,
  );

  window.addEventListener(
    "click",
    function () {
      if (!pressEndTimer) return;
      // The click the press was waiting for: after its handlers.
      clearTimeout(pressEndTimer);
      pressEndTimer = setTimeout(endPress, 0);
    },
    true,
  );

  // A press the browser takes over (a scroll, its own menu) has no
  // release for the page; nor has one on a page that is put away.
  window.addEventListener("pointercancel", endPress, true);
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) endPress();
  });
  // The browser's menu takes the release of a mouse press that opens
  // it. A finger held down sends the same event, on a phone before the
  // long press here is due, and its press goes on: ending it there
  // would redraw the row a moment before its menu was to open.
  window.addEventListener(
    "contextmenu",
    function () {
      if (pressByMouse) endPress();
    },
    true,
  );

  // ====================================================================
  // Long-press detection
  // ====================================================================

  // The click that ends a long press. Releasing a mouse button sends a
  // click after the pointerup, and the browser gives it to whatever is
  // then under the pointer: the pressed element (Firefox), or the menu
  // the long press has just opened over it (Chrome, WebKit). It is
  // discarded wherever it lands, before any handler sees it. A long
  // press by touch sends no click, so the wait for one ends at the next
  // press, and a click that belongs to something else is not taken.
  var discardedClick = null;

  function discardNextClick() {
    stopDiscardingClick();
    discardedClick = function (e) {
      e.preventDefault();
      e.stopPropagation();
      stopDiscardingClick();
    };
    window.addEventListener("click", discardedClick, true);
    window.addEventListener("pointerdown", stopDiscardingClick, true);
  }

  function stopDiscardingClick() {
    if (!discardedClick) return;
    window.removeEventListener("click", discardedClick, true);
    window.removeEventListener("pointerdown", stopDiscardingClick, true);
    discardedClick = null;
  }

  /**
   * Attach long-press detection to an element.
   * @param {Element} el - Target element
   * @param {Function} onLongPress - Called with the original event when long-press fires
   */
  function attachLongPress(el, onLongPress) {
    var timer = null;
    var startX = 0,
      startY = 0;
    var HOLD_MS = 500;
    var MOVE_THRESHOLD = 10;
    var fired = false;

    function onDown(e) {
      if (e.button && e.button !== 0) return; // Only primary button
      fired = false;
      var point = e.touches ? e.touches[0] : e;
      startX = point.clientX;
      startY = point.clientY;
      el.classList.add("long-press-active");
      timer = setTimeout(function () {
        timer = null;
        el.classList.remove("long-press-active");
        // Drawn again while it was pressed, by a redraw that does not
        // wait: the release went to the element that took its place,
        // and this one never heard of it.
        if (!el.isConnected) return;
        fired = true;
        discardNextClick();
        onLongPress(e);
      }, HOLD_MS);
    }

    function onMove(e) {
      if (!timer) return;
      var point = e.touches ? e.touches[0] : e;
      var dx = Math.abs(point.clientX - startX);
      var dy = Math.abs(point.clientY - startY);
      if (dx > MOVE_THRESHOLD || dy > MOVE_THRESHOLD) {
        cancel();
      }
    }

    function cancel() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      el.classList.remove("long-press-active");
    }

    function onUp(e) {
      cancel();
      // Keep the release from the handlers above (a swipe, a drag). The
      // click that follows a mouse release is not stopped by this; see
      // discardNextClick.
      if (fired) {
        e.preventDefault();
        e.stopPropagation();
      }
    }

    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", cancel);
    // Cancel on scroll (parent scroll can move without pointermove firing)
    el.addEventListener("touchmove", onMove, { passive: true });
  }

  // ====================================================================
  // Context menu actions for items
  // ====================================================================

  function buildItemContextActions(item) {
    var actions = [];

    // Edit (open detail)
    actions.push({
      icon: "\u270F\uFE0F",
      label: "Edit",
      onTap: function () {
        location.hash = "#/item/" + item.id;
      },
    });

    // Toggle complete
    actions.push({
      icon: item.complete ? "\u25CB" : "\u2713",
      label: item.complete ? "Mark Incomplete" : "Mark Complete",
      onTap: function () {
        onToggle(item.id);
      },
    });

    actions.push({ divider: true });

    // Set priority sub-menu
    var priorities = [
      { label: "High", value: 1, icon: "\u{1F534}" },
      { label: "Normal", value: 2, icon: "\u{1F535}" },
      { label: "Low", value: 3, icon: "\u26AA" },
    ];
    actions.push({
      icon: "\u{1F3F7}\uFE0F",
      label: "Priority",
      submenu: priorities.map(function (p) {
        return {
          icon: p.icon,
          label: p.label,
          checked: item.priority === p.value,
          onTap: function () {
            setPriority(item.id, p.value);
          },
        };
      }),
    });

    // Move to column sub-menu (if board data is available)
    if (
      cachedBoardData &&
      cachedBoardData.board_columns &&
      cachedBoardData.board_columns.length > 0
    ) {
      var columns = cachedBoardData.board_columns;
      actions.push({
        icon: "\u{1F4CB}",
        label: "Move to Column",
        submenu: columns.map(function (col) {
          return {
            icon:
              col === columns[0]
                ? "\u{1F4E5}"
                : col === columns[columns.length - 1]
                  ? "\u2705"
                  : "\u25AB",
            label: col,
            checked: item.board_column === col,
            onTap: function () {
              moveToColumn(item.id, col);
            },
          };
        }),
      });
    }

    // Recurrence submenu
    var recPresets = [
      { label: "Every 25 min", type: "minutely", interval: 25 },
      { label: "Every hour", type: "minutely", interval: 60 },
      { label: "Daily", type: "daily", interval: 1 },
      { label: "Weekly", type: "weekly", interval: 1 },
      { label: "Monthly", type: "monthly", interval: 1 },
      { label: "None", type: null, interval: 1 },
    ];
    actions.push({
      icon: "\u{1F504}",
      label: "Recurrence",
      submenu: recPresets.map(function (p) {
        return {
          icon: p.type === null ? "\u274C" : "\u{1F504}",
          label: p.label,
          checked:
            p.type === null
              ? !item.recurrence_type
              : item.recurrence_type === p.type &&
                item.recurrence_interval === p.interval,
          onTap: function () {
            setRecurrence(item.id, p.type, p.interval);
          },
        };
      }),
    });

    actions.push({ divider: true });

    // Delete
    actions.push({
      icon: "\u{1F5D1}\uFE0F",
      label: "Delete",
      danger: true,
      onTap: function () {
        var cardEl = document.querySelector('[data-id="' + item.id + '"]');
        onDelete(item.id, item.reminder, cardEl);
      },
    });

    return actions;
  }

  async function setPriority(itemId, priority) {
    var path = "/items/" + itemId;
    var fields = { priority: priority };
    var ua = getItemUpdatedAt(itemId);
    if (ua !== undefined) fields.updated_at = ua;
    var opts = {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    };
    var outcome = await sendOrQueue(path, opts);
    if (outcome === "sent") await refreshCurrentList();
  }

  async function setRecurrence(itemId, recType, recInterval) {
    var path = "/items/" + itemId;
    var fields = {
      recurrence_type: recType,
      recurrence_interval: recInterval || 1,
    };
    var ua = getItemUpdatedAt(itemId);
    if (ua !== undefined) fields.updated_at = ua;
    var opts = {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    };
    var outcome = await sendOrQueue(path, opts);
    if (outcome === "sent") {
      await refreshCurrentList();
      showToast(recType ? "Recurrence set" : "Recurrence removed");
    }
  }

  async function moveToColumn(itemId, column) {
    var path = "/items/" + itemId + "/move";
    var fields = { column: column };
    var ua = getItemUpdatedAt(itemId);
    if (ua !== undefined) fields.updated_at = ua;
    var opts = {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    };
    var outcome = await sendOrQueue(path, opts);
    if (outcome === "sent") {
      await refreshCurrentList();
      showToast("Moved to " + column);
    }
  }

  function openItemContextMenu(item) {
    var title =
      item.reminder.length > 40
        ? item.reminder.substring(0, 40) + "\u2026"
        : item.reminder;
    showContextMenu(title, buildItemContextActions(item));
  }

  // ====================================================================
  // Column management (context menu + actions)
  // ====================================================================

  function openColumnContextMenu(colName, colIdx, totalColumns, itemCount) {
    var isFirst = colIdx === 0;
    var isLast = colIdx === totalColumns - 1;
    var actions = [];

    // Rename (all columns)
    actions.push({
      icon: "\u270F\uFE0F",
      label: "Rename",
      onTap: function () {
        promptRenameColumn(colName);
      },
    });

    // WIP limit (middle columns only)
    if (!isFirst && !isLast) {
      actions.push({
        icon: "\u{1F522}",
        label: "Set WIP Limit",
        onTap: function () {
          promptWipLimit(colName);
        },
      });
    }

    // Delete (middle columns only, min 3 total)
    if (!isFirst && !isLast && totalColumns > 3) {
      actions.push({ divider: true });
      var firstCol = cachedBoardData
        ? cachedBoardData.board_columns[0]
        : "first column";
      actions.push({
        icon: "\u{1F5D1}\uFE0F",
        label: "Delete",
        danger: true,
        onTap: function () {
          var msg =
            itemCount > 0
              ? itemCount +
                " item" +
                (itemCount > 1 ? "s" : "") +
                ' will be moved to "' +
                firstCol +
                '"'
              : "This column is empty";
          showContextMenu('Delete "' + colName + '"?', [
            { label: msg },
            { divider: true },
            {
              icon: "\u{1F5D1}\uFE0F",
              label: "Delete Column",
              danger: true,
              onTap: function () {
                deleteColumn(colName);
              },
            },
          ]);
        },
      });
    }

    var icon = isFirst ? "\u{1F4E5}" : isLast ? "\u2705" : "\u{1F4CB}";
    showContextMenu(icon + " " + colName, actions);
  }

  function promptRenameColumn(oldName) {
    var newName = prompt("Rename column:", oldName);
    if (!newName || newName.trim() === "" || newName.trim() === oldName) return;
    newName = newName.trim().substring(0, 50);
    renameColumn(oldName, newName);
  }

  function promptWipLimit(colName) {
    var currentLimit =
      cachedBoardData && cachedBoardData.wip_limits
        ? cachedBoardData.wip_limits[colName] || 0
        : 0;
    var input = prompt(
      'WIP limit for "' + colName + '" (0 = no limit):',
      String(currentLimit),
    );
    if (input === null) return;
    var limit = parseInt(input, 10);
    if (isNaN(limit) || limit < 0 || limit > 99) {
      showToast("WIP limit must be 0\u201399");
      return;
    }
    setWipLimit(colName, limit);
  }

  async function renameColumn(oldName, newName) {
    var colFields = { action: "rename", old_name: oldName, new_name: newName };
    var colUa = getListUpdatedAt(currentListId);
    if (colUa !== undefined) colFields.updated_at = colUa;
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(colFields),
      });
      await refreshCurrentList();
      showToast('Renamed to "' + newName + '"');
    } catch (e) {
      if (e.status === 409) {
        showToast("Board was modified \u2014 refreshing");
        await refreshCurrentList();
      } else {
        showToast("Rename failed: " + e.message);
      }
    }
  }

  async function setWipLimit(colName, limit) {
    var wipFields = { action: "set_wip_limit", name: colName, limit: limit };
    var wipUa = getListUpdatedAt(currentListId);
    if (wipUa !== undefined) wipFields.updated_at = wipUa;
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wipFields),
      });
      await refreshCurrentList();
      showToast(limit > 0 ? "WIP limit set to " + limit : "WIP limit removed");
    } catch (e) {
      if (e.status === 409) {
        showToast("Board was modified \u2014 refreshing");
        await refreshCurrentList();
      } else {
        showToast("Failed: " + e.message);
      }
    }
  }

  async function deleteColumn(colName) {
    var delColFields = { action: "remove", name: colName };
    var delColUa = getListUpdatedAt(currentListId);
    if (delColUa !== undefined) delColFields.updated_at = delColUa;
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(delColFields),
      });
      await refreshCurrentList();
      showToast('Column "' + colName + '" deleted');
    } catch (e) {
      if (e.status === 409) {
        showToast("Board was modified \u2014 refreshing");
        await refreshCurrentList();
      } else {
        showToast("Delete failed: " + e.message);
      }
    }
  }

  // ====================================================================
  // Layout preset picker
  // ====================================================================

  var cachedPresets = null;

  async function openPresetPicker() {
    if (!cachedPresets) {
      try {
        var data = await api("/presets");
        cachedPresets = data.presets;
      } catch (e) {
        showToast("Failed to load presets");
        return;
      }
    }

    var currentCols = cachedBoardData ? cachedBoardData.board_columns : [];
    var actions = cachedPresets.map(function (preset) {
      var isActive =
        JSON.stringify(currentCols) === JSON.stringify(preset.columns);
      return {
        icon: isActive ? "\u2713" : "\u25AB",
        label: preset.name,
        checked: isActive,
        onTap: function () {
          applyPreset(preset.columns, preset.name);
        },
      };
    });

    showContextMenu("Board Layout", actions);
  }

  async function applyPreset(columns, presetName) {
    var presetFields = { columns: columns };
    var presetUa = getListUpdatedAt(currentListId);
    if (presetUa !== undefined) presetFields.updated_at = presetUa;
    try {
      var result = await api("/lists/" + currentListId + "/apply-preset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(presetFields),
      });
      await refreshCurrentList();
      var msg = 'Applied "' + presetName + '"';
      if (result.remapped > 0) {
        msg +=
          " (" +
          result.remapped +
          " item" +
          (result.remapped > 1 ? "s" : "") +
          " remapped)";
      }
      showToast(msg);
    } catch (e) {
      if (e.status === 409) {
        showToast("Board was modified \u2014 refreshing");
        await refreshCurrentList();
      } else {
        showToast("Failed: " + e.message);
      }
    }
  }

  // ====================================================================
  // Pick-up-and-place move mode (board cards)
  // ====================================================================

  var moveMode = null; // { itemId, itemReminder, sourceColumn }

  function enterMoveMode(itemId, itemReminder, sourceColumn) {
    if (moveMode) exitMoveMode();
    moveMode = {
      itemId: itemId,
      itemReminder: itemReminder,
      sourceColumn: sourceColumn,
    };
    haptic(15);
    renderMoveUI();
  }

  function exitMoveMode() {
    moveMode = null;
    // Remove banner
    var banner = document.querySelector(".move-banner");
    if (banner) banner.remove();
    // Remove drop zones and held state
    document.querySelectorAll(".board-drop-zone").forEach(function (z) {
      z.remove();
    });
    document.querySelectorAll(".board-card.held").forEach(function (c) {
      c.classList.remove("held");
    });
    // Remove sort indicators
    document.querySelectorAll(".board-sort-indicator").forEach(function (s) {
      s.remove();
    });
  }

  function renderMoveUI() {
    if (!moveMode || !boardContainer) return;

    // Mark held card
    var heldCard = boardContainer.querySelector(
      '[data-id="' + moveMode.itemId + '"]',
    );
    if (heldCard) heldCard.classList.add("held");

    // Add move banner above board
    var existing = document.querySelector(".move-banner");
    if (existing) existing.remove();
    var banner = document.createElement("div");
    banner.className = "move-banner";
    banner.setAttribute("aria-live", "polite");
    var bannerText = document.createElement("span");
    bannerText.className = "move-banner-text";
    var truncated =
      moveMode.itemReminder.length > 30
        ? moveMode.itemReminder.substring(0, 30) + "\u2026"
        : moveMode.itemReminder;
    bannerText.textContent = "Moving: " + truncated;
    banner.appendChild(bannerText);
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "move-banner-cancel";
    cancelBtn.textContent = "\u2715 Cancel";
    cancelBtn.addEventListener("click", function () {
      exitMoveMode();
    });
    banner.appendChild(cancelBtn);
    boardContainer.parentElement.insertBefore(banner, boardContainer);

    // Add drop zones to each column
    var columns = boardContainer.querySelectorAll(".board-column");
    var boardColumns = cachedBoardData ? cachedBoardData.board_columns : [];
    columns.forEach(function (col, idx) {
      var colName = boardColumns[idx];
      if (!colName) return;
      var isLast = idx === boardColumns.length - 1;
      var itemsDiv = col.querySelector(".board-column-items");
      if (!itemsDiv) return;

      var zone = document.createElement("div");
      zone.className = "board-drop-zone";
      if (isLast) zone.classList.add("completion-zone");
      zone.setAttribute("role", "button");
      zone.setAttribute("aria-label", "Drop in " + colName);
      zone.textContent = isLast ? "Drop to complete \u2713" : "Drop here";

      zone.addEventListener("click", function () {
        haptic(10);
        executeDrop(colName);
      });

      // Insert sort position indicator
      var colItems =
        cachedBoardData && cachedBoardData.columns
          ? cachedBoardData.columns[colName] || []
          : [];
      var sortPos = computeSortPosition(moveMode.itemId, colItems);
      var cards = itemsDiv.querySelectorAll(".board-card");

      if (sortPos >= cards.length) {
        itemsDiv.appendChild(createSortIndicator());
        itemsDiv.appendChild(zone);
      } else {
        itemsDiv.insertBefore(zone, cards[sortPos]);
        itemsDiv.insertBefore(createSortIndicator(), zone);
      }
    });
  }

  function createSortIndicator() {
    var indicator = document.createElement("div");
    indicator.className = "board-sort-indicator";
    return indicator;
  }

  function computeSortPosition(movingItemId, colItems) {
    // Find where the moving item would land in this column's sorted order
    // by comparing sort keys
    var movingItem = null;
    cachedItems.forEach(function (item) {
      if (item.id === movingItemId) movingItem = item;
    });
    if (!movingItem) return colItems.length;

    var tiers = currentSortTiers;
    var movingKey = sortKey(movingItem, tiers);
    var movingReminder = movingItem.reminder.toLowerCase();

    for (var i = 0; i < colItems.length; i++) {
      if (colItems[i].id === movingItemId) continue;
      var otherKey = sortKey(colItems[i], tiers);
      var cmp = 0;
      for (var k = 0; k < movingKey.length; k++) {
        if (movingKey[k] !== otherKey[k]) {
          cmp = movingKey[k] < otherKey[k] ? -1 : 1;
          break;
        }
      }
      if (cmp === 0) {
        cmp = movingReminder.localeCompare(colItems[i].reminder.toLowerCase());
      }
      if (cmp < 0) return i;
    }
    return colItems.length;
  }

  async function executeDrop(targetColumn) {
    if (!moveMode) return;
    var itemId = moveMode.itemId;
    var sourceColumn = moveMode.sourceColumn;
    var boardColumns = cachedBoardData ? cachedBoardData.board_columns : [];
    var isCompletionCol =
      boardColumns.length > 0 &&
      targetColumn === boardColumns[boardColumns.length - 1];
    var wasInCompletionCol =
      boardColumns.length > 0 &&
      sourceColumn === boardColumns[boardColumns.length - 1];
    exitMoveMode();

    var dropFields = { column: targetColumn };
    var dropUa = getItemUpdatedAt(itemId);
    if (dropUa !== undefined) dropFields.updated_at = dropUa;
    try {
      await api("/items/" + itemId + "/move", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dropFields),
      });
      await refreshCurrentList();
      var msg = 'Moved to "' + targetColumn + '"';
      if (isCompletionCol && !wasInCompletionCol) {
        msg += " (completed)";
      } else if (!isCompletionCol && wasInCompletionCol) {
        msg += " (marked incomplete)";
      }
      showToast(msg);
    } catch (e) {
      showToast("Move failed: " + e.message);
    }
  }

  // ====================================================================
  // Direct drag-and-drop (tablet/desktop)
  // ====================================================================

  function attachCardDrag(gripEl, card, item) {
    var dragging = false;
    var ghostEl = null;
    var startX = 0,
      startY = 0;
    var scrollInterval = null;

    gripEl.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      startX = e.clientX;
      startY = e.clientY;
      dragging = false;

      function onPointerMove(ev) {
        var dx = Math.abs(ev.clientX - startX);
        var dy = Math.abs(ev.clientY - startY);
        if (!dragging && (dx > 5 || dy > 5)) {
          dragging = true;
          startDirectDrag(card, item, ev);
        }
        if (dragging) {
          updateDragPosition(ev);
        }
      }

      function onPointerUp(ev) {
        document.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerup", onPointerUp);
        if (dragging) {
          endDirectDrag(ev);
          dragging = false;
        } else {
          // Was a tap, not a drag — enter pick-up-and-place mode
          enterMoveMode(item.id, item.reminder, item.board_column);
        }
      }

      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    });

    function startDirectDrag(cardEl, dragItem, ev) {
      cardEl.classList.add("dragging");
      haptic(10);

      // Create ghost
      ghostEl = cardEl.cloneNode(true);
      ghostEl.classList.remove("dragging");
      ghostEl.style.position = "fixed";
      ghostEl.style.width = cardEl.offsetWidth + "px";
      ghostEl.style.pointerEvents = "none";
      ghostEl.style.zIndex = "500";
      ghostEl.style.opacity = "0.9";
      ghostEl.style.transform = "rotate(2deg) scale(1.05)";
      ghostEl.style.boxShadow = "0 8px 24px rgba(0,0,0,0.2)";
      ghostEl.style.transition = "none";
      document.body.appendChild(ghostEl);
      updateGhostPosition(ev);

      // Show drop zones (reuse move mode rendering partially)
      if (!moveMode) {
        moveMode = {
          itemId: dragItem.id,
          itemReminder: dragItem.reminder,
          sourceColumn: dragItem.board_column,
        };
      }
      // Add drop zones to columns
      var columns = boardContainer.querySelectorAll(".board-column");
      var boardColumns = cachedBoardData ? cachedBoardData.board_columns : [];
      columns.forEach(function (col, idx) {
        var colName = boardColumns[idx];
        if (!colName) return;
        var isLast = idx === boardColumns.length - 1;
        var itemsDiv = col.querySelector(".board-column-items");
        if (!itemsDiv) return;

        var zone = document.createElement("div");
        zone.className = "board-drop-zone";
        zone.dataset.column = colName;
        if (isLast) zone.classList.add("completion-zone");
        zone.setAttribute("role", "button");
        zone.setAttribute("aria-label", "Drop in " + colName);
        zone.textContent = isLast ? "Drop to complete \u2713" : "Drop here";
        itemsDiv.appendChild(zone);
      });

      // Start edge auto-scroll
      scrollInterval = setInterval(function () {
        autoScrollBoard(ev);
      }, 16);
    }

    function updateGhostPosition(ev) {
      if (!ghostEl) return;
      ghostEl.style.left = ev.clientX - 40 + "px";
      ghostEl.style.top = ev.clientY - 20 + "px";
    }

    function updateDragPosition(ev) {
      updateGhostPosition(ev);
      // Highlight drop zone under cursor
      var zones = document.querySelectorAll(".board-drop-zone");
      zones.forEach(function (z) {
        var rect = z.getBoundingClientRect();
        var over =
          ev.clientX >= rect.left &&
          ev.clientX <= rect.right &&
          ev.clientY >= rect.top &&
          ev.clientY <= rect.bottom;
        z.classList.toggle("drag-over", over);
      });
      // Update auto-scroll reference
      if (scrollInterval) {
        autoScrollBoard._lastEv = ev;
      }
    }

    function endDirectDrag(ev) {
      if (scrollInterval) {
        clearInterval(scrollInterval);
        scrollInterval = null;
      }
      // Find drop zone under cursor
      var targetCol = null;
      var zones = document.querySelectorAll(".board-drop-zone");
      zones.forEach(function (z) {
        var rect = z.getBoundingClientRect();
        if (
          ev.clientX >= rect.left &&
          ev.clientX <= rect.right &&
          ev.clientY >= rect.top &&
          ev.clientY <= rect.bottom
        ) {
          targetCol = z.dataset.column;
        }
      });

      // Clean up
      if (ghostEl) {
        ghostEl.remove();
        ghostEl = null;
      }
      card.classList.remove("dragging");

      if (targetCol && moveMode) {
        executeDrop(targetCol);
      } else {
        exitMoveMode();
      }
    }
  }

  function autoScrollBoard(ev) {
    if (!boardContainer) return;
    var refEv = autoScrollBoard._lastEv || ev;
    var rect = boardContainer.getBoundingClientRect();
    var edgeSize = 100;
    var speed = 8;

    if (refEv.clientX < rect.left + edgeSize) {
      boardContainer.scrollLeft -= speed;
    } else if (refEv.clientX > rect.right - edgeSize) {
      boardContainer.scrollLeft += speed;
    }
  }
  autoScrollBoard._lastEv = null;

  // Escape key also cancels move mode (handled in existing Escape handler)

  // ====================================================================
  // Swipe gestures on item cards
  // ====================================================================

  function attachSwipe(el, itemId, itemReminder) {
    var startX = 0,
      startY = 0,
      currentX = 0;
    var pressed = false,
      swiping = false,
      locked = false;
    var threshold = 120; // Require deliberate swipe (was 80)

    // Create swipe action indicators
    var leftAction = document.createElement("div");
    leftAction.className = "swipe-action swipe-action-left";
    leftAction.textContent = "\u2713";
    var rightAction = document.createElement("div");
    rightAction.className = "swipe-action swipe-action-right";
    rightAction.textContent = "\u00D7";
    el.appendChild(leftAction);
    el.appendChild(rightAction);

    el.addEventListener("pointerdown", function (e) {
      // Swiping is a touch and pen gesture. A mouse has the checkbox and
      // the delete button on the row.
      if (e.pointerType === "mouse") return;
      if (e.target.closest(".item-checkbox, .item-actions, button")) return;
      pressed = true;
      startX = e.clientX;
      startY = e.clientY;
      currentX = 0;
      swiping = false;
      locked = false;
      el.style.transition = "none";
    });

    el.addEventListener("pointermove", function (e) {
      // A pointer that hovers moves over the task without being pressed.
      if (!pressed || locked) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;

      // Lock direction after 10px movement
      if (!swiping && Math.abs(dx) > 10) {
        if (Math.abs(dy) > Math.abs(dx)) {
          locked = true;
          return;
        }
        swiping = true;
        el.setPointerCapture(e.pointerId);
      }
      if (!swiping) return;

      e.preventDefault();
      currentX = dx;
      // Dampen the movement
      var dampened = currentX * 0.6;
      el.style.transform = "translateX(" + dampened + "px)";
      leftAction.classList.toggle("visible", dampened > threshold * 0.4);
      rightAction.classList.toggle("visible", dampened < -threshold * 0.4);
    });

    el.addEventListener("pointerup", function () {
      pressed = false;
      if (!swiping) return;
      swiping = false;
      el.style.transition = "transform 0.2s ease-out";
      el.style.transform = "";
      leftAction.classList.remove("visible");
      rightAction.classList.remove("visible");

      if (currentX * 0.6 > threshold) {
        haptic(15);
        onToggle(itemId);
      } else if (currentX * 0.6 < -threshold) {
        haptic(15);
        onDelete(itemId, itemReminder, el);
      }
    });

    el.addEventListener("pointercancel", function () {
      pressed = false;
      swiping = false;
      el.style.transition = "transform 0.2s ease-out";
      el.style.transform = "";
      leftAction.classList.remove("visible");
      rightAction.classList.remove("visible");
    });
  }

  // ====================================================================
  // Pull to refresh
  // ====================================================================

  var ptrIndicator = document.getElementById("ptr-indicator");

  (function initPullToRefresh() {
    var viewHome = document.getElementById("view-home");
    if (!viewHome) return;
    var startY = 0,
      pulling = false,
      refreshing = false;

    viewHome.addEventListener(
      "touchstart",
      function (e) {
        if (refreshing) return;
        // Only trigger when scrolled to top
        var scrollTop =
          document.getElementById("main").scrollTop || window.scrollY;
        if (scrollTop > 5) return;
        // Nor from inside a part of the page that scrolls by itself and
        // is not at its top: there a finger moving down scrolls it back.
        for (var el = e.target; el && el !== viewHome; el = el.parentElement) {
          if (el.scrollTop > 5) return;
        }
        startY = e.touches[0].clientY;
        pulling = true;
      },
      { passive: true },
    );

    viewHome.addEventListener(
      "touchmove",
      function (e) {
        if (!pulling || refreshing) return;
        var dy = e.touches[0].clientY - startY;
        if (dy > 60 && ptrIndicator) {
          ptrIndicator.classList.add("active");
        }
      },
      { passive: true },
    );

    viewHome.addEventListener("touchend", function () {
      if (!pulling) return;
      pulling = false;
      if (ptrIndicator && ptrIndicator.classList.contains("active")) {
        refreshing = true;
        haptic(10);
        refreshCurrentList().then(function () {
          ptrIndicator.classList.remove("active");
          refreshing = false;
          showToast("Refreshed");
        });
      }
    });
  })();

  // ====================================================================
  // Date formatting helpers
  // ====================================================================

  function formatDueDate(dateStr, timeStr, complete, timeEndStr, timeBlock) {
    if (!dateStr) return null;
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var due = new Date(dateStr + "T00:00:00");
    var diff = Math.floor((due - today) / 86400000);

    // Build time suffix: block label, range, or specific time
    var timeSuffix = "";
    if (timeBlock) {
      var label = timeBlock.replace(/_/g, " ");
      label = label.charAt(0).toUpperCase() + label.slice(1);
      timeSuffix = " (" + label + ")";
    } else if (timeStr && timeEndStr) {
      timeSuffix =
        " " + timeStr.substring(0, 5) + "-" + timeEndStr.substring(0, 5);
    } else if (timeStr) {
      timeSuffix = " " + timeStr.substring(0, 5);
    }

    if (complete) {
      return { text: dateStr.substring(5) + timeSuffix, cls: "" };
    }
    if (diff < 0) {
      return {
        text: "Overdue (" + Math.abs(diff) + "d)" + timeSuffix,
        cls: "overdue",
      };
    }
    if (diff === 0) {
      return { text: "Today" + timeSuffix, cls: "today" };
    }
    if (diff === 1) {
      return { text: "Tomorrow" + timeSuffix, cls: "upcoming" };
    }
    if (diff < 7) {
      var days = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
      ];
      return { text: days[due.getDay()] + timeSuffix, cls: "upcoming" };
    }
    return { text: dateStr.substring(5) + timeSuffix, cls: "" };
  }

  function isItemOverdue(item) {
    if (!item.due_date || item.complete) return false;
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var due = new Date(item.due_date + "T00:00:00");
    return due < today;
  }

  // ====================================================================
  // Render: list view items
  // ====================================================================

  // The rows of the last draw of the list: the list they were of, and
  // for each row what it was drawn from. A redraw builds every row
  // anew, and a row comes in with the entry animation only when it was
  // not there before, or its task has changed since. Given to every
  // row, the animation made the whole list dip to transparent each time
  // a change arrived.
  var drawnRows = { list: null, rows: {} };

  function renderItems(items, force) {
    if (!itemsContainer) return;

    // Tasks added without the server come first, in the order they
    // were added: the server reads their dates and priority when they
    // are sent, so they have no place in the sort yet.
    var waiting = currentListId
      ? QueueRules.queuedAdds(getOfflineQueue(), currentListId)
      : [];

    // Skip re-render if data hasn't changed (eliminates poll flicker)
    var fp = fingerprint([waiting, items]);
    if (!force && fp === lastItemsFingerprint) return;
    if (!force && redrawHeld()) return;
    lastItemsFingerprint = fp;

    // Another list's rows are all new to this one.
    var before = drawnRows.list === currentListId ? drawnRows.rows : {};
    var rows = {};
    drawnRows = { list: currentListId, rows: rows };

    function place(el, source) {
      var drawnFrom = fingerprint(source);
      if (before[source.id] !== drawnFrom) el.classList.add("item-enter");
      rows[source.id] = drawnFrom;
      itemsContainer.appendChild(el);
    }

    itemsContainer.innerHTML = "";
    if ((!items || items.length === 0) && waiting.length === 0) {
      if (emptyMsg) emptyMsg.classList.remove("hidden");
      return;
    }
    if (emptyMsg) emptyMsg.classList.add("hidden");

    waiting.forEach(function (queued) {
      place(createQueuedAddRow(queued), queued);
    });
    if (!items) return;

    // Separate top-level and subtasks
    var topLevel = [];
    var childMap = {};
    items.forEach(function (item) {
      if (item.parent_id) {
        if (!childMap[item.parent_id]) childMap[item.parent_id] = [];
        childMap[item.parent_id].push(item);
      } else {
        topLevel.push(item);
      }
    });

    topLevel = sortItems(topLevel);

    topLevel.forEach(function (item) {
      var hasChildren = childMap[item.id] && childMap[item.id].length > 0;
      var isCollapsed = hasChildren && collapsedParents[item.id];
      place(createItemCard(item, items, hasChildren, isCollapsed), item);
      if (hasChildren && !isCollapsed) {
        sortItems(childMap[item.id]).forEach(function (child) {
          var el = createItemCard(child, items, false, false);
          el.classList.add("subtask");
          place(el, child);
        });
      }
    });
  }

  // Marks a task whose change is waiting to be sent to the server.
  function createUnsentLabel() {
    var label = document.createElement("span");
    label.className = "item-unsent";
    label.textContent = "Not sent";
    label.title = "This change is sent when the server can be reached";
    return label;
  }

  // Takes back a task that is waiting to be added.
  function removeQueuedAdd(queued) {
    var step = { before: getOfflineQueue() };
    removeQueuedChange(queued.queued_at);
    step.after = getOfflineQueue();
    pushOfflineUndo(step.before, step.after);
    var name = '"' + queued.reminder + '"';
    showToast(name + " removed", function () {
      showToast(takeBackQueuedStep(step) ? name + " restored" : "Nothing to undo");
    });
  }

  function createQueuedAddRemoveButton(queued, className) {
    var button = document.createElement("button");
    button.className = className;
    button.textContent = "\u00D7";
    button.title = "Remove";
    button.setAttribute("aria-label", "Remove " + queued.reminder);
    button.addEventListener("click", function (e) {
      e.stopPropagation();
      removeQueuedAdd(queued);
    });
    return button;
  }

  // The row of a task added without the server: its text as typed and
  // the "Not sent" label. It cannot be ticked, opened or edited until
  // the server has it; it can be removed.
  function createQueuedAddRow(queued) {
    var div = document.createElement("div");
    div.className = "item priority-normal queued-add";

    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "item-checkbox";
    cb.disabled = true;
    cb.setAttribute("aria-label", queued.reminder + ", not sent yet");
    div.appendChild(cb);

    var content = document.createElement("div");
    content.className = "item-content";
    var reminder = document.createElement("div");
    reminder.className = "item-reminder";
    reminder.textContent = queued.reminder;
    content.appendChild(reminder);
    var meta = document.createElement("div");
    meta.className = "item-meta";
    meta.appendChild(createUnsentLabel());
    content.appendChild(meta);
    div.appendChild(content);

    var actions = document.createElement("div");
    actions.className = "item-actions";
    actions.appendChild(createQueuedAddRemoveButton(queued, "delete"));
    div.appendChild(actions);

    return div;
  }

  function createQueuedAddCard(queued) {
    var card = document.createElement("div");
    card.className = "board-card priority-normal queued-add";

    var text = document.createElement("div");
    text.className = "board-card-text";
    text.textContent = queued.reminder;
    card.appendChild(text);

    var meta = document.createElement("div");
    meta.className = "board-card-meta";
    meta.appendChild(createUnsentLabel());
    card.appendChild(meta);

    card.appendChild(
      createQueuedAddRemoveButton(queued, "board-card-grip queued-add-remove"),
    );
    return card;
  }

  function createItemCard(item, allItems, hasChildren, isCollapsed) {
    var div = document.createElement("div");
    var pClass =
      item.priority === 1
        ? "priority-high"
        : item.priority === 3
          ? "priority-low"
          : "priority-normal";
    div.className = "item " + pClass;
    if (item.complete) div.classList.add("completed");
    if (isItemOverdue(item)) div.classList.add("overdue");
    div.dataset.id = item.id;

    // Checkbox
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "item-checkbox";
    cb.checked = item.complete;
    cb.setAttribute("aria-label", "Toggle " + item.reminder);
    cb.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    cb.addEventListener("change", function (e) {
      e.stopPropagation();
      haptic(10);
      cb.classList.add("bounce");
      setTimeout(function () {
        cb.classList.remove("bounce");
      }, 150);
      onToggle(item.id);
    });
    div.appendChild(cb);

    // Content
    var content = document.createElement("div");
    content.className = "item-content";

    var reminder = document.createElement("div");
    reminder.className = "item-reminder";
    reminder.textContent = item.reminder;
    content.appendChild(reminder);

    // Meta row
    var meta = document.createElement("div");
    meta.className = "item-meta";

    if (item.unsent) meta.appendChild(createUnsentLabel());

    var dueInfo = formatDueDate(
      item.due_date,
      item.due_time,
      item.complete,
      item.due_time_end,
      item.due_time_block,
    );
    if (dueInfo) {
      var due = document.createElement("span");
      due.className = "item-due " + dueInfo.cls;
      due.textContent = dueInfo.text;
      meta.appendChild(due);
    }

    if (item.tags && item.tags.length > 0) {
      item.tags.forEach(function (tag) {
        var span = document.createElement("span");
        span.className = "tag";
        span.textContent = tag;
        meta.appendChild(span);
      });
    }

    if (item.is_recurring) {
      var rec = document.createElement("span");
      rec.className = "item-recurrence";
      rec.textContent = "\u{1F504} " + (item.recurrence_display || "");
      meta.appendChild(rec);
    }

    if (item.missed_recurrences > 0) {
      var missed = document.createElement("span");
      missed.className = "item-missed-badge";
      missed.textContent = item.missed_recurrences + " missed";
      meta.appendChild(missed);
    }

    if (item.estimated_pomodoros > 0) {
      var pom = document.createElement("span");
      pom.className = "item-pomodoro";
      pom.textContent =
        item.pomodoro_count + "/" + item.estimated_pomodoros + " \u{1F345}";
      meta.appendChild(pom);
    } else if (item.pomodoro_count > 0) {
      var pomC = document.createElement("span");
      pomC.className = "item-pomodoro";
      pomC.textContent = item.pomodoro_count + " \u{1F345}";
      meta.appendChild(pomC);
    }

    // Subtask progress badge with collapse toggle
    if (hasChildren && allItems) {
      var childCount = 0,
        childDone = 0;
      allItems.forEach(function (i) {
        if (i.parent_id === item.id) {
          childCount++;
          if (i.complete) childDone++;
        }
      });
      if (childCount > 0) {
        var toggle = document.createElement("button");
        toggle.className = "item-subtask-toggle";
        toggle.textContent = isCollapsed ? "\u25B6" : "\u25BC";
        toggle.setAttribute(
          "aria-label",
          isCollapsed ? "Expand subtasks" : "Collapse subtasks",
        );
        toggle.addEventListener("click", function (e) {
          e.stopPropagation();
          toggleCollapse(item.id);
        });
        meta.appendChild(toggle);

        var badge = document.createElement("span");
        badge.className = "item-subtask-badge";
        badge.textContent = "[" + childDone + "/" + childCount + "]";
        meta.appendChild(badge);
      }
    }

    if (meta.childNodes.length > 0) content.appendChild(meta);
    div.appendChild(content);

    // Delete button
    var actions = document.createElement("div");
    actions.className = "item-actions";
    var delBtn = document.createElement("button");
    delBtn.className = "delete";
    delBtn.textContent = "\u00D7";
    delBtn.title = "Delete";
    delBtn.setAttribute("aria-label", "Delete " + item.reminder);
    delBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      onDelete(item.id, item.reminder, div);
    });
    actions.appendChild(delBtn);
    div.appendChild(actions);

    // Tap card to open detail
    div.addEventListener("click", function () {
      location.hash = "#/item/" + item.id;
    });

    // Long-press for context menu
    attachLongPress(div, function () {
      openItemContextMenu(item);
    });

    // Swipe gestures
    attachSwipe(div, item.id, item.reminder);

    return div;
  }

  // ====================================================================
  // Render: kanban board view
  // ====================================================================

  async function refreshBoard(force) {
    if (!currentListId) return;
    try {
      serverBoardData = await api("/lists/" + currentListId + "/board");
      cachedBoardData = QueueRules.boardWithQueuedChanges(
        serverBoardData,
        getOfflineQueue(),
      );
      renderBoard(cachedBoardData, force);
    } catch (e) {
      console.error("Board load failed:", e);
    }
  }

  function renderBoard(data, force) {
    if (!boardContainer) return;

    // Skip re-render if data hasn't changed (eliminates poll flicker)
    var fp = fingerprint(data);
    if (!force && fp === lastBoardFingerprint) return;
    if (!force && redrawHeld()) return;
    lastBoardFingerprint = fp;

    boardContainer.innerHTML = "";

    if (!data || !data.board_columns || data.board_columns.length === 0) {
      if (boardEmptyMsg) boardEmptyMsg.classList.remove("hidden");
      return;
    }
    if (boardEmptyMsg) boardEmptyMsg.classList.add("hidden");

    var totalColumns = data.board_columns.length;

    data.board_columns.forEach(function (colName, colIdx) {
      var colItems = data.columns[colName] || [];
      var wipLimit = (data.wip_limits || {})[colName] || 0;
      var isFirst = colIdx === 0;
      var isLast = colIdx === totalColumns - 1;

      var col = document.createElement("div");
      col.className = "board-column";

      // Header
      var header = document.createElement("div");
      header.className = "board-column-header";
      var nameSpan = document.createElement("span");
      var colIcon = isFirst ? "\u{1F4E5} " : isLast ? "\u2705 " : "";
      nameSpan.textContent = colIcon + colName;
      header.appendChild(nameSpan);

      var countSpan = document.createElement("span");
      countSpan.className = "board-column-count";
      var countText = String(colItems.length);
      if (wipLimit > 0) {
        countText += "/" + wipLimit;
        if (colItems.length > wipLimit) countSpan.classList.add("over-wip");
      }
      countSpan.textContent = countText;
      header.appendChild(countSpan);

      // Long-press on header for column management
      attachLongPress(header, function () {
        openColumnContextMenu(colName, colIdx, totalColumns, colItems.length);
      });

      col.appendChild(header);

      // Items
      var itemsDiv = document.createElement("div");
      itemsDiv.className = "board-column-items";
      colItems.forEach(function (item) {
        itemsDiv.appendChild(
          item.provisional ? createQueuedAddCard(item) : createBoardCard(item),
        );
      });
      col.appendChild(itemsDiv);

      // Add button
      var addBtn = document.createElement("button");
      addBtn.className = "board-column-add";
      addBtn.textContent = "+ Add";
      addBtn.addEventListener("click", function () {
        openAddSheet();
      });
      col.appendChild(addBtn);

      boardContainer.appendChild(col);
    });

    // Column dots for phone
    var existingDots =
      boardContainer.parentElement.querySelector(".board-dots");
    if (existingDots) existingDots.remove();
    if (data.board_columns.length > 1) {
      var dots = document.createElement("div");
      dots.className = "board-dots";
      data.board_columns.forEach(function (_, idx) {
        var dot = document.createElement("div");
        dot.className = "board-dot" + (idx === 0 ? " active" : "");
        dots.appendChild(dot);
      });
      boardContainer.parentElement.insertBefore(
        dots,
        boardContainer.nextSibling,
      );

      // Update dots on scroll
      boardContainer.addEventListener("scroll", function () {
        var scrollLeft = boardContainer.scrollLeft;
        var colWidth = boardContainer.firstElementChild
          ? boardContainer.firstElementChild.offsetWidth + 12
          : 1;
        var activeIdx = Math.round(scrollLeft / colWidth);
        dots.querySelectorAll(".board-dot").forEach(function (d, i) {
          d.classList.toggle("active", i === activeIdx);
        });
      });
    }
  }

  function createBoardCard(item) {
    var card = document.createElement("div");
    var pClass =
      item.priority === 1
        ? "priority-high"
        : item.priority === 3
          ? "priority-low"
          : "priority-normal";
    card.className = "board-card " + pClass;
    if (item.complete) card.classList.add("completed");
    card.dataset.id = item.id;

    var text = document.createElement("div");
    text.className = "board-card-text";
    text.textContent = item.reminder;
    card.appendChild(text);

    var meta = document.createElement("div");
    meta.className = "board-card-meta";

    if (item.unsent) meta.appendChild(createUnsentLabel());

    var dueInfo = formatDueDate(
      item.due_date,
      item.due_time,
      item.complete,
      item.due_time_end,
      item.due_time_block,
    );
    if (dueInfo) {
      var due = document.createElement("span");
      due.className = "item-due " + dueInfo.cls;
      due.textContent = dueInfo.text;
      meta.appendChild(due);
    }

    if (item.tags && item.tags.length > 0) {
      item.tags.forEach(function (tag) {
        var span = document.createElement("span");
        span.className = "tag";
        span.textContent = tag;
        meta.appendChild(span);
      });
    }

    if (item.is_recurring) {
      var boardRec = document.createElement("span");
      boardRec.className = "item-recurrence";
      boardRec.textContent = "\u{1F504} " + (item.recurrence_display || "");
      meta.appendChild(boardRec);
    }

    if (item.missed_recurrences > 0) {
      var boardMissed = document.createElement("span");
      boardMissed.className = "item-missed-badge";
      boardMissed.textContent = item.missed_recurrences + " missed";
      meta.appendChild(boardMissed);
    }

    if (meta.childNodes.length > 0) card.appendChild(meta);

    // Subtask badge and collapsible checklist
    var subtasks = item.subtasks || [];
    if (subtasks.length > 0) {
      var stDone = subtasks.filter(function (s) {
        return s.complete;
      }).length;
      var stBadge = document.createElement("button");
      stBadge.className =
        "board-card-subtask-badge" +
        (stDone === subtasks.length ? " all-done" : "");
      stBadge.textContent =
        "\u2630 " + stDone + "/" + subtasks.length + " subtasks";
      stBadge.addEventListener("click", function (e) {
        e.stopPropagation();
        var container = card.querySelector(".board-card-subtasks");
        if (container) {
          container.classList.toggle("hidden");
        }
      });
      card.appendChild(stBadge);

      var stContainer = document.createElement("div");
      stContainer.className = "board-card-subtasks hidden";
      subtasks.forEach(function (sub) {
        var row = document.createElement("div");
        row.className =
          "board-card-subtask-row" + (sub.complete ? " completed" : "");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = sub.complete;
        cb.addEventListener("click", function (e) {
          e.stopPropagation();
        });
        cb.addEventListener("change", function (e) {
          e.stopPropagation();
          onToggle(sub.id);
        });
        row.appendChild(cb);
        var label = document.createElement("span");
        label.textContent = sub.reminder;
        label.addEventListener("click", function (e) {
          e.stopPropagation();
          location.hash = "#/item/" + sub.id;
        });
        row.appendChild(label);
        stContainer.appendChild(row);
      });
      card.appendChild(stContainer);
    }

    // Grip icon for pick-up-and-place / drag
    var grip = document.createElement("span");
    grip.className = "board-card-grip";
    grip.textContent = "\u2807";
    grip.setAttribute("role", "button");
    grip.setAttribute("aria-label", "Move card");
    grip.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    attachCardDrag(grip, card, item);
    card.appendChild(grip);

    card.addEventListener("click", function () {
      if (moveMode) {
        // Tap held card to cancel
        if (moveMode.itemId === item.id) {
          exitMoveMode();
          return;
        }
      }
      location.hash = "#/item/" + item.id;
    });

    // Long-press for context menu
    attachLongPress(card, function () {
      if (moveMode) return; // Don't open context menu while moving
      openItemContextMenu(item);
    });

    return card;
  }

  // ====================================================================
  // ====================================================================
  // Calendar view
  // ====================================================================

  // The calendar's view in use is kept in the browser, like the page's
  // view, so that a page loaded again opens where it was: opened from
  // the home screen, brought back by the browser, or reloaded by
  // itself for a new version. The date is not kept; the calendar opens
  // on today.
  var CAL_VIEWS = ["month", "week", "day", "timeline"];
  var calSubView = localStorage.getItem(CAL_VIEW_KEY);
  if (CAL_VIEWS.indexOf(calSubView) === -1) calSubView = "month";
  var calDate = new Date();
  // The calendar shows today until the arrows take it to another month,
  // week or day, and again once the arrows or Today bring it back. A
  // page left open overnight then shows the new day; a date that was
  // chosen is kept.
  var calDateChosen = false;

  // Wire up calendar toolbar
  var calToolbar = document.querySelector(".cal-toolbar");
  var calPrev = document.getElementById("cal-prev");
  var calNext = document.getElementById("cal-next");
  var calToday = document.getElementById("cal-today");
  var calTitle = document.getElementById("cal-title");
  var calContainer = document.getElementById("cal-container");
  var calTabs = document.querySelectorAll(".cal-tab");

  if (calPrev)
    calPrev.addEventListener("click", function () {
      navigateCalendar(-1);
    });
  if (calNext)
    calNext.addEventListener("click", function () {
      navigateCalendar(1);
    });
  if (calToday)
    calToday.addEventListener("click", function () {
      calDateChosen = false;
      renderCalendar();
    });
  calTabs.forEach(function (tab) {
    tab.classList.toggle("active", tab.dataset.cal === calSubView);
    tab.addEventListener("click", function () {
      calSubView = tab.dataset.cal;
      localStorage.setItem(CAL_VIEW_KEY, calSubView);
      calTabs.forEach(function (t) {
        t.classList.toggle("active", t === tab);
      });
      renderCalendar();
    });
  });

  function navigateCalendar(dir) {
    // The Timeline is not about one date; its arrows are hidden.
    if (calSubView === "timeline") return;
    if (calSubView === "month") {
      // The same day of the month before or after, or that month's last
      // day where it is shorter. setMonth alone carries the days a
      // shorter month lacks into the month after it: from January 31
      // the next arrow went to March.
      var day = calDate.getDate();
      calDate.setDate(1);
      calDate.setMonth(calDate.getMonth() + dir);
      var lastDay = new Date(
        calDate.getFullYear(),
        calDate.getMonth() + 1,
        0,
      ).getDate();
      calDate.setDate(Math.min(day, lastDay));
    } else if (calSubView === "week") {
      calDate.setDate(calDate.getDate() + dir * 7);
    } else {
      calDate.setDate(calDate.getDate() + dir);
    }
    calDateChosen = !calShowsToday();
    renderCalendar();
  }

  // Whether today is where the calendar is. On a wide screen the Month
  // and the Week show a calendar month and week, and are there when
  // today is in it. On a narrow screen the Month has a selected day and
  // the Week begins at a day, and they are there, like the Day, when
  // that day is today.
  function calShowsToday() {
    var today = new Date();
    if (!calIsNarrow()) {
      if (calSubView === "month") {
        return (
          calDate.getFullYear() === today.getFullYear() &&
          calDate.getMonth() === today.getMonth()
        );
      }
      if (calSubView === "week") {
        return (
          _startOfWeek(calDate).getTime() === _startOfWeek(today).getTime()
        );
      }
    }
    return _dayKey(calDate) === _dayKey(today);
  }

  // Whether the view on screen is an hour grid, drawn from the server's
  // answer: the Day, and the Week on a wide screen. The others are
  // drawn from the current list's tasks.
  function calShowsHourGrid() {
    return calSubView === "day" || (calSubView === "week" && !calIsNarrow());
  }

  // The calendar is on a day that has passed without having been
  // chosen: the page was loaded, or the calendar last drawn, on an
  // earlier day.
  function calDateIsStale() {
    return !calDateChosen && _dayKey(calDate) !== _dayKey(new Date());
  }

  // Counts the times the calendar has been drawn. An answer from the
  // server that arrives after a later draw is for a calendar that is no
  // longer on screen, and is dropped.
  var calDraws = 0;

  function renderCalendar() {
    if (!calContainer) return;
    calDraws++;
    if (!calDateChosen) calDate = new Date();
    var dated = calSubView !== "timeline";
    if (calToolbar) calToolbar.classList.toggle("cal-undated", !dated);
    if (calToday) calToday.disabled = !dated || calShowsToday();
    if (calSubView === "month") renderMonthView();
    else if (calSubView === "week") renderWeekView();
    else if (calSubView === "timeline") renderTimelineView();
    else renderDayView();
    calDrawnFrom = calShownFrom();
  }

  // What the Month and the Timeline were last drawn from, to tell
  // whether a refresh has anything new for them.
  var calDrawnFrom = "";

  // What the Month and the Timeline show: the view, its date, and the
  // current list's dated tasks, queued changes included.
  function calShownFrom() {
    return fingerprint([calSubView, _dayKey(calDate), _calItems()]);
  }

  // The calendar after a refresh, or a change to the queue: it is drawn
  // again when what it shows has changed, and left alone otherwise. The
  // hour grids and the Timeline's charts are costly to draw, and the
  // Timeline asks the server for its figures each time.
  //
  // The Month and the Timeline are drawn from the current list's tasks.
  // The Week and the Day are drawn from the server's answer, which
  // covers every list, so that answer is what is compared.
  function refreshCalendar() {
    if (!calContainer) return;
    if (redrawHeld()) return;
    if (calShowsHourGrid()) {
      _refreshHourGrid();
      return;
    }
    if (!calDateChosen) calDate = new Date();
    if (calShownFrom() === calDrawnFrom) return;
    keepingPageScroll(renderCalendar);
  }

  // Draws with the page left where it was scrolled to. A calendar that
  // is emptied and filled again is for a moment shorter than the
  // screen, and the page would jump to its top. The page scrolls as a
  // whole, or inside the main area, depending on the layout.
  function keepingPageScroll(draw) {
    var main = document.getElementById("main");
    var inMain = main ? main.scrollTop : 0;
    var inPage = window.scrollY;
    draw();
    if (main && main.scrollTop !== inMain) main.scrollTop = inMain;
    if (window.scrollY !== inPage) window.scrollTo(window.scrollX, inPage);
  }

  function _calItems() {
    return cachedItems.filter(function (i) {
      return i.due_date && !i.parent_id;
    });
  }

  function _itemsByDate(items) {
    var map = {};
    items.forEach(function (item) {
      var d = item.due_date;
      if (!map[d]) map[d] = [];
      map[d].push(item);
    });
    return map;
  }

  function _dayKey(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  // A screen as narrow as a phone's. Seven columns of it cannot hold
  // task titles, so the calendar is laid out differently there.
  var calNarrowScreen = window.matchMedia("(max-width: 700px)");

  function calIsNarrow() {
    return calNarrowScreen.matches;
  }

  // The window made wider or narrower across that width, or a phone
  // turned on its side.
  calNarrowScreen.addEventListener("change", function () {
    if (viewMode === "calendar") renderCalendar();
  });

  // The week begins on Monday, as in the desktop application.
  var _WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  // A date's place in the week: 0 for Monday, 6 for Sunday.
  function _weekdayIndex(d) {
    return (d.getDay() + 6) % 7;
  }

  function renderMonthView() {
    var year = calDate.getFullYear();
    var month = calDate.getMonth();
    var monthNames = [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ];
    if (calTitle) calTitle.textContent = monthNames[month] + " " + year;

    var byDate = _itemsByDate(_calItems());
    if (calIsNarrow()) _renderCompactMonth(year, month, byDate);
    else _renderWideMonth(year, month, byDate);
  }

  // The month on a wide screen: a cell for each day, holding the titles
  // of its first tasks.
  function _renderWideMonth(year, month, byDate) {
    var leading = _weekdayIndex(new Date(year, month, 1));
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var todayKey = _dayKey(new Date());

    var html = '<div class="cal-month-grid">';
    _WEEKDAY_NAMES.forEach(function (name) {
      html += '<div class="cal-dow">' + name + "</div>";
    });

    // Empty cells before the first day
    for (var e = 0; e < leading; e++) {
      html += '<div class="cal-day empty"></div>';
    }

    for (var d = 1; d <= daysInMonth; d++) {
      var key = _dayKey(new Date(year, month, d));
      var isToday = key === todayKey;
      var cls = "cal-day" + (isToday ? " today" : "");
      html += '<div class="' + cls + '">';
      html += '<span class="cal-day-num">' + d + "</span>";
      var dayItems = byDate[key] || [];
      for (var j = 0; j < Math.min(dayItems.length, 3); j++) {
        var it = dayItems[j];
        var pCls =
          it.priority === 1
            ? "priority-high"
            : it.priority === 3
              ? "priority-low"
              : "";
        html +=
          '<div class="cal-item ' +
          pCls +
          (it.complete ? " completed" : "") +
          '" data-id="' +
          it.id +
          '">' +
          _escHtml(it.reminder) +
          "</div>";
      }
      if (dayItems.length > 3) {
        html +=
          '<div class="cal-item-more">+' +
          (dayItems.length - 3) +
          " more</div>";
      }
      html += "</div>";
    }

    // Empty cells after the last day, to the end of its week
    var trailing = (7 - ((leading + daysInMonth) % 7)) % 7;
    for (var t = 0; t < trailing; t++) {
      html += '<div class="cal-day empty"></div>';
    }
    html += "</div>";
    calContainer.innerHTML = html;

    // Click handlers for items
    calContainer.querySelectorAll(".cal-item[data-id]").forEach(function (el) {
      el.addEventListener("click", function () {
        location.hash = "#/item/" + el.dataset.id;
      });
    });
  }

  // The month on a narrow screen: a grid of day numbers, each with a
  // dot for a task due on it, and under the grid the tasks of the day
  // that is selected. The selected day is the calendar's date: the Day
  // view opens on it, and the arrows carry it to the month before or
  // after.
  function _renderCompactMonth(year, month, byDate) {
    calContainer.innerHTML = "";
    var grid = document.createElement("div");
    grid.className = "cal-mini-grid";
    _WEEKDAY_NAMES.forEach(function (name) {
      var head = document.createElement("div");
      head.className = "cal-mini-dow";
      head.textContent = name;
      grid.appendChild(head);
    });

    // Whole weeks: the days of the months before and after that share
    // a week with this one are shown too, dimmed.
    var leading = _weekdayIndex(new Date(year, month, 1));
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var cells = Math.ceil((leading + daysInMonth) / 7) * 7;
    var todayKey = _dayKey(new Date());
    var selectedKey = _dayKey(calDate);
    for (var i = 0; i < cells; i++) {
      var day = new Date(year, month, 1 - leading + i);
      var key = _dayKey(day);
      grid.appendChild(
        _compactDay(
          day,
          byDate[key] || [],
          {
            other: day.getMonth() !== month,
            today: key === todayKey,
            selected: key === selectedKey,
          },
          selectCalendarDay,
        ),
      );
    }
    calContainer.appendChild(grid);
    calContainer.appendChild(_dayTaskList(calDate, byDate[selectedKey] || []));
  }

  // The most dots a day shows; a day with more says how many more.
  var _MAX_DAY_DOTS = 3;

  // A day as a button: its number, and a dot for each of its first
  // tasks. is says how it stands (other: of another month; today;
  // selected, for a grid that has a selected day), and onTap is given
  // the day when the button is pressed.
  function _compactDay(day, items, is, onTap) {
    var cell = document.createElement("button");
    cell.type = "button";
    cell.className =
      "cal-mini-day" +
      (is.other ? " other" : "") +
      (is.today ? " today" : "") +
      (is.selected ? " selected" : "");
    if (is.selected !== undefined) {
      cell.setAttribute("aria-pressed", is.selected ? "true" : "false");
    }
    cell.setAttribute(
      "aria-label",
      day.toLocaleDateString(undefined, {
        weekday: "long",
        day: "numeric",
        month: "long",
      }) +
        ", " +
        _taskCount(items.length),
    );

    var num = document.createElement("span");
    num.className = "cal-mini-num";
    num.textContent = String(day.getDate());
    cell.appendChild(num);

    var dots = document.createElement("span");
    dots.className = "cal-mini-dots";
    var sorted = _sortDayTasks(items);
    sorted.slice(0, _MAX_DAY_DOTS).forEach(function (item) {
      var dot = document.createElement("span");
      dot.className =
        "cal-mini-dot" +
        (item.complete
          ? " done"
          : item.priority === 1
            ? " high"
            : item.priority === 3
              ? " low"
              : "");
      dots.appendChild(dot);
    });
    if (sorted.length > _MAX_DAY_DOTS) {
      var more = document.createElement("span");
      more.className = "cal-mini-more";
      more.textContent = "+" + (sorted.length - _MAX_DAY_DOTS);
      dots.appendChild(more);
    }
    cell.appendChild(dots);

    cell.addEventListener("click", function () {
      onTap(day);
    });
    return cell;
  }

  // Makes a day the calendar's date. A day of another month takes the
  // month view there.
  function selectCalendarDay(day) {
    calDate = new Date(day.getFullYear(), day.getMonth(), day.getDate());
    calDateChosen = !calShowsToday();
    keepingPageScroll(renderCalendar);
  }

  function _taskCount(count) {
    if (count === 0) return "no tasks";
    return count + (count === 1 ? " task" : " tasks");
  }

  // The tasks of one day in the order they are listed: those still to
  // do before those done, a task with a time before one without, then
  // by time, then by priority.
  function _sortDayTasks(items) {
    return items.slice().sort(function (a, b) {
      if (a.complete !== b.complete) return a.complete ? 1 : -1;
      if (Boolean(a.due_time) !== Boolean(b.due_time)) return a.due_time ? -1 : 1;
      if (a.due_time && a.due_time !== b.due_time) {
        return a.due_time < b.due_time ? -1 : 1;
      }
      return a.priority - b.priority;
    });
  }

  // When in its day a task is due, in one or two short lines: a time,
  // the two ends of a time range, the name of a time block, or all day.
  function _taskTimeLines(item) {
    if (item.due_time && item.due_time_end) {
      return [item.due_time.substring(0, 5), item.due_time_end.substring(0, 5)];
    }
    if (item.due_time) return [item.due_time.substring(0, 5)];
    if (item.due_time_block) {
      var label = item.due_time_block.replace(/_/g, " ");
      return [label.charAt(0).toUpperCase() + label.slice(1)];
    }
    return ["All day"];
  }

  // A task as a row of the calendar's lists. timeLines replaces the
  // time of day where the row stands for something else.
  function _calTaskRow(item, timeLines) {
    var row = document.createElement("button");
    row.type = "button";
    row.className =
      "cal-task" +
      (item.priority === 1
        ? " priority-high"
        : item.priority === 3
          ? " priority-low"
          : "") +
      (item.complete ? " completed" : "");
    row.dataset.id = item.id;

    var time = document.createElement("span");
    time.className = "cal-task-time";
    (timeLines || _taskTimeLines(item)).forEach(function (line) {
      var span = document.createElement("span");
      span.textContent = line;
      time.appendChild(span);
    });
    row.appendChild(time);

    var title = document.createElement("span");
    title.className = "cal-task-title";
    title.textContent = item.reminder;
    row.appendChild(title);

    row.addEventListener("click", function () {
      location.hash = "#/item/" + item.id;
    });
    return row;
  }

  // The tasks of one day under a heading that names it.
  function _dayTaskList(day, items) {
    var section = document.createElement("div");
    section.className = "cal-day-tasks";

    var now = new Date();
    var isToday = _dayKey(day) === _dayKey(now);
    var isTomorrow =
      _dayKey(day) ===
      _dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
    var heading = document.createElement("div");
    heading.className = "cal-day-heading" + (isToday ? " today" : "");
    var name = document.createElement("span");
    name.className = "cal-day-name";
    name.textContent = day.toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
    heading.appendChild(name);
    var note = document.createElement("span");
    note.className = "cal-day-note";
    note.textContent =
      (isToday ? "Today \u00B7 " : isTomorrow ? "Tomorrow \u00B7 " : "") +
      _taskCount(items.length);
    heading.appendChild(note);
    section.appendChild(heading);

    _sortDayTasks(items).forEach(function (item) {
      section.appendChild(_calTaskRow(item));
    });
    return section;
  }

  // Hour-grid constants — shared by week and day Canvas 2D views.
  var _HOUR_ROW_HEIGHT = 30;
  var _GRID_HEADER_HEIGHT = 32;
  var _HOUR_LABEL_WIDTH = 50;
  var _CHIP_HEIGHT = 22;
  var _CHIP_SPACING = 2;
  var _ROW_PADDING = 4;
  var _GRID_CANVAS_MIN_WIDTH = 560;

  // The Monday of a date's week.
  function _startOfWeek(dt) {
    var d = new Date(dt);
    d.setDate(d.getDate() - _weekdayIndex(d));
    d.setHours(0, 0, 0, 0);
    return d;
  }

  function _paletteColor(state) {
    var key = (state || "future").replace(/_/g, "-");
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue("--bar-" + key)
      .trim();
    return v || "#60a5fa";
  }

  function _paletteDeviation(state) {
    var key = (state || "future").replace(/_/g, "-");
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue("--bar-" + key + "-deviation")
      .trim();
    return v || _paletteColor(state);
  }

  function _themeColor(name, fallback) {
    var v = getComputedStyle(document.documentElement)
      .getPropertyValue("--" + name)
      .trim();
    return v || fallback;
  }

  // The first day and the number of days of the hour grid on screen.
  function _hourGridRange() {
    if (calSubView === "week") return { start: _startOfWeek(calDate), days: 7 };
    var start = new Date(calDate);
    start.setHours(0, 0, 0, 0);
    return { start: start, days: 1 };
  }

  // The Week. On a wide screen, the hour grid of the calendar week,
  // Monday to Sunday. On a narrow one, seven columns of hours do not
  // fit, and most tasks have no hour: the week is seven days beginning
  // at the calendar's date, today unless another was chosen, with the
  // tasks listed day by day.
  function renderWeekView() {
    var narrow = calIsNarrow();
    var first = narrow
      ? new Date(calDate.getFullYear(), calDate.getMonth(), calDate.getDate())
      : _startOfWeek(calDate);
    var last = new Date(first);
    last.setDate(last.getDate() + 6);
    if (calTitle) {
      calTitle.textContent =
        first.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }) +
        " \u2013 " +
        last.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
    }
    if (narrow) _renderWeekList(first);
    else _renderHourGrid(first, 7);
  }

  // The week on a narrow screen: a strip of its seven days, each with
  // the dots of its tasks, and under it a section of tasks for each
  // day. A tap on a day of the strip brings its section to the top of
  // the list.
  //
  // The list scrolls inside the room between the strip and the bottom
  // bar. The toolbar and the strip stay where they are: scrolled with
  // the page, they slid under the header, and the arrows and the dates
  // were cut off by it.
  //
  // When today is in the week, the tasks still to do that were due
  // before the week's first day come first, under "Overdue": they are
  // what the days ahead start with.
  function _renderWeekList(first) {
    var firstKey = _dayKey(first);
    // The same week drawn again, after a change to its tasks, stays
    // where its list was scrolled to.
    var shown = calContainer.querySelector(".cal-week-days");
    var scrolled =
      shown && shown.dataset.first === firstKey ? shown.scrollTop : 0;

    calContainer.innerHTML = "";
    var byDate = _itemsByDate(_calItems());
    var todayKey = _dayKey(new Date());

    var days = [];
    for (var i = 0; i < 7; i++) {
      days.push(new Date(first.getFullYear(), first.getMonth(), first.getDate() + i));
    }
    var lastKey = _dayKey(days[6]);

    var strip = document.createElement("div");
    strip.className = "cal-mini-grid cal-week-strip";
    var sections = document.createElement("div");
    sections.className = "cal-week-days";
    sections.dataset.first = firstKey;

    if (firstKey <= todayKey && todayKey <= lastKey) {
      var overdue = _calItems().filter(function (item) {
        return !item.complete && item.due_date < firstKey;
      });
      if (overdue.length > 0) sections.appendChild(_overdueTaskList(overdue));
    }

    days.forEach(function (day) {
      var key = _dayKey(day);
      var items = byDate[key] || [];
      var section = _dayTaskList(day, items);
      sections.appendChild(section);

      // A day of the strip moves the list, not the calendar's date.
      var cell = _compactDay(
        day,
        items,
        { other: false, today: key === todayKey },
        function () {
          _showWeekDay(section);
        },
      );
      var name = document.createElement("span");
      name.className = "cal-mini-dow";
      name.textContent = _WEEKDAY_NAMES[_weekdayIndex(day)];
      cell.insertBefore(name, cell.firstChild);
      strip.appendChild(cell);
    });

    calContainer.appendChild(strip);
    calContainer.appendChild(sections);
    _fitWeekList();
    sections.scrollTop = scrolled;
  }

  // The least room worth scrolling a part of the calendar in. A screen
  // with less, a phone on its side, scrolls the whole page as before.
  var _WEEK_LIST_MIN_HEIGHT = 200;

  // The height between the top of an element and the bottom bar.
  function _roomAboveBottomBar(el) {
    var nav = document.getElementById("bottom-nav");
    var bottom = nav ? nav.getBoundingClientRect().top : window.innerHeight;
    return Math.floor(bottom - el.getBoundingClientRect().top - 8);
  }

  // Gives the week's list the room between the strip and the bottom
  // bar, to scroll in. Space is left after the last day, enough for it
  // to reach the top like any other day of the strip.
  function _fitWeekList() {
    var list = calContainer && calContainer.querySelector(".cal-week-days");
    if (!list) return;
    var room = _roomAboveBottomBar(list);
    list.style.paddingBottom = "";
    if (room < _WEEK_LIST_MIN_HEIGHT) {
      list.classList.remove("scrolls");
      list.style.height = "";
      return;
    }
    list.classList.add("scrolls");
    list.style.height = room + "px";
    var last = list.lastElementChild;
    if (last) {
      list.style.paddingBottom = Math.max(0, room - last.offsetHeight) + "px";
    }
  }

  // Gives the hour grid the room down to the bottom bar: its hours
  // scroll inside it, and the page, with the toolbar, stays in place.
  // The style sheet's own limit stands where there is too little room.
  function _fitHourGrid() {
    var wrap =
      calContainer && calContainer.querySelector(".cal-hour-grid-wrap");
    if (!wrap) return;
    var room = _roomAboveBottomBar(wrap);
    wrap.style.maxHeight = room < _WEEK_LIST_MIN_HEIGHT ? "" : room + "px";
  }

  // The window resized, a phone turned on its side, the browser's own
  // bars shown or hidden.
  window.addEventListener("resize", function () {
    _fitWeekList();
    _fitHourGrid();
  });

  // Brings a day's section to the top of the week's list; where the
  // whole page scrolls, to the top of the page below the header that
  // stays in place.
  function _showWeekDay(section) {
    var list = section.parentElement;
    if (list.classList.contains("scrolls")) {
      list.scrollTo({
        top: section.offsetTop - list.firstElementChild.offsetTop,
        behavior: "smooth",
      });
      return;
    }
    var header = document.getElementById("header");
    section.style.scrollMarginTop =
      (header ? header.offsetHeight : 0) + 8 + "px";
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // The tasks that were due before the days shown, oldest first, each
  // with the day it was due in place of a time.
  function _overdueTaskList(items) {
    var section = document.createElement("div");
    section.className = "cal-day-tasks";
    var heading = document.createElement("div");
    heading.className = "cal-day-heading overdue";
    var name = document.createElement("span");
    name.className = "cal-day-name";
    name.textContent = "Overdue";
    heading.appendChild(name);
    var note = document.createElement("span");
    note.className = "cal-day-note";
    note.textContent = _taskCount(items.length);
    heading.appendChild(note);
    section.appendChild(heading);

    items
      .slice()
      .sort(function (a, b) {
        if (a.due_date !== b.due_date) return a.due_date < b.due_date ? -1 : 1;
        return a.priority - b.priority;
      })
      .forEach(function (item) {
        var due = new Date(item.due_date + "T00:00:00");
        section.appendChild(
          _calTaskRow(item, [
            due.toLocaleDateString(undefined, {
              weekday: "short",
              day: "numeric",
            }),
          ]),
        );
      });
    return section;
  }

  function renderDayView() {
    if (calTitle) {
      calTitle.textContent = calDate.toLocaleDateString(undefined, {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric",
      });
    }
    var start = new Date(calDate);
    start.setHours(0, 0, 0, 0);
    _renderHourGrid(start, 1);
  }

  // The hour grid on screen: the days it was asked for, and the
  // server's answer it was painted from. answer is null until the first
  // one arrives, and after a request that failed.
  var hourGridShown = { range: "", answer: null };
  // Counts the refreshes asked for: of two answers on their way, the
  // later request's is the one used.
  var hourGridRefreshes = 0;
  // The draw whose grid is on screen with "Loading", waiting for its
  // first answer; 0 when none is.
  var hourGridLoading = 0;

  // The bars of the list chosen in the header. The Month and the
  // narrow Week are drawn from that list's tasks; the hour grid showed
  // those of every list, and a bar of another list could not be opened:
  // the item sheet knows the chosen list's tasks only.
  function _fetchSegments(startDate, days) {
    return api(
      "/calendar/segments?start=" +
        encodeURIComponent(_dayKey(startDate)) +
        "&days=" +
        days +
        _listQuery("&"),
    );
  }

  // The chosen list, as a part of a request's query: led by "&" after
  // other parts, by "?" as the first. Empty when no list is chosen.
  function _listQuery(lead) {
    return currentListId
      ? lead + "list_id=" + encodeURIComponent(currentListId)
      : "";
  }

  // The days of an hour grid and the list they are of, as one key.
  function _hourGridKey(startDate, days) {
    return _dayKey(startDate) + "/" + days + "/" + (currentListId || "");
  }

  // Puts an empty hour grid on screen, in place of whatever the
  // calendar showed.
  //
  // The hour-grid view is two stacked canvases sharing the same
  // width so their day columns line up pixel-for-pixel. The pinned
  // canvas carries the header row, the all-day chip row, and the
  // overdue marker row; it stays visible while the user scrolls.
  // The hours canvas carries the 24-hour grid and its bars; it
  // lives inside a scrolling div so the pinned rows stay anchored.
  function _buildHourGrid(days) {
    calContainer.innerHTML = "";

    var wrap = document.createElement("div");
    wrap.className = "cal-hour-grid-wrap";

    var pinnedCanvas = document.createElement("canvas");
    pinnedCanvas.className = "cal-hour-grid-pinned";
    wrap.appendChild(pinnedCanvas);

    var scrollDiv = document.createElement("div");
    scrollDiv.className = "cal-hour-grid-scroll";
    var hoursCanvas = document.createElement("canvas");
    hoursCanvas.className = "cal-hour-grid-hours";
    scrollDiv.appendChild(hoursCanvas);
    wrap.appendChild(scrollDiv);

    calContainer.appendChild(wrap);
    _fitHourGrid();

    // The width inside the wrap's padding. One day takes it as it is,
    // however narrow. Seven columns need a least width to hold their
    // titles, and scroll sideways where the window has less.
    var style = getComputedStyle(wrap);
    var room =
      wrap.clientWidth -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight);
    if (!(room > 0)) room = 720;
    return {
      wrap: wrap,
      pinned: pinnedCanvas,
      hours: hoursCanvas,
      scroll: scrollDiv,
      width: days === 1 ? room : Math.max(room, _GRID_CANVAS_MIN_WIDTH),
    };
  }

  // The minute of the day the hours open at: the present time when
  // today is among the days shown; otherwise the first bar that has a
  // time, or 08:00 when none has.
  function _openingMinute(data) {
    var now = new Date();
    var todayKey = _dayKey(now);
    var first = null;
    for (var d = 0; d < data.days.length; d++) {
      if (data.days[d].date === todayKey) {
        return now.getHours() * 60 + now.getMinutes();
      }
      data.days[d].segments.forEach(function (seg) {
        if (seg.is_all_day || seg.is_marker) return;
        if (first === null || seg.start_minute < first) first = seg.start_minute;
      });
    }
    return first === null ? 8 * 60 : first;
  }

  // Scrolls the hours so that the opening minute is an hour below the
  // top: opened at midnight, the grid showed the empty night.
  function _openHoursAt(scrollDiv, data) {
    var minute = Math.max(0, _openingMinute(data) - 60);
    scrollDiv.scrollTop = Math.round((minute / 60) * _HOUR_ROW_HEIGHT);
  }

  function _renderHourGrid(startDate, days) {
    var grid = _buildHourGrid(days);
    var loading = document.createElement("div");
    loading.className = "cal-hour-grid-loading";
    loading.textContent = "Loading\u2026";
    grid.wrap.appendChild(loading);

    var draw = calDraws;
    hourGridShown = { range: _hourGridKey(startDate, days), answer: null };
    hourGridLoading = draw;
    _fetchSegments(startDate, days)
      .then(function (data) {
        if (hourGridLoading === draw) hourGridLoading = 0;
        if (draw !== calDraws) return;
        loading.remove();
        _paintPinnedAndHours(grid.pinned, grid.hours, data, days, grid.width);
        _openHoursAt(grid.scroll, data);
        hourGridShown.answer = fingerprint(data);
      })
      .catch(function () {
        if (hourGridLoading === draw) hourGridLoading = 0;
        if (draw !== calDraws) return;
        loading.textContent = "Failed to load calendar data";
      });
  }

  // The Week or Day grid after a refresh. The server is asked again,
  // and the grid is replaced only when its answer differs from the one
  // on screen: with the answer in hand, so nothing says "Loading", and
  // scrolled to the hour it was at. A request that fails leaves the
  // grid as it is. A grid that is waiting for its first answer is left
  // to it.
  function _refreshHourGrid() {
    if (hourGridLoading === calDraws) return;
    if (!calDateChosen) calDate = new Date();
    var range = _hourGridRange();
    var key = _hourGridKey(range.start, range.days);
    if (key !== hourGridShown.range) {
      // Another list has been chosen, or the day has changed under a
      // calendar that follows today.
      renderCalendar();
      return;
    }
    var draw = calDraws;
    var refresh = ++hourGridRefreshes;
    _fetchSegments(range.start, range.days)
      .then(function (data) {
        // The calendar has been drawn again, or left, since.
        if (draw !== calDraws || refresh !== hourGridRefreshes) return;
        if (viewMode !== "calendar") return;
        var answer = fingerprint(data);
        if (answer === hourGridShown.answer) return;
        // A press that began while the answer was on its way.
        if (redrawHeld()) return;
        var old = calContainer.querySelector(".cal-hour-grid-scroll");
        var scrolled = old ? old.scrollTop : 0;
        keepingPageScroll(function () {
          var grid = _buildHourGrid(range.days);
          _paintPinnedAndHours(
            grid.pinned,
            grid.hours,
            data,
            range.days,
            grid.width,
          );
          grid.scroll.scrollTop = scrolled;
        });
        hourGridShown.answer = answer;
      })
      .catch(function () {
        /* the grid on screen stands */
      });
  }

  function _paintPinnedAndHours(pinned, hours, data, days, W) {
    // Measure the tallest column so the pinned canvas is just the
    // height it actually needs — empty days collapse the row.
    var maxAllDay = 0;
    var maxMarkers = 0;
    for (var d = 0; d < days; d++) {
      var allDayCount = 0;
      var markerCount = 0;
      data.days[d].segments.forEach(function (seg) {
        if (seg.is_all_day) allDayCount++;
        else if (seg.is_marker) markerCount++;
      });
      if (allDayCount > maxAllDay) maxAllDay = allDayCount;
      if (markerCount > maxMarkers) maxMarkers = markerCount;
    }

    var chipSlot = _CHIP_HEIGHT + _CHIP_SPACING;
    var allDayRowH =
      maxAllDay > 0 ? maxAllDay * chipSlot + _ROW_PADDING : 0;
    var markerRowH =
      maxMarkers > 0 ? maxMarkers * chipSlot + _ROW_PADDING : 0;

    var pinnedH = _GRID_HEADER_HEIGHT + allDayRowH + markerRowH;
    var hoursH = 24 * _HOUR_ROW_HEIGHT;

    // A canvas has as many pixels as the screen gives its size, and is
    // painted in the page's own units. With one pixel to each unit, a
    // phone's screen, which has two or three, showed the text blurred.
    var ratio = window.devicePixelRatio || 1;
    _sizeCanvas(pinned, W, pinnedH, ratio);
    _sizeCanvas(hours, W, hoursH, ratio);

    var layout = {
      W: W,
      pinnedH: pinnedH,
      hoursH: hoursH,
      ratio: ratio,
      days: days,
      colWidth: (W - _HOUR_LABEL_WIDTH) / days,
      todayKey: _dayKey(new Date()),
      allDayRowH: allDayRowH,
      markerRowH: markerRowH,
    };

    _paintPinnedZone(pinned, data, layout);
    _paintHoursZone(hours, data, layout);

    _installHourGridClickHandler(pinned);
    _installHourGridClickHandler(hours);
  }

  // Sizes a canvas in the page's units; its own pixels are ratio times
  // as many each way. The size in units is kept for finding what a
  // click is on.
  function _sizeCanvas(canvas, width, height, ratio) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    canvas._unitWidth = width;
    canvas._unitHeight = height;
  }

  function _paintPinnedZone(canvas, data, layout) {
    var ctx = canvas.getContext("2d");
    ctx.setTransform(layout.ratio, 0, 0, layout.ratio, 0, 0);
    var W = layout.W;
    var H = layout.pinnedH;
    ctx.clearRect(0, 0, W, H);

    var border = _themeColor("border", "#e0e0e0");
    var textPrimary = _themeColor("text", "#333");
    var bgCard = _themeColor("bg-card", "#fff");
    var todayBg = _themeColor("accent-subtle", "rgba(33,150,243,0.08)");

    var colWidth = layout.colWidth;
    var days = layout.days;
    var headerY = 0;
    var allDayY = _GRID_HEADER_HEIGHT;
    var markerY = allDayY + layout.allDayRowH;
    var todayKey = layout.todayKey;

    // Header background + today-column tint across the full pinned
    // height so the tint stays visible above the scrollable grid.
    ctx.fillStyle = bgCard;
    ctx.fillRect(0, 0, W, H);

    for (var t = 0; t < days; t++) {
      if (data.days[t].date === todayKey) {
        ctx.fillStyle = todayBg;
        ctx.fillRect(_HOUR_LABEL_WIDTH + t * colWidth, 0, colWidth, H);
      }
    }

    // --- Header row: day labels ---
    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    var dayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    for (var i = 0; i < days; i++) {
      var colX = _HOUR_LABEL_WIDTH + i * colWidth;
      var day = new Date(data.days[i].date + "T00:00:00");
      ctx.fillStyle = textPrimary;
      ctx.font = "bold 13px sans-serif";
      ctx.textAlign = "center";
      var label =
        days === 7
          ? dayNames[day.getDay()] + " " + day.getDate()
          : day.toLocaleDateString(undefined, {
              weekday: "long",
              month: "short",
              day: "numeric",
            });
      ctx.fillText(label, colX + colWidth / 2, headerY + 20);
    }
    ctx.textAlign = "left";

    // Header underline.
    ctx.beginPath();
    ctx.moveTo(0, _GRID_HEADER_HEIGHT);
    ctx.lineTo(W, _GRID_HEADER_HEIGHT);
    ctx.stroke();

    // Row separators — only when the row actually exists.
    if (layout.allDayRowH > 0) {
      ctx.beginPath();
      ctx.moveTo(0, allDayY + layout.allDayRowH);
      ctx.lineTo(W, allDayY + layout.allDayRowH);
      ctx.stroke();
    }
    if (layout.markerRowH > 0) {
      ctx.beginPath();
      ctx.moveTo(0, markerY + layout.markerRowH);
      ctx.lineTo(W, markerY + layout.markerRowH);
      ctx.stroke();
    }

    // Vertical grid lines between day columns.
    for (var v = 0; v <= days; v++) {
      var vx = _HOUR_LABEL_WIDTH + v * colWidth;
      ctx.beginPath();
      ctx.moveTo(vx, _GRID_HEADER_HEIGHT);
      ctx.lineTo(vx, H);
      ctx.stroke();
    }

    // --- All-day chips + markers ---
    canvas._hitRects = [];

    var chipSlot = _CHIP_HEIGHT + _CHIP_SPACING;
    for (var d = 0; d < days; d++) {
      var dayData = data.days[d];
      var colX2 = _HOUR_LABEL_WIDTH + d * colWidth;
      var allDaySlot = 0;
      var markerSlot = 0;

      dayData.segments.forEach(function (seg) {
        var item = data.items[seg.item_id];
        if (!item) return;

        if (seg.is_all_day) {
          var y = allDayY + _ROW_PADDING / 2 + allDaySlot * chipSlot;
          _paintAllDayChip(
            ctx,
            canvas._hitRects,
            item,
            seg,
            colX2 + 2,
            y,
            colWidth - 4,
          );
          allDaySlot++;
        } else if (seg.is_marker) {
          var ym = markerY + _ROW_PADDING / 2 + markerSlot * chipSlot;
          _paintMarkerChip(
            ctx,
            canvas._hitRects,
            item,
            seg,
            colX2 + 2,
            ym,
            colWidth - 4,
          );
          markerSlot++;
        }
      });
    }
  }

  function _paintHoursZone(canvas, data, layout) {
    var ctx = canvas.getContext("2d");
    ctx.setTransform(layout.ratio, 0, 0, layout.ratio, 0, 0);
    var W = layout.W;
    var H = layout.hoursH;
    ctx.clearRect(0, 0, W, H);

    var border = _themeColor("border", "#e0e0e0");
    var textSecondary = _themeColor("text-secondary", "#888");
    var bgCard = _themeColor("bg-card", "#fff");
    var todayBg = _themeColor("accent-subtle", "rgba(33,150,243,0.08)");

    var colWidth = layout.colWidth;
    var days = layout.days;
    var todayKey = layout.todayKey;

    ctx.fillStyle = bgCard;
    ctx.fillRect(0, 0, W, H);

    // Today-column tint inside the hours zone.
    for (var t = 0; t < days; t++) {
      if (data.days[t].date === todayKey) {
        ctx.fillStyle = todayBg;
        ctx.fillRect(_HOUR_LABEL_WIDTH + t * colWidth, 0, colWidth, H);
      }
    }

    // Horizontal hour lines + hour labels.
    ctx.fillStyle = textSecondary;
    ctx.font = "10px sans-serif";
    ctx.strokeStyle = border;
    for (var h = 0; h < 24; h++) {
      var y = h * _HOUR_ROW_HEIGHT;
      ctx.fillText(
        String(h).padStart(2, "0") + ":00",
        6,
        y + _HOUR_ROW_HEIGHT / 2 + 3,
      );
      if (h > 0) {
        ctx.beginPath();
        ctx.moveTo(_HOUR_LABEL_WIDTH, y);
        ctx.lineTo(W, y);
        ctx.stroke();
      }
    }

    // Vertical grid lines between day columns.
    for (var v = 0; v <= days; v++) {
      var vx = _HOUR_LABEL_WIDTH + v * colWidth;
      ctx.beginPath();
      ctx.moveTo(vx, 0);
      ctx.lineTo(vx, H);
      ctx.stroke();
    }

    // --- Paint hour-grid bars per day ---
    canvas._hitRects = [];

    for (var d = 0; d < days; d++) {
      var dayData = data.days[d];
      var colX = _HOUR_LABEL_WIDTH + d * colWidth;

      dayData.segments.forEach(function (seg) {
        if (seg.is_marker || seg.is_all_day) return;
        var item = data.items[seg.item_id];
        if (!item) return;

        var segTopY = (seg.start_minute / 60) * _HOUR_ROW_HEIGHT;
        var segBottomY = (seg.end_minute / 60) * _HOUR_ROW_HEIGHT;
        var segH = Math.max(segBottomY - segTopY, 3);
        var segX = colX + 2;
        var segW = colWidth - 4;

        _paintHourBar(
          ctx,
          canvas._hitRects,
          item,
          seg,
          segX,
          segTopY,
          segW,
          segH,
        );
      });
    }
  }

  // A canvas used to read a colour in one form, whatever form the
  // style sheet gives it in.
  var _colorProbe = document.createElement("canvas").getContext("2d");

  // The relative luminance of a colour, as WCAG defines it: 0 for
  // black, 1 for white. null for a colour that is not opaque or cannot
  // be read.
  function _luminance(color) {
    _colorProbe.fillStyle = "#000000";
    _colorProbe.fillStyle = color;
    var match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(
      _colorProbe.fillStyle,
    );
    if (!match) return null;
    var parts = [1, 2, 3].map(function (n) {
      var c = parseInt(match[n], 16) / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2];
  }

  // The colour of text written on a filled bar or chip: black or
  // white, whichever stands out more from the fill by WCAG's contrast
  // ratio. One of the two always reaches the 4.5:1 asked of text; the
  // worst fill, of middling lightness, gives 4.58:1 to both.
  //
  // The page's own text colour does not: it is chosen for the page's
  // background, and the bars are light in the dark theme and saturated
  // in the light one. On the dark theme's bars it measured 1.1:1 to
  // 2.1:1, and on four of the light theme's six, under 4.5:1.
  function _barTextColor(fill) {
    var lum = _luminance(fill);
    if (lum === null) return _themeColor("text", "#333");
    var onWhite = 1.05 / (lum + 0.05);
    var onBlack = (lum + 0.05) / 0.05;
    return onWhite >= onBlack ? "#ffffff" : "#000000";
  }

  // Writes a label on a fill, in the colour that fill calls for, and
  // only inside the fill's own rectangle. A bar of two colours has its
  // label written once for each, so that every part of it is on the
  // colour it was chosen for.
  function _paintLabelOn(ctx, text, tx, ty, zone) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(zone.x, zone.y, zone.w, zone.h);
    ctx.clip();
    ctx.fillStyle = _barTextColor(zone.fill);
    ctx.fillText(text, tx, ty);
    ctx.restore();
  }

  function _paintHourBar(ctx, hitRects, item, seg, x, y, w, h) {
    var base = _paletteColor(seg.state);
    var deviation = _paletteDeviation(seg.state);
    var labelColor = _barTextColor(base);
    // The parts of the bar by colour, for its label.
    var zones = [{ x: x, y: y, w: w, h: h, fill: base }];

    // Two-zone overlay for completed bars: base color for the
    // relevant span, deviation color for the surplus or overflow.
    // Zone boundary math uses the item's full bar window (ms
    // timestamps) mapped back into this cell's start_minute/end_minute
    // coordinate system — the server-computed fractions stay exact
    // when the bar is fully within one day.
    var paintedTwoZone = false;
    if (
      (seg.state === "completed_early" || seg.state === "completed_late") &&
      item.completed_at != null &&
      item.bar_origin_ms != null &&
      item.bar_end_ms != null
    ) {
      var origin = item.bar_origin_ms;
      var end = item.bar_end_ms;
      var completed = item.completed_at;
      var totalSpan = end - origin;
      if (totalSpan > 0) {
        if (seg.state === "completed_early" && completed < end) {
          var frac = Math.max(0, Math.min(1, (completed - origin) / totalSpan));
          var splitX = x + frac * w;
          ctx.fillStyle = base;
          ctx.fillRect(x, y, splitX - x, h);
          ctx.fillStyle = deviation;
          ctx.fillRect(splitX, y, x + w - splitX, h);
          zones = [
            { x: x, y: y, w: splitX - x, h: h, fill: base },
            { x: splitX, y: y, w: x + w - splitX, h: h, fill: deviation },
          ];
          paintedTwoZone = true;
        } else if (seg.state === "completed_late" && completed > end) {
          // Planned span fills the bar; overflow can't be drawn
          // inside this cell (it's on a later day's marker row),
          // so we paint the base color across the whole cell and
          // let the marker on the completion day carry the overflow.
          ctx.fillStyle = base;
          ctx.fillRect(x, y, w, h);
          paintedTwoZone = true;
        }
      }
    }
    if (!paintedTwoZone) {
      ctx.fillStyle = base;
      ctx.fillRect(x, y, w, h);
    }

    // Clipped-edge marks for multi-day bars: a thin contrasting
    // stripe at the clipped edge communicates "continues off-screen".
    if (seg.clipped_top) {
      ctx.fillStyle = labelColor;
      ctx.globalAlpha = 0.4;
      ctx.fillRect(x, y, w, 2);
      ctx.globalAlpha = 1;
    }
    if (seg.clipped_bottom) {
      ctx.fillStyle = labelColor;
      ctx.globalAlpha = 0.4;
      ctx.fillRect(x, y + h - 2, w, 2);
      ctx.globalAlpha = 1;
    }

    // Label — only when the bar is tall enough for text to fit.
    if (h >= 14) {
      ctx.font = "11px sans-serif";
      var text = (item.reminder || "").substring(0, Math.floor(w / 7));
      zones.forEach(function (zone) {
        _paintLabelOn(ctx, text, x + 4, y + 12, zone);
      });
    }

    hitRects.push({ x: x, y: y, w: w, h: h, item_id: seg.item_id });
  }

  function _paintAllDayChip(ctx, hitRects, item, seg, x, y, w) {
    var h = _CHIP_HEIGHT;
    var color = _paletteColor(seg.state);

    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);

    ctx.font = "11px sans-serif";
    var text = (item.reminder || "").substring(0, Math.floor(w / 7));
    _paintLabelOn(ctx, text, x + 4, y + h - 6, {
      x: x,
      y: y,
      w: w,
      h: h,
      fill: color,
    });

    hitRects.push({ x: x, y: y, w: w, h: h, item_id: seg.item_id });
  }

  function _paintMarkerChip(ctx, hitRects, item, seg, x, y, w) {
    var h = _CHIP_HEIGHT;
    var color = _paletteColor(seg.state);
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);

    ctx.font = "bold 10px sans-serif";
    var text = seg.marker_label || (item.reminder || "").substring(0, 14);
    _paintLabelOn(ctx, text, x + 4, y + h - 5, {
      x: x,
      y: y,
      w: w,
      h: h,
      fill: color,
    });

    hitRects.push({ x: x, y: y, w: w, h: h, item_id: seg.item_id });
  }

  function _installHourGridClickHandler(canvas) {
    canvas.addEventListener("click", function (e) {
      // In the units the bars were painted in.
      var rect = canvas.getBoundingClientRect();
      var scaleX = canvas._unitWidth / rect.width;
      var scaleY = canvas._unitHeight / rect.height;
      var x = (e.clientX - rect.left) * scaleX;
      var y = (e.clientY - rect.top) * scaleY;
      var hits = canvas._hitRects || [];
      // Iterate newest-first so overlapping segments favor the last
      // painted one (typically the most specific).
      for (var i = hits.length - 1; i >= 0; i--) {
        var r = hits[i];
        if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) {
          location.hash = "#/item/" + r.item_id;
          return;
        }
      }
    });
  }

  function _escHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Timeline charts (Canvas 2D)
  // ====================================================================

  function renderTimelineView() {
    calContainer.innerHTML = "";
    calTitle.textContent = "Timeline";
    var items = _calItems();

    var wrap = document.createElement("div");
    wrap.className = "timeline-charts";

    // Gantt chart — tasks with a scheduled bar
    wrap.appendChild(_chartGantt(items));
    // Daily activity — completed items per day (30 days)
    wrap.appendChild(_chartDailyActivity(items));
    // Time block distribution — items per time block
    wrap.appendChild(_chartTimeBlocks(items));
    // Estimate accuracy — estimated vs actual
    wrap.appendChild(_chartAccuracy(items));

    // Completion timing — async, populated from analytics endpoints.
    // The canvas is appended immediately so layout doesn't jump when
    // the data lands; the render call fills in bars and title once
    // the fetch resolves.
    var timingChart = _chartCanvas("Completion Timing", 700, 140);
    timingChart.container
      .querySelector("h3")
      .appendChild(_metricInfoButton(_TIMING_INFO_HTML));
    wrap.appendChild(timingChart.container);
    _loadCompletionTiming(timingChart);

    // Cycle time stat row — mean / median / p90 of completed-task
    // created-to-completed durations. Rendered as a single text row
    // rather than a chart because the underlying data is scalar.
    var cycleRow = document.createElement("div");
    cycleRow.className = "timeline-stat-row";
    var cycleText = document.createElement("span");
    cycleText.textContent = "Cycle time — loading\u2026";
    cycleRow.appendChild(cycleText);
    cycleRow.appendChild(_metricInfoButton(_CYCLE_INFO_HTML));
    wrap.appendChild(cycleRow);
    _loadCycleTime(cycleText);

    calContainer.appendChild(wrap);
  }

  async function _loadCompletionTiming(chart) {
    try {
      var results = await Promise.all([
        api("/analytics/completion_timing" + _listQuery("?")),
        api("/analytics/slip_rate" + _listQuery("?")),
      ]);
      _renderCompletionTiming(chart, results[0], results[1]);
    } catch (e) {
      _renderAnalyticsUnavailable(chart, "Completion Timing");
    }
  }

  function _renderCompletionTiming(chart, timing, slip) {
    var ctx = chart.ctx;
    var W = chart.canvas.width;
    var H = chart.canvas.height;
    ctx.clearRect(0, 0, W, H);

    var rootStyle = getComputedStyle(document.documentElement);
    var labelColor = rootStyle.getPropertyValue("--text").trim() || "#333";
    var mutedColor =
      rootStyle.getPropertyValue("--text-secondary").trim() || "#888";

    if (chart.titleSpan) {
      if (slip && slip.rate != null) {
        chart.titleSpan.textContent =
          "Completion Timing \u2014 slip rate " +
          Math.round(slip.rate * 100) +
          "%";
      } else {
        chart.titleSpan.textContent = "Completion Timing";
      }
    }

    if (!timing || timing.total === 0) {
      ctx.fillStyle = mutedColor;
      ctx.font = "13px sans-serif";
      ctx.fillText("No completed tasks in range", 20, H / 2);
      return;
    }

    var rows = [
      {
        label: "Early",
        count: timing.early_count,
        color: rootStyle.getPropertyValue("--bar-completed-early").trim(),
      },
      {
        label: "On time",
        count: timing.ontime_count,
        color: rootStyle.getPropertyValue("--bar-completed-ontime").trim(),
      },
      {
        label: "Late",
        count: timing.late_count,
        color: rootStyle.getPropertyValue("--bar-completed-late").trim(),
      },
    ];
    var classifiable =
      timing.early_count + timing.ontime_count + timing.late_count;
    var maxCount = Math.max(classifiable, 1);
    var barH = 22;
    var labelW = 80;
    var valueW = 50;
    var chartW = W - labelW - valueW - 20;

    rows.forEach(function (row, idx) {
      var y = 20 + idx * (barH + 8);
      var frac = row.count / maxCount;
      ctx.fillStyle = labelColor;
      ctx.font = "13px sans-serif";
      ctx.fillText(row.label, 10, y + barH - 6);
      ctx.fillStyle = row.color || mutedColor;
      ctx.fillRect(labelW, y, Math.max(frac * chartW, row.count > 0 ? 3 : 0), barH);
      ctx.fillStyle = labelColor;
      ctx.fillText(String(row.count), labelW + chartW + 5, y + barH - 6);
    });

    if (timing.unknown_count > 0) {
      ctx.fillStyle = mutedColor;
      ctx.font = "11px sans-serif";
      ctx.fillText(
        "(" + timing.unknown_count + " completed without timestamp)",
        10,
        H - 6,
      );
    }
  }

  async function _loadCycleTime(row) {
    try {
      var data = await api("/analytics/cycle_time" + _listQuery("?"));
      _renderCycleTime(row, data);
    } catch (e) {
      row.textContent = "Cycle time unavailable";
    }
  }

  function _renderCycleTime(row, data) {
    if (!data || data.count === 0 || data.mean_minutes == null) {
      row.textContent = "Cycle time \u2014 no data yet";
      return;
    }
    var mean = _formatDurationMinutes(data.mean_minutes);
    var median = _formatDurationMinutes(data.median_minutes);
    var p90 = _formatDurationMinutes(data.p90_minutes);
    row.textContent =
      "Cycle time \u2014 mean " +
      mean +
      ", median " +
      median +
      ", p90 " +
      p90 +
      " (over " +
      data.count +
      " tasks)";
  }

  function _formatDurationMinutes(m) {
    if (m == null) return "\u2014";
    if (m < 60) return Math.round(m) + "m";
    if (m < 1440) return (m / 60).toFixed(1) + "h";
    return (m / 1440).toFixed(1) + "d";
  }

  function _renderAnalyticsUnavailable(chart, title) {
    var ctx = chart.ctx;
    var W = chart.canvas.width;
    var H = chart.canvas.height;
    ctx.clearRect(0, 0, W, H);
    var mutedColor =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--text-secondary")
        .trim() || "#888";
    ctx.fillStyle = mutedColor;
    ctx.font = "13px sans-serif";
    ctx.fillText(title + " unavailable", 20, H / 2);
  }

  function _chartCanvas(title, width, height) {
    var div = document.createElement("div");
    div.className = "timeline-chart-box";
    var h3 = document.createElement("h3");
    var titleSpan = document.createElement("span");
    titleSpan.className = "title-text";
    titleSpan.textContent = title;
    h3.appendChild(titleSpan);
    div.appendChild(h3);
    var canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = "100%";
    canvas.style.height = "auto";
    div.appendChild(canvas);
    return {
      container: div,
      canvas: canvas,
      ctx: canvas.getContext("2d"),
      titleSpan: titleSpan,
    };
  }

  // Info-icon popover used by the analytics blocks. Click toggles a
  // floating panel anchored under the icon; click outside dismisses.
  // Mirrors the focus-score popover pattern in the desktop UI.
  var _METRIC_INFO_OPEN = null;
  function _metricInfoButton(htmlText) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "metric-info-btn";
    btn.textContent = "ⓘ";
    btn.setAttribute("aria-label", "What's this?");
    btn.title = "What's this? Click for the full explanation.";
    btn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      if (_METRIC_INFO_OPEN && _METRIC_INFO_OPEN.btn === btn) {
        _closeMetricInfoPopover();
        return;
      }
      _closeMetricInfoPopover();
      var pop = document.createElement("div");
      pop.className = "metric-info-popover";
      pop.innerHTML = htmlText;
      document.body.appendChild(pop);
      var rect = btn.getBoundingClientRect();
      var top = rect.bottom + window.scrollY + 6;
      var maxLeft = window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 8;
      var left = Math.min(rect.left + window.scrollX, maxLeft);
      pop.style.top = top + "px";
      pop.style.left = Math.max(8, left) + "px";
      _METRIC_INFO_OPEN = { btn: btn, pop: pop };
    });
    return btn;
  }

  function _closeMetricInfoPopover() {
    if (_METRIC_INFO_OPEN) {
      _METRIC_INFO_OPEN.pop.remove();
      _METRIC_INFO_OPEN = null;
    }
  }

  document.addEventListener("click", function (ev) {
    if (!_METRIC_INFO_OPEN) return;
    if (_METRIC_INFO_OPEN.pop.contains(ev.target)) return;
    if (_METRIC_INFO_OPEN.btn.contains(ev.target)) return;
    _closeMetricInfoPopover();
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") _closeMetricInfoPopover();
  });

  var _TIMING_INFO_HTML =
    "<b>Completion Timing</b><br/>" +
    "Where completed tasks landed relative to their deadline.<br/><br/>" +
    "<b>Early</b> &nbsp;completed before the deadline<br/>" +
    "<b>On time</b> &nbsp;completed exactly at the deadline<br/>" +
    "<b>Late</b> &nbsp;completed after the deadline<br/><br/>" +
    "The deadline is the task's <code>due_date</code>+<code>due_time</code> " +
    "when set, or end-of-day (next-day midnight) for all-day items.<br/><br/>" +
    "<b>Slip rate</b> = late ÷ (early + on time + late). Tasks completed " +
    "without a recorded timestamp are excluded from both the count and the rate.";

  var _CYCLE_INFO_HTML =
    "<b>Cycle Time</b><br/>" +
    "How long tasks stay open — from creation " +
    "(<code>created_at</code>) to completion (<code>completed_at</code>).<br/><br/>" +
    "<b>Mean</b> &nbsp;arithmetic average across the sample<br/>" +
    "<b>Median</b> &nbsp;middle value (50th percentile); robust to outliers<br/>" +
    "<b>p90</b> &nbsp;90th percentile; 90% of tasks finished at or below " +
    "this duration<br/><br/>" +
    "Only completed tasks with both timestamps are included. Negative " +
    "durations from clock drift or manual edits are excluded.";

  function _chartGantt(items) {
    // Only items that have a temporal window computed server-side
    // (via the core calendar layout rules) are plottable. Items with
    // no due date ship all four bar fields as null and are filtered
    // here.
    var dueItems = items.filter(function (i) {
      return i.bar_origin_ms != null && i.bar_end_ms != null;
    });
    dueItems.sort(function (a, b) {
      return a.bar_origin_ms - b.bar_origin_ms;
    });
    dueItems = dueItems.slice(0, 20);

    var barH = 22;
    var labelW = 140;
    var W = 700;
    var H = Math.max(100, dueItems.length * (barH + 4) + 40);
    var ch = _chartCanvas("Tasks / Gantt", W, H);
    var ctx = ch.ctx;

    var rootStyle = getComputedStyle(document.documentElement);
    var textColor =
      rootStyle.getPropertyValue("--text-secondary").trim() || "#888";

    if (dueItems.length === 0) {
      ctx.fillStyle = textColor;
      ctx.font = "13px sans-serif";
      ctx.fillText("No items with a scheduled bar", 20, 30);
      return ch.container;
    }

    // Look up the base and deviation colors for a lifecycle state.
    // The CSS variable names use dashes (--bar-in-work-window) while
    // the enum values use underscores (in_work_window).
    function palette(state) {
      var key = (state || "future").replace(/_/g, "-");
      var base = rootStyle.getPropertyValue("--bar-" + key).trim();
      var dev = rootStyle.getPropertyValue("--bar-" + key + "-deviation").trim();
      return {
        base: base || "#60a5fa",
        deviation: dev || base || "#60a5fa",
      };
    }

    // Chart extent needs to include post-deadline completion time
    // for late completions, otherwise the overflow zone gets clipped
    // off the right edge.
    var minMs = Infinity;
    var maxMs = -Infinity;
    dueItems.forEach(function (item) {
      if (item.bar_origin_ms < minMs) minMs = item.bar_origin_ms;
      var endExtent = item.bar_end_ms;
      if (item.bar_state === "completed_late" && item.completed_at != null) {
        endExtent = Math.max(endExtent, item.completed_at);
      }
      if (endExtent > maxMs) maxMs = endExtent;
    });
    var rangeMs = Math.max(maxMs - minMs, 86_400_000);
    var chartW = W - labelW - 20;

    function xPos(ms) {
      return labelW + ((ms - minMs) / rangeMs) * chartW;
    }

    var labelColor = rootStyle.getPropertyValue("--text").trim() || "#333";

    dueItems.forEach(function (item, idx) {
      var y = idx * (barH + 4) + 10;
      var colors = palette(item.bar_state);
      var origin = item.bar_origin_ms;
      var end = item.bar_end_ms;
      var x1 = xPos(origin);
      var xEnd = xPos(end);

      if (
        item.bar_state === "completed_early" &&
        item.completed_at != null
      ) {
        // Actual work from origin to completed_at, then a translucent
        // deviation zone for the unused planned span running to the
        // original deadline.
        var xMidE = xPos(item.completed_at);
        ctx.fillStyle = colors.base;
        ctx.fillRect(x1, y, Math.max(xMidE - x1, 2), barH);
        ctx.fillStyle = colors.deviation;
        ctx.fillRect(xMidE, y, Math.max(xEnd - xMidE, 2), barH);
      } else if (
        item.bar_state === "completed_late" &&
        item.completed_at != null
      ) {
        // Planned span in base, overflow past the deadline in
        // deviation to communicate that the task ran long.
        var xOverflow = xPos(item.completed_at);
        ctx.fillStyle = colors.base;
        ctx.fillRect(x1, y, Math.max(xEnd - x1, 2), barH);
        ctx.fillStyle = colors.deviation;
        ctx.fillRect(xEnd, y, Math.max(xOverflow - xEnd, 2), barH);
      } else {
        ctx.fillStyle = colors.base;
        ctx.fillRect(x1, y, Math.max(xEnd - x1, 3), barH);
      }

      ctx.fillStyle = labelColor;
      ctx.font = "11px sans-serif";
      var label = (item.reminder || "").substring(0, 18);
      ctx.fillText(label, 4, y + barH - 6);
    });
    return ch.container;
  }

  function _chartDailyActivity(items) {
    var W = 700;
    var H = 200;
    var ch = _chartCanvas("Daily Activity (30 days)", W, H);
    var ctx = ch.ctx;

    var now = new Date();
    var days = 30;
    var buckets = {};
    for (var d = 0; d < days; d++) {
      var dt = new Date(now);
      dt.setDate(dt.getDate() - (days - 1 - d));
      buckets[_dayKey(dt)] = { high: 0, normal: 0, low: 0 };
    }

    items.forEach(function (i) {
      if (!i.complete) return;
      // Prefer the real completion timestamp when it's available.
      // Tasks completed before schema v19 fall back to the last
      // update time so they still contribute to the historical
      // trend; tasks without any timestamp are skipped rather than
      // guessed.
      var ts = i.completed_at || i.updated_at;
      if (!ts) return;
      var key = new Date(ts).toISOString().substring(0, 10);
      if (buckets[key] !== undefined) {
        if (i.priority === 1) buckets[key].high++;
        else if (i.priority === 3) buckets[key].low++;
        else buckets[key].normal++;
      }
    });

    var keys = Object.keys(buckets).sort();
    var maxVal = 1;
    keys.forEach(function (k) {
      var t = buckets[k].high + buckets[k].normal + buckets[k].low;
      if (t > maxVal) maxVal = t;
    });

    var barW = Math.floor((W - 60) / keys.length);
    var chartH = H - 40;
    keys.forEach(function (k, idx) {
      var x = 40 + idx * barW;
      var b = buckets[k];
      var total = b.high + b.normal + b.low;
      var h = (total / maxVal) * chartH;

      var y = H - 20 - h;
      var seg = 0;
      if (b.high > 0) {
        var sh = (b.high / total) * h;
        ctx.fillStyle = "#ef4444";
        ctx.fillRect(x + 1, y + seg, barW - 2, sh);
        seg += sh;
      }
      if (b.normal > 0) {
        var sn = (b.normal / total) * h;
        ctx.fillStyle = "#3b82f6";
        ctx.fillRect(x + 1, y + seg, barW - 2, sn);
        seg += sn;
      }
      if (b.low > 0) {
        var sl = (b.low / total) * h;
        ctx.fillStyle = "#10b981";
        ctx.fillRect(x + 1, y + seg, barW - 2, sl);
      }

      if (idx % 5 === 0) {
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary") || "#888";
        ctx.font = "9px sans-serif";
        ctx.fillText(k.substring(5), x, H - 5);
      }
    });
    return ch.container;
  }

  function _chartTimeBlocks(items) {
    var W = 700;
    var H = 180;
    var ch = _chartCanvas("Time Block Distribution", W, H);
    var ctx = ch.ctx;

    var blocks = [
      "early_morning", "morning", "late_morning", "noon",
      "early_afternoon", "afternoon", "late_afternoon",
      "early_evening", "evening", "late_evening",
      "night", "late_night",
    ];
    var labels = [
      "Early AM", "Morning", "Late AM", "Noon",
      "Early PM", "Afternoon", "Late PM",
      "Early Eve", "Evening", "Late Eve",
      "Night", "Late Night",
    ];
    var counts = {};
    blocks.forEach(function (b) { counts[b] = 0; });

    items.forEach(function (i) {
      var block = i.effective_time_block;
      if (block && counts[block] !== undefined) {
        counts[block]++;
      }
    });

    var maxVal = 1;
    blocks.forEach(function (b) { if (counts[b] > maxVal) maxVal = counts[b]; });

    var barW = Math.floor((W - 60) / blocks.length);
    var chartH = H - 40;
    var gradient = ["#1e3a5f", "#1e4d7a", "#2563a0", "#3b82f6", "#60a5fa", "#93c5fd",
                    "#fbbf24", "#f59e0b", "#d97706", "#7c3aed", "#4c1d95", "#1e1b4b"];

    blocks.forEach(function (b, idx) {
      var x = 40 + idx * barW;
      var h = (counts[b] / maxVal) * chartH;
      ctx.fillStyle = gradient[idx];
      ctx.fillRect(x + 1, H - 20 - h, barW - 2, h);

      ctx.save();
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary") || "#888";
      ctx.font = "8px sans-serif";
      ctx.translate(x + barW / 2, H - 5);
      ctx.rotate(-Math.PI / 4);
      ctx.fillText(labels[idx], 0, 0);
      ctx.restore();
    });
    return ch.container;
  }

  function _chartAccuracy(items) {
    var W = 400;
    var H = 400;
    var ch = _chartCanvas("Estimate Accuracy", W, H);
    var ctx = ch.ctx;

    var pts = [];
    items.forEach(function (i) {
      if (i.estimated_minutes > 0 && i.time_spent > 0) {
        pts.push({ est: i.estimated_minutes, actual: i.time_spent / 60 });
      }
    });

    if (pts.length === 0) {
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary") || "#888";
      ctx.font = "13px sans-serif";
      ctx.fillText("No items with both estimate and tracked time", 20, 30);
      return ch.container;
    }

    var maxVal = 1;
    pts.forEach(function (p) {
      if (p.est > maxVal) maxVal = p.est;
      if (p.actual > maxVal) maxVal = p.actual;
    });
    maxVal = Math.ceil(maxVal * 1.1);

    var pad = 50;
    var cW = W - pad * 2;
    var cH = H - pad * 2;

    // Reference line (perfect accuracy)
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue("--border") || "#ccc";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(pad, H - pad);
    ctx.lineTo(pad + cW, H - pad - cH);
    ctx.stroke();
    ctx.setLineDash([]);

    // Points
    pts.forEach(function (p) {
      var x = pad + (p.est / maxVal) * cW;
      var y = H - pad - (p.actual / maxVal) * cH;
      ctx.fillStyle = p.actual > p.est ? "#ef4444" : "#10b981";
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
    });

    // Axis labels
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--text-secondary") || "#888";
    ctx.font = "11px sans-serif";
    ctx.fillText("Estimated (min)", W / 2 - 40, H - 8);
    ctx.save();
    ctx.translate(12, H / 2 + 30);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Actual (min)", 0, 0);
    ctx.restore();

    return ch.container;
  }

  // Smart add sheet
  // ====================================================================

  function openAddSheet() {
    if (!addSheet) return;
    addInput.value = "";
    if (addEntities) addEntities.innerHTML = "";
    // Sync list selector
    if (addListSelect) {
      addListSelect.innerHTML = "";
      cachedLists.forEach(function (lst) {
        var opt = document.createElement("option");
        opt.value = lst.id;
        opt.textContent = lst.name;
        if (lst.id === currentListId) opt.selected = true;
        addListSelect.appendChild(opt);
      });
    }
    addSheet.classList.remove("hidden");
    trapFocus(addSheet);
    addInput.focus();
  }

  function closeAddSheet() {
    animateSheetClose(addSheet);
  }

  if (addSheetClose) addSheetClose.addEventListener("click", closeAddSheet);
  if (addSheet) {
    addSheet
      .querySelector(".sheet-backdrop")
      .addEventListener("click", closeAddSheet);
  }

  // NLP preview debounce
  if (addInput) {
    addInput.addEventListener("input", function () {
      clearTimeout(parseDebounceTimer);
      var text = addInput.value.trim();
      if (!text) {
        if (addEntities) addEntities.innerHTML = "";
        return;
      }
      parseDebounceTimer = setTimeout(async function () {
        try {
          var result = await api("/parse", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: text }),
          });
          renderEntityChips(result);
        } catch (e) {
          // Parsing preview is best-effort
        }
      }, 300);
    });

    // Single-line: Enter submits, Shift+Enter for newline
    addInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        addForm.dispatchEvent(new Event("submit"));
      }
    });
  }

  function renderEntityChips(parseResult) {
    if (!addEntities) return;
    addEntities.innerHTML = "";
    if (!parseResult.spans || parseResult.spans.length === 0) return;

    parseResult.spans.forEach(function (span) {
      var chip = document.createElement("span");
      chip.className = "entity-chip " + span.kind;
      chip.textContent = span.display;
      addEntities.appendChild(chip);
    });
  }

  if (addForm) {
    addForm.addEventListener("submit", async function (e) {
      e.preventDefault();
      var text = addInput.value.trim();
      var targetList = addListSelect ? addListSelect.value : currentListId;
      if (!text || !targetList) return;

      var path = "/lists/" + targetList + "/items";
      var body = { reminder: text, parse_nlp: true };
      var opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };

      // A refused task stays in the sheet, to be corrected.
      var outcome = await sendOrQueue(path, opts);
      if (outcome === "sent") {
        closeAddSheet();
        await refreshCurrentList();
        showToast("Task added");
      } else if (outcome === "queued") {
        closeAddSheet();
        showToast("Added (offline)");
      }
    });
  }

  // ====================================================================
  // Item detail sheet
  // ====================================================================

  function openDetailSheet(itemId) {
    if (!detailSheet || !detailBody) return;
    // Find item in cache
    var item = null;
    for (var i = 0; i < cachedItems.length; i++) {
      if (cachedItems[i].id === itemId) {
        item = cachedItems[i];
        break;
      }
    }
    if (!item) {
      // Not a task of the chosen list: deleted a moment ago elsewhere,
      // or an address kept from another list. Saying nothing left a tap
      // without effect, and the address in place, so that a second tap
      // on the same task was not a change of address at all.
      detailSheet.classList.add("hidden");
      if (location.hash.startsWith("#/item/")) location.hash = "#/";
      if (appReady) showToast("That task is not in this list");
      return;
    }

    detailBody.innerHTML = "";

    // Completion toggle
    var statusDiv = document.createElement("div");
    statusDiv.className = "detail-field";
    var statusLabel = document.createElement("label");
    statusLabel.textContent = "Status";
    statusDiv.appendChild(statusLabel);
    var statusBtn = document.createElement("button");
    statusBtn.type = "button";
    statusBtn.className = "btn-toggle " + (item.complete ? "done" : "active");
    statusBtn.textContent = item.complete
      ? "\u2713 Completed"
      : "Mark Complete";
    statusBtn.addEventListener("click", async function () {
      await onToggle(itemId);
      // Re-open with updated data
      for (var j = 0; j < cachedItems.length; j++) {
        if (cachedItems[j].id === itemId) {
          openDetailSheet(itemId);
          break;
        }
      }
    });
    statusDiv.appendChild(statusBtn);
    detailBody.appendChild(statusDiv);

    // Completion timestamp — read-only, only shown when set.
    // The timestamp is managed automatically by the toggle path
    // (set on completion, cleared on un-completion), so the UI
    // displays it for transparency rather than offering it as an
    // editable field.
    if (item.completed_at) {
      var completedDiv = document.createElement("div");
      completedDiv.className = "detail-field";
      var completedLabel = document.createElement("label");
      completedLabel.textContent = "Completed";
      completedDiv.appendChild(completedLabel);
      var completedValue = document.createElement("div");
      completedValue.className = "detail-readonly";
      completedValue.textContent = new Date(item.completed_at).toLocaleString();
      completedDiv.appendChild(completedValue);
      detailBody.appendChild(completedDiv);
    }

    // Reminder
    var reminderField = makeField(
      "Task",
      "textarea",
      item.reminder,
      function (val) {
        saveItemField(itemId, { reminder: val });
      },
    );
    detailBody.appendChild(reminderField);

    // Priority
    var prioDiv = document.createElement("div");
    prioDiv.className = "detail-field";
    var prioLabel = document.createElement("label");
    prioLabel.textContent = "Priority";
    prioDiv.appendChild(prioLabel);
    var prioBtns = document.createElement("div");
    prioBtns.className = "detail-priority-btns";
    [
      { label: "High", value: 1, cls: "active-high" },
      { label: "Normal", value: 2, cls: "active-normal" },
      { label: "Low", value: 3, cls: "active-low" },
    ].forEach(function (p) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = p.label;
      if (item.priority === p.value) btn.classList.add(p.cls);
      btn.addEventListener("click", function () {
        prioBtns.querySelectorAll("button").forEach(function (b) {
          b.className = "";
        });
        btn.classList.add(p.cls);
        saveItemField(itemId, { priority: p.value });
      });
      prioBtns.appendChild(btn);
    });
    prioDiv.appendChild(prioBtns);
    detailBody.appendChild(prioDiv);

    // Due date
    detailBody.appendChild(
      makeField("Due Date", "date", item.due_date || "", function (val) {
        saveItemField(itemId, { due_date: val || null });
        remindAhead.setHasDueDate(Boolean(val));
      }),
    );

    // Due time
    detailBody.appendChild(
      makeField(
        "Due Time",
        "time",
        item.due_time ? item.due_time.substring(0, 5) : "",
        function (val) {
          saveItemField(itemId, { due_time: val ? val + ":00" : null });
        },
      ),
    );

    // Remind ahead. It counts back from the due date, so it sits with
    // the date and is told when the date above is set or cleared.
    var remindAhead = makeRemindAhead(item, function (days, cadence) {
      saveItemField(itemId, {
        remind_before_days: days,
        reminder_cadence: cadence,
      });
    });
    detailBody.appendChild(remindAhead.element);

    // Tags
    detailBody.appendChild(
      makeField("Tags", "text", (item.tags || []).join(", "), function (val) {
        var tags = val
          .split(",")
          .map(function (t) {
            return t.trim();
          })
          .filter(Boolean);
        saveItemField(itemId, { tags: tags });
      }),
    );

    // Board column
    if (
      cachedBoardData &&
      cachedBoardData.board_columns &&
      cachedBoardData.board_columns.length > 0
    ) {
      var colField = document.createElement("div");
      colField.className = "detail-field";
      var colLabel = document.createElement("label");
      colLabel.textContent = "Board Column";
      colField.appendChild(colLabel);
      var colSelect = document.createElement("select");
      cachedBoardData.board_columns.forEach(function (col) {
        var opt = document.createElement("option");
        opt.value = col;
        opt.textContent = col;
        if (item.board_column === col) opt.selected = true;
        colSelect.appendChild(opt);
      });
      colSelect.addEventListener("change", function () {
        saveItemField(itemId, { board_column: colSelect.value });
      });
      colField.appendChild(colSelect);
      detailBody.appendChild(colField);
    }

    // Recurrence
    var recDiv = document.createElement("div");
    recDiv.className = "detail-field";
    var recLabel = document.createElement("label");
    recLabel.textContent = "Recurrence";
    recDiv.appendChild(recLabel);
    var recRow = document.createElement("div");
    recRow.className = "detail-recurrence-row";
    var recTypeSelect = document.createElement("select");
    [
      { label: "None", value: "" },
      { label: "Minutes", value: "minutely" },
      { label: "Daily", value: "daily" },
      { label: "Weekly", value: "weekly" },
      { label: "Monthly", value: "monthly" },
      { label: "Yearly", value: "yearly" },
    ].forEach(function (opt) {
      var o = document.createElement("option");
      o.value = opt.value;
      o.textContent = opt.label;
      if ((item.recurrence_type || "") === opt.value) o.selected = true;
      recTypeSelect.appendChild(o);
    });
    recRow.appendChild(recTypeSelect);
    var recIntervalInput = document.createElement("input");
    recIntervalInput.type = "number";
    recIntervalInput.min = "1";
    recIntervalInput.value = item.recurrence_interval || 1;
    recIntervalInput.placeholder = "Interval";
    recIntervalInput.style.width = "70px";
    recIntervalInput.classList.toggle("hidden", !item.recurrence_type);
    recRow.appendChild(recIntervalInput);
    recDiv.appendChild(recRow);

    recTypeSelect.addEventListener("change", function () {
      var val = recTypeSelect.value || null;
      recIntervalInput.classList.toggle("hidden", !val);
      saveItemField(itemId, {
        recurrence_type: val,
        recurrence_interval: parseInt(recIntervalInput.value) || 1,
      });
    });
    recIntervalInput.addEventListener("change", function () {
      saveItemField(itemId, {
        recurrence_interval: parseInt(recIntervalInput.value) || 1,
      });
    });

    // Recurrence end conditions (only show if recurring)
    if (item.recurrence_type) {
      var endDiv = document.createElement("div");
      endDiv.className = "detail-recurrence-end";
      endDiv.appendChild(
        makeField(
          "End After (count)",
          "number",
          item.recurrence_end_count || "",
          function (val) {
            saveItemField(itemId, {
              recurrence_end_count: parseInt(val) || null,
            });
          },
        ),
      );
      endDiv.appendChild(
        makeField(
          "End Date",
          "date",
          item.recurrence_end_date || "",
          function (val) {
            saveItemField(itemId, { recurrence_end_date: val || null });
          },
        ),
      );
      if (item.recurrence_count > 0) {
        var countInfo = document.createElement("div");
        countInfo.className = "detail-meta";
        countInfo.textContent =
          item.recurrence_count + " completed occurrences";
        endDiv.appendChild(countInfo);
      }
      recDiv.appendChild(endDiv);
    }
    detailBody.appendChild(recDiv);

    // Estimated pomodoros
    detailBody.appendChild(
      makeField(
        "Pomodoro Estimate",
        "number",
        item.estimated_pomodoros || "",
        function (val) {
          saveItemField(itemId, { estimated_pomodoros: parseInt(val) || 0 });
        },
      ),
    );

    // Pomodoro progress (read-only)
    if (item.pomodoro_count > 0 || item.estimated_pomodoros > 0) {
      var pomInfo = document.createElement("div");
      pomInfo.className = "detail-meta";
      var total = item.pomodoro_count * (item.work_duration || 25);
      pomInfo.textContent =
        item.pomodoro_count + " sessions completed (" + total + " min focused)";
      detailBody.appendChild(pomInfo);
    }

    // --- v18 fields ---

    // Time Block
    var timeBlockOptions = [
      ["", "None"],
      ["early_morning", "Early Morning"],
      ["morning", "Morning"],
      ["late_morning", "Late Morning"],
      ["noon", "Noon"],
      ["early_afternoon", "Early Afternoon"],
      ["afternoon", "Afternoon"],
      ["late_afternoon", "Late Afternoon"],
      ["early_evening", "Early Evening"],
      ["evening", "Evening"],
      ["late_evening", "Late Evening"],
      ["night", "Night"],
      ["late_night", "Late Night"],
      ["midnight", "Midnight"],
    ];
    detailBody.appendChild(
      makeSelect("Time Block", timeBlockOptions, item.due_time_block || "", function (val) {
        saveItemField(itemId, { due_time_block: val || null });
      }),
    );

    // Event Date
    detailBody.appendChild(
      makeField("Event Date", "date", item.event_date || "", function (val) {
        saveItemField(itemId, { event_date: val || null });
      }),
    );

    // Estimated Minutes
    detailBody.appendChild(
      makeField(
        "Estimated Time (minutes)",
        "number",
        item.estimated_minutes || "",
        function (val) {
          saveItemField(itemId, { estimated_minutes: parseInt(val) || 0 });
        },
      ),
    );

    // Work Duration
    detailBody.appendChild(
      makeField(
        "Session Length (min, 0 = default)",
        "number",
        item.work_duration || "",
        function (val) {
          saveItemField(itemId, { work_duration: parseInt(val) || 0 });
        },
      ),
    );

    // Break Duration
    detailBody.appendChild(
      makeField(
        "Break Length (min, 0 = default)",
        "number",
        item.break_duration || "",
        function (val) {
          saveItemField(itemId, { break_duration: parseInt(val) || 0 });
        },
      ),
    );

    // Long Break Duration
    detailBody.appendChild(
      makeField(
        "Long Break (min, 0 = default)",
        "number",
        item.long_break_duration || "",
        function (val) {
          saveItemField(itemId, { long_break_duration: parseInt(val) || 0 });
        },
      ),
    );

    // Conditions (read-only display)
    if (item.conditions && item.conditions.length > 0) {
      var condDiv = document.createElement("div");
      condDiv.className = "detail-field";
      var condLabel = document.createElement("label");
      condLabel.textContent = "Conditions";
      condDiv.appendChild(condLabel);
      var condList = document.createElement("div");
      condList.className = "detail-conditions";
      item.conditions.forEach(function (cond) {
        var chip = document.createElement("span");
        chip.className = "condition-chip";
        chip.textContent = cond.type + ": " + cond.expression;
        condList.appendChild(chip);
      });
      condDiv.appendChild(condList);
      detailBody.appendChild(condDiv);
    }

    // Subtasks
    var subtaskDiv = document.createElement("div");
    subtaskDiv.className = "detail-field";
    var subtaskLabel = document.createElement("label");
    subtaskLabel.textContent = "Subtasks";
    subtaskDiv.appendChild(subtaskLabel);

    var children = cachedItems.filter(function (i) {
      return i.parent_id === itemId;
    });
    if (children.length > 0) {
      var subtaskList = document.createElement("div");
      subtaskList.className = "detail-subtask-list";
      children.forEach(function (child) {
        var row = document.createElement("div");
        row.className =
          "detail-subtask-row" + (child.complete ? " completed" : "");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = child.complete;
        cb.addEventListener("change", function () {
          onToggle(child.id);
        });
        row.appendChild(cb);
        var text = document.createElement("span");
        text.textContent = child.reminder;
        text.addEventListener("click", function () {
          openDetailSheet(child.id);
        });
        row.appendChild(text);
        subtaskList.appendChild(row);
      });
      subtaskDiv.appendChild(subtaskList);
    }

    // Inline add subtask
    var addSubRow = document.createElement("div");
    addSubRow.className = "detail-add-subtask";
    var addSubInput = document.createElement("input");
    addSubInput.type = "text";
    addSubInput.placeholder = "Add subtask...";
    var addSubBtn = document.createElement("button");
    addSubBtn.type = "button";
    addSubBtn.textContent = "+";
    addSubBtn.className = "btn-small";
    addSubBtn.addEventListener("click", async function () {
      var text = addSubInput.value.trim();
      if (!text || !currentListId) return;
      try {
        await api("/lists/" + currentListId + "/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reminder: text, parent_id: itemId }),
        });
        addSubInput.value = "";
        await refreshCurrentList();
        openDetailSheet(itemId);
      } catch (e) {
        showToast("Failed to add subtask");
      }
    });
    addSubInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        addSubBtn.click();
      }
    });
    addSubRow.appendChild(addSubInput);
    addSubRow.appendChild(addSubBtn);
    subtaskDiv.appendChild(addSubRow);

    // Only show subtask section for top-level items
    if (!item.parent_id) {
      detailBody.appendChild(subtaskDiv);
    }

    // Metadata
    var metaDiv = document.createElement("div");
    metaDiv.className = "detail-meta";
    metaDiv.innerHTML =
      "Created: " +
      new Date(item.created_at).toLocaleDateString() +
      "<br>Updated: " +
      new Date(item.updated_at).toLocaleDateString();
    detailBody.appendChild(metaDiv);

    // Save indicator
    var saveInd = document.createElement("div");
    saveInd.className = "detail-save-indicator";
    saveInd.id = "detail-save-indicator";
    detailBody.appendChild(saveInd);

    // Delete button
    var delBtn = document.createElement("button");
    delBtn.className = "detail-delete";
    delBtn.textContent = "Delete Item";
    delBtn.addEventListener("click", function () {
      // The task's row or card, when the list or the board is showing.
      var shown = document.querySelector(
        '.item[data-id="' + itemId + '"], .board-card[data-id="' + itemId + '"]',
      );
      onDelete(itemId, item.reminder, shown);
      closeDetailSheet();
    });
    detailBody.appendChild(delBtn);

    detailSheet.classList.remove("hidden");
    trapFocus(detailSheet);
  }

  function makeField(label, type, value, onChange) {
    var div = document.createElement("div");
    div.className = "detail-field";
    var lbl = document.createElement("label");
    lbl.textContent = label;
    div.appendChild(lbl);

    var input;
    if (type === "textarea") {
      input = document.createElement("textarea");
      input.rows = 2;
    } else {
      input = document.createElement("input");
      input.type = type;
    }
    input.value = value;
    input.addEventListener("change", function () {
      onChange(input.value);
    });
    if (type === "text" || type === "textarea") {
      input.addEventListener("blur", function () {
        onChange(input.value);
      });
    }
    div.appendChild(input);
    return div;
  }

  function makeSelect(label, options, value, onChange) {
    var div = document.createElement("div");
    div.className = "detail-field";
    var lbl = document.createElement("label");
    lbl.textContent = label;
    div.appendChild(lbl);
    var select = document.createElement("select");
    options.forEach(function (opt) {
      var el = document.createElement("option");
      el.value = opt[0];
      el.textContent = opt[1];
      if (opt[0] === value) el.selected = true;
      select.appendChild(el);
    });
    select.addEventListener("change", function () {
      onChange(select.value);
    });
    div.appendChild(select);
    return div;
  }

  // An advance reminder is two stored fields, a day count and a
  // cadence, that only mean something together: they are edited as one
  // choice and always saved as a pair.
  var REMIND_AHEAD_MIN_DAYS = 1;
  var REMIND_AHEAD_MAX_DAYS = 90;
  var REMIND_AHEAD_CHOICES = [
    ["none", "Off"],
    ["once", "Once"],
    ["daily_until_due", "Every day until due"],
  ];

  function remindAheadDays(value) {
    var days = parseInt(value, 10);
    if (isNaN(days)) return REMIND_AHEAD_MIN_DAYS;
    return Math.min(
      Math.max(days, REMIND_AHEAD_MIN_DAYS),
      REMIND_AHEAD_MAX_DAYS,
    );
  }

  function makeRemindAhead(item, onChange) {
    var div = document.createElement("div");
    div.className = "detail-field";
    var lbl = document.createElement("label");
    lbl.textContent = "Remind ahead";
    lbl.htmlFor = "detail-remind-cadence";
    div.appendChild(lbl);

    var row = document.createElement("div");
    row.className = "detail-remind-row";

    var select = document.createElement("select");
    select.id = "detail-remind-cadence";
    select.setAttribute("aria-describedby", "detail-remind-note");
    REMIND_AHEAD_CHOICES.forEach(function (choice) {
      var opt = document.createElement("option");
      opt.value = choice[0];
      opt.textContent = choice[1];
      select.appendChild(opt);
    });
    row.appendChild(select);

    var count = document.createElement("span");
    count.className = "detail-remind-count";
    var daysInput = document.createElement("input");
    daysInput.type = "number";
    daysInput.min = String(REMIND_AHEAD_MIN_DAYS);
    daysInput.max = String(REMIND_AHEAD_MAX_DAYS);
    daysInput.step = "1";
    daysInput.inputMode = "numeric";
    daysInput.setAttribute("aria-label", "Days before the due date");
    count.appendChild(daysInput);
    var unit = document.createElement("span");
    unit.className = "detail-remind-unit";
    count.appendChild(unit);
    row.appendChild(count);
    div.appendChild(row);

    var note = document.createElement("div");
    note.className = "detail-meta";
    note.id = "detail-remind-note";
    div.appendChild(note);

    // A stored pair that asks for no reminder, an unknown cadence or a
    // day count below one, is shown as "Off".
    var stored = REMIND_AHEAD_CHOICES.some(function (choice) {
      return choice[0] === item.reminder_cadence;
    });
    var on = stored && item.remind_before_days >= REMIND_AHEAD_MIN_DAYS;
    select.value = on ? item.reminder_cadence : "none";
    daysInput.value = remindAheadDays(on ? item.remind_before_days : NaN);
    var hasDueDate = Boolean(item.due_date);

    function refresh() {
      var off = select.value === "none";
      count.classList.toggle("hidden", off);
      unit.textContent =
        parseInt(daysInput.value, 10) === 1 ? "day before" : "days before";
      select.disabled = !hasDueDate;
      daysInput.disabled = !hasDueDate;
      note.textContent = hasDueDate
        ? "Mentions the task in the daily summary on the days before it is due."
        : "Needs a due date.";
    }

    function report() {
      if (select.value === "none") {
        onChange(0, "none");
      } else {
        onChange(remindAheadDays(daysInput.value), select.value);
      }
    }

    select.addEventListener("change", function () {
      refresh();
      report();
    });
    daysInput.addEventListener("input", refresh);
    daysInput.addEventListener("change", function () {
      daysInput.value = remindAheadDays(daysInput.value);
      refresh();
      report();
    });
    refresh();

    return {
      element: div,
      setHasDueDate: function (value) {
        hasDueDate = value;
        refresh();
      },
    };
  }

  var lastSavedFields = null;
  // Edits waiting out the debounce, by item id. An edit made while
  // another is waiting joins it; replacing it would lose the first.
  var pendingItemFields = {};

  function saveItemField(itemId, fields) {
    pendingItemFields[itemId] = Object.assign(
      pendingItemFields[itemId] || {},
      fields,
    );
    clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(flushPendingItemFields, 500);
  }

  async function flushPendingItemFields() {
    var waiting = pendingItemFields;
    pendingItemFields = {};
    var itemIds = Object.keys(waiting);
    for (var i = 0; i < itemIds.length; i++) {
      await sendItemFields(itemIds[i], waiting[itemIds[i]]);
    }
  }

  async function sendItemFields(itemId, fields) {
    var indicator = document.getElementById("detail-save-indicator");
    if (indicator) {
      indicator.textContent = "Saving...";
      indicator.className = "detail-save-indicator";
    }
    var ua = getItemUpdatedAt(itemId);
    if (ua !== undefined) fields.updated_at = ua;
    lastSavedFields = Object.assign({}, fields);
    try {
      var result = await api("/items/" + itemId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      updateCachedItemTimestamp(itemId, result.updated_at);
      if (indicator) indicator.textContent = "Saved \u2713";
      setTimeout(function () {
        if (indicator) indicator.textContent = "";
      }, 2000);
      await refreshCurrentList();
    } catch (e) {
      if (e.status === 409) {
        showDetailConflict(itemId, e.body.current);
      } else {
        if (indicator) indicator.textContent = "Save failed";
      }
    }
  }

  function showDetailConflict(itemId, currentData) {
    var indicator = document.getElementById("detail-save-indicator");
    if (!indicator) return;
    indicator.textContent = "";
    indicator.className = "detail-save-indicator detail-conflict";

    var msg = document.createElement("span");
    msg.textContent = "Modified on another device";
    indicator.appendChild(msg);

    var refreshBtn = document.createElement("button");
    refreshBtn.className = "conflict-btn";
    refreshBtn.textContent = "Refresh";
    refreshBtn.addEventListener("click", async function () {
      await refreshCurrentList();
      openDetailSheet(itemId);
    });
    indicator.appendChild(refreshBtn);

    var forceBtn = document.createElement("button");
    forceBtn.className = "conflict-btn conflict-force";
    forceBtn.textContent = "Force Save";
    forceBtn.addEventListener("click", function () {
      var pending = lastSavedFields || {};
      pending.force = true;
      pending.updated_at = currentData.updated_at;
      saveItemFieldForce(itemId, pending);
    });
    indicator.appendChild(forceBtn);
  }

  async function saveItemFieldForce(itemId, fields) {
    var indicator = document.getElementById("detail-save-indicator");
    if (indicator) {
      indicator.textContent = "Saving...";
      indicator.className = "detail-save-indicator";
    }
    try {
      var result = await api("/items/" + itemId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      updateCachedItemTimestamp(itemId, result.updated_at);
      if (indicator) indicator.textContent = "Saved \u2713";
      setTimeout(function () {
        if (indicator) indicator.textContent = "";
      }, 2000);
      await refreshCurrentList();
    } catch (e) {
      if (indicator) indicator.textContent = "Save failed";
    }
  }

  function closeDetailSheet() {
    animateSheetClose(detailSheet, function () {
      if (location.hash.startsWith("#/item/")) location.hash = "#/";
    });
  }

  if (detailClose) detailClose.addEventListener("click", closeDetailSheet);
  if (detailSheet) {
    detailSheet
      .querySelector(".sheet-backdrop")
      .addEventListener("click", closeDetailSheet);
  }

  // ====================================================================
  // Search & filter
  // ====================================================================

  var searchFilters = { priority: null, status: "all", due: null, tags: null };

  async function refreshSearch() {
    await fetchTags();
    renderSearchTagChips();
    doSearch();
  }

  async function fetchTags() {
    try {
      var data = await api("/tags");
      allTags = data.tags || [];
    } catch (e) {
      allTags = [];
    }
  }

  function renderSearchTagChips() {
    if (!searchTagChips) return;
    searchTagChips.innerHTML = "";
    if (allTags.length === 0) {
      if (searchTagFilters) searchTagFilters.classList.add("hidden");
      return;
    }
    if (searchTagFilters) searchTagFilters.classList.remove("hidden");
    allTags.forEach(function (tag) {
      var chip = document.createElement("button");
      chip.className = "chip";
      chip.dataset.filter = "tags";
      chip.dataset.value = tag;
      chip.textContent = tag;
      if (searchFilters.tags === tag) chip.classList.add("active");
      chip.addEventListener("click", function () {
        searchFilters.tags = chip.classList.contains("active") ? null : tag;
        renderSearchTagChips();
        doSearch();
      });
      searchTagChips.appendChild(chip);
    });
  }

  // Filter chip click handlers
  document.querySelectorAll("#search-filters .chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var filterType = chip.dataset.filter;
      var value = chip.dataset.value;

      if (filterType === "status") {
        searchFilters.status = value;
        chip.parentElement.querySelectorAll(".chip").forEach(function (c) {
          c.classList.toggle("active", c.dataset.value === value);
        });
      } else if (filterType === "priority") {
        if (chip.classList.contains("active")) {
          chip.classList.remove("active");
          searchFilters.priority = null;
        } else {
          chip.parentElement.querySelectorAll(".chip").forEach(function (c) {
            c.classList.remove("active");
          });
          chip.classList.add("active");
          searchFilters.priority = value;
        }
      } else if (filterType === "due") {
        if (chip.classList.contains("active")) {
          chip.classList.remove("active");
          searchFilters.due = null;
        } else {
          chip.parentElement.querySelectorAll(".chip").forEach(function (c) {
            c.classList.remove("active");
          });
          chip.classList.add("active");
          searchFilters.due = value;
        }
      }
      doSearch();
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      clearTimeout(parseDebounceTimer);
      parseDebounceTimer = setTimeout(doSearch, 200);
    });
  }

  async function doSearch() {
    if (!searchResults) return;
    searchResults.innerHTML = "";

    var query = searchInput ? searchInput.value.trim() : "";
    var results = [];

    for (var i = 0; i < cachedLists.length; i++) {
      var lst = cachedLists[i];
      try {
        var params = [];
        if (query) params.push("q=" + encodeURIComponent(query));
        if (searchFilters.priority)
          params.push("priority=" + searchFilters.priority);
        if (searchFilters.status !== "all")
          params.push("status=" + searchFilters.status);
        if (searchFilters.due) params.push("due=" + searchFilters.due);
        if (searchFilters.tags)
          params.push("tags=" + encodeURIComponent(searchFilters.tags));
        var url =
          "/lists/" + lst.id + (params.length ? "?" + params.join("&") : "");
        var data = await api(url);
        if (data.items && data.items.length > 0) {
          results.push({ list: lst, items: data.items });
        }
      } catch (e) {
        /* skip failed lists */
      }
    }

    if (results.length === 0) {
      if (searchEmpty) searchEmpty.classList.remove("hidden");
      return;
    }
    if (searchEmpty) searchEmpty.classList.add("hidden");

    results.forEach(function (group) {
      var groupDiv = document.createElement("div");
      groupDiv.className = "search-list-group";
      var nameDiv = document.createElement("div");
      nameDiv.className = "search-list-name";
      nameDiv.textContent = group.list.name;
      groupDiv.appendChild(nameDiv);

      group.items.forEach(function (item) {
        // The results of a search are all new.
        var row = createItemCard(item, null);
        row.classList.add("item-enter");
        groupDiv.appendChild(row);
      });
      searchResults.appendChild(groupDiv);
    });
  }

  // ====================================================================
  // Settings
  // ====================================================================

  async function refreshSettings() {
    // Connection info
    var connStatus = document.getElementById("settings-conn-status");
    if (connStatus) {
      var wsConnected = ws && ws.readyState === WebSocket.OPEN;
      var statusText = !isOnline
        ? "Offline"
        : wsConnected
          ? "Connected (live)"
          : "Connected (polling)";
      var statusClass = isOnline
        ? "settings-conn-online"
        : "settings-conn-offline";
      connStatus.textContent = statusText;
      connStatus.className = "settings-value " + statusClass;
    }
    var serverUrl = document.getElementById("settings-server-url");
    if (serverUrl) serverUrl.textContent = location.host;

    // Offline queue
    var offlineRow = document.getElementById("settings-offline-row");
    var offlineCount = document.getElementById("settings-offline-count");
    var queueSection = document.getElementById("settings-queue-section");
    var queue = getOfflineQueue();
    if (offlineRow)
      offlineRow.style.display = queue.length > 0 ? "flex" : "none";
    if (offlineCount) offlineCount.textContent = String(queue.length);
    if (queueSection)
      queueSection.style.display = queue.length > 0 ? "block" : "none";
    renderQueueList(queue);

    // Display info
    updateThemeLabel();
    var viewModeEl = document.getElementById("settings-view-mode");
    if (viewModeEl) {
      var modeLabels = { list: "List", board: "Board", calendar: "Calendar" };
      viewModeEl.textContent = modeLabels[viewMode] || viewMode;
    }

    // Server data
    try {
      var data = await api("/status");
      if (settingsStatus) {
        settingsStatus.textContent =
          data.list_count +
          " lists \u00B7 " +
          data.total_completed +
          "/" +
          data.total_items +
          " completed";
      }
      if (versionText) versionText.textContent = "Version " + data.version;
    } catch (e) {
      if (settingsStatus) settingsStatus.textContent = "Unable to load status";
    }

    // Recently deleted
    refreshTrash();
  }

  async function refreshTrash() {
    var trashList = document.getElementById("trash-list");
    var trashEmpty = document.getElementById("trash-empty");
    if (!trashList) return;

    try {
      var data = await api("/trash");
      var items = data.items || [];
      trashList.innerHTML = "";

      if (items.length === 0) {
        if (trashEmpty) trashEmpty.style.display = "";
        return;
      }
      if (trashEmpty) trashEmpty.style.display = "none";

      items.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "trash-item";

        var info = document.createElement("div");
        info.className = "trash-item-info";
        var name = document.createElement("div");
        name.className = "trash-item-name";
        name.textContent = item.reminder;
        info.appendChild(name);
        var meta = document.createElement("div");
        meta.className = "trash-item-meta";
        meta.textContent =
          item.list_name + " \u00B7 " + formatDeletedAgo(item.deleted_ago_ms);
        info.appendChild(meta);
        row.appendChild(info);

        var restoreBtn = document.createElement("button");
        restoreBtn.className = "trash-restore-btn";
        restoreBtn.textContent = "Restore";
        restoreBtn.addEventListener("click", async function () {
          try {
            await api("/items/" + item.id + "/restore", { method: "PATCH" });
            haptic(10);
            showToast("Item restored");
            refreshTrash();
            refreshCurrentList();
          } catch (e) {
            showToast("Failed to restore item");
          }
        });
        row.appendChild(restoreBtn);

        trashList.appendChild(row);
      });
    } catch (e) {
      if (trashEmpty) trashEmpty.textContent = "Unable to load deleted items";
    }
  }

  function formatDeletedAgo(ms) {
    var mins = Math.floor(ms / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    var days = Math.floor(hrs / 24);
    return days + "d ago";
  }

  // ====================================================================
  // Offline queue viewer (settings)
  // ====================================================================

  function describeQueueAction(entry) {
    var path = entry.path || "";
    var method = (entry.opts && entry.opts.method) || "GET";
    if (method === "PATCH" && path.includes("/toggle")) return "Toggle item";
    if (method === "PATCH" && path.includes("/restore")) return "Restore item";
    if (method === "PATCH" && path.includes("/move")) return "Move item";
    if (method === "DELETE") return "Delete item";
    if (method === "POST" && path.includes("/items")) return "Add item";
    if (method === "PUT") return "Update item";
    return method + " " + path.split("/").pop();
  }

  function renderQueueList(queue) {
    var queueList = document.getElementById("settings-queue-list");
    if (!queueList) return;
    queueList.innerHTML = "";
    queue.forEach(function (entry, idx) {
      var row = document.createElement("div");
      row.className = "queue-item";

      var info = document.createElement("span");
      info.className = "queue-item-info";
      info.textContent = describeQueueAction(entry);
      row.appendChild(info);

      var time = document.createElement("span");
      time.className = "queue-item-time";
      time.textContent = formatDeletedAgo(Date.now() - entry.timestamp);
      row.appendChild(time);

      var removeBtn = document.createElement("button");
      removeBtn.className = "queue-item-remove";
      removeBtn.title = "Remove";
      removeBtn.innerHTML = "&times;";
      removeBtn.addEventListener("click", function () {
        removeFromOfflineQueue(idx);
        clearOfflineUndo();
        refreshSettings();
      });
      row.appendChild(removeBtn);

      queueList.appendChild(row);
    });
  }

  // Clear all queued changes button
  var clearQueueBtn = document.getElementById("settings-clear-queue");
  if (clearQueueBtn) {
    clearQueueBtn.addEventListener("click", function () {
      if (!confirm("Discard all pending offline changes?")) return;
      saveOfflineQueue([]);
      clearOfflineUndo();
      showToast("Offline queue cleared");
      refreshSettings();
    });
  }

  // Theme toggle
  var themeRow = document.getElementById("settings-theme-row");
  if (themeRow) {
    themeRow.addEventListener("click", function () {
      cycleTheme();
    });
  }

  // ====================================================================
  // Event handlers
  // ====================================================================

  async function onToggle(itemId) {
    var path = "/items/" + itemId + "/toggle";
    var ua = getItemUpdatedAt(itemId);
    var opts = { method: "PATCH" };
    if (ua !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify({ updated_at: ua });
    }
    var outcome = await sendOrQueue(path, opts);
    if (outcome === "sent") await refreshCurrentList();
  }

  // Deletes a task, from wherever in the page that is asked for. The
  // row or card, when given, starts to leave at once. The notice waits
  // until the delete is kept, applied by the server or queued, so that
  // its Undo has that delete to act on; a delete is announced once.
  // Undo on the notice brings this task back, whatever has been done
  // since; the toolbar's Undo takes back the latest change.
  async function onDelete(itemId, reminderText, cardEl) {
    if (cardEl) cardEl.classList.add("item-exit");
    haptic(10);
    var path = "/items/" + itemId;
    var ua = getItemUpdatedAt(itemId);
    var opts = { method: "DELETE" };
    if (ua !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify({ updated_at: ua });
    }
    var name = reminderText ? '"' + reminderText + '"' : "Item";
    var step = {};
    var outcome = await sendOrQueue(path, opts, step);
    if (outcome === "sent") {
      await refreshCurrentList();
      showToast(name + " deleted", function () {
        restoreDeletedItem(itemId, name);
      });
    } else if (outcome === "queued") {
      showToast(name + " deleted (offline)", function () {
        undoQueuedDelete(step, itemId, name);
      });
    } else if (cardEl) {
      // Not deleted: sendOrQueue has said why. The list is drawn again
      // only when it has changed, so the row is put back here.
      cardEl.classList.remove("item-exit");
    }
  }

  // Takes one earlier step of the queue back, leaving the changes made
  // since. It is a step of its own for the toolbar's Undo and Redo.
  // False when the step is no longer in the queue.
  function takeBackQueuedStep(step) {
    var queue = getOfflineQueue();
    var result = QueueRules.withStepTakenBack(queue, step.before, step.after);
    if (!result) return false;
    saveOfflineQueue(result);
    pushOfflineUndo(queue, result);
    return true;
  }

  // Undo of a delete that was queued. While it waits, it is taken out
  // of the queue, and the changes to the task that it replaced are put
  // back. Once it has been sent, the server has deleted the task, and
  // is asked to restore it.
  async function undoQueuedDelete(step, itemId, name) {
    // A run that is sending the queue may have the delete on its way to
    // the server; which of the two applies is known when the run ends.
    while (replayRunning) {
      await new Promise(function (resolve) {
        setTimeout(resolve, 100);
      });
    }
    if (takeBackQueuedStep(step)) {
      showToast(name + " restored");
    } else {
      await restoreDeletedItem(itemId, name);
    }
  }

  // Undo of a delete the server has applied: the server restores the
  // task by its id. The application's undo stack is shared with the
  // desktop window and every other device, and its latest command may
  // be someone else's.
  async function restoreDeletedItem(itemId, name) {
    try {
      await api("/items/" + itemId + "/restore", { method: "PATCH" });
    } catch (e) {
      if (e.status === 404) {
        // Not deleted at the server: brought back already.
        showToast("Nothing to undo");
        await refreshCurrentList();
      } else {
        showToast(name + " not restored \u2014 see Recently Deleted");
      }
      return;
    }
    showToast(name + " restored");
    await refreshCurrentList();
    fetchUndoState();
  }

  // ====================================================================
  // Undo / Redo (online via server, offline via client-side stack)
  // ====================================================================

  // Undo without the server works on the queue: each queued change
  // records the queue before and after it, and undo and redo put one or
  // the other back. The list follows, since it is drawn from the queue.
  function pushOfflineUndo(before, after) {
    offlineUndoStack.push({ before: before, after: after });
    offlineRedoStack = []; // new action invalidates redo
    updateUndoButtons();
  }

  function clearOfflineUndo() {
    offlineUndoStack = [];
    offlineRedoStack = [];
    updateUndoButtons();
  }

  // Changes are waiting that the server has not seen: undo and redo act
  // on those, whether or not the browser reports the device offline.
  function undoIsOffline() {
    return (
      !isOnline || offlineUndoStack.length > 0 || offlineRedoStack.length > 0
    );
  }

  function updateUndoButtons() {
    if (undoIsOffline()) {
      if (undoBtn) {
        undoBtn.disabled = offlineUndoStack.length === 0;
        undoBtn.title = offlineUndoStack.length > 0 ? "Undo (offline)" : "Undo";
      }
      if (redoBtn) {
        redoBtn.disabled = offlineRedoStack.length === 0;
        redoBtn.title = offlineRedoStack.length > 0 ? "Redo (offline)" : "Redo";
      }
    } else {
      if (undoBtn) {
        undoBtn.disabled = !serverUndoState.can_undo;
        undoBtn.title = serverUndoState.undo_text
          ? "Undo: " + serverUndoState.undo_text
          : "Undo";
      }
      if (redoBtn) {
        redoBtn.disabled = !serverUndoState.can_redo;
        redoBtn.title = serverUndoState.redo_text
          ? "Redo: " + serverUndoState.redo_text
          : "Redo";
      }
    }
  }

  async function fetchUndoState() {
    try {
      var resp = await api("/undo-state");
      serverUndoState = resp;
      updateUndoButtons();
    } catch (e) {
      /* server unreachable */
    }
  }

  function offlineUndoAction() {
    if (offlineUndoStack.length === 0) return;
    var entry = offlineUndoStack.pop();
    offlineRedoStack.push(entry);
    saveOfflineQueue(entry.before);
    updateUndoButtons();
    showToast("Undone (offline)");
  }

  function offlineRedoAction() {
    if (offlineRedoStack.length === 0) return;
    var entry = offlineRedoStack.pop();
    offlineUndoStack.push(entry);
    saveOfflineQueue(entry.after);
    updateUndoButtons();
    showToast("Redone (offline)");
  }

  async function onUndo() {
    if (undoIsOffline()) {
      offlineUndoAction();
      return;
    }
    try {
      var resp = await api("/undo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (resp && resp.ok) {
        showToast("Undone: " + resp.undone);
        refreshCurrentList();
        serverUndoState.can_undo = resp.can_undo;
        serverUndoState.can_redo = resp.can_redo;
        updateUndoButtons();
      }
    } catch (e) {
      /* ignore */
    }
  }

  async function onRedo() {
    if (undoIsOffline()) {
      offlineRedoAction();
      return;
    }
    try {
      var resp = await api("/redo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (resp && resp.ok) {
        showToast("Redone: " + resp.redone);
        refreshCurrentList();
        serverUndoState.can_undo = resp.can_undo;
        serverUndoState.can_redo = resp.can_redo;
        updateUndoButtons();
      }
    } catch (e) {
      /* ignore */
    }
  }

  if (undoBtn) undoBtn.addEventListener("click", onUndo);
  if (redoBtn) redoBtn.addEventListener("click", onRedo);

  // ====================================================================
  // Toast notifications
  // ====================================================================

  function showToast(message, undoCallback) {
    if (!toastContainer) return;
    var toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;

    if (undoCallback) {
      var undoBtn = document.createElement("button");
      undoBtn.className = "toast-undo";
      undoBtn.textContent = "Undo";
      undoBtn.addEventListener("click", function () {
        undoCallback();
        toast.remove();
      });
      toast.appendChild(undoBtn);
    }

    toastContainer.appendChild(toast);
    setTimeout(
      function () {
        toast.remove();
      },
      undoCallback ? 5500 : 3000,
    );
  }

  // ====================================================================
  // List picker sheet
  // ====================================================================

  function renderLists(lists) {
    // Skip re-render if data hasn't changed
    var fp = fingerprint(lists);
    if (fp === lastListsFingerprint) {
      cachedLists = lists;
      return;
    }
    lastListsFingerprint = fp;
    cachedLists = lists;

    // Update header button text
    if (currentListId && lists.length > 0) {
      var current = lists.find(function (l) {
        return l.id === currentListId;
      });
      if (current && listPickerName) listPickerName.textContent = current.name;
    } else if (lists.length > 0) {
      currentListId = lists[0].id;
      if (listPickerName) listPickerName.textContent = lists[0].name;
    }

    // Update sheet body if open
    if (listSheet && !listSheet.classList.contains("hidden")) {
      renderListSheetBody(lists);
    }
  }

  function renderListSheetBody(lists) {
    if (!listSheetBody) return;
    listSheetBody.innerHTML = "";
    lists.forEach(function (lst) {
      var row = document.createElement("div");
      row.className = "list-row" + (lst.id === currentListId ? " active" : "");

      var info = document.createElement("div");
      info.className = "list-row-info";
      info.addEventListener("click", function () {
        currentListId = lst.id;
        if (listPickerName) listPickerName.textContent = lst.name;
        closeListSheet();
        refreshCurrentList();
      });

      var name = document.createElement("div");
      name.className = "list-row-name";
      name.textContent = lst.name;
      info.appendChild(name);

      var stats = document.createElement("div");
      stats.className = "list-row-stats";
      var pct =
        lst.item_count > 0
          ? Math.round((lst.completed_count / lst.item_count) * 100)
          : 0;
      stats.textContent =
        lst.completed_count + "/" + lst.item_count + " done (" + pct + "%)";
      if (lst.overdue_count > 0) {
        stats.textContent += " \u00B7 " + lst.overdue_count + " overdue";
      }
      info.appendChild(stats);
      row.appendChild(info);

      // Action buttons
      var actions = document.createElement("div");
      actions.className = "list-row-actions";

      var renameBtn = document.createElement("button");
      renameBtn.className = "list-action-btn";
      renameBtn.title = "Rename";
      renameBtn.innerHTML = "&#9998;";
      renameBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        startRenameList(lst.id, lst.name, name);
      });
      actions.appendChild(renameBtn);

      var deleteBtn = document.createElement("button");
      deleteBtn.className = "list-action-btn danger";
      deleteBtn.title = "Delete";
      deleteBtn.innerHTML = "&times;";
      deleteBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        confirmDeleteList(lst.id, lst.name, lst.item_count);
      });
      actions.appendChild(deleteBtn);

      row.appendChild(actions);
      listSheetBody.appendChild(row);
    });
  }

  function openListSheet() {
    if (!listSheet) return;
    renderListSheetBody(cachedLists);
    listSheet.classList.remove("hidden");
    trapFocus(listSheet);
  }

  function closeListSheet() {
    animateSheetClose(listSheet);
  }

  function startRenameList(listId, currentName, nameEl) {
    var input = document.createElement("input");
    input.type = "text";
    input.className = "list-rename-input";
    input.value = currentName;
    nameEl.textContent = "";
    nameEl.appendChild(input);
    input.focus();
    input.select();

    async function commitRename() {
      var newName = input.value.trim();
      if (newName && newName !== currentName) {
        var renameFields = { name: newName };
        var renameUa = getListUpdatedAt(listId);
        if (renameUa !== undefined) renameFields.updated_at = renameUa;
        try {
          await api("/lists/" + listId, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(renameFields),
          });
          showToast("List renamed");
          await refreshLists();
          renderListSheetBody(cachedLists);
        } catch (e) {
          if (e.status === 409) {
            showToast("List was modified \u2014 refreshing");
            await refreshLists();
            renderListSheetBody(cachedLists);
            nameEl.textContent = e.body.current
              ? e.body.current.name
              : currentName;
          } else {
            showToast("Failed to rename list");
            nameEl.textContent = currentName;
          }
        }
      } else {
        nameEl.textContent = currentName;
      }
    }

    input.addEventListener("blur", commitRename);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        input.blur();
      }
      if (e.key === "Escape") {
        nameEl.textContent = currentName;
      }
    });
  }

  function confirmDeleteList(listId, name, itemCount) {
    var msg = 'Delete "' + name + '"';
    if (itemCount > 0)
      msg +=
        " and its " + itemCount + " item" + (itemCount > 1 ? "s" : "") + "?";
    else msg += "?";

    if (!confirm(msg)) return;

    (async function () {
      var delListFields = {};
      var delListUa = getListUpdatedAt(listId);
      if (delListUa !== undefined) delListFields.updated_at = delListUa;
      try {
        await api("/lists/" + listId, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(delListFields),
        });
        showToast("List deleted");
        if (currentListId === listId) {
          currentListId = null;
        }
        await refreshLists();
        renderListSheetBody(cachedLists);
        if (!currentListId && cachedLists.length > 0) {
          currentListId = cachedLists[0].id;
          if (listPickerName) listPickerName.textContent = cachedLists[0].name;
        }
        refreshCurrentList();
      } catch (e) {
        if (e.status === 409) {
          showToast("List was modified \u2014 refreshing");
          await refreshLists();
          renderListSheetBody(cachedLists);
        } else {
          showToast("Failed to delete list");
        }
      }
    })();
  }

  // Wiring
  if (listPickerBtn) listPickerBtn.addEventListener("click", openListSheet);
  if (listSheetClose) listSheetClose.addEventListener("click", closeListSheet);
  if (listSheet) {
    listSheet
      .querySelector(".sheet-backdrop")
      .addEventListener("click", closeListSheet);
  }

  if (listCreateBtn) {
    listCreateBtn.addEventListener("click", async function () {
      var name = listCreateInput.value.trim();
      if (!name) return;
      try {
        var result = await api("/lists", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name }),
        });
        listCreateInput.value = "";
        showToast("List created");
        currentListId = result.id;
        await refreshLists();
        if (listPickerName) listPickerName.textContent = name;
        renderListSheetBody(cachedLists);
        refreshCurrentList();
      } catch (e) {
        showToast(e.message || "Failed to create list");
      }
    });
  }
  if (listCreateInput) {
    listCreateInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        listCreateBtn.click();
      }
    });
  }

  // ====================================================================
  // Data loading
  // ====================================================================

  async function refreshLists() {
    try {
      var data = await api("/lists");
      renderLists(data.lists);
      cacheListsData(data.lists);
    } catch (e) {
      console.error("Failed to load lists:", e);
      // Fall back to IndexedDB cache
      var cached = await getCachedLists();
      if (cached && cached.length > 0) {
        renderLists(cached);
      }
    }
  }

  async function refreshCurrentList() {
    if (!currentListId) {
      serverItems = [];
      cachedItems = [];
      renderItems([]);
      return;
    }
    try {
      var data = await api("/lists/" + currentListId);
      serverItems = data.items || [];
      serverBoardData = {
        board_columns: data.board_columns || [],
        wip_limits: data.wip_limits || {},
        columns: null,
      };

      // Cache for offline use
      cacheListItems(currentListId, serverItems);

      showQueuedChanges();
      if (viewMode === "board") await refreshBoard();

      // Refresh list selector counts
      await refreshLists();
      markSynced();
    } catch (e) {
      console.error("Failed to load list:", e);
      // Fall back to IndexedDB cache
      serverItems = (await getCachedListItems(currentListId)) || [];
      showQueuedChanges();
    }
  }

  // ====================================================================
  // Polling (fallback when WebSocket unavailable)
  // ====================================================================

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(function () {
      refreshCurrentList();
    }, 3000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // ====================================================================
  // WebSocket (real-time push, replaces polling when connected)
  // ====================================================================

  var ws = null;
  var wsReconnectTimer = null;
  var wsReconnectDelay = 1000;
  var WS_MAX_DELAY = 30000;

  function connectWebSocket() {
    if (
      ws &&
      (ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING)
    )
      return;
    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var wsToken = getAuthToken();
    var url =
      protocol +
      "//" +
      location.host +
      "/ws" +
      (wsToken ? "?token=" + encodeURIComponent(wsToken) : "");
    try {
      ws = new WebSocket(url);
    } catch (e) {
      startPolling();
      return;
    }
    ws.onopen = function () {
      wsReconnectDelay = 1000;
      updateOnlineStatus(true);
      stopPolling();
      replayOfflineQueue();
    };
    ws.onmessage = function (e) {
      try {
        var msg = JSON.parse(e.data);
        if (msg.event === "refresh") {
          refreshCurrentList();
          fetchUndoState();
        } else if (msg.event === "hello") {
          onServerPageVersion(msg.page_version);
        }
      } catch (err) {
        /* ignore malformed messages */
      }
    };
    ws.onclose = function () {
      ws = null;
      if (navigator.onLine) {
        startPolling();
        scheduleReconnect();
      } else {
        updateOnlineStatus(false);
      }
    };
    ws.onerror = function () {
      /* onclose fires after onerror */
    };
  }

  function scheduleReconnect() {
    if (wsReconnectTimer) return;
    wsReconnectTimer = setTimeout(function () {
      wsReconnectTimer = null;
      connectWebSocket();
    }, wsReconnectDelay);
    wsReconnectDelay = Math.min(wsReconnectDelay * 2, WS_MAX_DELAY);
  }

  function disconnectWebSocket() {
    if (wsReconnectTimer) {
      clearTimeout(wsReconnectTimer);
      wsReconnectTimer = null;
    }
    if (ws) {
      ws.close();
      ws = null;
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else {
      refreshCurrentList();
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        connectWebSocket();
        startPolling();
      }
      // A calendar left on screen overnight moves to the new day.
      if (viewMode === "calendar" && calDateIsStale()) renderCalendar();
    }
  });

  // ====================================================================
  // Bottom navigation
  // ====================================================================

  if (bottomNav) {
    bottomNav.querySelectorAll(".nav-btn[data-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        navigateTo(btn.dataset.view);
      });
    });

    var navAddBtn = document.getElementById("nav-add");
    if (navAddBtn) {
      navAddBtn.addEventListener("click", function () {
        openAddSheet();
      });
    }
  }

  // ====================================================================
  // Install banner
  // ====================================================================

  var installBanner = document.getElementById("install-banner");
  var installDismiss = document.getElementById("install-dismiss");

  function showInstallBanner() {
    if (!installBanner) return;
    if (window.matchMedia("(display-mode: standalone)").matches) return;
    if (localStorage.getItem(INSTALL_DISMISSED_KEY)) return;
    installBanner.classList.remove("hidden");
  }

  if (installDismiss) {
    installDismiss.addEventListener("click", function () {
      if (installBanner) installBanner.classList.add("hidden");
      localStorage.setItem(INSTALL_DISMISSED_KEY, "1");
    });
  }

  var installText = document.getElementById("install-text");
  if (installText) {
    var ua = navigator.userAgent || "";
    if (/iPhone|iPad|iPod/.test(ua)) {
      installText.innerHTML =
        "Tap <b>Share</b> \u2192 <b>Add to Home Screen</b> for quick access";
    } else {
      installText.innerHTML =
        "Tap <b>\u22ee</b> menu \u2192 <b>Add to Home Screen</b> for quick access";
    }
  }

  setTimeout(showInstallBanner, 500);

  // ====================================================================
  // Init
  // ====================================================================

  async function init() {
    updateOnlineStatus(navigator.onLine);
    await openIDB();
    updatePendingBadge();
    hideLoginScreen();
    await refreshLists();
    await refreshCurrentList();
    onRouteChange();
    // Setting the view draws the list a second time, in the same
    // moment as the first: its rows are still new to the person.
    drawnRows = { list: null, rows: {} };
    setViewMode(viewMode);
    connectWebSocket();
    startPolling(); // Fallback until WS connects
    fetchUndoState();
    // Keep "last synced" text fresh
    setInterval(updateLastSyncedText, 15000);
    appReady = true;
    storeDataForOffline();
  }

  // Block insecure HTTP connections — require HTTPS
  if (
    location.protocol === "http:" &&
    location.hostname !== "localhost" &&
    location.hostname !== "127.0.0.1"
  ) {
    var upgradeUrl = "https://" + location.host + location.pathname;
    document.body.innerHTML =
      '<div style="display:flex;align-items:center;justify-content:center;' +
      'min-height:100vh;background:var(--bg,#fff);padding:24px;text-align:center;">' +
      '<div style="max-width:360px;">' +
      '<h2 style="color:var(--danger,#c0392b);">Insecure Connection</h2>' +
      "<p>This app requires an encrypted (HTTPS) connection.</p>" +
      "<p>Please reinstall from:</p>" +
      '<a href="' +
      upgradeUrl +
      '" style="color:var(--accent,#2196F3);word-break:break-all;">' +
      upgradeUrl +
      "</a>" +
      '<p style="margin-top:16px;font-size:12px;opacity:0.7;">' +
      "If you previously added this app to your home screen over HTTP, " +
      "remove it and add again from the HTTPS URL above.</p>" +
      "</div></div>";
    return;
  }

  // Listen for SW upgrade message (old HTTP SW unregistering)
  if (navigator.serviceWorker) {
    navigator.serviceWorker.addEventListener("message", function (e) {
      if (e.data && e.data.type === "http-upgrade-needed") {
        location.reload();
      }
    });
  }

  var appReady = false;
  var loadedUnderWorker = false;

  // Register the service worker. The page's security policy allows
  // scripts from this origin only, so this cannot be an inline script.
  // A worker is for HTTPS: over plain HTTP sw.js removes itself.
  if (navigator.serviceWorker && location.protocol === "https:") {
    // A worker that controlled the page as it loaded means a later
    // change of controller is a new version of the page. Otherwise it
    // is the first install.
    loadedUnderWorker = Boolean(navigator.serviceWorker.controller);
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (loadedUnderWorker) reloadForUpdateWhenIdle();
      else storeDataForOffline();
    });
    navigator.serviceWorker
      .register("/sw.js")
      .then(function (registration) {
        // The browser looks for a new worker when the page is loaded. A
        // page that stays open, as an installed app does, is not loaded
        // again for days, so look whenever it comes back into view.
        document.addEventListener("visibilitychange", function () {
          if (document.visibilityState === "visible") {
            registration.update().catch(function () {
              /* offline, or the server is unreachable */
            });
          }
        });
      })
      .catch(function (err) {
        console.warn("SW registration failed:", err);
      });
  }

  // What the page read before its first worker was in place went
  // straight to the network, so the worker has stored none of it and a
  // start without the server would have nothing to show. Read it again
  // through the worker. Called when the worker takes control and when
  // the page has finished starting, whichever comes last.
  function storeDataForOffline() {
    if (!appReady || loadedUnderWorker) return;
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) {
      return;
    }
    fetch(API + "/status", { headers: authHeaders() }).catch(function () {});
    refreshLists()
      .then(refreshCurrentList)
      .catch(function () {});
  }

  // The version of the page's files this page is, written into the
  // page by the server. Empty for a page that carries none.
  var PAGE_VERSION = (function () {
    var meta = document.querySelector('meta[name="page-version"]');
    var version = meta ? meta.getAttribute("content") || "" : "";
    return version.indexOf("__") === 0 ? "" : version;
  })();
  var PAGE_RELOAD_KEY = "pytodo_reloaded_for";

  // The server says, each time the page connects to it, which version
  // of the page it serves. A page looks for a new version of itself
  // when it is loaded and when it comes back into view; one that was
  // loaded from the service worker's store while the server was down,
  // and then stays in view, does neither, and went on running the old
  // page against the new server.
  //
  // Hearing of another version, the page takes it up: the service
  // worker fetches it, where there is one, and the page loads itself
  // again once nothing is open that a reload would discard. It does so
  // once for each version of the server, so that a version it cannot
  // take up, a worker that fails to install, does not make it reload
  // without end.
  function onServerPageVersion(version) {
    if (!version || !PAGE_VERSION || version === PAGE_VERSION) return;
    try {
      if (sessionStorage.getItem(PAGE_RELOAD_KEY) === version) return;
      sessionStorage.setItem(PAGE_RELOAD_KEY, version);
    } catch (e) {
      /* without the store, the reload below happens each time */
    }
    var registered =
      navigator.serviceWorker && location.protocol === "https:"
        ? navigator.serviceWorker.getRegistration()
        : Promise.resolve(null);
    registered
      .then(function (registration) {
        if (!registration) return null;
        return registration
          .update()
          .then(function () {
            return workerSettled(registration);
          });
      })
      .catch(function () {
        /* the worker could not be fetched; the reload is still tried */
      })
      .then(reloadForUpdateWhenIdle);
  }

  // Resolves when a worker that is being installed has taken over, or
  // has failed to; at once when none is.
  function workerSettled(registration) {
    var worker = registration.installing || registration.waiting;
    if (!worker) return Promise.resolve();
    return new Promise(function (resolve) {
      worker.addEventListener("statechange", function () {
        if (worker.state === "activated" || worker.state === "redundant") {
          resolve();
        }
      });
    });
  }

  // A new version of the page is running in the service worker. Load it,
  // once nothing is open that a reload would discard.
  var updateReloadTimer = null;
  function reloadForUpdateWhenIdle() {
    if (updateReloadTimer !== null) return;
    updateReloadTimer = setInterval(function () {
      if (!pageIsIdle()) return;
      clearInterval(updateReloadTimer);
      location.reload();
    }, 1000);
  }

  function pageIsIdle() {
    if (document.querySelector(".sheet:not(.hidden), .context-menu")) {
      return false;
    }
    if (Object.keys(pendingItemFields).length > 0) return false;
    // Text being typed, in the search field for one.
    var focused = document.activeElement;
    return !(
      focused &&
      focused.matches(
        "textarea, input:not([type=checkbox]):not([type=radio]):not([type=button])",
      )
    );
  }

  // Check for existing token — if none, show login; if valid, init app
  (async function () {
    var token = getAuthToken();
    if (!token) {
      // Try without token (server might have auth disabled)
      try {
        var resp = await fetch(API + "/status");
        if (resp.ok) {
          init();
          return;
        }
      } catch (e) {
        /* server unreachable */
      }
      showLoginScreen();
      return;
    }
    // Validate stored token
    try {
      var resp2 = await fetch(API + "/status", {
        headers: { Authorization: "Bearer " + token },
      });
      if (resp2.ok) {
        init();
        return;
      }
      // Token rejected (401) — clear it so user re-pairs
      if (resp2.status === 401) {
        localStorage.removeItem(AUTH_TOKEN_KEY);
      }
    } catch (e) {
      // Network error — could be cert issue with active service worker.
      // Unregister SW so the browser handles TLS directly (allows user
      // to accept self-signed cert warnings in Quick Connect mode).
      if (navigator.serviceWorker) {
        try {
          var regs = await navigator.serviceWorker.getRegistrations();
          for (var i = 0; i < regs.length; i++) {
            await regs[i].unregister();
          }
          // Clear caches too so stale content doesn't persist
          var cacheNames = await caches.keys();
          for (var j = 0; j < cacheNames.length; j++) {
            await caches.delete(cacheNames[j]);
          }
        } catch (swErr) {
          /* best effort */
        }
      }
    }
    showLoginScreen();
  })();
})();
