import { esc, fmtClock, fmtMin, pct, relDay } from "./lib.js";

function findTask(state, id) {
  return (state.tasks ?? []).find((task) => task.id === id) ?? null;
}

function dateOf(state) {
  return String(state.now ?? "").slice(0, 10);
}

function firstPlanTask(state) {
  for (const item of state.today?.plan ?? []) {
    const task = findTask(state, item.task_id);
    if (task) return { item, task };
  }
  return null;
}

function riskLevel(pLate) {
  if (pLate < 0.2) return "green";
  if (pLate < 0.5) return "orange";
  return "red";
}

function riskLine(task) {
  if (task.p_late == null) return "";
  const level = riskLevel(Number(task.p_late));
  const percent = esc(pct(task.p_late));
  return (
    `<div class="row">` +
    `<div class="bar" data-level="${level}" aria-hidden="true">` +
    `<span style="width:${percent}"></span>` +
    `</div>` +
    `<span class="muted">late ${percent}</span>` +
    `</div>`
  );
}

function dueText(task, today) {
  if (task.p_late == null || !task.due) return "";
  return `<span>due ${esc(task.due)} (${esc(relDay(task.due, today))})</span>`;
}

function timer(state) {
  const running = state.running;
  if (!running) {
    const next = firstPlanTask(state);
    if (next) {
      return (
        `<div class="card">` +
        `<button type="button" class="btn btn-primary" data-act="start" data-id="${esc(next.task.id)}">` +
        `Start: ${esc(next.task.title)}` +
        `</button>` +
        `</div>`
      );
    }
    return `<div class="card"><p class="muted">nothing to do — <a href="#/tasks">add a task</a></p></div>`;
  }

  const task = findTask(state, running.task_id);
  const elapsed = Number(running.elapsed_s ?? 0);
  const long = elapsed > 21600;
  const title = task ? task.title : `#${running.task_id}`;
  return (
    `<div class="card">` +
    `<div class="spread">` +
    `<h2>${esc(title)}</h2>` +
    `<span class="clock"><b data-elapsed>${fmtClock(elapsed)}</b></span>` +
    `</div>` +
    (task?.first_step ? `<p class="muted">first step: ${esc(task.first_step)}</p>` : "") +
    (task?.note ? `<p class="muted">where you left off: ${esc(task.note)}</p>` : "") +
    (long ? `<p class="muted">this has run over 6 hours; use "Stop as" if you forgot it</p>` : "") +
    `<form data-act="stop">` +
    `<div class="field">` +
    `<label>pause note <input name="note" maxlength="300" placeholder="where are you leaving off?"></label>` +
    `</div>` +
    `<div class="row">` +
    `<button type="submit" class="btn btn-primary">Stop</button>` +
    `<button type="button" class="btn" data-act="done" data-id="${esc(running.task_id)}">Done</button>` +
    `</div>` +
    `<details${long ? " open" : ""}>` +
    `<summary>Stop as…</summary>` +
    `<div class="field">` +
    `<label>stop as <input name="as" placeholder="e.g. 1h30m"></label>` +
    `</div>` +
    `</details>` +
    `</form>` +
    `</div>`
  );
}

function meter(state) {
  const worked = Number(state.today?.worked_min ?? 0);
  const cap = Number(state.today?.cap_min ?? 0);
  const width = cap > 0 ? Math.min(100, Math.round((100 * worked) / cap)) : 0;
  return (
    `<div class="card">` +
    `<div class="spread">` +
    `<h2>Day</h2>` +
    `<span class="muted">${esc(fmtMin(worked))} of ${esc(fmtMin(cap))}</span>` +
    `</div>` +
    `<div class="bar" role="progressbar" aria-label="worked today" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width}">` +
    `<span style="width:${width}%"></span>` +
    `</div>` +
    peakHint(state) +
    `</div>`
  );
}

function peakHint(state) {
  const hint = state.today?.peak_hint;
  if (!hint) return "";
  return (
    `<p class="muted">your best hours look like ${esc(hint)} ` +
    `<button type="button" class="btn btn-small" data-act="usePeak" data-peak="${esc(hint)}">Use ${esc(hint)}</button></p>`
  );
}

function energyCard(state) {
  if (state.today?.unrated !== true) return "";
  const buttons = [1, 2, 3, 4, 5]
    .map((n) => `<button type="button" class="btn btn-small" data-act="energy" data-energy="${n}">${n}</button>`)
    .join("");
  return `<div class="card"><p>how was your energy?</p><div class="row">${buttons}</div></div>`;
}

function planItem(entry) {
  const task = entry.task;
  const status = task.behind
    ? `<span class="tag">BEHIND</span>`
    : task.start_by && task.start_by === dateOf(entry.state)
      ? `<span class="muted">start today</span>`
      : "";
  const start = task.running
    ? `<button type="button" class="btn btn-small" disabled>running</button>`
    : `<button type="button" class="btn btn-small" data-act="start" data-id="${esc(task.id)}">Start</button>`;
  return (
    `<article class="card">` +
    `<div class="spread">` +
    `<h3>${esc(task.title)}</h3>` +
    `<div class="row">` +
    (task.course ? `<span class="tag">${esc(task.course)}</span>` : "") +
    (task.kind ? `<span class="tag">${esc(task.kind)}</span>` : "") +
    `</div>` +
    `</div>` +
    `<div class="row muted">` +
    `<span>~${esc(fmtMin(entry.item.minutes))} today</span>` +
    dueText(task, dateOf(entry.state)) +
    status +
    `</div>` +
    riskLine(task) +
    (task.first_step ? `<p class="muted">first step: ${esc(task.first_step)}</p>` : "") +
    `<div class="row">` +
    start +
    `<form data-act="log" data-id="${esc(task.id)}">` +
    `<label>log <input name="duration" required></label>` +
    `<button type="submit" class="btn btn-small">Log</button>` +
    `</form>` +
    `<button type="button" class="btn btn-small" data-act="done" data-id="${esc(task.id)}">Done</button>` +
    `</div>` +
    `</article>`
  );
}

