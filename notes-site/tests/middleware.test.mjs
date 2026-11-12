// Tests for functions/_middleware.js (run: node --test tests/). Not in functions/: every file there becomes a route.
import { test } from "node:test";
import assert from "node:assert/strict";
import { onRequest } from "../functions/_middleware.js";

function setup(seed = {}) {
  const map = new Map(Object.entries(seed));
  const kv = { get: async k => map.get(k) ?? null, put: async (k, v) => { map.set(k, v); } };
  const env = { SITE_USER: "u", SITE_PASSWORD: "p", BACKUP: kv };
  const call = (path, { method = "GET", body, auth = true } = {}) => onRequest({
    request: new Request("https://x.dev" + path, { method, body, headers: auth ? { Authorization: "Basic " + btoa("u:p") } : {} }),
    next: () => new Response("static"),
    env,
  });
  return { map, call };
}

test("PUT then GET /api/pm round-trips under pm:<user>", async () => {
  const { map, call } = setup();
  assert.equal((await call("/api/pm", { method: "PUT", body: '{"version":1}' })).status, 204);
  assert.equal(map.get("pm:u"), '{"version":1}');
  const res = await call("/api/pm");
  assert.equal(await res.text(), '{"version":1}');
  assert.equal(res.headers.get("Cache-Control"), "no-store");
});

test("GET /api/pm with nothing stored is null", async () => {
  assert.equal(await (await setup().call("/api/pm")).text(), "null");
});

test("PUT /api/pm never touches the backup", async () => {
  const { map, call } = setup({ "backup:u": '{"study.done":"[]"}', "pm:other": "{}" });
  await call("/api/pm", { method: "PUT", body: '{"version":1}' });
  assert.equal(map.get("backup:u"), '{"study.done":"[]"}');
  assert.equal(map.get("pm:other"), "{}");
});

test("/api/pm rejects bad bodies and methods", async () => {
  const { call } = setup();
  assert.equal((await call("/api/pm", { method: "PUT", body: "[1]" })).status, 400);
  assert.equal((await call("/api/pm", { method: "PUT", body: "nope" })).status, 400);
  assert.equal((await call("/api/pm", { method: "PUT", body: '{"a":"' + "x".repeat(1_000_000) + '"}' })).status, 413);
  assert.equal((await call("/api/pm", { method: "DELETE" })).status, 405);
});

test("login is required", async () => {
  assert.equal((await setup().call("/api/pm", { auth: false })).status, 401);
});

test("/api/backup still round-trips", async () => {
  const { map, call } = setup();
  assert.equal((await call("/api/backup", { method: "PUT", body: '{"study.done":"[]"}' })).status, 204);
  assert.equal(map.get("backup:u"), '{"study.done":"[]"}');
  assert.equal(await (await call("/api/backup")).text(), '{"study.done":"[]"}');
});

test("other paths go to the static site", async () => {
  assert.equal(await (await setup().call("/poe/")).text(), "static");
});

test("PUT then GET /api/pm-inbox round-trips under pm-inbox:<user>", async () => {
  const { map, call } = setup();
  assert.equal(await (await call("/api/pm-inbox")).text(), "null");
  assert.equal((await call("/api/pm-inbox", { method: "PUT", body: '{"items":[]}' })).status, 204);
  assert.equal(map.get("pm-inbox:u"), '{"items":[]}');
  const res = await call("/api/pm-inbox");
  assert.equal(await res.text(), '{"items":[]}');
  assert.equal(res.headers.get("Cache-Control"), "no-store");
});

test("the inbox, the pm summary and the backup never touch each other", async () => {
  const { map, call } = setup({ "pm:u": '{"version":1}', "backup:u": '{"study.done":"[]"}' });
  await call("/api/pm-inbox", { method: "PUT", body: '{"items":[{"id":"a"}]}' });
  assert.equal(map.get("pm:u"), '{"version":1}');
  assert.equal(map.get("backup:u"), '{"study.done":"[]"}');
  await call("/api/pm", { method: "PUT", body: '{"version":1,"x":2}' });
  assert.equal(map.get("pm-inbox:u"), '{"items":[{"id":"a"}]}');
});

