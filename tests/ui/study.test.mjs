import test from "node:test";
import assert from "node:assert/strict";

import { LH, STUDY, STATE } from "./fixture.mjs";
import { actions, html, input, load } from "../../pm/ui/study.js";

function fakeCtx(overrides = {}) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return overrides.reply ?? STUDY;
    },
    refresh: async () => {},
    go: () => {},
    toast: () => {},
    run: () => {},
    confirm: () => true,
    ...overrides,
  };
  return { ctx, calls };
}

function withStudy(study) {
  return html(STATE, { study });
}

test.afterEach(() => actions.cancel());

test("load fetches the study data", async () => {
  const { ctx, calls } = fakeCtx();
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/study"], ["GET", "/api/lh"]]);
  assert.equal(extra.study, STUDY);
});

test("html says loading until the study data arrives", () => {
  assert.equal(html(STATE, {}), '<p class="muted">loading…</p>');
  assert.equal(html(STATE), '<p class="muted">loading…</p>');
});

test("the next card names the topic, its mastery and what it unblocks", () => {
  const out = withStudy(STUDY);
  assert.ok(out.includes("os / paging"));
  assert.ok(out.includes("mastery 45%"));
  assert.ok(out.includes("(prerequisite of virtual memory)"));
  assert.ok(out.includes('href="#/review"'));
  assert.ok(out.includes("Review now"));
});

test("no pick says no topics with an upcoming exam", () => {
  const out = withStudy({ ...STUDY, next: null });
  assert.ok(out.includes("no topics with an upcoming exam"));
  assert.ok(!out.includes("Review now"));
});

test("a course gets a graph only when it has a prerequisite link", () => {
  const out = withStudy(STUDY);
  assert.ok(out.includes('<div class="graph">'));
  assert.ok(out.includes('<svg role="img" aria-label="prerequisites for '));
  const flat = {
    ...STUDY,
    topics: STUDY.topics.map((topic) => ({ ...topic, prereqs: [] })),
  };
  assert.ok(!withStudy(flat).includes('<div class="graph">'));
});

test("the calibration verdict matches the cli", () => {
  const calibration = (gap) => ({
    ...STUDY,
    calibration: { ...STUDY.calibration, gap },
  });
  assert.ok(withStudy(calibration(0.12)).includes("you overrate yourself by 12 points"));
  assert.ok(withStudy(calibration(-0.15)).includes("you underrate yourself by 15 points"));
  assert.ok(withStudy(calibration(0.05)).includes("well calibrated"));
});

test("no reviews shows no chart", () => {
  const out = withStudy({
    ...STUDY,
    calibration: { n: 0, brier: null, gap: 0, bins: [] },
  });
  assert.ok(out.includes("no reviews yet"));
  assert.ok(!out.includes('class="calib-chart"'));
});

test("the calibration chart has one titled circle per bin and a table", () => {
  const out = withStudy(STUDY);
  const circles = out.match(/<circle /g) ?? [];
  assert.equal(circles.length, STUDY.calibration.bins.length);
  assert.ok(out.includes("<title>said 70%, recalled 60%, 10 reviews</title>"));
  assert.ok(out.includes("40 reviews · Brier 0.182"));
  assert.ok(out.includes('<td data-label="said">70%</td><td data-label="recalled">60%</td><td data-label="reviews">10</td>'));
});

test("the queue line shows due and held new items", () => {
  const out = withStudy(STUDY);
  assert.ok(out.includes("7 due now · 2 new items wait for another day"));
  const clear = withStudy({ ...STUDY, queue: { due: 3, held: 0 } });
  assert.ok(clear.includes("3 due now"));
  assert.ok(!clear.includes("wait for another day"));
});

test("addTopic sends only the filled fields and numbers the weight", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.addTopic(
    { name: "tlb", course: "os", exam: "+20", weight: "2", needs: ["paging"] },
    ctx,
  );
  assert.deepEqual(calls, [
    [
      "POST",
      "/api/topics",
      { name: "tlb", course: "os", exam: "+20", weight: 2, needs: ["paging"] },
    ],
  ]);
});

