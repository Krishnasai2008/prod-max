import test from "node:test";
import assert from "node:assert/strict";

import { EXCERPT, NEXT, STATE } from "./fixture.mjs";
import { actions, after, enter, html, input, keys, load } from "../../pm/ui/review.js";

function fakeCtx(handler = () => ({})) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return handler(method, path, body);
    },
    refresh: async () => {},
    go(name) {
      calls.push(["GO", name]);
    },
    toast() {},
    run(name, data) {
      calls.push(["RUN", name, data]);
    },
  };
  return { ctx, calls };
}

async function start(handler = () => NEXT) {
  const made = fakeCtx(handler);
  await enter(made.ctx);
  return made;
}

test("enter fetches the next item once and starts at the bet", async () => {
  const { ctx, calls } = fakeCtx(() => NEXT);
  await enter(ctx);
  assert.deepEqual(calls, [["GET", "/api/review/next"]]);

  const out = html(STATE);
  assert.ok(out.includes("notes.md › TLB"));
  assert.ok(out.includes("1 of 7"));
  assert.ok(out.includes("os / paging"));
  assert.ok(out.includes("<strong>TLB</strong>"));
  assert.ok(out.includes('type="range"'));
  assert.ok(out.includes('name="confidence"'));
  assert.ok(out.includes('min="0"'));
  assert.ok(out.includes('max="100"'));
  assert.ok(out.includes('step="5"'));
  assert.ok(out.includes('value="50"'));
  assert.ok(out.includes("50%"));
  assert.ok(out.includes("Show answer"));
  assert.ok(!out.includes('data-act="grade"'));
  assert.ok(!out.includes("A cache of page-table entries."));
});

test("bet fetches only the excerpt and reveals the answer and intervals", async () => {
  const { ctx, calls } = await start((method, path) =>
    path.endsWith("/excerpt") ? EXCERPT : NEXT,
  );
  calls.length = 0;
  await actions.bet({ confidence: "70" }, ctx);
  assert.deepEqual(calls, [["GET", "/api/items/5/excerpt"]]);

  const out = html(STATE);
  assert.ok(out.includes("What is a <strong>TLB</strong>?"));
  assert.ok(out.includes('<div class="md question">'));
  assert.ok(out.includes('<div class="md answer">'));
  assert.ok(!out.includes('class="md excerpt"'));
  assert.ok(out.includes("A cache of page-table entries."));
  for (const grade of [1, 2, 3, 4]) {
    assert.ok(out.includes(`data-act="grade" data-grade="${grade}"`));
  }
  assert.ok(out.includes("Again · in 10m"));
  assert.ok(out.includes("Good · in 3d"));
  assert.ok(out.includes("~/notes/os.md › TLB"));
  assert.ok(out.includes("Suspend"));
});

test("a missing excerpt still lets you grade or suspend", async () => {
  const missing = {
    ...EXCERPT,
    kind: "missing",
    text: null,
    error: "no such file: /home/u/notes/os.md",
  };
  const { ctx } = fakeCtx((method, path) => (path.endsWith("/excerpt") ? missing : NEXT));
  await enter(ctx);
  await actions.bet({ confidence: "50" }, ctx);
  const out = html(STATE);
  assert.ok(out.includes("can't show this item: no such file: /home/u/notes/os.md"));
  assert.ok(out.includes("grade it from memory, or suspend it"));
  assert.ok(out.includes('data-grade="1"'));
  assert.ok(out.includes('data-act="suspend"'));
});

test("a pdf excerpt shows the page image or falls back to its text", async () => {
  const image = {
    ...EXCERPT,
    kind: "pdf",
    text: null,
    image: "/api/items/5/page.png?v=123",
    path: "~/slides/week3.pdf",
    locator: "p12",
  };
  const { ctx, calls } = fakeCtx((method, path) =>
    path.endsWith("/excerpt") ? image : NEXT,
  );
  await enter(ctx);
  await actions.bet({ confidence: "50" }, ctx);
  assert.deepEqual(calls, [
    ["GET", "/api/review/next"],
    ["GET", "/api/items/5/excerpt"],
  ]);
  const out = html(STATE);
  assert.ok(out.includes('src="/api/items/5/page.png?v=123"'));
  assert.ok(out.includes('alt="page 12 of week3.pdf"'));

  const fallback = { ...image, image: null, text: "the page as text" };
  const textCtx = fakeCtx((method, path) =>
    path.endsWith("/excerpt") ? fallback : NEXT,
  );
  await enter(textCtx.ctx);
  await actions.bet({ confidence: "50" }, textCtx.ctx);
  const textOut = html(STATE);
  assert.ok(textOut.includes("<pre class=\"excerpt\">the page as text</pre>"));
});

