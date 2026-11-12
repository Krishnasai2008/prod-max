import { esc, fmtMin, pct, relDay } from "./lib.js";

let editing = null;

export async function load(ctx) {
  const json = await ctx.api("GET", "/api/finished");
  return { finished: json.tasks };
}

function datalists(state) {
  const options = (values) =>
    (values ?? []).map((value) => `<option value="${esc(value)}"></option>`).join("");
  return (
    `<datalist id="courses">${options(state?.courses)}</datalist>` +
    `<datalist id="kinds">${options(state?.kinds)}</datalist>`
  );
}

function energyFields(current) {
  return (
    `<div class="field row">` +
    `<label class="row"><input type="radio" name="energy" value="deep"${current === "deep" ? " checked" : ""}> deep</label>` +
    `<label class="row"><input type="radio" name="energy" value="shallow"${current === "shallow" ? " checked" : ""}> shallow</label>` +
    `</div>`
  );
}

function addForm() {
  return `
    <form data-act="add" class="card">
      <h2>Add a task</h2>
      <div class="field">
        <label for="add-title">title</label>
        <input id="add-title" name="title" required maxlength="200">
      </div>
      <div class="field">
        <label for="add-est">estimate</label>
        <input id="add-est" name="est" required placeholder="90m, 2h, 1h30m">
      </div>
      <div class="field">
        <label for="add-due">due</label>
        <input id="add-due" name="due" placeholder="2026-11-20 or +3">
      </div>
      <div class="field">
        <label for="add-course">course</label>
        <input id="add-course" name="course" list="courses" autocomplete="off">
      </div>
      <div class="field">
        <label for="add-kind">kind</label>
        <input id="add-kind" name="kind" list="kinds" autocomplete="off">
      </div>
      ${energyFields("deep")}
      <div class="field">
        <label for="add-first">first step</label>
        <input id="add-first" name="first" placeholder="a tiny first step">
      </div>
      <button class="btn btn-primary" type="submit">Add</button>
    </form>`;
}

function taskRow(task, todayIso) {
  const id = esc(task.id);
  const running = task.running === true;
  const start = running
    ? `<button type="button" class="btn btn-small" data-act="start" data-id="${id}" disabled>running</button>`
    : `<button type="button" class="btn btn-small" data-act="start" data-id="${id}">Start</button>`;
  const course = task.course ? `<span class="tag">${esc(task.course)}</span>` : "—";
  const kind = task.kind ? `<span class="tag">${esc(task.kind)}</span>` : "—";
  const rel = task.due ? relDay(task.due, todayIso) : "";
  const due = task.due
    ? `${esc(task.due)}${rel ? ` <span class="muted">(${esc(rel)})</span>` : ""}`
    : "—";
  const late =
    task.p_late === null || task.p_late === undefined ? "—" : `late ${pct(task.p_late)}`;
  const startBy = task.start_by
    ? `${esc(task.start_by)}${task.behind ? ' <span class="tag">BEHIND</span>' : ""}`
    : "—";
  return `
        <tr${running ? ' class="running"' : ""}>
          <td>${esc(task.title)}</td>
          <td>${course}</td>
          <td>${kind}</td>
          <td>${esc(task.energy)}</td>
          <td>${esc(fmtMin(task.logged_min))} / ${esc(fmtMin(task.est_min))}</td>
          <td>${due}</td>
          <td>${late}</td>
          <td>${startBy}</td>
          <td>
            <div class="row">
              ${start}
              <form data-act="log" data-id="${id}" class="row">
                <label>log <input name="duration" required placeholder="30m" autocomplete="off"></label>
                <button type="submit" class="btn btn-small">Log</button>
              </form>
              <button type="button" class="btn btn-small" data-act="done" data-id="${id}">Done</button>
              <button type="button" class="btn btn-small" data-act="edit" data-id="${id}">Edit</button>
              <button type="button" class="btn btn-small" data-act="drop" data-id="${id}">Drop</button>
            </div>
          </td>
        </tr>`;
}

function linkChip(task, link) {
  const close = `<button type="button" class="link-x" data-act="dropLink" data-id="${esc(task.id)}" data-link="${esc(link.id)}" aria-label="remove link ${esc(link.short)}">×</button>`;
  const target = String(link.target ?? "");
  let body;
  if (link.kind === "url" && /^https?:\/\//i.test(target)) {
    body = `<a href="${esc(target)}" target="_blank" rel="noopener noreferrer">${esc(link.short)}</a>`;
  } else if (link.kind === "file" || link.kind === "folder") {
    body = `<button type="button" class="link-open" data-act="openLink" data-id="${esc(task.id)}" data-link="${esc(link.id)}">${esc(link.short)}</button>`;
  } else {
    body = `<s>${esc(link.short ?? target)}</s>`;
  }
  return `<span class="link-chip">${body}${close}</span>`;
}

function linksRow(task) {
  const chips = (task.links ?? []).map((link) => linkChip(task, link)).join("");
  return `
        <tr class="links-row">
          <td colspan="9">
            <div class="row">
              ${chips}
              <form data-act="addLink" data-id="${esc(task.id)}" class="row">
                <input name="target" required placeholder="a file path or https://…" autocomplete="off" aria-label="link a file or address">
                <button type="submit" class="btn btn-small">Add link</button>
              </form>
            </div>
          </td>
        </tr>`;
}

