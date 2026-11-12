import test from "node:test";
import assert from "node:assert/strict";

import { OUTLINE, STATE, STUDY } from "./fixture.mjs";
import { actions, current, html, input, open } from "../../pm/ui/addstudy.js";

function fakeCtx(routes = {}) {
  const calls = [];
  const toasts = [];
  const ctx = {
    state: STATE,
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      const key = `${method} ${path}`;
      const route = routes[key] ?? routes[path];
      if (route instanceof Error) throw route;
      if (typeof route === "function") return route(method, path, body);
      if (route !== undefined) return route;
      if (path === "/api/study") return STUDY;
      if (path.startsWith("/api/outline")) return OUTLINE;
      return {};
    },
    refresh: async () => {},
    go: () => {},
    toast(message) {
      toasts.push(message);
    },
    run: () => {},
    confirm: () => true,
  };
  return { ctx, calls, toasts };
}

function outlineRoute(outline) {
  return { [`GET /api/outline?path=${encodeURIComponent(OUTLINE.path)}`]: outline };
}

async function start(routes = {}) {
  const made = fakeCtx(routes);
  await open(made.ctx);
  return made;
}

async function withOutline(outline = OUTLINE, routes = {}) {
  const made = fakeCtx({ ...outlineRoute(outline), ...routes });
  await open(made.ctx);
  await actions.outline({ path: OUTLINE.path }, made.ctx);
  return made;
}

test("no outline shows the path field and the outline button, but no checkboxes", async () => {
  await start();
  const out = html(current());
  assert.ok(out.includes('<h2 id="addstudy-title">Add items from a file</h2>'));
  assert.ok(out.includes('name="path"'));
  assert.ok(out.includes("Show sections"));
  assert.ok(out.includes('data-act="close"'));
  assert.ok(!out.includes('type="checkbox"'));
  assert.ok(!out.includes('name="topic"'));
});

test("the outline checks the picked sections and disables the existing one", async () => {
  await withOutline();
  const out = html(current());
  assert.equal((out.match(/type="checkbox"/g) ?? []).length, 5);
  assert.equal((out.match(/type="checkbox"[^>]* checked/g) ?? []).length, 3);
  assert.ok(out.includes("3 of 5 selected"));
  assert.ok(out.includes("already added"));
  assert.match(out, /data-index="4"[^>]* disabled/);
  assert.doesNotMatch(out, /data-index="4"[^>]* checked/);
});

test("an exists section that was picked is never checked or counted", async () => {
  await withOutline();
  actions.toggleAll({ on: "1" });
  const out = html(current());
  assert.ok(out.includes("4 of 5 selected"));
  assert.doesNotMatch(out, /data-index="4"[^>]* checked/);
});

test("a section title is escaped", async () => {
  const outline = {
    ...OUTLINE,
    sections: OUTLINE.sections.map((section, index) =>
      index === 1 ? { ...section, title: "<i>x</i>" } : section,
    ),
  };
  await withOutline(outline);
  const out = html(current());
  assert.ok(out.includes("&lt;i&gt;x&lt;/i&gt;"));
  assert.ok(!out.includes("<i>x</i>"));
});

test("sections: [] gives one checked whole-file row", async () => {
  await withOutline({ ...OUTLINE, sections: [], whole_file_exists: false });
  const out = html(current());
  assert.ok(out.includes("the whole file"));
  assert.match(out, /data-index="0"[^>]* checked/);
  assert.ok(!out.includes("already added"));
  assert.ok(out.includes("1 of 1 selected"));
});

test("a whole file that is already added is disabled, unchecked and not counted", async () => {
  const made = await withOutline(
    { ...OUTLINE, sections: [], whole_file_exists: true },
    { "POST /api/items": { added: 1, skipped: 0 } },
  );
  let out = html(current());
  assert.match(out, /data-index="0"[^>]* disabled/);
  assert.doesNotMatch(out, /data-index="0"[^>]* checked/);
  assert.ok(out.includes("already added"));
  assert.ok(out.includes("0 of 1 selected"));
  assert.equal(
    input({ target: { type: "checkbox", checked: true, dataset: { index: "0" } } }),
    false,
  );

  actions.toggleAll({ on: "1" });
  out = html(current());
  assert.ok(out.includes("0 of 1 selected"));
  assert.doesNotMatch(out, /data-index="0"[^>]* checked/);

  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.ok(html(current()).includes("pick at least one section"));
  assert.equal(current().open, true);
});

test("the whole-file row can be unchecked and then adds nothing", async () => {
  const made = await withOutline(
    { ...OUTLINE, sections: [] },
    { "POST /api/items": { added: 1, skipped: 0 } },
  );
  assert.equal(
    input({ target: { type: "checkbox", checked: false, dataset: { index: "0" } } }),
    true,
  );
  const out = html(current());
  assert.doesNotMatch(out, /data-index="0"[^>]* checked/);
  assert.ok(out.includes("0 of 1 selected"));
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.ok(html(current()).includes("pick at least one section"));
  assert.equal(current().open, true);
});

