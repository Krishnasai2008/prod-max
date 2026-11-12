import { esc, fmtMin } from "./lib.js";

const BUILTIN_TAGS = [
  "off-by-one",
  "overflow",
  "uninit",
  "null-check",
  "bounds",
  "segfault",
  "abort",
  "timeout",
];

const DIFF_META = ["diff ", "index ", "--- ", "+++ "];
const DIFF_LINES = 2000;

const view = { tag: null, openId: null, list: null, detail: null };

function absorb(extra) {
  if (!extra || typeof extra !== "object") {
    view.list = null;
    return;
  }
  const has = (key) => Object.prototype.hasOwnProperty.call(extra, key);
  view.list = has("bugs") ? extra.bugs ?? null : null;
  if (has("bug")) view.detail = extra.bug ?? null;
  else if (view.openId === null) view.detail = null;
}

export async function load(ctx) {
  const path = view.tag
    ? `/api/bugs?tag=${encodeURIComponent(view.tag)}`
    : "/api/bugs";
  const list = await ctx.api("GET", path);
  view.list = list;
  let detail = null;
  if (view.openId !== null) {
    try {
      detail = await ctx.api("GET", `/api/bugs/${encodeURIComponent(view.openId)}`);
    } catch (error) {
      view.openId = null; // a bug that is gone must not break every later load
      view.detail = null;
      throw error;
    }
    view.detail = detail;
  } else {
    view.detail = null;
  }
  return { bugs: list, bug: detail };
}

function failsText(n) {
  const count = Number(n) || 0;
  return count === 1 ? "1 fail" : `${count} fails`;
}

function day(iso) {
  return String(iso ?? "").slice(0, 10);
}

function minute(iso) {
  return String(iso ?? "").replace("T", " ").slice(0, 16);
}

function clock(iso) {
  return String(iso ?? "").slice(11, 16);
}

function seconds(dur) {
  const value = Number(dur);
  return Number.isFinite(value) ? value.toFixed(1) : "0.0";
}

export function diffHtml(text) {
  const raw = String(text ?? "").replace(/\n$/, "");
  if (raw === "") return '<pre class="diff"></pre>';
  const lines = raw.split("\n");
  const shown = lines.slice(0, DIFF_LINES);
  const parts = shown.map((line) => {
    const kind = diffKind(line);
    const cls = kind ? ` class="${kind}"` : "";
    return `<span${cls}>${esc(line)}</span>`;
  });
  if (lines.length > DIFF_LINES) {
    parts.push(`<span class="more">… (${lines.length - DIFF_LINES} more lines)</span>`);
  }
  return `<pre class="diff">${parts.join("\n")}</pre>`;
}

function diffKind(line) {
  if (DIFF_META.some((prefix) => line.startsWith(prefix))) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "";
}

function tiles(summary) {
  const tile = (label, value) =>
    `<div class="bug-tile"><b class="bug-tile-value">${esc(value)}</b>` +
    `<span class="bug-tile-label">${esc(label)}</span></div>`;
  return (
    `<section class="bug-tiles" aria-label="bug totals">` +
    tile("fixed", summary.fixed ?? 0) +
    tile("open", summary.open ?? 0) +
    tile("abandoned", summary.abandoned ?? 0) +
    tile("time lost", fmtMin(summary.lost_min ?? 0)) +
    `</section>`
  );
}

function burstsLine(summary) {
  const bursts = summary.bursts ?? [];
  if (!bursts.length) return "";
  const parts = bursts
    .map(([tag, n]) => `${esc(tag)} ×${esc(n)}`)
    .join(" · ");
  return `<p class="bug-burst">burst: ${parts} in 7 days</p>`;
}

