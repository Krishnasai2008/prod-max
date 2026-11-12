// Runs in front of every request on Cloudflare Pages (free plan, no card).
// 1. Password-protects the whole site. Set SITE_USER and SITE_PASSWORD in the
//    Pages project: Settings > Variables and Secrets. More logins: add
//    SITE_USER_2 + SITE_PASSWORD_2, SITE_USER_3 + SITE_PASSWORD_3, and so on.
// 2. /api/backup: keeps a copy of each login's study data (done ticks, to-do,
//    study time) for javascripts/backup.js. Needs a KV namespace bound as BACKUP
//    in the Pages project: Settings > Bindings.
// 3. /api/pm: the summary `pm stats --push` sends from the laptop, drawn by javascripts/pmstats.js on
//    /stats/. Same KV namespace, its own key, so it can never overwrite the backup.
// 4. /api/pm-inbox: tasks and time sent from the home page's Planner box (javascripts/pmhome.js) for
//    the laptop to pick up (`pm inbox`). Its own key again: the site writes pm-inbox:, the laptop pm:.
export async function onRequest({ request, next, env }) {
  const logins = Object.keys(env).filter(k => k.startsWith("SITE_USER"))
    .map(k => [env[k], env["SITE_PASSWORD" + k.slice("SITE_USER".length)]])
    .filter(([user, password]) => user && password);
  if (!logins.length) {
    return new Response("Site login is not configured yet.", { status: 503 });
  }
  const auth = request.headers.get("Authorization") || "";
  const basic = s => "Basic " + btoa(String.fromCharCode(...new TextEncoder().encode(s)));  // UTF-8, as browsers send it
  const login = logins.find(([user, password]) => auth === basic(`${user}:${password}`));
  if (!login) {
    return new Response("Login required", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="My Notes", charset="UTF-8"' },
    });
  }
  const path = new URL(request.url).pathname;
  if (path === "/api/backup") return store(request, env, "backup:" + login[0], 5_000_000);  // one copy per login
  if (path === "/api/pm") return store(request, env, "pm:" + login[0], 1_000_000);
  if (path === "/api/pm-inbox") return store(request, env, "pm-inbox:" + login[0], 100_000);
  const page = await next();
  const res = new Response(page.body, page);  // a copy: the original's headers can't be changed
  res.headers.set("X-Frame-Options", "SAMEORIGIN");
  return res;
}

async function store(request, env, key, max) {  // one JSON object per key: GET it, or PUT a new one
  if (!env.BACKUP) return new Response("Storage is not linked yet.", { status: 503 });
  if (request.method === "GET") {
    return new Response(await env.BACKUP.get(key) ?? "null",
      { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  }
  if (request.method !== "PUT") return new Response("Use GET or PUT", { status: 405 });
  const body = await request.text();
  if (body.length > max) return new Response("Too large", { status: 413 });
  try {
    const data = JSON.parse(body);
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error();
  } catch {
    return new Response("Must be a JSON object", { status: 400 });
  }
  await env.BACKUP.put(key, body);
  return new Response(null, { status: 204 });
}
