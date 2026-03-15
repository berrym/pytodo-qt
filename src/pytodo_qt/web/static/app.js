/* PyTodo-Qt Web UI — SPA with hash routing, dual view, and offline support */
(function () {
  "use strict";

  var API = "/api";
  var OFFLINE_QUEUE_KEY = "pytodo_offline_queue";
  var VIEW_MODE_KEY = "pytodo_view_mode";
  var INSTALL_DISMISSED_KEY = "pytodo_install_dismissed";

  var currentListId = null;
  var cachedLists = [];
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

  // ====================================================================
  // DOM refs
  // ====================================================================

  var offlineBanner = document.getElementById("offline-banner");
  var connectionDot = document.getElementById("connection-dot");
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

  // ====================================================================
  // Accessibility: keyboard & focus management
  // ====================================================================

  // Escape key closes any open sheet or context menu
  document.addEventListener("keydown", function (e) {
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
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length === 0) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    sheet._focusTrapHandler = function (e) {
      if (e.key !== "Tab") return;
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
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
    var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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

  async function api(path, opts) {
    var resp = await fetch(API + path, opts);
    if (!resp.ok) {
      var err = await resp.json().catch(function () { return {}; });
      throw new Error(err.error || resp.statusText);
    }
    return resp.json();
  }

  // ====================================================================
  // IndexedDB cache (offline data persistence)
  // ====================================================================

  var IDB_NAME = "pytodo_cache";
  var IDB_VERSION = 1;
  var idb = null;

  function openIDB() {
    return new Promise(function (resolve) {
      if (idb) { resolve(idb); return; }
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
      req.onsuccess = function (e) { idb = e.target.result; resolve(idb); };
      req.onerror = function () { resolve(null); }; // Graceful degradation
    });
  }

  async function cacheListsData(lists) {
    var db = await openIDB();
    if (!db) return;
    try {
      var tx = db.transaction("lists", "readwrite");
      var store = tx.objectStore("lists");
      store.clear();
      lists.forEach(function (lst) { store.put(lst); });
    } catch (e) { /* best-effort */ }
  }

  async function getCachedLists() {
    var db = await openIDB();
    if (!db) return null;
    return new Promise(function (resolve) {
      try {
        var tx = db.transaction("lists", "readonly");
        var req = tx.objectStore("lists").getAll();
        req.onsuccess = function () { resolve(req.result); };
        req.onerror = function () { resolve(null); };
      } catch (e) { resolve(null); }
    });
  }

  async function cacheListItems(listId, items) {
    var db = await openIDB();
    if (!db) return;
    try {
      var tx = db.transaction("listItems", "readwrite");
      tx.objectStore("listItems").put({ listId: listId, items: items });
    } catch (e) { /* best-effort */ }
  }

  async function getCachedListItems(listId) {
    var db = await openIDB();
    if (!db) return null;
    return new Promise(function (resolve) {
      try {
        var tx = db.transaction("listItems", "readonly");
        var req = tx.objectStore("listItems").get(listId);
        req.onsuccess = function () { resolve(req.result ? req.result.items : null); };
        req.onerror = function () { resolve(null); };
      } catch (e) { resolve(null); }
    });
  }

  // ====================================================================
  // Offline queue
  // ====================================================================

  function getOfflineQueue() {
    try { return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]"); }
    catch (e) { return []; }
  }

  function saveOfflineQueue(queue) {
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
    updatePendingBadge();
  }

  function enqueueOfflineEdit(path, opts) {
    var queue = getOfflineQueue();
    queue.push({ path: path, opts: opts, timestamp: Date.now() });
    saveOfflineQueue(queue);
  }

  function removeFromOfflineQueue(index) {
    var queue = getOfflineQueue();
    queue.splice(index, 1);
    saveOfflineQueue(queue);
  }

  async function replayOfflineQueue() {
    var queue = getOfflineQueue();
    if (queue.length === 0) return;
    showToast("Syncing " + queue.length + " offline change" + (queue.length > 1 ? "s" : "") + "...");
    var remaining = [];
    for (var i = 0; i < queue.length; i++) {
      try { await fetch(API + queue[i].path, queue[i].opts); }
      catch (e) { remaining.push(queue[i]); }
    }
    saveOfflineQueue(remaining);
    if (remaining.length === 0) {
      showToast("All changes synced");
      await refreshCurrentList();
    } else {
      showToast(remaining.length + " change" + (remaining.length > 1 ? "s" : "") + " still pending");
    }
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
    if (connectionDot) {
      connectionDot.classList.toggle("online", online);
      connectionDot.classList.toggle("offline", !online);
      connectionDot.title = online ? "Connected" : "Offline";
    }
    updatePendingBadge();
  }

  window.addEventListener("online", function () {
    updateOnlineStatus(true);
    replayOfflineQueue();
    refreshCurrentList();
    startPolling();
  });

  window.addEventListener("offline", function () {
    updateOnlineStatus(false);
    stopPolling();
  });

  // ====================================================================
  // Hash routing
  // ====================================================================

  function getRoute() {
    var hash = location.hash || "#/";
    if (hash === "#" || hash === "#/") return { view: "home", id: null };
    if (hash.startsWith("#/search")) return { view: "search", id: null };
    if (hash.startsWith("#/settings")) return { view: "settings", id: null };
    if (hash.startsWith("#/item/")) return { view: "item", id: hash.substring(7) };
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
        viewEl.classList.add(toIdx > fromIdx ? "slide-in-right" : "slide-in-left");
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
    if (headerTitle) headerTitle.textContent = titles[activeView] || "PyTodo-Qt";

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
    if (listView) listView.classList.toggle("active", mode === "list");
    if (boardView) boardView.classList.toggle("active", mode === "board");

    viewBtns.forEach(function (btn) {
      btn.classList.toggle("active", btn.dataset.view === mode);
    });

    if (mode === "board") {
      refreshBoard(true);
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
      setViewMode(viewMode === "list" ? "board" : "list");
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

  // Fetch sort tiers from API (non-blocking, falls back to defaults)
  function fetchSortTiers() {
    fetch(API + "/sort")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (data) {
        if (data && data.sort_tiers && data.sort_tiers.length === 3) {
          currentSortTiers = data.sort_tiers;
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
    var labels = { completion: "Completion", due_date: "Due Date", priority: "Priority" };
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
      sortDirBtns[j].textContent = currentSortTiers[j].reverse ? "\u2193" : "\u2191";
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
    var payload = { tiers: currentSortTiers };
    fetch(API + "/sort", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(function () {
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
    sortTierSelects[si].addEventListener("change", (function (changedIdx) {
      return function () {
        var newDim = sortTierSelects[changedIdx].value;
        // Find if another tier already has this dimension
        for (var k = 0; k < currentSortTiers.length; k++) {
          if (k !== changedIdx && currentSortTiers[k].dimension === newDim) {
            // Swap: give the other tier the dimension we're leaving
            currentSortTiers[k].dimension = currentSortTiers[changedIdx].dimension;
            break;
          }
        }
        currentSortTiers[changedIdx].dimension = newDim;
        syncSortSheetUI();
        saveSortTiers();
      };
    })(si));
  }

  // Direction toggle buttons
  for (var di = 0; di < sortDirBtns.length; di++) {
    sortDirBtns[di].addEventListener("click", (function (tierIdx) {
      return function () {
        currentSortTiers[tierIdx].reverse = !currentSortTiers[tierIdx].reverse;
        syncSortSheetUI();
        saveSortTiers();
      };
    })(di));
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
      try { navigator.vibrate(duration || 10); } catch (e) { /* best-effort */ }
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
    backdrop.addEventListener("click", function () { closeContextMenu(); });
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
    cancelBtn.addEventListener("click", function () { closeContextMenu(); });
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

    var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) {
      menu.remove();
      return;
    }
    menu.classList.add("closing");
    setTimeout(function () { menu.remove(); }, 150);
  }

  // ====================================================================
  // Long-press detection
  // ====================================================================

  /**
   * Attach long-press detection to an element.
   * @param {Element} el - Target element
   * @param {Function} onLongPress - Called with the original event when long-press fires
   */
  function attachLongPress(el, onLongPress) {
    var timer = null;
    var startX = 0, startY = 0;
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
        fired = true;
        el.classList.remove("long-press-active");
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
      if (timer) { clearTimeout(timer); timer = null; }
      el.classList.remove("long-press-active");
    }

    function onUp(e) {
      cancel();
      // Prevent tap from firing after long-press
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
      onTap: function () { location.hash = "#/item/" + item.id; }
    });

    // Toggle complete
    actions.push({
      icon: item.complete ? "\u25CB" : "\u2713",
      label: item.complete ? "Mark Incomplete" : "Mark Complete",
      onTap: function () { onToggle(item.id); }
    });

    actions.push({ divider: true });

    // Set priority sub-menu
    var priorities = [
      { label: "High", value: 1, icon: "\u{1F534}" },
      { label: "Normal", value: 2, icon: "\u{1F535}" },
      { label: "Low", value: 3, icon: "\u26AA" }
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
          }
        };
      })
    });

    // Move to column sub-menu (if board data is available)
    if (cachedBoardData && cachedBoardData.board_columns && cachedBoardData.board_columns.length > 0) {
      var columns = cachedBoardData.board_columns;
      actions.push({
        icon: "\u{1F4CB}",
        label: "Move to Column",
        submenu: columns.map(function (col) {
          return {
            icon: col === columns[0] ? "\u{1F4E5}" : col === columns[columns.length - 1] ? "\u2705" : "\u25AB",
            label: col,
            checked: item.board_column === col,
            onTap: function () {
              moveToColumn(item.id, col);
            }
          };
        })
      });
    }

    actions.push({ divider: true });

    // Delete
    actions.push({
      icon: "\u{1F5D1}\uFE0F",
      label: "Delete",
      danger: true,
      onTap: function () {
        var cardEl = document.querySelector('[data-id="' + item.id + '"]');
        onDeleteWithUndo(item.id, item.reminder, cardEl);
      }
    });

    return actions;
  }

  async function setPriority(itemId, priority) {
    var path = "/items/" + itemId;
    var opts = {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priority: priority })
    };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      return;
    }
    try {
      await api(path, opts);
      await refreshCurrentList();
    } catch (e) {
      enqueueOfflineEdit(path, opts);
    }
  }

  async function moveToColumn(itemId, column) {
    var path = "/items/" + itemId + "/move";
    var opts = {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ column: column })
    };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      return;
    }
    try {
      await api(path, opts);
      await refreshCurrentList();
      showToast("Moved to " + column);
    } catch (e) {
      enqueueOfflineEdit(path, opts);
    }
  }

  function openItemContextMenu(item) {
    var title = item.reminder.length > 40
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
      onTap: function () { promptRenameColumn(colName); }
    });

    // WIP limit (middle columns only)
    if (!isFirst && !isLast) {
      actions.push({
        icon: "\u{1F522}",
        label: "Set WIP Limit",
        onTap: function () { promptWipLimit(colName); }
      });
    }

    // Delete (middle columns only, min 3 total)
    if (!isFirst && !isLast && totalColumns > 3) {
      actions.push({ divider: true });
      var firstCol = cachedBoardData ? cachedBoardData.board_columns[0] : "first column";
      actions.push({
        icon: "\u{1F5D1}\uFE0F",
        label: "Delete",
        danger: true,
        onTap: function () {
          var msg = itemCount > 0
            ? itemCount + " item" + (itemCount > 1 ? "s" : "") + ' will be moved to "' + firstCol + '"'
            : "This column is empty";
          showContextMenu("Delete \"" + colName + "\"?", [
            { label: msg },
            { divider: true },
            {
              icon: "\u{1F5D1}\uFE0F",
              label: "Delete Column",
              danger: true,
              onTap: function () { deleteColumn(colName); }
            }
          ]);
        }
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
    var currentLimit = (cachedBoardData && cachedBoardData.wip_limits)
      ? cachedBoardData.wip_limits[colName] || 0 : 0;
    var input = prompt("WIP limit for \"" + colName + "\" (0 = no limit):", String(currentLimit));
    if (input === null) return;
    var limit = parseInt(input, 10);
    if (isNaN(limit) || limit < 0 || limit > 99) {
      showToast("WIP limit must be 0\u201399");
      return;
    }
    setWipLimit(colName, limit);
  }

  async function renameColumn(oldName, newName) {
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "rename", old_name: oldName, new_name: newName })
      });
      await refreshCurrentList();
      showToast("Renamed to \"" + newName + "\"");
    } catch (e) {
      showToast("Rename failed: " + e.message);
    }
  }

  async function setWipLimit(colName, limit) {
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "set_wip_limit", name: colName, limit: limit })
      });
      await refreshCurrentList();
      showToast(limit > 0 ? "WIP limit set to " + limit : "WIP limit removed");
    } catch (e) {
      showToast("Failed: " + e.message);
    }
  }

  async function deleteColumn(colName) {
    try {
      await api("/lists/" + currentListId + "/columns", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "remove", name: colName })
      });
      await refreshCurrentList();
      showToast("Column \"" + colName + "\" deleted");
    } catch (e) {
      showToast("Delete failed: " + e.message);
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
      var isActive = JSON.stringify(currentCols) === JSON.stringify(preset.columns);
      return {
        icon: isActive ? "\u2713" : "\u25AB",
        label: preset.name,
        checked: isActive,
        onTap: function () { applyPreset(preset.columns, preset.name); }
      };
    });

    showContextMenu("Board Layout", actions);
  }

  async function applyPreset(columns, presetName) {
    try {
      var result = await api("/lists/" + currentListId + "/apply-preset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ columns: columns })
      });
      await refreshCurrentList();
      var msg = "Applied \"" + presetName + "\"";
      if (result.remapped > 0) {
        msg += " (" + result.remapped + " item" + (result.remapped > 1 ? "s" : "") + " remapped)";
      }
      showToast(msg);
    } catch (e) {
      showToast("Failed: " + e.message);
    }
  }

  // ====================================================================
  // Pick-up-and-place move mode (board cards)
  // ====================================================================

  var moveMode = null; // { itemId, itemReminder, sourceColumn }

  function enterMoveMode(itemId, itemReminder, sourceColumn) {
    if (moveMode) exitMoveMode();
    moveMode = { itemId: itemId, itemReminder: itemReminder, sourceColumn: sourceColumn };
    haptic(15);
    renderMoveUI();
  }

  function exitMoveMode() {
    moveMode = null;
    // Remove banner
    var banner = document.querySelector(".move-banner");
    if (banner) banner.remove();
    // Remove drop zones and held state
    document.querySelectorAll(".board-drop-zone").forEach(function (z) { z.remove(); });
    document.querySelectorAll(".board-card.held").forEach(function (c) { c.classList.remove("held"); });
    // Remove sort indicators
    document.querySelectorAll(".board-sort-indicator").forEach(function (s) { s.remove(); });
  }

  function renderMoveUI() {
    if (!moveMode || !boardContainer) return;

    // Mark held card
    var heldCard = boardContainer.querySelector('[data-id="' + moveMode.itemId + '"]');
    if (heldCard) heldCard.classList.add("held");

    // Add move banner above board
    var existing = document.querySelector(".move-banner");
    if (existing) existing.remove();
    var banner = document.createElement("div");
    banner.className = "move-banner";
    banner.setAttribute("aria-live", "polite");
    var bannerText = document.createElement("span");
    bannerText.className = "move-banner-text";
    var truncated = moveMode.itemReminder.length > 30
      ? moveMode.itemReminder.substring(0, 30) + "\u2026"
      : moveMode.itemReminder;
    bannerText.textContent = "Moving: " + truncated;
    banner.appendChild(bannerText);
    var cancelBtn = document.createElement("button");
    cancelBtn.className = "move-banner-cancel";
    cancelBtn.textContent = "\u2715 Cancel";
    cancelBtn.addEventListener("click", function () { exitMoveMode(); });
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
      var colItems = (cachedBoardData && cachedBoardData.columns) ? cachedBoardData.columns[colName] || [] : [];
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
        if (movingKey[k] !== otherKey[k]) { cmp = movingKey[k] < otherKey[k] ? -1 : 1; break; }
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
    var isCompletionCol = boardColumns.length > 0 && targetColumn === boardColumns[boardColumns.length - 1];
    var wasInCompletionCol = boardColumns.length > 0 && sourceColumn === boardColumns[boardColumns.length - 1];
    exitMoveMode();

    try {
      await api("/items/" + itemId + "/move", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ column: targetColumn })
      });
      await refreshCurrentList();
      var msg = "Moved to \"" + targetColumn + "\"";
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
    var startX = 0, startY = 0;
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
        moveMode = { itemId: dragItem.id, itemReminder: dragItem.reminder, sourceColumn: dragItem.board_column };
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
      ghostEl.style.left = (ev.clientX - 40) + "px";
      ghostEl.style.top = (ev.clientY - 20) + "px";
    }

    function updateDragPosition(ev) {
      updateGhostPosition(ev);
      // Highlight drop zone under cursor
      var zones = document.querySelectorAll(".board-drop-zone");
      zones.forEach(function (z) {
        var rect = z.getBoundingClientRect();
        var over = ev.clientX >= rect.left && ev.clientX <= rect.right &&
                   ev.clientY >= rect.top && ev.clientY <= rect.bottom;
        z.classList.toggle("drag-over", over);
      });
      // Update auto-scroll reference
      if (scrollInterval) {
        autoScrollBoard._lastEv = ev;
      }
    }

    function endDirectDrag(ev) {
      if (scrollInterval) { clearInterval(scrollInterval); scrollInterval = null; }
      // Find drop zone under cursor
      var targetCol = null;
      var zones = document.querySelectorAll(".board-drop-zone");
      zones.forEach(function (z) {
        var rect = z.getBoundingClientRect();
        if (ev.clientX >= rect.left && ev.clientX <= rect.right &&
            ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
          targetCol = z.dataset.column;
        }
      });

      // Clean up
      if (ghostEl) { ghostEl.remove(); ghostEl = null; }
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
    var startX = 0, startY = 0, currentX = 0;
    var swiping = false, locked = false;
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
      if (e.target.closest(".item-checkbox, .item-actions, button")) return;
      startX = e.clientX;
      startY = e.clientY;
      currentX = 0;
      swiping = false;
      locked = false;
      el.style.transition = "none";
    });

    el.addEventListener("pointermove", function (e) {
      if (locked) return;
      var dx = e.clientX - startX;
      var dy = e.clientY - startY;

      // Lock direction after 10px movement
      if (!swiping && Math.abs(dx) > 10) {
        if (Math.abs(dy) > Math.abs(dx)) { locked = true; return; }
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
        onDeleteWithUndo(itemId, itemReminder, el);
      }
    });

    el.addEventListener("pointercancel", function () {
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
    var startY = 0, pulling = false, refreshing = false;

    viewHome.addEventListener("touchstart", function (e) {
      if (refreshing) return;
      // Only trigger when scrolled to top
      var scrollTop = document.getElementById("main").scrollTop || window.scrollY;
      if (scrollTop > 5) return;
      startY = e.touches[0].clientY;
      pulling = true;
    }, { passive: true });

    viewHome.addEventListener("touchmove", function (e) {
      if (!pulling || refreshing) return;
      var dy = e.touches[0].clientY - startY;
      if (dy > 60 && ptrIndicator) {
        ptrIndicator.classList.add("active");
      }
    }, { passive: true });

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

  function formatDueDate(dateStr, timeStr, complete) {
    if (!dateStr) return null;
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var due = new Date(dateStr + "T00:00:00");
    var diff = Math.floor((due - today) / 86400000);
    var timeSuffix = timeStr ? " " + timeStr.substring(0, 5) : "";

    if (complete) {
      return { text: dateStr.substring(5) + timeSuffix, cls: "" };
    }
    if (diff < 0) {
      return { text: "Overdue (" + Math.abs(diff) + "d)" + timeSuffix, cls: "overdue" };
    }
    if (diff === 0) {
      return { text: "Today" + timeSuffix, cls: "today" };
    }
    if (diff === 1) {
      return { text: "Tomorrow" + timeSuffix, cls: "upcoming" };
    }
    if (diff < 7) {
      var days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
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

  function renderItems(items, force) {
    if (!itemsContainer) return;

    // Skip re-render if data hasn't changed (eliminates poll flicker)
    var fp = fingerprint(items);
    if (!force && fp === lastItemsFingerprint) return;
    lastItemsFingerprint = fp;

    itemsContainer.innerHTML = "";
    if (!items || items.length === 0) {
      if (emptyMsg) emptyMsg.classList.remove("hidden");
      return;
    }
    if (emptyMsg) emptyMsg.classList.add("hidden");

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
      itemsContainer.appendChild(createItemCard(item, items));
      var children = childMap[item.id];
      if (children) {
        sortItems(children).forEach(function (child) {
          var el = createItemCard(child, items);
          el.classList.add("subtask");
          itemsContainer.appendChild(el);
        });
      }
    });
  }

  function createItemCard(item, allItems) {
    var div = document.createElement("div");
    var pClass = item.priority === 1 ? "priority-high" : item.priority === 3 ? "priority-low" : "priority-normal";
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
    cb.addEventListener("click", function (e) { e.stopPropagation(); });
    cb.addEventListener("change", function (e) {
      e.stopPropagation();
      haptic(10);
      cb.classList.add("bounce");
      setTimeout(function () { cb.classList.remove("bounce"); }, 150);
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

    var dueInfo = formatDueDate(item.due_date, item.due_time, item.complete);
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
      rec.textContent = "\u{1F504}";
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
      pom.textContent = item.pomodoro_count + "/" + item.estimated_pomodoros + " \u{1F345}";
      meta.appendChild(pom);
    } else if (item.pomodoro_count > 0) {
      var pomC = document.createElement("span");
      pomC.className = "item-pomodoro";
      pomC.textContent = item.pomodoro_count + " \u{1F345}";
      meta.appendChild(pomC);
    }

    // Subtask progress badge
    if (!item.parent_id && allItems) {
      var childCount = 0, childDone = 0;
      allItems.forEach(function (i) {
        if (i.parent_id === item.id) { childCount++; if (i.complete) childDone++; }
      });
      if (childCount > 0) {
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
      onDeleteWithUndo(item.id, item.reminder, div);
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

    // Enter animation
    div.classList.add("item-enter");

    return div;
  }

  // ====================================================================
  // Render: kanban board view
  // ====================================================================

  async function refreshBoard(force) {
    if (!currentListId) return;
    try {
      cachedBoardData = await api("/lists/" + currentListId + "/board");
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
        itemsDiv.appendChild(createBoardCard(item));
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
    var existingDots = boardContainer.parentElement.querySelector(".board-dots");
    if (existingDots) existingDots.remove();
    if (data.board_columns.length > 1) {
      var dots = document.createElement("div");
      dots.className = "board-dots";
      data.board_columns.forEach(function (_, idx) {
        var dot = document.createElement("div");
        dot.className = "board-dot" + (idx === 0 ? " active" : "");
        dots.appendChild(dot);
      });
      boardContainer.parentElement.insertBefore(dots, boardContainer.nextSibling);

      // Update dots on scroll
      boardContainer.addEventListener("scroll", function () {
        var scrollLeft = boardContainer.scrollLeft;
        var colWidth = boardContainer.firstElementChild ? boardContainer.firstElementChild.offsetWidth + 12 : 1;
        var activeIdx = Math.round(scrollLeft / colWidth);
        dots.querySelectorAll(".board-dot").forEach(function (d, i) {
          d.classList.toggle("active", i === activeIdx);
        });
      });
    }
  }

  function createBoardCard(item) {
    var card = document.createElement("div");
    var pClass = item.priority === 1 ? "priority-high" : item.priority === 3 ? "priority-low" : "priority-normal";
    card.className = "board-card " + pClass;
    if (item.complete) card.classList.add("completed");
    card.dataset.id = item.id;

    var text = document.createElement("div");
    text.className = "board-card-text";
    text.textContent = item.reminder;
    card.appendChild(text);

    var meta = document.createElement("div");
    meta.className = "board-card-meta";

    var dueInfo = formatDueDate(item.due_date, item.due_time, item.complete);
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

    if (meta.childNodes.length > 0) card.appendChild(meta);

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
    addSheet.querySelector(".sheet-backdrop").addEventListener("click", closeAddSheet);
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

      if (!isOnline) {
        enqueueOfflineEdit(path, opts);
        closeAddSheet();
        showToast("Added (offline)");
        return;
      }

      try {
        await api(path, opts);
        closeAddSheet();
        await refreshCurrentList();
        showToast("Task added");
      } catch (err) {
        enqueueOfflineEdit(path, opts);
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
      if (cachedItems[i].id === itemId) { item = cachedItems[i]; break; }
    }
    if (!item) {
      // Try fetching
      detailSheet.classList.add("hidden");
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
    statusBtn.textContent = item.complete ? "\u2713 Completed" : "Mark Complete";
    statusBtn.addEventListener("click", async function () {
      await onToggle(itemId);
      // Re-open with updated data
      for (var j = 0; j < cachedItems.length; j++) {
        if (cachedItems[j].id === itemId) { openDetailSheet(itemId); break; }
      }
    });
    statusDiv.appendChild(statusBtn);
    detailBody.appendChild(statusDiv);

    // Reminder
    var reminderField = makeField("Task", "textarea", item.reminder, function (val) {
      saveItemField(itemId, { reminder: val });
    });
    detailBody.appendChild(reminderField);

    // Priority
    var prioDiv = document.createElement("div");
    prioDiv.className = "detail-field";
    var prioLabel = document.createElement("label");
    prioLabel.textContent = "Priority";
    prioDiv.appendChild(prioLabel);
    var prioBtns = document.createElement("div");
    prioBtns.className = "detail-priority-btns";
    [{ label: "High", value: 1, cls: "active-high" },
     { label: "Normal", value: 2, cls: "active-normal" },
     { label: "Low", value: 3, cls: "active-low" }].forEach(function (p) {
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
    detailBody.appendChild(makeField("Due Date", "date", item.due_date || "", function (val) {
      saveItemField(itemId, { due_date: val || null });
    }));

    // Due time
    detailBody.appendChild(makeField("Due Time", "time", item.due_time ? item.due_time.substring(0, 5) : "", function (val) {
      saveItemField(itemId, { due_time: val ? val + ":00" : null });
    }));

    // Tags
    detailBody.appendChild(makeField("Tags", "text", (item.tags || []).join(", "), function (val) {
      var tags = val.split(",").map(function (t) { return t.trim(); }).filter(Boolean);
      saveItemField(itemId, { tags: tags });
    }));

    // Board column
    if (cachedBoardData && cachedBoardData.board_columns && cachedBoardData.board_columns.length > 0) {
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
    [{ label: "None", value: "" }, { label: "Daily", value: "daily" },
     { label: "Weekly", value: "weekly" }, { label: "Monthly", value: "monthly" },
     { label: "Yearly", value: "yearly" }].forEach(function (opt) {
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
      saveItemField(itemId, { recurrence_type: val, recurrence_interval: parseInt(recIntervalInput.value) || 1 });
    });
    recIntervalInput.addEventListener("change", function () {
      saveItemField(itemId, { recurrence_interval: parseInt(recIntervalInput.value) || 1 });
    });

    // Recurrence end conditions (only show if recurring)
    if (item.recurrence_type) {
      var endDiv = document.createElement("div");
      endDiv.className = "detail-recurrence-end";
      endDiv.appendChild(makeField("End After (count)", "number", item.recurrence_end_count || "", function (val) {
        saveItemField(itemId, { recurrence_end_count: parseInt(val) || null });
      }));
      endDiv.appendChild(makeField("End Date", "date", item.recurrence_end_date || "", function (val) {
        saveItemField(itemId, { recurrence_end_date: val || null });
      }));
      if (item.recurrence_count > 0) {
        var countInfo = document.createElement("div");
        countInfo.className = "detail-meta";
        countInfo.textContent = item.recurrence_count + " completed occurrences";
        endDiv.appendChild(countInfo);
      }
      recDiv.appendChild(endDiv);
    }
    detailBody.appendChild(recDiv);

    // Estimated pomodoros
    detailBody.appendChild(makeField("Pomodoro Estimate", "number", item.estimated_pomodoros || "", function (val) {
      saveItemField(itemId, { estimated_pomodoros: parseInt(val) || 0 });
    }));

    // Pomodoro progress (read-only)
    if (item.pomodoro_count > 0 || item.estimated_pomodoros > 0) {
      var pomInfo = document.createElement("div");
      pomInfo.className = "detail-meta";
      var total = item.pomodoro_count * 25;
      pomInfo.textContent = item.pomodoro_count + " sessions completed (" + total + " min focused)";
      detailBody.appendChild(pomInfo);
    }

    // Subtasks
    var subtaskDiv = document.createElement("div");
    subtaskDiv.className = "detail-field";
    var subtaskLabel = document.createElement("label");
    subtaskLabel.textContent = "Subtasks";
    subtaskDiv.appendChild(subtaskLabel);

    var children = cachedItems.filter(function (i) { return i.parent_id === itemId; });
    if (children.length > 0) {
      var subtaskList = document.createElement("div");
      subtaskList.className = "detail-subtask-list";
      children.forEach(function (child) {
        var row = document.createElement("div");
        row.className = "detail-subtask-row" + (child.complete ? " completed" : "");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = child.complete;
        cb.addEventListener("change", function () { onToggle(child.id); });
        row.appendChild(cb);
        var text = document.createElement("span");
        text.textContent = child.reminder;
        text.addEventListener("click", function () { openDetailSheet(child.id); });
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
      if (e.key === "Enter") { e.preventDefault(); addSubBtn.click(); }
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
    metaDiv.innerHTML = "Created: " + new Date(item.created_at).toLocaleDateString() +
      "<br>Updated: " + new Date(item.updated_at).toLocaleDateString();
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
      onDelete(itemId, item.reminder);
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
    input.addEventListener("change", function () { onChange(input.value); });
    if (type === "text" || type === "textarea") {
      input.addEventListener("blur", function () { onChange(input.value); });
    }
    div.appendChild(input);
    return div;
  }

  function saveItemField(itemId, fields) {
    clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(async function () {
      var indicator = document.getElementById("detail-save-indicator");
      if (indicator) indicator.textContent = "Saving...";
      try {
        await api("/items/" + itemId, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fields),
        });
        if (indicator) indicator.textContent = "Saved \u2713";
        setTimeout(function () { if (indicator) indicator.textContent = ""; }, 2000);
        await refreshCurrentList();
      } catch (e) {
        if (indicator) indicator.textContent = "Save failed";
      }
    }, 500);
  }

  function closeDetailSheet() {
    animateSheetClose(detailSheet, function () {
      if (location.hash.startsWith("#/item/")) location.hash = "#/";
    });
  }

  if (detailClose) detailClose.addEventListener("click", closeDetailSheet);
  if (detailSheet) {
    detailSheet.querySelector(".sheet-backdrop").addEventListener("click", closeDetailSheet);
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
    } catch (e) { allTags = []; }
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
          chip.parentElement.querySelectorAll(".chip").forEach(function (c) { c.classList.remove("active"); });
          chip.classList.add("active");
          searchFilters.priority = value;
        }
      } else if (filterType === "due") {
        if (chip.classList.contains("active")) {
          chip.classList.remove("active");
          searchFilters.due = null;
        } else {
          chip.parentElement.querySelectorAll(".chip").forEach(function (c) { c.classList.remove("active"); });
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
        if (searchFilters.priority) params.push("priority=" + searchFilters.priority);
        if (searchFilters.status !== "all") params.push("status=" + searchFilters.status);
        if (searchFilters.due) params.push("due=" + searchFilters.due);
        if (searchFilters.tags) params.push("tags=" + encodeURIComponent(searchFilters.tags));
        var url = "/lists/" + lst.id + (params.length ? "?" + params.join("&") : "");
        var data = await api(url);
        if (data.items && data.items.length > 0) {
          results.push({ list: lst, items: data.items });
        }
      } catch (e) { /* skip failed lists */ }
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
        groupDiv.appendChild(createItemCard(item, null));
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
      connStatus.textContent = isOnline ? "Connected" : "Offline";
      connStatus.className = "settings-value " + (isOnline ? "settings-conn-online" : "settings-conn-offline");
    }
    var serverUrl = document.getElementById("settings-server-url");
    if (serverUrl) serverUrl.textContent = location.host;

    // Offline queue
    var offlineRow = document.getElementById("settings-offline-row");
    var offlineCount = document.getElementById("settings-offline-count");
    var queueSection = document.getElementById("settings-queue-section");
    var queue = getOfflineQueue();
    if (offlineRow) offlineRow.style.display = queue.length > 0 ? "flex" : "none";
    if (offlineCount) offlineCount.textContent = String(queue.length);
    if (queueSection) queueSection.style.display = queue.length > 0 ? "block" : "none";
    renderQueueList(queue);

    // Display info
    var themeEl = document.getElementById("settings-theme");
    if (themeEl) {
      var isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      themeEl.textContent = isDark ? "Dark (system)" : "Light (system)";
    }
    var viewModeEl = document.getElementById("settings-view-mode");
    if (viewModeEl) viewModeEl.textContent = viewMode === "board" ? "Board" : "List";

    // Server data
    try {
      var data = await api("/status");
      if (settingsStatus) {
        settingsStatus.textContent =
          data.list_count + " lists \u00B7 " +
          data.total_completed + "/" + data.total_items + " completed";
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
        meta.textContent = item.list_name + " \u00B7 " + formatDeletedAgo(item.deleted_ago_ms);
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
      showToast("Offline queue cleared");
      refreshSettings();
    });
  }

  // ====================================================================
  // Event handlers
  // ====================================================================

  async function onToggle(itemId) {
    var path = "/items/" + itemId + "/toggle";
    var opts = { method: "PATCH" };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      return;
    }
    try {
      await api(path, opts);
      await refreshCurrentList();
    } catch (e) {
      enqueueOfflineEdit(path, opts);
    }
  }

  async function onDelete(itemId, reminderText) {
    var path = "/items/" + itemId;
    var opts = { method: "DELETE" };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      showToast("Deleted (offline)");
      return;
    }
    try {
      await api(path, opts);
      await refreshCurrentList();
      showToast(reminderText ? '"' + reminderText + '" deleted' : "Item deleted");
    } catch (e) {
      enqueueOfflineEdit(path, opts);
    }
  }

  // Delete with undo (delayed delete)
  var pendingDeletes = {};

  function onDeleteWithUndo(itemId, reminderText, cardEl) {
    // Animate card removal
    if (cardEl) {
      cardEl.classList.add("item-exit");
    }
    haptic(10);

    // Set up a delayed delete (5 seconds — generous window to undo)
    var timer = setTimeout(function () {
      delete pendingDeletes[itemId];
      onDelete(itemId, null); // silent delete, no toast
    }, 5000);

    pendingDeletes[itemId] = timer;

    showToast(reminderText ? '"' + reminderText + '" deleted' : "Item deleted", function () {
      // Undo callback
      clearTimeout(pendingDeletes[itemId]);
      delete pendingDeletes[itemId];
      haptic(10);
      refreshCurrentList();
    });
  }

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
    setTimeout(function () {
      toast.remove();
    }, undoCallback ? 5500 : 3000);
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
      var current = lists.find(function (l) { return l.id === currentListId; });
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
      var pct = lst.item_count > 0 ? Math.round(lst.completed_count / lst.item_count * 100) : 0;
      stats.textContent = lst.completed_count + "/" + lst.item_count + " done (" + pct + "%)";
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
        try {
          await api("/lists/" + listId, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName }),
          });
          showToast("List renamed");
          await refreshLists();
          renderListSheetBody(cachedLists);
        } catch (e) {
          showToast("Failed to rename list");
          nameEl.textContent = currentName;
        }
      } else {
        nameEl.textContent = currentName;
      }
    }

    input.addEventListener("blur", commitRename);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") { nameEl.textContent = currentName; }
    });
  }

  function confirmDeleteList(listId, name, itemCount) {
    var msg = 'Delete "' + name + '"';
    if (itemCount > 0) msg += " and its " + itemCount + " item" + (itemCount > 1 ? "s" : "") + "?";
    else msg += "?";

    if (!confirm(msg)) return;

    (async function () {
      try {
        await api("/lists/" + listId, { method: "DELETE" });
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
        showToast("Failed to delete list");
      }
    })();
  }

  // Wiring
  if (listPickerBtn) listPickerBtn.addEventListener("click", openListSheet);
  if (listSheetClose) listSheetClose.addEventListener("click", closeListSheet);
  if (listSheet) {
    listSheet.querySelector(".sheet-backdrop").addEventListener("click", closeListSheet);
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
      if (e.key === "Enter") { e.preventDefault(); listCreateBtn.click(); }
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
      cachedItems = [];
      renderItems([]);
      return;
    }
    try {
      var data = await api("/lists/" + currentListId);
      cachedItems = data.items || [];
      cachedBoardData = {
        board_columns: data.board_columns || [],
        wip_limits: data.wip_limits || {},
        columns: null,
      };

      // Cache for offline use
      cacheListItems(currentListId, cachedItems);

      if (viewMode === "board") {
        await refreshBoard();
      } else {
        renderItems(cachedItems);
      }

      // Refresh list selector counts
      await refreshLists();
    } catch (e) {
      console.error("Failed to load list:", e);
      // Fall back to IndexedDB cache
      var cached = await getCachedListItems(currentListId);
      if (cached) {
        cachedItems = cached;
        renderItems(cachedItems);
      } else {
        cachedItems = [];
        renderItems([]);
      }
    }
  }

  // ====================================================================
  // Polling
  // ====================================================================

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(function () {
      refreshCurrentList();
    }, 3000);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else {
      refreshCurrentList();
      startPolling();
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
      installText.innerHTML = "Tap <b>Share</b> \u2192 <b>Add to Home Screen</b> for quick access";
    } else {
      installText.innerHTML = "Tap <b>\u22ee</b> menu \u2192 <b>Add to Home Screen</b> for quick access";
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
    await refreshLists();
    await refreshCurrentList();
    onRouteChange();
    setViewMode(viewMode);
    startPolling();
  }

  init();
})();
