import test from "node:test";
import assert from "node:assert/strict";

import { STATE } from "./fixture.mjs";
import { actions, after, html, load, statsHtml } from "../../pm/ui/stats.js";
import { dayOf, shift } from "../../pm/ui/charts.js";

const H = 3600e3;
const NOW = new Date(2026, 10, 9, 15);
const day = (k) => dayOf(shift(NOW, k));
const EVIL = "<img src=x onerror=alert(1)> & co";

const FIXTURE = {
  version: 1,
  generated: "2026-11-09T14:00:00",
  settings: { hours_per_day: 4, peak: "09-12" },
  days: {
    [day(0)]: { min: 60, deep: 60, peak: 30, reviews: 0, recalled: 0, fails: 2, fixes: 1 },
    [day(-1)]: { min: 30, deep: 0, peak: 0, reviews: 5, recalled: 4, fails: 0, fixes: 0 },
    [day(-2)]: { min: 0, deep: 0, peak: 0, reviews: 3, recalled: 3, fails: 1, fixes: 0 },
    [day(-3)]: { min: 0, deep: 0, peak: 0, reviews: 2, recalled: 1, fails: 0, fixes: 0 },
  },
  time: { by_course: { os: 90 }, by_kind: { lab: 90 }, by_energy: { deep: 60, shallow: 30 } },
  estimates: {
    kinds: [{ kind: "all", n: 2, median: 1.8 }],
    history: [
      { done: day(-2), title: "a", kind: "lab", ratio: 1.5 },
      { done: day(-1), title: "b", kind: "lab", ratio: 2.1 },
    ],
  },
  deadlines: {
    crunch: 0.31,
    on_time: 4,
    late: 1,
    open: [
      { title: EVIL, course: "os", due: day(3), p_late: 0.4, start_by: day(1), behind: false },
    ],
    recent: [{ title: "c", due: day(-5), done: day(-4), late: true }],
  },
  study: {
    reviews: 10,
    brier: 0.182,
    due_now: 7,
    bins: [{ lo: 60, hi: 80, n: 10, said: 0.7, recalled: 0.6 }],
    topics: [{ course: "os", name: "paging", exam: day(20), weight: 2, mastery: 0.45 }],
  },
  bugs: {
    fixed: 1,
    open: 1,
    abandoned: 0,
    lost_min: 25,
    untagged: 0,
    tags: [["off-by-one", 3]],
    bursts: [["off-by-one", 3]],
    recent: [
      { id: 2, prog: "make", status: "fixed", fails: 2, lost_min: 25, tags: ["off-by-one"], opened: day(0) },
    ],
  },
};

const EMPTY = {
  version: 1,
  generated: "2026-11-09T14:00:00",
  settings: { hours_per_day: 4, peak: "09-12" },
  days: {},
  time: { by_course: {}, by_kind: {}, by_energy: {} },
  estimates: { kinds: [], history: [] },
  deadlines: { crunch: 0, on_time: 0, late: 0, open: [], recent: [] },
  study: { reviews: 0, brier: null, due_now: 0, bins: [], topics: [] },
  bugs: {
    fixed: 0,
    open: 0,
    abandoned: 0,
    lost_min: 0,
    untagged: 0,
    tags: [],
    bursts: [],
    recent: [],
  },
};

function fakeCtx(stats = FIXTURE) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path) {
      calls.push([method, path]);
      return stats;
    },
  };
  return { ctx, calls };
}

test("load fetches the stats summary", async () => {
  const { ctx, calls } = fakeCtx();
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/stats"]]);
  assert.equal(extra.stats, FIXTURE);
});

test("html says loading until the stats arrive", () => {
  assert.equal(html(STATE, {}), '<p class="muted">loading…</p>');
  assert.equal(html(STATE), '<p class="muted">loading…</p>');
});

test("html draws the summary at the server's clock", () => {
  const out = html({ ...STATE, now: "2026-11-09T15:00:00" }, { stats: FIXTURE });
  assert.ok(out.includes('class="study-pm card"'));
  assert.match(out, /Today<\/small><b[^>]*>1h</);
  assert.ok(!out.includes("updated "));
});

