import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const H = 3600e3;
const { subjectOf, streakOf, heatCells, dayOf, shift } =
  load(["study.js", "today.js"], { path: "/stats/", expose: ["subjectOf", "streakOf", "heatCells", "dayOf", "shift"] });

test("the stats page is not a subject, so the clock never counts it", () => {
  assert.equal(subjectOf("/stats/"), "");
  assert.equal(subjectOf("/poe/exam-prep/x/"), "poe");
});

test("streakOf counts 2h+ days before today when today is short", () => {
  const now = new Date(2026, 10, 9, 15);
  const ms = { [dayOf(shift(now, -1))]: 2 * H, [dayOf(shift(now, -2))]: 3 * H, [dayOf(shift(now, -3))]: 2 * H, [dayOf(now)]: 0.5 * H };
  assert.equal(streakOf(d => ms[dayOf(d)] ?? 0, now), 3);
});

test("heatCells draws empty days", () => {
  assert.match(heatCells(() => 0, new Date(2026, 10, 9)), /data-level="none"/);
});
