import { test } from "node:test";
import assert from "node:assert/strict";
import { load } from "./env.mjs";

const DAY = 864e5, MIN = 60e3, T0 = Date.UTC(2026, 10, 14, 10);
const plain = x => JSON.parse(JSON.stringify(x));  // objects made inside the vm have another realm's prototype
const settle = () => new Promise(r => setImmediate(r));
const { backupEntry, backupOthers } = load(["backup.js"], { expose: ["backupEntry", "backupOthers"] });
const time = (day, ms) => JSON.stringify({ [day]: { os: ms } });

test("backupEntry: a browser's day totals and stretches, whatever shape the stored text is in", () => {
  const data = { "study.time": JSON.stringify({ "2026-11-13": { os: 30 * MIN, poe: 15 * MIN, other: "x" }, "2026-11-14": { os: 0 }, "2026-11-12": 5 }),
                 "study.spans": JSON.stringify({ "2026-11-13": [[600, 645]] }) };
  assert.deepEqual(plain(backupEntry(data, T0)), { at: T0, time: { "2026-11-13": 45 * MIN }, spans: { "2026-11-13": [[600, 645]] } });
  for (const bad of [{}, { "study.time": "not json", "study.spans": "[1]" }, { "study.time": "5", "study.spans": "null" }])
    assert.deepEqual(plain(backupEntry(bad, T0)), { at: T0, time: {}, spans: {} });
});

test("backupEntry keeps the newest 400 days", () => {
  const log = {};
  for (let i = 0; i < 450; i++) log[new Date(T0 - i * DAY).toISOString().slice(0, 10)] = { os: MIN };
  const kept = backupEntry({ "study.time": JSON.stringify(log) }, T0).time;
  assert.equal(Object.keys(kept).length, 400);
  assert.ok("2026-11-14" in kept);
});

test("backupOthers keeps the server's list without this browser, junk, or a browser long gone", () => {
  const phone = { at: T0 - DAY, time: { "2026-11-13": 5 * MIN }, spans: {} };
  const saved = { "study.devices": JSON.stringify({ me: { at: T0, time: { old: 1 } }, phone, junk: 5, list: [], gone: { at: T0 - 401 * DAY, time: {} } }) };
  assert.deepEqual(plain(backupOthers(saved, "me", T0)), { phone });
  for (const none of [null, undefined, 5, {}, { "study.devices": "not json" }, { "study.devices": "[]" }, { "study.devices": 5 }])
    assert.deepEqual(plain(backupOthers(none, "me", T0)), {});
});

test("backupOthers turns the browser that saved last into an entry, from the backup's own log", () => {
  const stale = { at: T0 - DAY, time: { "2026-11-14": MIN }, spans: {} };
  const saved = { "study.saver": "laptop", "study.time": time("2026-11-14", 30 * MIN), "study.spans": JSON.stringify({ "2026-11-14": [[600, 630]] }),
                  "study.devices": JSON.stringify({ laptop: stale }) };
  const fresh = { at: T0, time: { "2026-11-14": 30 * MIN }, spans: { "2026-11-14": [[600, 630]] } };
  assert.deepEqual(plain(backupOthers(saved, "phone", T0)), { laptop: fresh });  // the fresh log, not the stale entry
  assert.deepEqual(plain(backupOthers(saved, "laptop", T0)), {});  // it is this browser: its log is saved as itself
  assert.deepEqual(plain(backupOthers({ ...saved, "study.saver": "" }, "phone", T0)), { laptop: stale });  // nobody's log: only the list
  assert.deepEqual(plain(backupOthers({ "study.saver": "laptop" }, "phone", T0)), {});  // a saver with no clock time
});

test("backupOthers keeps the 7 browsers saved most recently", () => {
  const many = {};
  for (let i = 0; i < 12; i++) many["d" + i] = { at: T0 - i * DAY, time: {} };
  const kept = Object.keys(backupOthers({ "study.devices": JSON.stringify(many) }, "me", T0));
  assert.deepEqual(kept.sort(), ["d0", "d1", "d2", "d3", "d4", "d5", "d6"]);
});

