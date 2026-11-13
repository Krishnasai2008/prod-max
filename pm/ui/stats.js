import { esc, fmtMin, pct } from "./lib.js";
import { barRows, dayOf, heatCells, level, shift, spark, streakOf, table } from "./charts.js";

const PM_DAYS = 28;

const pmDay = (pm, date) => pm?.days?.[dayOf(date)];
const txt = (value) => esc(String(value ?? ""));
const hint = (text) => `<p class="study-hint">${text}</p>`;
const lastDays = (n, now) =>
  [...Array(n)].map((_, index) => shift(now, index - n + 1));
const sorted = (object) =>
  Object.entries(object ?? {})
    .filter(([, value]) => value > 0)
    .sort((a, b) => b[1] - a[1]);
const days = (n) => `${n} ${n === 1 ? "day" : "days"}`;
const mins = (minutes) => fmtMin(minutes);

function reviewStreak(pm, now) {
  const has = (date) => (pmDay(pm, date)?.reviews ?? 0) > 0;
  let n = 0;
  let date = has(now) ? now : shift(now, -1);
  while (has(date)) {
    n++;
    date = shift(date, -1);
  }
  return n;
}

function timeHtml(time, span, peak) {
  const total = (key) => span.reduce((sum, day) => sum + (day[key] ?? 0), 0);
  let html = `<h2>Time <small>last ${PM_DAYS} days</small></h2>`;
  if (!total("min")) {
    return html + hint("No timed work yet: <code>pm start</code> / <code>pm log</code>.");
  }
  html +=
    `<p class="study-label">By course</p>${barRows(sorted(time.by_course), mins)}` +
    `<p class="study-label">By kind</p>${barRows(sorted(time.by_kind), mins)}` +
    `<p class="study-label">Deep vs shallow</p>${barRows(sorted(time.by_energy), mins)}` +
    hint(
      `${total("deep") ? pct(total("peak") / total("deep")) : "0%"} of deep work in your peak hours (${txt(peak)})`,
    );
  return html;
}

function estimatesHtml(estimates) {
  const kinds = estimates.kinds ?? [];
  let html = `<h2>Estimates</h2>`;
  if (!kinds.length) {
    return (
      html +
      hint("Finish a few tasks with logged time to see how far off your estimates are.")
    );
  }
  html += kinds
    .map(
      (kind) =>
        `<div class="study-row"><span>${txt(kind.kind)}</span><b>×${Number(kind.median).toFixed(2)}</b><small>n=${txt(kind.n)}</small></div>`,
    )
    .join("");
  html += spark(
    (estimates.history ?? []).map((entry) => entry.ratio),
    "actual ÷ estimate, oldest to newest",
  );
  return html + hint("×1.00 = spot on; above 1 = it took longer than you guessed.");
}

function deadlinesHtml(deadlines) {
  const open = deadlines.open ?? [];
  let html = `<h2>Deadlines</h2>`;
  html += open.length
    ? table(
        ["Task", "Due", "Late", "Start by"],
        open.map((task) => [
          txt(task.title) + (task.course ? ` <small>${txt(task.course)}</small>` : ""),
          txt(task.due),
          pct(task.p_late),
          task.behind ? `<b>${txt(task.start_by)} · BEHIND</b>` : txt(task.start_by),
        ]),
        ["task", "due", "late", "start by"],
      )
    : hint("Nothing open with a due date.");
  const onTime = deadlines.on_time ?? 0;
  const late = deadlines.late ?? 0;
  if (onTime + late) html += hint(`Finished on time ${txt(onTime)} · late ${txt(late)}`);
  return html;
}

function studyHtml(study, span) {
  const topics = study.topics ?? [];
  const reviews = study.reviews ?? 0;
  let html = `<h2>Study</h2>`;
  if (!reviews && !topics.length) {
    return (
      html +
      hint("No topics or reviews yet: <code>pm topic add</code>, <code>pm review</code>.")
    );
  }
  html += hint(
    `${txt(reviews)} reviews · Brier ${study.brier == null ? "—" : Number(study.brier).toFixed(3)} (0 is perfect, 0.25 is guessing) · ${txt(study.due_now ?? 0)} due now`,
  );
  const bins = study.bins ?? [];
  if (bins.length) {
    html += table(
      ["You said", "Recalled", "Reviews"],
      bins.map((bin) => [`${txt(bin.lo)}–${txt(bin.hi)}%`, pct(bin.recalled), txt(bin.n)]),
      ["you said", "recalled", "reviews"],
    );
  }
  if (topics.length) {
    html +=
      `<p class="study-label">Mastery</p>` +
      topics
        .map(
          (topic) =>
            `<div class="study-row"><span>${txt(topic.name)}${topic.exam ? ` <small>exam ${txt(topic.exam)}</small>` : ""}</span>${masteryBar(topic.mastery)}<b>${pct(topic.mastery)}</b></div>`,
        )
        .join("");
  }
  html += spark(
    span.map((day) => day.reviews ?? 0),
    `reviews per day, last ${PM_DAYS} days`,
  );
  return html;
}

