import test from "node:test";
import assert from "node:assert/strict";

import { STATE } from "./fixture.mjs";
import { actions, diffHtml, html, load } from "../../pm/ui/bugs.js";

const SUMMARY = {
  fixed: 2,
  open: 1,
  abandoned: 0,
  lost_min: 47,
  untagged: 3,
  tags: [
    ["off-by-one", 4],
    ["overflow", 1],
  ],
  bursts: [["off-by-one", 3]],
};

const DIFF =
  "--- a/x.c\n+++ b/x.c\n@@ -1 +1 @@\n-for (i = 0; i <= n; i++)\n+for (i = 0; i < n; i++)";

function episode(overrides = {}) {
  return {
    id: 12,
    cmd: "make test",
    cwd: "~/os",
    status: "fixed",
    opened: "2026-11-09T10:02:00",
    closed: "2026-11-09T10:08:00",
    fails: 2,
    lost_min: 8,
    tags: ["off-by-one"],
    diff: DIFF,
    runs: [
      { start: "2026-11-09T10:02:00", dur_s: 1.3, code: 2 },
      { start: "2026-11-09T10:04:00", dur_s: 0.8, code: 2 },
      { start: "2026-11-09T10:08:00", dur_s: 0.5, code: 0 },
    ],
    ...overrides,
  };
}

const BUGS = { summary: SUMMARY, episodes: [episode()] };
const DETAIL = episode();

function fakeCtx(reply = BUGS) {
  const calls = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      if (typeof reply === "function") return reply(method, path);
      if (path.endsWith("/tags")) return { tags: body?.tags ?? [] };
      if (path === "/api/bugs" || path.startsWith("/api/bugs?")) return reply;
      return DETAIL;
    },
    async refresh() {},
    go() {},
    toast() {},
    run() {},
    patch() {},
    confirm: () => true,
    openAddStudy: async () => {},
  };
  return { ctx, calls };
}

function spans(out) {
  return out.match(/<span/g) ?? [];
}

function reset() {
  actions.close();
  actions.filter({});
  html(STATE, {});
}

test.afterEach(reset);

test("html says loading until the bug list arrives", () => {
  assert.equal(html(STATE, {}), '<p class="muted">loading…</p>');
});

test("an empty extra drops the stored list and shows loading again", () => {
  html(STATE, { bugs: BUGS });
  assert.equal(html(STATE, {}), '<p class="muted">loading…</p>');
});

test("diffHtml marks meta, hunk, removed and added lines", () => {
  const out = diffHtml(DIFF);
  assert.equal((out.match(/class="meta"/g) ?? []).length, 2);
  assert.equal((out.match(/class="hunk"/g) ?? []).length, 1);
  assert.equal((out.match(/class="del"/g) ?? []).length, 1);
  assert.equal((out.match(/class="add"/g) ?? []).length, 1);
  assert.ok(out.includes("&lt;="));
});

