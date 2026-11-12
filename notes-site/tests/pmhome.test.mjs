// Tests for docs/javascripts/pmhome.js, the home page's Planner box (run: node --test tests/).
import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const H = 3600e3;
const { planHtml, planSummary, planCheck, planEntry, planMerge, planPending, planEntryText, pmStatsHtml, dayOf, shift } =
  load(["study.js", "today.js", "pmstats.js", "pmhome.js"], { path: "/", expose: [
    "planHtml", "planSummary", "planCheck", "planEntry", "planMerge", "planPending", "planEntryText", "pmStatsHtml", "dayOf", "shift"] });
const NOW = new Date(2026, 10, 9, 15);
const day = k => dayOf(shift(NOW, k));
const EVIL = "<img src=x onerror=alert(1)> & co";
const ids = list => Array.from(list, e => e.id);  // the scripts run in their own realm: copy before deepEqual

const BASE = {  // the stats page's fixture shape (pmstats.test.mjs), trimmed to what the box reads
  version: 1, generated: "2026-11-09T13:00:00", settings: { hours_per_day: 4, peak: "09-12" }, days: {},
  time: { by_course: {}, by_kind: {}, by_energy: {} }, estimates: { kinds: [], history: [] },
  deadlines: { crunch: 0.31, on_time: 0, late: 0, open: [], recent: [] },
  study: { reviews: 0, brier: null, due_now: 7, bins: [], topics: [] },
  bugs: { fixed: 0, open: 0, abandoned: 0, lost_min: 0, untagged: 0, tags: [], bursts: [], recent: [] },
};
const PM = {
  ...BASE,
  today: { cap_min: 240, worked_min: 95, plan: [
    { id: 3, title: "OS lab 3", course: "os", minutes: 195, energy: "deep", due: "2026-11-12", behind: true, first: "open the handout" },
    { id: 4, title: EVIL, course: null, minutes: 30, energy: "shallow", due: null, behind: false, first: null }] },
  study: { ...BASE.study, held: 2, due: [
    { id: 5, topic: "paging", title: "TLB", url: "/os/paging/#tlb" },
    { id: 6, topic: "paging", title: EVIL, url: "javascript:alert(1)" },
    { id: 7, topic: "x", title: "far", url: "//evil.example/x" },
    { id: 8, topic: "x", title: "none", url: null }] },
  inbox_done: [],
};

test("the plan, the day meter and the first step", () => {
  const html = planHtml(PM, NOW);
  for (const s of ["OS lab 3", "~3h 15m", "<b>BEHIND</b>", "open the handout", "due 12 Nov", "1h 35m of 4h 00m today", "study-bar"])
    assert.ok(html.includes(s), s);
});

test("titles are text, never HTML, in the plan and the due list", () => {
  const html = planHtml(PM, NOW);
  assert.ok(!html.includes("<img"), "raw <img must not appear");
  assert.equal(html.split("&#60;img src=x onerror=alert(1)&#62; &#38; co").length - 1, 4);  // plan title, label, data-title, due title
});

test("only same-site addresses become links", () => {
  const html = planHtml(PM, NOW);
  assert.ok(html.includes('<a href="/os/paging/#tlb">TLB</a>'));
  assert.equal((html.match(/<a /g) ?? []).length, 1);
  assert.ok(!html.includes("javascript:") && !html.includes("//evil"));
});

test("more due than listed, and items held back", () => {
  const due = Array.from({ length: 30 }, (_, i) => ({ id: i, topic: "t", title: `q${i}`, url: null }));
  const html = planHtml({ ...PM, study: { ...PM.study, due_now: 42, due } }, NOW);
  assert.ok(html.includes("+ 12 more"));
  assert.ok(html.includes("2 new items wait for another day"));
  assert.ok(!planHtml({ ...PM, study: { ...PM.study, held: 0 } }, NOW).includes("wait for another day"));
});

test("an old push says so; a recent one doesn't", () => {
  assert.ok(planHtml({ ...PM, generated: "2026-11-06T15:00:00" }, NOW).includes("last pushed 3 days ago"));
  assert.ok(!planHtml(PM, NOW).includes("last pushed"));
});