test("no pm data: notes streak and heatmap, plus a hint", () => {
  const out = statsHtml(null, {}, NOW);
  assert.match(out, /Nothing logged yet: start a task from Today\./);
  assert.match(out, /study-heat/);
  assert.match(out, /Crunch risk<\/small><b>—/);
  assert.ok(!out.includes("undefined"));
  assert.ok(!out.includes("NaN"));
});

test("a day is the larger of notes time and pm time, never the sum", () => {
  const state = { ...STATE, now: "2026-11-09T15:00:00" };
  const more = html(state, { stats: { ...FIXTURE, notes: { [day(0)]: 90 } } });
  assert.match(more, /title="[^"]*: 1h 30m"/);
  assert.match(more, /Today<\/small><b[^>]*>1h30m</);
  assert.ok(!more.includes("2h30m"));
  const less = html(state, { stats: { ...FIXTURE, notes: { [day(0)]: 30 } } });
  assert.match(less, /Today<\/small><b[^>]*>1h</);
});

test("LearnHarness time counts when it is the largest", () => {
  const state = { ...STATE, now: "2026-11-09T15:00:00" };
  const out = html(state, { stats: { ...FIXTURE, notes: { [day(0)]: 90 }, lh: { [day(0)]: 120 } } });
  assert.match(out, /Today<\/small><b[^>]*>2h</);
  assert.ok(!out.includes("4h30m"));
});

test("titles are text, never HTML", () => {
  const out = statsHtml(FIXTURE, {}, NOW);
  assert.ok(!out.includes("<img"), "raw <img must not appear");
  assert.match(out, /&lt;img src=x onerror=alert\(1\)&gt; &amp; co/);
});

test("review streak counts days with a review, ending yesterday when today has none", () => {
  assert.match(statsHtml(FIXTURE, {}, NOW), /Review streak<\/small><b>3 days</);
});

test("every section shows up", () => {
  const out = statsHtml(FIXTURE, {}, NOW);
  for (const text of [
    "Time",
    "last 28 days",
    "Estimates",
    "Deadlines",
    "Study",
    "Code issues",
    "off-by-one",
    "×1.80",
    "31%",
    "paging",
    "1h30m",
  ]) {
    assert.ok(out.includes(text), text);
  }
});

test("an empty summary shows every hint, with no undefined or NaN", () => {
  const out = statsHtml(EMPTY, {}, NOW);
  for (const text of [
    "No timed work yet",
    "Finish a few tasks with logged time",
    "Nothing open with a due date",
    "No topics or reviews yet",
    "No bugs logged yet",
  ]) {
    assert.ok(out.includes(text), text);
  }
  assert.ok(!out.includes("undefined"));
  assert.ok(!out.includes("NaN"));
});

test("after scrolls the heatmap to the newest weeks", () => {
  const heat = { scrollWidth: 480, scrollLeft: 0 };
  after({ querySelector: (selector) => (selector === ".study-heat-wrap" ? heat : null) });
  assert.equal(heat.scrollLeft, 480);
});

test("actions is empty: the stats screen only reads", () => {
  assert.deepEqual(actions, {});
});

test("a summary without deadlines still renders", () => {
  const out = statsHtml({ version: 1, days: {} }, {}, new Date("2026-11-11T10:00:00"));
  assert.ok(out.includes("Crunch risk"));
  assert.ok(!/undefined|NaN/.test(out));
});

test("a day is pm's combined minutes when the summary carries them", () => {
  const pm = { ...FIXTURE, days: { ...FIXTURE.days, [day(0)]: { ...FIXTURE.days[day(0)], min: 60, study: 180 } } };
  const out = statsHtml(pm, { [day(0)]: 90 }, NOW);  // timer 60 + site 90, apart: the server says 150+
  assert.match(out, /Today<\/small><b data-level="green">3h</);
  assert.match(out, /Streak \(2h\+ a day\)<\/small><b>🔥 1 day</);
});

test("the combined minutes win over the timer's own, which sit on the day a session started", () => {
  const pm = { ...FIXTURE, days: { ...FIXTURE.days, [day(0)]: { ...FIXTURE.days[day(0)], min: 120, study: 60 } } };
  assert.match(statsHtml(pm, { [day(0)]: 60 }, NOW), /Today<\/small><b data-level="some">1h</);
});
