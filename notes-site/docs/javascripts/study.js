// Study helpers: "Mark as done" + progress bars, "Continue where you left off",
// reading time, a Focus button, keyboard shortcuts and practice mode. Progress lives in this browser's
// localStorage (not synced between devices); backup.js keeps an online copy.

const DONE_KEY = "study.done", LAST_KEY = "study.last", FOCUS_KEY = "study.focus";

function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: just don't remember */ }
}
const doneSet = () => new Set(load(DONE_KEY, []));
const pathOf = a => new URL(a.href, location.href).pathname;
const countUnder = (done, prefix) => [...done].filter(p => p.startsWith(prefix)).length;

function bar(done, total) {
  const pct = total ? Math.min(100, Math.round(100 * done / total)) : 0;
  return `<div class="study-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>`;
}

function markSidebar(done) {
  document.querySelectorAll(".md-nav--primary a.md-nav__link[href]").forEach(a =>
    a.classList.toggle("study-done", !a.hash && done.has(pathOf(a))));  // a.hash: the page's own ToC links
}

function notePage(content, done) {
  const h1 = content.querySelector("h1");
  if (!h1 || h1.textContent.startsWith("404")) return;
  const here = location.pathname;
  const words = content.innerText.trim().split(/\s+/).length;
  const row = document.createElement("div");
  row.className = "study-meta";
  row.innerHTML = `<span>⏱ ${Math.max(1, Math.round(words / 200))} min read</span><button class="study-btn" type="button"></button>`;
  const btn = row.querySelector("button");
  const paint = on => { btn.classList.toggle("on", on); btn.textContent = on ? "✓ Done" : "Mark as done"; btn.setAttribute("aria-pressed", on); };
  btn.title = "Shortcut: D";
  paint(done.has(here));
  btn.addEventListener("click", () => {
    const d = doneSet();
    d.has(here) ? d.delete(here) : d.add(here);
    save(DONE_KEY, [...d]);
    paint(d.has(here));
    markSidebar(d);
  });
  h1.after(row);
  const where = [...document.querySelectorAll(".md-path__link")].slice(1).map(a => a.textContent.trim()).join(" · ");
  save(LAST_KEY, { path: here, title: h1.textContent.replace("¶", "").trim(), where });
}

function folderCards(content, done) {
  // section/subject cards: "N notes" is written by make_indexes.py
  content.querySelectorAll(".grid.cards:not(.compact) > ul > li").forEach(li => {
    const a = li.querySelector("a[href]"), count = li.querySelector("p:last-child");
    const total = parseInt(count?.textContent, 10);
    if (!a || !total) return;
    const n = Math.min(total, countUnder(done, pathOf(a).replace(/[^/]*$/, "")));
    count.insertAdjacentHTML("beforebegin", bar(n, total));
    if (n) count.insertAdjacentHTML("beforeend", ` · ${n} done`);
  });
  content.querySelectorAll(".grid.cards.compact > ul > li").forEach(li => {
    const a = li.querySelector("a[href]");
    li.classList.toggle("study-done", !!a && done.has(pathOf(a)));
  });
}

function indexPage(content, done, progress) {
  const total = +progress.dataset.total;
  const n = Math.min(total, countUnder(done, location.pathname));
  progress.innerHTML = `${bar(n, total)}<span><b>${n} / ${total}</b> done</span>`;
  folderCards(content, done);
}

function homePage(content, done, cont) {
  const last = load(LAST_KEY, null);
  if (last && last.path) {
    const a = document.createElement("a");
    a.href = last.path; a.className = "study-continue-card";
    a.innerHTML = `<span><small>Continue where you left off</small><b></b><small></small></span><span class="study-go">Resume →</span>`;
    a.querySelector("b").textContent = last.title;
    a.querySelectorAll("small")[1].textContent = last.where || "";
    cont.replaceChildren(a);
    cont.hidden = false;
  }
  folderCards(content, done);
}

