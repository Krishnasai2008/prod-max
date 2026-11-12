import { esc, fmtClock, pct, routeOf, stateKey, shouldRender, ROUTES } from "./lib.js";
import * as today from "./today.js";
import { warnLong } from "./today.js";
import * as tasks from "./tasks.js";
import * as review from "./review.js";
import * as study from "./study.js";
import * as risk from "./risk.js";
import * as stats from "./stats.js";
import * as settings from "./settings.js";
import * as bugs from "./bugs.js";
import * as files from "./files.js";
import * as addstudy from "./addstudy.js";
import * as spot from "./spot.js";
import * as exam from "./exam.js";
import * as practice from "./practice.js";
import * as versus from "./versus.js";

const screens = { today, tasks, review, study, risk, stats, bugs, files, settings, spot, exam, practice, versus };

const ROUTE_KEYS = {
  "1": "today",
  "2": "tasks",
  "3": "review",
  "4": "study",
  "5": "risk",
  "6": "stats",
  "7": "bugs",
  "8": "files",
  "9": "settings",
  "0": "exam",
  p: "practice",
  v: "versus",
};

const screenEl = document.querySelector("#screen");
const headerEl = document.querySelector("header");
const navEl = document.querySelector("#nav");
const chipEl = document.querySelector("#timer-chip");
const crunchEl = document.querySelector("#crunch");
const reviewsEl = document.querySelector("#reviews");
const bannerEl = document.querySelector("#banner");
const toastEl = document.querySelector("#toast");
const helpEl = document.querySelector("#help");
const addstudyEl = document.querySelector("#addstudy");

let state = null;
let renderedKey = "";
let arrivedAt = 0;
let dirty = false;
let route = routeOf(location.hash);
let toastTimer = 0;
let extra = {};
let busy = false;
let busySince = 0;
let loadFailed = ""; // why the screen's own data couldn't be loaded; shown in place of the screen

const shared = {
  async reload() {}, // the error panel's button: every action ends by loading again
  async stop(_data, context) {
    warnLong(await context.api("POST", "/api/stop"), context);
  },
};

function context() {
  return {
    state,
    api,
    refresh,
    go,
    toast,
    run: runAction,
    patch(id, html) {
      const el = screenEl.querySelector("#" + CSS.escape(id));
      if (el) el.innerHTML = html;
    },
    busy: () => busy,
    confirm: window.confirm.bind(window),
    openAddStudy: async (path) => {
      await addstudy.open(context(), path);
      renderDialog();
    },
  };
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (method === "POST") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body ?? {});
  }
  const response = await fetch(path, options);
  let json = {};
  try {
    json = await response.json();
  } catch {
    json = {};
  }
  if (!response.ok) {
    throw new Error(json.error ?? `request failed (${response.status})`);
  }
  return json;
}

function currentElapsed() {
  if (!state?.running) return 0;
  const base = Number(state.running.elapsed_s ?? 0);
  return base + Math.max(0, Math.floor((performance.now() - arrivedAt) / 1000));
}

function updateElapsed() {
  const text = fmtClock(currentElapsed());
  for (const el of document.querySelectorAll("[data-elapsed]")) {
    el.textContent = text;
  }
}

function renderHeader() {
  if (!state) return;
  if (state.running) {
    const task = (state.tasks ?? []).find((item) => item.id === state.running.task_id);
    const title = task ? task.title : `#${state.running.task_id}`;
    chipEl.innerHTML =
      `<span class="chip-title" title="${esc(title)}">${esc(title)}</span>` +
      `<b class="clock" data-elapsed>${fmtClock(currentElapsed())}</b>` +
      `<button type="button" class="btn btn-small" data-act="stop">Stop</button>`;
    chipEl.hidden = false;
  } else {
    chipEl.innerHTML = "";
    chipEl.hidden = true;
  }
  crunchEl.textContent = `crunch ${pct(state.crunch ?? 0)}`;
  crunchEl.hidden = false;
  reviewsEl.textContent = `${state.reviews_due ?? 0} due`;
  reviewsEl.hidden = !state.reviews_due;
}