test("an excerpt is escaped in a pre, and api strings are escaped", async () => {
  const dangerous = {
    ...EXCERPT,
    kind: "text",
    text: "<script>alert(1)</script>",
    path: '<img src=x onerror=alert(1)>',
    locator: "<b>",
  };
  const { ctx } = fakeCtx((method, path) => (path.endsWith("/excerpt") ? dangerous : NEXT));
  await enter(ctx);
  await actions.bet({ confidence: "50" }, ctx);
  const out = html(STATE);
  assert.ok(out.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(!out.includes("<script>alert(1)"));
  assert.ok(out.includes("&lt;img src=x onerror=alert(1)&gt;"));
  assert.ok(out.includes("&lt;b&gt;"));
});

test("grade posts numbers and then asks for the next item", async () => {
  const { ctx, calls } = await start((method, path) =>
    path.endsWith("/excerpt") ? EXCERPT : NEXT,
  );
  await actions.bet({ confidence: "70" }, ctx);
  calls.length = 0;
  await actions.grade({ grade: "3" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/items/5/review", { grade: 3, confidence: 70 }],
    ["GET", "/api/review/next"],
  ]);
});

test("two grades give the session totals, and the held line", async () => {
  let nextCalls = 0;
  const { ctx } = fakeCtx((method, path) => {
    if (path === "/api/review/next") {
      nextCalls += 1;
      if (nextCalls === 1) return NEXT;
      if (nextCalls === 2) return { ...NEXT, left: 6 };
      return { left: 0, held: 2, item: null };
    }
    if (path.endsWith("/excerpt")) return EXCERPT;
    return {};
  });
  await enter(ctx);
  await actions.bet({ confidence: "80" }, ctx);
  await actions.grade({ grade: "3" }, ctx);
  await actions.bet({ confidence: "60" }, ctx);
  await actions.grade({ grade: "1" }, ctx);

  const out = html(STATE);
  assert.ok(out.includes("reviewed 2 · recalled 1 · you said 70% on average, recalled 50%"));
  assert.ok(out.includes("2 new items wait for another day"));
});

test("an empty queue says nothing due", async () => {
  const { ctx } = fakeCtx(() => ({ left: 0, held: 0, item: null }));
  await enter(ctx);
  const out = html(STATE);
  assert.ok(out.includes("nothing due"));
  assert.ok(!out.includes("reviewed"));
});

test("keys set the confidence, grade, and escape to today", async () => {
  const { ctx, calls } = await start();
  assert.equal(keys({ key: "7" }, ctx), true);
  assert.ok(html(STATE).includes('value="70"'));
  assert.ok(html(STATE).includes("70%"));
  assert.equal(keys({ key: "0" }, ctx), true);
  assert.ok(html(STATE).includes('value="100"'));

  calls.length = 0;
  assert.equal(keys({ key: "Enter" }, ctx), true);
  assert.deepEqual(calls, [["RUN", "bet", { confidence: "100" }]]);

  await actions.bet({ confidence: "70" }, ctx);
  calls.length = 0;
  assert.equal(keys({ key: "3" }, ctx), true);
  assert.deepEqual(calls, [["RUN", "grade", { grade: "3" }]]);

  calls.length = 0;
  assert.equal(keys({ key: "Escape" }, ctx), true);
  assert.deepEqual(calls, [["GO", "today"]]);
});

test("keys ignore a text field but work on the range and the body", async () => {
  const { ctx } = await start();
  const text = { tagName: "INPUT", type: "text" };
  const range = { tagName: "INPUT", type: "range" };
  const body = { tagName: "BODY" };

  assert.equal(keys({ key: "7", target: text }, ctx), false);
  assert.ok(html(STATE).includes('value="50"'));
  assert.equal(keys({ key: "7", target: range }, ctx), true);
  assert.ok(html(STATE).includes('value="70"'));
  assert.equal(keys({ key: "6", target: body }, ctx), true);
  assert.ok(html(STATE).includes('value="60"'));
  assert.equal(keys({ key: "x", target: body }, ctx), false);
});

test("keys leave a focused button, link or summary to its native behaviour", async () => {
  const { ctx } = await start();
  const widget = (tagName) => ({
    tagName,
    closest: (selector) => (selector === "a, button, summary" ? {} : null),
  });
  for (const target of [widget("BUTTON"), widget("A"), widget("SUMMARY")]) {
    assert.equal(keys({ key: "Enter", target }, ctx), false);
    assert.equal(keys({ key: "7", target }, ctx), false);
  }
  const range = { tagName: "INPUT", type: "range", closest: () => null };
  assert.equal(keys({ key: "7", target: range }, ctx), true);
  assert.ok(html(STATE).includes('value="70"'));
});

test("keys are swallowed while a request is in flight", async () => {
  const { ctx, calls } = await start();
  let busy = true;
  ctx.busy = () => busy;
  calls.length = 0;
  for (const key of ["7", "0", "Enter", " ", "3", "Escape"]) {
    assert.equal(keys({ key }, ctx), true);
  }
  assert.deepEqual(calls, []);
  assert.ok(html(STATE).includes('value="50"'));

  busy = false;
  assert.equal(keys({ key: "7" }, ctx), true);
  assert.ok(html(STATE).includes('value="70"'));
});

test("the confidence is committed when the bet is placed", async () => {
  let release;
  const { ctx, calls } = await start((method, path) =>
    path.endsWith("/excerpt")
      ? new Promise((resolve) => {
          release = resolve;
        })
      : NEXT,
  );
  const betting = actions.bet({ confidence: "70" }, ctx);
  assert.equal(keys({ key: "9" }, ctx), true);
  release(EXCERPT);
  await betting;
  calls.length = 0;
  await actions.grade({ grade: "3" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/items/5/review", { grade: 3, confidence: 70 }],
    ["GET", "/api/review/next"],
  ]);
});

test("html says loading until enter has fetched the first item", async () => {
  let release;
  const { ctx } = fakeCtx(
    () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  );
  const entering = enter(ctx);
  assert.equal(html(STATE), '<p class="muted">loading…</p>');
  release(NEXT);
  await entering;
  assert.ok(html(STATE).includes("Show answer"));
});

test("load fetches a newly due item only from the done screen", async () => {
  let nextCalls = 0;
  const { ctx, calls } = fakeCtx((method, path) => {
    if (path !== "/api/review/next") return {};
    nextCalls += 1;
    return nextCalls === 1 ? { left: 0, held: 0, item: null } : NEXT;
  });
  await enter(ctx);
  assert.ok(html(STATE).includes("nothing due"));

  calls.length = 0;
  let extra = await load({ ...ctx, state: { ...STATE, reviews_due: 0 } });
  assert.deepEqual(extra, { item: null, stage: "done" });
  assert.deepEqual(calls, []);

  extra = await load({ ...ctx, state: { ...STATE, reviews_due: 1 } });
  assert.deepEqual(extra, { item: 5, stage: "bet" });
  assert.deepEqual(calls, [["GET", "/api/review/next"]]);
  assert.ok(html(STATE).includes("Show answer"));

  calls.length = 0;
  extra = await load({ ...ctx, state: { ...STATE, reviews_due: 1 } });
  assert.deepEqual(extra, { item: 5, stage: "bet" });
  assert.deepEqual(calls, []);
});

test("the input hook stores the slider value and updates the readout", async () => {
  await start();
  const readout = { textContent: "50%" };
  const target = {
    name: "confidence",
    value: "65",
    form: { querySelector: () => readout },
  };
  input({ target }, {});
  assert.equal(readout.textContent, "65%");
  assert.ok(html(STATE).includes('value="65"'));
});

test("after is quiet without maths and safe to call everywhere", async () => {
  await start();
  const root = { querySelectorAll: () => [] };
  assert.equal(after(root), undefined);
  await enter(fakeCtx(() => ({ ...NEXT, item: { ...NEXT.item, question: "what is $x$?" } })).ctx);
  assert.equal(after(root), undefined);
});

test("after typesets only the md elements, and only a markdown answer counts as maths", async () => {
  const seen = [];
  globalThis.window = {
    MathJax: {
      startup: { promise: Promise.resolve() },
      typesetPromise: (elements) => {
        seen.push(elements);
        return Promise.resolve();
      },
    },
  };
  globalThis.document = {};
  try {
    const questionEl = {};
    const answerEl = {};
    const { ctx } = await start((method, path) =>
      path.endsWith("/excerpt") ? { ...EXCERPT, text: "the answer is $x$" } : NEXT,
    );
    await actions.bet({ confidence: "50" }, ctx);
    const root = {
      querySelectorAll: (selector) => {
        assert.equal(selector, ".md");
        return [questionEl, answerEl];
      },
    };
    after(root);
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(seen, [[questionEl], [answerEl]]);

    seen.length = 0;
    const textCtx = fakeCtx((method, path) =>
      path.endsWith("/excerpt")
        ? { ...EXCERPT, kind: "text", text: "the answer is $x$" }
        : NEXT,
    );
    await enter(textCtx.ctx);
    await actions.bet({ confidence: "50" }, textCtx.ctx);
    let scanned = 0;
    after({
      querySelectorAll: () => {
        scanned += 1;
        return [];
      },
    });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(scanned, 0);
    assert.deepEqual(seen, []);

    await enter(
      fakeCtx(() => ({ ...NEXT, item: { ...NEXT.item, question: "what is $x$?" } })).ctx,
    );
    const betEl = {};
    after({ querySelectorAll: () => [betEl] });
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(seen, [[betEl]]);
  } finally {
    delete globalThis.window;
    delete globalThis.document;
  }
});

test("every data-act button on the review screen is type=button", async () => {
  const { ctx } = await start();
  await actions.bet({ confidence: "50" }, ctx);
  const out = html(STATE);
  for (const [tag] of out.matchAll(/<button[^>]*>/g)) {
    assert.match(tag, /type="(button|submit)"/);
    if (tag.includes("data-act")) assert.match(tag, /type="button"/);
  }
});

test("load retries when the first fetch failed", async () => {
  let fail = true;
  const { ctx } = fakeCtx((method, path) => {
    if (path !== "/api/review/next") return {};
    if (fail) throw new Error("offline");
    return NEXT;
  });
  await assert.rejects(enter(ctx));
  fail = false;
  const extra = await load({ ...ctx, state: { ...STATE, reviews_due: 1 } });
  assert.deepEqual(extra, { item: 5, stage: "bet" });
  assert.ok(html(STATE).includes("Show answer"));
});

test("a site link sits next to the source line when the answer is revealed", async () => {
  const { ctx } = fakeCtx((method, path) =>
    path.endsWith("/excerpt")
      ? { ...EXCERPT, site: "https://x.dev/os/paging/#tlb" }
      : NEXT,
  );
  await enter(ctx);
  await actions.bet({ confidence: "50" }, ctx);
  const out = html(STATE);
  assert.ok(out.includes('href="https://x.dev/os/paging/#tlb"'));
  assert.ok(out.includes('target="_blank"'));
  assert.ok(out.includes('rel="noopener noreferrer"'));
  assert.ok(out.includes("open on the site"));
  assert.ok(out.includes("~/notes/os.md › TLB"));
});

test("only an https site address draws the link", async () => {
  for (const site of [null, undefined, "", "javascript:alert(1)", "http://x.dev/a", 5]) {
    const { ctx } = fakeCtx((method, path) =>
      path.endsWith("/excerpt") ? { ...EXCERPT, site } : NEXT,
    );
    await enter(ctx);
    await actions.bet({ confidence: "50" }, ctx);
    const out = html(STATE);
    assert.ok(!out.includes("open on the site"), `site ${site}`);
    assert.ok(!out.includes("<a "), `site ${site}`);
  }
});

test("the site address and the source line are escaped", async () => {
  const { ctx } = fakeCtx((method, path) =>
    path.endsWith("/excerpt")
      ? { ...EXCERPT, site: 'https://x.dev/a?q="><script>' }
      : NEXT,
  );
  await enter(ctx);
  await actions.bet({ confidence: "50" }, ctx);
  const out = html(STATE);
  assert.ok(out.includes('href="https://x.dev/a?q=&quot;&gt;&lt;script&gt;"'));
  assert.ok(!out.includes('"><script>'));
});

test("the bet stage never shows the site link", async () => {
  const { ctx } = fakeCtx((method, path) =>
    path.endsWith("/excerpt") ? { ...EXCERPT, site: "https://x.dev/os/" } : NEXT,
  );
  await enter(ctx);
  assert.ok(!html(STATE).includes("open on the site"));
  assert.ok(!html(STATE).includes("https://x.dev"));
});
