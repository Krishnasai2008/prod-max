import { esc } from "./lib.js";

const FIELDS = {
  hours_per_day: ["Hours you can work a day", "used by the plan and the risk simulation; 0.1–16"],
  peak: ["Peak hours", "when deep work goes first, like 09-12"],
  new_per_day: ["New study items a day", "how many never-reviewed items enter the queue each day"],
  nudge_hours: ["Nudge hours", "start nudges are only sent between these hours, like 08-22"],
  watch: ["Watched folders", "folders to index, separated by :"],
  watch_ignore: ["Ignored folders", "folders under the watched ones to skip, separated by :"],
  course_codes: ["Course codes", "name=CODE pairs separated by ; like os=CS F372"],
  notes_url: ["Notes site address", "https://…; where pm stats --push sends the summary"],
  agent_daily_calls: ["Model calls a day", "how many times the background jobs may call the language model each day; 0 turns them off"],
  lh_dir: ["LearnHarness data folder", "leave empty to use ~/.config/LearnHarness/data; pm only reads it"],
  llm_cmd: ["Language model command", "a command that reads a prompt on stdin and prints the reply; used for spot-the-error"],
  notes_dir: ["Notes folder", "the docs folder of your notes site, like ~/my-notes/docs; items from it link to the site"],
};

export async function load(ctx) {
  return { settings: await ctx.api("GET", "/api/settings") };
}

function form(key, value) {
  const [label, hint] = Object.hasOwn(FIELDS, key) ? FIELDS[key] : [key, ""];
  const id = `setting-${key}`;
  return (
    `<form data-act="save" class="card">` +
    `<input type="hidden" name="key" value="${esc(key)}">` +
    `<div class="field">` +
    `<label for="${esc(id)}">${esc(label)}</label>` +
    `<input id="${esc(id)}" name="value" value="${esc(value)}">` +
    `</div>` +
    (hint ? `<p class="muted">${esc(hint)}</p>` : "") +
    `<button type="submit" class="btn btn-small">Save</button>` +
    `</form>`
  );
}

export function html(state, extra) {
  const data = extra?.settings;
  if (!data) return '<p class="muted">loading…</p>';
  const values = data.values ?? {};
  return (
    `<div class="settings">` +
    Object.entries(values)
      .map(([key, value]) => form(key, value))
      .join("") +
    `<p class="muted">database: ${esc(data.db)}</p>` +
    `<p class="muted">${esc(data.files ?? 0)} files indexed</p>` +
    `</div>`
  );
}

export const actions = {
  async save({ key, value }, ctx) {
    await ctx.api("POST", "/api/settings", { key, value });
    ctx.toast("saved");
  },
};