// ---- the whole script, one fake browser at a time, against one shared server ----
function browser(server, stored, clock, { failOn } = {}) {
  let tick, hide, reloads = 0;
  const calls = [];
  const fetch = (url, opts = {}) => {
    const method = opts.method ?? "GET";
    calls.push(method);
    server.seen.push({ method, keepalive: opts.keepalive, signal: opts.signal });
    if (server.hang) return new Promise(() => {});  // never answers
    if (server.down) return Promise.reject(new Error("offline"));
    if (method === "PUT") { server.blob = JSON.parse(opts.body); server.puts.push(opts); return Promise.resolve({ ok: true }); }
    return Promise.resolve({ ok: true, json: async () => plain(server.blob) });
  };
  class FakeDate extends Date { static now() { return clock.t; } }
  const x = load(["backup.js"], { stored, globals: {
    fetch, Date: FakeDate, AbortSignal, setInterval: f => { tick = f; }, addEventListener: (e, f) => { if (e === "pagehide") hide = f; },
    location: { pathname: "/", hash: "", href: "https://x.dev/", reload() { reloads++; } } } });
  const ls = x.localStorage;
  if (failOn) { const set = ls.setItem; ls.setItem = (k, v) => { if (k === failOn) throw new Error("full"); set(k, v); }; }
  const all = () => {
    const out = {};
    for (let i = 0; i < ls.length; i++) { const name = ls.key(i); out[name] = ls.getItem(name); }
    return out;
  };
  return { calls, all, ls, tick: async () => { tick(); await settle(); await settle(); }, hide: async () => { hide(); await settle(); }, get reloads() { return reloads; } };
}
const others = server => JSON.parse(server.blob["study.devices"]);
const newServer = blob => ({ blob, puts: [], seen: [], down: false, hang: false });

test("two browsers: the one that saved before is kept as an entry, and a restored copy gets its own name", async () => {
  const server = newServer(null), clock = { t: T0 };
  const laptop = browser(server, { "study.time": time("2026-11-14", 30 * MIN), "study.done": "[]" }, clock);
  await settle();
  await laptop.tick();
  assert.deepEqual(laptop.calls, ["GET", "GET", "PUT"]);  // the first look, then a fresh read right before the save
  const id = laptop.ls.getItem("study.device");
  assert.ok(id && id.length >= 8);
  assert.equal(server.blob["study.saver"], id);
  assert.equal(server.blob["study.devices"], "{}");  // a lone browser's log is in the backup once, as it always was
  assert.equal(server.blob["study.time"], time("2026-11-14", 30 * MIN));
  assert.ok(!("study.device" in server.blob) && !("study.pushed" in server.blob));
  for (const name of ["study.saver", "study.devices"]) assert.equal(laptop.ls.getItem(name), null);

  // the phone starts empty: it takes the laptop's copy, but not its name, nor the saver, nor the list
  let phone = browser(server, {}, clock);
  await settle();
  assert.equal(phone.reloads, 1);
  assert.equal(phone.ls.getItem("study.time"), time("2026-11-14", 30 * MIN));
  for (const name of ["study.device", "study.saver", "study.devices"]) assert.equal(phone.ls.getItem(name), null);
  phone = browser(server, { ...phone.all(), "study.time": time("2026-11-14", 50 * MIN) }, clock);  // after the reload, 20 more minutes on the phone
  await settle();
  clock.t += 3 * MIN;
  await phone.tick();
  const phoneId = phone.ls.getItem("study.device");
  assert.notEqual(phoneId, id);
  assert.equal(server.blob["study.saver"], phoneId);
  assert.equal(server.blob["study.time"], time("2026-11-14", 50 * MIN));
  assert.deepEqual(Object.keys(others(server)), [id]);
  assert.equal(others(server)[id].time["2026-11-14"], 30 * MIN);

  // back on the laptop, whose page has been open all along: it reads the server again, so the phone's clock is kept
  laptop.ls.setItem("study.time", time("2026-11-14", 40 * MIN));
  clock.t += 3 * MIN;
  await laptop.tick();
  assert.equal(server.blob["study.saver"], id);
  assert.equal(server.blob["study.time"], time("2026-11-14", 40 * MIN));
  assert.deepEqual(Object.keys(others(server)), [phoneId]);
  assert.equal(others(server)[phoneId].time["2026-11-14"], 50 * MIN);
});

test("nothing is saved when the server can't be read first", async () => {
  const server = newServer({ "study.done": "[]", "study.devices": JSON.stringify({ phone: { at: T0, time: {} } }) }), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", MIN) }, clock);
  await settle();
  server.down = true;
  await b.tick();
  assert.equal(server.puts.length, 0);
  assert.equal(b.ls.getItem("study.pushed"), null);
  server.down = false;
  await b.tick();
  assert.equal(server.puts.length, 1);
  assert.ok("phone" in others(server));
});

test("a read that never answers does not stop later saves", async () => {
  const server = newServer(null), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", MIN) }, clock);
  await settle();
  server.hang = true;
  await b.tick();
  await b.tick();  // 30 s later in real life: the first save is still waiting, so this one stands back
  assert.deepEqual(b.calls, ["GET", "GET"]);
  server.hang = false;
  clock.t += MIN;
  await b.tick();
  assert.deepEqual(b.calls, ["GET", "GET", "GET", "PUT"]);
  assert.equal(server.puts.length, 1);
});

