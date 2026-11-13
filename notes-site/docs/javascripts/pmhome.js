// Home page "Planner" box: today's plan and the reviews due, from `pm stats --push` (/api/pm), plus a small
// form that sends tasks and time back to the laptop through /api/pm-inbox (functions/_middleware.js); the
// laptop picks them up within 5 minutes and acknowledges them in its next push (pm.inbox_done).
// Needs study.js (load, save, bar), today.js (foldOut, fmt, esc, pad, dayOf, newId, H) and pmstats.js
// (txt, pct, mins, hint, days) loaded first. Classic script: every top-level name starts with plan or pmHome.

const PLAN_KEY = "study.pminbox";  // entries this browser sent that the laptop hasn't acknowledged (not backed up)
const PLAN_MAX = 100, PLAN_WAIT_MAX = 50;
const PLAN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const PLAN_OFFLINE = "Saved on this device; it will be sent next time the page loads.";
const PLAN_FULL = "Wait until your laptop picks up what's waiting, then reload.";
// shortcut: pm ui's default port, so the link misses a pm ui started with --port; push the port in /api/pm if that's needed
const PLAN_APP = "http://127.0.0.1:8321/";  // pm ui on this computer; hidden on touch screens (extra.css)

const planAgo = age => age < 60e3 ? "just now" : age < 48 * H ? fmt(age) + " ago" : days(Math.floor(age / (24 * H))) + " ago";
const planDate = iso => { const [, m, d] = String(iso).split("-").map(Number); return PLAN_MONTHS[m - 1] ? `${d} ${PLAN_MONTHS[m - 1]}` : txt(iso); };
const planLink = url => typeof url === "string" && url.startsWith("/") && !url.startsWith("//");  // a page of this site, nothing else
const planMinutes = s => { const v = String(s ?? "").trim(); const m = /^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?$/.exec(v);
  if (v.length > 20) return 0;  // pm's parse_duration: a unit is required (a bare 90 is refused), whole minutes, at most 1000h
  return v && m ? Math.round(Number(m[1] ?? 0) * 60) + Number(m[2] ?? 0) : 0; };

function planSummary(pm, now) {
  const bits = [];
  if (typeof pm?.deadlines?.crunch === "number") bits.push(`crunch ${pct(pm.deadlines.crunch)}`);
  if (typeof pm?.study?.due_now === "number") bits.push(`${pm.study.due_now} due`);
  if (pm?.generated) bits.push(`updated ${planAgo(Math.max(0, now - new Date(pm.generated)))}`);
  return `Planner <small>${bits.join(" · ")}</small>`;
}

// ---------- quick capture: pure helpers ----------
function planCheck(fields) {  // the laptop does the real check; this only catches typos before sending
  if ("title" in fields && !String(fields.title ?? "").trim()) return "Give it a title.";
  const n = planMinutes(fields.est ?? fields.duration);
  if (!(n > 0 && n <= 60000)) return "Give a length like 45m or 1h30m.";
  return null;
}

function planEntry(op, fields, now) {  // `at` is the phone's local time without a zone, as pm reads it
  const at = `${dayOf(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const entry = { id: newId(), at, op };
  for (const [k, v] of Object.entries(fields)) {
    const value = typeof v === "string" ? v.trim() : v;
    if (value !== "" && value !== undefined && value !== null) entry[k] = value;
  }
  return entry;
}

function planMerge(server, local) {  // union by id, server order first: a stale read of the inbox can't lose an entry
  const seen = new Set(), out = [];
  for (const e of [...(Array.isArray(server) ? server : []), ...local]) {
    if (!e || typeof e.id !== "string" || seen.has(e.id)) continue;
    seen.add(e.id);
    out.push(e);
  }
  return out.slice(-PLAN_MAX);
}

function planPending(local, pm) {
  const done = new Map((Array.isArray(pm?.inbox_done) ? pm.inbox_done : []).map(d => [d?.id, d]));
  const waiting = [], failed = [];
  for (const e of local) {
    const d = done.get(e.id), error = d ? d.error : e.error;  // e.error: the laptop said so on an earlier visit
    if (error) failed.push({ ...e, error });
    else if (!d) waiting.push(e);
  }
  return { waiting, failed };
}

function planEntryText(e) {
  if (e.op === "add") return `add "${txt(e.title)}" (${txt(e.est)})`;
  if (e.op === "log") return `log ${txt(e.duration)} on #${txt(e.task)}`;
  if (e.op === "done") return `finish #${txt(e.task)}`;
  return txt(e.op);
}

