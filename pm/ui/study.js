import { esc, pct, relDay } from "./lib.js";
import { graphSvg } from "./graph.js";

const CHART = 200;
const CHART_PAD = 20;
const CHART_SPAN = CHART - CHART_PAD * 2;

let editing = null;
let current = null;

export async function load(ctx) {
  current = await ctx.api("GET", "/api/study");
  const lh = await ctx.api("GET", "/api/lh").catch(() => null); // LearnHarness trouble must not hide the topics
  return { study: current, lh };
}

function findTopic(study, id) {
  return (study?.topics ?? []).find((topic) => String(topic.id) === String(id)) ?? null;
}

function courseGroups(study) {
  const groups = new Map();
  for (const topic of study.topics ?? []) {
    const course = topic.course || "other";
    if (!groups.has(course)) groups.set(course, []);
    groups.get(course).push(topic);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function examCell(exam, today) {
  if (!exam) return "-";
  const rel = relDay(exam, today);
  return `${esc(exam)}${rel ? ` <span class="muted">(${esc(rel)})</span>` : ""}`;
}

function masteryBar(mastery) {
  const value = Number(mastery) || 0;
  const level = value < 0.6 ? "red" : "green";
  const percent = esc(pct(value));
  return (
    `<div class="row">` +
    `<div class="bar" data-level="${level}" aria-hidden="true"><span style="width:${percent}"></span></div>` +
    `<span class="muted">${percent}</span>` +
    `</div>`
  );
}

function nextCard(study) {
  const next = study.next;
  const topic = next ? findTopic(study, next.topic_id) : null;
  if (!topic) {
    return (
      `<section class="card"><h2>Study next</h2>` +
      `<p class="muted">no topics with an upcoming exam</p></section>`
    );
  }
  const goal = next.unblocks_id != null ? findTopic(study, next.unblocks_id) : null;
  return (
    `<section class="card"><h2>Study next</h2>` +
    `<p>study next: ${esc(topic.course || "other")} / ${esc(topic.name)} — mastery ${esc(pct(topic.mastery))}` +
    (goal ? ` <span class="muted">(prerequisite of ${esc(goal.name)})</span>` : "") +
    `</p>` +
    (topic.items === 0
      ? `<p class="muted">nothing in it yet: add a note's sections to this topic first</p>`
      : `<a href="#/review">Review now</a>`) +
    `</section>`
  );
}

function rankingSection(study, today) {
  const rows = (study.ranking ?? [])
    .slice(0, 5)
    .map((pick) => {
      const topic = findTopic(study, pick.topic_id);
      const name = topic
        ? `${topic.course || "other"} / ${topic.name}`
        : `#${pick.topic_id}`;
      return (
        `<tr>` +
        `<td>${esc(name)}</td>` +
        `<td data-label="exam">${topic ? examCell(topic.exam, today) : "-"}</td>` +
        `<td data-label="mastery">${esc(pct(pick.mastery))}</td>` +
        `<td data-label="score">${esc(Number(pick.score).toFixed(2))}</td>` +
        `</tr>`
      );
    })
    .join("");
  const body = rows
    ? `<table><thead><tr><th>topic</th><th>exam</th><th>mastery</th><th>score</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`
    : '<p class="muted">no topics with an upcoming exam</p>';
  return `<section class="card"><h2>Ranking</h2>${body}</section>`;
}

const FACETS = [
  ["memory", "no items yet"],
  ["understanding", "no checks yet"],
  ["application", "no practice yet"],
];

function facetBars(facets) {
  if (!facets) return "";
  const rows = FACETS.map(([name, missing]) => {
    const part = facets[name];
    if (!part) return `<li class="facet"><span class="facet-name">${name}</span> <span class="muted">${missing}</span></li>`;
    const percent = esc(pct(part.value));
    const n = Number(part.n) || 0;
    const thin = Number(part.strength) < 1;
    const title = thin ? ` title="thin evidence: ${esc(n === 1 ? "1 answer" : `${n} answers`)}"` : "";
    return (
      `<li class="facet${thin ? " thin" : ""}"${title}><span class="facet-name">${name}</span>` +
      `<div class="bar facet-bar" aria-hidden="true"><span style="width:${percent}"></span></div>` +
      `<span class="muted">${percent}</span></li>`
    );
  }).join("");
  const total = Number(facets.total) || 0;
  const covered = total
    ? `<p class="muted facet-covered">covered ${esc(facets.covered ?? 0)} of ${esc(total)} sections</p>`
    : "";
  return `<ul class="facets">${rows}</ul>${covered}`;
}

function readinessSection(study, today) {
  const lines = (study.readiness ?? []).map((r) => {
    const when = relDay(r.exam, today);
    return `<li>${esc(r.course || "other")} ${esc(pct(r.value))} ready, exam ${esc(when || r.exam)}</li>`;
  });
  return lines.length ? `<ul class="readiness">${lines.join("")}</ul>` : "";
}

function missesSection(study) {
  const topicName = (id) => findTopic(study, id)?.name ?? "-";
  const rows = (study.misses ?? []).map(
    (m) =>
      `<tr><td data-label="when">${esc(String(m.when ?? "").slice(0, 10))}</td>` +
      `<td data-label="topic">${esc(topicName(m.topic_id))}</td>` +
      `<td data-label="said">said ${esc(pct(m.confidence))}</td>` +
      `<td data-label="source">${esc(m.source)}</td><td>${esc(m.label)}</td></tr>`,
  );
  if (!rows.length) return "";
  return (
    `<section class="card"><h2>Confident mistakes</h2>` +
    `<table><thead><tr><th>when</th><th>topic</th><th>said</th><th>source</th><th>what</th></tr></thead>` +
    `<tbody>${rows.join("")}</tbody></table></section>`
  );
}

function gapText(gap) {
  const g = Number(gap) || 0;
  if (g > 0.1) return `overrates by ${Math.round(g * 100)}`;
  if (g < -0.1) return `underrates by ${Math.round(-g * 100)}`;
  return "calibrated";
}

function sourcesTable(cal) {
  const sources = cal?.sources ?? [];
  if (sources.length < 2) return "";
  const rows = sources
    .map(
      (s) =>
        `<tr><td>${esc(s.source)}</td><td data-label="answers">${esc(s.n ?? 0)}</td>` +
        `<td data-label="Brier">${esc(s.brier == null ? "-" : Number(s.brier).toFixed(3))}</td>` +
        `<td>${esc(gapText(s.gap))}</td></tr>`,
    )
    .join("");
  return (
    `<table class="calib-sources"><thead><tr><th>source</th><th>answers</th><th>Brier</th><th></th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`
  );
}

function topicRow(topic, today) {
  const id = esc(topic.id);
  return (
    `<tr>` +
    `<td>${esc(topic.name)}</td>` +
    `<td data-label="exam">${examCell(topic.exam, today)}</td>` +
    `<td data-label="weight">${esc(topic.weight)}</td>` +
    `<td>${masteryBar(topic.mastery)}${facetBars(topic.facets)}</td>` +
    `<td data-label="items">${esc(topic.items ?? 0)}</td>` +
    `<td data-label="due">${esc(topic.due ?? 0)}</td>` +
    `<td><button type="button" class="btn btn-small" data-act="editTopic" data-id="${id}">Edit</button></td>` +
    `</tr>`
  );
}

function editRow(topic) {
  const id = esc(topic.id);
  return (
    `<tr class="editing"><td colspan="7">` +
    `<form data-act="saveTopic" data-id="${id}" class="card">` +
    `<h3>Edit ${esc(topic.name)}</h3>` +
    `<div class="field">` +
    `<label for="edit-exam-${id}">exam</label>` +
    `<input id="edit-exam-${id}" name="exam" value="${esc(topic.exam)}" placeholder="2026-12-01 or +3">` +
    `</div>` +
    `<div class="field">` +
    `<label for="edit-weight-${id}">weight</label>` +
    `<input id="edit-weight-${id}" name="weight" type="number" step="any" min="0.1" required value="${esc(topic.weight)}">` +
    `</div>` +
    `<div class="row">` +
    `<button type="submit" class="btn btn-primary">Save</button>` +
    `<button type="button" class="btn" data-act="cancel">Cancel</button>` +
    `</div>` +
    `</form></td></tr>`
  );
}

function topicsSection(study, today) {
  const groups = courseGroups(study);
  if (!groups.length) {
    return `<section class="card"><h2>Topics by course</h2><p class="muted">no topics yet</p></section>`;
  }
  const body = groups
    .map(([course, topics]) => {
      const ids = new Set(topics.map((topic) => topic.id));
      const linked = topics.some((topic) =>
        (topic.prereqs ?? []).some((id) => ids.has(id)),
      );
      const graph = linked
        ? `<div class="graph">${graphSvg(topics, study.next?.topic_id, course)}</div>`
        : "";
      const rows = topics
        .map((topic) =>
          String(topic.id) === editing ? editRow(topic) : topicRow(topic, today),
        )
        .join("");
      return (
        `<h3>${esc(course)}</h3>` +
        graph +
        `<table><thead><tr><th>name</th><th>exam</th><th>weight</th><th>mastery</th>` +
        `<th>items</th><th>due</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      );
    })
    .join("");
  return `<section class="card"><h2>Topics by course</h2>${readinessSection(study, today)}${body}</section>`;
}

function courseList(study) {
  const courses = [
    ...new Set((study.topics ?? []).map((topic) => topic.course).filter(Boolean)),
  ].sort();
  return courses
    .map((course) => `<option value="${esc(course)}"></option>`)
    .join("");
}

function needsOptions(study) {
  return courseGroups(study)
    .map(
      ([course, topics]) =>
        `<optgroup label="${esc(course)}">` +
        topics
          .map((topic) => {
            const topicCourse = String(topic.course ?? "");
            const disabled = topicCourse === "" ? "" : " disabled";
            return (
              `<option value="${esc(topic.name)}" data-course="${esc(topicCourse)}"${disabled}>` +
              `${esc(topic.name)}</option>`
            );
          })
          .join("") +
        `</optgroup>`,
    )
    .join("");
}

function addForm(study) {
  return (
    `<section class="card"><h2>Add a topic</h2>` +
    `<form data-act="addTopic">` +
    `<datalist id="study-courses">${courseList(study)}</datalist>` +
    `<div class="field">` +
    `<label for="study-name">name</label>` +
    `<input id="study-name" name="name" required maxlength="200">` +
    `</div>` +
    `<div class="field">` +
    `<label for="study-course">course</label>` +
    `<input id="study-course" name="course" list="study-courses" autocomplete="off">` +
    `</div>` +
    `<div class="field">` +
    `<label for="study-exam">exam</label>` +
    `<input id="study-exam" name="exam" placeholder="2026-12-01 or +20">` +
    `</div>` +
    `<div class="field">` +
    `<label for="study-weight">weight</label>` +
    `<input id="study-weight" name="weight" type="number" step="any" min="0.1" value="1">` +
    `</div>` +
    `<div class="field">` +
    `<label for="study-needs">needs</label>` +
    `<select multiple name="needs" id="study-needs" size="6">${needsOptions(study)}</select>` +
    `</div>` +
    `<button type="submit" class="btn btn-primary">Add topic</button>` +
    `</form>` +
    `<div class="row dialog-actions">` +
    `<button type="button" class="btn" data-act="addFromFile">Add items from a file</button>` +
    `</div>` +
    `</section>`
  );
}

function clamp01(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number));
}

function chartPoint(said, recalled) {
  return {
    x: CHART_PAD + clamp01(said) * CHART_SPAN,
    y: CHART - CHART_PAD - clamp01(recalled) * CHART_SPAN,
  };
}

function calibrationChart(cal) {
  const bins = cal.bins ?? [];
  const maxN = Math.max(1, ...bins.map((bin) => Number(bin.n) || 0));
  const circles = bins
    .map((bin) => {
      const point = chartPoint(bin.said, bin.recalled);
      const radius = 4 + 6 * Math.sqrt((Number(bin.n) || 0) / maxN);
      const title = `said ${pct(bin.said)}, recalled ${pct(bin.recalled)}, ${Number(bin.n) || 0} reviews`;
      return (
        `<circle cx="${point.x}" cy="${point.y}" r="${radius}">` +
        `<title>${esc(title)}</title></circle>`
      );
    })
    .join("");
  const start = chartPoint(0, 0);
  const end = chartPoint(1, 1);
  return (
    `<svg class="calib-chart" role="img" aria-label="reliability: what you said against what you recalled" viewBox="0 0 200 200" width="200" height="200">` +
    `<line class="axis" x1="${CHART_PAD}" y1="${CHART - CHART_PAD}" x2="${CHART - CHART_PAD}" y2="${CHART - CHART_PAD}"></line>` +
    `<line class="axis" x1="${CHART_PAD}" y1="${CHART_PAD}" x2="${CHART_PAD}" y2="${CHART - CHART_PAD}"></line>` +
    `<line class="diagonal" x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}"></line>` +
    `<text x="${CHART / 2}" y="${CHART - 4}" text-anchor="middle">said</text>` +
    `<text x="12" y="${CHART / 2}" text-anchor="middle" transform="rotate(-90 12 ${CHART / 2})">recalled</text>` +
    circles +
    `</svg>`
  );
}

function calibrationSection(cal) {
  if (!Number(cal?.n)) {
    return `<section class="card"><h2>Calibration</h2><p class="muted">no reviews yet</p></section>`;
  }
  const n = Number(cal.n);
  const brier = cal.brier == null ? "-" : Number(cal.brier).toFixed(3);
  const gap = Number(cal.gap) || 0;
  let verdict = "well calibrated";
  if (gap > 0.1) {
    verdict = `you overrate yourself by ${Math.round(gap * 100)} points`;
  } else if (gap < -0.1) {
    verdict = `you underrate yourself by ${Math.round(-gap * 100)} points`;
  }
  const rows = (cal.bins ?? [])
    .map(
      (bin) =>
        `<tr><td data-label="said">${esc(pct(bin.said))}</td><td data-label="recalled">${esc(pct(bin.recalled))}</td>` +
        `<td data-label="reviews">${esc(bin.n ?? 0)}</td></tr>`,
    )
    .join("");
  const table = rows
    ? `<table class="calib-table"><thead><tr><th>said</th><th>recalled</th><th>reviews</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`
    : "";
  return (
    `<section class="card"><h2>Calibration</h2>` +
    `<p>${n} reviews · Brier ${esc(brier)} (0 is perfect, 0.25 is always guessing 50%)</p>` +
    calibrationChart(cal) +
    table +
    sourcesTable(cal) +
    `<p>${esc(verdict)}</p>` +
    `</section>`
  );
}

function queueSection(study) {
  const due = Number(study.queue?.due ?? 0);
  const held = Number(study.queue?.held ?? 0);
  const line = `${due} due now${held === 1 ? " · 1 new item waits for another day" : held > 1 ? ` · ${held} new items wait for another day` : ""}`;
  return `<section class="card"><h2>Queue</h2><p>${esc(line)}</p></section>`;
}

function spotSection(state) {
  const llm = state?.llm === true;
  const spots = Number(state?.spots ?? 0);
  if (!llm && spots <= 0) return "";
  const ready = spots === 1 ? "1 card ready" : `${spots} cards ready`;
  return (
    `<section class="card"><h2>Spot the error</h2>` +
    `<p>${esc(ready)}</p><div class="row">` +
    (spots > 0 ? `<a class="btn btn-small" href="#/spot">Start</a>` : "") +
    (llm ? `<button type="button" class="btn btn-small" data-act="makeSpots">Make 3 more</button>` : "") +
    `</div></section>`
  );
}

function lhSession(s, study) {
  const when = s.updated ? String(s.updated).slice(0, 10) : "-";
  const meta = `${esc(s.kind)} · ${esc(s.minutes)} min · ${esc(when)}`;
  if (s.topic_id != null) {
    const topic = findTopic(study, s.topic_id);
    const where = topic ? `${topic.course || "-"}/${topic.name}` : `topic #${s.topic_id}`;
    return `<li><strong>${esc(s.title)}</strong> <span class="muted">${meta}</span> → ${esc(where)}</li>`;
  }
  const options = (study.topics ?? [])
    .map((t) => `<option value="${esc(t.id)}">${esc(`${t.course || "-"}/${t.name}`)}</option>`)
    .join("");
  return (
    `<li><form data-act="mapSession" data-chat="${esc(s.chat_id)}" class="row">` +
    `<strong>${esc(s.title)}</strong> <span class="muted">${meta}</span>` +
    `<select name="topic" aria-label="topic for ${esc(s.title)}"><option value="">no topic</option>${options}</select>` +
    `<button type="submit" class="btn btn-small">Save</button></form></li>`
  );
}

function suspendedSection(study) {
  const found = study.suspended ?? [];
  if (!found.length) return "";
  const rows = found
    .map((item) => {
      const topic = findTopic(study, item.topic_id);
      return (
        `<li>${esc(item.title)}${topic ? ` <span class="muted">${esc(topic.name)}</span>` : ""} ` +
        `<button type="button" class="btn btn-small" data-act="resumeItem" data-id="${esc(item.id)}">Resume</button></li>`
      );
    })
    .join("");
  return `<section class="card"><h2>Suspended items</h2><ul>${rows}</ul></section>`;
}

function suggestionsSection(study) {
  const found = study.suggestions ?? [];
  const agent = study.agent ?? {};
  const jobs =
    Number(agent.budget) > 0
      ? `<p class="muted">model jobs: ${esc(agent.spent)} of ${esc(agent.budget)} calls used today, ${esc(agent.queued)} queued</p>`
      : "";
  if (!found.length) return jobs ? `<section class="card">${jobs}</section>` : "";
  const rows = found
    .map(
      (s) =>
        `<li class="spread"><span>${esc(s.text)}</span><span class="row">` +
        `<button type="button" class="btn btn-small" data-act="acceptSuggestion" data-id="${esc(s.id)}">Accept</button>` +
        `<button type="button" class="btn btn-small" data-act="rejectSuggestion" data-id="${esc(s.id)}">Reject</button>` +
        `</span></li>`,
    )
    .join("");
  return `<section class="card"><h2>Suggestions</h2><ul class="suggestions">${rows}</ul>${jobs}</section>`;
}

const PLUGIN_HINTS = {
  missing: "the tutor can't see pm yet: run pm lh install",
  old: "the pm plugin in LearnHarness is out of date: run pm lh install",
};

function lhSection(lh, study, plugin) {
  if (!lh) return "";
  if (!lh.found) {
    return `<section class="card"><h2>LearnHarness sessions</h2><p class="muted">LearnHarness not found: set lh_dir in Settings if you use it</p></section>`;
  }
  const sessions = (lh.sessions ?? []).filter((s) => !s.error);
  const unsorted = sessions.filter((s) => s.topic_id == null);
  const mapped = sessions.filter((s) => s.topic_id != null);
  const list = [...unsorted, ...mapped].map((s) => lhSession(s, study)).join("");
  const skipped = lh.skipped ?? [];
  return (
    `<section class="card lh-sessions"><div class="spread"><h2>LearnHarness sessions</h2>` +
    `<button type="button" class="btn btn-small" data-act="lhSync">Sync now</button></div>` +
    (PLUGIN_HINTS[plugin] ? `<p class="muted">${esc(PLUGIN_HINTS[plugin])}</p>` : "") +
    (list ? `<ul>${list}</ul>` : `<p class="muted">no sessions yet</p>`) +
    (skipped.length ? `<ul class="muted">${skipped.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "") +
    `</section>`
  );
}

export function html(state, extra = {}) {
  const study = extra?.study;
  if (!study) return '<p class="muted">loading…</p>';
  current = study;
  const today = String(state?.now ?? "").slice(0, 10);
  return (
    nextCard(study) +
    rankingSection(study, today) +
    topicsSection(study, today) +
    addForm(study) +
    missesSection(study) +
    calibrationSection(study.calibration) +
    queueSection(study) +
    spotSection(state) +
    suggestionsSection(study) +
    suspendedSection(study) +
    lhSection(extra.lh, study, state?.lh?.plugin)
  );
}


export function input(event, _ctx) {
  const target = event?.target;
  if (!target || target.name !== "course" || !target.form) return false;
  const form = target.form;
  const select = form.querySelector?.('select[name="needs"]');
  const options =
    select?.options ??
    form.querySelectorAll?.('select[name="needs"] option') ??
    form.querySelectorAll?.("option") ??
    [];
  const course = String(target.value ?? "").trim();
  for (const option of options) {
    const matches = String(option.dataset?.course ?? "") === course;
    option.disabled = !matches;
    if (!matches) option.selected = false;
  }
  return false;
}

export const actions = {
  async resumeItem(data, ctx) {
    await ctx.api("POST", `/api/items/${Number(data.id)}/suspend`, { on: false });
    ctx.toast("back in your reviews");
  },
  async acceptSuggestion(data, ctx) {
    const done = await ctx.api("POST", `/api/suggestions/${Number(data.id)}/accept`, undefined);
    if (done?.text) ctx.toast(`done: ${done.text}`);
  },
  async rejectSuggestion(data, ctx) {
    await ctx.api("POST", `/api/suggestions/${Number(data.id)}/reject`, undefined);
  },
  async mapSession(data, ctx) {
    const topic = String(data.topic ?? "");
    await ctx.api("POST", `/api/lh/sessions/${encodeURIComponent(data.chat)}/map`, {
      topic_id: topic ? Number(topic) : null,
    });
  },
  async lhSync(_data, ctx) {
    const out = await ctx.api("POST", "/api/lh/sync", {});
    if (!out) return;
    const counts = `${out.sessions} sessions, ${out.answers} answers, ${out.outcomes} outcomes, ${out.questions} questions, ${out.cards} cards`;
    const changed = out.sessions || out.answers || out.outcomes || out.questions || out.cards;
    ctx.toast(changed ? `learnharness: ${counts}` : (out.skipped?.[0] ?? "learnharness: nothing new"));
  },
  async makeSpots(_data, ctx) {
    const answer = await ctx.api("POST", "/api/spot/make", { n: 3 });
    const made = Number(answer?.made ?? 0);
    const errors = answer?.errors ?? [];
    if (made > 0) ctx.toast(`made ${made} ${made === 1 ? "card" : "cards"}`);
    else ctx.toast(errors[0] ?? "nothing to make cards from (review some text items first)");
  },

  async addFromFile(_data, ctx) {
    await ctx.openAddStudy();
  },

  async addTopic(data, ctx) {
    const body = { name: String(data?.name ?? "").trim() };
    const course = data?.course;
    if (course !== undefined && String(course) !== "") body.course = course;
    const exam = data?.exam;
    if (exam !== undefined && String(exam) !== "") body.exam = exam;
    const weight = data?.weight;
    if (weight !== undefined && String(weight) !== "") body.weight = Number(weight);
    const needs = data?.needs;
    if (needs !== undefined && needs !== null) {
      const values = (Array.isArray(needs) ? needs : [needs]).filter(
        (value) => String(value ?? "") !== "",
      );
      if (values.length) body.needs = values;
    }
    await ctx.api("POST", "/api/topics", body);
  },

  editTopic(data) {
    if (data?.id !== undefined) editing = String(data.id);
  },

  cancel() {
    editing = null;
  },

  async saveTopic(data, ctx) {
    const id = String(data.id);
    const topic = (current?.topics ?? []).find((item) => String(item.id) === id);
    if (!topic) throw new Error(`no topic #${id}`);
    const body = {};
    if ("exam" in data) {
      const exam = String(data.exam ?? "");
      if (exam !== String(topic.exam ?? "")) body.exam = exam;
    }
    if ("weight" in data && String(data.weight ?? "") !== "") {
      const weight = Number(data.weight);
      if (Number.isFinite(weight) && weight !== Number(topic.weight)) {
        body.weight = weight;
      }
    }
    if (Object.keys(body).length === 0) {
      editing = null;
      return;
    }
    await ctx.api("POST", `/api/topics/${id}/edit`, body);
    editing = null;
  },
};
