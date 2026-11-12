import test from "node:test";
import assert from "node:assert/strict";

import {
  actions,
  html,
  input,
  load,
  resultsHtml,
  setSliders,
  timeline,
} from "../../pm/ui/risk.js";

const RISK = {
  today: "2026-11-09",
  hours: 3.5,
  skip: 2,
  set_hours: 4,
  crunch: 0.74,
  base_crunch: 0.31,
  start_queue_by: "2026-11-10",
  undated: 2,
  tasks: [
    {
      id: 3,
      title: "OS lab 3",
      course: "os",
      due: "2026-11-12",
      p_late: 0.4,
      start_by: "2026-11-10",
      behind: false,
      finish_p50: "2026-11-11",
      finish_p95: "2026-11-13",
      late_days: 1.6,
    },
    {
      id: 4,
      title: "DBMS chapter 4",
      course: "db",
      due: "2026-11-13",
      p_late: 0.6,
      start_by: "2026-11-08",
      behind: true,
      finish_p50: "2026-11-14",
      finish_p95: "2026-11-16",
      late_days: 0,
    },
  ],
};

function fakeCtx(reply = RISK) {
  const calls = [];
  const patches = [];
  let refreshes = 0;
  const ctx = {
    state: {},
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return reply;
    },
    patch(id, markup) {
      patches.push([id, markup]);
    },
    refresh: async () => {
      refreshes += 1;
    },
    toast: () => {},
    go: () => {},
    run: () => {},
    confirm: () => true,
  };
  return { ctx, calls, patches, refreshes: () => refreshes };
}

test.beforeEach(() => {
  actions.reset();
  setSliders(null);
});

test("load fetches the risk and adopts the setting as the slider start", async () => {
  const { ctx, calls } = fakeCtx();
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/risk"]]);
  assert.equal(extra.risk, RISK);
  assert.ok(
    html({}, { risk: RISK }).includes(
      'name="hours" data-act="whatif" min="0.5" max="16" step="0.5" value="4"',
    ),
  );
});

test("html says loading until the risk data arrives", () => {
  assert.equal(html({}, {}), '<p class="muted">loading…</p>');
  assert.equal(html({}), '<p class="muted">loading…</p>');
});

test("the controls carry both sliders, labels and readouts", () => {
  const out = html({}, { risk: RISK });
  assert.ok(
    out.includes(
      '<input id="risk-hours" type="range" name="hours" data-act="whatif" min="0.5" max="16" step="0.5" value="4">',
    ),
  );
  assert.ok(
    out.includes(
      '<input id="risk-skip" type="range" name="skip" data-act="whatif" min="0" max="14" step="1" value="0">',
    ),
  );
  assert.ok(out.includes('<label for="risk-hours">hours a day</label>'));
  assert.ok(out.includes('<output id="risk-hours-out" for="risk-hours">4 h a day</output>'));
  assert.ok(out.includes('<output id="risk-skip-out" for="risk-skip">start today</output>'));
  assert.ok(out.includes('<div id="risk-out"><p class="risk-crunch">'));
});

test("results show the crunch, the base and the queue date", () => {
  const out = resultsHtml(RISK);
  assert.ok(out.includes("crunch risk 74%"));
  assert.ok(out.includes("(31% at 4 h a day starting today)"));
  assert.ok(out.includes("start the queue by 2026-11-10"));
  assert.ok(out.includes("if late: about 1.6 days"));
  assert.ok(out.includes("BEHIND"));
});

test("the base line disappears at the setting with no lost days", () => {
  const out = resultsHtml({ ...RISK, hours: 4, skip: 0 });
  assert.ok(!out.includes("starting today"));
});

test("the use button shows the what-if hours only when they differ", () => {
  assert.ok(resultsHtml(RISK).includes('data-act="apply"'));
  assert.ok(resultsHtml(RISK).includes("Use 3.5 h a day"));
  assert.ok(!resultsHtml({ ...RISK, hours: 4 }).includes('data-act="apply"'));
});

test("no dated tasks says nothing with a due date", () => {
  const out = resultsHtml({ ...RISK, tasks: [], start_queue_by: null, undated: 0 });
  assert.ok(out.includes("nothing with a due date"));
  assert.ok(!out.includes("<svg"));
  assert.ok(!out.includes("not simulated"));
});

test("undated tasks are counted with the right words", () => {
  assert.ok(
    resultsHtml({ ...RISK, undated: 1 }).includes(
      "1 task has no due date and is not simulated",
    ),
  );
  assert.ok(
    resultsHtml(RISK).includes("2 tasks have no due date and are not simulated"),
  );
});

test("the timeline draws one bar per task with its level and tooltip", () => {
  const out = timeline(RISK);
  assert.ok(out.startsWith("<svg "));
  assert.equal((out.match(/<rect /g) ?? []).length, RISK.tasks.length);
  assert.ok(out.includes('role="img"'));
  assert.ok(out.includes("aria-label="));
  assert.ok(out.includes('data-level="orange"'));
  assert.ok(out.includes('data-level="red"'));
  assert.ok(
    out.includes(
      "<title>OS lab 3: due 12 Nov, likely 11 Nov, worst case 13 Nov, late 40%</title>",
    ),
  );
});

