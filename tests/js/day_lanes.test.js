// Where the web page's Week and Day put the bars of one day that share
// hours (_placeDayBars and its helpers in
// src/pytodo_qt/web/static/app.js), and the block that stands for the
// bars a Week's column has no lane for (#88).
// Run by tests/test_web_pwa.py with `node --test`.
//
// The functions are taken out of the page's script as text.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

// Lines end in a line feed here whatever the checkout gave them: on
// Windows git writes the file with a carriage return before each.
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
  const found = new RegExp("  var " + name + " = \\d+;").exec(source);
  assert.notEqual(found, null, name + " is in app.js");
  return found[0];
}

const page = new Function(
  "labels",
  [
    constantText("_LANE_MIN_WIDTH"),
    constantText("_LANE_GAP"),
    constantText("_BAR_INSET"),
    "function _themeColor(name, fallback) { return '#6c6c6c'; }",
    "function _paintLabelOn(ctx, text, tx, ty, zone) {",
    "  labels.push({ text: text, tx: tx, ty: ty, zone: zone, align: ctx.textAlign });",
    "}",
    functionText("_lanesThatFit"),
    functionText("_widthForLanes"),
    functionText("_mostLanes"),
    functionText("_placeDayBars"),
    functionText("_paintMoreBlock"),
    "return {",
    "  least: _LANE_MIN_WIDTH, gap: _LANE_GAP, inset: _BAR_INSET,",
    "  lanesThatFit: _lanesThatFit, widthForLanes: _widthForLanes,",
    "  mostLanes: _mostLanes, placeDayBars: _placeDayBars,",
    "  paintMoreBlock: _paintMoreBlock,",
    "};",
  ].join("\n"),
);

const labels = [];
const fn = page(labels);

function bar(id, start, end, lane, lanes) {
  return {
    item_id: id,
    start_minute: start,
    end_minute: end,
    is_marker: false,
    is_all_day: false,
    lane: lane,
    lanes: lanes,
  };
}

function near(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 1e-9, actual + " is " + expected);
}

// No two things placed in a column share any of it at a minute both
// are at.
function assertNothingCovered(placed) {
  const boxes = placed.bars
    .map((b) => ({
      x: b.x,
      w: b.w,
      start: b.seg.start_minute,
      end: b.seg.end_minute,
    }))
    .concat(
      placed.more.map((m) => ({
        x: m.x,
        w: m.w,
        start: m.start_minute,
        end: m.end_minute,
      })),
    );
  boxes.forEach((a, i) => {
    boxes.slice(i + 1).forEach((b) => {
      const sideBySide = a.x + a.w <= b.x + 1e-9 || b.x + b.w <= a.x + 1e-9;
      const apartInTime = a.end <= b.start || b.end <= a.start;
      assert.ok(sideBySide || apartInTime, JSON.stringify([a, b]));
    });
  });
}

test("the least width of a bar is the least size of something to tap", () => {
  assert.equal(fn.least, 24);
  assert.equal(fn.gap, 2);
  assert.equal(fn.inset, 2);
});

test("a column holds as many lanes as have 24 units each", () => {
  // The Week's column in a window 701 wide, 760 wide and 1280 wide,
  // and the Day's on a phone 412 wide, as measured in the browser.
  assert.equal(fn.lanesThatFit(90.4), 3);
  assert.equal(fn.lanesThatFit(98.9), 3);
  assert.equal(fn.lanesThatFit(173.1), 6);
  assert.equal(fn.lanesThatFit(344), 13);
  // Never fewer than one, however narrow.
  assert.equal(fn.lanesThatFit(10), 1);
});

test("a column of the width asked for n lanes holds n", () => {
  for (let lanes = 1; lanes <= 40; lanes++) {
    assert.equal(fn.lanesThatFit(fn.widthForLanes(lanes)), lanes);
    assert.equal(
      fn.lanesThatFit(fn.widthForLanes(lanes) - 1),
      Math.max(1, lanes - 1),
    );
  }
});

test("a bar alone keeps the column's width", () => {
  const placed = fn.placeDayBars([bar("a", 540, 600, 0, 1)], 50, 344);
  assert.deepEqual(placed.more, []);
  assert.equal(placed.bars.length, 1);
  // As it was drawn before bars had lanes: 2 in from each edge.
  assert.equal(placed.bars[0].x, 52);
  assert.equal(placed.bars[0].w, 340);
});

