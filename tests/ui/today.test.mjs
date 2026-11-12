import test from "node:test";
import assert from "node:assert/strict";

import { STATE } from "./fixture.mjs";
import { html, actions, warnLong } from "../../pm/ui/today.js";

function stateWith(patch) {
  return { ...structuredClone(STATE), ...patch };
}

function fakeCtx(answer = {}) {
  const calls = [];
  const toasts = [];
  return {
    calls,
    toasts,
    async api(method, path, body) {
      calls.push([method, path, body]);
      return answer;
    },
    toast(message) {
      toasts.push(message);
    },
  };
}

test("today shows the running task, the plan groups and the day meter", () => {
  const out = html(STATE);
  assert.ok(out.includes("OS lab 3"));
  assert.ok(out.includes("data-elapsed"));
  assert.ok(out.includes("where you left off: stuck on fork"));
  assert.ok(out.includes("first step: open the handout"));
  assert.ok(out.includes("Deep work (peak 09-12)"));
  assert.ok(out.includes("Shallow"));
  assert.ok(out.includes("BEHIND"));
  assert.ok(out.includes("45m of 4h"));
});

test("today escapes a task title from the database", () => {
  const state = structuredClone(STATE);
  state.tasks[0].title = '<img src=x onerror=alert(1)> & co';
  const out = html(state);
  assert.ok(out.includes("&lt;img src=x onerror=alert(1)&gt; &amp; co"));
  assert.ok(!out.includes("<img"));
});

test("without a running task the start button names the first plan item", () => {
  const state = structuredClone(STATE);
  state.running = null;
  state.tasks = state.tasks.map((task) => ({ ...task, running: false }));
  const out = html(state);
  assert.ok(out.includes("Start: OS lab 3"));
  assert.ok(!out.includes('data-act="stop"'));
});

test("an empty plan says there is nothing to do", () => {
  const state = structuredClone(STATE);
  state.running = null;
  state.tasks = [];
  state.today.plan = [];
  assert.ok(html(state).includes("nothing to do"));
});

test("a session over six hours warns and opens stop as", () => {
  const state = structuredClone(STATE);
  state.running.elapsed_s = 22000;
  const out = html(state);
  assert.ok(out.includes('this has run over 6 hours; use "Stop as" if you forgot it'));
  assert.ok(out.includes("<details open>"));
});

test("the day meter caps its bar while keeping the true minutes", () => {
  const state = structuredClone(STATE);
  state.today.worked_min = 300;
  state.today.cap_min = 240;
  const out = html(state);
  assert.ok(out.includes("5h of 4h"));
  assert.ok(out.includes('style="width:100%"'));
});

test("the risk bar changes level at 20 and 50 percent", () => {
  for (const [pLate, level] of [
    [0.1, "green"],
    [0.3, "orange"],
    [0.7, "red"],
  ]) {
    const state = structuredClone(STATE);
    state.running = null;
    state.tasks = [{ ...state.tasks[0], p_late: pLate, running: false }];
    state.today.plan = [{ task_id: 3, minutes: 195 }];
    assert.ok(
      html(state).includes(`data-level="${level}"`),
      `expected ${pLate} to be ${level}`,
    );
  }
});

test("no reviews line when nothing is due", () => {
  assert.ok(!html({ ...STATE, reviews_due: 0 }).includes("reviews due"));
});

test("the reviews line links to the review screen", () => {
  const out = html(STATE);
  assert.ok(out.includes('<a href="#/review">7 reviews due</a>'));
});

test("stop sends only the fields that are filled", async () => {
  const ctx = fakeCtx({});
  await actions.stop({ note: "x", as: "" }, ctx);
  assert.deepEqual(ctx.calls, [["POST", "/api/stop", { note: "x" }]]);

  const withAs = fakeCtx({});
  await actions.stop({ note: "", as: "2h" }, withAs);
  assert.deepEqual(withAs.calls, [["POST", "/api/stop", { as: "2h" }]]);
});

test("start posts to the first plan item and asks pm to open its links", async () => {
  const ctx = fakeCtx({});
  await actions.start({ id: "3" }, ctx);
  assert.deepEqual(ctx.calls, [["POST", "/api/tasks/3/start", { open: true }]]);
});

test("log and done post to their task routes", async () => {
  const logCtx = fakeCtx({});
  await actions.log({ id: "4", duration: "30m" }, logCtx);
  assert.deepEqual(logCtx.calls, [["POST", "/api/tasks/4/log", { duration: "30m" }]]);

  const doneCtx = fakeCtx({});
  await actions.done({ id: "4" }, doneCtx);
  assert.deepEqual(doneCtx.calls, [["POST", "/api/tasks/4/done", undefined]]);
});

test("a long stop tells you to fix it with stop as", async () => {
  const ctx = fakeCtx({ long: true, minutes: 420 });
  await actions.stop({ note: "", as: "" }, ctx);
  assert.deepEqual(ctx.toasts, ["that ran 7h; fix it with Stop as next time"]);
});

test("warnLong toasts exactly once for a long answer", () => {
  const ctx = fakeCtx();
  warnLong({ long: true, minutes: 420 }, ctx);
  assert.deepEqual(ctx.toasts, ["that ran 7h; fix it with Stop as next time"]);
});

