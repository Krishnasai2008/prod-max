import { esc } from "./lib.js";

const WEEKS = 26;
const H = 3600e3;

export const LEVELS = [
  [6, "red"],
  [4, "orange"],
  [2, "green"],
];

const pad = (n) => String(n).padStart(2, "0");

export function dayOf(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function shift(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

export function monday(date) {
  return shift(date, -((date.getDay() + 6) % 7));
}

export function level(ms) {
  return LEVELS.find(([hours]) => ms >= hours * H)?.[1] ?? (ms >= 60e3 ? "some" : "none");
}

export function streakOf(msOf, now) {
  const floor = LEVELS[LEVELS.length - 1][0] * H;
  let n = 0;
  let date = now;
  if (msOf(date) < floor) date = shift(date, -1);
  while (msOf(date) >= floor) {
    n++;
    date = shift(date, -1);
  }
  return n;
}

export function heatCells(msOf, now) {
  const first = shift(monday(now), -7 * (WEEKS - 1));
  let cells =
    `<span></span>` +
    ["Mon", "", "Wed", "", "Fri", "", ""].map((day) => `<span>${day}</span>`).join("");
  for (let week = 0; week < WEEKS; week++) {
    const start = shift(first, 7 * week);
    const month = [...Array(7)]
      .map((_, index) => shift(start, index))
      .find((date) => date.getDate() === 1);
    cells += `<span>${week === 0 || month ? (month ?? start).toLocaleString("en", { month: "short" }) : ""}</span>`;
    for (let index = 0; index < 7; index++) {
      const date = shift(start, index);
      const ms = msOf(date);
      cells +=
        date > now
          ? "<i hidden></i>"
          : `<i data-level="${level(ms)}" title="${date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}: ${fmt(ms)}"></i>`;
    }
  }
  return cells;
}

function fmt(ms) {
  const minutes = Math.floor(ms / 60e3);
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${pad(minutes % 60)}m`;
}

export function spark(values, label) {
  if (values.length < 2) return "";
  const top = Math.max(...values, 1);
  const step = 120 / (values.length - 1);
  const points = values
    .map((value, index) => `${(index * step).toFixed(1)},${(31 - (30 * value) / top).toFixed(1)}`)
    .join(" ");
  return (
    `<svg class="study-spark" viewBox="0 0 120 32" preserveAspectRatio="none" role="img" aria-label="${esc(label)}">` +
    `<polyline points="${points}"/></svg>`
  );
}

function bar(value, max) {
  const top = Math.max(Number(max) || 0, 1);
  const width = Math.max(0, Math.min(100, ((Number(value) || 0) / top) * 100));
  return `<div class="bar study-bar" aria-hidden="true"><span style="width:${width.toFixed(1)}%"></span></div>`;
}

export function barRows(pairs, show) {
  const top = Math.max(...pairs.map((pair) => pair[1]), 1);
  return pairs
    .map(
      ([key, value]) =>
        `<div class="study-row"><span>${esc(key)}</span>${bar(value, top)}<b>${show(value)}</b></div>`,
    )
    .join("");
}

export function table(head, rows, labels = []) {
  const cell = (value, index) =>
    `<td${labels[index] ? ` data-label="${esc(labels[index])}"` : ""}>${value}</td>`;
  return (
    `<table><thead><tr>${head.map((value) => `<th>${value}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((row) => `<tr>${row.map(cell).join("")}</tr>`).join("")}</tbody></table>`
  );
}
