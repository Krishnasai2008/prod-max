import test from "node:test";
import assert from "node:assert/strict";

import { STATE } from "./fixture.mjs";
import { actions, html, load } from "../../pm/ui/versus.js";

const day = (kel, sam) => ({ kel, sam });
const BOARD = {
  you: "kel",
  players: ["kel", "sam"],
  today: {
    day: "2026-11-09",
    rows: [
      { key: "min", label: "minutes studied", values: day(185, 140), leader: "kel" },
      { key: "reviews", label: "reviews done", values: day(42, 60), leader: "sam" },
      { key: "quiz", label: "quiz answers right", values: day(18, 18), leader: null },
      { key: "test", label: "test answers right", values: day(9, 0), leader: "kel" },
      { key: "syllabus", label: "syllabus gained", values: day(2.1, -0.4), leader: "kel" },
    ],
    points: day(3, 1),
    leader: "kel",
    draw: false,
  },
  tally: day(12, 9),
  draws: 2,
  streak: { name: "kel", days: 3 },
  penalties: day(1, 4),
  score: day(11, 5),
  recent: [
    { day: "2026-11-08", winner: "kel", points: day(3, 2) },
    { day: "2026-11-07", winner: null, points: day(2, 2) },
    { day: "2026-11-06", winner: null, points: day(0, 0) },
  ],
  synced: { kel: "2026-11-09T09:55:00", sam: "2026-11-09T07:00:00" },
};
const on = (board) => ({ versus: { on: true, board } });

test("off: points at the setting and has no sync button", () => {
  const out = html(STATE, { versus: { on: false, board: null } });
  assert.ok(out.includes("The scoreboard is off"));
  assert.ok(!out.includes("data-act"));
  assert.ok(html(STATE, {}).includes("The scoreboard is off"));
});

test("on with no board yet: offers a sync", () => {
  const out = html(STATE, on(null));
  assert.ok(out.includes("No scoreboard yet"));
  assert.ok(out.includes('<button type="button" class="btn" data-act="sync">Sync now</button>'));
});

test("the board marks each row's leader and shows the viewer as you", () => {
  const out = html(STATE, on(BOARD));
  assert.ok(out.includes('<th scope="col">you</th><th scope="col">sam</th>'));
  assert.ok(!out.includes(">kel<"));
  assert.ok(out.includes('<th scope="row">minutes studied</th><td class="versus-lead"><b>3h5m</b> ★</td><td>2h20m</td>'));
  assert.ok(out.includes('<th scope="row">reviews done</th><td>42</td><td class="versus-lead"><b>60</b> ★</td>'));
  assert.ok(out.includes('<th scope="row">quiz answers right</th><td>18</td><td>18</td>'));
  assert.ok(out.includes('<td class="versus-lead"><b>+2.1%</b> ★</td><td>-0.4%</td>'));
  assert.ok(out.includes('<th scope="row">points</th><td><b>3</b></td><td><b>1</b></td>'));
  assert.ok(out.includes("<strong>you lead today</strong>"));
  assert.ok(out.includes("<small>you · days won</small><b>12</b>"));
  assert.ok(out.includes("<small>sam · days won</small><b>9</b>"));
  assert.ok(out.includes("<small>draws</small><b>2</b>"));
  assert.ok(out.includes("Streak: you, 3 days in a row."));
  assert.ok(out.includes("sam synced 3h ago"));
  assert.ok(!out.includes("you synced"));
});

test("recent days say who won, a draw, or no winner", () => {
  const out = html(STATE, on(BOARD));
  assert.ok(out.includes('<span class="muted">2026-11-08</span> you <span class="muted">3–2</span>'));
  assert.ok(out.includes('<span class="muted">2026-11-07</span> draw <span class="muted">2–2</span>'));
  assert.ok(out.includes('<span class="muted">2026-11-06</span> no winner <span class="muted">0–0</span>'));
});

test("a friend leading, and a level day", () => {
  const behind = { ...BOARD, today: { ...BOARD.today, leader: "sam" } };
  assert.ok(html(STATE, on(behind)).includes("<strong>sam leads today</strong>"));
  const level = { ...BOARD, today: { ...BOARD.today, leader: null }, streak: null };
  const out = html(STATE, on(level));
  assert.ok(out.includes("<strong>today is level</strong>"));
  assert.ok(!out.includes("Streak"));
});

test("alone on the board: waits for another player", () => {
  const alone = {
    ...BOARD,
    players: ["kel"],
    recent: [],
    streak: null,
    synced: { kel: BOARD.synced.kel },
  };
  const out = html(STATE, on(alone));
  assert.ok(out.includes("Waiting for another player to sync."));
  assert.ok(!out.includes("days won"));
});

test("another player's name is text, never markup", () => {
  const evil = '<img src=x onerror="1">';
  const swap = (o) => ({ kel: o.kel, [evil]: o.sam });
  const board = {
    ...BOARD,
    players: ["kel", evil],
    today: {
      ...BOARD.today,
      rows: BOARD.today.rows.map((r) => ({ ...r, label: `${r.label}<b>`, values: swap(r.values), leader: r.leader === "sam" ? evil : r.leader })),
      points: swap(BOARD.today.points),
      leader: evil,
    },
    tally: swap(BOARD.tally),
    streak: { name: evil, days: 2 },
    recent: [{ day: "<i>", winner: evil, points: swap(BOARD.recent[0].points) }],
    synced: swap(BOARD.synced),
  };
  const out = html(STATE, on(board));
  assert.ok(!out.includes("<img"));
  assert.ok(!out.includes("<i>"));
  assert.ok(!out.includes("studied<b>"));
  assert.ok(out.includes("&lt;img src=x onerror=&quot;1&quot;&gt; leads today"));
});

test("numbers that aren't numbers are shown as 0", () => {
  const board = { ...BOARD, tally: { kel: "<b>", sam: null }, draws: "x" };
  const out = html(STATE, on(board));
  assert.ok(out.includes("<small>you · days won</small><b>0</b>"));
  assert.ok(out.includes("<small>draws</small><b>0</b>"));
});

test("load reads the board and sync posts", async () => {
  const calls = [];
  const ctx = {
    async api(method, path) {
      calls.push([method, path]);
      return { on: true, board: null };
    },
    toast(message) {
      calls.push(["toast", message]);
    },
  };
  assert.deepEqual(await load(ctx), { versus: { on: true, board: null } });
  await actions.sync({}, ctx);
  assert.deepEqual(calls, [["GET", "/api/versus"], ["POST", "/api/versus/sync"], ["toast", "synced"]]);
});

test("the overall score is shown with the penalty days behind it", () => {
  const out = html(STATE, on(BOARD));
  assert.ok(out.includes('<p class="versus-score">Score: <strong>you 11 · sam 5</strong></p>'));
  assert.ok(out.includes("(never below zero). Days of 30m or less: you 1 · sam 4."));
  const old = { ...BOARD, score: undefined, penalties: undefined };
  assert.ok(!html(STATE, on(old)).includes("Score"));
});
