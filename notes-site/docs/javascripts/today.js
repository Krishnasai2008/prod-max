// Today: a to-do list for the day and study stats with a heatmap (home page), a study clock (header,
// top right) and a "+ Today" button on notes. The clock counts by itself while you read here, or runs as
// a stopwatch / Pomodoro timer for study away from the site. Lives in this browser's localStorage only.
// Uses load(), save(), doneSet() and bar() from study.js, which loads first.

const TODO_KEY = "study.todo", TIME_KEY = "study.time", NAMES_KEY = "study.subjects", OPEN_KEY = "study.open",
      CLOCK_KEY = "study.clock", TICK_KEY = "study.tick", ACTIVE_KEY = "study.active";
const LEVELS = [[6, "red"], [4, "orange"], [2, "green"]];  // hours studied in a day -> colour; 2 h+ keeps the streak
const IDLE = 5 * 60e3;  // Auto pauses after 5 min without mouse, keys or scrolling
const POMO = { pomo25: [25, 5], pomo50: [50, 10] };  // minutes of study, minutes of break
const MODES = [["auto", "Auto"], ["watch", "Stopwatch"], ["pomo25", "25 / 5"], ["pomo50", "50 / 10"]];
const NOTES = { auto: "Counts while you read notes here. Pauses after 5 min without scrolling, typing or moving the mouse.",
                watch: "Counting everything, also study away from the site. Press Stopwatch again to go back to Auto." };
const WEEKS = 26, H = 3600e3;

