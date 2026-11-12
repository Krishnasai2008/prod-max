import test from "node:test";
import assert from "node:assert/strict";

import { esc } from "../../pm/ui/lib.js";
import { html, actions, load } from "../../pm/ui/tasks.js";
import { STATE } from "./fixture.mjs";

const FINISHED = [
  {
    id: 1,
    title: "DBMS quiz",
    kind: "task",
    est_min: 60,
    logged_min: 108,
    ratio: 1.8,
    due: "2026-11-08",
    done: "2026-11-08T12:00:00",
    late: true,
  },
];

function fakeCtx(overrides = {}) {
  const calls = [];
  const ctx = {
    state: STATE,
    api: async (method, path, body) => {
      calls.push([method, path, body]);
      return {};
    },
    refresh: async () => {},
    go: () => {},
    toast: () => {},
    confirm: () => true,
    ...overrides,
  };
  return { ctx, calls };
}

test.afterEach(() => actions.cancel());

test("html shows open tasks in order, their columns and the finished list", () => {
  const out = html(STATE, { finished: FINISHED });
  assert.ok(out.indexOf("OS lab 3") < out.indexOf("DBMS chapter 4"));
  assert.match(out, /45m \/ 4h/);
  assert.match(out, /late 40%/);
  assert.match(out, /BEHIND/);
  assert.match(out, /×1\.80/);
  assert.match(out, />late</);
  assert.match(out, /<datalist id="courses">/);
  assert.match(out, /<option value="os"><\/option>/);
});

test("html escapes titles in the open list and the finished list", () => {
  const title = '<img src=x onerror=alert(1)> & co';
  const state = { ...STATE, tasks: [{ ...STATE.tasks[0], title }] };
  const out = html(state, { finished: [{ ...FINISHED[0], title }] });
  const escaped = "&lt;img src=x onerror=alert(1)&gt; &amp; co";
  assert.equal(out.split(escaped).length - 1, 2);
  assert.ok(!out.includes("<img"));
});

test("html says no open tasks when the list is empty", () => {
  assert.match(html({ ...STATE, tasks: [] }, { finished: [] }), /no open tasks/);
});

test("the running row is marked and its start button is disabled", () => {
  const out = html(STATE, {});
  assert.match(out, /<tr class="running">/);
  assert.match(out, /data-act="start" data-id="3" disabled>running</);
});

test("every data-act button is type=button", () => {
  actions.edit({ id: "3" });
  const out = html(STATE, { finished: FINISHED });
  for (const [tag] of out.matchAll(/<button[^>]*>/g)) {
    assert.match(tag, /type="(button|submit)"/);
    if (tag.includes("data-act")) assert.match(tag, /type="button"/);
  }
});

test("add drops empty fields from the body", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.add(
    { title: "A", est: "2h", due: "", course: "", kind: "", energy: "deep", first: "" },
    ctx,
  );
  assert.deepEqual(calls, [
    ["POST", "/api/tasks", { title: "A", est: "2h", energy: "deep" }],
  ]);
});

test("edit draws the save form with the escaped title and locked estimate", () => {
  const title = '<img src=x onerror=alert(1)> & co';
  const state = { ...STATE, tasks: [{ ...STATE.tasks[0], title }] };
  actions.edit({ id: "3" });
  const out = html(state, {});
  assert.match(out, /<form data-act="save" data-id="3"/);
  assert.ok(out.includes(`value="${esc(title)}"`));
  assert.match(out, /name="est" value="4h" disabled/);
  assert.match(out, /locked: time is logged/);
});

test("edit leaves the estimate enabled when no time is logged", () => {
  actions.edit({ id: "4" });
  const out = html(STATE, {});
  assert.match(out, /<form data-act="save" data-id="4"/);
  assert.doesNotMatch(out, /name="est" value="1h" disabled/);
});

