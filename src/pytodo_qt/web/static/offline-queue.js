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

  var rules = {
    itemIdOf: itemIdOf,
    newTimestamp: newTimestamp,
    replyOutcome: replyOutcome,
    nextToSend: nextToSend,
    withUpdatedAt: withUpdatedAt,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = rules;
  } else {
    root.PytodoOfflineQueue = rules;
  }
})(typeof self !== "undefined" ? self : this);