function focusButton() {
  document.documentElement.classList.toggle("study-focus", load(FOCUS_KEY, false));
  if (document.querySelector(".study-focus-btn")) return;
  const search = document.querySelector(".md-header .study-search-btn");
  if (!search) return;
  const btn = document.createElement("button");
  btn.type = "button"; btn.className = "study-focus-btn";
  btn.title = "Focus mode: hide the sidebars (Z)";
  btn.textContent = "⤢ Focus";
  btn.addEventListener("click", toggleFocus);
  search.before(btn);
}

function toggleFocus() {
  save(FOCUS_KEY, document.documentElement.classList.toggle("study-focus"));
}

// Keyboard shortcuts (press ? for the list). Ignored while typing or with Ctrl/Cmd/Alt held.
const KEYS = {
  z: toggleFocus,
  d: () => document.querySelector(".study-meta .study-btn:not(.study-today-btn)")?.click(),
  t: () => document.querySelector(".study-today-btn")?.click(),  // today.js
  ArrowLeft: () => document.querySelector(".md-footer__link--prev")?.click(),
  ArrowRight: () => document.querySelector(".md-footer__link--next")?.click(),
  "?": toggleHelp,
};
const typing = t => t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
document.addEventListener("keydown", e => {
  const t = e.composedPath()[0];  // the real element, even inside the search box's shadow DOM
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (!KEYS[key] || e.ctrlKey || e.metaKey || e.altKey || e.repeat || typing(t)) return;
  const arrow = key.startsWith("Arrow");
  if (arrow && (e.shiftKey || t.closest?.("pre, table, .md-typeset__scrollwrap"))) return;  // keep text selection and sideways scrolling
  if (help?.open && key !== "?") return;
  if (arrow) e.preventDefault();
  KEYS[key]();
});

let help;
function toggleHelp() {
  if (!help?.isConnected) {
    help = document.createElement("dialog");
    help.className = "study-help";
    const rows = [["/", "Search"], ["Z", "Focus mode"], ["D", "Mark note as done"], ["T", "Add note to today's list"],
                  ["← →", "Previous / next note"], ["?", "Show this list"], ["Esc", "Close"]];
    help.innerHTML = `<h2>Keyboard shortcuts</h2><table>${rows.map(([k, v]) => `<tr><td><kbd>${k}</kbd></td><td>${v}</td></tr>`).join("")}</table>` +
                     `<form method="dialog"><button class="study-btn">Close</button></form>`;
    help.addEventListener("click", e => e.target === help && help.close());  // click outside the box
    document.body.append(help);
  }
  help.open ? help.close() : help.showModal();
}

// Practice mode: on pages of Q1/Q2-style questions, answers start hidden behind "Show answer".
// Answers come from the page itself ("**Answer**" / "**Solution**" / "**Model answer**" paragraphs,
// or whatever follows a question quoted in a > block) or, for test pages, from the matching key page.
const KEY_PAGES = [[/-test\/$/, "-key/"], [/-quiz\/$/, "-quiz-answers/"], [/-qns\/$/, "-ans/"],
                   [/\/exam-qns-([^/]+)\/$/, "/exam-ans-key-$1/"]];
const levelOf = el => +(/^H(\d)$/.exec(el.tagName)?.[1] ?? 7);  // paragraphs etc. count as 7

function qId(el) {
  // "### Q3 ..." heading, or a paragraph opening with bold "Q3." / "Q3 — B." / "3. (C)" (not "8.2 < 13.2")
  if (/^H[2-5]$/.test(el.tagName)) return el.textContent.match(/^Q(\d+(?:\.\d+)?)\b/)?.[1];
  const b = el.tagName === "P" && el.firstChild === el.firstElementChild && el.firstElementChild;
  const m = b?.tagName === "STRONG" && b.textContent.match(/^(?:Q(\d+(?:\.\d+)?)(?=[.):]?(?:\s|$))|(\d+)[.)](?:\s|$))/);
  return m ? m[1] ?? m[2] : undefined;
}
const isAnswer = el => el.tagName === "P" && el.firstChild?.tagName === "STRONG" &&
  /^(Answers?|Solution|Model answer)\b/.test(el.firstChild.textContent);
const ends = (el, level) => el.tagName === "HR" || qId(el) || (/^H\d$/.test(el.tagName) && levelOf(el) <= level);

