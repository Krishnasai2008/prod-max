// Stats page (/stats/, docs/stats.md): everything pm logs on the laptop (`pm stats --push` -> /api/pm in
// functions/_middleware.js), next to this site's own study clock. Needs study.js (load, bar) and today.js
// (heatCells, streakOf, level, fmt, esc, ...) loaded first. Writes nothing to localStorage.

const PM_DAYS = 28;  // window for the time totals and the sparklines
const pmDay = (pm, d) => pm?.days?.[dayOf(d)];
const pct = p => `${Math.round(p * 100)}%`;
const mins = m => fmt(m * 60e3);
const txt = v => esc(String(v ?? ""));
const hint = s => `<p class="study-hint">${s}</p>`;
const lastDays = (n, now) => [...Array(n)].map((_, i) => shift(now, i - n + 1));  // oldest first

function spark(values, label) {  // a tiny line chart; scaled to its max
  if (values.length < 2) return "";
  const top = Math.max(...values, 1), step = 120 / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(31 - 30 * v / top).toFixed(1)}`).join(" ");
  return `<svg class="study-spark" viewBox="0 0 120 32" preserveAspectRatio="none" role="img" aria-label="${txt(label)}"><polyline points="${pts}"/></svg>`;
}

function barRows(pairs, show) {  // [[label, value]] as the home page's labelled bars
  const top = Math.max(...pairs.map(p => p[1]), 1);
  return pairs.map(([k, v]) => `<div class="study-row"><span>${txt(k)}</span>${bar(v, top)}<b>${show(v)}</b></div>`).join("");
}

function table(head, rows) {
  return `<table><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead>`
    + `<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function reviewStreak(pm, now) {  // days in a row with a review; today only counts once it has one
  const has = d => (pmDay(pm, d)?.reviews ?? 0) > 0;
  let n = 0, d = has(now) ? now : shift(now, -1);
  while (has(d)) { n++; d = shift(d, -1); }
  return n;
}

