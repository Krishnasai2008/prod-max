import { esc, pct } from "./lib.js";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const DAY_MS = 86400000;
const ROW = 28;
const TOP = 24;
const LABEL = 170;
const RIGHT = 16;
const MIN_PLOT = 220;

let view = { hours: null, skip: 0 };
let current = null;

function dayMs(iso) {
  const [year, month, day] = String(iso).split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function isoOf(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function shift(ms, days) {
  return ms + days * DAY_MS;
}

function daysBetween(from, to) {
  return Math.round((to - from) / DAY_MS);
}

function shortDate(iso) {
  if (!iso) return "-";
  const date = new Date(dayMs(iso));
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

function numberText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value ?? "");
  return Number.isInteger(number) ? String(number) : number.toFixed(1);
}

function hoursText(value) {
  return `${numberText(value)} h a day`;
}

function skipText(value) {
  const days = Math.max(0, Math.trunc(Number(value) || 0));
  if (days === 0) return "start today";
  return `after ${days} lost ${days === 1 ? "day" : "days"}`;
}

function lateText(value) {
  const days = Number(value) || 0;
  return `${numberText(days)} ${days === 1 ? "day" : "days"}`;
}

function levelOf(pLate) {
  const p = Number(pLate) || 0;
  if (p < 0.2) return "green";
  if (p < 0.5) return "orange";
  return "red";
}

function query() {
  const parts = [];
  if (view.hours !== null) parts.push(`hours=${view.hours}`);
  if (view.skip) parts.push(`skip=${view.skip}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

// the input hook keeps view in step with the sliders; the DOM value can be clamped by the range
// (an hours_per_day of 14 shows as 12 on an older range), so never read it back from there
function defaultSliders() {
  return { hours: view.hours ?? current?.set_hours ?? 4, skip: view.skip ?? 0 };
}

export let sliders = defaultSliders;

export function setSliders(fn) {
  sliders = fn ?? defaultSliders;
}

export async function load(ctx) {
  const risk = await ctx.api("GET", `/api/risk${query()}`);
  current = risk;
  if (view.hours === null) view.hours = risk.set_hours;
  return { risk };
}

function control(name, label, min, max, step, value, readout) {
  const id = `risk-${name}`;
  return (
    `<div class="risk-control" data-control="${name}">` +
    `<label for="${id}">${esc(label)}</label>` +
    `<div class="row risk-slider">` +
    `<input id="${id}" type="range" name="${name}" data-act="whatif" ` +
    `min="${min}" max="${max}" step="${step}" value="${esc(value)}">` +
    `<output id="${id}-out" for="${id}">${esc(readout)}</output>` +
    `</div>` +
    `</div>`
  );
}

export function html(_state, extra) {
  const risk = extra?.risk;
  if (!risk) return '<p class="muted">loading…</p>';
  const hours = view.hours ?? risk.set_hours;
  const skip = view.skip ?? 0;
  // half-hour steps, unless the saved setting is finer (0.1 to 16 is allowed) and the slider would misstate it
  const fine = Number.isInteger(Number(risk.set_hours) * 2) ? "0.5" : "0.1";
  return (
    `<section class="card risk-controls" aria-label="what-if">` +
    control("hours", "hours a day", fine, "16", fine, hours, hoursText(hours)) +
    control("skip", "lost days", "0", "14", "1", skip, skipText(skip)) +
    `</section>` +
    `<div id="risk-out">${resultsHtml(risk)}</div>`
  );
}

export function input(event) {
  const field = event?.target;
  if (!field || (field.name !== "hours" && field.name !== "skip")) return false;
  const value = Number(field.value);
  if (field.name === "hours") view.hours = value;
  else view.skip = value;
  const text = field.name === "hours" ? hoursText(value) : skipText(value);
  const output =
    field.closest?.(".risk-control")?.querySelector?.("output") ??
    globalThis.document?.getElementById?.(`risk-${field.name}-out`);
  if (output) output.textContent = text;
  return false;
}

function table(tasks) {
  const rows = tasks
    .map((task) => {
      const days = Number(task.late_days) || 0;
      const late = days > 0
        ? `<td data-label="if late" title="if late: about ${esc(lateText(days))}">about ${esc(lateText(days))}</td>`
        : `<td data-label="if late" title="if late: none">-</td>`;
      return (
        `<tr>` +
        `<td>${esc(task.title)}</td>` +
        `<td data-label="due">${esc(task.due ?? "-")}</td>` +
        `<td data-label="late">${esc(pct(task.p_late))}</td>` +
        `<td data-label="start by">${esc(task.start_by ?? "-")}` +
        (task.behind ? ' <span class="tag">BEHIND</span>' : "") +
        `</td>` +
        `<td data-label="likely finish">${esc(task.finish_p50 ?? "-")}</td>` +
        `<td data-label="worst case">${esc(task.finish_p95 ?? "-")}</td>` +
        late +
        `</tr>`
      );
    })
    .join("");
  return (
    `<div class="risk-table"><table>` +
    `<thead><tr><th>task</th><th>due</th><th>late %</th><th>start by</th>` +
    `<th>likely finish</th><th>worst case</th><th>if late</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`
  );
}

export function timeline(risk) {
  const tasks = risk?.tasks ?? [];
  const today = dayMs(risk?.today);
  let start = today;
  let end = today;
  for (const task of tasks) {
    for (const iso of [task.due, task.start_by, task.finish_p50]) {
      if (iso) start = Math.min(start, dayMs(iso));
    }
    if (task.due) end = Math.max(end, dayMs(task.due));
    if (task.finish_p95) end = Math.max(end, dayMs(task.finish_p95));
  }
  end = shift(end, 1);
  const span = Math.max(1, daysBetween(start, end));
  const plot = Math.max(MIN_PLOT, span * 18);
  const width = LABEL + plot + RIGHT;
  const height = TOP + Math.max(1, tasks.length) * ROW + 6;
  const xAt = (ms) => LABEL + (daysBetween(start, ms) / span) * plot;
  const xOf = (iso) => (iso ? xAt(dayMs(iso)) : LABEL);

  let ticks = "";
  for (let ms = start; ms <= end; ms = shift(ms, 7)) {
    const x = xAt(ms);
    ticks +=
      `<line class="tick" x1="${x}" y1="${TOP}" x2="${x}" y2="${height}"></line>` +
      `<text class="tick-label" x="${x}" y="${TOP - 8}" text-anchor="middle">` +
      `${esc(shortDate(isoOf(ms)))}</text>`;
  }

  const todayX = xAt(today);
  const todayMark =
    `<line class="today" x1="${todayX}" y1="${TOP}" x2="${todayX}" y2="${height}"></line>`;

  const rows = tasks
    .map((task, index) => {
      const y = TOP + index * ROW + ROW / 2;
      const fullTitle = String(task.title ?? "");
      const label = [...fullTitle].slice(0, 24).join("");
      const level = levelOf(task.p_late);
      const title =
        `${fullTitle}: due ${shortDate(task.due)}, likely ${shortDate(task.finish_p50)}, ` +
        `worst case ${shortDate(task.finish_p95)}, late ${pct(task.p_late)}`;
      const parts = [
        `<g class="risk-row">`,
        `<title>${esc(title)}</title>`,
        `<text class="risk-label" x="4" y="${y + 4}">${esc(label)}</text>`,
      ];
      if (task.finish_p50 || task.finish_p95) {
        const x1 = xOf(task.finish_p50 ?? task.finish_p95);
        const x2 = Math.max(x1 + 2, xOf(task.finish_p95 ?? task.finish_p50));
        parts.push(
          `<rect class="risk-bar" data-level="${level}" x="${x1}" y="${y - 7}" ` +
          `width="${x2 - x1}" height="14" rx="4"></rect>`,
        );
      }
      if (task.due) {
        const dueX = xOf(task.due);
        parts.push(
          `<line class="risk-due" x1="${dueX}" y1="${y - 10}" x2="${dueX}" y2="${y + 10}"></line>`,
        );
      }
      if (task.start_by) {
        const startX = Math.max(LABEL, xOf(task.start_by));
        parts.push(
          `<polygon class="risk-startby" points="${startX},${y - 6} ` +
          `${startX - 5},${y + 4} ${startX + 5},${y + 4}"></polygon>`,
        );
      }
      parts.push(`</g>`);
      return parts.join("");
    })
    .join("");

  return (
    `<svg role="img" aria-label="risk timeline: likely and worst-case finish against each due date" ` +
    `viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">` +
    ticks +
    rows +
    todayMark +
    `</svg>`
  );
}

