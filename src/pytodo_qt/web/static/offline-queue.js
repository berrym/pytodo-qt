/* PyTodo-Qt offline queue rules.
 *
 * The page keeps a change it could not send, and sends it when the
 * server answers again. This file holds the rules for that and nothing
 * else: no page, no storage, no network. app.js loads it in the page;
 * the tests load the same file under Node.
 *
 * A queued change is { path, opts, timestamp }: the API path, the
 * request (method, headers, body as a JSON string), and the time it was
 * queued, which also identifies it.
 *
 * Two things follow from the queue. What is sent: withChange combines a
 * new change with those already queued, withStepTakenBack undoes one
 * earlier step, and nextToSend, replyOutcome and withUpdatedAt govern
 * the sending. What is shown: the page draws
 * the server's last answer with the queued changes applied on top
 * (withQueuedChanges, boardWithQueuedChanges, and queuedAdds for tasks
 * that do not exist at the server yet), so that a change made without
 * the server is visible, and stays visible when the page is opened
 * again.
 */
(function (root) {
  "use strict";

  // The item a request is about: /items/<id> and /items/<id>/<action>.
  // A request that is not about one item (adding to a list) has none.
  function itemIdOf(path) {
    var match = /^\/items\/([0-9a-f-]+)/.exec(path || "");
    return match ? match[1] : null;
  }

  // A time for a new queued change that no queued change already has.
  function newTimestamp(queue, now) {
    var latest = 0;
    for (var i = 0; i < queue.length; i++) {
      if (queue[i].timestamp > latest) latest = queue[i].timestamp;
    }
    return now > latest ? now : latest + 1;
  }

  // What the server's answer means for a change:
  //   "sent"      applied
  //   "conflict"  the item was changed elsewhere since the page read it
  //   "refused"   the server will not accept it, now or later
  //   "kept"      not applied this time; worth sending again
  // A request that got no answer at all has no status, and is "kept".
  function replyOutcome(status) {
    if (status === undefined || status === null) return "kept";
    if (status >= 200 && status < 300) return "sent";
    if (status === 409) return "conflict";
    // Not signed in, timed out, asked to slow down, or a server fault.
    if (status === 401 || status === 408 || status === 429 || status >= 500) {
      return "kept";
    }
    return "refused";
  }

  // The next queued change to send: the first that has not been tried in
  // this run and is not behind a kept change to the same item, so that
  // changes to one item reach the server in the order they were made.
  function nextToSend(queue, tried, heldItems) {
    for (var i = 0; i < queue.length; i++) {
      var entry = queue[i];
      if (tried[entry.timestamp]) continue;
      var itemId = itemIdOf(entry.path);
      if (itemId && heldItems[itemId]) continue;
      return entry;
    }
    return null;
  }

  // The request of a queued change with its "last seen" time replaced.
  // The server refuses a change whose updated_at is older than the
  // item's; after an earlier queued change to the same item is applied,
  // the item's time is the one in that reply.
  function withUpdatedAt(opts, updatedAt) {
    if (!opts || typeof opts.body !== "string") return opts;
    var body;
    try {
      body = JSON.parse(opts.body);
    } catch (_) {
      return opts;
    }
    if (!body || body.updated_at === undefined) return opts;
    body.updated_at = updatedAt;
    var patched = {};
    for (var key in opts) patched[key] = opts[key];
    patched.body = JSON.stringify(body);
    return patched;
  }

  // What a queued change does: "toggle", "update", "move", "delete" or
  // "add"; null for a request the queue has no rule for.
  function kindOf(change) {
    var method = change.opts && change.opts.method;
    var path = change.path || "";
    if (itemIdOf(path)) {
      var action = path.replace(/^\/items\/[0-9a-f-]+/, "");
      if (method === "PATCH" && action === "/toggle") return "toggle";
      if (method === "PATCH" && action === "/move") return "move";
      if (method === "PUT" && action === "") return "update";
      if (method === "DELETE" && action === "") return "delete";
      return null;
    }
    if (method === "POST" && /^\/lists\/[0-9a-f-]+\/items$/.test(path)) {
      return "add";
    }
    return null;
  }

  function bodyOf(change) {
    if (!change.opts || typeof change.opts.body !== "string") return {};
    try {
      return JSON.parse(change.opts.body) || {};
    } catch (_) {
      return {};
    }
  }

  function copyOf(object) {
    var copy = {};
    for (var key in object) copy[key] = object[key];
    return copy;
  }

  // The queue with a change added. The given queue is not altered.
  //
  // A change is combined with what is already queued for the same item,
  // so that the queue holds what is to be done and not every step that
  // led there:
  //   - A tick on an item with a queued tick takes that tick back; the
  //     two would undo each other at the server, and here nothing is
  //     sent.
  //   - A field update that follows a field update is merged into it,
  //     the later value winning; a move that follows a move replaces
  //     its column. Only when it directly follows: an update either
  //     side of a tick stays where it was made, since a tick on a
  //     repeating task depends on the fields at that moment.
  //   - A delete takes every earlier change to the item with it.
  function withChange(queue, change) {
    var result = queue.slice();
    var kind = kindOf(change);
    var itemId = itemIdOf(change.path);
    if (!kind || !itemId) {
      result.push(change);
      return result;
    }
    var i;
    if (kind === "toggle") {
      for (i = 0; i < result.length; i++) {
        if (
          itemIdOf(result[i].path) === itemId &&
          kindOf(result[i]) === "toggle"
        ) {
          result.splice(i, 1);
          return result;
        }
      }
      result.push(change);
      return result;
    }
    if (kind === "delete") {
      result = result.filter(function (queued) {
        return itemIdOf(queued.path) !== itemId;
      });
      result.push(change);
      return result;
    }
    // update or move: the last queued change to this item, if any
    var previous = -1;
    for (i = result.length - 1; i >= 0; i--) {
      if (itemIdOf(result[i].path) === itemId) {
        previous = i;
        break;
      }
    }
    if (previous === -1 || kindOf(result[previous]) !== kind) {
      result.push(change);
      return result;
    }
    // Merged in place. The time the earlier change was based on stands:
    // the page has seen nothing newer from the server since.
    var merged = bodyOf(result[previous]);
    var added = bodyOf(change);
    for (var key in added) {
      if (key === "updated_at" && merged.updated_at !== undefined) continue;
      merged[key] = added[key];
    }
    var combined = copyOf(result[previous]);
    combined.opts = copyOf(combined.opts);
    combined.opts.body = JSON.stringify(merged);
    result[previous] = combined;
    return result;
  }

  // The queue with one earlier step taken back, and the changes made
  // since left in place. A step is the queue before it and after it.
  // The changes the step added are removed. Those it removed are put
  // back: a delete takes the earlier changes to its task with it, and a
  // task waiting to be added can be removed. They go back where they
  // were, the queue being in the order of its changes' times. The given
  // queues are not altered.
  //
  // null when the step is no longer in the queue: a change it added has
  // gone, sent to the server or taken back already, or nothing it
  // removed is still missing.
  //
  // For steps that add or remove whole changes. A change merged into an
  // earlier one keeps that one's time, and is not told apart here.
  function withStepTakenBack(queue, before, after) {
    function timesOf(changes) {
      var times = {};
      for (var n = 0; n < changes.length; n++)
        times[changes[n].timestamp] = true;
      return times;
    }
    var inQueue = timesOf(queue);
    var inBefore = timesOf(before);
    var inAfter = timesOf(after);
    var added = {};
    var i;
    for (i = 0; i < after.length; i++) {
      var time = after[i].timestamp;
      if (inBefore[time]) continue;
      if (!inQueue[time]) return null;
      added[time] = true;
    }
    var result = queue.filter(function (queued) {
      return !added[queued.timestamp];
    });
    var changed = result.length !== queue.length;
    for (i = 0; i < before.length; i++) {
      var removed = before[i];
      if (inAfter[removed.timestamp] || inQueue[removed.timestamp]) continue;
      var at = 0;
      while (at < result.length && result[at].timestamp < removed.timestamp)
        at++;
      result.splice(at, 0, removed);
      changed = true;
    }
    return changed ? result : null;
  }

  // The column the server gives an item that stops being complete: the
  // first, or the "in progress" one when time has been spent on it.
  // The server also looks at completed subtasks; the true column is
  // known once the change is sent.
  function incompleteColumn(item, boardColumns) {
    if (boardColumns.length >= 3 && item.time_spent > 0) {
      var middle = boardColumns.slice(1, -1);
      return middle.indexOf("In Progress") !== -1 ? "In Progress" : middle[0];
    }
    return boardColumns[0];
  }

  // The short text for how often an item repeats, as the server words it.
  function recurrenceLabel(type, interval) {
    if (!type) return "";
    var count = interval || 1;
    if (type === "minutely") return "Every " + count + " min";
    var single = {
      daily: "Daily",
      weekly: "Weekly",
      monthly: "Monthly",
      yearly: "Yearly",
    };
    if (count === 1) return single[type] || type;
    var units = {
      daily: "days",
      weekly: "weeks",
      monthly: "months",
      yearly: "years",
    };
    return "Every " + count + " " + (units[type] || "");
  }

  // What the page shows: the items as the server last gave them, with
  // the queued changes applied in order. An item with a queued change
  // carries unsent: true. The given items are not altered.
  //
  // boardColumns are the list's column names; the last is the one for
  // completed items. Without columns only the item's own fields change.
  //
  // A tick is shown as the person made it. For a repeating task the
  // server answers a tick by moving the task to its next date and
  // leaving it incomplete; that is shown once the change is sent.
  function withQueuedChanges(items, queue, boardColumns) {
    var columns = boardColumns || [];
    var lastColumn = columns.length > 0 ? columns[columns.length - 1] : null;
    var shown = (items || []).map(copyOf);

    function find(itemId) {
      for (var n = 0; n < shown.length; n++) {
        if (shown[n].id === itemId) return n;
      }
      return -1;
    }

    for (var i = 0; i < queue.length; i++) {
      var change = queue[i];
      var kind = kindOf(change);
      var at = find(itemIdOf(change.path));
      if (!kind || at === -1) continue;
      var item = shown[at];
      if (kind === "delete") {
        shown.splice(at, 1);
        continue;
      }
      if (kind === "toggle") {
        item.complete = !item.complete;
        if (lastColumn !== null) {
          if (item.complete) {
            item.board_column = lastColumn;
          } else if (item.board_column === lastColumn) {
            item.board_column = incompleteColumn(item, columns);
          }
        }
      } else if (kind === "move") {
        var column = bodyOf(change).column;
        if (columns.indexOf(column) !== -1) {
          var from = item.board_column;
          item.board_column = column;
          if (column === lastColumn) item.complete = true;
          else if (from === lastColumn) item.complete = false;
        }
      } else if (kind === "update") {
        var fields = bodyOf(change);
        for (var key in fields) {
          if (key !== "updated_at" && key !== "force") item[key] = fields[key];
        }
        if ("recurrence_type" in fields) {
          item.is_recurring = Boolean(item.recurrence_type);
          item.recurrence_display = recurrenceLabel(
            item.recurrence_type,
            item.recurrence_interval,
          );
        }
      }
      item.unsent = true;
    }
    return shown;
  }

  // Rows for the tasks waiting to be added to a list, in the order they
  // were added. A row has the text as it was typed: the dates, tags and
  // priority written in it are read by the server when the task is sent,
  // so until then it has no place in the list's sort and nothing can be
  // done to it but remove it. queued_at identifies its queued change.
  function queuedAdds(queue, listId) {
    var rows = [];
    for (var i = 0; i < queue.length; i++) {
      var change = queue[i];
      if (kindOf(change) !== "add") continue;
      if (change.path !== "/lists/" + listId + "/items") continue;
      rows.push({
        id: "unsent-" + change.timestamp,
        queued_at: change.timestamp,
        reminder: String(bodyOf(change).reminder || ""),
        provisional: true,
        unsent: true,
      });
    }
    return rows;
  }

  // The board as the page shows it: the cards of every column with the
  // queued changes applied, each in the column it then belongs to, and
  // the tasks waiting to be added at the top of the first column, where
  // the server puts a new task. The given board is not altered.
  function boardWithQueuedChanges(board, queue) {
    if (!board || !board.columns) return board;
    var names = board.board_columns || [];
    var cards = [];
    names.forEach(function (name) {
      (board.columns[name] || []).forEach(function (card) {
        var copy = copyOf(card);
        copy.board_column = name;
        cards.push(copy);
      });
    });
    var columns = {};
    names.forEach(function (name) {
      columns[name] = [];
    });
    withQueuedChanges(cards, queue, names).forEach(function (card) {
      if (card.subtasks && card.subtasks.length > 0) {
        card.subtasks = withQueuedChanges(card.subtasks, queue, []);
      }
      columns[card.board_column].push(card);
    });
    if (names.length > 0 && board.id) {
      columns[names[0]] = queuedAdds(queue, board.id).concat(columns[names[0]]);
    }
    var shown = copyOf(board);
    shown.columns = columns;
    return shown;
  }

  // Whether the copy of the queue kept in IndexedDB is the one to go
  // on from, and not the one in localStorage whose counter is localN.
  //
  // The queue is stored twice, with a counter that rises at every
  // save. A browser writes localStorage to disk some time after the
  // page's write: one that is killed in between starts again with an
  // earlier queue and an earlier counter, while IndexedDB has the
  // last. The higher counter is the later save, whatever its queue
  // holds: an empty one, saved when the last change had been sent,
  // keeps an earlier queue from being sent a second time.
  //
  // saved is the record read from IndexedDB, {n, queue}; anything
  // else (none kept, or one that cannot be made out) is not newer.
  function savedIsNewer(localN, saved) {
    return (
      Boolean(saved) &&
      typeof saved.n === "number" &&
      Array.isArray(saved.queue) &&
      saved.n > localN
    );
  }

  var rules = {
    itemIdOf: itemIdOf,
    kindOf: kindOf,
    withChange: withChange,
    withStepTakenBack: withStepTakenBack,
    withQueuedChanges: withQueuedChanges,
    queuedAdds: queuedAdds,
    boardWithQueuedChanges: boardWithQueuedChanges,
    newTimestamp: newTimestamp,
    replyOutcome: replyOutcome,
    nextToSend: nextToSend,
    withUpdatedAt: withUpdatedAt,
    savedIsNewer: savedIsNewer,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = rules;
  } else {
    root.PytodoOfflineQueue = rules;
  }
})(typeof self !== "undefined" ? self : this);