const pad = n => String(n).padStart(2, "0");
const dayOf = (t = new Date()) => `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;  // local date
const fmt = ms => { const m = Math.floor(ms / 60e3); return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${pad(m % 60)}m`; };
const countdown = ms => { const s = Math.ceil(ms / 1000); return `${Math.floor(s / 60)}:${pad(s % 60)}`; };
const sum = day => Object.values(day ?? {}).reduce((a, b) => a + b, 0);
const level = ms => LEVELS.find(([h]) => ms >= h * H)?.[1] ?? (ms >= 60e3 ? "some" : "none");
const shift = (t, days) => { const d = new Date(t); d.setDate(d.getDate() + days); return d; };
const monday = t => shift(t, -((t.getDay() + 6) % 7));
const PAGES = new Set(["stats"]);  // top-level pages that are not subjects: the clock never counts them
const subjectOf = path => { const s = decodeURIComponent(path.split("/")[1] || ""); return PAGES.has(s) ? "" : s; };  // "/poe/exam-prep/x/" -> "poe"
const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const esc = s => s.replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`);

// ---------- Study clock ----------
let lastActive = Date.now(), chip, panel, bells;
for (const e of ["pointermove", "pointerdown", "keydown", "wheel", "scroll", "touchstart"])
  addEventListener(e, () => {
    const now = Date.now();
    if (now - lastActive > 30e3) save(ACTIVE_KEY, now);  // shared with other tabs, for the forgotten-stopwatch stop
    lastActive = now;
  }, { capture: true, passive: true });

const clock = () => load(CLOCK_KEY, { mode: "auto" });
function phase(c, now) {  // Pomodoro: study or break, and the time left in it
  const [work, rest] = POMO[c.mode].map(m => m * 60e3), t = (now - c.start) % (work + rest);
  return t < work ? { study: true, left: work - t } : { study: false, left: work + rest - t };
}

function tick() {
  const now = Date.now(), c = clock(), here = subjectOf(location.pathname);
  // shortcut: a forgotten stopwatch stops after 3 h without you touching the site (that time still counts)
  if (c.mode !== "auto" && now - Math.max(lastActive, load(ACTIVE_KEY, 0)) > 3 * H) return setMode("auto");
  const counting = c.mode === "auto" ? document.visibilityState === "visible" && now - lastActive < IDLE && !!here
                                     : !POMO[c.mode] || phase(c, now).study;
  if (counting) {
    // add the time since any tab last counted, so two open tabs never count twice; the cap keeps a sleeping computer out
    const add = Math.min(now - load(TICK_KEY, 0), c.mode === "auto" ? 1000 : 90e3);
    const log = load(TIME_KEY, {}), day = (log[dayOf()] ??= {}), s = here || "other";
    if (add > 0) { day[s] = (day[s] || 0) + add; save(TIME_KEY, log); }
  }
  if (counting || c.mode !== "auto") save(TICK_KEY, now);
  paintClock(c, now, counting);
}

function setMode(mode) {
  const c = clock();
  if (mode === c.mode) mode = "auto";  // pressing the running timer again stops it
  const next = { mode, start: Date.now() };
  save(CLOCK_KEY, next);
  save(TICK_KEY, next.start);
  try { sessionStorage.setItem("study.bells", next.start); } catch { /* no bells after a reload, that's all */ }
  ring(next);
  tick();
}

function ring(c) {  // Pomodoro bells, put on the audio clock so they ring on time even in a background tab
  bells?.close(); bells = null;
  if (!POMO[c.mode]) return;
  bells = new AudioContext();
  const [work, rest] = POMO[c.mode].map(m => m * 60), since = (Date.now() - c.start) / 1000;
  for (let at = 0, k = 0; at < since + 4 * 3600; k++) {  // shortcut: bells for the next 4 hours only
    at += k % 2 ? rest : work;
    if (at > since) bell(at - since, k % 2 === 1);
  }
}

function bell(delay, up) {  // two soft notes: falling = break time, rising = back to study
  (up ? [660, 880] : [880, 660]).forEach((hz, i) => {
    const o = bells.createOscillator(), g = bells.createGain(), t = bells.currentTime + delay + i * 0.25;
    o.frequency.value = hz;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.3, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.2);
    o.connect(g).connect(bells.destination);
    o.start(t); o.stop(t + 1.3);
  });
}

function clockChip() {
  if (chip?.isConnected) return;
  const search = document.querySelector(".md-header .study-search-btn");
  if (!search) return;
  const home = document.querySelector(".md-header .md-logo")?.href ?? "/";
  const wrap = document.createElement("div");
  wrap.className = "study-clock";
  wrap.innerHTML = `<button type="button" class="study-clock-chip" aria-expanded="false" aria-controls="study-clock-panel"><i></i><em></em><b></b></button>
    <div class="study-clock-panel" id="study-clock-panel" hidden>
      <div class="study-clock-head"><span>Studied today</span><b></b></div>
      <div class="study-clock-modes" role="group" aria-label="Clock mode">${MODES.map(([m, label]) =>
        `<button type="button" data-mode="${m}">${label}</button>`).join("")}</div>
      <p class="study-clock-note"></p>
      <ul class="study-clock-subjects"></ul>
      <a class="study-clock-more" href="${home}#study-stats">Stats and history →</a>
    </div>`;
  [chip, panel] = wrap.children;
  const show = open => { panel.hidden = !open; chip.setAttribute("aria-expanded", open); if (open) tick(); };
  chip.addEventListener("click", () => show(panel.hidden));
  panel.addEventListener("click", e => {
    if (e.target.dataset.mode) setMode(e.target.dataset.mode);
    if (e.target.closest("a")) show(false);
  });
  document.addEventListener("click", e => !wrap.contains(e.target) && show(false));
  document.addEventListener("keydown", e => e.key === "Escape" && show(false));
  (document.querySelector(".study-focus-btn") ?? search).before(wrap);
  const c = clock();
  let mine = null;
  try { mine = sessionStorage.getItem("study.bells"); } catch { /* ignore */ }
  if (POMO[c.mode] && mine === String(c.start)) {  // this tab started the Pomodoro: keep ringing after a reload
    ring(c);
    addEventListener("pointerdown", () => bells?.resume(), { once: true });  // browsers need a click before sound
  }
}

function paintClock(c, now, counting) {
  if (!chip?.isConnected) return;
  const day = load(TIME_KEY, {})[dayOf()] ?? {}, today = sum(day), p = POMO[c.mode] && phase(c, now);
  chip.querySelector("i").textContent = p ? (p.study ? "🍅" : "☕") : c.mode === "watch" ? "⏺" : "⏱";
  chip.querySelector("em").textContent = p ? countdown(p.left) : "";  // Pomodoro countdown, beside today's total
  chip.querySelector("b").textContent = fmt(today);
  chip.dataset.level = level(today);
  chip.classList.toggle("idle", !counting && !p);
  chip.title = p ? `${p.study ? "Study" : "Break"}: ${countdown(p.left)} left · ${fmt(today)} today`
                 : counting ? "Study clock: counting" : "Study clock: paused";
  if (panel.hidden) return;
  panel.querySelector(".study-clock-head b").textContent = fmt(today);
  panel.querySelector(".study-clock-head b").dataset.level = level(today);
  panel.querySelectorAll("[data-mode]").forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === c.mode));
  panel.querySelector(".study-clock-note").textContent = p
    ? `${p.study ? "Study" : "Break"}: ${countdown(p.left)} left. A bell rings at each switch. Press ${MODES.find(m => m[0] === c.mode)[1]} again to stop.`
    : NOTES[c.mode] ?? NOTES.auto;
  const names = load(NAMES_KEY, {});
  panel.querySelector(".study-clock-subjects").innerHTML = Object.entries(day).filter(([, ms]) => ms >= 60e3).sort((a, b) => b[1] - a[1])
    .map(([s, ms]) => `<li><span>${esc(names[s] ?? (s === "other" ? "Other (timer)" : s))}</span><b>${fmt(ms)}</b></li>`).join("")
    || "<li><span>Nothing yet today</span></li>";
}

// ---------- To-do list ----------
function todos() {  // today's list; on a new day, ticked tasks drop off and unticked ones carry over
  const t = load(TODO_KEY, { day: dayOf(), items: [] });
  if (t.day !== dayOf()) { t.day = dayOf(); t.items = t.items.filter(i => !i.done); save(TODO_KEY, t); }
  return t;
}

function foldOut(slot, name, openByDefault) {  // a fold-out box that remembers whether you left it open
  const box = document.createElement("details");
  box.className = box.id = slot.className;
  box.open = load(OPEN_KEY, {})[name] ?? openByDefault;
  box.innerHTML = "<summary></summary>";
  box.addEventListener("toggle", () => { const o = load(OPEN_KEY, {}); o[name] = box.open; save(OPEN_KEY, o); });
  slot.replaceWith(box);
  return box;
}

function todayBox(slot) {
  const box = foldOut(slot, "today", true);
  box.insertAdjacentHTML("beforeend", `<ul class="study-todo"></ul>
    <form class="study-add"><input type="text" maxlength="200" placeholder="Add a task and press Enter" aria-label="New task"></form>
    <p class="study-hint">Unticked tasks move to tomorrow. On a note, press <kbd>T</kbd> to add it here.</p>`);
  const list = box.querySelector("ul"), input = box.querySelector("input");
  box.querySelector("form").addEventListener("submit", e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    const t = todos();
    t.items.push({ id: newId(), text, done: false });
    save(TODO_KEY, t);
    input.value = "";
    paintTodos(box);
  });
  const update = (li, change) => {  // change one task, without redrawing the list under your cursor
    const t = todos(), i = t.items.findIndex(x => x.id === li.dataset.id);
    if (i < 0) return;
    if (change(t.items, i) === "redraw") { save(TODO_KEY, t); return paintTodos(box); }
    save(TODO_KEY, t);
    paintSummary(box, t);
  };
  list.addEventListener("change", e => {
    const li = e.target.closest("li");
    li.classList.toggle("done", e.target.checked);
    update(li, (items, i) => { items[i].done = e.target.checked; });
  });
  list.addEventListener("click", e => {
    if (e.target.matches(".study-del")) update(e.target.closest("li"), (items, i) => (items.splice(i, 1), "redraw"));
  });
  list.addEventListener("keydown", e => {
    const li = e.target.closest("li");
    if (e.target.isContentEditable && (e.key === "Enter" || e.key === "Escape")) {
      e.preventDefault();
      if (e.key === "Escape") e.target.textContent = todos().items.find(x => x.id === li.dataset.id)?.text ?? "";
      e.target.blur();
    }
    if (e.target.matches(".study-grip") && (e.key === "ArrowUp" || e.key === "ArrowDown")) {  // move with the keyboard
      e.preventDefault();
      const up = e.key === "ArrowUp";
      update(li, (items, i) => {
        const j = i + (up ? -1 : 1);
        if (j < 0 || j >= items.length) return;
        [items[i], items[j]] = [items[j], items[i]];
        return "redraw";
      });
      list.querySelector(`[data-id="${li.dataset.id}"] .study-grip`)?.focus();
    }
  });
  list.addEventListener("focusout", e => {  // finished editing a task's text
    if (!e.target.isContentEditable) return;
    const text = e.target.textContent.trim();
    update(e.target.closest("li"), (items, i) => text ? void (items[i].text = text) : (items.splice(i, 1), "redraw"));
  });
  // Drag to reorder, by the ⠿ handle
  let dragged;
  list.addEventListener("pointerdown", e => { const li = e.target.closest(".study-grip")?.closest("li"); if (li) li.draggable = true; });
  list.addEventListener("pointerup", () => list.querySelectorAll("[draggable=true]").forEach(li => li.draggable = false));
  list.addEventListener("dragstart", e => {
    if (!e.target.matches?.("li[draggable=true]")) return;  // e.g. dragging a task's link
    dragged = e.target; dragged.classList.add("dragging"); e.dataTransfer.setData("text/plain", "");
  });
  list.addEventListener("dragover", e => {
    const over = e.target.closest?.("li");
    if (!dragged || !over || over === dragged) return;
    e.preventDefault();
    const r = over.getBoundingClientRect();
    over[e.clientY > r.top + r.height / 2 ? "after" : "before"](dragged);
  });
  list.addEventListener("dragend", () => {
    if (!dragged) return;
    dragged.draggable = false;
    dragged.classList.remove("dragging");
    dragged = null;
    const t = todos(), order = [...list.children].map(li => li.dataset.id);
    t.items.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    save(TODO_KEY, t);
  });
  paintTodos(box);
}

function paintSummary(box, t) {
  const n = t.items.filter(i => i.done).length;
  box.querySelector("summary").innerHTML = `Today <small>${t.items.length ? `${n} of ${t.items.length} done` : "nothing planned yet"}</small>`;
}

function paintTodos(box) {
  const t = todos();
  paintSummary(box, t);
  box.querySelector("ul").innerHTML = t.items.map(i => `<li data-id="${esc(String(i.id))}"${i.done ? ' class="done"' : ""}>` +
    `<button type="button" class="study-grip" title="Drag, or press ↑ ↓, to move" aria-label="Move task">⠿</button>` +
    `<input type="checkbox" aria-label="Done"${i.done ? " checked" : ""}>` +
    (i.href ? `<span class="study-task"><a href="${esc(i.href)}">${esc(i.text)}</a>${i.where ? ` <small>${esc(i.where)}</small>` : ""}</span>`
            : `<span class="study-task" contenteditable="plaintext-only" spellcheck="false">${esc(i.text)}</span>`) +
    `<button type="button" class="study-del" title="Delete" aria-label="Delete task">×</button></li>`).join("");
}

function todayButton() {  // "+ Today" next to "Mark as done" on a note
  const done = document.querySelector(".md-content .study-meta .study-btn");
  if (!done) return;
  const path = location.pathname, title = document.querySelector(".md-content h1").textContent.replace("¶", "").trim();
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "study-btn study-today-btn";
  const paint = () => {
    const on = todos().items.some(i => i.href === path);
    btn.classList.toggle("on", on);
    btn.textContent = on ? "✓ On today's list" : "+ Today";
    btn.title = on ? "Remove from today's to-do list (T)" : "Add to today's to-do list (T)";
    btn.setAttribute("aria-pressed", on);
  };
  btn.addEventListener("click", () => {
    const t = todos(), i = t.items.findIndex(x => x.href === path);
    if (i >= 0) t.items.splice(i, 1);
    else t.items.push({ id: newId(), text: title, where: subjectName(), href: path, done: doneSet().has(path) });
    save(TODO_KEY, t);
    paint();
  });
  done.addEventListener("click", () => {  // runs after study.js saved the note: marking it done (D) ticks it here too
    const t = todos(), item = t.items.find(x => x.href === path);
    if (item) { item.done = doneSet().has(path); save(TODO_KEY, t); }
  });
  paint();
  done.before(btn);
}

function subjectName() {  // "Principles of Economics": the breadcrumb under the home page, or a subject page's own title
  const crumb = document.querySelectorAll(".md-path__link")[1];
  if (crumb) return crumb.textContent.trim();
  if (location.pathname.split("/").filter(Boolean).length === 1)
    return document.querySelector(".md-content h1")?.textContent.replace("¶", "").trim();
}

// ---------- Stats ----------
function streakOf(msOf, now = new Date()) {  // days in a row with 2 h+; today only counts once it gets there. msOf(date) -> ms
  let n = 0, d = now;
  if (msOf(d) < LEVELS.at(-1)[0] * H) d = shift(d, -1);
  while (msOf(d) >= LEVELS.at(-1)[0] * H) { n++; d = shift(d, -1); }
  return n;
}

function heatCells(msOf, now = new Date()) {  // the heatmap's inner HTML: WEEKS columns, Monday first. msOf(date) -> ms
  const first = shift(monday(now), -7 * (WEEKS - 1));
  let cells = `<span></span>` + ["Mon", "", "Wed", "", "Fri", "", ""].map(d => `<span>${d}</span>`).join("");
  for (let w = 0; w < WEEKS; w++) {
    const start = shift(first, 7 * w), month = [...Array(7)].map((_, i) => shift(start, i)).find(d => d.getDate() === 1);
    cells += `<span>${w === 0 || month ? (month ?? start).toLocaleString("en", { month: "short" }) : ""}</span>`;
    for (let i = 0; i < 7; i++) {
      const d = shift(start, i), ms = msOf(d);
      cells += d > now ? "<i hidden></i>" : `<i data-level="${level(ms)}" title="${d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}: ${fmt(ms)}"></i>`;
    }
  }
  return cells;
}

function weekOf(log, start) {  // per-subject totals for the 7 days from start
  const out = {};
  for (let i = 0; i < 7; i++) for (const [s, ms] of Object.entries(log[dayOf(shift(start, i))] ?? {})) out[s] = (out[s] || 0) + ms;
  return out;
}

function statsBox(slot) {
  const box = foldOut(slot, "stats", false), log = load(TIME_KEY, {}), names = load(NAMES_KEY, {});
  const now = new Date(), today = sum(log[dayOf()]), thisWeek = weekOf(log, monday(now)), streak = streakOf(d => sum(log[dayOf(d)]), now);
  box.querySelector("summary").innerHTML = `Study stats <small>🔥 ${streak}-day streak · ${fmt(sum(thisWeek))} this week</small>`;

  const cells = heatCells(d => sum(log[dayOf(d)]), now);
  const weeks = [...Array(8)].map((_, k) => { const s = shift(monday(now), -7 * k); return [s, sum(weekOf(log, s))]; });
  const top = Math.max(...weeks.map(w => w[1]), 1), subjects = Object.entries(thisWeek).filter(([, ms]) => ms >= 60e3).sort((a, b) => b[1] - a[1]);
  const row = (label, ms, max) => `<div class="study-row"><span>${esc(label)}</span>${bar(ms, max)}<b>${fmt(ms)}</b></div>`;
  box.insertAdjacentHTML("beforeend", `
    <div class="study-tiles">
      <div><small>Today</small><b data-level="${level(today)}">${fmt(today)}</b></div>
      <div><small>This week</small><b>${fmt(sum(thisWeek))}</b></div>
      <div><small>Streak (2h+ a day)</small><b>🔥 ${streak} ${streak === 1 ? "day" : "days"}</b></div>
    </div>
    <div class="study-heat-wrap"><div class="study-heat">${cells}</div></div>
    <p class="study-legend"><i data-level="some"></i> under 2h <i data-level="green"></i> 2h+ <i data-level="orange"></i> 4h+ <i data-level="red"></i> 6h+</p>
    <p class="study-label">Weekly totals</p>
    ${weeks.map(([s, ms], k) => row(k ? `${s.getDate()} ${s.toLocaleString("en", { month: "short" })}` : "This week", ms, top)).join("")}
    <p class="study-label">This week by subject</p>
    ${subjects.map(([s, ms]) => row(names[s] ?? (s === "other" ? "Other (timer)" : s), ms, subjects[0][1])).join("") || "<p class='study-hint'>Nothing yet this week.</p>"}
    <p class="study-hint"><a href="/stats/">All stats →</a></p>`);
  const heat = box.querySelector(".study-heat-wrap");
  box.addEventListener("toggle", () => heat.scrollLeft = heat.scrollWidth);  // newest weeks in view on small screens
  if (location.hash === "#study-stats") { box.open = true; box.scrollIntoView(); }
}

// ---------- Page hook ----------
function todayPage() {
  clockChip();
  const here = subjectOf(location.pathname), name = here && subjectName();
  if (name) { const n = load(NAMES_KEY, {}); if (n[here] !== name) { n[here] = name; save(NAMES_KEY, n); } }
  const content = document.querySelector(".md-content .md-typeset");
  const todoSlot = content?.querySelector("div.study-today"), statsSlot = content?.querySelector("div.study-stats");
  if (todoSlot) todayBox(todoSlot);
  if (statsSlot) statsBox(statsSlot);
  todayButton();
  tick();
}

setInterval(tick, 1000);
if (typeof document$ !== "undefined") document$.subscribe(todayPage);  // after study.js: runs again after instant page switches
else document.addEventListener("DOMContentLoaded", todayPage);