test("addTopic trims the name, wraps one need and omits empty needs", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.addTopic({ name: "  tlb  ", needs: "paging" }, ctx);
  await actions.addTopic({ name: "tlb", needs: [] }, ctx);
  await actions.addTopic({ name: "tlb" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/topics", { name: "tlb", needs: ["paging"] }],
    ["POST", "/api/topics", { name: "tlb" }],
    ["POST", "/api/topics", { name: "tlb" }],
  ]);
});

test("editTopic opens the row and cancel closes it", async () => {
  const { ctx } = fakeCtx();
  await load(ctx);
  actions.editTopic({ id: "1" });
  let out = withStudy(STUDY);
  assert.ok(out.includes('<form data-act="saveTopic" data-id="1"'));
  assert.ok(out.includes('name="exam" value="2026-12-01"'));
  assert.ok(out.includes('name="weight" type="number" step="any" min="0.1" required value="2"'));
  actions.cancel();
  out = withStudy(STUDY);
  assert.ok(!out.includes('data-act="saveTopic"'));
});

test("saveTopic sends only the changed fields", async () => {
  const { ctx, calls } = fakeCtx();
  await load(ctx);
  calls.length = 0;
  await actions.saveTopic({ id: "1", exam: "", weight: "2" }, ctx);
  assert.deepEqual(calls, [["POST", "/api/topics/1/edit", { exam: "" }]]);
  assert.ok(!withStudy(STUDY).includes('data-act="saveTopic"'));
});

test("saveTopic makes no request when nothing changed", async () => {
  const { ctx, calls } = fakeCtx();
  await load(ctx);
  calls.length = 0;
  await actions.saveTopic({ id: "1", exam: "2026-12-01", weight: "2" }, ctx);
  assert.deepEqual(calls, []);
});

test("a topic name is escaped in the table, ranking and needs options", () => {
  const name = "<b>x</b>";
  const study = {
    ...STUDY,
    topics: STUDY.topics.map((topic) => (topic.id === 1 ? { ...topic, name } : topic)),
  };
  const out = withStudy(study);
  assert.ok(out.includes("<td>&lt;b&gt;x&lt;/b&gt;</td>"));
  assert.ok(out.includes("os / &lt;b&gt;x&lt;/b&gt;"));
  assert.ok(
    out.includes(
      '<option value="&lt;b&gt;x&lt;/b&gt;" data-course="os" disabled>&lt;b&gt;x&lt;/b&gt;</option>',
    ),
  );
  assert.ok(!out.includes("<b>x</b>"));
});

test("needs options carry their course and only an empty course starts enabled", () => {
  const study = {
    ...STUDY,
    topics: [
      ...STUDY.topics,
      {
        id: 4,
        course: "",
        name: "misc",
        exam: null,
        weight: 1,
        mastery: 0,
        items: 0,
        due: 0,
        prereqs: [],
      },
    ],
  };
  const out = withStudy(study);
  assert.ok(out.includes('<option value="paging" data-course="os" disabled>paging</option>'));
  assert.ok(out.includes('<option value="indexes" data-course="db" disabled>indexes</option>'));
  assert.ok(out.includes('<option value="misc" data-course="">misc</option>'));
});

test("changing the course enables only that course's needs and deselects the rest", () => {
  const paging = { dataset: { course: "os" }, disabled: true, selected: true };
  const indexes = { dataset: { course: "db" }, disabled: true, selected: true };
  const misc = { dataset: { course: "" }, disabled: false, selected: true };
  const select = { options: [paging, indexes, misc] };
  const form = {
    querySelector: (selector) =>
      selector === 'select[name="needs"]' ? select : null,
  };
  const target = { name: "course", value: "  os  ", form };
  assert.equal(input({ target }, {}), false);
  assert.deepEqual(
    [paging.disabled, indexes.disabled, misc.disabled],
    [false, true, true],
  );
  assert.deepEqual(
    [paging.selected, indexes.selected, misc.selected],
    [true, false, false],
  );

  target.value = "";
  assert.equal(input({ target }, {}), false);
  assert.deepEqual(
    [paging.disabled, indexes.disabled, misc.disabled],
    [true, true, false],
  );
  assert.deepEqual(
    [paging.selected, indexes.selected, misc.selected],
    [false, false, false],
  );
});

test("the course hook ignores other fields and a form without needs", () => {
  assert.equal(input({ target: { name: "name", value: "x" } }, {}), false);
  assert.equal(
    input({ target: { name: "course", value: "os", form: { querySelector: () => null } } }, {}),
    false,
  );
});

