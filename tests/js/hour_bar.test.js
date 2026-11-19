// What the web page's Week and Day draw for a bar and its deviation zone
// (_paintHourBar and _paintHatch of src/pytodo_qt/web/static/app.js).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The two functions are taken out of the page's script as text and run
// against a canvas that records what is drawn on it.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

// Lines end in a line feed here whatever the checkout gave them: on
// Windows git writes the file with a carriage return before each.
const source = fs
  .readFileSync(
    path.join(__dirname, "..", "..", "src", "pytodo_qt", "web", "static", "app.js"),
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

const BASE = "#059669";
const HATCH = "#450a0a";

// A canvas context that records filled rectangles and the lines
// stroked, with the clip in force for each.
function recordingContext() {
  const ctx = {
    fills: [],
    hatches: [],
    labels: [],
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
    font: "",
    _clip: null,
    _stack: [],
    _path: [],
    _rect: null,
    save() {
      this._stack.push(this._clip);
    },
    restore() {
      this._clip = this._stack.pop();
    },
    beginPath() {
      this._path = [];
      this._rect = null;
    },
    rect(x, y, w, h) {
      this._rect = { x: x, y: y, w: w, h: h };
    },
    clip() {
      this._clip = this._rect;
    },
    moveTo(x, y) {
      this._path.push({ from: [x, y] });
    },
    lineTo(x, y) {
      this._path[this._path.length - 1].to = [x, y];
    },
    stroke() {
      this.hatches.push({
        color: this.strokeStyle,
        clip: this._clip,
        lines: this._path,
      });
    },
    fillRect(x, y, w, h) {
      this.fills.push({ x: x, y: y, w: w, h: h, color: this.fillStyle });
    },
    fillText() {},
  };
  return ctx;
}

const paint = new Function(
  "ctx",
  "hitRects",
  "item",
  "seg",
  "x",
  "y",
  "w",
  "h",
  "labels",
  [
    "function _paletteColor(state) { return '" + BASE + "'; }",
    "function _paletteDeviation(state) { return '" + HATCH + "'; }",
    "function _barTextColor(fill) { return '#ffffff'; }",
    "function _paintLabelOn(ctx, text, tx, ty, zone) { labels.push(zone); }",
    "var _BAR_LABEL_BAND = 16;",
    functionText("_paintHatch"),
    functionText("_paintHourBar"),
    "_paintHourBar(ctx, hitRects, item, seg, x, y, w, h);",
  ].join("\n"),
);

// A bar as the page draws it: 60 units of height to the hour.
function draw(seg) {
  const ctx = recordingContext();
  const hits = [];
  const labels = [];
  const y = seg.start_minute;
  const h = seg.end_minute - seg.start_minute;
  paint(ctx, hits, { reminder: "Task" }, seg, 100, y, 80, h, labels);
  return { ctx: ctx, hits: hits, labels: labels };
}

function segment(fields) {
  return Object.assign(
    {
      item_id: "a",
      start_minute: 360,
      end_minute: 420,
      state: "completed_ontime",
      clipped_top: false,
      clipped_bottom: false,
      zone_start_minute: null,
      zone_end_minute: null,
    },
    fields,
  );
}

test("a bar without a zone is its color and no hatch", () => {
  const drawn = draw(segment({}));
  assert.deepEqual(drawn.ctx.fills[0], { x: 100, y: 360, w: 80, h: 60, color: BASE });
  assert.equal(drawn.ctx.hatches.length, 0);
});

test("a bar finished late is hatched from its planned end to its end", () => {
  const drawn = draw(
    segment({
      end_minute: 460,
      state: "completed_late",
      zone_start_minute: 420,
      zone_end_minute: 460,
    }),
  );
  // The whole bar in its color, to the completion.
  assert.deepEqual(drawn.ctx.fills[0], { x: 100, y: 360, w: 80, h: 100, color: BASE });
  assert.equal(drawn.ctx.hatches.length, 1);
  const hatch = drawn.ctx.hatches[0];
  assert.equal(hatch.color, HATCH);
  assert.deepEqual(hatch.clip, { x: 100, y: 420, w: 80, h: 40 });
  assert.ok(hatch.lines.length > 5);
});

test("a bar finished early is hatched from the completion to its end", () => {
  const drawn = draw(
    segment({
      start_minute: 780,
      end_minute: 900,
      state: "completed_early",
      zone_start_minute: 840,
      zone_end_minute: 900,
    }),
  );
  // Across the bar's whole width, at the time of the completion: the
  // zone was a part of the width before, whatever the time.
  assert.deepEqual(drawn.ctx.hatches[0].clip, { x: 100, y: 840, w: 80, h: 60 });
});

test("the two zones are hatched in different directions", () => {
  const late = draw(
    segment({
      end_minute: 480,
      state: "completed_late",
      zone_start_minute: 420,
      zone_end_minute: 480,
    }),
  ).ctx.hatches[0].lines[0];
  const early = draw(
    segment({
      state: "completed_early",
      zone_start_minute: 380,
      zone_end_minute: 420,
    }),
  ).ctx.hatches[0].lines[0];
  const falls = (line) => line.to[1] > line.from[1];
  assert.equal(falls(late), true);
  assert.equal(falls(early), false);
});

test("no hatch is drawn behind the label", () => {
  // All of the bar is zone, as on the day a task was finished late.
  const drawn = draw(
    segment({
      start_minute: 0,
      end_minute: 600,
      state: "completed_late",
      clipped_top: true,
      zone_start_minute: 0,
      zone_end_minute: 600,
    }),
  );
  assert.deepEqual(drawn.ctx.hatches[0].clip, { x: 100, y: 16, w: 80, h: 584 });
  // The label is written once, on the bar's color.
  assert.equal(drawn.labels.length, 1);
  assert.equal(drawn.labels[0].fill, BASE);
});

test("a zone that would lie behind the label alone is not drawn", () => {
  const drawn = draw(
    segment({
      start_minute: 0,
      end_minute: 30,
      state: "completed_late",
      zone_start_minute: 0,
      zone_end_minute: 10,
    }),
  );
  assert.equal(drawn.ctx.hatches.length, 0);
});

test("the whole bar opens the task, its zone with it", () => {
  const drawn = draw(
    segment({
      end_minute: 460,
      state: "completed_late",
      zone_start_minute: 420,
      zone_end_minute: 460,
    }),
  );
  assert.deepEqual(drawn.hits, [{ x: 100, y: 360, w: 80, h: 100, item_id: "a" }]);
});

test("a segment from a server that sends no zone is drawn as before", () => {
  const seg = segment({ state: "completed_late" });
  delete seg.zone_start_minute;
  delete seg.zone_end_minute;
  const drawn = draw(seg);
  assert.equal(drawn.ctx.hatches.length, 0);
  assert.equal(drawn.ctx.fills[0].color, BASE);
});
