import test from "node:test";
import assert from "node:assert/strict";

import { PRACTICE, PROBLEM, STATE, VERDICT } from "./fixture.mjs";
import { _set, actions, enter, html, keys, load } from "../../pm/ui/practice.js";

function fakeCtx(handler = () => ({})) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return handler(method, path, body);
    },
    run(name, data) {
      calls.push(["RUN", name, data]);
    },
    toast() {},
  };
  return { ctx, calls };
}

async function picking(overview = PRACTICE) {
  const made = fakeCtx(() => overview);
  await enter(made.ctx);
  await load(made.ctx);
  return made;
}

test("the pick stage lists linked topics, chips and tries", async () => {
  const { calls } = await picking();
  assert.deepEqual(calls, [["GET", "/api/practice"]]);
  const out = html(STATE);
  assert.ok(out.includes('<option value="">next best topic</option>'));
  assert.ok(out.includes('<option value="3">os/paging</option>'));
  assert.ok(!out.includes('<option value="4">'));
  assert.ok(out.includes('data-act="unlink" data-topic="3" data-gen="paging"'));
  assert.ok(out.includes("6 tries, 4 right in 30 days"));
  assert.ok(out.includes('<form data-act="link" data-topic="4"'));
  assert.ok(out.includes("bad.toml: &lt;b&gt;"));
  assert.ok(!out.includes("<b>the template"));
});

test("no links anywhere shows the hint", async () => {
  await picking({ ...PRACTICE, topics: PRACTICE.topics.map((t) => ({ ...t, gens: [] })), errors: [] });
  assert.ok(html(STATE).includes("link a generator to a topic to start: paging, cpu, disk"));
});

test("start asks for a problem, for one topic or the next best", async () => {
  const { ctx, calls } = fakeCtx(() => PROBLEM);
  await actions.start({ topic: "" }, ctx);
  await actions.start({ topic: "3" }, ctx);
  assert.deepEqual(calls, [["GET", "/api/practice/next"], ["GET", "/api/practice/next?topic=3"]]);
});

test("the problem stage renders the text and nothing of the verdict", async () => {
  const { ctx } = fakeCtx(() => PROBLEM);
  await actions.start({ topic: "" }, ctx);
  const out = html(STATE);
  assert.ok(out.includes("<table>"));
  assert.ok(out.includes('<form data-act="answer">'));
  assert.ok(out.includes('data-act="dontKnow"'));
  assert.ok(!out.includes("walkthrough"));
});

test("answer posts the problem, the answer, the confidence and the time", async () => {
  const { ctx, calls } = fakeCtx((method) => (method === "GET" ? PROBLEM : VERDICT));
  await actions.start({ topic: "" }, ctx);
  await actions.answer({ answer: "12", confidence: "80" }, ctx);
  const [method, path, body] = calls[1];
  assert.equal(method, "POST");
  assert.equal(path, "/api/practice/answer");
  assert.deepEqual({ ...body, seconds: 0 }, {
    topic_id: 3, gen: "paging", seed: 1804289383, variant: "count", answer: "12", confidence: 80,
    dont_know: false, seconds: 0,
  });
  assert.equal(typeof body.seconds, "number");
  const out = html(STATE);
  assert.ok(out.includes("wrong: the answer is 12"));
  assert.ok(out.includes("pm couldn't read that as a number"));
  assert.ok(out.includes("walkthrough"));
  assert.ok(out.includes('data-act="next"'));
});

test("don't know posts no confidence and shows the answer", async () => {
  const { ctx, calls } = fakeCtx((method) => (method === "GET" ? PROBLEM : { ...VERDICT, readable: true }));
  await actions.start({ topic: "" }, ctx);
  await actions.dontKnow({}, ctx);
  const body = calls[1][2];
  assert.equal(body.dont_know, true);
  assert.ok(!("confidence" in body));
  const out = html(STATE);
  assert.ok(out.includes("the answer is 12"));
  assert.ok(!out.includes("wrong"));
});

test("a right answer says right", () => {
  _set({ stage: "verdict", problem: PROBLEM, verdict: { ...VERDICT, correct: true, readable: true }, dontKnew: false });
  assert.ok(html(STATE).includes("<strong>right</strong>"));
});

test("link and unlink post the topic id as a number", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.link({ topic: "3", gen: "disk" }, ctx);
  await actions.unlink({ topic: "3", gen: "paging" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/practice/link", { topic_id: 3, gen: "disk" }],
    ["POST", "/api/practice/unlink", { topic_id: 3, gen: "paging" }],
  ]);
});

test("keys: n goes on from the verdict, Escape stops, typing is left alone", () => {
  const { ctx, calls } = fakeCtx();
  _set({ stage: "verdict", problem: PROBLEM, verdict: VERDICT });
  assert.equal(keys({ key: "n", target: { tagName: "BODY" } }, ctx), true);
  assert.equal(keys({ key: "n", target: { tagName: "INPUT" } }, ctx), false);
  assert.equal(keys({ key: "Escape", target: { tagName: "INPUT" } }, ctx), false); // typing: the problem stays
  assert.equal(keys({ key: "Escape", target: { tagName: "BODY" } }, ctx), true);
  _set({ stage: "pick" });
  assert.equal(keys({ key: "Escape", target: { tagName: "BODY" } }, ctx), false);
  assert.deepEqual(calls, [["RUN", "next", {}], ["RUN", "stop", {}]]);
});