function editRow(task) {
  const id = esc(task.id);
  const locked = Number(task.logged_min) > 0;
  const est = `<input id="edit-est-${id}" name="est" value="${esc(fmtMin(task.est_min))}"${locked ? " disabled" : ""}>`;
  return `
        <tr class="editing">
          <td colspan="9">
            <form data-act="save" data-id="${id}" class="card">
              <h3>Edit #${id}</h3>
              <div class="field">
                <label for="edit-title-${id}">title</label>
                <input id="edit-title-${id}" name="title" required maxlength="200" value="${esc(task.title)}">
              </div>
              <div class="field">
                <label for="edit-est-${id}">estimate</label>
                ${est}
                ${locked ? '<span class="muted">locked: time is logged</span>' : ""}
              </div>
              <div class="field">
                <label for="edit-due-${id}">due</label>
                <input id="edit-due-${id}" name="due" value="${esc(task.due)}" placeholder="2026-11-20 or +3">
              </div>
              <div class="field">
                <label for="edit-course-${id}">course</label>
                <input id="edit-course-${id}" name="course" list="courses" value="${esc(task.course)}" autocomplete="off">
              </div>
              <div class="field">
                <label for="edit-kind-${id}">kind</label>
                <input id="edit-kind-${id}" name="kind" list="kinds" value="${esc(task.kind)}" autocomplete="off">
              </div>
              ${energyFields(task.energy)}
              <div class="field">
                <label for="edit-first-${id}">first step</label>
                <input id="edit-first-${id}" name="first" value="${esc(task.first_step)}" placeholder="a tiny first step">
              </div>
              <div class="row">
                <button type="submit" class="btn btn-primary">Save</button>
                <button type="button" class="btn" data-act="cancel">Cancel</button>
              </div>
            </form>
          </td>
        </tr>`;
}

function openTasks(state, todayIso) {
  const tasks = state?.tasks ?? [];
  const rows = tasks
    .map((task) => (String(task.id) === editing ? editRow(task) : taskRow(task, todayIso) + linksRow(task)))
    .join("");
  const body = tasks.length
    ? `<table>
        <thead>
          <tr><th>task</th><th>course</th><th>kind</th><th>energy</th><th>logged / estimate</th><th>due</th><th>late</th><th>start by</th><th></th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>`
    : '<p class="muted">no open tasks</p>';
  return `<section class="card"><h2>Open tasks</h2>${body}</section>`;
}

function finishedSection(finished) {
  const items = finished
    .map((task) => {
      const ratio =
        task.ratio === null || task.ratio === undefined
          ? "—"
          : `×${Number(task.ratio).toFixed(2)}`;
      const late =
        task.late === null || task.late === undefined
          ? ""
          : task.late
            ? '<span class="tag">late</span>'
            : '<span class="tag">on time</span>';
      return `<li class="spread"><span>${esc(task.title)}</span><span class="muted">${esc(fmtMin(task.logged_min))} / ${esc(fmtMin(task.est_min))}</span><span>${esc(ratio)}</span>${late}</li>`;
    })
    .join("");
  const body = finished.length
    ? `<ul>${items}</ul>`
    : '<p class="muted">nothing finished yet</p>';
  return `<section class="card"><h2>Recently finished</h2>${body}</section>`;
}

export function html(state, extra = {}) {
  const finished = extra.finished ?? [];
  const todayIso = String(state?.now ?? "").slice(0, 10);
  return (
    datalists(state) +
    addForm() +
    openTasks(state, todayIso) +
    finishedSection(finished)
  );
}

export const actions = {
  async add(data, ctx) {
    const body = {};
    for (const field of ["title", "est", "due", "course", "kind", "energy", "first"]) {
      const value = data[field] ?? "";
      if (value !== "") body[field] = value;
    }
    await ctx.api("POST", "/api/tasks", body);
  },

  edit(data) {
    if (data?.id !== undefined) editing = String(data.id);
  },

  cancel() {
    editing = null;
  },

  async save(data, ctx) {
    const id = String(data.id);
    const task = (ctx.state?.tasks ?? []).find((item) => String(item.id) === id);
    if (!task) throw new Error(`no task #${id}`);
    const stored = {
      title: task.title,
      est: fmtMin(task.est_min),
      due: task.due ?? "",
      course: task.course ?? "",
      kind: task.kind ?? "",
      energy: task.energy,
      first: task.first_step ?? "",
    };
    const body = {};
    for (const [field, old] of Object.entries(stored)) {
      if (!(field in data)) continue;
      const value = String(data[field] ?? "");
      if (value !== String(old ?? "")) body[field] = value;
    }
    if (Object.keys(body).length === 0) {
      editing = null;
      return;
    }
    await ctx.api("POST", `/api/tasks/${id}/edit`, body);
    editing = null;
  },

  async start(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/start`);
  },

  async addLink(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/links`, { target: data.target });
  },

  async dropLink(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/links/${data.link}/drop`, undefined);
  },

  async openLink(data, ctx) {
    const answer = await ctx.api("POST", `/api/tasks/${data.id}/links/${data.link}/open`, undefined);
    if (answer?.skipped?.length) ctx.toast(answer.skipped[0]);
  },

  async log(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/log`, { duration: data.duration });
    ctx.toast?.(`logged ${data.duration} on #${data.id}`);
  },

  async done(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/done`);
    ctx.toast?.(`#${data.id} done (undo: pm reopen ${data.id})`);
  },

  async drop(data, ctx) {
    const id = String(data.id);
    const task = (ctx.state?.tasks ?? []).find((item) => String(item.id) === id);
    const title = task ? task.title : "";
    if (!ctx.confirm(`Drop #${id} ${title}? Its logged time is kept.`)) return;
    await ctx.api("POST", `/api/tasks/${id}/drop`);
  },
};
