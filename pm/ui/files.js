import { esc } from "./lib.js";

let filters = { q: "", course: "" };

function apiPath() {
  const parts = [];
  if (filters.q.trim()) parts.push(`q=${encodeURIComponent(filters.q)}`);
  if (filters.course) parts.push(`course=${encodeURIComponent(filters.course)}`);
  return parts.length ? `/api/files?${parts.join("&")}` : "/api/files";
}

export async function load(ctx) {
  const files = await ctx.api("GET", apiPath());
  return { files };
}

export function snippetHtml(snippet) {
  return esc(snippet)
    .replace(/\x02([^\x02\x03]*)\x03/g, "<mark>$1</mark>")
    .replace(/[\x02\x03]/g, "");
}

function searching(data) {
  if (data?.q !== undefined && data?.q !== null) return String(data.q).trim() !== "";
  return filters.q.trim() !== "";
}

function heading(data, hits) {
  if (!searching(data)) return "recent files";
  return `${hits.length} ${hits.length === 1 ? "match" : "matches"}`;
}

function buttons(hit) {
  const id = esc(hit.id);
  return (
    (hit.openable
      ? `<button type="button" class="btn btn-small" data-act="open" data-id="${id}">Open</button>`
      : "") +
    `<button type="button" class="btn btn-small" data-act="reveal" data-id="${id}">Show in folder</button>` +
    `<button type="button" class="btn btn-small" data-act="study" data-id="${id}" data-path="${esc(hit.path)}">Study this</button>`
  );
}

function hitHtml(hit) {
  return (
    `<article class="file">` +
    `<div class="spread">` +
    `<span class="file-name"><strong>${esc(hit.name)}</strong></span>` +
    (hit.course ? `<span class="tag">${esc(hit.course)}</span>` : "") +
    `</div>` +
    `<p class="file-path muted">${esc(hit.short)}</p>` +
    (hit.snippet ? `<p class="file-snippet">${snippetHtml(hit.snippet)}</p>` : "") +
    `<div class="row">${buttons(hit)}</div>` +
    `</article>`
  );
}

export function resultsHtml(data) {
  const hits = data?.hits ?? [];
  if (!hits.length) {
    const total = data?.total;
    if (total !== undefined && total !== null && Number(total) === 0) {
      return '<p class="muted">nothing indexed yet: run pm watch --install, or pm watch --once</p>';
    }
    return '<p class="muted">no matches</p>';
  }
  return (
    `<section class="card"><h2>${esc(heading(data, hits))}</h2>` +
    hits.map(hitHtml).join("") +
    `</section>`
  );
}

function courseOptions(courses) {
  return (
    `<option value="">all courses</option>` +
    (courses ?? [])
      .map((course) => {
        const value = String(course ?? "");
        const selected = value === filters.course ? " selected" : "";
        return `<option value="${esc(value)}"${selected}>${esc(value)}</option>`;
      })
      .join("")
  );
}

export function html(_state, extra = {}) {
  const files = extra?.files;
  return (
    `<section class="card files-controls">` +
    `<input type="search" name="q" data-act="search" aria-label="search files" placeholder="search files" value="${esc(filters.q)}">` +
    `<select name="course" data-act="course" aria-label="course filter">${courseOptions(files?.courses)}</select>` +
    `</section>` +
    `<div id="files-out">` +
    (files ? resultsHtml(files) : '<p class="muted">loading…</p>') +
    `</div>`
  );
}

let latest = 0;

async function fetchInto(ctx) {
  const mine = ++latest;
  const files = await ctx.api("GET", apiPath());
  if (mine === latest) ctx.patch("files-out", resultsHtml(files)); // an older, slower answer never wins
}

// keep the filters in step at once, so a refresh or a click inside the 250 ms debounce loads what is typed
export function input(event) {
  const field = event?.target;
  if (field?.name === "q") filters.q = String(field.value ?? "");
  else if (field?.name === "course") filters.course = String(field.value ?? "");
}

export const actions = {
  async search(data, ctx) {
    filters.q = String(data?.value ?? "");
    await fetchInto(ctx);
  },

  async course(data, ctx) {
    filters.course = String(data?.value ?? "");
    await fetchInto(ctx);
  },

  async open(data, ctx) {
    await ctx.api("POST", `/api/files/${encodeURIComponent(String(data?.id ?? ""))}/open`);
  },

  async reveal(data, ctx) {
    await ctx.api("POST", `/api/files/${encodeURIComponent(String(data?.id ?? ""))}/reveal`);
  },

  async study(data, ctx) {
    await ctx.openAddStudy(String(data?.path ?? ""));
  },
};
