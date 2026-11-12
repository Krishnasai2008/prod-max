import test from "node:test";
import assert from "node:assert/strict";

import { NEXT, STATE, STUDY } from "./fixture.mjs";
import * as review from "../../pm/ui/review.js";
import * as study from "../../pm/ui/study.js";
import * as exam from "../../pm/ui/exam.js";
import * as spot from "../../pm/ui/spot.js";

function fakeCtx(confirm, reply = () => ({})) {
  const calls = [];
  const asked = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return reply(method, path);
    },
    refresh: async () => {},
    go: () => {},
    toast: (message) => calls.push(["TOAST", message]),
    run: (name, data) => calls.push(["RUN", name, data]),
    confirm: (message) => (asked.push(message), confirm),
  };
  return { ctx, calls, asked };
}

test("suspend asks first and posts only on yes", async () => {
  const no = fakeCtx(false, () => NEXT);
  await review.enter(no.ctx);
  no.calls.length = 0;
  await review.actions.suspend({}, no.ctx);
  assert.deepEqual(no.calls, []);
  assert.equal(no.asked.length, 1);
  const yes = fakeCtx(true, () => NEXT);
  await review.actions.suspend({}, yes.ctx);
  assert.equal(yes.calls[0][0], "POST");
  assert.ok(yes.calls[0][1].endsWith("/suspend"));
});

test("retire asks first and says how to undo it", async () => {
  const no = fakeCtx(false);
  await exam.actions.retireQuestion({ id: "7", reason: "wrong key" }, no.ctx);
  assert.deepEqual(no.calls, []);
  assert.ok(no.asked[0].includes("pm q restore 7"));
  const yes = fakeCtx(true);
  await exam.actions.retireQuestion({ id: "7", reason: "wrong key" }, yes.ctx);
  assert.deepEqual(yes.calls, [["POST", "/api/questions/7/retire", { reason: "wrong key" }]]);
});

test("suspended items are listed with a resume button, and escaped", async () => {
  const none = study.html(STATE, { study: STUDY });
  assert.ok(!none.includes("Suspended items"));
  const out = study.html(STATE, {
    study: { ...STUDY, suspended: [{ id: 4, title: "<b>TLB</b>", topic_id: STUDY.topics[0].id }] },
  });
  assert.ok(out.includes("Suspended items"));
  assert.ok(out.includes("&lt;b&gt;TLB&lt;/b&gt;"));
  assert.ok(out.includes('<button type="button" class="btn btn-small" data-act="resumeItem" data-id="4">Resume</button>'));
  const { ctx, calls } = fakeCtx(true);
  await study.actions.resumeItem({ id: "4" }, ctx);
  assert.deepEqual(calls[0], ["POST", "/api/items/4/suspend", { on: false }]);
});

test("an empty next topic says to add items instead of offering a review", () => {
  const first = STUDY.topics[0];
  const empty = {
    ...STUDY,
    next: { topic_id: first.id, unblocks_id: null },
    topics: [{ ...first, items: 0 }, ...STUDY.topics.slice(1)],
  };
  const out = study.html(STATE, { study: empty });
  assert.ok(out.includes("nothing in it yet"));
});

test("n is not a shortcut on the spot screen before the answer is shown", () => {
  const { ctx, calls } = fakeCtx(true);
  assert.equal(spot.keys({ key: "n", target: { tagName: "BODY" } }, ctx), false);
  assert.deepEqual(calls, []);
});
