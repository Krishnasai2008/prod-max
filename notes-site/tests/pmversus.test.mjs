// Tests for docs/javascripts/pmversus.js, the home page's Versus box (run: node --test tests/).
import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const { versusHtml, versusSummary, versusMount } = load(["study.js", "today.js", "pmstats.js", "pmhome.js", "pmversus.js"],
  { path: "/", expose: ["versusHtml", "versusSummary", "versusMount"] });
const NOW = new Date("2026-11-13T10:30:00");
const EVIL = "<img src=x onerror=1>";

const V = () => ({
  you: "kelvin", players: ["kelvin", "sam"],
  today: { day: "2026-11-13", rows: [
    { key: "min", label: "minutes studied", values: { kelvin: 185, sam: 140 }, leader: "kelvin" },
    { key: "reviews", label: "reviews done", values: { kelvin: 42, sam: 60 }, leader: "sam" },
    { key: "quiz", label: "quiz answers right", values: { kelvin: 18, sam: 18 }, leader: null },
    { key: "test", label: "test answers right", values: { kelvin: 9, sam: 0 }, leader: "kelvin" },
    { key: "syllabus", label: "syllabus gained", values: { kelvin: 2.1, sam: -0.4 }, leader: "kelvin" }],
    points: { kelvin: 3, sam: 1 }, leader: "kelvin", draw: false },
  tally: { kelvin: 12, sam: 9 }, draws: 2, streak: { name: "kelvin", days: 3 },
  recent: [{ day: "2026-11-12", winner: "kelvin", points: { kelvin: 3, sam: 2 } },
    { day: "2026-11-11", winner: null, points: { kelvin: 2, sam: 2 } },
    { day: "2026-11-10", winner: null, points: { kelvin: 0, sam: 0 } }],
  synced: { kelvin: "2026-11-13T10:00:00", sam: "2026-11-13T09:12:00" },
});

test("the scoreboard: leader cells, you, durations, signed syllabus, tally, streak, recent, sync", () => {
  const html = versusHtml(V(), NOW);
  for (const s of ["<th>you</th><th>sam</th>", `<td class="versus-lead"><b>3h 05m</b> ★</td><td>2h 20m</td>`,
    `<td>42</td><td class="versus-lead"><b>60</b> ★</td>`, "<td>18</td><td>18</td>", "+2.1%", "-0.4%",
    "points today: you 3 · sam 1", "Days won: you 12 · sam 9 · draws 2", "Streak: you won 3 days in a row",
    "<span>12 Nov</span> you", "<span>11 Nov</span> draw", "<span>10 Nov</span> no winner", "Last synced: sam 1h 18m ago"])
    assert.ok(html.includes(s), s);
  assert.ok(!html.includes("kelvin"), "the viewer is shown as you");
  assert.equal(versusSummary(V()), "Versus <small>you lead 3–1 · wins 12–9</small>");
});

test("zero syllabus, other leaders, more players and no viewer", () => {
  const v = V();
  v.today.rows[4].values.kelvin = 0.01;
  v.today.leader = "sam";
  assert.ok(versusHtml(v, NOW).includes("<b>0%</b> ★</td><td>-0.4%</td>"));
  assert.equal(versusSummary(v), "Versus <small>sam leads 1–3 · wins 12–9</small>");
  v.today.draw = true; v.today.leader = null;
  assert.equal(versusSummary(v), "Versus <small>level 3–1 · wins 12–9</small>");
  const three = { ...V(), you: null, players: ["ann", "kelvin", "sam"] };
  assert.equal(versusSummary(three), "Versus <small>today: kelvin leads</small>");
  assert.match(versusHtml(three, NOW), /Last synced: ann never · kelvin 30m ago · sam 1h 18m ago/);
});

test("names and labels from the data are escaped, bad numbers show as 0", () => {
  const v = { ...V(), you: null, players: [EVIL, "sam"], streak: { name: EVIL, days: 1 } };
  v.today.rows[0] = { key: "min", label: EVIL, values: { [EVIL]: "x", sam: Infinity }, leader: EVIL };
  v.today.day = EVIL;
  const html = versusHtml(v, NOW) + versusSummary(v);
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&#60;img src=x onerror=1&#62;"));
  assert.ok(html.includes("<b>0m</b> ★</td><td>0m</td>"));
});

test("missing, null or malformed versus draws nothing", () => {
  const bad = [undefined, null, 1, "x", [], {}, { players: [] }, { ...V(), players: "kelvin" }, { ...V(), players: [1] },
    { ...V(), today: null }, { ...V(), today: { rows: {} } }, { ...V(), today: { rows: [null] } },
    { ...V(), today: { rows: [{ key: "min", values: null }] } }, { ...V(), players: Array(51).fill("a") }];
  for (const v of bad) {
    assert.equal(versusHtml(v, NOW), "");
    assert.equal(versusSummary(v), "");
  }
  let touched = false;
  const box = { after: () => { touched = true; } };
  versusMount(box, { version: 1 });
  versusMount(box, null);
  assert.equal(touched, false);
});

test("a failure while inserting the box never reaches the Planner box that called it", () => {
  assert.doesNotThrow(() => versusMount({ after: () => { throw new Error("no DOM"); } }, { version: 1, versus: V() }));
  assert.doesNotThrow(() => versusMount(null, { version: 1, versus: V() }));
});

test("the overall score and penalty days are shown when the push has them, and nothing when it doesn't", () => {
  const v = { ...V(), score: { kelvin: 11, sam: 5 }, penalties: { kelvin: 1, sam: 4 } };
  assert.ok(versusHtml(v, NOW).includes("Score: you 11 · sam 5 · days of 30m or less: you 1 · sam 4"));
  assert.ok(!versusHtml(V(), NOW).includes("Score:"));
  assert.ok(!versusHtml({ ...v, score: "<b>" }, NOW).includes("Score:"));
});

test("each player's study streak is shown when the push has it", () => {
  assert.ok(versusHtml({ ...V(), streaks: { kelvin: 4, sam: 0 } }, NOW).includes("2h+ days in a row: you 4 · sam 0"));
  assert.ok(!versusHtml(V(), NOW).includes("days in a row:"));
  assert.ok(!versusHtml({ ...V(), streaks: "<b>" }, NOW).includes("days in a row:"));
});