function plan(state) {
  const entries = (state.today?.plan ?? [])
    .map((item) => ({ item, task: findTask(state, item.task_id), state }))
    .filter((entry) => entry.task);
  const deep = entries.filter((entry) => entry.task.energy === "deep");
  const shallow = entries.filter((entry) => entry.task.energy !== "deep");
  let out = "";
  if (deep.length) {
    const peak = state.today?.peak;
    const heading = peak ? `Deep work (peak ${peak})` : "Deep work";
    out += `<h2>${esc(heading)}</h2>` + deep.map(planItem).join("");
  }
  if (shallow.length) {
    out += `<h2>Shallow</h2>` + shallow.map(planItem).join("");
  }
  return out;
}

// the opening message, kept for a textarea when the clipboard refuses it
let opening = null;

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function studyCard(state) {
  const rows = [];
  const due = Number(state.reviews_due ?? 0);
  if (due) rows.push(`<a href="#/review">${plural(due, "review", "reviews")} due</a>`);
  const spots = Number(state.spots ?? 0);
  if (spots) rows.push(`<a href="#/spot">${plural(spots, "spot-the-error card", "spot-the-error cards")}</a>`);
  const lh = state.lh ?? {};
  const cards = Number(lh.cards_ready ?? 0);
  if (lh.found && cards) rows.push(`${plural(cards, "card", "cards")} ready in LearnHarness`);
  const tutor = state.tutor;
  if (tutor) {
    const where = `${esc(tutor.course || "-")} / ${esc(tutor.topic)}`;
    rows.push(
      `<span>tutor next: ${where}</span> ` +
        `<button type="button" class="btn" data-act="copyOpening" data-topic="${esc(tutor.topic_id)}">Copy opening message</button> ` +
        `<button type="button" class="btn" data-act="copyOpening" data-topic="${esc(tutor.topic_id)}" data-practice="1">Copy for practice</button>` +
        (opening && opening.topic === String(tutor.topic_id)
          ? `<textarea class="opening" readonly rows="8" aria-label="opening message">${esc(opening.text)}</textarea>`
          : ""),
    );
    rows.push(`<a href="#/practice">practise: ${where}</a>`);
  }
  if (state.exam?.open) rows.push(`<a href="#/exam">a test is in progress</a>`);
  const unsorted = Number(lh.unsorted ?? 0);
  if (lh.found && unsorted) {
    rows.push(`<a href="#/study">${unsorted === 1 ? "1 LearnHarness session has" : `${unsorted} LearnHarness sessions have`} no topic</a>`);
  }
  if (!rows.length) return "";
  return `<section class="card study-card"><h2>Study</h2><ul>${rows.map((r) => `<li>${r}</li>`).join("")}</ul></section>`;
}

export function html(state) {
  if (!state) return "";
  return timer(state) + studyCard(state) + energyCard(state) + meter(state) + plan(state);
}

export function warnLong(answer, ctx) {
  if (answer?.long) {
    ctx.toast(`that ran ${fmtMin(answer.minutes)}; fix it with Stop as next time`);
  }
}

export const actions = {
  async start(data, ctx) {
    const answer = await ctx.api("POST", `/api/tasks/${data.id}/start`, { open: true });
    const opened = Number(answer?.opened ?? 0);
    const skipped = answer?.skipped ?? [];
    if (opened > 0) {
      const line = `opened ${opened} ${opened === 1 ? "link" : "links"}`;
      ctx.toast(skipped.length ? `${line}; ${skipped[0]}` : line);
    } else if (skipped.length) {
      ctx.toast(skipped[0]);
    }
  },

  async energy(data, ctx) {
    await ctx.api("POST", "/api/energy", { energy: Number(data.energy) });
  },

  async usePeak(data, ctx) {
    await ctx.api("POST", "/api/settings", { key: "peak", value: data.peak });
    ctx.toast(`peak set to ${data.peak}`);
  },

  async stop(data, ctx) {
    const body = {};
    if (data.note) body.note = data.note;
    if (data.as) body.as = data.as;
    const answer = await ctx.api("POST", "/api/stop", body);
    warnLong(answer, ctx);
  },

  async log(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/log`, { duration: data.duration });
    ctx.toast?.(`logged ${data.duration} on #${data.id}`);
  },

  async copyOpening(data, ctx) {
    const topic = String(data.topic ?? ctx.state?.tutor?.topic_id ?? "");
    const path = `/api/lh/opening?topic=${encodeURIComponent(topic)}${data.practice === "1" ? "&practice=1" : ""}`;
    const answer = await ctx.api("GET", path);
    if (!answer?.text) return null;
    try {
      await navigator.clipboard.writeText(answer.text);
      opening = null;
      ctx.toast("copied: paste it into a new LearnHarness session");
      return null;
    } catch {
      opening = { topic, text: answer.text };
      return opening.text;
    }
  },

  async done(data, ctx) {
    await ctx.api("POST", `/api/tasks/${data.id}/done`, undefined);
    ctx.toast?.(`#${data.id} done (undo: pm reopen ${data.id})`);
  },
};