function tagsSection(summary) {
  const tags = summary.tags ?? [];
  const untagged = Number(summary.untagged ?? 0);
  if (!tags.length && !untagged && view.tag === null) return "";
  const counts = tags.map(([, n]) => Number(n) || 0);
  const largest = Math.max(1, ...counts);
  const rows = tags
    .map(([tag, n]) => {
      const count = Number(n) || 0;
      const active = view.tag === tag;
      const width = Math.round((count / largest) * 100);
      return (
        `<button type="button" data-act="filter" data-tag="${esc(tag)}"` +
        ` aria-pressed="${active ? "true" : "false"}" class="bug-tag-row">` +
        `<span class="bug-tag-name">${esc(tag)}</span>` +
        `<span class="bar bug-tag-bar" aria-hidden="true"><span style="width:${width}%"></span></span>` +
        `<span class="bug-tag-count">${esc(count)}</span>` +
        `</button>`
      );
    })
    .join("");
  return (
    `<section class="card bug-tags"><h2>Tags</h2>` +
    rows +
    `<div class="row bug-tag-actions">` +
    `<button type="button" data-act="filter" class="btn btn-small">show all</button>` +
    (untagged ? `<span class="muted">untagged ${esc(untagged)}</span>` : "") +
    `</div>` +
    `</section>`
  );
}

function listChips(tags) {
  return (tags ?? [])
    .map((tag) => `<span class="tag">${esc(tag)}</span>`)
    .join(" ");
}

function detailChips(episode) {
  const id = esc(episode.id);
  return (episode.tags ?? [])
    .map(
      (tag) =>
        `<span class="tag bug-chip">${esc(tag)} ` +
        `<button type="button" data-act="dropTag" data-id="${id}"` +
        ` data-tag="${esc(tag)}"` +
        ` aria-label="remove tag ${esc(tag)}">×</button></span>`,
    )
    .join(" ");
}

function datalist() {
  const names = [
    ...(view.list?.summary?.tags ?? []).map(([tag]) => tag),
    ...BUILTIN_TAGS,
  ];
  const unique = [...new Set(names)];
  return (
    `<datalist id="bug-tags">` +
    unique.map((tag) => `<option value="${esc(tag)}"></option>`).join("") +
    `</datalist>`
  );
}

function runsList(runs) {
  const rows = (runs ?? [])
    .map((run) => {
      const code = Number(run.code);
      const outcome = code === 0 ? "passed" : `exit ${esc(code)}`;
      return (
        `<li class="bug-run">` +
        `<span class="bug-run-line" data-code="${esc(code)}">` +
        `${esc(clock(run.start))} ${outcome} (${esc(seconds(run.dur_s))}s)` +
        `</span></li>`
      );
    })
    .join("");
  return rows ? `<ul class="bug-runs">${rows}</ul>` : "";
}

function detail(episode) {
  const id = esc(episode.id);
  const closed = episode.closed ? ` · closed ${esc(minute(episode.closed))}` : "";
  const diff =
    episode.diff && String(episode.diff).trim() !== ""
      ? diffHtml(episode.diff)
      : `<p class="muted">no diff (not a git repo, or not fixed)</p>`;
  return (
    `<section class="card bug-detail">` +
    `<div class="spread">` +
    `<h2>#${id} ${esc(episode.status)}</h2>` +
    `<button type="button" data-act="close">Close</button>` +
    `</div>` +
    `<p><code class="bug-cmd">${esc(episode.cmd)}</code> ` +
    `<span class="muted">${esc(episode.cwd)}</span></p>` +
    `<p class="muted bug-times">opened ${esc(minute(episode.opened))}${closed} · ` +
    `${esc(failsText(episode.fails))} · lost ${esc(fmtMin(episode.lost_min ?? 0))}</p>` +
    runsList(episode.runs) +
    `<div class="row bug-chip-row">${detailChips(episode)}</div>` +
    `<form data-act="addTag" data-id="${id}">` +
    datalist() +
    `<label for="bug-tag">add a tag</label>` +
    `<input id="bug-tag" name="tag" list="bug-tags" autocomplete="off">` +
    `<button type="submit" class="btn btn-small">Add</button>` +
    `</form>` +
    diff +
    `</section>`
  );
}