test("none clears the whole-file row too", async () => {
  const made = await withOutline(
    { ...OUTLINE, sections: [] },
    { "POST /api/items": { added: 1, skipped: 0 } },
  );
  actions.toggleAll({ on: "0" });
  assert.ok(html(current()).includes("0 of 1 selected"));
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.ok(html(current()).includes("pick at least one section"));
});

test("a checkbox without an index is ignored", async () => {
  await withOutline();
  assert.equal(
    input({ target: { type: "checkbox", checked: true, dataset: { index: "" } } }),
    false,
  );
});

test("more selected than the daily cap says how many come up each day", async () => {
  const many = {
    ...OUTLINE,
    sections: Array.from({ length: 12 }, (_, index) => ({
      ...OUTLINE.sections[1],
      locator: `L${index + 1}`,
      title: `section ${index + 1}`,
      picked: true,
      exists: false,
    })),
  };
  await withOutline(many);
  assert.ok(html(current()).includes("12 items: 10 will come up each day"));
  current().selected = new Set([0, 1, 2, 3, 4]);
  assert.ok(!html(current()).includes("will come up each day"));
});

test("outline URL-encodes the path", async () => {
  const made = await start();
  made.calls.length = 0;
  await actions.outline({ path: "~/a.md" }, made.ctx);
  assert.deepEqual(made.calls, [["GET", "/api/outline?path=~%2Fa.md"]]);
});

test("an outline error shows in the alert and leaves no list", async () => {
  const made = fakeCtx({
    "GET /api/outline?path=~%2Fa.md": new Error("no such file: /x"),
  });
  await open(made.ctx);
  await actions.outline({ path: "~/a.md" }, made.ctx);
  const out = html(current());
  assert.ok(out.includes('role="alert"'));
  assert.ok(out.includes("no such file: /x"));
  assert.ok(!out.includes('type="checkbox"'));
});

test("add sends the checked locators in list order and closes", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/items": { added: 2, skipped: 0 },
  });
  input({ target: { type: "checkbox", checked: false, dataset: { index: "2" } } });
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), [
    [
      "POST",
      "/api/items",
      { topic_id: 1, path: OUTLINE.path, locators: ["TLB", "L20-25"] },
    ],
  ]);
  assert.deepEqual(made.toasts, ["added 2 items"]);
  assert.equal(current().open, false);
});

test("a skipped item shows in the toast", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/items": { added: 12, skipped: 3 },
  });
  current().selected = new Set([1, 3]);
  await actions.add({}, made.ctx);
  assert.deepEqual(made.toasts, ["added 12 items (3 already there)"]);
});

test("a new topic is created before the items are added", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/topics": { id: 9 },
    "POST /api/items": { added: 1, skipped: 0 },
  });
  input({ target: { name: "topic", value: "new" } });
  input({ target: { name: "name", value: "  tlb  " } });
  input({ target: { name: "course", value: "os" } });
  current().selected = new Set([1]);
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), [
    ["POST", "/api/topics", { name: "tlb", course: "os" }],
    ["POST", "/api/items", { topic_id: 9, path: OUTLINE.path, locators: ["TLB"] }],
  ]);
  assert.deepEqual(made.toasts, ["added 1 item"]);
});

test("a blank new-topic name makes no request", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/topics": { id: 9 },
  });
  input({ target: { name: "topic", value: "new" } });
  input({ target: { name: "name", value: "   " } });
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.ok(html(current()).includes("name the new topic"));
  assert.equal(current().open, true);
});

test("add with nothing checked makes no request", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/items": { added: 0, skipped: 0 },
  });
  actions.toggleAll({ on: "0" });
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.ok(html(current()).includes("pick at least one section"));
  assert.equal(current().open, true);
});

test("toggleAll selects all and none without touching an exists section", async () => {
  await withOutline();
  actions.toggleAll({ on: "0" });
  assert.ok(html(current()).includes("0 of 5 selected"));
  actions.toggleAll({ on: "1" });
  const out = html(current());
  assert.ok(out.includes("4 of 5 selected"));
  assert.doesNotMatch(out, /data-index="4"[^>]* checked/);
});

test("add with no outline loads the sections instead of posting items", async () => {
  const made = fakeCtx(outlineRoute(OUTLINE));
  await open(made.ctx);
  await actions.add({ path: OUTLINE.path }, made.ctx);
  assert.deepEqual(made.calls, [
    ["GET", "/api/study"],
    ["GET", `/api/outline?path=${encodeURIComponent(OUTLINE.path)}`],
  ]);
  assert.equal(current().open, true);
  assert.ok(html(current()).includes("3 of 5 selected"));
});