test("ordinary requests carry a time limit; the closing save does not, and goes out at once", async () => {
  const server = newServer({ "study.done": "[]", "study.devices": JSON.stringify({ phone: { at: T0, time: {} } }) }), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", MIN) }, clock);
  await settle();
  await b.tick();
  assert.deepEqual(server.seen.map(s => [s.method, !!s.signal]), [["GET", true], ["GET", true], ["PUT", true]]);
  b.ls.setItem("study.time", time("2026-11-14", 2 * MIN));
  clock.t += 30 * MIN;  // a tab left in the background: what it last read is old
  server.blob = { ...server.blob, "study.devices": JSON.stringify({ ...others(server), tablet: { at: clock.t, time: {} } }) };  // another browser saved meanwhile
  await b.hide();
  assert.deepEqual(b.calls, ["GET", "GET", "PUT", "PUT"]);  // no read: the page is going away
  const closing = server.seen.at(-1);
  assert.deepEqual([closing.method, closing.keepalive, closing.signal], ["PUT", true, undefined]);
  assert.equal(server.blob["study.time"], time("2026-11-14", 2 * MIN));
  assert.ok("phone" in others(server));  // the browsers it knew of are kept; the tablet waits for its own next visit
});

test("a big backup is saved without keepalive", async () => {
  const server = newServer(null), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", MIN), "study.done": JSON.stringify(Array(4000).fill("/some/long/note/path/")) }, clock);
  await settle();
  await b.tick();
  assert.equal(server.puts[0].keepalive, false);
});

test("unchanged data is saved again only when the backup no longer holds this browser's clock as it is", async () => {
  const server = newServer(null), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", 9 * MIN) }, clock);
  await settle();
  await b.tick();
  clock.t += 3 * MIN;
  await b.tick();
  assert.equal(server.puts.length, 1);
  const id = b.ls.getItem("study.device");
  const reload = async () => { const again = browser(server, b.all(), clock); await settle(); clock.t += 3 * MIN; await again.tick(); return again; };

  // another browser saved, and kept our clock exactly: nothing to do
  server.blob = { "study.time": time("2026-11-14", MIN), "study.saver": "phone", "study.done": "[]",
                  "study.devices": JSON.stringify({ [id]: { at: 5, time: { "2026-11-14": 9 * MIN }, spans: {} } }) };
  await reload();
  assert.equal(server.puts.length, 1);

  // another browser put back an older copy of our clock (it had read the backup before our last save)
  server.blob["study.devices"] = JSON.stringify({ [id]: { at: 5, time: { "2026-11-14": 4 * MIN }, spans: {} } });
  let again = await reload();
  assert.equal(server.puts.length, 2);
  assert.equal(server.blob["study.saver"], id);
  assert.equal(server.blob["study.time"], time("2026-11-14", 9 * MIN));
  assert.ok("phone" in others(server));
  clock.t += 3 * MIN;
  await again.tick();
  assert.equal(server.puts.length, 2);

  // a browser still on the older script saved: no list at all, and a log that is not ours
  server.blob = { "study.time": time("2026-11-14", 2 * MIN), "study.done": "[]" };
  await reload();
  assert.equal(server.puts.length, 3);
  // the same older script, after restoring our backup: it sends our name back with its own log
  server.blob = { "study.time": time("2026-11-14", 70 * MIN), "study.saver": id, "study.devices": "{}", "study.done": "[]" };
  await reload();
  assert.equal(server.puts.length, 4);
  assert.equal(server.blob["study.time"], time("2026-11-14", 9 * MIN));
});

test("a browser that can't keep a name still saves, as nobody, and keeps every other browser's clock", async () => {
  const server = newServer({ "study.done": "[]", "study.saver": "laptop", "study.time": time("2026-11-14", 30 * MIN),
                             "study.devices": JSON.stringify({ phone: { at: T0, time: {} } }) }), clock = { t: T0 };
  const b = browser(server, { "study.time": time("2026-11-14", MIN) }, clock, { failOn: "study.device" });
  await settle();
  await b.tick();
  assert.equal(server.puts.length, 1);
  assert.ok(!("study.saver" in server.blob));
  assert.equal(server.blob["study.time"], time("2026-11-14", MIN));
  assert.deepEqual(Object.keys(others(server)).sort(), ["laptop", "phone"]);
  assert.equal(others(server).laptop.time["2026-11-14"], 30 * MIN);
  clock.t += 3 * MIN;
  await b.tick();
  assert.equal(server.puts.length, 1);  // and it does not save unchanged data over and over
});

test("an empty browser never saves, and a browser with data never restores", async () => {
  const server = newServer(null), clock = { t: T0 };
  const empty = browser(server, {}, clock);
  await settle();
  await empty.tick();
  await empty.hide();
  assert.equal(server.puts.length, 0);
  server.blob = { "study.done": '["/x/"]', "study.time": time("2026-11-13", MIN) };
  const full = browser(server, { "study.done": "[]" }, clock);
  await settle();
  assert.equal(full.reloads, 0);
  assert.equal(full.ls.getItem("study.done"), "[]");
});
