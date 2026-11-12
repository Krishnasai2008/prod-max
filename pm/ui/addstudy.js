import { esc } from "./lib.js";

const model = {
  open: false,
  path: "",
  topics: [],
  outline: null,
  error: null,
  new_per_day: 10,
  topic: "new",
  name: "",
  course: "",
  selected: new Set(),
};

let fetchedPath = "";

export function current() {
  return model;
}

function message(error) {
  return error instanceof Error ? error.message : String(error ?? "");
}

function sections(model) {
  return model.outline?.sections ?? [];
}

// Already in the topic picked in the dialog: the same section may sit in two topics.
function inTopic(topics, any) {
  return Array.isArray(topics) ? topics.includes(Number(model.topic)) : any === true;
}

function taken(section) {
  return inTopic(section.topics, section.exists);
}

function wholeFileExists(model) {
  return !sections(model).length && inTopic(model.outline?.whole_file_topics, model.outline?.whole_file_exists);
}

function chosen(model) {
  const all = sections(model);
  if (!all.length) return model.selected.has(0) && !wholeFileExists(model) ? [0] : [];
  return all
    .map((section, index) => (!taken(section) && model.selected.has(index) ? index : -1))
    .filter((index) => index >= 0);
}

function topicOptions(model) {
  const options = (model.topics ?? []).map((topic) => {
    const id = String(topic.id);
    const name = topic.course ? `${topic.course} / ${topic.name}` : `other / ${topic.name}`;
    return (
      `<option value="${esc(id)}"${id === String(model.topic) ? " selected" : ""}>` +
      `${esc(name)}</option>`
    );
  });
  const isNew = String(model.topic) === "new";
  options.push(`<option value="new"${isNew ? " selected" : ""}>new topic…</option>`);
  return options.join("");
}

function sectionRow(section, index, checked) {
  const level = Math.max(1, Math.min(6, Number(section.level) || 1));
  const id = `addstudy-s-${index}`;
  const lines = section.pdf
    ? ""
    : `<span class="muted">${Number(section.lines) || 0} ${Number(section.lines) === 1 ? "line" : "lines"}</span>`;
  const added = taken(section) ? ` <span class="muted">already added</span>` : "";
  const disabled = taken(section) ? " disabled" : "";
  const marked = !taken(section) && checked ? " checked" : "";
  return (
    `<label class="section section-level-${level}" for="${id}">` +
    `<input id="${id}" type="checkbox" data-index="${index}"${marked}${disabled}>` +
    `<span class="section-title">${esc(section.title)}</span>${lines}${added}` +
    `</label>`
  );
}

function wholeFileRow(checked, exists) {
  const added = exists ? ` <span class="muted">already added</span>` : "";
  const disabled = exists ? " disabled" : "";
  const marked = !exists && checked ? " checked" : "";
  return (
    `<label class="section section-level-1" for="addstudy-s-0">` +
    `<input id="addstudy-s-0" type="checkbox" data-index="0"${marked}${disabled}>` +
    `<span class="section-title">the whole file</span>${added}` +
    `</label>`
  );
}

function outlineBody(model) {
  const all = sections(model);
  const picked = chosen(model);
  const marked = new Set(picked);
  const cap = Number(model.new_per_day) || 10;
  const rows = all.length
    ? all.map((section, index) => sectionRow(section, index, marked.has(index))).join("")
    : wholeFileRow(marked.has(0), wholeFileExists(model));
  const newTopic =
    String(model.topic) === "new"
      ? `<div class="field">` +
        `<label for="addstudy-name">name</label>` +
        `<input id="addstudy-name" name="name" type="text" autocomplete="off" value="${esc(model.name)}">` +
        `</div>` +
        `<div class="field">` +
        `<label for="addstudy-course">course</label>` +
        `<input id="addstudy-course" name="course" type="text" autocomplete="off" value="${esc(model.course)}">` +
        `</div>`
      : "";
  const warning =
    picked.length > cap
      ? `<p class="muted">${picked.length} items: ${cap} will come up each day</p>`
      : "";
  return (
    `<div class="field">` +
    `<label for="addstudy-topic">topic</label>` +
    `<select id="addstudy-topic" name="topic">${topicOptions(model)}</select>` +
    `</div>` +
    newTopic +
    `<div class="spread">` +
    `<span>${picked.length} of ${all.length || 1} selected</span>` +
    `<span class="row">` +
    `<button type="button" class="btn btn-small" data-act="toggleAll" data-on="1">all</button>` +
    `<button type="button" class="btn btn-small" data-act="toggleAll" data-on="0">none</button>` +
    `</span>` +
    `</div>` +
    `<div class="sections">${rows}</div>` +
    warning
  );
}

