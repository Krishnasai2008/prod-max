import { esc, relTime } from "./lib.js";
import { hasMath, mdHtml, typeset } from "./md.js";

const GRADES = ["Again", "Hard", "Good", "Easy"];

let stage = "bet";
let item = null;
let excerpt = null;
let confidence = 50;
let committed = 50;
let left = 0;
let held = 0;
let ready = false;
let session = { reviewed: 0, recalled: 0, confSum: 0 };

function clampConfidence(value, fallback = confidence) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function textField(target) {
  if (!target) return false;
  if (target.isContentEditable) return true;
  if (target.closest?.("a, button, summary")) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  return tag === "INPUT" && target.type !== "range";
}

async function fetchNext(ctx) {
  const answer = (await ctx.api("GET", "/api/review/next")) ?? {};
  left = Number(answer.left ?? 0);
  held = Number(answer.held ?? 0);
  item = answer.item ?? null;
  excerpt = null;
  confidence = 50;
  stage = item ? "bet" : "done";
}

export async function enter(ctx) {
  ready = false;
  stage = "bet";
  item = null;
  excerpt = null;
  confidence = 50;
  committed = 50;
  left = 0;
  held = 0;
  session = { reviewed: 0, recalled: 0, confSum: 0 };
  try {
    await fetchNext(ctx);
  } finally {
    ready = true;
  }
}

export async function load(ctx) {
  if (!item && Number(ctx.state?.reviews_due ?? 0) > 0) {
    await fetchNext(ctx);
  }
  return { item: item?.id ?? null, stage };
}

export function input(event, _ctx) {
  const target = event.target;
  if (!target || target.name !== "confidence") return;
  confidence = clampConfidence(target.value);
  const readout =
    target.form?.querySelector?.("[data-confidence-value]") ??
    (typeof document === "undefined" ? null : document.getElementById("confidence-value"));
  if (readout) readout.textContent = `${confidence}%`;
}

export function keys(event, ctx) {
  if (textField(event.target)) return false;
  const key = event.key;
  if (
    ctx.busy?.() &&
    (/^[0-9]$/.test(key) ||
      key === "Enter" ||
      key === " " ||
      key === "Space" ||
      key === "Spacebar" ||
      key === "Escape")
  ) return true;
  if (key === "Escape") {
    ctx.go("today");
    return true;
  }
  if (!item) return false;
  if (stage === "bet") {
    if (/^[0-9]$/.test(key)) {
      confidence = key === "0" ? 100 : Number(key) * 10;
      return true;
    }
    if (key === "Enter" || key === " " || key === "Space" || key === "Spacebar") {
      ctx.run("bet", { confidence: String(confidence) });
      return true;
    }
  } else if (stage === "reveal" && /^[1-4]$/.test(key)) {
    ctx.run("grade", { grade: key });
    return true;
  }
  return false;
}

function progress() {
  const total = session.reviewed + left;
  return `${session.reviewed + 1} of ${Math.max(total, session.reviewed + 1)}`;
}

function header() {
  return (
    `<div class="spread muted">` +
    `<span>${esc(progress())}</span>` +
    `<span>${esc(item.course)} / ${esc(item.topic)}</span>` +
    `</div>`
  );
}

function question(className = "md") {
  if (!item.question) return "";
  return `<div class="${className}">${mdHtml(item.question)}</div>`;
}

function bet() {
  return (
    `<article class="card review">` +
    header() +
    `<h2>${esc(item.title)}</h2>` +
    question() +
    `<form data-act="bet">` +
    `<div class="field">` +
    `<label for="confidence">confidence <output id="confidence-value" data-confidence-value for="confidence">${confidence}%</output></label>` +
    `<input type="range" id="confidence" name="confidence" min="0" max="100" step="5" value="${confidence}">` +
    `</div>` +
    `<button type="submit" class="btn btn-primary">Show answer</button>` +
    `</form>` +
    `</article>`
  );
}

function pageAlt(data) {
  const name = String(data.path ?? "").split("/").pop() || "page";
  const page = String(data.locator ?? "").replace(/^p/, "");
  return page ? `page ${page} of ${name}` : name;
}

