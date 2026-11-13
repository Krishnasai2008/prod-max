import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const H = 3600e3;
const { subjectOf, streakOf, heatCells, dayOf, shift } =
  load(["study.js", "today.js"], { path: "/stats/", expose: ["subjectOf", "streakOf", "heatCells", "dayOf", "shift"] });

test("the stats page is not a subject, so the clock never counts it", () => {
  assert.equal(subjectOf("/stats/"), "");
  assert.equal(subjectOf("/poe/exam-prep/x/"), "poe");
});

test("streakOf counts 2h+ days before today when today is short", () => {
  const now = new Date(2026, 10, 9, 15);
  const ms = { [dayOf(shift(now, -1))]: 2 * H, [dayOf(shift(now, -2))]: 3 * H, [dayOf(shift(now, -3))]: 2 * H, [dayOf(now)]: 0.5 * H };
  assert.equal(streakOf(d => ms[dayOf(d)] ?? 0, now), 3);
});

test("heatCells draws empty days", () => {
  assert.match(heatCells(() => 0, new Date(2026, 10, 9)), /data-level="none"/);
});

// ---- the stretches the clock counted (study.spans), read by pm to count overlap with its timer once ----
const S = load(["study.js", "today.js"], { path: "/os/", expose: ["spanAdd", "spanSave", "studyMs", "dayOf", "shift"] });
const plain = x => JSON.parse(JSON.stringify(x));  // arrays made inside the vm have another realm's prototype

test("spanAdd grows the last stretch, bridges two idle minutes and starts a new one after three", () => {
  const list = [];
  assert.equal(S.spanAdd(list, 600), true);
  assert.deepEqual(plain(list), [[600, 601]]);
  assert.equal(S.spanAdd(list, 600), false);  // the same minute again: nothing to write
  S.spanAdd(list, 601);
  assert.deepEqual(plain(list), [[600, 602]]);
  S.spanAdd(list, 604);  // 602 and 603 idle: bridged
  assert.deepEqual(plain(list), [[600, 605]]);
  S.spanAdd(list, 608);  // 605, 606 and 607 idle: a new stretch
  assert.deepEqual(plain(list), [[600, 605], [608, 609]]);
});

test("spanAdd leaves the list alone when the clock was set back", () => {
  const list = [[600, 605], [608, 609]];
  assert.equal(S.spanAdd(list, 603), false);
  assert.equal(S.spanAdd(list, 100), false);
  assert.deepEqual(plain(list), [[600, 605], [608, 609]]);
});

test("spanSave writes today's stretches once a minute and keeps 60 days", () => {
  const noon = new Date(2026, 10, 9), at = (h, m, s = 0) => new Date(2026, 10, 9, h, m, s).getTime(), old = {};
  for (let i = 1; i <= 60; i++) old[S.dayOf(S.shift(noon, -i))] = [[0, 1]];
  S.localStorage.setItem("study.spans", JSON.stringify(old));
  S.spanSave(at(10, 0));
  const first = S.localStorage.getItem("study.spans");
  S.spanSave(at(10, 0, 30));
  assert.equal(S.localStorage.getItem("study.spans"), first);
  S.spanSave(at(10, 1)); S.spanSave(at(10, 10)); S.spanSave(at(23, 59));
  const spans = JSON.parse(S.localStorage.getItem("study.spans"));
  assert.deepEqual(spans["2026-11-09"], [[600, 602], [610, 611], [1439, 1440]]);
  assert.equal(Object.keys(spans).length, 60);
  assert.equal(spans[S.dayOf(S.shift(noon, -60))], undefined);
});

test("spanSave starts over from a stored value that is not a list of days", () => {
  ["[]", '"x"', "5", '{"2026-11-08": "x"}'].forEach((bad, i) => {  // junk inside a day's list stays: pm drops that day
    S.localStorage.setItem("study.spans", bad);
    S.spanSave(new Date(2026, 10, 8, 8, 10 * i).getTime());  // a new minute each time, three or more apart
    assert.deepEqual(JSON.parse(S.localStorage.getItem("study.spans"))["2026-11-08"], [[480 + 10 * i, 481 + 10 * i]], bad);
  });
});

test("studyMs is the larger of this browser's clock and pm's combined minutes", () => {
  const d = new Date(2026, 10, 9), log = { "2026-11-09": { os: H } };
  assert.equal(S.studyMs(log, null, d), H);
  assert.equal(S.studyMs(log, { days: { "2026-11-09": { study: 150 } } }, d), 150 * 60e3);
  assert.equal(S.studyMs(log, { days: { "2026-11-09": { study: 30 } } }, d), H);
  assert.equal(S.studyMs({}, { days: { "2026-11-09": { study: "x" } } }, d), 0);
});

test("statsRepaint redraws the home box once, with pm's minutes, and never throws", () => {
  const X = load(["study.js", "today.js"], { path: "/", expose: ["statsRepaint", "dayOf", "document"] });
  const summary = { innerHTML: "" }, kids = [summary];
  const box = {
    get children() { return kids; },
    querySelector: s => (s === "summary" ? summary : null),
    insertAdjacentHTML(_, html) { kids.push({ html, remove() { kids.splice(kids.indexOf(this), 1); } }); },
  };
  X.document.querySelector = s => (s.includes("details.study-stats") ? box : null);
  const today = X.dayOf(new Date());
  X.statsRepaint({ days: { [today]: { study: 150 } } });
  X.statsRepaint({ days: { [today]: { study: 150 } } });
  assert.equal(kids.length, 2);  // the summary and one body, not two
  assert.match(summary.innerHTML, /1-day streak/);
  assert.match(kids[1].html, /Today<\/small><b data-level="green">2h 30m</);
  for (const bad of [null, 5, { days: "x" }, { days: { [today]: { study: "<b>" } } }, { days: { [today]: { study: -5 } } }])
    assert.doesNotThrow(() => X.statsRepaint(bad));
  assert.match(kids[1].html, /Today<\/small><b data-level="none">0m</);
  X.document.querySelector = () => { throw new Error("no page"); };
  assert.doesNotThrow(() => X.statsRepaint({ days: {} }));
});