test("diffHtml escapes a script tag", () => {
  const out = diffHtml("+<script>alert(1)</script>");
  assert.ok(!out.includes("<script"));
  assert.ok(out.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
});

test("a trailing newline adds no empty span", () => {
  const out = diffHtml("+x\n");
  assert.equal(spans(out).length, 1);
  assert.ok(!out.includes("<span></span>"));
});

test("a removed line of two dashes is del and a file header is meta", () => {
  const out = diffHtml("--x\n--- a/x");
  assert.ok(out.includes('<span class="del">--x</span>'));
  assert.ok(out.includes('<span class="meta">--- a/x</span>'));
});

test("diff lines are joined with newlines so a copy keeps them", () => {
  const out = diffHtml("+a\n+b");
  assert.equal(
    out,
    '<pre class="diff"><span class="add">+a</span>\n<span class="add">+b</span></pre>',
  );
});

test("a long diff keeps the first 2,000 lines and counts the rest", () => {
  const lines = Array.from({ length: 2500 }, (_, i) => `+line ${i}`);
  const out = diffHtml(lines.join("\n"));
  assert.equal(spans(out).length, 2001);
  assert.ok(out.includes("… (500 more lines)"));
});

test("the list shows the episode fields, its tags and opened date", () => {
  const out = html(STATE, { bugs: BUGS });
  assert.ok(out.includes("#12"));
  assert.ok(out.includes("fixed"));
  assert.ok(out.includes("make test"));
  assert.ok(out.includes("~/os"));
  assert.ok(out.includes("2 fails"));
  assert.ok(out.includes("lost 8m"));
  assert.ok(out.includes("off-by-one"));
  assert.ok(out.includes("2026-11-09"));
});

test("a command from the database is escaped", () => {
  const out = html(STATE, {
    bugs: { ...BUGS, episodes: [episode({ cmd: "<b>x</b>" })] },
  });
  assert.ok(!out.includes("<b>x</b>"));
  assert.ok(out.includes("&lt;b&gt;x&lt;/b&gt;"));
});

test("bursts get a line and an empty burst list gets none", () => {
  assert.ok(
    html(STATE, { bugs: BUGS }).includes("burst: off-by-one ×3 in 7 days"),
  );
  const quiet = html(STATE, {
    bugs: { ...BUGS, summary: { ...SUMMARY, bursts: [] } },
  });
  assert.ok(!quiet.includes("burst:"));
});

test("no episodes says no bugs yet and how to record them", () => {
  const empty = {
    summary: {
      fixed: 0,
      open: 0,
      abandoned: 0,
      lost_min: 0,
      untagged: 0,
      tags: [],
      bursts: [],
    },
    episodes: [],
  };
  const out = html(STATE, { bugs: empty });
  assert.ok(out.includes("no bugs yet"));
  assert.ok(out.includes("pm run --"));
});

test("an open episode shows its times, runs, tags, add form and diff", () => {
  const out = html(STATE, { bugs: BUGS, bug: DETAIL });
  assert.ok(out.includes("opened 2026-11-09 10:02"));
  assert.ok(out.includes("closed 2026-11-09 10:08"));
  assert.ok(out.includes("10:02"));
  assert.ok(out.includes("exit 2"));
  assert.ok(out.includes("(1.3s)"));
  assert.ok(out.includes("passed"));
  assert.ok(out.includes('aria-label="remove tag off-by-one"'));
  assert.ok(out.includes('<form data-act="addTag" data-id="12"'));
  assert.ok(out.includes('name="tag" list="bug-tags"'));
  assert.ok(out.includes('<option value="segfault"></option>'));
  assert.ok(out.includes('class="diff"'));
  assert.ok(out.includes("for (i = 0; i &lt; n; i++)"));
});

test("an episode with no diff shows the cli line", () => {
  const out = html(STATE, { bugs: BUGS, bug: episode({ diff: null }) });
  assert.ok(out.includes("no diff (not a git repo, or not fixed)"));
  assert.ok(!out.includes('class="diff"'));
});

test("addTag posts the whole new tag list", async () => {
  html(STATE, { bugs: BUGS, bug: DETAIL });
  const { ctx, calls } = fakeCtx();
  await actions.addTag({ id: "12", tag: "bounds" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/bugs/12/tags", { tags: ["off-by-one", "bounds"] }],
  ]);
});

test("addTag falls back to the list entry and ignores a tag already there", async () => {
  html(STATE, { bugs: BUGS });
  const { ctx, calls } = fakeCtx();
  await actions.addTag({ id: "12", tag: "bounds" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/bugs/12/tags", { tags: ["off-by-one", "bounds"] }],
  ]);
  calls.length = 0;
  await actions.addTag({ id: "12", tag: "off-by-one" }, ctx);
  assert.deepEqual(calls, []);
});

test("dropTag posts the remaining tags", async () => {
  html(STATE, { bugs: BUGS, bug: DETAIL });
  const { ctx, calls } = fakeCtx();
  await actions.dropTag({ id: "12", tag: "off-by-one" }, ctx);
  assert.deepEqual(calls, [["POST", "/api/bugs/12/tags", { tags: [] }]]);
});

test("dropTag falls back to the list entry when no detail is loaded", async () => {
  const tagged = {
    ...BUGS,
    episodes: [episode({ tags: ["off-by-one", "overflow"] })],
  };
  html(STATE, { bugs: tagged });
  const { ctx, calls } = fakeCtx(tagged);
  await actions.dropTag({ id: "12", tag: "off-by-one" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/bugs/12/tags", { tags: ["overflow"] }],
  ]);
});

test("tag actions for an unknown episode post nothing", async () => {
  html(STATE, { bugs: BUGS });
  const { ctx, calls } = fakeCtx();
  await actions.addTag({ id: "99", tag: "bounds" }, ctx);
  await actions.dropTag({ id: "99", tag: "off-by-one" }, ctx);
  assert.deepEqual(calls, []);
});

test("tag actions with no list and no detail post nothing", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.addTag({ id: "12", tag: "bounds" }, ctx);
  await actions.dropTag({ id: "12", tag: "off-by-one" }, ctx);
  assert.deepEqual(calls, []);
});

