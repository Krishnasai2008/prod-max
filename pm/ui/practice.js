// Practice: generated problems whose answers pm computes itself. The key and the worked solution
// reach the page only with the verdict, after the answer is sent.
import { esc } from "./lib.js";
import { hasMath, mdHtml, typeset } from "./md.js";

let stage = "pick"; // pick | problem | verdict
let overview = null;
let problem = null;
let verdict = null;
let dontKnew = false;
let topicChoice = "";
let confidence = 50;
let shownAt = 0;

const clock = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

export async function enter(_ctx) {
  stage = "pick";
  problem = null;
  verdict = null;
}

export async function load(ctx) {
  overview = (await ctx.api("GET", "/api/practice")) ?? null;
  return { practice: overview, stage };
}

export function input(event, _ctx) {
  const target = event.target;
  if (!target || target.name !== "confidence") return;
  confidence = Math.max(0, Math.min(100, Math.round(Number(target.value) || 0)));
  const out = target.form?.querySelector?.("[data-confidence-value]");
  if (out) out.textContent = `${confidence}%`;
}

function where(t) {
  return `${t.course || "-"}/${t.name}`;
}

function topicRow(t, gens) {
  const chips = t.gens
    .map(
      (g) =>
        `<span class="gen-chip">${esc(g)} <button type="button" class="gen-chip-x" data-act="unlink" data-topic="${esc(t.id)}"` +
        ` data-gen="${esc(g)}" aria-label="unlink ${esc(g)} from ${esc(t.name)}">×</button></span>`,
    )
    .join(" ");
  const free = gens.filter((g) => !t.gens.includes(g.id));
  const linkForm = free.length
    ? `<form data-act="link" data-topic="${esc(t.id)}" class="row">` +
      `<select name="gen" aria-label="generator to link to ${esc(t.name)}">` +
      free.map((g) => `<option value="${esc(g.id)}">${esc(g.id)}: ${esc(g.title)}</option>`).join("") +
      `</select><button type="submit" class="btn">Link</button></form>`
    : "";
  const tries = t.attempts
    ? `${t.attempts === 1 ? "1 try" : `${t.attempts} tries`}, ${t.right} right in 30 days`
    : "no tries in 30 days";
  return (
    `<li class="practice-topic"><div class="spread"><strong>${esc(where(t))}</strong>` +
    `<span class="muted">${esc(tries)}</span></div>` +
    (chips ? `<div class="gen-chips">${chips}</div>` : "") +
    linkForm +
    `</li>`
  );
}

function pickHtml() {
  const gens = overview?.generators ?? [];
  const all = overview?.topics ?? [];
  const linked = all.filter((t) => t.gens.length);
  const start = linked.length
    ? `<form data-act="start" class="row">` +
      `<select name="topic" aria-label="topic to practise">` +
      `<option value="">next best topic</option>` +
      linked
        .map((t) => `<option value="${esc(t.id)}"${String(t.id) === topicChoice ? " selected" : ""}>${esc(where(t))}</option>`)
        .join("") +
      `</select><button type="submit" class="btn btn-primary">Start</button></form>`
    : `<p class="muted">link a generator to a topic to start: ${esc(gens.map((g) => g.id).join(", "))}</p>`;
  const errors = overview?.errors ?? [];
  return (
    `<section class="card practice"><h2>Practice</h2>` +
    `<p class="muted">fresh problems whose answers pm works out itself</p>` +
    start +
    (all.length ? `<ul class="practice-topics">${all.map((t) => topicRow(t, gens)).join("")}</ul>` : `<p class="muted">no topics yet</p>`) +
    (errors.length
      ? `<h3>templates that didn't load</h3><ul class="practice-errors">${errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>`
      : "") +
    `</section>`
  );
}

function head() {
  return (
    `<div class="spread muted"><span>${esc(problem.title)}</span>` +
    `<span>${esc(problem.course || "-")} / ${esc(problem.topic)}</span></div>`
  );
}