const sorted = obj => Object.entries(obj ?? {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
const days = n => `${n} ${n === 1 ? "day" : "days"}`;

function pmStatsHtml(pm, notes, now) {
  // pm's `study` is every clock with the overlap counted once, so it wins over `min` (the timer alone); this browser's
  // clock still shows through for reading since the last push. A push from an older pm has only `min`, and then a day
  // is the larger clock, never the sum. Uses nothing new from today.js, so a cached older copy of it still works.
  const msOf = d => Math.max(sum(notes[dayOf(d)]), (pmDay(pm, d)?.study != null ? Number(pmDay(pm, d).study) || 0 : pmDay(pm, d)?.min ?? 0) * 60e3);
  const today = msOf(now), streak = streakOf(msOf, now);
  let html = `
    <div class="study-tiles">
      <div><small>Streak (2h+ a day)</small><b>🔥 ${days(streak)}</b></div>
      <div><small>Review streak</small><b>${days(pm ? reviewStreak(pm, now) : 0)}</b></div>
      <div><small>Today</small><b data-level="${level(today)}">${fmt(today)}</b></div>
      <div><small>Crunch risk</small><b>${pm ? pct(pm.deadlines.crunch) : "—"}</b></div>
    </div>
    <div class="study-heat-wrap"><div class="study-heat">${heatCells(msOf, now)}</div></div>
    <p class="study-legend"><i data-level="some"></i> under 2h <i data-level="green"></i> 2h+ <i data-level="orange"></i> 4h+ <i data-level="red"></i> 6h+</p>`;
  if (!pm) return html + hint("No pm data yet. Run <code>pm stats --push</code> on your laptop.");

  const span = lastDays(PM_DAYS, now).map(d => pmDay(pm, d) ?? {});
  const total = key => span.reduce((a, d) => a + (d[key] ?? 0), 0);
  const { time, estimates: est, deadlines: dl, study, bugs } = pm;

  html += `<h2>Time <small>last ${PM_DAYS} days</small></h2>`;
  if (!total("min")) html += hint("No timed work yet: <code>pm start</code> / <code>pm log</code>.");
  else html += `<p class="study-label">By course</p>${barRows(sorted(time.by_course), mins)}
    <p class="study-label">By kind</p>${barRows(sorted(time.by_kind), mins)}
    <p class="study-label">Deep vs shallow</p>${barRows(sorted(time.by_energy), mins)}
    ${hint(`${total("deep") ? pct(total("peak") / total("deep")) : "0%"} of deep work in your peak hours (${txt(pm.settings.peak)})`)}`;

  html += `<h2>Estimates</h2>`;
  if (!est.kinds.length) html += hint("Finish a few tasks with logged time to see how far off your estimates are.");
  else html += est.kinds.map(k => `<div class="study-row"><span>${txt(k.kind)}</span><b>×${Number(k.median).toFixed(2)}</b><small>n=${txt(k.n)}</small></div>`).join("")
    + spark(est.history.map(h => h.ratio), "actual ÷ estimate, oldest to newest")
    + hint("×1.00 = spot on; above 1 = it took longer than you guessed.");

  html += `<h2>Deadlines</h2>`;
  html += dl.open.length
    ? table(["Task", "Due", "Late", "Start by"], dl.open.map(t => [
        txt(t.title) + (t.course ? ` <small>${txt(t.course)}</small>` : ""), txt(t.due), pct(t.p_late),
        t.behind ? `<b>${txt(t.start_by)} · BEHIND</b>` : txt(t.start_by)]))
    : hint("Nothing open with a due date.");
  if (dl.on_time + dl.late) html += hint(`Finished on time ${dl.on_time} · late ${dl.late}`);

  html += `<h2>Study</h2>`;
  if (!study.reviews && !study.topics.length) html += hint("No topics or reviews yet: <code>pm topic add</code>, <code>pm review</code>.");
  else {
    html += hint(`${study.reviews} reviews · Brier ${study.brier == null ? "—" : Number(study.brier).toFixed(3)} (0 is perfect, 0.25 is guessing) · ${study.due_now} due now`);
    if (study.bins.length) html += table(["You said", "Recalled", "Reviews"], study.bins.map(b => [`${b.lo}–${b.hi}%`, pct(b.recalled), txt(b.n)]));
    if (study.topics.length) html += `<p class="study-label">Mastery</p>` + study.topics.map(t =>
      `<div class="study-row"><span>${txt(t.name)}${t.exam ? ` <small>exam ${txt(t.exam)}</small>` : ""}</span>${bar(t.mastery * 100, 100)}<b>${pct(t.mastery)}</b></div>`).join("");
    html += spark(span.map(d => d.reviews ?? 0), `reviews per day, last ${PM_DAYS} days`);
  }

  html += `<h2>Code issues</h2>`;
  if (!(bugs.fixed + bugs.open + bugs.abandoned)) html += hint("No bugs logged yet: run builds and tests through <code>pm run -- …</code>.");
  else {
    html += hint(`${bugs.fixed} fixed · ${bugs.open} open · ${bugs.abandoned} abandoned · ${mins(bugs.lost_min)} lost`);
    if (bugs.bursts.length) html += `<p><b>Burst:</b> ${bugs.bursts.map(([t, n]) => `${txt(t)} ×${n}`).join(", ")} in 7 days</p>`;
    const tags = [...bugs.tags, ...(bugs.untagged ? [["untagged", bugs.untagged]] : [])];
    if (tags.length) html += `<p class="study-label">Tags</p>` + barRows(tags, n => String(n));
    html += spark(span.map(d => d.fails ?? 0), `failed runs per day, last ${PM_DAYS} days`);
    html += table(["Bug", "Status", "Fails", "Lost", "Tags"], bugs.recent.map(b => [
      `#${txt(b.id)} ${txt(b.prog)} <small>${txt(b.opened)}</small>`, txt(b.status), txt(b.fails), mins(b.lost_min), b.tags.map(txt).join(", ")]));
  }

  const age = now - new Date(pm.generated);  // laptop and phone clocks can disagree: a "future" push is just now
  return html + hint(`updated ${age < 60e3 ? "just now" : age < 48 * H ? fmt(age) + " ago" : days(Math.floor(age / (24 * H))) + " ago"}`);
}

async function pmPage() {
  const slot = document.querySelector(".md-content .md-typeset div.study-pm");
  if (!slot) return;
  const res = await fetch("/api/pm", { cache: "no-store" }).catch(() => null);
  const pm = res?.ok ? await res.json().catch(() => null) : null;
  slot.innerHTML = pmStatsHtml(pm?.version === 1 ? pm : null, load(TIME_KEY, {}), new Date());
  const heat = slot.querySelector(".study-heat-wrap");
  if (heat) heat.scrollLeft = heat.scrollWidth;  // newest weeks in view on small screens
}

if (typeof document$ !== "undefined") document$.subscribe(pmPage);  // after today.js: runs again after instant page switches
else document.addEventListener("DOMContentLoaded", pmPage);
