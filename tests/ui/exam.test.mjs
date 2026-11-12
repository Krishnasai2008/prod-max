import test from "node:test";
import assert from "node:assert/strict";

import { EXAM, MOCK_MARKED, MOCK_RUNNING, MOCK_TO_MARK, STATE } from "./fixture.mjs";
import { _set, actions, clock, html, input, resultHtml } from "../../pm/ui/exam.js";

function fakeCtx(overrides = {}) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return overrides.reply ?? {};
    },
    toast: () => {},
    confirm: () => true,
    ...overrides,
  };
  return { ctx, calls };
}

const draftFor = (pos, answer = "") => ({ mock: 1, pos, answer, confidence: 50, dontKnow: false });

test("clock", () => {
  assert.equal(clock(1290), "21:30");
  assert.equal(clock(0), "0:00");
  assert.equal(clock(-250), "over by 4:10");
  assert.equal(clock(null), "");
});

test("overview lists courses, papers, tests and the bank", () => {
  _set({ openId: null });
  const out = html(STATE, { exam: EXAM });
  assert.match(out, /<option value="os">os<\/option>/);
  assert.match(out, /2025 midsem/);
  assert.match(out, /62% \(predicted 55%\)/);
  assert.match(out, /paging 14 questions/);
  const bare = html(STATE, { exam: { ...EXAM, mocks: [EXAM.mocks[1]], bank: [] } });
  assert.match(bare, /62%/);
  assert.doesNotMatch(bare, /predicted/);
  assert.match(bare, /no questions yet: import the answer sections of a note/);
  const empty = html(STATE, { exam: { ...EXAM, courses: [], mocks: [], bank: [] } });
  assert.match(empty, /A test needs questions first/);
  assert.doesNotMatch(empty, /data-act="create"/);
});

test("create posts the sample or the paper", async () => {
  const { ctx, calls } = fakeCtx({ reply: { id: 7 } });
  await actions.create({ course: "os", n: "10", minutes: "", paper: "" }, ctx);
  assert.deepEqual(calls[0], ["POST", "/api/mocks", { course: "os", n: 10 }]);
  await actions.create({ course: "os", n: "10", minutes: "", paper: "2" }, ctx);
  assert.deepEqual(calls[1], ["POST", "/api/mocks", { paper_id: 2 }]);
});

test("running draws one question with its field and the clock, never a key", () => {
  _set({ openId: 1, pos: 1, draft: draftFor(1), leftS: 1290 });
  const one = html(STATE, { exam: EXAM, mock: MOCK_RUNNING });
  assert.match(one, /question 1 of 3/);
  assert.match(one, /data-left/);
  assert.match(one, /21:30/);
  assert.match(one, /<input id="exam-answer" name="answer"/);
  assert.doesNotMatch(one, /class="tag"/);
  _set({ pos: 2, draft: draftFor(2) });
  const two = html(STATE, { exam: EXAM, mock: MOCK_RUNNING });
  assert.equal((two.match(/type="checkbox" name="choice"/g) ?? []).length, 3);
  assert.doesNotMatch(two, /type="radio"/);
  assert.match(two, /class="tag">checked/);
  _set({ pos: 3, draft: draftFor(3) });
  const three = html(STATE, { exam: EXAM, mock: MOCK_RUNNING });
  assert.match(three, /<textarea/);
  for (const out of [one, two, three]) assert.doesNotMatch(out, /A cache of page-table entries|B: LRU/);
});

test("a prompt is escaped and keeps its maths", () => {
  const items = [{ ...MOCK_RUNNING.items[0], prompt: "<script>x</script> $x^2$" }];
  _set({ openId: 1, pos: 1, draft: draftFor(1) });
  const out = html(STATE, { exam: EXAM, mock: { ...MOCK_RUNNING, items } });
  assert.doesNotMatch(out, /<script>/);
  assert.match(out, /&lt;script&gt;/);
  assert.match(out, /\$x\^2\$/);
});

test("typing updates the draft and next saves it", async () => {
  _set({ openId: 1, pos: 1, draft: draftFor(1) });
  input({ target: { name: "answer", value: "12" } });
  input({ target: { name: "confidence", value: "80" } });
  const { ctx, calls } = fakeCtx();
  await actions.next({}, ctx);
  assert.deepEqual(calls[0], ["POST", "/api/mocks/1/items/1", { confidence: 80, answer: "12" }]);
});

test("choice boxes save as numbers", async () => {
  _set({ openId: 1, pos: 2, draft: draftFor(2) });
  const form = { querySelectorAll: () => [{ value: "1" }, { value: "3" }] };
  input({ target: { name: "choice", form } });
  const { ctx, calls } = fakeCtx();
  await actions.save({}, ctx);
  assert.equal(calls[0][2].answer, "1,3");
});