function episodeRow(episode) {
  const id = esc(episode.id);
  return (
    `<button type="button" data-act="open" data-id="${id}">` +
    `<span class="bug-id">#${id}</span>` +
    `<span class="bug-status" data-status="${esc(episode.status)}">${esc(episode.status)}</span>` +
    `<code class="bug-cmd">${esc(episode.cmd)}</code>` +
    `<span class="bug-cwd muted">${esc(episode.cwd)}</span>` +
    `<span class="bug-fails">${esc(failsText(episode.fails))}</span>` +
    `<span class="bug-lost muted">lost ${esc(fmtMin(episode.lost_min ?? 0))}</span>` +
    `<span class="bug-chips">${listChips(episode.tags)}</span>` +
    `<time class="bug-date muted">${esc(day(episode.opened))}</time>` +
    `</button>`
  );
}

function episodesSection(episodes) {
  if (!episodes.length) {
    const note = view.tag
      ? `no bugs with tag ${esc(view.tag)}`
      : "no episodes";
    return `<section class="card"><h2>Episodes</h2><p class="muted">${note}</p></section>`;
  }
  return (
    `<section class="card bug-episodes"><h2>Episodes</h2>` +
    episodes.map(episodeRow).join("") +
    `</section>`
  );
}

export function html(state, extra = {}) {
  absorb(extra);
  const list = view.list;
  if (!list && !view.detail) return '<p class="muted">loading…</p>';
  const summary = list?.summary ?? {};
  const episodes = list?.episodes ?? [];
  const total =
    (Number(summary.fixed) || 0) +
    (Number(summary.open) || 0) +
    (Number(summary.abandoned) || 0);
  if (list && !total && !episodes.length && !view.detail) {
    return (
      `<section class="card bug-empty"><h2>Bugs</h2>` +
      `<p class="muted">no bugs yet</p>` +
      `<p class="muted">run builds and tests through pm run -- &lt;command&gt;</p>` +
      `</section>`
    );
  }
  return (
    (list ? tiles(summary) : "") +
    (list ? burstsLine(summary) : "") +
    (list ? tagsSection(summary) : "") +
    (view.detail ? detail(view.detail) : "") +
    (list ? episodesSection(episodes) : "")
  );
}

function episodeById(id) {
  const wanted = String(id);
  if (view.detail && String(view.detail.id) === wanted) return view.detail;
  return (
    (view.list?.episodes ?? []).find(
      (episode) => String(episode.id) === wanted,
    ) ?? null
  );
}

function rememberTags(id, tags) {
  const wanted = String(id);
  if (view.detail && String(view.detail.id) === wanted) {
    view.detail = { ...view.detail, tags };
  }
  const episodes = view.list?.episodes ?? [];
  const index = episodes.findIndex((item) => String(item.id) === wanted);
  if (index >= 0) {
    view.list = {
      ...view.list,
      episodes: episodes.map((item, at) =>
        at === index ? { ...item, tags } : item,
      ),
    };
  }
}

export const actions = {
  filter(data) {
    const raw = data?.tag;
    const tag =
      raw === undefined || raw === null || String(raw) === "" ? null : String(raw);
    if (tag === view.tag) return;
    view.tag = tag;
    view.openId = null;
    view.detail = null;
  },

  open(data) {
    if (data?.id === undefined || data.id === null) return;
    view.openId = data.id;
    view.detail = null;
  },

  close() {
    view.openId = null;
    view.detail = null;
  },

  async addTag(data, ctx) {
    const id = String(data?.id ?? "");
    const tag = String(data?.tag ?? "").trim();
    if (!id || !tag) return;
    const episode = episodeById(id);
    if (!episode) return;
    const tags = [...(episode.tags ?? [])];
    if (tags.includes(tag)) return;
    tags.push(tag);
    const result = await ctx.api("POST", `/api/bugs/${encodeURIComponent(id)}/tags`, { tags });
    if (Array.isArray(result?.tags)) rememberTags(id, result.tags);
  },

  async dropTag(data, ctx) {
    const id = String(data?.id ?? "");
    const tag = String(data?.tag ?? "");
    if (!id || !tag) return;
    const episode = episodeById(id);
    if (!episode) return;
    const tags = (episode.tags ?? []).filter((item) => String(item) !== tag);
    const result = await ctx.api("POST", `/api/bugs/${encodeURIComponent(id)}/tags`, { tags });
    if (Array.isArray(result?.tags)) rememberTags(id, result.tags);
  },
};