test("a low late chance draws a green bar", () => {
  const out = timeline({ ...RISK, tasks: [{ ...RISK.tasks[0], p_late: 0.1 }] });
  assert.ok(out.includes('data-level="green"'));
});


test("a task title is escaped and cut to 24 code points on the chart", () => {
  const title = '<script>alert("x")</script> and more';
  const out = timeline({ ...RISK, tasks: [{ ...RISK.tasks[0], title }] });
  assert.ok(!out.includes("<script"));
  const label = out.match(/<text class="risk-label"[^>]*>([^<]*)<\/text>/)[1];
  assert.equal(label, "&lt;script&gt;alert(&quot;x&quot;)&lt;/scri");
});

test("the chart label cuts by code point, not UTF-16 unit", () => {
  const title = "😀".repeat(30);
  const out = timeline({ ...RISK, tasks: [{ ...RISK.tasks[0], title }] });
  const label = out.match(/<text class="risk-label"[^>]*>([^<]*)<\/text>/)[1];
  assert.equal([...label].length, 24);
});

test("a behind task's start-by triangle stays inside the plot", () => {
  const out = timeline(RISK);
  const axis = Number(out.match(/<line class="tick" x1="([\d.]+)"/)[1]);
  const starts = [...out.matchAll(/<polygon class="risk-startby" points="([\d.]+),/g)].map(
    (match) => Number(match[1]),
  );
  assert.equal(starts.length, RISK.tasks.length);
  for (const x of starts) assert.ok(x >= axis, `${x} is left of the axis at ${axis}`);
  assert.ok(out.includes(`<polygon class="risk-startby" points="${axis},`));
});

test("whatif asks for both sliders and patches only the results", async () => {
  const { ctx, calls, patches, refreshes } = fakeCtx();
  setSliders(() => ({ hours: 3.5, skip: 2 }));
  await actions.whatif({}, ctx);
  assert.deepEqual(calls, [["GET", "/api/risk?hours=3.5&skip=2"]]);
  assert.equal(patches.length, 1);
  assert.equal(patches[0][0], "risk-out");
  assert.ok(patches[0][1].includes("crunch risk 74%"));
  assert.equal(refreshes(), 0);
});

test("a what-if view is kept for the next load", async () => {
  setSliders(() => ({ hours: 3.5, skip: 2 }));
  await actions.whatif({}, fakeCtx().ctx);
  const { ctx, calls } = fakeCtx();
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/risk?hours=3.5&skip=2"]]);
});

test("moving only the lost-days slider keeps hours the range can't show", async () => {
  setSliders();
  actions.reset();
  await load(fakeCtx({ ...RISK, set_hours: 14 }).ctx);
  input({ target: { name: "skip", value: "2" } });
  // the browser clamps an hours range to its max, so the DOM would say less than the setting
  globalThis.document = { querySelector: (sel) => ({ value: sel.includes("hours") ? "12" : "2" }) };
  try {
    const { ctx, calls } = fakeCtx();
    await actions.whatif({ name: "skip", value: "2" }, ctx);
    assert.deepEqual(calls, [["GET", "/api/risk?hours=14&skip=2"]]);
  } finally {
    delete globalThis.document;
    actions.reset();
  }
});

test("apply saves the hours as a setting", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.apply({ value: "3.5" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/settings", { key: "hours_per_day", value: "3.5" }],
  ]);
});

test("reset forgets the what-if and the next load omits hours", async () => {
  setSliders(() => ({ hours: 3.5, skip: 2 }));
  await actions.whatif({}, fakeCtx().ctx);
  actions.reset();
  const { ctx, calls } = fakeCtx();
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/risk"]]);
});

test("input updates the hours readout and the view", async () => {
  const output = { textContent: "" };
  const control = {
    querySelector: (selector) => (selector === "output" ? output : null),
  };
  const target = {
    name: "hours",
    value: "3.5",
    closest: (selector) => (selector === ".risk-control" ? control : null),
  };
  assert.equal(input({ target }, {}), false);
  assert.equal(output.textContent, "3.5 h a day");
  const { ctx, calls } = fakeCtx();
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/risk?hours=3.5"]]);
});

test("input words the lost days", () => {
  const output = { textContent: "" };
  const control = { querySelector: () => output };
  for (const [value, text] of [
    ["0", "start today"],
    ["1", "after 1 lost day"],
    ["2", "after 2 lost days"],
  ]) {
    const target = { name: "skip", value, closest: () => control };
    input({ target }, {});
    assert.equal(output.textContent, text);
  }
});

test("a saved setting finer than half an hour gets a finer slider, so it isn't shown rounded", () => {
  const out = html({}, { risk: { ...RISK, set_hours: 0.3, hours: 0.3 } });
  assert.ok(out.includes('min="0.1" max="16" step="0.1"'));
});

