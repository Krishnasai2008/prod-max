// Automatic backup of this browser's study data (done ticks, to-do list, study time, ...: every "study."
// key) to /api/backup in functions/_middleware.js. If the browser's copy is wiped (site data cleared),
// the next visit puts the backup back. Loads before study.js so it sees the data before anything writes.
//
// Each browser counts its own study time, and the backup is one copy: whichever browser saved last. So that time
// from every browser counts, a save also writes "study.saver" (this browser's name) and "study.devices": the other
// browsers' clocks, each as its day totals and stretches. pm on the laptop adds the saver's log and those up.
// A save reads the backup first: the browser that saved before becomes one more entry in the list.

function backupEntry(data, now) {  // a browser's clock as the list holds it: ms per day (newest 400) and its stretches
  const obj = k => { try { const v = JSON.parse(data[k]); return v && typeof v === "object" && !Array.isArray(v) ? v : {}; } catch { return {}; } };
  const time = {};
  for (const [day, subjects] of Object.entries(obj("study.time")).sort(([a], [b]) => (a < b ? -1 : 1)).slice(-400)) {
    const ms = subjects && typeof subjects === "object" ? Object.values(subjects).reduce((a, b) => a + (Number(b) > 0 ? Number(b) : 0), 0) : 0;
    if (ms > 0) time[day] = Math.round(ms);
  }
  return { at: now, time, spans: obj("study.spans") };
}

function backupOthers(saved, id, now) {  // what to save under "study.devices": every browser the server knows but this one
  let all = {};
  try { const v = JSON.parse(saved["study.devices"]); if (v && typeof v === "object" && !Array.isArray(v)) all = v; } catch { /* none saved yet */ }
  try {  // the browser that saved last has its clock in the backup's own log, fresher than any entry for it
    const last = saved["study.saver"];
    if (typeof last === "string" && last && typeof saved["study.time"] === "string") all = { ...all, [last]: backupEntry(saved, now) };
  } catch { /* no backup yet */ }
  return Object.fromEntries(Object.entries(all)  // the 7 saved most recently; one not seen for 400 days is past everything pm reads
    .filter(([k, e]) => k !== id && e && typeof e === "object" && !Array.isArray(e) && now - (Number(e.at) || 0) < 400 * 864e5)
    .sort((a, b) => (Number(b[1].at) || 0) - (Number(a[1].at) || 0)).slice(0, 7));
}

(() => {
  const CORE = ["study.done", "study.time", "study.todo", "study.last"];  // any of these = this browser has data
  const DEVICE = "study.device", DEVICES = "study.devices", SAVER = "study.saver";
  const SKIP = new Set(["study.tick", "study.active", "study.clock", "study.pushed",  // live timer state, not history
    "study.pminbox",  // entries waiting for the laptop (pmhome.js): a queue, restoring it would resend them
    DEVICE,  // this browser's own name, never handed to another
    DEVICES, SAVER]);  // written at each save, never kept here
  const PUSHED = "study.pushed";
  const EVERY = 2 * 60e3;  // at most one save per 2 min across tabs (Cloudflare KV's free plan allows 1,000 a day)
  const get = k => { try { return localStorage.getItem(k); } catch { return null; } };
  const cut = () => { try { return AbortSignal.timeout(20e3); } catch { return undefined; } };  // a request that hangs must not hold up the next save
  const wasEmpty = !CORE.some(k => get(k) !== null);
  let checked = false, lastCheck = 0;  // nothing is saved until the backup was read: an empty browser must never overwrite it
  let server = null;  // the backup as last read or saved: it holds the other browsers' clocks
  let busy = 0;  // when the save now running began

  async function read() {  // undefined: offline, or storage not linked yet
    const res = await fetch("/api/backup", { cache: "no-store", signal: cut() }).catch(() => null);
    const saved = res?.ok ? await res.json().catch(() => undefined) : undefined;
    if (saved !== undefined) server = saved;
    return saved;
  }

  async function check() {
    lastCheck = Date.now();
    const saved = await read();
    if (saved === undefined) return;  // try again later
    checked = true;
    if (!wasEmpty || !saved || !CORE.some(k => typeof saved[k] === "string")) return;
    try {
      for (const [k, v] of Object.entries(saved))
        if (k.startsWith("study.") && k !== DEVICE && k !== DEVICES && k !== SAVER && typeof v === "string") localStorage.setItem(k, v);
    } catch { return; }
    location.reload();  // show the restored progress
  }

  const hash = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = (h * 33 ^ s.charCodeAt(i)) | 0; return String(h); };

  function deviceId() {  // a name for this browser, made once; throws when the browser won't keep it
    let id = get(DEVICE);
    if (!id) { id = Date.now().toString(36) + Math.random().toString(36).slice(2, 10); localStorage.setItem(DEVICE, id); }
    return id;
  }

  function known(id, data) {  // does the backup, as last seen, hold this browser's clock as it is now?
    try {
      if (server[SAVER] === id) return server["study.time"] === data["study.time"] && server["study.spans"] === data["study.spans"];
      const theirs = JSON.parse(server[DEVICES])[id], mine = backupEntry(data, 0);
      return JSON.stringify([theirs.time, theirs.spans]) === JSON.stringify([mine.time, mine.spans]);
    } catch { return false; }
  }

  async function push(closing) {
    if (!closing && Date.now() - busy < 45e3) return;  // one save at a time; one that hangs is given up on
    if (!checked) { if (Date.now() - lastCheck > 5 * 60e3) check(); return; }
    let data = {}, last = {}, id = null;
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k.startsWith("study.") && !SKIP.has(k)) data[k] = localStorage.getItem(k);
      }
      last = JSON.parse(get(PUSHED)) ?? {};
    } catch { return; }
    if (!CORE.some(k => k in data)) return;  // never replace a backup with nothing
    try { id = deviceId(); } catch { /* this browser keeps no name: it saves, but as nobody */ }
    const h = hash(JSON.stringify(data));
    // unchanged data is saved again only when the backup no longer holds this browser's clock as it is
    // (another browser saved an older copy of it, or one still on the older script saved without the list)
    if ((h === last.h && (!id || known(id, data))) || (!closing && Date.now() - (last.at || 0) < EVERY)) return;
    busy = Date.now();
    try {
      // The other browsers' clocks must be current, or this save would put old ones back: read first, and don't save
      // if that fails. A closing tab has no time to read and uses what it last saw; a clock put back stale that way
      // is repaired at that browser's next visit, and pm never lets a day's total go down.
      if (!closing && (await read()) === undefined) return;
      data[DEVICES] = JSON.stringify(backupOthers(server, id ?? "", Date.now()));
      if (id) data[SAVER] = id;
      const body = JSON.stringify(data);
      // keepalive lets the save finish while the tab closes, but browsers only allow it under 64 KB
      const r = await fetch("/api/backup", { method: "PUT", body, headers: { "Content-Type": "application/json" },
        keepalive: body.length < 60000, signal: closing ? undefined : cut() });
      if (!r.ok) return;
      server = data;
      localStorage.setItem(PUSHED, JSON.stringify({ h, at: Date.now() }));
    } catch { /* offline, timed out, or storage full: the next tick tries again */ } finally { busy = 0; }
  }

  navigator.storage?.persist?.().catch(() => {});  // ask the browser not to clear the site's storage when the disk fills up
  check();
  setInterval(push, 30e3);
  addEventListener("pagehide", () => push(true));
})();