function renderNav() {
  for (const link of navEl.querySelectorAll("[data-route]")) {
    if (link.dataset.route === route) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
}

function renderScreen() {
  const screen = screens[route] ?? screens.today;
  if (loadFailed) {
    screenEl.innerHTML =
      `<div class="card" role="alert"><p>Couldn't load this screen: ${esc(loadFailed)}</p>` +
      `<button type="button" class="btn" data-act="reload">Try again</button></div>`;
    return;
  }
  screenEl.innerHTML = screen.html(state, extra);
  updateElapsed();
  if (typeof screen.after === "function") screen.after(screenEl);
}

function maybeRender() {
  if (!state) return;
  const nextKey = stateKey(state) + JSON.stringify(extra) + loadFailed;
  // a background refresh never redraws under a focused live control (search box, slider); an action resets renderedKey
  const holding = renderedKey !== "" && !!liveControl(document.activeElement);
  if (!shouldRender(renderedKey, nextKey, dirty || holding)) return;
  renderScreen();
  renderedKey = nextKey;
}

function renderDialog() {
  // keep focus and the section list's scroll across a re-render (a checkbox click re-renders)
  const focusId = addstudyEl.contains(document.activeElement) ? document.activeElement.id : "";
  const scroll = addstudyEl.querySelector(".sections")?.scrollTop ?? 0;
  addstudyEl.innerHTML = addstudy.html(addstudy.current());
  const list = addstudyEl.querySelector(".sections");
  if (list) list.scrollTop = scroll;
  if (focusId) document.getElementById(focusId)?.focus();
  if (addstudy.current().open && !addstudyEl.open) {
    addstudyEl.showModal();
  } else if (!addstudy.current().open && addstudyEl.open) {
    addstudyEl.close();
  }
}

async function loadExtra() {
  const screen = screens[route] ?? screens.today;
  if (typeof screen.load !== "function") {
    extra = {};
    return;
  }
  try {
    extra = (await screen.load(context())) ?? {};
    loadFailed = "";
  } catch (error) {
    loadFailed = error instanceof Error ? error.message : String(error);
  }
}

async function enterScreen() {
  const screen = screens[route] ?? screens.today;
  if (typeof screen.enter !== "function") return;
  try {
    await screen.enter(context());
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  }
}

async function refresh() {
  try {
    state = await api("GET", "/api/state");
    arrivedAt = performance.now();
    bannerEl.hidden = true;
    renderHeader();
    maybeRender();
  } catch {
    bannerEl.textContent = "pm ui is not answering";
    bannerEl.hidden = false;
  }
}

function toast(message) {
  toastEl.textContent = String(message ?? "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl.textContent = "";
  }, 4000);
}

function go(name) {
  if (!ROUTES.includes(name)) return;
  if (routeOf(location.hash) === name) {
    route = name;
    renderNav();
    return;
  }
  location.hash = `#/${name}`;
}

function actionFor(name) {
  return screens[route]?.actions?.[name] ?? shared[name];
}

function runAction(name, data) {
  const action = actionFor(name);
  if (action) return run(action, data);
}

async function run(action, data) {
  if (busy) {
    // a quick double click is dropped quietly; a click during a slow call gets told
    if (Date.now() - busySince > 1000) toast("still working on the last action, try again in a moment");
    return;
  }
  busy = true;
  busySince = Date.now();
  // the action's reload already uses what is typed (screens' input hooks), so a pending live call is stale
  for (const timer of liveTimers.values()) clearTimeout(timer);
  liveTimers.clear();
  try {
    await action(data, context());
    dirty = false;
    renderedKey = "";
    await loadExtra();
    await refresh();
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  } finally {
    busy = false;
  }
}

function focusField(name) {
  let attempts = 0;
  const seek = () => {
    const field = screenEl.querySelector(`[name="${name}"]`);
    if (field) {
      field.focus();
      return;
    }
    if (attempts++ < 60) requestAnimationFrame(seek);
  };
  requestAnimationFrame(seek);
}

screenEl.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-act]:not(form):not(input):not(select):not(textarea)");
  if (!trigger || !screenEl.contains(trigger)) return;
  const action = actionFor(trigger.dataset.act);
  if (!action) return;
  event.preventDefault();
  run(action, { ...trigger.dataset });
});

screenEl.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-act]");
  if (!form) return;
  event.preventDefault();
  const action = actionFor(form.dataset.act);
  if (!action) return;
  const formData = new FormData(form);
  const data = { ...form.dataset, ...Object.fromEntries(formData) };
  for (const select of form.querySelectorAll("select[multiple]")) {
    data[select.name] = formData.getAll(select.name);
  }
  run(action, data);
});

async function runDialog(action, data) {
  if (busy) return;
  busy = true;
  try {
    await action(data, context());
    renderDialog();
    if (action === addstudy.actions.add && !addstudy.current().open) {
      await loadExtra();
      await refresh();
    }
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  } finally {
    busy = false;
  }
}

addstudyEl.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-act]:not(form)");
  if (!trigger || !addstudyEl.contains(trigger)) return;
  const action = addstudy.actions[trigger.dataset.act];
  if (!action) return;
  event.preventDefault();
  runDialog(action, { ...trigger.dataset });
});

addstudyEl.addEventListener("submit", (event) => {
  const form = event.target.closest("form[data-act]");
  if (!form || !addstudyEl.contains(form)) return;
  event.preventDefault();
  const action = addstudy.actions[form.dataset.act];
  if (!action) return;
  const formData = new FormData(form);
  runDialog(action, { ...form.dataset, ...Object.fromEntries(formData) });
});