function problemHtml() {
  return (
    `<section class="card practice">` +
    head() +
    `<div class="md">${mdHtml(problem.text ?? "")}</div>` +
    `<form data-act="answer">` +
    `<div class="field"><label for="practice-answer">your answer</label>` +
    `<input id="practice-answer" name="answer" autocomplete="off" required></div>` +
    `<div class="field"><label for="practice-conf">how sure are you? <output data-confidence-value>${confidence}%</output></label>` +
    `<input type="range" id="practice-conf" name="confidence" min="0" max="100" step="5" value="${confidence}"></div>` +
    `<div class="row"><button type="submit" class="btn btn-primary">Check</button>` +
    `<button type="button" class="btn" data-act="dontKnow">Don't know</button></div>` +
    `</form></section>`
  );
}

function verdictHtml() {
  const v = verdict;
  let line;
  if (dontKnew) line = `the answer is ${v.key}`;
  else if (v.correct) line = "right";
  else line = `wrong: the answer is ${v.key}`;
  const unread =
    !dontKnew && !v.readable
      ? `<p>pm couldn't read that${problem.kind === "number" ? " as a number" : " answer"}</p>`
      : "";
  return (
    `<section class="card practice">` +
    head() +
    `<div class="md">${mdHtml(problem.text ?? "")}</div>` +
    unread +
    `<p class="practice-verdict${v.correct ? " good" : ""}"><strong>${esc(line)}</strong></p>` +
    `<div class="md practice-steps">${mdHtml(v.steps ?? "")}</div>` +
    `<div class="row"><button type="button" class="btn btn-primary" data-act="next">Next</button>` +
    `<button type="button" class="btn" data-act="stop">Stop</button></div>` +
    `</section>`
  );
}

export function html(_state, _extra) {
  if (stage === "problem" && problem) return problemHtml();
  if (stage === "verdict" && problem && verdict) return verdictHtml();
  if (!overview) return '<p class="muted">loading…</p>';
  return pickHtml();
}

export function after(root) {
  if (root && hasMath(root.textContent ?? "")) for (const el of root.querySelectorAll(".md")) typeset(el);
}

export function keys(event, ctx) {
  const tag = event.target?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false; // Escape while typing must not drop the problem
  if (event.key === "Escape" && stage !== "pick") {
    ctx.run("stop", {});
    return true;
  }
  if (event.key === "n" && stage === "verdict") {
    ctx.run("next", {});
    return true;
  }
  return false;
}

async function fetchProblem(ctx) {
  const path = topicChoice ? `/api/practice/next?topic=${encodeURIComponent(topicChoice)}` : "/api/practice/next";
  const next = await ctx.api("GET", path);
  if (!next) return;
  problem = next;
  verdict = null;
  dontKnew = false;
  confidence = 50;
  shownAt = clock();
  stage = "problem";
}

function seconds() {
  return Math.max(0, Math.min(86_400, Math.round((clock() - shownAt) / 1000)));
}

function served() {
  return { topic_id: problem.topic_id, gen: problem.gen, seed: problem.seed, variant: problem.variant };
}

export const actions = {
  async start(data, ctx) {
    topicChoice = String(data?.topic ?? "");
    await fetchProblem(ctx);
  },
  async answer(data, ctx) {
    if (!problem || stage !== "problem") return;
    const said = Math.max(0, Math.min(100, Math.round(Number(data?.confidence ?? confidence) || 0)));
    const body = { ...served(), answer: String(data?.answer ?? ""), confidence: said, dont_know: false, seconds: seconds() };
    verdict = await ctx.api("POST", "/api/practice/answer", body);
    dontKnew = false;
    if (verdict) stage = "verdict";
  },
  async dontKnow(_data, ctx) {
    if (!problem || stage !== "problem") return;
    verdict = await ctx.api("POST", "/api/practice/answer", { ...served(), answer: "", dont_know: true, seconds: seconds() });
    dontKnew = true;
    if (verdict) stage = "verdict";
  },
  async next(_data, ctx) {
    await fetchProblem(ctx);
  },
  async stop(_data, _ctx) {
    stage = "pick";
    problem = null;
    verdict = null;
  },
  async link(data, ctx) {
    await ctx.api("POST", "/api/practice/link", { topic_id: Number(data.topic), gen: data.gen });
  },
  async unlink(data, ctx) {
    await ctx.api("POST", "/api/practice/unlink", { topic_id: Number(data.topic), gen: data.gen });
  },
};

// test hook: put the screen in a given stage
export function _set(values) {
  ({ stage = stage, overview = overview, problem = problem, verdict = verdict, dontKnew = dontKnew } = values);
}
