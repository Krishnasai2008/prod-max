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