test("/api/pm-inbox rejects bad bodies, methods and strangers", async () => {
  const { call } = setup();
  const big = '{"a":"' + "x".repeat(100_000 - 8) + '"}';
  assert.equal(big.length, 100_000);
  assert.equal((await call("/api/pm-inbox", { method: "PUT", body: big })).status, 204);
  assert.equal((await call("/api/pm-inbox", { method: "PUT", body: big.replace('"a"', '"ab"') })).status, 413);
  assert.equal((await call("/api/pm-inbox", { method: "PUT", body: "[1]" })).status, 400);
  assert.equal((await call("/api/pm-inbox", { method: "DELETE" })).status, 405);
  assert.equal((await call("/api/pm-inbox", { auth: false })).status, 401);
});


test("a password outside ASCII logs in, sent as UTF-8 the way browsers do", async () => {
  const env = { SITE_USER: "u", SITE_PASSWORD: "pä₹", BACKUP: null };
  const basic = s => "Basic " + btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  const call = auth => onRequest({ request: new Request("https://x.dev/", { headers: { Authorization: auth } }), next: () => new Response("static"), env });
  assert.equal((await call(basic("u:pä₹"))).status, 200);
  assert.equal((await call(basic("u:pa"))).status, 401);
});

test("pages can't be framed by another site, and keep their body and type", async () => {
  const res = await setup().call("/os/paging/");
  assert.equal(res.headers.get("X-Frame-Options"), "SAMEORIGIN");
  assert.equal(await res.text(), "static");
});

// ---------- /api/versus: the scoreboard and its scoreboard-only logins ----------
function versusSetup(seed = {}, extra = {}) {
  const map = new Map(Object.entries(seed));
  const kv = { get: async k => map.get(k) ?? null, put: async (k, v) => { map.set(k, v); } };
  const env = { SITE_USER: "u", SITE_PASSWORD: "p", VERSUS_USER: "sam", VERSUS_PASSWORD: "s3", BACKUP: kv, ...extra };
  const call = (path, { method = "GET", body, as = "u:p" } = {}) => onRequest({
    request: new Request("https://x.dev" + path, { method, body, headers: as ? { Authorization: "Basic " + btoa(as) } : {} }),
    next: () => new Response("static"),
    env,
  });
  return { map, call, env };
}
const CARD = '{"version":1,"generated":"2026-11-13T10:00:00","days":{}}';

test("each player PUTs their own card and GETs everyone's", async () => {
  const { map, call } = versusSetup();
  assert.equal((await call("/api/versus", { method: "PUT", body: CARD })).status, 204);
  assert.equal((await call("/api/versus", { method: "PUT", body: '{"version":1,"days":{"x":1}}', as: "sam:s3" })).status, 204);
  assert.deepEqual([...map.keys()].sort(), ["versus:sam", "versus:u"]);
  const res = await call("/api/versus", { as: "sam:s3" });
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await res.json(), { you: "sam", cards: { u: JSON.parse(CARD), sam: { version: 1, days: { x: 1 } } } });
  assert.equal((await (await call("/api/versus")).json()).you, "u");
});

test("a scoreboard login opens nothing but /api/versus", async () => {
  const { map, call } = versusSetup({ "backup:u": "{}", "pm:u": "{}", "backup:sam": "{}" });
  for (const path of ["/", "/poe/", "/stats/", "/api/backup", "/api/pm", "/api/pm-inbox", "/api/versus/", "/api/versus/u",
    "/API/VERSUS", "/api/versusx", "/x/api/versus", "//api/versus"]) {
    for (const method of ["GET", "PUT"]) {
      const res = await call(path, { method, body: method === "PUT" ? "{}" : undefined, as: "sam:s3" });
      assert.equal(res.status, 401, `${method} ${path}`);
      assert.equal(res.headers.get("WWW-Authenticate"), 'Basic realm="My Notes", charset="UTF-8"');
    }
  }
  assert.deepEqual([...map.entries()].sort(), [["backup:sam", "{}"], ["backup:u", "{}"], ["pm:u", "{}"]]);
});