function answer(data) {
  if (data.kind === "markdown") {
    return `<div class="md answer">${mdHtml(data.text ?? "")}</div>`;
  }
  if (data.kind === "missing") {
    return (
      `<p>can't show this item: ${esc(data.error)}</p>` +
      `<p class="muted">grade it from memory, or suspend it</p>`
    );
  }
  if (data.kind === "pdf" && data.image) {
    return `<img class="page" src="${esc(data.image)}" alt="${esc(pageAlt(data))}">`;
  }
  if (data.kind === "text" || data.kind === "pdf") {
    return `<pre class="excerpt">${esc(data.text ?? "")}</pre>`;
  }
  return "";
}

function source(data) {
  const where = data.locator ? `${data.path} › ${data.locator}` : data.path;
  const site =
    typeof data.site === "string" && data.site.startsWith("https://")
      ? ` <a href="${esc(data.site)}" target="_blank" rel="noopener noreferrer">open on the site</a>`
      : "";
  return `<p class="muted">${esc(where)}${site}</p>`;
}

function gradeButtons(data, now) {
  const intervals = data.intervals ?? {};
  return (
    `<div class="grades">` +
    GRADES.map((label, index) => {
      const grade = index + 1;
      const when = relTime(intervals[grade], now);
      return (
        `<button type="button" class="btn" data-act="grade" data-grade="${grade}">` +
        `${label}${when ? ` · ${esc(when)}` : ""}` +
        `</button>`
      );
    }).join("") +
    `</div>`
  );
}

function reveal(state) {
  const data = excerpt ?? {};
  const now = String(state?.now ?? "");
  return (
    `<article class="card review">` +
    question("md question") +
    answer(data) +
    source(data) +
    gradeButtons(data, now) +
    `<div class="row">` +
    `<button type="button" class="btn btn-small" data-act="suspend">Suspend</button>` +
    `</div>` +
    `</article>`
  );
}

function done() {
  let line;
  if (!session.reviewed) {
    line = "nothing due";
  } else {
    const said = Math.round(session.confSum / session.reviewed);
    const recalled = Math.round((100 * session.recalled) / session.reviewed);
    line =
      `reviewed ${session.reviewed} · recalled ${session.recalled} · ` +
      `you said ${said}% on average, recalled ${recalled}%`;
  }
  const waiting = held
    ? held === 1
      ? "1 new item waits for another day"
      : `${held} new items wait for another day`
    : "";
  return (
    `<article class="card review">` +
    `<p>${esc(line)}</p>` +
    (waiting ? `<p class="muted">${esc(waiting)}</p>` : "") +
    `</article>`
  );
}

export function html(state) {
  if (!ready) return '<p class="muted">loading…</p>';
  if (!item || stage === "done") return done();
  return stage === "reveal" ? reveal(state) : bet();
}

export function after(root) {
  if (!root) return;
  let text = "";
  if (stage === "bet" && item) text = item.question ?? "";
  if (stage === "reveal") {
    text = item?.question ?? "";
    if (excerpt?.kind === "markdown") text += ` ${excerpt.text ?? ""}`;
  }
  if (!hasMath(text)) return;
  for (const element of root.querySelectorAll(".md")) typeset(element);
}

export const actions = {
  async bet(data, ctx) {
    if (!item) return;
    confidence = clampConfidence(data?.confidence);
    committed = confidence;
    excerpt = (await ctx.api("GET", `/api/items/${item.id}/excerpt`)) ?? {};
    stage = "reveal";
  },

  async grade(data, ctx) {
    if (!item) return;
    const grade = Number(data?.grade);
    await ctx.api("POST", `/api/items/${item.id}/review`, { grade, confidence: committed });
    session.reviewed += 1;
    if (grade >= 2) session.recalled += 1;
    session.confSum += committed;
    await fetchNext(ctx);
  },

  async suspend(_data, ctx) {
    if (!item) return;
    if (!ctx.confirm("Suspend this item? It leaves your reviews until you resume it on the Study screen.")) return;
    await ctx.api("POST", `/api/items/${item.id}/suspend`, undefined);
    await fetchNext(ctx);
  },
};
