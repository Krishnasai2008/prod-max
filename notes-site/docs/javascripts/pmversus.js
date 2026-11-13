// Home page "Versus" box: a study scoreboard between you and friends, from the optional `versus` key of the
// /api/pm summary the Planner box already fetched (pmhome.js calls versusMount; no fetch of its own). Anything
// missing or malformed draws nothing. Needs today.js (foldOut, fmt, esc, H), pmstats.js (txt, mins, hint, days)
// and pmhome.js (planAgo, planDate) loaded first. Classic script: every top-level name starts with versus.

const versusNum = v => Number.isFinite(Number(v)) ? Number(v) : 0;
const versusObj = v => !!v && typeof v === "object" && !Array.isArray(v);

function versusOk(v) {  // the shape the box reads; old pushes have no versus at all
  return versusObj(v) && Array.isArray(v.players) && v.players.length >= 1 && v.players.length <= 50
    && v.players.every(p => typeof p === "string") && versusObj(v.today) && Array.isArray(v.today.rows)
    && v.today.rows.every(r => versusObj(r) && versusObj(r.values));
}

const versusName = (v, n) => n === v.you ? "you" : txt(n);
const versusLeader = (v, n) => typeof n === "string" && v.players.includes(n) ? n : null;
const versusOrder = v => v.players.includes(v.you) ? [v.you, ...v.players.filter(p => p !== v.you)] : v.players;

function versusValue(key, value) {
  const n = versusNum(value);
  if (key === "min") return mins(n);
  if (key === "syllabus") { const r = Math.round(n * 10) / 10; return r === 0 ? "0%" : `${r > 0 ? "+" : ""}${r.toFixed(1)}%`; }
  return String(n);
}

const versusCounts = (v, obj, order) => order.map(p => `${versusName(v, p)} ${versusNum(obj?.[p])}`).join(" · ");

function versusSummary(v) {
  try {
    if (!versusOk(v)) return "";
    const leader = versusLeader(v, v.today.leader), order = versusOrder(v);
    if (order.length !== 2) return `Versus <small>${leader && !v.today.draw ? `today: ${versusName(v, leader)} leads` : "level"}</small>`;
    const pts = p => versusNum(v.today.points?.[p]), wins = order.map(p => versusNum(v.tally?.[p])).join("–");
    const other = order.find(p => p !== leader);
    const today = leader && !v.today.draw
      ? `${versusName(v, leader)} ${leader === v.you ? "lead" : "leads"} ${pts(leader)}–${pts(other)}`
      : `level ${pts(order[0])}–${pts(order[1])}`;
    return `Versus <small>${today} · wins ${wins}</small>`;
  } catch { return ""; }
}

function versusHtml(v, now) {
  try {
    if (!versusOk(v)) return "";
    const order = versusOrder(v);
    const rows = v.today.rows.map(r => {
      const lead = versusLeader(v, r.leader);
      return `<tr><td>${txt(r.label)}</td>` + order.map(p => p === lead
        ? `<td class="versus-lead"><b>${versusValue(r.key, r.values[p])}</b> ★</td>`
        : `<td>${versusValue(r.key, r.values[p])}</td>`).join("") + `</tr>`;
    }).join("");
    let html = `<p class="study-label">Today <small>${txt(v.today.day)}</small></p>`
      + `<div class="versus-wrap"><table><thead><tr><th></th>${order.map(p => `<th>${versusName(v, p)}</th>`).join("")}</tr></thead>`
      + `<tbody>${rows}</tbody></table></div>`
      + hint(`★ leads the row · points today: ${versusCounts(v, v.today.points, order)}`)
      + hint(`Days won: ${versusCounts(v, v.tally, order)} · draws ${versusNum(v.draws)}`);
    if (versusObj(v.score) && versusObj(v.penalties))  // +1 a day won, -1 a day of 30m or less, never below zero; older pushes have neither
      html += hint(`Score: ${versusCounts(v, v.score, order)} · days of 30m or less: ${versusCounts(v, v.penalties, order)}`);
    const streak = versusObj(v.streak) ? versusLeader(v, v.streak.name) : null;
    if (streak && versusNum(v.streak.days) > 0) html += hint(`Streak: ${versusName(v, streak)} won ${days(versusNum(v.streak.days))} in a row`);
    if (versusObj(v.streaks)) html += hint(`2h+ days in a row: ${versusCounts(v, v.streaks, order)}`);  // study streaks; older pushes have none
    const recent = Array.isArray(v.recent) ? v.recent.filter(versusObj).slice(0, 14) : [];
    if (recent.length) html += `<ul class="versus-recent">` + recent.map(d => {
      const w = versusLeader(v, d.winner);
      const none = !v.players.some(p => versusNum(d.points?.[p]) > 0);  // nobody scored: no winner, not a draw
      return `<li><span>${planDate(d.day)}</span> ${w ? versusName(v, w) : none ? "no winner" : "draw"}</li>`;
    }).join("") + `</ul>`;
    const others = v.players.filter(p => p !== v.you);
    if (others.length) html += hint("Last synced: " + others.map(p => {
      const t = new Date(typeof v.synced?.[p] === "string" ? v.synced[p] : NaN).getTime();
      return `${txt(p)} ${Number.isFinite(t) ? planAgo(Math.max(0, now - t)) : "never"}`;
    }).join(" · "));
    return html;
  } catch { return ""; }
}

function versusMount(box, pm) {  // called by pmHomePage with the Planner box and the /api/pm object it fetched
  let slot = null;
  try {  // whatever goes wrong here, the Planner box that called us must still finish drawing
    const summary = versusSummary(pm?.versus), html = versusHtml(pm?.versus, new Date());
    if (!summary || !html) return;
    slot = document.createElement("div");
    slot.className = "study-versus";
    box.after(slot);
    const vbox = foldOut(slot, "versus", true);
    slot = vbox;
    vbox.querySelector("summary").innerHTML = summary;
    vbox.insertAdjacentHTML("beforeend", `<div class="versus-body">${html}</div>`);
  } catch { slot?.remove(); }
}