export function html(model) {
  const error = model.error
    ? `<p class="error" role="alert">${esc(model.error)}</p>`
    : "";
  return (
    `<h2 id="addstudy-title">Add items from a file</h2>` +
    `<form data-act="add">` +
    `<div class="field">` +
    `<label for="addstudy-path">path</label>` +
    `<input id="addstudy-path" name="path" type="text" autocomplete="off"` +
    ` value="${esc(model.path)}" placeholder="~/notes/os.md or ~/slides/week3.pdf">` +
    `</div>` +
    `<div class="row">` +
    `<button type="button" class="btn" data-act="outline">Show sections</button>` +
    `</div>` +
    error +
    (model.outline ? outlineBody(model) : "") +
    `<div class="row dialog-actions">` +
    `<button type="button" class="btn" data-act="close">Cancel</button>` +
    `<button type="submit" class="btn btn-primary">Add items</button>` +
    `</div>` +
    `</form>`
  );
}

export function input(event) {
  const target = event?.target;
  if (!target) return false;
  if (target.type === "checkbox") {
    const all = sections(model);
    const raw = target.dataset?.index;
    if (raw === undefined || raw === "") return false;
    const index = Number(raw);
    if (!Number.isInteger(index) || index < 0) return false;
    if (!all.length && wholeFileExists(model)) return false;
    if (all.length && (index >= all.length || taken(all[index]))) return false;
    if (target.checked) model.selected.add(index);
    else model.selected.delete(index);
    return true;
  }
  const name = target.name;
  if (name === "path") {
    model.path = String(target.value ?? "");
    return false;
  }
  if (name === "topic") {
    model.topic = String(target.value ?? "new");
    return true;
  }
  if (name === "name") {
    model.name = String(target.value ?? "");
    return false;
  }
  if (name === "course") {
    model.course = String(target.value ?? "");
    return false;
  }
  return false;
}

async function outline(data, ctx) {
  model.path = String(data?.path ?? model.path ?? "");
  try {
    const result = await ctx.api("GET", `/api/outline?path=${encodeURIComponent(model.path)}`);
    model.outline = result ?? null;
    fetchedPath = model.path;
    const all = sections(model);
    model.selected = new Set(
      all.length
        ? all
            .map((section, index) => (section.picked && !taken(section) ? index : -1))
            .filter((index) => index >= 0)
        : wholeFileExists(model)
          ? []
          : [0],
    );
    model.error = null;
  } catch (error) {
    model.outline = null;
    fetchedPath = "";
    model.selected = new Set();
    model.error = message(error);
  }
}

export async function open(ctx, path = "") {
  model.open = true;
  model.path = String(path ?? "");
  model.topics = [];
  model.outline = null;
  fetchedPath = "";
  model.error = null;
  model.new_per_day = Number(ctx?.state?.new_per_day ?? 10) || 10;
  model.topic = "new";
  model.name = "";
  model.course = "";
  model.selected = new Set();
  try {
    const study = await ctx.api("GET", "/api/study");
    model.topics = study?.topics ?? [];
    if (model.topics.length) model.topic = String(model.topics[0].id);
  } catch (error) {
    model.error = message(error);
  }
  if (model.path) await outline({ path: model.path }, ctx);
}

export const actions = {
  async outline(data, ctx) {
    await outline(data, ctx);
  },

  toggleAll(data) {
    const all = sections(model);
    const on = String(data?.on) === "1";
    if (!all.length) {
      model.selected = on && !wholeFileExists(model) ? new Set([0]) : new Set();
      return;
    }
    model.selected = new Set(
      on
        ? all.map((section, index) => (!taken(section) ? index : -1)).filter((index) => index >= 0)
        : [],
    );
  },

  async add(data, ctx) {
    if (data?.path !== undefined) model.path = String(data.path);
    if (data?.topic !== undefined) model.topic = String(data.topic);
    if (data?.name !== undefined) model.name = String(data.name);
    if (data?.course !== undefined) model.course = String(data.course);
    if (!model.outline || fetchedPath !== model.path) {
      await outline(data, ctx);
      return;
    }
    const all = sections(model);
    const picked = chosen(model);
    if (!picked.length) {
      model.error = "pick at least one section";
      return;
    }
    const locators = all.length ? picked.map((index) => all[index].locator) : [null];
    try {
      let topicId = model.topic;
      if (String(topicId) === "new") {
        const name = model.name.trim();
        if (!name) {
          model.error = "name the new topic";
          return;
        }
        const course = model.course;
        const created = await ctx.api("POST", "/api/topics", { name, course });
        const createdId = created?.id;
        if (createdId == null) throw new Error("no topic id");
        model.topic = String(createdId);
        model.topics = [...(model.topics ?? []), { id: createdId, course, name }];
        topicId = createdId;
      }
      const result =
        (await ctx.api("POST", "/api/items", {
          topic_id: Number(topicId),
          path: model.outline.path,
          locators,
        })) ?? {};
      const added = Number(result.added ?? 0);
      const skipped = Number(result.skipped ?? 0);
      model.error = null;
      model.open = false;
      const base = `added ${added} item${added === 1 ? "" : "s"}`;
      ctx.toast?.(skipped > 0 ? `${base} (${skipped} already there)` : base);
    } catch (error) {
      model.error = message(error);
    }
  },

  close() {
    model.open = false;
  },
};