test("the add-from-file button opens the dialog", async () => {
  const out = withStudy(STUDY);
  assert.ok(out.includes('type="button" class="btn" data-act="addFromFile"'));
  assert.ok(out.includes("Add items from a file"));
  const opened = [];
  const { ctx } = fakeCtx({
    openAddStudy: async (...args) => {
      opened.push(args);
    },
  });
  await actions.addFromFile({}, ctx);
  assert.equal(opened.length, 1);
});

test("one held item reads in the singular", () => {
  const out = withStudy({ ...STUDY, queue: { due: 3, held: 1 } });
  assert.ok(out.includes("3 due now · 1 new item waits for another day"));
});

test("the spot card shows when there are cards or a model", () => {
  const out = html(STATE, { study: STUDY });
  assert.ok(out.includes("Spot the error"));
  assert.ok(out.includes("2 cards ready"));
  assert.ok(out.includes('href="#/spot"'));
  assert.ok(out.includes('data-act="makeSpots"'));
  const none = html({ ...STATE, llm: false, spots: 0 }, { study: STUDY });
  assert.ok(!none.includes("Spot the error"));
  const noModel = html({ ...STATE, llm: false, spots: 1 }, { study: STUDY });
  assert.ok(noModel.includes("1 card ready") && !noModel.includes("makeSpots"));
});

test("make 3 more posts n=3 and says how many it made", async () => {
  const toasts = [];
  const { ctx, calls } = fakeCtx({ reply: { made: 2, errors: [] }, toast: (m) => toasts.push(m) });
  await actions.makeSpots({}, ctx);
  assert.deepEqual(calls, [["POST", "/api/spot/make", { n: 3 }]]);
  assert.deepEqual(toasts, ["made 2 cards"]);
  const failed = [];
  const other = fakeCtx({ reply: { made: 0, errors: ["#7: too short"] }, toast: (m) => failed.push(m) });
  await actions.makeSpots({}, other.ctx);
  assert.deepEqual(failed, ["#7: too short"]);
});

// --- phase 11: what mastery is made of ---
const withFacets = (patch) => html(STATE, { study: { ...STUDY, ...patch } });

test("a topic shows its three parts and coverage", () => {
  const out = html(STATE, { study: STUDY });
  for (const name of ["memory", "understanding", "application"]) assert.match(out, new RegExp(`facet-name">${name}`));
  assert.match(out, /81%/);
  assert.match(out, /67%/);
  assert.match(out, /covered 9 of 15 sections/);
});

test("a missing part says so instead of drawing a bar", () => {
  const out = html(STATE, { study: { ...STUDY, topics: [STUDY.topics[1]] } });
  assert.match(out, /no practice yet/);
  assert.equal((out.match(/facet-bar/g) ?? []).length, 2);
});

test("thin evidence is marked", () => {
  assert.match(html(STATE, { study: STUDY }), /title="thin evidence: 2 answers"/);
});

test("no tracked files means no coverage line", () => {
  const out = html(STATE, { study: { ...STUDY, topics: [STUDY.topics[2]] } });
  assert.doesNotMatch(out, /covered/);
});

test("readiness line per course", () => {
  assert.match(html(STATE, { study: STUDY }), /os 62% ready, exam /);
  assert.doesNotMatch(withFacets({ readiness: [] }), /ready, exam/);
});

test("confident mistakes are escaped, and the card goes when empty", () => {
  const bad = [{ ...STUDY.misses[0], label: "<script>x</script>" }];
  const out = withFacets({ misses: bad });
  assert.match(out, /Confident mistakes/);
  assert.match(out, /said 90%/);
  assert.match(out, /&lt;script&gt;x&lt;\/script&gt;/);
  assert.doesNotMatch(out, /<script>/);
  assert.doesNotMatch(withFacets({ misses: [] }), /Confident mistakes/);
});

test("calibration by source only with two sources", () => {
  const cal = (sources) => withFacets({ calibration: { ...STUDY.calibration, sources } });
  assert.doesNotMatch(cal(STUDY.calibration.sources), /calib-sources/);
  const out = cal([
    { source: "practice", n: 5, brier: 0.1, gap: 0.08 },
    { source: "review", n: 40, brier: 0.182, gap: 0.2 },
  ]);
  assert.equal((out.match(/<tr><td>(practice|review)<\/td>/g) ?? []).length, 2);
  assert.match(out, /calibrated/);
  assert.match(out, /overrates by 20/);
});