test("finish asks first when something is blank", async () => {
  const items = MOCK_RUNNING.items.map((i) => ({ ...i, answer: i.pos === 3 ? null : "x" }));
  _set({ openId: 1, pos: 1, draft: draftFor(1, "12"), mock: { ...MOCK_RUNNING, items } });
  const asked = [];
  const no = fakeCtx({ confirm: (m) => (asked.push(m), false) });
  await actions.finish({}, no.ctx);
  assert.match(asked[0], /1 question is blank/);
  assert.equal(no.calls.length, 0);
  _set({ draft: draftFor(1, "12"), mock: { ...MOCK_RUNNING, items } });
  const yes = fakeCtx({ confirm: () => true });
  await actions.finish({}, yes.ctx);
  assert.deepEqual(yes.calls.at(-1), ["POST", "/api/mocks/1/finish", {}]);
});

test("to mark shows the answer, the model answer and a capped field", async () => {
  _set({ openId: 1 });
  const out = html(STATE, { exam: EXAM, mock: MOCK_TO_MARK });
  assert.match(out, /your answer/);
  assert.match(out, /A cache of page-table entries/);
  assert.match(out, /max="5"/);
  const { ctx, calls } = fakeCtx();
  await actions.mark({ pos: "3", got: "3" }, ctx);
  assert.deepEqual(calls[0], ["POST", "/api/mocks/1/items/3/mark", { got: 3 }]);
});

test("the result", () => {
  const out = resultHtml(MOCK_MARKED);
  assert.match(out, /31 of 50 \(62%\)/);
  assert.match(out, /predicted 55%/);
  assert.match(out, /4 minutes over/);
  assert.match(out, /scheduling<\/td><td>19 of 30/);
  assert.match(out, /you said 70% on average and scored 62%/);
  assert.match(out, /B: LRU/);
  assert.match(out, /3 missed/);
  const clean = resultHtml({ ...MOCK_MARKED, result: { ...MOCK_MARKED.result, missed: [], over_min: 0 } });
  assert.doesNotMatch(clean, /data-act="retry"/);
  assert.doesNotMatch(clean, /over/);
});

test("a void question shows its note and no answer field", () => {
  const voidItem = { pos: 1, question_id: null, marks: 2, topic: "paging", kind: "open", page: false, answer: null,
    confidence: null, dont_know: false, trust: "verified", void: true,
    prompt: "this question came from an older generator and is left out of the score" };
  const m = { ...MOCK_RUNNING, items: [voidItem, ...MOCK_RUNNING.items.slice(1)] };
  _set({ openId: 1, pos: 1, draft: draftFor(1), leftS: 1290 });
  const out = html(STATE, { exam: EXAM, mock: m });
  assert.match(out, /older generator/);
  assert.doesNotMatch(out, /name="answer"|name="confidence"|name="dont_know"/);
  const toMark = html(STATE, { exam: EXAM, mock: { ...MOCK_TO_MARK, items: [{ ...voidItem }, ...MOCK_TO_MARK.items] } });
  assert.equal((toMark.match(/data-act="mark"/g) ?? []).length, 1);
});

test("a marked generated question shows its steps under the key", () => {
  const gen = { ...MOCK_MARKED.items[0], question_id: null, steps: "LRU table\n\nFaults: 12", void: false };
  const out = resultHtml({ ...MOCK_MARKED, items: [gen, ...MOCK_MARKED.items.slice(1)] });
  assert.match(out, /class="md exam-steps"/);
  assert.match(out, /Faults: 12/);
});

test("a marked test with misses offers variants only when a model is set", async () => {
  assert.ok(resultHtml(MOCK_MARKED, { llm: true }).includes('data-act="vary">Make variants of the 3 missed questions'));
  assert.ok(!resultHtml(MOCK_MARKED, { llm: false }).includes('data-act="vary"'));
  const clean = { ...MOCK_MARKED, result: { ...MOCK_MARKED.result, missed: [] } };
  assert.ok(!resultHtml(clean, { llm: true }).includes('data-act="vary"'));
  const toasts = [];
  const { ctx, calls } = fakeCtx({ reply: { queued: 3 }, toast: (m) => toasts.push(m) });
  _set({ openId: 1 });
  await actions.vary({}, ctx);
  assert.deepEqual(calls, [["POST", "/api/mocks/1/vary", {}]]);
  assert.deepEqual(toasts, ["3 jobs queued: they run within today's budget"]);
  _set({ openId: null });
});

test("questions to check are listed with a retire button", async () => {
  _set({ openId: null });
  const row = { id: 31, flags: ["suspect"], trust: "unverified", attempts: 2, mean: 0.25, prompt: "What is <b>?" };
  const out = html(STATE, { exam: { ...EXAM, to_check: [row] } });
  assert.ok(out.includes("<h2>Questions to check</h2>"));
  assert.ok(out.includes("unverified · 2 tries, mean 25%"));
  assert.ok(out.includes("What is &lt;b&gt;?"));
  assert.ok(out.includes('data-act="retireQuestion" data-id="31" data-reason="flagged: suspect">Retire'));
  assert.ok(!html(STATE, { exam: { ...EXAM, to_check: [] } }).includes("questions to check"));
  const { ctx, calls } = fakeCtx();
  await actions.retireQuestion({ id: "31", reason: "flagged: suspect" }, ctx);
  assert.deepEqual(calls, [["POST", "/api/questions/31/retire", { reason: "flagged: suspect" }]]);
});
