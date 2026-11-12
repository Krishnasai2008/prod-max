import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const H = 3600e3;
const { pmStatsHtml, spark, dayOf, shift } =
  load(["study.js", "today.js", "pmstats.js"], { path: "/stats/", expose: ["pmStatsHtml", "spark", "dayOf", "shift"] });
const NOW = new Date(2026, 10, 9, 15);
const day = k => dayOf(shift(NOW, k));
const EVIL = "<img src=x onerror=alert(1)> & co";

const FIXTURE = {
  version: 1, generated: "2026-11-09T14:00:00", settings: { hours_per_day: 4, peak: "09-12" },
  days: {
    [day(0)]: { min: 60, deep: 60, peak: 30, reviews: 0, recalled: 0, fails: 2, fixes: 1 },
    [day(-1)]: { min: 30, deep: 0, peak: 0, reviews: 5, recalled: 4, fails: 0, fixes: 0 },
    [day(-2)]: { min: 0, deep: 0, peak: 0, reviews: 3, recalled: 3, fails: 1, fixes: 0 },
    [day(-3)]: { min: 0, deep: 0, peak: 0, reviews: 2, recalled: 1, fails: 0, fixes: 0 },
  },
  time: { by_course: { os: 90 }, by_kind: { lab: 90 }, by_energy: { deep: 60, shallow: 30 } },
  estimates: { kinds: [{ kind: "all", n: 2, median: 1.8 }],
               history: [{ done: day(-2), title: "a", kind: "lab", ratio: 1.5 }, { done: day(-1), title: "b", kind: "lab", ratio: 2.1 }] },
  deadlines: { crunch: 0.31, on_time: 4, late: 1,
               open: [{ title: EVIL, course: "os", due: day(3), p_late: 0.4, start_by: day(1), behind: false }],
               recent: [{ title: "c", due: day(-5), done: day(-4), late: true }] },
  study: { reviews: 10, brier: 0.182, due_now: 7, bins: [{ lo: 60, hi: 80, n: 10, said: 0.7, recalled: 0.6 }],
           topics: [{ course: "os", name: "paging", exam: day(20), weight: 2, mastery: 0.45 }] },
  bugs: { fixed: 1, open: 1, abandoned: 0, lost_min: 25, untagged: 0, tags: [["off-by-one", 3]], bursts: [["off-by-one", 3]],
          recent: [{ id: 2, prog: "make", status: "fixed", fails: 2, lost_min: 25, tags: ["off-by-one"], opened: day(0) }] },
};

test("no pm data: notes streak and heatmap, plus a hint", () => {
  const html = pmStatsHtml(null, {}, NOW);
  assert.match(html, /No pm data yet/);
  assert.match(html, /study-heat/);
});

test("a day is the larger of notes time and pm time, never the sum", () => {
  assert.match(pmStatsHtml(FIXTURE, { [day(0)]: { poe: 3 * H } }, NOW), /Today<\/small><b[^>]*>3h 00m</);
  assert.match(pmStatsHtml(FIXTURE, { [day(0)]: { poe: 1 * H } }, NOW), /Today<\/small><b[^>]*>1h 00m</);
});

test("titles are text, never HTML", () => {
  const html = pmStatsHtml(FIXTURE, {}, NOW);
  assert.ok(!html.includes("<img"), "raw <img must not appear");
  assert.match(html, /&#60;img src=x onerror=alert\(1\)&#62; &#38; co/);
});

test("review streak counts days with a review, ending yesterday when today has none", () => {
  assert.match(pmStatsHtml(FIXTURE, {}, NOW), /Review streak<\/small><b>3 days</);
});

test("every section shows up", () => {
  const html = pmStatsHtml(FIXTURE, {}, NOW);
  for (const s of ["Time", "Estimates", "Deadlines", "Study", "Code issues", "off-by-one", "×1.80", "31%", "paging", "updated 1h 00m ago"])
    assert.ok(html.includes(s), s);
});

test("spark needs two points", () => {
  assert.equal(spark([1], "x"), "");
  assert.match(spark([0, 2, 1], "x"), /<polyline points="/);
});

test("updated time never goes negative, and old data reads in days", () => {
  assert.match(pmStatsHtml({ ...FIXTURE, generated: "2026-11-09T18:00:00" }, {}, NOW), /updated just now/);
  assert.match(pmStatsHtml({ ...FIXTURE, generated: "2026-11-06T09:00:00" }, {}, NOW), /updated 3 days ago/);
});
