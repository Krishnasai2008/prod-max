import test from "node:test";
import assert from "node:assert/strict";

import {
  LEVELS,
  barRows,
  dayOf,
  heatCells,
  level,
  monday,
  shift,
  spark,
  streakOf,
  table,
} from "../../pm/ui/charts.js";

const H = 3600e3;
const NOW = new Date(2026, 10, 9, 15);
const day = (k) => dayOf(shift(NOW, k));

test("dayOf is the local date, zero padded", () => {
  assert.equal(dayOf(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
  assert.equal(dayOf(NOW), "2026-11-09");
});

test("shift moves days across months and years", () => {
  assert.equal(dayOf(shift(new Date(2026, 0, 31), 1)), "2026-02-01");
  assert.equal(dayOf(shift(new Date(2026, 0, 1), -1)), "2025-12-31");
});

test("monday is the Monday of that week", () => {
  assert.equal(dayOf(monday(NOW)), "2026-11-09");
  assert.equal(dayOf(monday(shift(NOW, 1))), "2026-11-09");
  assert.equal(dayOf(monday(shift(NOW, 6))), "2026-11-09");
  assert.equal(dayOf(monday(shift(NOW, 7))), "2026-11-16");
});

test("the levels are 2h green, 4h orange, 6h red, and some from a minute", () => {
  assert.deepEqual(LEVELS, [
    [6, "red"],
    [4, "orange"],
    [2, "green"],
  ]);
  assert.equal(level(0), "none");
  assert.equal(level(30e3), "none");
  assert.equal(level(60e3), "some");
  assert.equal(level(2 * H), "green");
  assert.equal(level(3.9 * H), "green");
  assert.equal(level(4 * H), "orange");
  assert.equal(level(6 * H), "red");
});

test("streakOf counts 2h+ days before today when today is short", () => {
  const ms = {
    [day(-1)]: 2 * H,
    [day(-2)]: 3 * H,
    [day(-3)]: 2 * H,
    [day(0)]: 0.5 * H,
  };
  assert.equal(streakOf((date) => ms[dayOf(date)] ?? 0, NOW), 3);
});

test("streakOf counts today once it reaches 2h", () => {
  const ms = { [day(0)]: 2 * H, [day(-1)]: 2 * H, [day(-2)]: 1 * H };
  assert.equal(streakOf((date) => ms[dayOf(date)] ?? 0, NOW), 2);
  assert.equal(streakOf(() => 0, NOW), 0);
});

test("heatCells draws empty days and never the future", () => {
  const out = heatCells(() => 0, NOW);
  assert.match(out, /data-level="none"/);
  assert.match(out, /<i hidden><\/i>/);
  assert.ok(!out.includes("NaN"));
  assert.equal((out.match(/<i /g) ?? []).length, 26 * 7);
});

test("heatCells colours a 2h day green and titles it", () => {
  const out = heatCells((date) => (dayOf(date) === day(-1) ? 2 * H : 0), NOW);
  assert.match(out, /data-level="green"/);
  assert.match(out, /: 2h 00m"/);
});

test("spark needs two points and escapes its label", () => {
  assert.equal(spark([1], "x"), "");
  assert.match(spark([0, 2, 1], "x"), /<polyline points="/);
  assert.ok(spark([1, 2], "<b>x</b>").includes('aria-label="&lt;b&gt;x&lt;/b&gt;"'));
});

test("barRows labels rows, scales to the top value and escapes labels", () => {
  const out = barRows(
    [
      ["os", 4],
      ["<b>x</b>", 2],
    ],
    (value) => `${value}h`,
  );
  assert.equal((out.match(/class="study-row"/g) ?? []).length, 2);
  assert.ok(out.includes(">os</span>"));
  assert.ok(out.includes("&lt;b&gt;x&lt;/b&gt;"));
  assert.ok(out.includes("width:100.0%"));
  assert.ok(out.includes("width:50.0%"));
  assert.ok(out.includes("<b>4h</b>"));
});

test("table builds a head and rows", () => {
  const out = table(["A", "B"], [["x", "y"]]);
  assert.equal(
    out,
    "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>x</td><td>y</td></tr></tbody></table>",
  );
});

test("table labels cells for the phone layout and escapes the label", () => {
  const out = table(["A", "B"], [["x", "y"]], ["a", "<b>"]);
  assert.ok(out.includes('<td data-label="a">x</td>'));
  assert.ok(out.includes('<td data-label="&lt;b&gt;">y</td>'));
});