test("a push from an older pm draws what it has", () => {
  const html = planHtml(BASE, NOW);
  assert.equal(typeof html, "string");
  assert.ok(!html.includes("undefined") && !html.includes("NaN"));
  assert.ok(!html.includes("today</p>"));
  assert.ok(html.includes("Add to pm"));
  const bare = planHtml({ version: 1 }, NOW);
  assert.ok(!bare.includes("undefined") && !bare.includes("NaN"));
  assert.equal(planSummary({ version: 1 }, NOW), "Planner <small></small>");
});

test("an empty day and no reviews", () => {
  const html = planHtml({ ...PM, today: { cap_min: 240, worked_min: 0, plan: [] }, study: { ...PM.study, due: [], due_now: 0 } }, NOW);
  assert.ok(html.includes("Nothing planned for today.") && html.includes("No reviews due."));
});

test("the summary line", () => {
  const s = planSummary(PM, NOW);
  for (const part of ["Planner", "crunch 31%", "7 due", "updated 2h 00m ago"]) assert.ok(s.includes(part), part);
  assert.ok(planSummary({ ...PM, generated: "2026-11-09T16:00:00" }, NOW).includes("just now"));  // a laptop clock ahead
});

test("all four scripts load together, and the stats page still works", () => {
  assert.match(pmStatsHtml(PM, {}, NOW), /Crunch risk/);
});

// ---------- quick capture ----------
test("planCheck catches a missing title and a bad length", () => {
  assert.equal(planCheck({ title: " ", est: "1h" }), "Give it a title.");
  for (const est of ["soon", "", "0", "0m", "h", "1h30", "-1h", "2", "90", "1.5"]) assert.equal(planCheck({ title: "a", est }), "Give a length like 45m or 1h30m.", est);
  for (const est of ["1h30m", "45m", "2h", "1.5h", " 90m "]) assert.equal(planCheck({ title: "a", est }), null, est);
  assert.equal(planCheck({ duration: "45m" }), null);  // logging time has no title
  assert.equal(planCheck({ duration: "x" }), "Give a length like 45m or 1h30m.");
  // rounded to whole minutes and at most 1000h, like pm's parse_duration (a date typed as the estimate is caught here)
  for (const est of ["0.005h", "20261120", "1001h", "99999999m", "1".repeat(21)]) assert.equal(planCheck({ title: "a", est }), "Give a length like 45m or 1h30m.", est);
  for (const est of ["1000h", "0.01h", "1m"]) assert.equal(planCheck({ title: "a", est }), null, est);
});

test("planEntry: local time without a zone, empty optional fields left out", () => {
  const e = planEntry("add", { title: " A ", est: "1h", due: "" }, new Date(2026, 10, 10, 18, 30));
  assert.equal(e.op, "add");
  assert.equal(e.title, "A");
  assert.equal(e.est, "1h");
  assert.equal(e.at, "2026-11-10T18:30:00");
  assert.ok(typeof e.id === "string" && e.id.length > 0 && /^[A-Za-z0-9_-]{1,40}$/.test(e.id));
  assert.ok(!("due" in e));
  const log = planEntry("log", { task: 3, duration: "45m" }, NOW);
  assert.equal(log.op, "log");
  assert.equal(log.task, 3);
  assert.equal(log.duration, "45m");
});

test("planMerge: union by id, server first, newest 100", () => {
  assert.deepEqual(ids(planMerge([{ id: "a" }], [{ id: "b" }])), ["a", "b"]);
  assert.deepEqual(ids(planMerge([], [{ id: "a" }, { id: "b" }])), ["a", "b"]);  // a stale read of the inbox
  assert.equal(planMerge([{ id: "a" }], [{ id: "a" }]).length, 1);
  const many = Array.from({ length: 120 }, (_, i) => ({ id: `e${i}` }));
  const kept = planMerge(many, []);
  assert.equal(kept.length, 100);
  assert.equal(kept[0].id, "e20");
  assert.deepEqual(ids(planMerge(null, [{ id: "a" }, { nope: 1 }, "x"])), ["a"]);
});