test("the LearnHarness card lists unsorted sessions first, with a topic picker", () => {
  const out = html(STATE, { study: STUDY, lh: LH });
  assert.ok(out.includes("<h2>LearnHarness sessions</h2>"));
  const form = out.indexOf('<form data-act="mapSession" data-chat="chat_practice"');
  assert.ok(form > 0);
  assert.ok(form < out.indexOf("TLB and paging"));
  assert.ok(out.includes('<option value="">no topic</option>'));
  assert.ok(out.includes("chat_v2: newer LearnHarness format (version 2)"));
  assert.ok(out.includes('data-act="lhSync"'));
});

test("session titles are escaped", () => {
  const lh = { ...LH, sessions: [{ ...LH.sessions[0], title: "<script>" }] };
  const out = html(STATE, { study: STUDY, lh });
  assert.ok(out.includes("&lt;script&gt;"));
  assert.ok(!out.includes("<script>"));
});

test("not found and empty", () => {
  assert.ok(html(STATE, { study: STUDY, lh: { found: false, sessions: [], skipped: [] } })
    .includes("LearnHarness not found: set lh_dir in Settings if you use it"));
  assert.ok(html(STATE, { study: STUDY, lh: { found: true, sessions: [], skipped: [] } }).includes("no sessions yet"));
});

test("mapSession posts the topic or null; lhSync posts and toasts", async () => {
  const toasts = [];
  const { ctx, calls } = fakeCtx({ reply: { sessions: 1, answers: 2, outcomes: 0, questions: 0, cards: 0, skipped: [] },
    toast: (m) => toasts.push(m) });
  await actions.mapSession({ chat: "chat_practice", topic: "3" }, ctx);
  await actions.mapSession({ chat: "chat_practice", topic: "" }, ctx);
  await actions.lhSync({}, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/lh/sessions/chat_practice/map", { topic_id: 3 }],
    ["POST", "/api/lh/sessions/chat_practice/map", { topic_id: null }],
    ["POST", "/api/lh/sync", {}],
  ]);
  assert.deepEqual(toasts, ["learnharness: 1 sessions, 2 answers, 0 outcomes, 0 questions, 0 cards"]);
});

test("the plugin hint shows only when it is missing or old", () => {
  const draw = (plugin) => html({ ...STATE, lh: { ...STATE.lh, plugin } }, { study: STUDY, lh: LH });
  assert.ok(draw("missing").includes("the tutor can&#39;t see pm yet: run pm lh install"));
  assert.ok(draw("old").includes("the pm plugin in LearnHarness is out of date: run pm lh install"));
  for (const plugin of ["ok", "no-app"]) assert.ok(!draw(plugin).includes("pm lh install"));
});

test("suggestions get accept and reject buttons, and the budget line shows when it's on", async () => {
  const study = { ...STUDY, suggestions: [{ id: 4, kind: "topic", text: "put session \"<b>x\" under os/paging" }],
    agent: { budget: 30, spent: 12, queued: 2 } };
  const out = html(STATE, { study });
  assert.ok(out.includes("<h2>Suggestions</h2>"));
  assert.ok(out.includes("put session &quot;&lt;b&gt;x&quot; under os/paging"));
  assert.ok(out.includes('data-act="acceptSuggestion" data-id="4"'));
  assert.ok(out.includes('data-act="rejectSuggestion" data-id="4"'));
  assert.ok(out.includes("model jobs: 12 of 30 calls used today, 2 queued"));
  const none = html(STATE, { study: { ...STUDY, suggestions: [], agent: { budget: 0, spent: 0, queued: 0 } } });
  assert.ok(!none.includes("<h2>Suggestions</h2>"));
  assert.ok(!none.includes("model jobs:"));
  const { ctx, calls } = fakeCtx({ reply: { text: "done" } });
  await actions.acceptSuggestion({ id: "4" }, ctx);
  await actions.rejectSuggestion({ id: "4" }, ctx);
  assert.deepEqual(calls, [["POST", "/api/suggestions/4/accept"], ["POST", "/api/suggestions/4/reject"]]);
});