test("save sends only the changed fields and clears a due date with an empty string", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.save(
    {
      id: "3",
      title: "new",
      est: "4h",
      due: "",
      course: "os",
      kind: "lab",
      energy: "deep",
      first: "open the handout",
    },
    ctx,
  );
  assert.deepEqual(calls, [
    ["POST", "/api/tasks/3/edit", { title: "new", due: "" }],
  ]);
});

test("save with nothing changed makes no api call and leaves edit mode", async () => {
  actions.edit({ id: "3" });
  const { ctx, calls } = fakeCtx();
  await actions.save(
    {
      id: "3",
      title: "OS lab 3",
      est: "4h",
      due: "2026-11-12",
      course: "os",
      kind: "lab",
      energy: "deep",
      first: "open the handout",
    },
    ctx,
  );
  assert.deepEqual(calls, []);
  assert.doesNotMatch(html(STATE, {}), /data-act="save"/);
});

test("drop asks first and only posts when confirmed", async () => {
  let asked = "";
  const no = fakeCtx({
    confirm: (message) => {
      asked = message;
      return false;
    },
  });
  await actions.drop({ id: "3" }, no.ctx);
  assert.deepEqual(no.calls, []);
  assert.equal(asked, "Drop #3 OS lab 3? Its logged time is kept.");

  const yes = fakeCtx();
  await actions.drop({ id: "3" }, yes.ctx);
  assert.deepEqual(yes.calls, [["POST", "/api/tasks/3/drop", undefined]]);
});

test("start, log and done post to the task routes", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.start({ id: "3" }, ctx);
  await actions.log({ id: "3", duration: "30m" }, ctx);
  await actions.done({ id: "3" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/tasks/3/start", undefined],
    ["POST", "/api/tasks/3/log", { duration: "30m" }],
    ["POST", "/api/tasks/3/done", undefined],
  ]);
});

test("load fetches the finished tasks", async () => {
  const calls = [];
  const ctx = {
    ...fakeCtx().ctx,
    api: async (method, path) => {
      calls.push([method, path]);
      return { tasks: FINISHED };
    },
  };
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/finished"]]);
  assert.deepEqual(extra, { finished: FINISHED });
});

test("links show as chips: files open through pm, addresses are plain links", () => {
  const out = html(STATE, { finished: [] });
  assert.ok(out.includes('data-act="openLink" data-id="3" data-link="1"'));
  assert.ok(out.includes("~/os/lab3.pdf"));
  assert.ok(out.includes('<a href="https://example.com/lab3" target="_blank" rel="noopener noreferrer">'));
  assert.ok(out.includes('data-act="dropLink" data-id="3" data-link="2"'));
  assert.ok(out.includes('<form data-act="addLink" data-id="4"'));
});

test("a link that is not http(s) is never drawn as a link, and text is escaped", () => {
  const state = structuredClone(STATE);
  state.tasks[1].links = [
    { id: 7, target: "javascript:alert(1)", short: "javascript:alert(1)", kind: "url" },
    { id: 8, target: '/x/"><script>', short: '~/"><script>', kind: "missing" },
  ];
  const out = html(state, { finished: [] });
  assert.ok(!out.includes('href="javascript'));
  assert.ok(out.includes("<s>javascript:alert(1)</s>"));
  assert.ok(!out.includes("<script>"));
  assert.ok(out.includes("&lt;script&gt;"));
});

test("link actions call the routes", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.addLink({ id: "3", target: "/a/b.pdf" }, ctx);
  await actions.dropLink({ id: "3", link: "4" }, ctx);
  await actions.openLink({ id: "3", link: "4" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/tasks/3/links", { target: "/a/b.pdf" }],
    ["POST", "/api/tasks/3/links/4/drop", undefined],
    ["POST", "/api/tasks/3/links/4/open", undefined],
  ]);
});

test("opening a link that is gone says so", async () => {
  const toasts = [];
  const { ctx } = fakeCtx({ api: async () => ({ opened: 0, skipped: ["gone ~/x.pdf"] }), toast: (m) => toasts.push(m) });
  await actions.openLink({ id: "3", link: "4" }, ctx);
  assert.deepEqual(toasts, ["gone ~/x.pdf"]);
});
