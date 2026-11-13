// Versus: the study scoreboard. The board comes from pm's last sync with the hub; other players' names are
// their text, so everything goes through esc().
import { esc, fmtMin } from "./lib.js";

export async function load(ctx) {
  return { versus: (await ctx.api("GET", "/api/versus")) ?? null };
}

const num = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0);
const signed = (value) => `${num(value) > 0 ? "+" : ""}${num(value).toFixed(1)}%`;
function ago(iso, nowIso) {
  const minutes = Math.round((Date.parse(nowIso) - Date.parse(iso)) / 60000);
  if (!Number.isFinite(minutes)) return "at an unknown time";
  if (minutes < 60) return `${Math.max(0, minutes)}m ago`;
  return minutes < 2880 ? `${Math.round(minutes / 60)}h ago` : `${Math.round(minutes / 1440)} days ago`;
}
const days = (n) => `${n} ${n === 1 ? "day" : "days"}`;

function cell(kind, value) {
  if (kind === "min") return fmtMin(num(value));
  return kind === "syllabus" ? signed(value) : String(num(value));
}

function boardHtml(board, now) {
  const who = (name) => esc(name === board.you ? "you" : name);
  const players = board.players;
  const today = board.today;
  const head = `<tr><th scope="col">today so far</th>${players.map((p) => `<th scope="col">${who(p)}</th>`).join("")}</tr>`;
  const body = today.rows
    .map(
      ({ key: kind, label, values, leader }) =>
        `<tr><th scope="row">${esc(label)}</th>` +
        players
          .map((p) =>
            leader === p
              ? `<td class="versus-lead"><b>${esc(cell(kind, values[p]))}</b> ★</td>`
              : `<td>${esc(cell(kind, values[p]))}</td>`,
          )
          .join("") +
        `</tr>`,
    )
    .join("");
  const points =
    `<tr class="versus-points"><th scope="row">points</th>` +
    players.map((p) => `<td><b>${esc(num(today.points[p]))}</b></td>`).join("") +
    `</tr>`;
  let out = `<div class="versus-wrap"><table class="versus-table"><thead>${head}</thead><tbody>${body}${points}</tbody></table></div>`;
  out += `<p class="study-hint">★ leads the row and takes its point. Syllabus is the change in your average topic mastery.</p>`;
  if (players.length < 2) {
    return out + `<p class="muted">Waiting for another player to sync.</p>`;
  }
  const lead = today.leader ? `${who(today.leader)} ${today.leader === board.you ? "lead" : "leads"} today` : "today is level";
  const tiles = players.map((p) => `<div><small>${who(p)} · days won</small><b>${esc(num(board.tally[p]))}</b></div>`).join("");
  out +=
    `<p><strong>${lead}</strong></p>` +
    `<div class="study-tiles">${tiles}<div><small>draws</small><b>${esc(num(board.draws))}</b></div></div>`;
  if (board.score && board.penalties) {
    const line = (values) => players.map((p) => `${who(p)} ${esc(num(values[p]))}`).join(" · ");
    out +=
      `<p class="versus-score">Score: <strong>${line(board.score)}</strong></p>` +
      `<p class="study-hint">+1 for a day won, −1 for a day of 30m or less (never below zero). Days of 30m or less: ${line(board.penalties)}.</p>`;
  }
  if (board.streak) {
    out += `<p>Streak: ${who(board.streak.name)}, ${esc(days(num(board.streak.days)))} in a row.</p>`;
  }
  if (board.streaks) {
    const runs = players.map((p) => `${who(p)} ${esc(num(board.streaks[p]))}`).join(" · ");
    out += `<p class="study-hint">2h+ days in a row: ${runs}.</p>`;
  }
  if (board.recent.length) {
    out +=
      `<h2>Recent days</h2><ul class="versus-recent">` +
      board.recent
        .map((d) => {
          const scores = players.map((p) => num(d.points[p]));
          const won = d.winner ? who(d.winner) : scores.some((n) => n > 0) ? "draw" : "no winner";
          return `<li><span class="muted">${esc(d.day)}</span> ${won} <span class="muted">${esc(scores.join("–"))}</span></li>`;
        })
        .join("") +
      `</ul>`;
  }
  const synced = players
    .filter((p) => p !== board.you)
    .map((p) => `${who(p)} synced ${esc(ago(board.synced[p], now))}`)
    .join(" · ");
  return out + (synced ? `<p class="study-hint">${synced}. A day counts once everyone has synced after midnight.</p>` : "");
}

export function html(state, extra) {
  const versus = extra?.versus;
  const out = `<h1>Versus</h1>`;
  if (!versus?.on) {
    return (
      out +
      `<p class="muted">The scoreboard is off. Set the <a href="#/settings">scoreboard address</a> ` +
      `(or run <code>pm set versus_url https://the-scoreboard-site</code>) and add its login to <code>~/.netrc</code>.</p>`
    );
  }
  const button = `<p><button type="button" class="btn" data-act="sync">Sync now</button></p>`;
  if (!versus.board) {
    return out + `<p class="muted">No scoreboard yet. It syncs once an hour while <code>pm watch</code> runs.</p>` + button;
  }
  return out + boardHtml(versus.board, state?.now) + button;
}

export const actions = {
  async sync(_data, ctx) {
    await ctx.api("POST", "/api/versus/sync");
    ctx.toast("synced");
  },
};
