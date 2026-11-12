export const ROUTES = ["today", "tasks", "review", "study", "risk", "stats", "bugs", "files", "settings", "spot", "exam", "practice"];

const ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

export function fmtMin(minutes) {
  const total = Math.trunc(Number(minutes) || 0);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours && rest) return `${hours}h${rest}m`;
  return hours ? `${hours}h` : `${rest}m`;
}

export function fmtClock(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function pct(p) {
  return `${Math.round((Number(p) || 0) * 100)}%`;
}

function dayNumber(iso) {
  const [year, month, day] = String(iso).split("-").map(Number);
  return Date.UTC(year, month - 1, day) / 86400000;
}

export function relDay(iso, todayIso) {
  if (!iso || !todayIso) return "";
  const days = dayNumber(iso) - dayNumber(todayIso);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

export function relTime(iso, nowIso) {
  if (!iso || !nowIso) return "";
  const minutes = Math.round((Date.parse(iso) - Date.parse(nowIso)) / 60000);
  if (!Number.isFinite(minutes)) return "";
  if (Math.abs(minutes) < 60) return `in ${Math.max(0, minutes)}m`;
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return `in ${hours}h`;
  const days = Math.round(minutes / 1440);
  if (Math.abs(days) < 60) return `in ${days}d`;
  return `in ${Math.round(days / 30)}mo`;
}

export function routeOf(hash) {
  const name = String(hash ?? "").replace(/^#\/?/, "").replace(/\/+$/, "");
  return ROUTES.includes(name) ? name : "today";
}

export function stateKey(state) {
  if (!state) return "";
  const copy = { ...state };
  delete copy.now;
  if (copy.running) {
    copy.running = { ...copy.running };
    delete copy.running.elapsed_s;
  }
  return JSON.stringify(copy);
}

export function shouldRender(prevKey, nextKey, dirty) {
  if (prevKey === nextKey) return false;
  return !dirty;
}
