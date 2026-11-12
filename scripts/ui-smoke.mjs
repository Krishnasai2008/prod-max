// Browser smoke test for `pm ui`: node scripts/ui-smoke.mjs
// Seeds a throwaway database, starts `pm ui` and headless Firefox (WebDriver BiDi, Node's built-in
// WebSocket), clicks through the screens, and exits non-zero if any check fails. Never touches the
// real database. Skips (exit 0) when Firefox is not installed. Screenshots go to the printed folder.
// shortcut: needs Firefox and a free port 8398/9223; not run by the unittest suite, run it by hand
// after UI changes.
import { execFileSync, spawn } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const PORT = Number(process.env.UI_SMOKE_PORT ?? 8398);
const BIDI = Number(process.env.UI_SMOKE_BIDI ?? 9223);
const U = `http://127.0.0.1:${PORT}`;
const dir = mkdtempSync(join(tmpdir(), "pm-ui-smoke-"));
const env = { ...process.env, PM_DB: join(dir, "pm.db") };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pm = (...args) => execFileSync("uv", ["run", "pm", ...args], { cwd: ROOT, env, encoding: "utf8" }).trim();
let failed = 0;
const check = (name, ok, extra = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? ` (${extra})` : ""}`);
};

try {
  execFileSync("firefox", ["--version"], { stdio: "ignore" });
} catch {
  console.log("skip: firefox is not installed");
  process.exit(0);
}

const children = [];
async function main() {
  pm("add", "OS lab 3", "--est", "4h", "--due", "+3", "--course", "os", "--kind", "lab", "--first", "open the handout");
  pm("add", "<img src=x onerror=alert(1)> & co", "--est", "30m", "--shallow", "--due", "+5");
  pm("add", "DBMS quiz", "--est", "1h", "--due", "+1", "--course", "db");
  // study items: a question/answer note with maths, a plain note with a table, a PDF page
  writeFileSync(join(dir, "qa.md"), "# Q1\nWhat is $x^2$ when $x = 3$?\n\n**Answer.** It is 9, a cache of nothing.\n");
  writeFileSync(join(dir, "notes.md"), "# TLB\n\n| hit | miss |\n|---|---|\n| 1 ns | 100 ns |\n");
  writeFileSync(join(dir, "slides.ps"), "%!PS\n/Helvetica findfont 24 scalefont setfont\n" +
    "72 700 moveto (Page one) show showpage\n72 700 moveto (Page two) show showpage\n");
  execFileSync("ps2pdf", [join(dir, "slides.ps"), join(dir, "slides.pdf")]);
  writeFileSync(join(dir, "long.md"), Array.from({ length: 14 }, (_, i) => `## Part ${i + 1}\na\nb\nc\n`).join("\n"));
  pm("topic", "add", "paging", "--course", "os", "--exam", "+10");
  pm("study", "add", `${join(dir, "qa.md")}#Q1`, "--topic", "paging");
  pm("study", "add", `${join(dir, "notes.md")}#TLB`, "--topic", "paging");
  pm("study", "add", `${join(dir, "slides.pdf")}#p2`, "--topic", "paging");
  // a bug episode: a failing run in a git folder, then a fix whose diff holds markup
  const proj = join(dir, "proj");
  mkdirSync(proj);
  const git = (...a) => execFileSync("git", ["-C", proj, "-c", "user.name=t", "-c", "user.email=t@t", ...a], { stdio: "ignore" });
  writeFileSync(join(proj, "a.c"), "int x = 0;\n");
  git("init", "-q");
  git("add", ".");
  git("commit", "-qm", "a");
  const pmIn = (...args) => execFileSync("uv", ["run", "--project", ROOT, "pm", ...args], { cwd: proj, env, stdio: "ignore" });
  const test = ["run", "--", "grep", "-q", "x = 1", "a.c"]; // an episode is one command failing, then passing
  try { pmIn(...test); } catch { /* the failing run is the point */ }
  writeFileSync(join(proj, "a.c"), "int x = 1; // <script>alert(1)</script>\n");
  pmIn(...test);
  // watched files, indexed with files.scan directly (pm watch --once could also send a desktop nudge)
  const watched = join(dir, "watched");
  mkdirSync(watched);
  const seeded = { "os-paging.md": "# Paging\nThe translation lookaside buffer caches <b>page</b> entries.\n",
    "db-joins.txt": "hash joins use translation tables\n", "build.sh": "echo translation\n" };
  const settled = new Date(Date.now() - 3600e3); // scan skips files changed in the last 10 s
  for (const [name, body] of Object.entries(seeded)) {
    writeFileSync(join(watched, name), body);
    utimesSync(join(watched, name), settled, settled);
  }
  pm("set", "watch", watched);
  execFileSync("uv", ["run", "python", "-c", "from datetime import datetime; from pm.db import connect, default_path;"
    + " from pm.files import scan; scan(connect(default_path()), datetime.now())"], { cwd: ROOT, env });

  children.push(spawn("uv", ["run", "pm", "ui", "--port", String(PORT), "--no-open"], { cwd: ROOT, env, stdio: "ignore" }));
  children.push(spawn("firefox", ["--headless", "--no-remote", "--profile", mkdtempSync(join(dir, "ff-")),
    "--remote-debugging-port", String(BIDI)], { stdio: "ignore" }));
  for (let i = 0; i < 60; i++) {
    const up = await Promise.all([fetch(`${U}/api/ping`), fetch(`http://127.0.0.1:${BIDI}/`)].map((p) => p.then(() => true, () => false)));
    if (up.every(Boolean)) break;
    await sleep(500);
  }

  // --- WebDriver BiDi client ---
  const ws = new WebSocket(`ws://127.0.0.1:${BIDI}/session`);
  let id = 0;
  const pending = new Map();
  const logs = [];
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      const { ok, bad } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.type === "error" ? bad(new Error(`${msg.error}: ${msg.message}`)) : ok(msg.result);
    } else if (msg.method === "log.entryAdded" && ["error", "warn"].includes(msg.params.level)) {
      logs.push(msg.params.text);
    }
  };
  const send = (method, params = {}) => new Promise((ok, bad) => {
    const n = ++id;
    pending.set(n, { ok, bad });
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  await send("session.new", { capabilities: {} });
  await send("session.subscribe", { events: ["log.entryAdded"] });
  const { context } = await send("browsingContext.create", { type: "tab" });
  const go = (path) => send("browsingContext.navigate", { context, url: U + path, wait: "complete" });
  const size = (width, height) => send("browsingContext.setViewport", { context, viewport: { width, height } });
  const js = async (expression) => {
    const r = await send("script.evaluate", { expression, target: { context }, awaitPromise: true });
    if (r.type === "exception") throw new Error(`${r.exceptionDetails.text} in: ${expression}`);
    return r.result?.value;
  };
  const until = async (expression, ms = 5000) => {
    for (const end = Date.now() + ms; Date.now() < end; await sleep(100)) {
      if (await js(expression).catch(() => false)) return true;
    }
    return false;
  };
  const shot = async (name) => {
    const { data } = await send("browsingContext.captureScreenshot", { context, origin: "document" });
    writeFileSync(join(dir, `${name}.png`), Buffer.from(data, "base64"));
  };
  const text = `document.querySelector('#screen').textContent`;
  const state = (expr) => js(`fetch("/api/state").then(r => r.json()).then(s => ${expr})`);
  const refreshNow = `document.dispatchEvent(new Event("visibilitychange"))`;

  // --- Today ---
  await size(1280, 1000);
  await go("/#/today");
  check("today renders the plan", await until(`${text}.includes("Deep work")`));
  check("xss title is not markup", (await js(`document.querySelectorAll("#screen img").length`)) === 0);
  await shot("today");
  await js(`document.querySelector('#screen button[data-act="start"]').click()`);
  check("start shows the clock", await until(`!!document.querySelector('#screen [data-elapsed]')`));
  const c1 = await js(`document.querySelector('#screen [data-elapsed]').textContent`);
  check("clock ticks", await until(`document.querySelector('#screen [data-elapsed]').textContent !== ${JSON.stringify(c1)}`, 3000));
  check("header chip shown", await js(`!document.querySelector('#timer-chip').hidden`));
  await js(`document.querySelector('#screen input[name="note"]').click()`);
  await sleep(500);
  check("click in the note field keeps the timer", await js(`!!document.querySelector('#screen [data-elapsed]')`));
  await js(`(() => { const f = document.querySelector('#screen input[name="note"]'); f.value = "stuck on fork"; f.dispatchEvent(new Event("input", {bubbles: true})); })()`);
  pm("log", "2", "10m");
  await js(refreshNow);
  await sleep(1000);
  check("typed note survives a refresh", (await js(`document.querySelector('#screen input[name="note"]').value`)) === "stuck on fork");
  const running = await state("s.running.task_id");
  await js(`document.querySelector('#screen form[data-act="stop"]').requestSubmit()`);
  check("stop", await until(`document.querySelector('#timer-chip').hidden`));
  check("stop saved the note", (await state(`s.tasks.find(t => t.id === ${running}).note`)) === "stuck on fork");
  pm("start", "1");
  await js(refreshNow);
  check("a timer started in the terminal shows", await until(`!document.querySelector('#timer-chip').hidden`));
  await js(`document.querySelector('#timer-chip button[data-act="stop"]').click()`);
  check("header stop", await until(`document.querySelector('#timer-chip').hidden`));

  // --- Tasks ---
  await go("/#/tasks");
  await until(`!!document.querySelector('form[data-act="add"]')`);
  const before = await state("s.tasks.length");
  await js(`(() => { const f = document.querySelector('form[data-act="add"]');
    f.title.value = "New from page"; f.est.value = "2h"; f.due.value = "+4"; f.requestSubmit(); f.requestSubmit(); })()`);
  check("add (double submit adds one)", await until(`${text}.includes("New from page")`) && (await state("s.tasks.length")) === before + 1);
  await js(`(() => { const f = document.querySelector('form[data-act="add"]'); f.title.value = "Bad"; f.est.value = "soon"; f.requestSubmit(); })()`);
  check("bad input toasts", await until(`/bad duration/.test(document.querySelector('#toast').textContent)`));
  check("bad input keeps the text", (await js(`document.querySelector('form[data-act="add"]').title.value`)) === "Bad");
  await js(`(() => { const f = document.querySelector('form[data-act="add"]'); f.title.value = ""; f.est.value = "";
    const r = f.querySelector('input[value="shallow"]'); r.checked = true; r.dispatchEvent(new Event("change", {bubbles: true})); })()`);
  pm("log", "1", "5m");
  await js(refreshNow);
  await sleep(1000);
  check("a radio choice survives a refresh", await js(`document.querySelector('form[data-act="add"] input[value="shallow"]').checked`));
  await js(`(() => { const r = document.querySelector('form[data-act="add"] input[value="deep"]'); r.checked = true; r.dispatchEvent(new Event("change", {bubbles: true})); })()`);
  const newId = await state(`s.tasks.find(t => t.title === "New from page").id`);
  await js(`document.querySelector('button[data-act="edit"][data-id="${newId}"]').click()`);
  check("edit opens", await until(`!!document.querySelector('form[data-act="save"]')`));
  await js(`(() => { const f = document.querySelector('form[data-act="save"]'); f.title.value = "Renamed"; f.requestSubmit(); })()`);
  check("edit saves", await until(`${text}.includes("Renamed") && !document.querySelector('form[data-act="save"]')`));
  await js(`document.querySelector('button[data-act="edit"][data-id="2"]').click()`);
  check("estimate locked once time is logged", await until(`document.querySelector('form[data-act="save"] input[name="est"]')?.disabled === true`));
  await shot("tasks-edit");
  await js(`document.querySelector('button[data-act="cancel"]').click()`);
  check("cancel", await until(`!document.querySelector('form[data-act="save"]')`));
  await js(`window.confirm = () => true; document.querySelector('button[data-act="drop"][data-id="${newId}"]').click()`);
  check("drop", await until(`!${text}.includes("Renamed")`));
  pm("done", "3");
  await js(refreshNow);
  check("a task finished in the terminal shows in Recently finished", await until(`[...document.querySelectorAll('#screen li')].some(li => li.textContent.includes("DBMS quiz"))`));
  const stale = await js(`fetch("/api/tasks/3/log", {method: "POST", headers: {"Content-Type": "application/json"}, body: '{"duration":"10m"}'}).then(r => r.status)`);
  check("logging onto a finished task is refused", stale === 400, String(stale));
  await js(`Promise.all([...Array(10)].map((_, i) => fetch("/api/tasks/" + (i % 2 ? 1 : 2) + "/start",
    {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})))`);
  const open = execFileSync("sqlite3", [env.PM_DB, "select count(*) from sessions where end is null"], { encoding: "utf8" }).trim();
  check("10 concurrent starts leave one running timer", open === "1", open);
  pm("stop");

  // --- Review ---
  const key = (k) => js(`document.dispatchEvent(new KeyboardEvent("keydown", {key: ${JSON.stringify(k)}, cancelable: true}))`);
  await go("/#/review");
  check("review shows the question", await until(`${text}.includes("when")`));
  check("review hides the answer before the bet", !(await js(`${text}.includes("cache of nothing")`)));
  check("review typesets the question (MathJax from the CDN, needs the network)", await until(`!!document.querySelector('#screen mjx-container')`, 20000));
  await js(`document.activeElement?.blur()`);
  await key("7");
  check("key 7 sets 70%", await until(`document.querySelector('#confidence-value')?.textContent === "70%"`));
  check("space is taken by the screen (no page scroll)", (await key(" ")) === false);
  check("space reveals the answer", await until(`${text}.includes("cache of nothing")`));
  check("grade buttons show intervals", await js(`[...document.querySelectorAll('#screen [data-act="grade"]')].every(b => b.textContent.includes("·"))`));
  await key("3");
  check("key 3 grades and moves on", await until(`${text}.includes("TLB") && !${text}.includes("cache of nothing")`));
  await key(" ");
  check("markdown answer renders a table", await until(`!!document.querySelector('#screen .md table')`));
  await shot("review-reveal");
  await js(`document.querySelector('#screen [data-act="grade"][data-grade="4"]').click()`);
  check("pdf item reached", await until(`${text}.includes("p2")`));
  await key(" ");
  check("pdf page shows as an image", await until(`document.querySelector('#screen img.page')?.naturalWidth > 0`, 8000));
  await js(`document.querySelector('#screen [data-act="suspend"]').click()`);
  check("suspend ends the session", await until(`${text}.includes("reviewed 2")`));
  check("two reviews saved", /reviews 2/.test(pm("study", "calib")));
  writeFileSync(join(dir, "gone.md"), "# Gone\nwill be renamed\n");
  pm("study", "add", `${join(dir, "gone.md")}#Gone`, "--topic", "paging");
  rmSync(join(dir, "gone.md"));
  await go("/#/today");
  await go("/#/review");
  check("an item whose file is gone still comes up", await until(`${text}.includes("gone.md")`));
  await js(`document.activeElement?.blur()`);
  await key(" ");
  check("its excerpt says it can't be shown", await until(`${text}.includes("can't show this item") && ${text}.includes("no such file")`));
  await key("1");
  check("and it can still be graded", await until(`${text}.includes("reviewed 1")`) && /reviews 3/.test(pm("study", "calib")));

  // --- Study ---
  await js(`document.activeElement?.blur()`);
  await key("4");
  check("key 4 goes to Study", await until(`location.hash === "#/study" && ${text}.includes("Topics by course")`));
  check("study next names the topic", await js(`${text}.includes("os / paging")`));
  check("a topic shows the parts of its mastery", await js(`["memory", "understanding", "application"].every(n => [...document.querySelectorAll('#screen .facet-name')].some(e => e.textContent === n))`));
  check("calibration counts the reviews", await js(`${text}.includes("3 reviews")`));
  await js(`(() => { const f = document.querySelector('form[data-act="addTopic"]');
    f.name.value = "tlb"; f.course.value = "os"; f.course.dispatchEvent(new Event("input", {bubbles: true})); f.exam.value = "+12";
    [...f.needs.options].find(o => o.value === "paging").selected = true; f.requestSubmit(); })()`);
  check("add topic with a prerequisite draws the graph", await until(`!!document.querySelector('#screen .graph svg') && ${text}.includes("tlb")`));
  check("graph marks the next pick", await js(`!!document.querySelector('#screen .graph svg g.next')`));
  await js(`document.querySelector('#screen [data-act="editTopic"]').click()`);
  check("topic edit opens", await until(`!!document.querySelector('form[data-act="saveTopic"]')`));
  await js(`(() => { const f = document.querySelector('form[data-act="saveTopic"]'); f.weight.value = "3"; f.requestSubmit(); })()`);
  check("topic edit saves", await until(`!document.querySelector('form[data-act="saveTopic"]')`) && /weight 3 /.test(pm("topic", "ls")));

  // --- add-to-study dialog ---
  const dlg = `document.querySelector('#addstudy')`;
  await js(`document.querySelector('#screen [data-act="addFromFile"]').click()`);
  check("dialog opens", await until(`${dlg}.open && !!${dlg}.querySelector('input[name="path"]')`));
  await js(`(() => { const f = ${dlg}.querySelector('input[name="path"]'); f.value = ${JSON.stringify(join(dir, "long.md"))};
    f.dispatchEvent(new Event("input", {bubbles: true})); ${dlg}.querySelector('[data-act="outline"]').click(); })()`);
  check("dialog lists the sections", await until(`${dlg}.querySelectorAll('input[type="checkbox"]').length === 14 && ${dlg}.textContent.includes("14 of 14 selected")`));
  check("dialog warns about the daily cap", await js(`${dlg}.textContent.includes("14 items: 10 will come up each day")`));
  await js(`(() => { const l = ${dlg}.querySelector('.sections'); l.scrollTop = l.scrollHeight;
    const c = ${dlg}.querySelector('#addstudy-s-13'); c.focus(); c.click(); })()`);
  check("checkbox click updates the count", await until(`${dlg}.textContent.includes("13 of 14 selected")`));
  check("checkbox click keeps focus and scroll", await js(`document.activeElement?.id === "addstudy-s-13" && ${dlg}.querySelector('.sections').scrollTop > 0`));
  await js(`document.dispatchEvent(new KeyboardEvent("keydown", {key: "1"}))`);
  check("keys are ignored while the dialog is open", (await js(`location.hash`)) === "#/study");
  await js(`(() => { const s = ${dlg}.querySelector('select[name="topic"]'); s.value = "new"; s.dispatchEvent(new Event("change", {bubbles: true})); })()`);
  await until(`!!${dlg}.querySelector('input[name="name"]')`);
  await js(`(() => { const n = ${dlg}.querySelector('input[name="name"]'); n.value = "long notes"; n.dispatchEvent(new Event("input", {bubbles: true}));
    const c = ${dlg}.querySelector('input[name="course"]'); c.value = "os"; c.dispatchEvent(new Event("input", {bubbles: true}));
    ${dlg}.querySelector('form').requestSubmit(); })()`);
  check("dialog adds into a new topic and closes", await until(`!${dlg}.open && /added 13 items/.test(document.querySelector('#toast').textContent)`));
  check("study screen shows the new topic", await until(`${text}.includes("long notes")`));
  await js(`document.querySelector('#screen [data-act="addFromFile"]').click()`);
  await until(`${dlg}.open`);
  await js(`(() => { const f = ${dlg}.querySelector('input[name="path"]'); f.value = ${JSON.stringify(join(dir, "long.md"))};
    f.dispatchEvent(new Event("input", {bubbles: true})); f.form.requestSubmit(); })()`);
  check("a section another topic has can be added to this one", await until(`${dlg}.textContent.includes("14 of 14 selected") && !${dlg}.textContent.includes("already added")`));
  await js(`(() => { const s = ${dlg}.querySelector('select[name="topic"]'); s.value = [...s.options].find((o) => o.textContent.includes("long notes")).value;
    s.dispatchEvent(new Event("change", {bubbles: true})); })()`);
  check("reopened file marks added sections", await until(`(${dlg}.textContent.match(/already added/g) ?? []).length === 13 && ${dlg}.textContent.includes("1 of 14 selected")`));
  await js(`(() => { const f = ${dlg}.querySelector('input[name="path"]'); f.value = "relative.md"; f.dispatchEvent(new Event("input", {bubbles: true})); f.form.requestSubmit(); })()`);
  check("a bad path shows its error in the dialog", await until(`${dlg}.querySelector('[role="alert"]')?.textContent.includes("full path")`));
  await shot("addstudy");
  await js(`${dlg}.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}))`);
  await js(`${dlg}.close()`);
  check("dialog closes", await until(`!${dlg}.open`));

  // --- Spot the error (a card seeded with a fake model; no real model runs) ---
  writeFileSync(join(dir, "spot.md"), "# Spot\nalpha is first\nbeta is second\ngamma is third\ndelta is fourth\n");
  pm("study", "add", join(dir, "spot.md"), "--topic", "paging");
  execFileSync("uv", ["run", "python", "-c", "from datetime import datetime; from pm.db import connect, default_path;"
    + " from pm import spot; c = connect(default_path()); i = c.execute('SELECT max(id) FROM items').fetchone()[0];"
    + " spot.make(c, i, datetime.now(), lambda p:"
    + " p.split('<excerpt>\\n')[1].split('\\n</excerpt>')[0].replace('gamma is third', 'gamma is first'))"], { cwd: ROOT, env });
  await go("/#/spot");
  check("spot shows the changed lines", await until(`${text}.includes("gamma is first") && ${text}.includes("Lock in")`));
  check("spot hides the answer before the bet", !(await js(`${text}.includes("gamma is third")`)));
  check("spot lines aren't clickable before the bet", (await js(`document.querySelectorAll('#screen [data-act="pick"]').length`)) === 0);
  await key("8");
  await key("Enter");
  check("bet makes the lines clickable", await until(`document.querySelectorAll('#screen [data-act="pick"]').length > 0`));
  // clicks again until the verdict shows: a click while the bet's refresh is still finishing is dropped
  check("pick shows right and the original line", await until(`(() => {
    [...document.querySelectorAll('#screen [data-act="pick"]')].find(b => b.textContent.includes("gamma"))?.click();
    return ${text}.includes("right") && ${text}.includes("gamma is third"); })()`));
  await shot("spot");
  await js(`document.querySelector('#screen [data-act="next"]').click()`);
  check("no more spot cards", await until(`${text}.includes("no spot cards")`));

  // --- Practice (generated problems, checked by code) ---
  pm("practice", "link", "paging", "--topic", "paging");
  await js(`document.activeElement?.blur()`);
  await key("p");
  check("key p goes to Practice", await until(`location.hash === "#/practice" && ${text}.includes("next best topic")`));
  check("practice lists the linked generator", await js(`!!document.querySelector('#screen [data-act="unlink"][data-gen="paging"]')`));
  await js(`document.querySelector('#screen form[data-act="start"]').requestSubmit()`);
  check("practice shows a problem with no answer", await until(`${text}.includes("Frames:") && !!document.querySelector('#practice-answer')`)
    && !(await js(`${text}.includes("Faults:")`)));
  await js(`(() => { const f = document.querySelector('#practice-answer'); f.value = "not a number"; f.form.requestSubmit(); })()`);
  check("a wrong answer shows the key and the steps", await until(`${text}.includes("wrong: the answer is") && ${text}.includes("Faults:")`));
  await shot("practice");
  await js(`document.querySelector('#screen [data-act="stop"]').click()`);
  check("stop goes back to the topics", await until(`${text}.includes("1 try, 0 right in 30 days")`));

  // --- LearnHarness (a fixture folder; pm only reads it) ---
  const lhDir = join(dir, "lh");
  mkdirSync(join(lhDir, "chats"), { recursive: true });
  copyFileSync(join(ROOT, "tests/lh/practice.json"), join(lhDir, "chats", "chat_practice.json"));
  const old = new Date(Date.now() - 3600_000);
  utimesSync(join(lhDir, "chats", "chat_practice.json"), old, old);
  pm("set", "lh_dir", lhDir);
  check("pm lh sync reads the fixture", pm("lh", "sync").startsWith("learnharness: 1 sessions"));
  await go("/#/today");
  await js(refreshNow);
  check("today has the study card", await until(`!!document.querySelector('#screen .study-card') && ${text}.includes("tutor next")`));
  check("today lists the unsorted session", await until(`${text}.includes("1 LearnHarness session has no topic")`));
  await js(`document.querySelector('#screen [data-act="copyOpening"]').click()`);
  check("copy opening copies or shows the text", await until(
    `document.body.textContent.includes("copied: paste it") || !!document.querySelector('#screen textarea.opening')`));
  await go("/#/study");
  check("study lists the unsorted session", await until(`!!document.querySelector('#screen form[data-act="mapSession"][data-chat="chat_practice"]')`));
  await js(`(() => { const f = document.querySelector('#screen form[data-act="mapSession"]');
    f.topic.value = [...f.topic.options].find(o => o.textContent === "os/paging").value; f.requestSubmit(); })()`);
  check("mapping removes the form", await until(`!document.querySelector('#screen form[data-act="mapSession"]')`));
  await go("/#/today");
  await js(refreshNow);
  check("today no longer lists it", await until(`!!document.querySelector('#screen .study-card') && !${text}.includes("has no topic")`));
  pm("set", "lh_dir", "");

  // --- Risk ---
  await js(`document.activeElement?.blur()`);
  await key("5");
  check("key 5 goes to Risk", await until(`location.hash === "#/risk" && !!document.querySelector('#risk-out svg')`));
  check("risk shows crunch and the queue line", await js(`${text}.includes("crunch risk") && ${text}.includes("start the queue by")`));
  await js(`(() => { const r = document.querySelector('input[name="hours"]'); r.focus(); r.value = "1";
    r.dispatchEvent(new Event("input", {bubbles: true})); window.__marker = document.querySelector('.risk-controls'); })()`);
  check("slider readout follows at once", (await js(`document.querySelector('#risk-hours-out').textContent`)) === "1 h a day");
  check("what-if patches the results", await until(`${text}.includes("at 4 h a day starting today") && ${text}.includes("Use 1 h a day")`));
  check("what-if keeps the controls and focus (no redraw)", await js(`window.__marker === document.querySelector('.risk-controls') && document.activeElement?.name === "hours"`));
  const hoursSetting = () => js(`fetch("/api/settings").then(r => r.json()).then(s => s.values.hours_per_day)`);
  check("what-if writes nothing", (await hoursSetting()) === "4");
  await js(`document.querySelector('#screen [data-act="apply"]').click()`);
  check("apply saves the hours", await until(`document.querySelector('input[name="hours"]')?.value === "1" && !document.querySelector('#screen [data-act="apply"]')`));
  check("apply saved hours_per_day", (await hoursSetting()) === "1");
  pm("set", "hours_per_day", "4");
  await shot("risk");

  // --- Stats ---
  await go("/#/stats");
  check("stats renders the tiles and heatmap", await until(`!!document.querySelector('#screen .study-heat i[data-level]') && ${text}.includes("Crunch risk")`));
  check("stats has no undefined or NaN", !(await js(`/undefined|NaN/.test(${text})`)));
  check("stats escapes titles", (await js(`document.querySelectorAll("#screen img").length`)) === 0);
  await shot("stats");

  // --- Bugs ---
  await js(`document.activeElement?.blur()`);
  await key("7");
  check("key 7 goes to Bugs", await until(`location.hash === "#/bugs" && ${text}.includes("Episodes")`));
  await js(`document.querySelector('#screen button[data-act="open"]').click()`);
  check("a bug opens with its diff", await until(`!!document.querySelector('#screen pre.diff .add')`));
  check("the diff is text, not markup", (await js(`document.querySelectorAll("#screen script").length`)) === 0
    && (await js(`document.querySelector('#screen pre.diff').textContent.includes("<script>")`)));
  const bugTags = () => js(`fetch("/api/bugs/1").then(r => r.json()).then(b => b.tags.join(","))`);
  await js(`(() => { const f = document.querySelector('#screen form[data-act="addTag"]'); f.tag.value = "off-by-one"; f.requestSubmit(); })()`);
  check("a tag is added", await until(`!!document.querySelector('#screen button[data-act="dropTag"]')`) && (await bugTags()) === "off-by-one");
  await js(`document.querySelector('#screen button[data-act="dropTag"]').click()`);
  check("a tag is removed", await until(`!document.querySelector('#screen button[data-act="dropTag"]')`) && (await bugTags()) === "");
  await shot("bugs");

  // --- Files ---
  await js(`document.activeElement?.blur()`);
  await key("/");
  check("key / goes to Files and focuses the search", await until(`location.hash === "#/files" && document.activeElement?.name === "q"`));
  check("files lists recent files", await until(`${text}.includes("recent files") && document.querySelectorAll('#screen article.file').length === 3`));
  await js(`(() => { const q = document.querySelector('#screen input[name="q"]'); window.__marker = q; q.value = "translation";
    q.dispatchEvent(new Event("input", {bubbles: true})); })()`);
  check("search patches the results", await until(`${text}.includes("3 matches") && !!document.querySelector('#files-out mark')`));
  check("search keeps the field and focus (no redraw)", await js(`window.__marker === document.querySelector('#screen input[name="q"]') && document.activeElement === window.__marker`));
  await js(refreshNow);
  await sleep(1000);
  check("a background refresh doesn't redraw under the search box", await js(`window.__marker === document.querySelector('#screen input[name="q"]') && document.activeElement === window.__marker`));
  check("snippets are text, not markup", (await js(`document.querySelectorAll("#files-out b").length`)) === 0);
  const fileCard = (name) => `[...document.querySelectorAll('#screen article.file')].find(a => a.textContent.includes(${JSON.stringify(name)}))`;
  check("a .sh file has no Open button, a note has one", await js(`!${fileCard("build.sh")}.querySelector('[data-act="open"]') && !!${fileCard("os-paging.md")}.querySelector('[data-act="open"]')`));
  await js(`(() => { const c = document.querySelector('#screen select[name="course"]'); c.value = "os"; c.dispatchEvent(new Event("input", {bubbles: true})); })()`);
  check("the course filter narrows the results", await until(`${text}.includes("1 match") && !!${fileCard("os-paging.md")}`));
  const apiFiles = (q) => fetch(`${U}/api/files?q=${encodeURIComponent(q)}`).then((r) => r.json());
  check("a query with FTS syntax doesn't fail", Array.isArray((await apiFiles('"a" AND (')).hits));
  const sh = (await apiFiles("echo")).hits.find((h) => h.name === "build.sh");
  const openSh = await fetch(`${U}/api/files/${sh.id}/open`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  check("the API refuses to open a .sh file", openSh.status === 400 && /won't open a \.sh file/.test((await openSh.json()).error));
  await shot("files");

  // --- Settings ---
  await go("/#/settings");
  check("settings lists every setting", await until(`document.querySelectorAll('#screen form[data-act="save"]').length >= 8`));
  await js(`(() => { const f = [...document.querySelectorAll('#screen form[data-act="save"]')].find(f => f.key.value === "peak");
    f.value.value = "25-30"; f.requestSubmit(); })()`);
  check("a bad peak is refused", await until(`/expected a range/.test(document.querySelector('#toast').textContent)`) && /09-12/.test(pm("today")));
  await js(`(() => { const f = [...document.querySelectorAll('#screen form[data-act="save"]')].find(f => f.key.value === "peak");
    f.value.value = "10-13"; f.requestSubmit(); })()`);
  check("a good peak is saved", await until(`/saved/.test(document.querySelector('#toast').textContent)`) && /10-13/.test(pm("today")));
  pm("set", "peak", "09-12");

  // --- keys ---
  await js(`document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent("keydown", {key: "1"}))`);
  check("key 1 goes to Today", await until(`location.hash === "#/today"`));
  await js(`document.dispatchEvent(new KeyboardEvent("keydown", {key: "n"}))`);
  check("key n focuses the new task title", await until(`location.hash === "#/tasks" && document.activeElement?.name === "title"`));
  await js(`document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent("keydown", {key: "?"}))`);
  check("key ? opens help", await until(`document.querySelector('#help').open`));
  await js(`document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}))`);

  // --- the guard, from a real HTTP client ---
  const post = (headers) => fetch(`${U}/api/tasks`, { method: "POST", headers, body: '{"title":"x","est":"1h"}' }).then((r) => r.status);
  check("cross-site POST refused", (await post({ "Content-Type": "application/json", Origin: "https://evil.example" })) === 403);
  check("text/plain POST refused", (await post({ "Content-Type": "text/plain" })) === 403);

  // --- narrow ---
  await size(390, 900);
  await go("/#/today");
  await until(`${text}.includes("day")`);
  check("narrow: no horizontal scroll", await js(`document.documentElement.scrollWidth <= innerWidth`));
  check("narrow: the nav marks Today", (await js(`document.querySelector('#nav [aria-current]')?.dataset.route`)) === "today");
  await shot("narrow-today");
  await go("/#/study");
  await until(`${text}.includes("Topics by course")`);
  check("narrow study: no horizontal scroll", await js(`document.documentElement.scrollWidth <= innerWidth`));
  await shot("narrow-study");

  check("no console errors", logs.length === 0, logs.join(" | "));
  await send("session.end").catch(() => {});
  ws.close();
}

try {
  await main();
} catch (e) {
  failed++;
  console.log(`FAIL crashed: ${e.message}`);
} finally {
  for (const c of children) c.kill();
  console.log(`${failed ? `${failed} failed` : "all passed"}; screenshots in ${dir}`);
  if (!failed) setTimeout(() => rmSync(join(dir, "pm.db"), { force: true }), 0);
  process.exitCode = failed ? 1 : 0;
}
