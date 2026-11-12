// Exam: build a mock test, sit it against the server's clock, mark the open answers, read the result.
// The answer key reaches the page only once the test is finished (the server leaves it out before).
import { esc, fmtMin, pct } from "./lib.js";
import { hasMath, mdHtml, typeset } from "./md.js";

let openId = null;
let pos = 1;
let draft = null; // {mock, pos, answer, confidence, dontKnow}: what is typed for the shown question
let received = 0; // when left_s arrived, for the ticking clock
let leftS = null;
let ticker = null;
let lastMock = null;

export function clock(left) {
  if (left == null || !Number.isFinite(Number(left))) return "";
  const s = Math.round(Number(left));
  const a = Math.abs(s);
  const text = `${Math.floor(a / 60)}:${String(a % 60).padStart(2, "0")}`;
  return s < 0 ? `over by ${text}` : text;
}

function num(x) {
  return String(Number(Number(x ?? 0).toFixed(2)));
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function startDraft(mock) {
  const item = mock?.items?.[pos - 1];
  if (!item) return;
  if (draft && draft.mock === mock.id && draft.pos === pos) return;
  draft = {
    mock: mock.id,
    pos,
    answer: item.answer ?? "",
    confidence: item.confidence == null ? 50 : Math.round(item.confidence * 100),
    dontKnow: Boolean(item.dont_know),
  };
}

export async function enter(ctx) {
  draft = null;
  if (openId == null && ctx.state?.exam?.open) {
    openId = ctx.state.exam.open;
    pos = 1;
  }
}

export async function load(ctx) {
  const exam = await ctx.api("GET", "/api/exam");
  let mock = null;
  if (openId != null) {
    mock = await ctx.api("GET", `/api/mocks/${openId}`);
    received = Date.now();
    leftS = mock?.left_s ?? null;
    lastMock = mock;
    if (mock?.status === "running") startDraft(mock);
  }
  return { exam, mock };
}

export function input(event, _ctx) {
  const target = event?.target;
  if (!target || !draft) return;
  if (target.name === "answer") draft.answer = target.value;
  else if (target.name === "confidence") {
    draft.confidence = Math.max(0, Math.min(100, Math.round(Number(target.value) || 0)));
    const out = target.form?.querySelector?.("[data-confidence-value]");
    if (out) out.textContent = `${draft.confidence}%`;
  } else if (target.name === "dont_know") draft.dontKnow = Boolean(target.checked);
  else if (target.name === "choice") {
    const boxes = target.form?.querySelectorAll?.('input[name="choice"]:checked') ?? [];
    draft.answer = [...boxes].map((b) => b.value).join(",");
  }
}

function statusText(m) {
  if (m.status !== "marked") return m.status;
  return m.predicted == null ? pct(m.pct) : `${pct(m.pct)} (predicted ${pct(m.predicted)})`;
}

function overview(exam) {
  const courses = (exam?.courses ?? []).map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  const papers = (exam?.papers ?? [])
    .map((p) => `<option value="${esc(p.id)}">${esc(p.course)}: ${esc(p.title)} (${esc(plural(p.questions, "question"))})</option>`)
    .join("");
  const tests = (exam?.mocks ?? [])
    .map(
      (m) =>
        `<li><button type="button" class="btn btn-small" data-act="open" data-id="${esc(m.id)}">${esc(m.title)}</button> ` +
        `<span class="muted">${esc(plural(m.questions, "question"))}, ${esc(fmtMin(m.minutes))} · ${esc(statusText(m))}</span></li>`,
    )
    .join("");
  const bank = (exam?.bank ?? [])
    .map((b) => {
      const trust = Object.entries(b.by_trust ?? {});
      const extra = trust.some(([t]) => t !== "source")
        ? ` <span class="muted">(${trust.map(([t, n]) => `${esc(t)} ${esc(n)}`).join(", ")})</span>`
        : "";
      return `<li>${esc(b.course || "-")} / ${esc(b.topic ?? "no topic")} ${esc(plural(b.n, "question"))}${extra}</li>`;
    })
    .join("");
  const topics = (exam?.topics ?? [])
    .map((t) => `<option value="${esc(t.id)}">${esc(t.course || "-")} / ${esc(t.name)}</option>`)
    .join("");
  return (
    `<section class="card"><h2>New test</h2>` +
    (courses
      ? `<form data-act="create" class="exam-new">` +
        `<div class="field"><label for="exam-course">course</label><select id="exam-course" name="course">${courses}</select></div>` +
        `<div class="field"><label for="exam-n">questions</label><input id="exam-n" name="n" type="number" min="1" max="100" value="10"></div>` +
        `<div class="field"><label for="exam-minutes">minutes</label><input id="exam-minutes" name="minutes" type="number" min="1" max="600" placeholder="default"></div>` +
        `<div class="field"><label for="exam-paper">from</label><select id="exam-paper" name="paper"><option value="">sample from the bank</option>${papers}</select></div>` +
        `<button type="submit" class="btn btn-primary">Create</button>` +
        `</form>`
      : `<p class="muted">A test needs questions first: add some under Question bank below.</p>`) +
    `</section>` +
    `<section class="card"><h2>Tests</h2>${tests ? `<ul class="exam-tests">${tests}</ul>` : `<p class="muted">no tests yet</p>`}</section>` +
    toCheck(exam) +
    `<section class="card"><h2>Question bank</h2>` +
    (bank
      ? `<ul>${bank}</ul>`
      : `<p class="muted">no questions yet: import the answer sections of a note, or a past paper (pm paper import)</p>`) +
    `<form data-act="importNote" class="row">` +
    `<label for="exam-import">Import questions from a note</label>` +
    `<input id="exam-import" name="path" placeholder="/full/path/notes.md" required>` +
    `<select name="topic" aria-label="topic" required>${topics}</select>` +
    `<button type="submit" class="btn">Import</button>` +
    `</form></section>`
  );
}

function toCheck(exam) {
  const rows = (exam?.to_check ?? [])
    .map(
      (q) =>
        `<li><strong>${esc((q.flags ?? []).join(", "))}</strong> <span class="muted">${esc(q.trust)} · ` +
        `${esc(q.attempts === 1 ? "1 try" : `${q.attempts} tries`)}, mean ${esc(pct(q.mean))}</span> ${esc(q.prompt)} ` +
        `<button type="button" class="btn btn-small" data-act="retireQuestion" data-id="${esc(q.id)}"` +
        ` data-reason="flagged: ${esc((q.flags ?? [])[0] ?? "")}">Retire</button></li>`,
    )
    .join("");
  return rows ? `<section class="card"><h2>Questions to check</h2><ul class="exam-check">${rows}</ul></section>` : "";
}

function readyView(m) {
  return (
    `<section class="card"><h2>${esc(m.title)}</h2>` +
    `<p>${esc(plural(m.items.length, "question"))}, ${esc(fmtMin(m.minutes))}</p>` +
    `<div class="row"><button type="button" class="btn btn-primary" data-act="start">Start</button>` +
    `<button type="button" class="btn" data-act="back">Back to tests</button></div></section>`
  );
}

function answerField(item) {
  const value = draft?.pos === item.pos ? draft.answer : item.answer ?? "";
  if (item.kind === "open") {
    return `<textarea id="exam-answer" name="answer" rows="8" aria-label="your answer">${esc(value)}</textarea>`;
  }
  if (item.kind === "choice") {
    const picked = new Set(String(value).split(",").filter(Boolean));
    return (
      `<fieldset class="exam-choice"><legend class="muted">tick every correct option</legend>` +
      (item.options ?? [])
        .map((text, i) => {
          const n = String(i + 1);
          return (
            `<label><input type="checkbox" name="choice" value="${n}"${picked.has(n) ? " checked" : ""}> ` +
            `${String.fromCharCode(97 + i)}) ${esc(text)}</label>`
          );
        })
        .join("") +
      `</fieldset>`
    );
  }
  return `<input id="exam-answer" name="answer" autocomplete="off" aria-label="your answer" value="${esc(value)}">`;
}

function runningView(m) {
  const item = m.items[pos - 1];
  if (!item) return `<p class="muted">no such question</p>`;
  const n = m.items.length;
  const conf = draft?.pos === pos ? draft.confidence : 50;
  const dk = draft?.pos === pos ? draft.dontKnow : Boolean(item.dont_know);
  const tag = item.trust === "checked" || item.trust === "unverified" ? ` <span class="tag">${esc(item.trust)}</span>` : "";
  return (
    `<section class="card exam-q">` +
    `<div class="spread"><span>question ${pos} of ${n}${item.topic ? ` · ${esc(item.topic)}` : ""} · ${esc(plural(item.marks, "mark"))}${tag}</span>` +
    `<b class="clock" data-left>${esc(clock(leftS))}</b></div>` +
    `<div class="md">${mdHtml(item.prompt ?? "")}</div>` +
    (item.page ? `<img class="page" alt="the question's page" src="/api/questions/${esc(item.question_id)}/page.png">` : "") +
    `<form data-act="next">` +
    (item.void
      ? ""
      : answerField(item) +
        `<div class="field"><label for="exam-conf">how sure are you? <output data-confidence-value>${conf}%</output></label>` +
        `<input type="range" id="exam-conf" name="confidence" min="0" max="100" step="5" value="${conf}"></div>` +
        `<label><input type="checkbox" name="dont_know"${dk ? " checked" : ""}> don't know</label>`) +
    `<div class="row">` +
    `<button type="button" class="btn" data-act="prev"${pos <= 1 ? " disabled" : ""}>Previous</button>` +
    `<button type="submit" class="btn"${pos >= n ? " disabled" : ""}>Next</button>` +
    `<button type="button" class="btn btn-primary" data-act="finish">Finish</button>` +
    `</div></form></section>`
  );
}

function toMarkView(m) {
  const waiting = m.items.filter((i) => !i.auto && !i.void && i.score == null);
  return (
    `<section class="card"><h2>${esc(m.title)}: mark your answers</h2>` +
    waiting
      .map(
        (i) =>
          `<article class="exam-mark"><h3>question ${esc(i.pos)} · ${esc(plural(i.marks, "mark"))}</h3>` +
          `<div class="md">${mdHtml(i.prompt ?? "")}</div>` +
          `<p class="muted">your answer</p><pre class="exam-answer">${esc(i.answer ?? "")}</pre>` +
          `<p class="muted">model answer</p>` +
          (i.key ? `<div class="md">${mdHtml(i.key)}</div>` : `<p>no model answer; check the paper's key</p>`) +
          `<form data-act="mark" data-pos="${esc(i.pos)}" class="row">` +
          `<input name="got" type="number" min="0" max="${esc(i.marks)}" step="0.5" required aria-label="marks">` +
          `<button type="submit" class="btn btn-primary">Save marks</button></form></article>`,
      )
      .join("") +
    `</section>`
  );
}

export function resultHtml(m, state = {}) {
  const r = m?.result;
  if (!r) return "";
  const head =
    `<p class="exam-score"><strong>${esc(num(r.got))} of ${esc(num(r.total))} (${esc(pct(r.pct))})</strong>` +
    (r.predicted == null ? "" : ` <span class="muted">predicted ${esc(pct(r.predicted))}</span>`) +
    `</p>` +
    (r.over_min > 0 ? `<p>${esc(plural(r.over_min, "minute"))} over</p>` : "");
  const rows = (r.by_topic ?? [])
    .map((t) => `<tr><td>${esc(t.topic ?? "-")}</td><td>${esc(num(t.got))} of ${esc(num(t.total))}</td></tr>`)
    .join("");
  const said = r.said == null ? "" : `<p>you said ${esc(pct(r.said))} on average and scored ${esc(pct(r.pct))}</p>`;
  const unread = (r.unread ?? []).length ? `<p>couldn't read your answer to: ${esc(r.unread.join(", "))}</p>` : "";
  const each = (m.items ?? [])
    .map((i) =>
      i.void
        ? `<li><p class="muted">${esc(i.prompt ?? "")}</p></li>`
        : `<li><div class="md">${mdHtml(i.prompt ?? "")}</div>` +
          `<p><span class="muted">you:</span> ${esc(i.dont_know ? "don't know" : i.answer ?? "-")}` +
          ` · <span class="muted">key:</span> ${esc(i.key ?? "-")} · <span class="muted">score:</span> ${esc(pct(i.score))}</p>` +
          (i.steps ? `<div class="md exam-steps">${mdHtml(i.steps)}</div>` : "") +
          `</li>`,
    )
    .join("");
  const missed = (r.missed ?? []).length;
  return (
    `<section class="card"><h2>${esc(m.title)}</h2>` +
    head +
    `<table><thead><tr><th>topic</th><th>score</th></tr></thead><tbody>${rows}</tbody></table>` +
    said +
    unread +
    `<ol class="exam-review">${each}</ol>` +
    `<div class="row">` +
    (missed ? `<button type="button" class="btn btn-primary" data-act="retry">Retry the ${missed} missed ${missed === 1 ? "question" : "questions"}</button>` : "") +
    (missed && state?.llm === true
      ? `<button type="button" class="btn" data-act="vary">Make variants of the ${missed} missed ${missed === 1 ? "question" : "questions"}</button>`
      : "") +
    `<button type="button" class="btn" data-act="back">Back to tests</button></div></section>`
  );
}

export function html(state, extra = {}) {
  if (!extra?.exam) return '<p class="muted">loading…</p>';
  const m = extra.mock;
  if (openId == null || !m) return overview(extra.exam);
  if (m.status === "ready") return readyView(m);
  if (m.status === "running") return runningView(m);
  if (m.status === "to mark") return toMarkView(m);
  return resultHtml(m, state);
}

function tick() {
  const els = document.querySelectorAll("[data-left]");
  if (!els.length || leftS == null) {
    clearInterval(ticker);
    ticker = null;
    return;
  }
  const now = leftS - Math.round((Date.now() - received) / 1000);
  for (const el of els) el.textContent = clock(now);
}

export function after(root) {
  if (!root) return;
  if (root.querySelector?.("[data-left]") && ticker == null && typeof setInterval === "function") {
    ticker = setInterval(tick, 1000);
  }
  if (hasMath(root.textContent ?? "")) for (const el of root.querySelectorAll(".md")) typeset(el);
}

async function saveDraft(ctx) {
  if (!draft || openId == null || draft.mock !== openId) return;
  const body = { confidence: draft.confidence };
  if (draft.dontKnow) body.dont_know = true;
  else body.answer = draft.answer;
  await ctx.api("POST", `/api/mocks/${openId}/items/${draft.pos}`, body);
}

function blanks(m) {
  return (m?.items ?? []).filter((i) => {
    if (i.void) return false;
    if (draft && draft.pos === i.pos) return !draft.dontKnow && !String(draft.answer ?? "").trim();
    return !i.dont_know && !String(i.answer ?? "").trim();
  }).length;
}

export const actions = {
  async create(data, ctx) {
    const body = {};
    if (data.paper) body.paper_id = Number(data.paper);
    else {
      body.course = data.course;
      body.n = Number(data.n || 10);
    }
    if (data.minutes) body.minutes = Number(data.minutes);
    const made = await ctx.api("POST", "/api/mocks", body);
    if (made?.id) {
      openId = made.id;
      pos = 1;
      draft = null;
    }
  },
  async open(data) {
    openId = Number(data.id);
    pos = 1;
    draft = null;
  },
  async back() {
    openId = null;
    draft = null;
  },
  async start(_data, ctx) {
    await ctx.api("POST", `/api/mocks/${openId}/start`, {});
  },
  async save(_data, ctx) {
    await saveDraft(ctx);
  },
  async next(_data, ctx) {
    await saveDraft(ctx);
    pos += 1;
    draft = null;
  },
  async prev(_data, ctx) {
    await saveDraft(ctx);
    pos = Math.max(1, pos - 1);
    draft = null;
  },
  async finish(_data, ctx) {
    const m = lastMock ?? (await ctx.api("GET", `/api/mocks/${openId}`));
    const n = blanks(m);
    if (n && !ctx.confirm(`finish the test? ${n === 1 ? "1 question is" : `${n} questions are`} blank`)) return;
    await saveDraft(ctx);
    await ctx.api("POST", `/api/mocks/${openId}/finish`, {});
    draft = null;
  },
  async mark(data, ctx) {
    await ctx.api("POST", `/api/mocks/${openId}/items/${Number(data.pos)}/mark`, { got: Number(data.got) });
  },
  async retry(_data, ctx) {
    const made = await ctx.api("POST", `/api/mocks/${openId}/retry`, {});
    if (made?.id) {
      openId = made.id;
      pos = 1;
      draft = null;
    }
  },
  async vary(_data, ctx) {
    const done = await ctx.api("POST", `/api/mocks/${openId}/vary`, {});
    if (done) ctx.toast?.(`${plural(done.queued, "job")} queued: they run within today's budget`);
  },
  async retireQuestion(data, ctx) {
    if (!ctx.confirm(`Retire question #${Number(data.id)}? Tests stop using it (undo: pm q restore ${Number(data.id)}).`)) return;
    await ctx.api("POST", `/api/questions/${Number(data.id)}/retire`, { reason: data.reason });
  },
  async importNote(data, ctx) {
    const done = await ctx.api("POST", "/api/questions/import", { path: data.path, topic_id: Number(data.topic) });
    if (done) ctx.toast?.(`added ${plural(done.added, "question")}${done.skipped ? ` (${done.skipped} already there)` : ""}`);
  },
};

// test hooks: the screen's module state
export function _set(state) {
  if ("openId" in state) openId = state.openId;
  if ("pos" in state) pos = state.pos;
  if ("draft" in state) draft = state.draft;
  if ("mock" in state) lastMock = state.mock;
  if ("leftS" in state) leftS = state.leftS;
}