function blockAfter(start) {  // start's siblings up to the next question, a heading at its level or above, or a rule
  const out = [], level = levelOf(start);
  for (let el = start.nextElementSibling; el && !ends(el, level); el = el.nextElementSibling) out.push(el);
  return out;
}

function answerBox(nodes) {
  const box = document.createElement("details");
  box.className = "study-answer";
  box.innerHTML = "<summary>Show answer</summary>";
  box.append(...nodes);
  box.addEventListener("toggle", () => box.firstChild.textContent = box.open ? "Hide answer" : "Show answer");
  return box;
}

function inlineAnswers(content) {
  const kids = [...content.children];
  if (kids.filter(qId).length < 2) return [];
  const boxes = [];
  let level = 0;  // 0 until the first question: an "**Answer template**" tip above it stays visible
  for (let i = 0; i < kids.length; i++) {
    if (qId(kids[i])) level = levelOf(kids[i]);
    const quoted = kids[i - 1]?.tagName === "BLOCKQUOTE" && /^H/.test(kids[i - 2]?.tagName) && qId(kids[i - 2]);  // "### Q4" + "> question" + solution
    if (!level || !(isAnswer(kids[i]) || quoted) || ends(kids[i], level)) continue;
    let j = i + 1;
    while (j < kids.length && !ends(kids[j], level)) j++;
    const box = answerBox([]);
    kids[i].before(box);
    box.append(...kids.slice(i, j));
    boxes.push(box);
    i = j - 1;
  }
  return boxes;
}

async function keyAnswers(content) {
  const rule = KEY_PAGES.find(([re]) => re.test(location.pathname));
  if (!rule) return [];
  const res = await fetch(location.pathname.replace(...rule)).catch(() => null);
  if (!res?.ok) return [];
  const key = new DOMParser().parseFromString(await res.text(), "text/html").querySelector(".md-content .md-typeset");
  const answers = new Map();
  for (const el of key?.children ?? []) {
    const id = qId(el);
    if (id && !answers.has(id)) answers.set(id, [el, ...blockAfter(el)]);
  }
  const boxes = [];
  for (const q of [...content.children].filter(qId)) {
    const ans = answers.get(qId(q));
    if (!ans) continue;
    const box = answerBox(ans);
    (blockAfter(q).at(-1) ?? q).after(box);
    boxes.push(box);
  }
  if (boxes.length && window.MathJax?.typesetPromise) MathJax.startup.promise.then(() => MathJax.typesetPromise(boxes));
  else if (boxes.length) renderMath();  // from mathjax.js: loads MathJax, which then typesets the whole page
  return boxes;
}

async function practice(content) {
  if (/(-key|-answers|-ans|\/exam-ans-key-[^/]+)\/$/.test(location.pathname)) return;  // answer keys stay open
  const boxes = inlineAnswers(content);
  if (!boxes.length) boxes.push(...await keyAnswers(content));
  if (!boxes.length) return;
  const bar = document.createElement("div");
  bar.className = "study-practice";
  bar.innerHTML = `<span>🎯 Practice mode · ${boxes.length} answers hidden</span><button class="study-btn" type="button">Show all</button>`;
  const btn = bar.querySelector("button");
  btn.addEventListener("click", () => {
    const open = btn.textContent === "Show all";
    boxes.forEach(b => b.open = open);
    btn.textContent = open ? "Hide all" : "Show all";
  });
  (content.querySelector(".study-meta") ?? content.querySelector("h1"))?.after(bar);
}

function studyPage() {
  const content = document.querySelector(".md-content .md-typeset");
  if (!content) return;
  const done = doneSet();
  focusButton();
  markSidebar(done);
  const progress = content.querySelector(".study-progress");
  const cont = content.querySelector(".study-continue");
  if (cont) homePage(content, done, cont);
  else if (progress) indexPage(content, done, progress);
  else if (content.querySelector(".study-pm")) return;  // the stats page (pmstats.js) is not a note
  else { notePage(content, done); practice(content); }
}

if (typeof document$ !== "undefined") document$.subscribe(studyPage);  // runs again after instant page switches
else document.addEventListener("DOMContentLoaded", studyPage);