test("filter makes the next load ask for that tag", async () => {
  actions.filter({ tag: "overflow" });
  const { ctx, calls } = fakeCtx(BUGS);
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/bugs?tag=overflow"]]);
  assert.equal(extra.bugs, BUGS);
});

test("a tag with an ampersand is URL-encoded", async () => {
  actions.filter({ tag: "a&b" });
  const { ctx, calls } = fakeCtx(BUGS);
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/bugs?tag=a%26b"]]);
});

test("show all clears the filter and the next load asks for every bug", async () => {
  actions.filter({ tag: "x" });
  actions.filter({});
  const { ctx, calls } = fakeCtx(BUGS);
  const extra = await load(ctx);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "GET");
  assert.equal(calls[0][1], "/api/bugs");
  assert.ok(!calls[0][1].includes("?"));
  assert.equal(extra.bugs, BUGS);
});

test("the active filter is pressed and the others are not", () => {
  actions.filter({ tag: "off-by-one" });
  const out = html(STATE, { bugs: BUGS });
  const active = out.match(/<button[^>]*data-tag="off-by-one"[^>]*>/)?.[0] ?? "";
  const other = out.match(/<button[^>]*data-tag="overflow"[^>]*>/)?.[0] ?? "";
  assert.ok(active.includes('aria-pressed="true"'));
  assert.ok(other.includes('aria-pressed="false"'));
  assert.ok(out.includes("show all"));
});

test("open loads the detail and close stops loading it", async () => {
  actions.open({ id: "12" });
  const { ctx, calls } = fakeCtx((_method, path) =>
    path === "/api/bugs" ? BUGS : DETAIL,
  );
  const extra = await load(ctx);
  assert.deepEqual(calls, [
    ["GET", "/api/bugs"],
    ["GET", "/api/bugs/12"],
  ]);
  assert.equal(extra.bug, DETAIL);

  actions.close();
  calls.length = 0;
  const again = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/bugs"]]);
  assert.equal(again.bug, null);
});

test("a bug that is gone closes, so the next load works again", async () => {
  actions.close();
  actions.filter({});
  actions.open({ id: "9" });
  const calls = [];
  const ctx = {
    async api(method, path) {
      calls.push(path);
      if (path === "/api/bugs/9") throw new Error("no bug #9");
      return BUGS;
    },
  };
  await assert.rejects(load(ctx), /no bug #9/);
  calls.length = 0;
  await load(ctx);
  assert.deepEqual(calls, ["/api/bugs"]);
  html(STATE, {});
});
