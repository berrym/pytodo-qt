/* PyTodo-Qt Web UI — Client-side logic */
(function () {
  "use strict";

  const API = "/api";
  var OFFLINE_QUEUE_KEY = "pytodo_offline_queue";
  let currentListId = null;
  let pollTimer = null;
  let isOnline = navigator.onLine;

  // DOM refs
  const listSelect = document.getElementById("list-select");
  const addForm = document.getElementById("add-form");
  const addInput = document.getElementById("add-input");
  const itemsContainer = document.getElementById("items-container");
  const emptyMsg = document.getElementById("empty-msg");
  const statusText = document.getElementById("status-text");
  const offlineBanner = document.getElementById("offline-banner");

  // --- API helpers ---

  async function api(path, opts) {
    const resp = await fetch(API + path, opts);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || resp.statusText);
    }
    return resp.json();
  }

  async function getLists() {
    const data = await api("/lists");
    return data.lists;
  }

  async function getList(id) {
    return api("/lists/" + id);
  }

  async function addItem(listId, reminder) {
    return api("/lists/" + listId + "/items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reminder: reminder }),
    });
  }

  async function toggleItem(itemId) {
    return api("/items/" + itemId + "/toggle", { method: "PATCH" });
  }

  async function deleteItem(itemId) {
    return api("/items/" + itemId, { method: "DELETE" });
  }

  // --- Offline queue ---

  function getOfflineQueue() {
    try {
      return JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function saveOfflineQueue(queue) {
    localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
  }

  function enqueueOfflineEdit(path, opts) {
    var queue = getOfflineQueue();
    queue.push({ path: path, opts: opts, timestamp: Date.now() });
    saveOfflineQueue(queue);
  }

  async function replayOfflineQueue() {
    var queue = getOfflineQueue();
    if (queue.length === 0) return;

    var remaining = [];
    for (var i = 0; i < queue.length; i++) {
      try {
        await fetch(API + queue[i].path, queue[i].opts);
      } catch (e) {
        remaining.push(queue[i]);
      }
    }
    saveOfflineQueue(remaining);
    if (remaining.length === 0) {
      await refreshCurrentList();
    }
  }

  function updateOnlineStatus(online) {
    isOnline = online;
    if (offlineBanner) {
      if (online) {
        offlineBanner.classList.add("hidden");
      } else {
        offlineBanner.classList.remove("hidden");
      }
    }
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

  // --- Rendering ---

  function renderLists(lists) {
    listSelect.innerHTML = "";
    lists.forEach(function (lst) {
      const opt = document.createElement("option");
      opt.value = lst.id;
      opt.textContent = lst.name + " (" + lst.completed_count + "/" + lst.item_count + ")";
      listSelect.appendChild(opt);
    });

    // Restore selection or pick first
    if (currentListId && lists.some(function (l) { return l.id === currentListId; })) {
      listSelect.value = currentListId;
    } else if (lists.length > 0) {
      currentListId = lists[0].id;
      listSelect.value = currentListId;
    }
  }

  function renderItems(items) {
    itemsContainer.innerHTML = "";

    if (items.length === 0) {
      emptyMsg.classList.remove("hidden");
      return;
    }
    emptyMsg.classList.add("hidden");

    // Sort: incomplete first, then by priority (1=high first), then by reminder
    items.sort(function (a, b) {
      if (a.complete !== b.complete) return a.complete ? 1 : -1;
      if (a.priority !== b.priority) return a.priority - b.priority;
      return a.reminder.localeCompare(b.reminder);
    });

    items.forEach(function (item) {
      var el = createItemElement(item);
      itemsContainer.appendChild(el);
    });
  }

  function createItemElement(item) {
    var div = document.createElement("div");
    div.className = "item" + (item.complete ? " completed" : "");
    div.dataset.id = item.id;

    // Priority dot
    var priority = document.createElement("span");
    var pClass = item.priority === 1 ? "high" : item.priority === 3 ? "low" : "normal";
    priority.className = "priority-badge " + pClass;
    div.appendChild(priority);

    // Checkbox
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "item-checkbox";
    cb.checked = item.complete;
    cb.addEventListener("change", function () {
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

    // Meta row (due date, tags)
    var meta = document.createElement("div");
    meta.className = "item-meta";

    if (item.due_date) {
      var due = document.createElement("span");
      due.className = "item-due";
      var dateStr = item.due_date;
      if (item.due_time) {
        dateStr += " " + item.due_time.substring(0, 5);
      }
      due.textContent = dateStr;
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

    if (meta.childNodes.length > 0) {
      content.appendChild(meta);
    }

    div.appendChild(content);

    // Delete button
    var actions = document.createElement("div");
    actions.className = "item-actions";
    var delBtn = document.createElement("button");
    delBtn.className = "delete";
    delBtn.textContent = "\u00D7";
    delBtn.title = "Delete";
    delBtn.addEventListener("click", function () {
      onDelete(item.id);
    });
    actions.appendChild(delBtn);
    div.appendChild(actions);

    return div;
  }

  // --- Event handlers ---

  async function onToggle(itemId) {
    var path = "/items/" + itemId + "/toggle";
    var opts = { method: "PATCH" };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      return;
    }
    try {
      await toggleItem(itemId);
      await refreshCurrentList();
    } catch (e) {
      enqueueOfflineEdit(path, opts);
      console.error("Toggle failed:", e);
    }
  }

  async function onDelete(itemId) {
    var path = "/items/" + itemId;
    var opts = { method: "DELETE" };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      return;
    }
    try {
      await deleteItem(itemId);
      await refreshCurrentList();
    } catch (e) {
      enqueueOfflineEdit(path, opts);
      console.error("Delete failed:", e);
    }
  }

  addForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    var text = addInput.value.trim();
    if (!text || !currentListId) return;

    var path = "/lists/" + currentListId + "/items";
    var opts = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reminder: text }),
    };
    if (!isOnline) {
      enqueueOfflineEdit(path, opts);
      addInput.value = "";
      return;
    }
    try {
      await addItem(currentListId, text);
      addInput.value = "";
      await refreshCurrentList();
    } catch (err) {
      enqueueOfflineEdit(path, opts);
      addInput.value = "";
      console.error("Add failed:", err);
    }
  });

  listSelect.addEventListener("change", function () {
    currentListId = listSelect.value;
    refreshCurrentList();
  });

  // --- Data loading ---

  async function refreshLists() {
    try {
      var lists = await getLists();
      renderLists(lists);
      updateStatus(lists);
    } catch (e) {
      console.error("Failed to load lists:", e);
    }
  }

  async function refreshCurrentList() {
    if (!currentListId) {
      renderItems([]);
      return;
    }
    try {
      var data = await getList(currentListId);
      renderItems(data.items);
      // Also refresh list selector counts
      await refreshLists();
    } catch (e) {
      console.error("Failed to load list:", e);
      renderItems([]);
    }
  }

  function updateStatus(lists) {
    var total = 0;
    var completed = 0;
    lists.forEach(function (l) {
      total += l.item_count;
      completed += l.completed_count;
    });
    statusText.textContent =
      lists.length + " lists \u00B7 " + completed + "/" + total + " completed";
  }

  // --- Polling ---

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

  // Pause polling when tab is hidden
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      stopPolling();
    } else {
      refreshCurrentList();
      startPolling();
    }
  });

  // --- Init ---

  async function init() {
    await refreshLists();
    await refreshCurrentList();
    startPolling();
  }

  init();
})();