addstudyEl.addEventListener("input", (event) => {
  if (addstudy.input(event)) renderDialog();
});

addstudyEl.addEventListener("change", (event) => {
  if (addstudy.input(event)) renderDialog();
});

addstudyEl.addEventListener("close", () => {
  addstudy.actions.close({}, context());
  renderDialog();
});

function formClean() {
  const texts = screenEl.querySelectorAll(
    'input:not([type]):not([data-act]), input[type="text"]:not([data-act]), input[type="search"]:not([data-act]), input[type="number"]:not([data-act]), input[type="date"]:not([data-act]), input[type="range"]:not([data-act]), textarea:not([data-act])',
  );
  const choices = screenEl.querySelectorAll(
    'input[type="radio"]:not([data-act]), input[type="checkbox"]:not([data-act])',
  );
  const selects = screenEl.querySelectorAll("select:not([data-act])");
  return (
    [...texts].every((field) => field.value === field.defaultValue) &&
    [...choices].every((field) => field.checked === field.defaultChecked) &&
    [...selects].every((select) =>
      [...select.options].every((option) => option.selected === option.defaultSelected),
    )
  );
}

function trackDirty() {
  dirty = true;
  if (formClean()) {
    dirty = false;
    maybeRender();
  }
}

function liveControl(target) {
  if (!(target instanceof HTMLElement)) return null;
  if (!["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return null;
  if (!target.dataset.act || !screenEl.contains(target)) return null;
  return target;
}

const liveTimers = new Map();

function liveAction(el) {
  const action = screens[route]?.actions?.[el.dataset.act];
  if (!action) return;
  try {
    Promise.resolve(
      action({ ...el.dataset, name: el.name, value: el.value }, context()),
    ).catch((error) => toast(error instanceof Error ? error.message : String(error)));
  } catch (error) {
    toast(error instanceof Error ? error.message : String(error));
  }
}

function debounceLive(el) {
  clearTimeout(liveTimers.get(el.dataset.act));
  liveTimers.set(
    el.dataset.act,
    setTimeout(() => {
      liveTimers.delete(el.dataset.act);
      liveAction(el);
    }, 250),
  );
}

screenEl.addEventListener("input", (event) => {
  const screen = screens[route] ?? screens.today;
  if (typeof screen.input === "function") screen.input(event, context());
  const live = liveControl(event.target);
  if (live) debounceLive(live);
  else trackDirty();
});
screenEl.addEventListener("change", (event) => {
  const live = liveControl(event.target);
  if (live) {
    if (live.tagName === "SELECT") debounceLive(live);
  } else {
    trackDirty();
  }
});

headerEl.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-act]:not(form)");
  if (!trigger || !headerEl.contains(trigger)) return;
  const action = shared[trigger.dataset.act];
  if (!action) return;
  event.preventDefault();
  run(action, { ...trigger.dataset });
});

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (!document.querySelector("dialog[open]")) {
    const screen = screens[route] ?? screens.today;
    if (typeof screen.keys === "function") {
      let handled = false;
      try {
        handled = screen.keys(event, context());
      } catch (error) {
        toast(error instanceof Error ? error.message : String(error));
      }
      if (handled) {
        event.preventDefault();
        renderedKey = "";
        renderScreen();
        return;
      }
    }
  }
  if (event.key === "Escape") {
    if (helpEl.open) helpEl.close();
    return;
  }
  const target = event.target;
  if (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  ) return;
  if (document.querySelector("dialog[open]")) return;
  if (ROUTE_KEYS[event.key]) {
    go(ROUTE_KEYS[event.key]);
  } else if (event.key === "n") {
    go("tasks");
    focusField("title");
  } else if (event.key === "s") {
    if (state?.running) {
      go("today");
      focusField("note");
    } else {
      const item = state?.today?.plan?.[0];
      const action = screens.today.actions?.start;
      if (item && action) run(action, { id: String(item.task_id) });
    }
  } else if (event.key === "/") {
    if (ROUTES.includes("files")) {
      event.preventDefault();
      go("files");
      focusField("q");
    }
  } else if (event.key === "?") {
    helpEl.showModal();
  }
});

window.addEventListener("hashchange", async () => {
  for (const timer of liveTimers.values()) clearTimeout(timer);
  liveTimers.clear();
  route = routeOf(location.hash);
  dirty = false;
  renderNav();
  await enterScreen();
  await loadExtra();
  renderedKey = "";
  maybeRender();
});

async function backgroundRefresh() {
  await loadExtra();
  await refresh();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) backgroundRefresh();
});

setInterval(backgroundRefresh, 60000);
setInterval(updateElapsed, 1000);

screenEl.innerHTML = '<p class="muted">loading…</p>';
renderNav();
(async () => {
  await refresh();
  await enterScreen();
  await loadExtra();
  renderedKey = "";
  maybeRender();
})();