// ---------- the box ----------
function planItem(t) {
  const id = Number.isInteger(t.id) ? t.id : null;
  const meta = [`~${mins(t.minutes ?? 0)}`, t.due ? `due ${planDate(t.due)}` : "", t.behind ? "<b>BEHIND</b>" : ""].filter(Boolean);
  return `<li class="plan-item"><div class="plan-line"><span class="plan-title">${txt(t.title)}`
    + `${t.course ? ` <small>${txt(t.course)}</small>` : ""}</span><span class="plan-meta">${meta.join(" · ")}</span></div>`
    + (t.first ? `<small class="plan-first">${txt(t.first)}</small>` : "")
    + (id === null ? "" : `<div class="plan-acts">`  // a plain toggle: Material styles every <details> as a callout
      + `<button type="button" class="plan-btn" data-plan="time" aria-expanded="false">+ time</button>`
      + `<button type="button" class="plan-btn" data-plan="done" data-task="${id}" data-title="${txt(t.title)}">done</button>`
      + `<form class="plan-form" data-plan="log" data-task="${id}" hidden><input name="duration" placeholder="45m" size="6" aria-label="Time spent on ${txt(t.title)}">`
      + `<button type="submit" class="plan-btn">Log</button></form></div>`)
    + `</li>`;
}

function planDue(study) {
  const due = study.due;
  if (!due.length) return hint("No reviews due.");
  let html = `<ul class="plan-due">` + due.map(e => {
    const title = txt(e?.title);
    return `<li>${planLink(e?.url) ? `<a href="${txt(e.url)}">${title}</a>` : title}${e?.topic ? ` <small>${txt(e.topic)}</small>` : ""}</li>`;
  }).join("") + `</ul>`;
  if (typeof study.due_now === "number" && study.due_now > due.length) html += hint(`+ ${study.due_now - due.length} more`);
  return html;
}

function planHtml(pm, now, local = [], msg = "") {
  let html = "";
  const age = now - new Date(pm.generated);
  if (age > 26 * H) html += hint(`Your laptop last pushed ${planAgo(age)}, so this may be out of date.`);
  const today = pm.today;
  if (today && typeof today === "object") {
    const worked = Number(today.worked_min) || 0, cap = Number(today.cap_min) || 0;
    html += `<p class="study-label">${mins(worked)} of ${mins(cap)} today</p>${bar(worked, cap)}`;
    const plan = Array.isArray(today.plan) ? today.plan : [];
    html += plan.length ? `<ul class="plan-list">${plan.map(planItem).join("")}</ul>` : hint("Nothing planned for today.");
  }
  const study = pm.study;
  if (study && Array.isArray(study.due)) {
    html += `<p class="study-label">Reviews <small>${txt(study.due_now ?? study.due.length)} due</small></p>` + planDue(study);
    if (study.held > 0) html += hint(`${txt(study.held)} new ${study.held === 1 ? "item waits" : "items wait"} for another day`);
  }
  // quick capture
  const { waiting, failed } = planPending(local, pm);
  const full = waiting.length > PLAN_WAIT_MAX, off = full ? " disabled" : "";
  html += `<form class="plan-form plan-add" data-plan="add">`
    + `<input name="title" maxlength="200" placeholder="New task for pm" aria-label="New task for pm"${off}>`
    + `<input name="est" placeholder="1h" size="5" aria-label="Estimate"${off}>`
    + `<input name="due" placeholder="+3 or 2026-11-20" size="12" aria-label="Due (optional)"${off}>`
    + `<button type="submit" class="plan-btn"${off}>Add to pm</button></form>`;
  if (full) html += hint(`Your laptop hasn't picked up the last ${PLAN_WAIT_MAX} entries yet. Reload once it has.`);
  html += `<p class="plan-msg study-hint" role="status">${txt(msg)}</p>`;
  if (waiting.length) html += `<ul class="plan-pending">` + waiting.map(e => `<li>Waiting for your laptop: ${planEntryText(e)}</li>`).join("") + `</ul>`;
  if (failed.length) html += `<ul class="plan-pending plan-failed">` + failed.map(e =>
    `<li>Your laptop said: ${txt(e.error)} <button type="button" class="plan-btn" data-plan="dismiss" data-id="${txt(e.id)}">dismiss</button></li>`).join("") + `</ul>`;
  html += `<p class="plan-app study-hint"><a href="${PLAN_APP}" target="_blank" rel="noopener">Open the pm app</a> (on the laptop, while pm ui runs)</p>`;
  return html;
}