test("a wrong or missing scoreboard password is refused", async () => {
  const { call } = versusSetup();
  for (const as of [null, "sam:nope", "sam:", "sam:p", "u:s3", ":s3", "nobody:x"]) {
    assert.equal((await call("/api/versus", { as })).status, 401, String(as));
    assert.equal((await call("/api/versus", { method: "PUT", body: CARD, as })).status, 401, String(as));
  }
});

test("nobody can write another player's card", async () => {
  const { map, call } = versusSetup({ "versus:u": CARD });
  await call("/api/versus?user=u", { method: "PUT", body: '{"you":"u","login":"u","cards":{"u":{}}}', as: "sam:s3" });
  assert.equal(map.get("versus:u"), CARD);
  assert.equal(map.get("versus:sam"), '{"you":"u","login":"u","cards":{"u":{}}}');
});

test("a scoreboard login can't take a site login's name, or another guest's", async () => {
  const { map, call } = versusSetup({ "versus:u": CARD }, { VERSUS_USER_2: "u", VERSUS_PASSWORD_2: "evil",
    VERSUS_USER_3: "sam", VERSUS_PASSWORD_3: "other" });
  assert.equal((await call("/api/versus", { method: "PUT", body: "{}", as: "u:evil" })).status, 401);
  assert.equal((await call("/api/versus", { method: "PUT", body: "{}", as: "sam:other" })).status, 401);
  assert.equal(map.get("versus:u"), CARD);
  assert.deepEqual(Object.keys((await (await call("/api/versus", { as: "sam:s3" })).json()).cards), ["u"]);
});

test("/api/versus rejects bad bodies and methods, and skips a stored card that isn't JSON", async () => {
  const { call } = versusSetup({ "versus:u": "not json", "versus:sam": CARD, "versus:stranger": CARD });
  assert.equal((await call("/api/versus", { method: "PUT", body: "[1]", as: "sam:s3" })).status, 400);
  assert.equal((await call("/api/versus", { method: "PUT", body: "nope", as: "sam:s3" })).status, 400);
  assert.equal((await call("/api/versus", { method: "PUT", body: '{"a":"' + "x".repeat(100_000) + '"}', as: "sam:s3" })).status, 413);
  assert.equal((await call("/api/versus", { method: "DELETE", as: "sam:s3" })).status, 405);
  assert.equal((await call("/api/versus", { method: "POST", body: "{}", as: "sam:s3" })).status, 405);
  assert.deepEqual(await (await call("/api/versus")).json(), { you: "u", cards: { sam: JSON.parse(CARD) } });
});

test("the scoreboard needs storage, and the site login still needs to exist", async () => {
  const { call, env } = versusSetup();
  delete env.BACKUP;
  assert.equal((await call("/api/versus", { as: "sam:s3" })).status, 503);
  assert.equal((await call("/api/versus", { method: "PUT", body: CARD, as: "sam:s3" })).status, 503);
  delete env.SITE_USER;
  assert.equal((await call("/api/versus", { as: "sam:s3" })).status, 503);
});

test("with no scoreboard login set, the site login still plays and everything else is as before", async () => {
  const { call, env, map } = versusSetup({ "backup:u": "{}" });
  delete env.VERSUS_USER; delete env.VERSUS_PASSWORD;
  assert.equal((await call("/api/versus", { as: "sam:s3" })).status, 401);
  assert.equal((await call("/api/versus", { method: "PUT", body: CARD })).status, 204);
  assert.equal(await (await call("/poe/")).text(), "static");
  assert.equal(await (await call("/api/backup")).text(), "{}");
  assert.equal((await call("/poe/", { as: null })).status, 401);
  assert.equal(map.get("backup:u"), "{}");
});