test("two bars that share hours have half the width each, a gap between", () => {
  const placed = fn.placeDayBars(
    [bar("a", 540, 600, 0, 2), bar("b", 570, 660, 1, 2)],
    50,
    344,
  );
  assert.equal(placed.bars[0].x, 52);
  assert.equal(placed.bars[0].w, 169);
  assert.equal(placed.bars[1].x, 52 + 169 + 2);
  assert.equal(placed.bars[1].w, 169);
  // The second ends where a bar alone ends.
  assert.equal(placed.bars[1].x + placed.bars[1].w, 50 + 344 - 2);
});

test("five bars at one time are five to be seen, none covering another", () => {
  // The case measured for the issue: five rectangles in one place.
  const five = [0, 1, 2, 3, 4].map((lane) =>
    bar("r" + lane, 840, 930, lane, 5),
  );
  const placed = fn.placeDayBars(five, 50, 344);
  assert.equal(placed.bars.length, 5);
  assert.deepEqual(placed.more, []);
  assertNothingCovered(placed);
  placed.bars.forEach((b) => near(b.w, (340 - 4 * 2) / 5));
});

test("markers and all-day chips are not of the hours", () => {
  const chip = bar("c", 0, 1440, null, null);
  chip.is_all_day = true;
  const marker = bar("m", 0, 1440, null, null);
  marker.is_marker = true;
  const placed = fn.placeDayBars(
    [chip, marker, bar("a", 540, 600, 0, 1)],
    50,
    344,
  );
  assert.deepEqual(
    placed.bars.map((b) => b.seg.item_id),
    ["a"],
  );
});

test("a server that sends no lanes: every bar at the full width, as before", () => {
  const a = bar("a", 540, 600, 0, 1);
  const b = bar("b", 570, 660, 0, 1);
  [a, b].forEach((seg) => {
    delete seg.lane;
    delete seg.lanes;
  });
  const placed = fn.placeDayBars(
    [a, b, bar("c", 700, 760, null, null)],
    50,
    344,
  );
  placed.bars.forEach((placedBar) => {
    assert.equal(placedBar.x, 52);
    assert.equal(placedBar.w, 340);
  });
});

test("a Week's column without the lanes says how many bars it has none for", () => {
  // Five at one time in a column 98.9 wide, which holds three lanes:
  // two bars, and a block for the other three.
  const five = [0, 1, 2, 3, 4].map((lane) =>
    bar("r" + lane, 840, 930, lane, 5),
  );
  const placed = fn.placeDayBars(five, 346.7, 98.9);
  assert.deepEqual(
    placed.bars.map((b) => b.seg.item_id),
    ["r0", "r1"],
  );
  assert.equal(placed.more.length, 1);
  const more = placed.more[0];
  assert.equal(more.count, 3);
  assert.equal(more.start_minute, 840);
  assert.equal(more.end_minute, 930);
  const lane = (98.9 - 4 - 2 * 2) / 3;
  near(placed.bars[0].w, lane);
  near(more.w, lane);
  near(more.x, 346.7 + 2 + 2 * (lane + 2));
  assert.ok(more.w >= 24);
  assertNothingCovered(placed);
});

test("no bar or block is narrower than the least width", () => {
  [90.4, 98.9, 120, 173.1, 264].forEach((colWidth) => {
    for (let lanes = 1; lanes <= 16; lanes++) {
      const bars = [];
      for (let lane = 0; lane < lanes; lane++) {
        bars.push(bar("b" + lane, 600, 660, lane, lanes));
      }
      const placed = fn.placeDayBars(bars, 50, colWidth);
      placed.bars.concat(placed.more).forEach((box) => {
        assert.ok(
          box.w >= 24,
          colWidth + " wide, " + lanes + " lanes: " + box.w,
        );
        assert.ok(box.x >= 50 + 2 - 1e-9);
        assert.ok(box.x + box.w <= 50 + colWidth - 2 + 1e-9);
      });
      // Every bar is drawn or counted.
      const counted = placed.more.reduce((sum, m) => sum + m.count, 0);
      assert.equal(placed.bars.length + counted, lanes);
      assertNothingCovered(placed);
    }
  });
});