export function resultsHtml(risk) {
  if (!risk) return "";
  const tasks = risk.tasks ?? [];
  const base =
    Number(risk.hours) === Number(risk.set_hours) && Number(risk.skip ?? 0) === 0;
  const parts = [
    `<p class="risk-crunch"><b>crunch risk ${esc(pct(risk.crunch))}</b>` +
      (base
        ? ""
        : ` <span class="muted">(${esc(pct(risk.base_crunch))} at ` +
          `${esc(hoursText(risk.set_hours))} starting today)</span>`) +
      `</p>`,
    risk.start_queue_by
      ? `<p>start the queue by ${esc(risk.start_queue_by)}</p>`
      : `<p class="muted">nothing with a due date</p>`,
  ];
  if (tasks.length) {
    parts.push(`<div class="risk-chart">${timeline(risk)}</div>`);
    parts.push(table(tasks));
  }
  const undated = Number(risk.undated) || 0;
  if (undated > 0) {
    parts.push(
      `<p class="muted">${esc(undated)} task${undated === 1 ? " has" : "s have"} ` +
      `no due date and ${undated === 1 ? "is" : "are"} not simulated</p>`,
    );
  }
  const use =
    Number(risk.hours) !== Number(risk.set_hours)
      ? `<button type="button" class="btn" data-act="apply" ` +
        `data-value="${esc(risk.hours)}">Use ${esc(hoursText(risk.hours))}</button>`
      : "";
  parts.push(
    `<div class="row risk-actions">${use}` +
    `<button type="button" class="btn" data-act="reset">Reset</button></div>`,
  );
  return parts.join("");
}

async function whatif(_data, ctx) {
  const picked = sliders(globalThis.document);
  view = { hours: picked.hours, skip: picked.skip };
  const risk = await ctx.api(
    "GET",
    `/api/risk?hours=${view.hours}&skip=${view.skip}`,
  );
  current = risk;
  ctx.patch("risk-out", resultsHtml(risk));
}

async function apply(data, ctx) {
  const value = String(data?.value ?? view.hours ?? current?.hours ?? "");
  if (!ctx.confirm(`Change your hours a day to ${value}? Every forecast and today's plan use it.`)) return;
  await ctx.api("POST", "/api/settings", { key: "hours_per_day", value });
  view.hours = null;
}

function reset() {
  view = { hours: null, skip: 0 };
}

export const actions = { whatif, apply, reset };