test("warnLong stays quiet for a short answer", () => {
  const ctx = fakeCtx();
  warnLong({ long: false }, ctx);
  assert.deepEqual(ctx.toasts, []);
});

test("start says how many links it opened and the first one it skipped", async () => {
  const ctx = fakeCtx({ opened: 2, skipped: [] });
  await actions.start({ id: "3" }, ctx);
  assert.deepEqual(ctx.toasts, ["opened 2 links"]);
  const other = fakeCtx({ opened: 1, skipped: ["gone ~/x.pdf"] });
  await actions.start({ id: "3" }, other);
  assert.deepEqual(other.toasts, ["opened 1 link; gone ~/x.pdf"]);
  const none = fakeCtx({});
  await actions.start({ id: "3" }, none);
  assert.deepEqual(none.toasts, []);
});

test("the energy card shows only right after a session", () => {
  const today = { ...STATE.today, unrated: true };
  const out = html(stateWith({ today }));
  assert.ok(out.includes("how was your energy?"));
  assert.equal((out.match(/data-act="energy"/g) ?? []).length, 5);
  assert.ok(!html(STATE).includes('data-act="energy"'));
});

test("energy posts the rating as a number", async () => {
  const ctx = fakeCtx();
  await actions.energy({ energy: "4" }, ctx);
  assert.deepEqual(ctx.calls, [["POST", "/api/energy", { energy: 4 }]]);
});

test("a peak hint offers to use it", async () => {
  const today = { ...STATE.today, peak_hint: "15-18" };
  const out = html(stateWith({ today }));
  assert.ok(out.includes("your best hours look like 15-18"));
  assert.ok(out.includes('data-act="usePeak" data-peak="15-18"'));
  assert.ok(!html(STATE).includes("usePeak"));
  const ctx = fakeCtx();
  await actions.usePeak({ peak: "15-18" }, ctx);
  assert.deepEqual(ctx.calls, [["POST", "/api/settings", { key: "peak", value: "15-18" }]]);
});

test("a running test shows a link to the Exam screen", async () => {
  const { html: todayHtml } = await import("../../pm/ui/today.js");
  const { STATE: S } = await import("./fixture.mjs");
  assert.match(todayHtml({ ...S, exam: { open: 3 } }), /href="#\/exam">a test is in progress/);
  assert.doesNotMatch(todayHtml({ ...S, exam: { open: null } }), /a test is in progress/);
});

test("the study card lists what is waiting", () => {
  const out = html(STATE);
  assert.ok(out.includes("<h2>Study</h2>"));
  assert.ok(out.includes('<a href="#/spot">2 spot-the-error cards</a>'));
  assert.ok(out.includes("12 cards ready in LearnHarness"));
  assert.ok(out.includes("tutor next: os / paging"));
  assert.ok(out.includes('data-act="copyOpening" data-topic="3">Copy opening message'));
  assert.ok(out.includes('data-act="copyOpening" data-topic="3" data-practice="1">Copy for practice'));
  assert.ok(out.includes('<a href="#/practice">practise: os / paging</a>'));
  assert.ok(out.includes('<a href="#/study">1 LearnHarness session has no topic</a>'));
});

test("without LearnHarness the tutor row stays", () => {
  const out = html(stateWith({ lh: { found: false, cards_ready: 12, unsorted: 1 } }));
  assert.ok(!out.includes("ready in LearnHarness"));
  assert.ok(!out.includes("no topic"));
  assert.ok(out.includes("tutor next"));
  const none = html(stateWith({ tutor: null }));
  assert.ok(!none.includes("tutor next"));
  assert.ok(!none.includes("practise:"));
});

test("nothing to study leaves the card out, and names are escaped", () => {
  const empty = stateWith({ reviews_due: 0, spots: 0, lh: { found: true, cards_ready: 0, unsorted: 0 }, tutor: null });
  assert.ok(!html(empty).includes("<h2>Study</h2>"));
  const out = html(stateWith({ tutor: { topic_id: 3, topic: "<b>x", course: "os" } }));
  assert.ok(out.includes("&lt;b&gt;x"));
  assert.ok(!out.includes("<b>x"));
});

test("copyOpening fetches the message and copies it", async () => {
  const written = [];
  const clipboard = { writeText: async (t) => written.push(t) };
  const saved = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: { clipboard }, configurable: true });
  try {
    const ctx = fakeCtx({ text: "[pm:topic=3] hi" });
    await actions.copyOpening({ topic: "3" }, ctx);
    await actions.copyOpening({ topic: "3", practice: "1" }, ctx);
    assert.deepEqual(ctx.calls.map((c) => c[1]), ["/api/lh/opening?topic=3", "/api/lh/opening?topic=3&practice=1"]);
    assert.deepEqual(written, ["[pm:topic=3] hi", "[pm:topic=3] hi"]);
    assert.equal(ctx.toasts[0], "copied: paste it into a new LearnHarness session");
    clipboard.writeText = async () => {
      throw new Error("denied");
    };
    assert.equal(await actions.copyOpening({ topic: "3" }, ctx), "[pm:topic=3] hi");
    assert.ok(html(STATE).includes('<textarea class="opening" readonly rows="8" aria-label="opening message">[pm:topic=3] hi</textarea>'));
  } finally {
    if (saved) Object.defineProperty(globalThis, "navigator", saved);
    else delete globalThis.navigator;
  }
});
