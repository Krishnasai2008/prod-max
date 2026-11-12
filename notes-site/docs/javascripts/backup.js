// Automatic backup of this browser's study data (done ticks, to-do list, study time, ...: every "study."
// key) to /api/backup in functions/_middleware.js. If the browser's copy is wiped (site data cleared),
// the next visit puts the backup back. Loads before study.js so it sees the data before anything writes.

(() => {
  const CORE = ["study.done", "study.time", "study.todo", "study.last"];  // any of these = this browser has data
  const SKIP = new Set(["study.tick", "study.active", "study.clock", "study.pushed",  // live timer state, not history
    "study.pminbox"]);  // entries waiting for the laptop (pmhome.js): a queue, restoring it would resend them
  const PUSHED = "study.pushed";
  const EVERY = 2 * 60e3;  // at most one save per 2 min across tabs (Cloudflare KV's free plan allows 1,000 a day)
  const get = k => { try { return localStorage.getItem(k); } catch { return null; } };
  const wasEmpty = !CORE.some(k => get(k) !== null);
  let checked = false, lastCheck = 0;  // nothing is saved until the backup was read: an empty browser must never overwrite it

  async function check() {
    lastCheck = Date.now();
    const res = await fetch("/api/backup", { cache: "no-store" }).catch(() => null);
    const saved = res?.ok ? await res.json().catch(() => undefined) : undefined;
    if (saved === undefined) return;  // offline, or storage not linked yet: try again later
    checked = true;
    if (!wasEmpty || !saved || !CORE.some(k => typeof saved[k] === "string")) return;
    try {
      for (const [k, v] of Object.entries(saved)) if (k.startsWith("study.") && typeof v === "string") localStorage.setItem(k, v);
    } catch { return; }
    location.reload();  // show the restored progress
  }

  const hash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = (h * 33 ^ s.charCodeAt(i)) | 0; return String(h); };

  function push(closing) {
    if (!checked) { if (Date.now() - lastCheck > 5 * 60e3) check(); return; }
    let data = {}, last = {};
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k.startsWith("study.") && !SKIP.has(k)) data[k] = localStorage.getItem(k);
      }
      last = JSON.parse(get(PUSHED)) ?? {};
    } catch { return; }
    if (!CORE.some(k => k in data)) return;  // never replace a backup with nothing
    const body = JSON.stringify(data), h = hash(body);
    if (h === last.h || (!closing && Date.now() - (last.at || 0) < EVERY)) return;
    // keepalive lets the save finish while the tab closes, but browsers only allow it under 64 KB
    fetch("/api/backup", { method: "PUT", body, headers: { "Content-Type": "application/json" }, keepalive: body.length < 60000 })
      .then(r => r.ok && localStorage.setItem(PUSHED, JSON.stringify({ h, at: Date.now() })))
      .catch(() => {});
  }

  navigator.storage?.persist?.().catch(() => {});  // ask the browser not to clear the site's storage when the disk fills up
  check();
  setInterval(push, 30e3);
  addEventListener("pagehide", () => push(true));
})();