// ---------- page hook ----------
async function planSend(pm) {  // merge this browser's entries into the inbox and drop what the laptop acknowledged
  const res = await fetch("/api/pm-inbox", { cache: "no-store" }).catch(() => null);
  const body = res?.ok ? await res.json().catch(() => undefined) : undefined;
  if (body === undefined) return false;
  const server = Array.isArray(body?.items) ? body.items : [];
  const local = load(PLAN_KEY, []);  // read after the GET: an entry added meanwhile is included
  const acked = new Set([...(Array.isArray(pm?.inbox_done) ? pm.inbox_done : []).map(d => d?.id),
    ...local.filter(e => e.error).map(e => e.id)]);  // a failure this device already knows about is finished too
  const items = planMerge(server.filter(e => !acked.has(e?.id)), local.filter(e => !acked.has(e.id)));
  if (JSON.stringify(items) === JSON.stringify(server)) return true;  // nothing new: no KV write
  const put = await fetch("/api/pm-inbox", { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }) }).catch(() => null);
  return !!put?.ok;
}

async function pmHomePage() {
  const slot = document.querySelector(".md-content .md-typeset div.study-plan");
  if (!slot) return;
  const res = await fetch("/api/pm", { cache: "no-store" }).catch(() => null);
  const pm = res?.ok ? await res.json().catch(() => null) : null;
  if (!slot.isConnected) return;  // the reader already moved on to another page
  if (pm?.version !== 1) { slot.remove(); return; }  // no pm on this login (or an unknown format): no box at all
  if (typeof statsRepaint === "function") statsRepaint(pm);  // today.js: the streak box counts pm's combined minutes too
  const box = foldOut(slot, "plan", true);
  box.querySelector("summary").innerHTML = planSummary(pm, new Date());
  box.insertAdjacentHTML("beforeend", `<div class="plan-body"></div>`);
  const body = box.querySelector(".plan-body");
  if (typeof versusMount === "function") versusMount(box, pm);  // pmversus.js: the Versus box under this one, same data
  // entries the laptop applied are done; failures stay until dismissed
  const { waiting, failed } = planPending(load(PLAN_KEY, []), pm);
  save(PLAN_KEY, [...waiting, ...failed]);
  const draw = msg => { body.innerHTML = planHtml(pm, new Date(), load(PLAN_KEY, []), msg); };
  const say = msg => { body.querySelector(".plan-msg").textContent = msg; };  // keeps what the reader is typing
  const full = () => planPending(load(PLAN_KEY, []), pm).waiting.length > PLAN_WAIT_MAX;
  let sending = false, again = false;
  const send = async () => {  // one GET+PUT at a time, so an older PUT can't overwrite a newer one
    if (sending) { again = true; return; }
    sending = true;
    try {
      do {
        again = false;
        const sent = await planSend(pm), msg = body.querySelector(".plan-msg").textContent;
        // only worth a word when something of ours is still waiting
        if (!sent && planPending(load(PLAN_KEY, []), pm).waiting.length) say(PLAN_OFFLINE);
        else if (sent && msg === PLAN_OFFLINE) say("");
      } while (again);
    } finally { sending = false; }
  };
  draw("");
  send();

  body.addEventListener("submit", e => {
    const form = e.target.closest("form[data-plan]");
    if (!form) return;
    e.preventDefault();
    const fields = Object.fromEntries(new FormData(form));
    const problem = planCheck(fields);
    if (problem) { say(problem); return; }
    if (full()) { say(PLAN_FULL); return; }
    const entry = form.dataset.plan === "log"
      ? planEntry("log", { task: Number(form.dataset.task), duration: fields.duration }, new Date())
      : planEntry("add", { title: fields.title, est: fields.est, due: fields.due }, new Date());
    save(PLAN_KEY, [...load(PLAN_KEY, []), entry]);
    draw("");
    send();
  });
  body.addEventListener("click", e => {
    const button = e.target.closest("button[data-plan]");
    if (!button) return;
    if (button.dataset.plan === "time") {
      const form = button.closest(".plan-acts").querySelector("form"), show = form.hidden;
      form.hidden = !show;
      button.setAttribute("aria-expanded", String(show));
      if (show) form.querySelector("input").focus();
    } else if (button.dataset.plan === "dismiss") {
      save(PLAN_KEY, load(PLAN_KEY, []).filter(x => x.id !== button.dataset.id));
      draw("");
    } else if (button.dataset.plan === "done") {
      if (full()) { say(PLAN_FULL); return; }
      if (!confirm(`Mark "${button.dataset.title}" as done in pm?`)) return;
      save(PLAN_KEY, [...load(PLAN_KEY, []), planEntry("done", { task: Number(button.dataset.task) }, new Date())]);
      draw("");
      send();
    }
  });
}

if (typeof document$ !== "undefined") document$.subscribe(pmHomePage);  // after pmstats.js: runs again after instant page switches
else document.addEventListener("DOMContentLoaded", pmHomePage);
