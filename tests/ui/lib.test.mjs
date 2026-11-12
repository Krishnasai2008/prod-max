import test from "node:test";
import assert from "node:assert/strict";

import {
  esc,
  fmtMin,
  fmtClock,
  pct,
  relDay,
  relTime,
  routeOf,
  ROUTES,
  stateKey,
  shouldRender,
} from "../../pm/ui/lib.js";
import { STATE } from "./fixture.mjs";

test("esc escapes html and handles missing values", () => {
  assert.equal(
    esc('<img src=x onerror=alert(1)> & "q" \'a\''),
    "&lt;img src=x onerror=alert(1)&gt; &amp; &quot;q&quot; &#39;a&#39;",
  );
  assert.equal(esc(null), "");
  assert.equal(esc(5), "5");
});

test("fmtMin matches the cli duration format", () => {
  assert.equal(fmtMin(45), "45m");
  assert.equal(fmtMin(120), "2h");
  assert.equal(fmtMin(90), "1h30m");
  assert.equal(fmtMin(0), "0m");
});

test("fmtClock pads minutes and seconds", () => {
  assert.equal(fmtClock(2700), "0:45:00");
  assert.equal(fmtClock(43389), "12:03:09");
});

test("pct rounds to a whole percent", () => {
  assert.equal(pct(0.4), "40%");
  assert.equal(pct(0.005), "1%");
});

test("relDay compares calendar dates, not the wall clock", () => {
  assert.equal(relDay("2026-11-09", "2026-11-09"), "today");
  assert.equal(relDay("2026-11-10", "2026-11-09"), "tomorrow");
  assert.equal(relDay("2026-11-12", "2026-11-09"), "in 3 days");
  assert.equal(relDay("2026-11-08", "2026-11-09"), "yesterday");
  assert.equal(relDay("2026-11-07", "2026-11-09"), "2 days ago");
});

test("relTime counts minutes, hours, days and 30-day months", () => {
  assert.equal(relTime("2026-11-09T10:10:00", "2026-11-09T10:00:00"), "in 10m");
  assert.equal(relTime("2026-11-09T13:00:00", "2026-11-09T10:00:00"), "in 3h");
  assert.equal(relTime("2026-11-12T10:00:00", "2026-11-09T10:00:00"), "in 3d");
  assert.equal(relTime("2027-02-07T10:00:00", "2026-11-09T10:00:00"), "in 3mo");
  assert.equal(relTime("", "2026-11-09T10:00:00"), "");
});

test("routeOf falls back to today", () => {
  assert.deepEqual(ROUTES, ["today", "tasks", "review", "study", "risk", "stats", "bugs", "files", "settings", "spot", "exam", "practice"]);
  assert.equal(routeOf("#/tasks"), "tasks");
  assert.equal(routeOf("#/review"), "review");
  assert.equal(routeOf("#/study"), "study");
  assert.equal(routeOf(""), "today");
  assert.equal(routeOf("#/nope"), "today");
});

test("stateKey ignores the ticking clock", () => {
  const later = {
    ...STATE,
    now: "later",
    running: { ...STATE.running, elapsed_s: 9999 },
  };
  assert.equal(stateKey(STATE), stateKey(later));
  assert.notEqual(stateKey(STATE), stateKey({ ...STATE, running: null }));
  assert.notEqual(
    stateKey(STATE),
    stateKey({
      ...STATE,
      tasks: STATE.tasks.map((task, index) =>
        index === 0 ? { ...task, logged_min: task.logged_min + 1 } : task),
    }),
  );
});

test("shouldRender respects an equal key and the dirty flag", () => {
  assert.equal(shouldRender("a", "a", false), false);
  assert.equal(shouldRender("a", "b", false), true);
  assert.equal(shouldRender("a", "b", true), false);
});