test("planPending sorts what the laptop said", () => {
  const p = planPending([{ id: "a" }, { id: "b" }, { id: "c" }], { inbox_done: [{ id: "a" }, { id: "b", error: "bad duration 'soon'" }] });
  assert.deepEqual(ids(p.waiting), ["c"]);
  assert.deepEqual(Array.from(p.failed, e => [e.id, e.error]), [["b", "bad duration 'soon'"]]);
  assert.deepEqual(ids(planPending([{ id: "a" }], {}).waiting), ["a"]);  // an older push without inbox_done
  // a failure remembered on this device stays a failure after its acknowledgement leaves the laptop's newest 100
  const kept = planPending([{ id: "b", error: "bad duration 'soon'" }], { inbox_done: [] });
  assert.deepEqual(ids(kept.waiting), []);
  assert.deepEqual(Array.from(kept.failed, e => [e.id, e.error]), [["b", "bad duration 'soon'"]]);
});

test("planSend never sends a failed entry back and skips the PUT when nothing changed", async () => {
  const x = load(["study.js", "today.js", "pmstats.js", "pmhome.js"], { expose: ["planSend", "globalThis"] });
  x.localStorage.setItem("study.pminbox", JSON.stringify([{ id: "w", op: "done", task: 1 }, { id: "f", op: "done", task: 2, error: "no" }]));
  const calls = [];
  x.globalThis.fetch = async (url, init = {}) => {
    calls.push([init.method ?? "GET", init.body ?? null]);
    return { ok: true, json: async () => ({ items: [] }) };
  };
  assert.equal(await x.planSend({ inbox_done: [] }), true);
  assert.deepEqual(calls.map(c => c[0]), ["GET", "PUT"]);
  assert.deepEqual(JSON.parse(calls[1][1]).items.map(e => e.id), ["w"]);
  calls.length = 0;
  x.globalThis.fetch = async (url, init = {}) => {
    calls.push([init.method ?? "GET"]);
    return { ok: true, json: async () => ({ items: [{ id: "w", op: "done", task: 1 }] }) };
  };
  assert.equal(await x.planSend({ inbox_done: [] }), true);
  assert.deepEqual(calls.map(c => c[0]), ["GET"]);
  // the server still holds a failure whose acknowledgement aged out of inbox_done: this device prunes it
  calls.length = 0;
  x.globalThis.fetch = async (url, init = {}) => {
    calls.push([init.method ?? "GET", init.body ?? null]);
    return { ok: true, json: async () => ({ items: [{ id: "f", op: "done", task: 2 }, { id: "w", op: "done", task: 1 }] }) };
  };
  assert.equal(await x.planSend({ inbox_done: [] }), true);
  assert.deepEqual(JSON.parse(calls[1][1]).items.map(e => e.id), ["w"]);
});

test("planEntryText", () => {
  assert.equal(planEntryText({ op: "add", title: "<b>x</b>", est: "1h" }), 'add "&#60;b&#62;x&#60;/b&#62;" (1h)');
  assert.equal(planEntryText({ op: "log", task: 3, duration: "45m" }), "log 45m on #3");
  assert.equal(planEntryText({ op: "done", task: 3 }), "finish #3");
});

test("planHtml draws the form, the item buttons and both pending lists", () => {
  const local = [{ id: "a", op: "add", title: "OS lab 4", est: "1h" }, { id: "b", op: "add", title: "x", est: "soon" }];
  const html = planHtml({ ...PM, inbox_done: [{ id: "b", error: "bad duration <'soon'>" }] }, NOW, local);
  for (const s of ['data-plan="add"', 'data-plan="log" data-task="3"', 'data-plan="done" data-task="3"', "+ time", "hidden>",
                   'Waiting for your laptop: add "OS lab 4" (1h)', "Your laptop said: bad duration &#60;'soon'&#62;", 'data-plan="dismiss" data-id="b"'])
    assert.ok(html.includes(s), s);
  assert.ok(!html.includes(" disabled"));
});

test("more than 50 waiting entries disable the form", () => {
  const local = Array.from({ length: 51 }, (_, i) => ({ id: `w${i}`, op: "done", task: 1 }));
  const html = planHtml(PM, NOW, local);
  assert.equal((html.match(/ disabled/g) ?? []).length, 4);
  assert.ok(html.includes("hasn't picked up the last 50 entries yet"));
});