test("a bar without a lane that is alone at its time is drawn as itself", () => {
  // Four lanes at 09:00 in a column for three: tracks A and B keep
  // their lanes, talks C and D are counted, and talk E, of the same
  // group and alone among them at 10:30, is a bar in the last lane.
  const placed = fn.placeDayBars(
    [
      bar("A", 540, 720, 0, 4),
      bar("B", 540, 720, 1, 4),
      bar("C", 540, 600, 2, 4),
      bar("D", 540, 600, 3, 4),
      bar("E", 630, 690, 2, 4),
    ],
    50,
    98.9,
  );
  assert.deepEqual(placed.bars.map((b) => b.seg.item_id).sort(), [
    "A",
    "B",
    "E",
  ]);
  assert.equal(placed.more.length, 1);
  assert.equal(placed.more[0].count, 2);
  assert.equal(placed.more[0].start_minute, 540);
  assert.equal(placed.more[0].end_minute, 600);
  const e = placed.bars.find((b) => b.seg.item_id === "E");
  near(e.x, placed.more[0].x);
  assertNothingCovered(placed);
});

test("bars without a lane at times apart have a block each", () => {
  const morning = [0, 1, 2, 3].map((lane) =>
    bar("m" + lane, 540, 600, lane, 4),
  );
  const evening = [0, 1, 2, 3, 4].map((lane) =>
    bar("e" + lane, 1080, 1140, lane, 5),
  );
  const placed = fn.placeDayBars(morning.concat(evening), 50, 98.9);
  assert.deepEqual(
    placed.more.map((m) => [m.start_minute, m.end_minute, m.count]),
    [
      [540, 600, 2],
      [1080, 1140, 3],
    ],
  );
});

test("a block covers the hours of all the bars it stands for", () => {
  // 09:00-10:00 and 09:30-11:00 share time: one block, 09:00-11:00.
  const placed = fn.placeDayBars(
    [
      bar("A", 540, 720, 0, 4),
      bar("B", 540, 720, 1, 4),
      bar("C", 540, 600, 2, 4),
      bar("D", 570, 660, 3, 4),
    ],
    50,
    98.9,
  );
  assert.deepEqual(
    placed.more.map((m) => [m.start_minute, m.end_minute, m.count]),
    [[540, 660, 2]],
  );
});

test("the Day is asked for the lanes of its widest group", () => {
  const data = {
    days: [
      {
        segments: [
          bar("a", 540, 600, 0, 2),
          bar("b", 540, 600, 1, 2),
          bar("c", 700, 760, 0, 1),
          Object.assign(bar("chip", 0, 1440, null, null), { is_all_day: true }),
        ],
      },
    ],
  };
  assert.equal(fn.mostLanes(data), 2);
  assert.equal(fn.mostLanes({ days: [{ segments: [] }] }), 1);
  // Fifteen at once on a phone: 50 for the hours' names and 392 for
  // the bars, more than the 394 the screen gave.
  assert.equal(50 + fn.widthForLanes(15), 442);
});

test("the block is the count, and a tap on it is for the day", () => {
  const fills = [];
  const ctx = {
    fillStyle: "",
    font: "",
    textAlign: "start",
    fillRect(x, y, w, h) {
      fills.push({ x: x, y: y, w: w, h: h, color: this.fillStyle });
    },
  };
  const hits = [];
  labels.length = 0;
  fn.paintMoreBlock(
    ctx,
    hits,
    "2030-06-15",
    { count: 3, x: 100, w: 30 },
    420,
    45,
  );
  assert.deepEqual(fills, [{ x: 100, y: 420, w: 30, h: 45, color: "#6c6c6c" }]);
  assert.equal(labels.length, 1);
  assert.equal(labels[0].text, "+3");
  // Written about the block's middle, on the block's own color.
  assert.equal(labels[0].tx, 115);
  assert.equal(labels[0].align, "center");
  assert.equal(labels[0].zone.fill, "#6c6c6c");
  assert.equal(ctx.textAlign, "start");
  assert.deepEqual(hits, [{ x: 100, y: 420, w: 30, h: 45, day: "2030-06-15" }]);
});

test("a block too low for text is still there to tap", () => {
  const ctx = { fillStyle: "", font: "", textAlign: "start", fillRect() {} };
  const hits = [];
  labels.length = 0;
  fn.paintMoreBlock(ctx, hits, "2030-06-15", { count: 2, x: 100, w: 30 }, 0, 5);
  assert.equal(labels.length, 0);
  assert.equal(hits.length, 1);
});