test("changing the path after an outline reloads it before adding", async () => {
  const other = { ...OUTLINE, path: "/home/u/other.md" };
  const made = await withOutline(OUTLINE, {
    [`GET /api/outline?path=${encodeURIComponent(other.path)}`]: other,
    "POST /api/items": { added: 2, skipped: 0 },
  });
  input({ target: { name: "path", value: other.path } });
  await actions.add({}, made.ctx);
  assert.deepEqual(made.calls.filter((call) => call[0] === "POST"), []);
  assert.equal(current().outline.path, other.path);
  assert.equal(current().open, true);
  await actions.add({}, made.ctx);
  assert.deepEqual(
    made.calls.filter((call) => call[0] === "POST"),
    [
      [
        "POST",
        "/api/items",
        { topic_id: 1, path: other.path, locators: ["TLB", "Example", "L20-25"] },
      ],
    ],
  );
});

test("an item add that fails keeps the dialog open and shows the error", async () => {
  const made = await withOutline(OUTLINE, {
    "POST /api/items": new Error("topic #1 is gone"),
  });
  await actions.add({}, made.ctx);
  assert.equal(current().open, true);
  const out = html(current());
  assert.ok(out.includes('role="alert"'));
  assert.ok(out.includes("topic #1 is gone"));
  assert.deepEqual(made.toasts, []);
});

test("a retry after the items fail reuses the topic it created", async () => {
  let attempts = 0;
  const made = await withOutline(OUTLINE, {
    "POST /api/topics": { id: 9 },
    "POST /api/items": () => {
      attempts += 1;
      if (attempts === 1) throw new Error("file changed");
      return { added: 1, skipped: 0 };
    },
  });
  input({ target: { name: "topic", value: "new" } });
  input({ target: { name: "name", value: "tlb" } });
  current().selected = new Set([1]);
  await actions.add({}, made.ctx);
  assert.equal(current().topic, "9");
  assert.equal(current().open, true);
  await actions.add({}, made.ctx);
  assert.deepEqual(
    made.calls.filter((call) => call[0] === "POST" && call[1] === "/api/topics"),
    [["POST", "/api/topics", { name: "tlb", course: "" }]],
  );
  assert.deepEqual(made.toasts, ["added 1 item"]);
  assert.equal(current().open, false);
});

test("a topic name is escaped in the options", async () => {
  await withOutline();
  current().topics = [{ id: 1, course: "", name: "<i>x</i>" }];
  current().topic = "1";
  const out = html(current());
  assert.ok(out.includes("other / &lt;i&gt;x&lt;/i&gt;"));
  assert.ok(!out.includes("<i>x</i>"));
});

test("typing keeps the model in step without asking for a redraw", async () => {
  await start();
  assert.equal(input({ target: { name: "path", value: "~/a.md" } }), false);
  assert.equal(current().path, "~/a.md");
  assert.equal(input({ target: { name: "name", value: "x" } }), false);
  assert.equal(input({ target: { name: "course", value: "os" } }), false);
  assert.equal(current().name, "x");
  assert.equal(current().course, "os");
});

test("a topic change and a checkbox change ask for a redraw", async () => {
  await withOutline();
  assert.equal(input({ target: { name: "topic", value: "new" } }), true);
  assert.equal(
    input({ target: { type: "checkbox", checked: false, dataset: { index: "1" } } }),
    true,
  );
  assert.equal(
    input({ target: { type: "checkbox", checked: true, dataset: { index: "4" } } }),
    false,
  );
});

test("open fetches the topics and then the outline", async () => {
  const made = fakeCtx();
  await open(made.ctx, "/home/u/a.md");
  assert.deepEqual(made.calls, [
    ["GET", "/api/study"],
    ["GET", `/api/outline?path=${encodeURIComponent("/home/u/a.md")}`],
  ]);
  assert.equal(current().open, true);
  assert.equal(current().path, "/home/u/a.md");
  assert.equal(current().topic, "1");
  assert.equal(current().new_per_day, 10);
  assert.ok(html(current()).includes("3 of 5 selected"));
});

test("open with no topics picks new topic and shows its fields", async () => {
  const made = fakeCtx({ "/api/study": { topics: [] } });
  await open(made.ctx, "/home/u/a.md");
  assert.equal(current().topic, "new");
  const out = html(current());
  assert.ok(out.includes("new topic…"));
  assert.ok(out.includes('name="name"'));
  assert.ok(out.includes('name="course"'));
});

test("close shuts the dialog", async () => {
  await start();
  assert.equal(current().open, true);
  actions.close();
  assert.equal(current().open, false);
});

test("a section another topic has can still be added to this one", async () => {
  const sections = OUTLINE.sections.map((s, i) => ({ ...s, exists: i === 1, topics: i === 1 ? [999] : [] }));
  await start(outlineRoute({ ...OUTLINE, sections }));
  await actions.outline({ path: OUTLINE.path }, fakeCtx(outlineRoute({ ...OUTLINE, sections })).ctx);
  assert.ok(!html(current()).includes("already added"));
  input({ target: { name: "topic", value: "999" } });
  assert.match(html(current()), /data-index="1"[^>]* disabled/);
});
