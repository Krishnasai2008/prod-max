// Spot the error: one line of your note was changed; bet first, then pick the line.
// The page only ever has the changed lines until the answer comes back from the pick.
import { esc } from "./lib.js";

let stage = "bet";
let card = null;
let left = 0;
let confidence = 50;
let committed = 50;
let result = null;
let picked = null;
let ready = false;

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
  const answer = (await ctx.api("GET", "/api/spot/next")) ?? {};
  left = Number(answer.left ?? 0);
  card = answer.spot ?? null;
  confidence = 50;
  result = null;
  picked = null;
  stage = card ? "bet" : "done";
}

export async function enter(ctx) {
  ready = false;
  card = null;
  stage = "bet";
  committed = 50;
  try {
    await fetchNext(ctx);
  } finally {
    ready = true;
  }
}

export async function load(ctx) {
  if (!card && Number(ctx.state?.spots ?? 0) > 0) await fetchNext(ctx);
  return { spot: card?.id ?? null, stage };
}

export function input(event, _ctx) {
  const target = event.target;
  if (!target || target.name !== "confidence") return;
  confidence = clampConfidence(target.value);
  const readout = target.form?.querySelector?.("[data-confidence-value]");
  if (readout) readout.textContent = `${confidence}%`;
}

export function keys(event, ctx) {
  if (textField(event.target)) return false;
  const key = event.key;
  if (ctx.busy?.() && (/^[0-9]$/.test(key) || key === "Enter" || key === " " || key === "Escape")) return true;
  if (key === "Escape") {
    ctx.go("study");
    return true;
  }
  if (key === "n" && card && stage === "result") {
    ctx.run("next", {}); // the same key as on the Practice screen
    return true;
  }
  if (!card || stage !== "bet") return false;
  if (/^[0-9]$/.test(key)) {
    confidence = key === "0" ? 100 : Number(key) * 10;
    return true;
  }
  if (key === "Enter" || key === " ") {
    ctx.run("bet", { confidence: String(confidence) });
    return true;
  }
  return false;
}

function header() {
  return (
    `<div class="spread muted">` +
    `<span>${esc(left === 1 ? "1 card left" : `${left} cards left`)}</span>` +
    `<span>${esc(card.course)} / ${esc(card.topic)}</span>` +
    `</div>` +
    `<h2>${esc(card.title)}</h2>` +
    `<p class="muted">one line was changed to say something false</p>`
  );
}

function lineClass(n) {
  if (stage !== "result" || !result) return "";
  if (n === result.line) return ' class="spot-wrong"';
  if (n === picked) return ' class="spot-picked"';
  return "";
}

function lines() {
  const width = String((card.lines ?? []).length).length;
  return (
    `<ol class="spot-lines">` +
    (card.lines ?? [])
      .map((text, index) => {
        const n = index + 1;
        const number = `<span class="spot-n">${esc(String(n).padStart(width, " "))}</span>`;
        const body = `<code>${esc(text)}</code>`;
        if (stage === "pick") {
          return `<li><button type="button" class="spot-line" data-act="pick" data-line="${n}">${number}${body}</button></li>`;
        }
        return `<li${lineClass(n)}>${number}${body}</li>`;
      })
      .join("") +
    `</ol>`
  );
}

function bet() {
  return (
    `<article class="card spot">` +
    header() +
    lines() +
    `<form data-act="bet">` +
    `<div class="field">` +
    `<label for="confidence">how sure will you be of your pick? <output data-confidence-value for="confidence">${confidence}%</output></label>` +
    `<input type="range" id="confidence" name="confidence" min="0" max="100" step="5" value="${confidence}">` +
    `</div>` +
    `<button type="submit" class="btn btn-primary">Lock in</button>` +
    `</form>` +
    `</article>`
  );
}

function pick() {
  return `<article class="card spot">` + header() + `<p>which line is wrong? (you said ${committed}%)</p>` + lines() + `</article>`;
}

function answer() {
  const verdict = result.correct ? "right" : `wrong: it was line ${result.line}`;
  return (
    `<article class="card spot">` +
    header() +
    `<p class="spot-verdict"><strong>${esc(verdict)}</strong></p>` +
    lines() +
    `<dl class="spot-diff"><dt>was:</dt><dd><code>${esc(result.was)}</code></dd>` +
    `<dt>shown:</dt><dd><code>${esc(result.shown)}</code></dd></dl>` +
    `<button type="button" class="btn btn-primary" data-act="next">Next</button>` +
    `</article>`
  );
}

function done() {
  return `<article class="card spot"><p>no spot cards</p><p><a href="#/study">back to Study</a></p></article>`;
}

export function html(_state) {
  if (!ready) return '<p class="muted">loading…</p>';
  if (!card || stage === "done") return done();
  if (stage === "pick") return pick();
  if (stage === "result" && result) return answer();
  return bet();
}

export const actions = {
  async bet(data, _ctx) {
    if (!card) return;
    confidence = clampConfidence(data?.confidence);
    committed = confidence;
    stage = "pick";
  },

  async pick(data, ctx) {
    if (!card || stage !== "pick") return;
    picked = Number(data?.line);
    result = await ctx.api("POST", `/api/spots/${card.id}/answer`, { picked, confidence: committed });
    stage = "result";
  },

  async next(_data, ctx) {
    await fetchNext(ctx);
  },
};
