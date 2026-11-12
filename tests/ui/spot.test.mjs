import test from "node:test";
import assert from "node:assert/strict";

import { SPOT, STATE } from "./fixture.mjs";
import { actions, enter, html, keys, load } from "../../pm/ui/spot.js";

function fakeCtx(handler = () => SPOT) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return handler(method, path, body);
    },
    go(name) {
      calls.push(["GO", name]);
    },
    run(name, data) {
      calls.push(["RUN", name, data]);
    },
    toast() {},
  };
  return { ctx, calls };
}

async function started(handler) {
  const made = fakeCtx(handler);
  await enter(made.ctx);
  return made;
}

test("the bet stage shows the escaped lines and no line buttons", async () => {
  const { calls } = await started();
  assert.deepEqual(calls, [["GET", "/api/spot/next"]]);
  const out = html(STATE);
  assert.ok(out.includes("notes.md › TLB"));
  assert.ok(out.includes("b &lt;i&gt;"));
  assert.ok(!out.includes("<i>"));
  assert.ok(!out.includes('data-act="pick"'));
  assert.ok(out.includes('<form data-act="bet">'));
  assert.ok(out.includes("Lock in"));
});

test("after the bet every line is a pick button; the pick posts both", async () => {
  const { ctx, calls } = await started((method, path) =>
    path === "/api/spot/next" ? SPOT : { correct: false, line: 2, was: "b", shown: "b <i>" },
  );
  await actions.bet({ confidence: "80" }, ctx);
  const pick = html(STATE);
  for (const n of [1, 2, 3, 4]) assert.ok(pick.includes(`data-act="pick" data-line="${n}"`));
  await actions.pick({ line: "3" }, ctx);
  assert.deepEqual(calls.at(-1), ["POST", "/api/spots/1/answer", { picked: 3, confidence: 80 }]);
  const out = html(STATE);
  assert.ok(out.includes("wrong: it was line 2"));
  assert.ok(out.includes("was:") && out.includes("shown:"));
  assert.ok(out.includes("b &lt;i&gt;"));
  assert.ok(out.includes('class="spot-wrong"'));
  assert.ok(out.includes('class="spot-picked"'));
  assert.ok(out.includes('data-act="next"'));
});

test("a right pick says right", async () => {
  const { ctx } = await started((method, path) =>
    path === "/api/spot/next" ? SPOT : { correct: true, line: 3, was: "c", shown: "C" },
  );
  await actions.bet({ confidence: "60" }, ctx);
  await actions.pick({ line: "3" }, ctx);
  assert.ok(html(STATE).includes("<strong>right</strong>"));
});

test("no card says so and links back to Study", async () => {
  await started(() => ({ left: 0, spot: null }));
  const out = html(STATE);
  assert.ok(out.includes("no spot cards"));
  assert.ok(out.includes('href="#/study"'));
});

test("keys: digits set the bet, Enter locks it in, Escape goes to Study; all synchronous booleans", async () => {
  const { ctx, calls } = await started();
  assert.equal(keys({ key: "7", target: null }, ctx), true);
  assert.equal(keys({ key: "Enter", target: null }, ctx), true);
  assert.deepEqual(calls.at(-1), ["RUN", "bet", { confidence: "70" }]);
  assert.equal(keys({ key: "x", target: null }, ctx), false);
  assert.equal(keys({ key: "Escape", target: null }, ctx), true);
  assert.deepEqual(calls.at(-1), ["GO", "study"]);
});

test("load fetches a card only when there is none and state says some wait", async () => {
  const { ctx, calls } = fakeCtx(() => ({ left: 0, spot: null }));
  await enter(ctx);
  calls.length = 0;
  await load({ ...ctx, state: { ...STATE, spots: 0 } });
  assert.deepEqual(calls, []);
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/spot/next"]]);
});
