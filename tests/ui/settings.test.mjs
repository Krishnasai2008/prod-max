import test from "node:test";
import assert from "node:assert/strict";

import { actions, html, load } from "../../pm/ui/settings.js";

const SETTINGS = {
  values: {
    hours_per_day: "4",
    peak: "09-12",
    new_per_day: "10",
    nudge_hours: "08-22",
    watch: "~/Downloads",
    watch_ignore: "",
    course_codes: "",
    notes_url: "",
    notes_dir: "",
    llm_cmd: "",
  },
  db: "~/.local/share/prod-max/pm.db",
  files: 12,
};

function fakeCtx(overrides = {}) {
  const calls = [];
  const ctx = {
    state: {},
    async api(method, path, body) {
      calls.push(body === undefined ? [method, path] : [method, path, body]);
      return overrides.reply ?? SETTINGS;
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

function withSettings(settings) {
  return html({}, { settings });
}

test("load fetches the settings", async () => {
  const { ctx, calls } = fakeCtx();
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/settings"]]);
  assert.equal(extra.settings, SETTINGS);
});

test("html says loading until the settings arrive", () => {
  assert.equal(html({}, {}), '<p class="muted">loading…</p>');
  assert.equal(html({}), '<p class="muted">loading…</p>');
});

test("every setting gets a form with its label, hidden key and named value", () => {
  const out = withSettings(SETTINGS);
  assert.equal((out.match(/<form /g) ?? []).length, Object.keys(SETTINGS.values).length);
  assert.ok(out.includes('<label for="setting-hours_per_day">Hours you can work a day</label>'));
  assert.ok(out.includes('<input id="setting-hours_per_day" name="value" value="4">'));
  assert.ok(out.includes('<input type="hidden" name="key" value="hours_per_day">'));
  assert.ok(out.includes("used by the plan and the risk simulation; 0.1–16"));
  assert.ok(out.includes("database: ~/.local/share/prod-max/pm.db"));
  assert.ok(out.includes("12 files indexed"));
});

test("a value with markup is escaped inside the value attribute", () => {
  const settings = {
    ...SETTINGS,
    values: { ...SETTINGS.values, notes_url: '"><script>' },
  };
  const out = withSettings(settings);
  assert.ok(out.includes('value="&quot;&gt;&lt;script&gt;"'));
  assert.ok(!out.includes('"><script>'));
});

test("an unknown key is drawn with the key as its label and no hint", () => {
  const settings = { ...SETTINGS, values: { ...SETTINGS.values, x_new: "1" } };
  const out = withSettings(settings);
  assert.ok(out.includes('<label for="setting-x_new">x_new</label>'));
  assert.ok(out.includes('<input id="setting-x_new" name="value" value="1">'));
  const form = out.slice(out.indexOf('name="key" value="x_new"'));
  const end = form.indexOf("</form>");
  assert.ok(end >= 0);
  assert.ok(!form.slice(0, end).includes('<p class="muted">'));
});

test("save posts the key and value and says saved", async () => {
  const { ctx, calls } = fakeCtx();
  const toasts = [];
  ctx.toast = (message) => toasts.push(message);
  await actions.save({ key: "peak", value: "10-13" }, ctx);
  assert.deepEqual(calls, [["POST", "/api/settings", { key: "peak", value: "10-13" }]]);
  assert.deepEqual(toasts, ["saved"]);
});

test("save lets an api error through", async () => {
  const ctx = {
    api: async () => {
      throw new Error("unknown setting 'nope'");
    },
    toast: () => {
      throw new Error("should not toast an error");
    },
  };
  await assert.rejects(actions.save({ key: "nope", value: "1" }, ctx), /unknown setting/);
});

test("the notes folder setting has its own label and hint", () => {
  const out = withSettings(SETTINGS);
  assert.ok(out.includes('<label for="setting-notes_dir">Notes folder</label>'));
  assert.ok(out.includes('<input type="hidden" name="key" value="notes_dir">'));
  assert.ok(
    out.includes(
      "the docs folder of your notes site, like ~/my-notes/docs; items from it link to the site",
    ),
  );
});

test("lh_dir is drawn with its label", () => {
  const out = withSettings({ ...SETTINGS, values: { ...SETTINGS.values, lh_dir: "" } });
  assert.ok(out.includes('<label for="setting-lh_dir">LearnHarness data folder</label>'));
  assert.ok(out.includes("pm only reads it"));
});

test("llm_cmd is drawn as the language model command", () => {
  const out = withSettings(SETTINGS);
  assert.ok(out.includes('<label for="setting-llm_cmd">Language model command</label>'));
  assert.ok(out.includes("used for spot-the-error"));
});

test("agent_daily_calls is drawn with its label", () => {
  const out = withSettings({ ...SETTINGS, values: { ...SETTINGS.values, agent_daily_calls: "0" } });
  assert.ok(out.includes('<label for="setting-agent_daily_calls">Model calls a day</label>'));
  assert.ok(out.includes("0 turns them off"));
});