function masteryBar(mastery) {
  const value = Math.max(0, Math.min(1, Number(mastery) || 0));
  return `<div class="bar study-bar" aria-hidden="true"><span style="width:${(value * 100).toFixed(1)}%"></span></div>`;
}

function bugsHtml(bugs, span) {
  const fixed = bugs.fixed ?? 0;
  const open = bugs.open ?? 0;
  const abandoned = bugs.abandoned ?? 0;
  let html = `<h2>Code issues</h2>`;
  if (!(fixed + open + abandoned)) {
    return (
      html + hint("No bugs logged yet: run builds and tests through <code>pm run -- …</code>.")
    );
  }
  html += hint(
    `${txt(fixed)} fixed · ${txt(open)} open · ${txt(abandoned)} abandoned · ${mins(bugs.lost_min ?? 0)} lost`,
  );
  const bursts = bugs.bursts ?? [];
  if (bursts.length) {
    html += `<p><b>Burst:</b> ${bursts.map(([tag, n]) => `${txt(tag)} ×${txt(n)}`).join(", ")} in 7 days</p>`;
  }
  const tags = [...(bugs.tags ?? []), ...(bugs.untagged ? [["untagged", bugs.untagged]] : [])];
  if (tags.length) html += `<p class="study-label">Tags</p>${barRows(tags, (n) => esc(String(n)))}`;
  html += spark(
    span.map((day) => day.fails ?? 0),
    `failed runs per day, last ${PM_DAYS} days`,
  );
  html += table(
    ["Bug", "Status", "Fails", "Lost", "Tags"],
    (bugs.recent ?? []).map((bug) => [
      `#${txt(bug.id)} ${txt(bug.prog)} <small>${txt(bug.opened)}</small>`,
      txt(bug.status),
      txt(bug.fails),
      mins(bug.lost_min),
      (bug.tags ?? []).map(txt).join(", "),
    ]),
    ["bug", "status", "fails", "lost", "tags"],
  );
  return html;
}

export function statsHtml(pm, notes = {}, now, lh = {}) {
  // `study` is every clock with the overlap counted once, per calendar day: it wins when the day has it.
  // Without it (an older summary) a day is the largest clock, never a sum.
  const msOf = (date) => {
    const day = pmDay(pm, date);
    if (day?.study != null) return Math.max(0, Number(day.study) || 0) * 60e3;
    return Math.max(Number(notes?.[dayOf(date)]) || 0, Number(lh?.[dayOf(date)]) || 0, day?.min ?? 0) * 60e3;
  };
  const today = msOf(now);
  const streak = streakOf(msOf, now);
  let html =
    `<div class="study-tiles">` +
    `<div><small>Streak (2h+ a day)</small><b>🔥 ${days(streak)}</b></div>` +
    `<div><small>Review streak</small><b>${days(pm ? reviewStreak(pm, now) : 0)}</b></div>` +
    `<div><small>Today</small><b data-level="${level(today)}">${mins(today / 60e3)}</b></div>` +
    `<div><small>Crunch risk</small><b>${pm ? pct(pm.deadlines?.crunch ?? 0) : "—"}</b></div>` +
    `</div>` +
    `<div class="study-heat-wrap"><div class="study-heat">${heatCells(msOf, now)}</div></div>` +
    `<p class="study-legend"><i data-level="some"></i> under 2h <i data-level="green"></i> 2h+ <i data-level="orange"></i> 4h+ <i data-level="red"></i> 6h+</p>`;
  if (!pm) return html + hint("Nothing logged yet: start a task from Today.");

  const span = lastDays(PM_DAYS, now).map((date) => pmDay(pm, date) ?? {});
  html += timeHtml(pm.time ?? {}, span, pm.settings?.peak ?? "");
  html += estimatesHtml(pm.estimates ?? {});
  html += deadlinesHtml(pm.deadlines ?? {});
  html += studyHtml(pm.study ?? {}, span);
  html += bugsHtml(pm.bugs ?? {}, span);
  return html;
}

export async function load(ctx) {
  return { stats: await ctx.api("GET", "/api/stats") };
}

export function html(state, extra = {}) {
  const stats = extra?.stats;
  if (!stats) return '<p class="muted">loading…</p>';
  return `<div class="study-pm card">${statsHtml(stats, stats.notes ?? {}, new Date(state.now), stats.lh ?? {})}</div>`;
}

export function after(root) {
  const heat = root.querySelector(".study-heat-wrap");
  if (heat) heat.scrollLeft = heat.scrollWidth;
}

export const actions = {};
