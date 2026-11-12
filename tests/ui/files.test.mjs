import test from "node:test";
import assert from "node:assert/strict";

import { actions, html, input, load, resultsHtml, snippetHtml } from "../../pm/ui/files.js";

const FILES = {
  hits: [
    {
      id: 4,
      path: "/home/u/os/paging.pdf",
      short: "~/os/paging.pdf",
      name: "paging.pdf",
      course: "os",
      snippet: "chapter on \x02paging\x03 and the tlb",
      openable: true,
    },
    {
      id: 7,
      path: "/home/u/dl/tool.desktop",
      short: "~/dl/tool.desktop",
      name: "tool.desktop",
      course: "",
      snippet: "",
      openable: false,
    },
  ],
  courses: ["db", "os"],
  total: 2,
};

function fakeCtx(overrides = {}) {
  const calls = [];
  const ctx = {
    async api(method, path, body) {
      calls.push([method, path, body]);
      return overrides.reply ?? FILES;
    },
    patch(id, markup) {
      calls.push(["PATCH", id, markup]);
    },
    async refresh() {
      calls.push(["REFRESH"]);
    },
    async openAddStudy(path) {
      calls.push(["STUDY", path]);
    },
    toast() {},
    ...overrides,
  };
  return { ctx, calls };
}

async function reset() {
  const { ctx } = fakeCtx();
  await actions.search({ value: "" }, ctx);
  await actions.course({ value: "" }, ctx);
}

test.beforeEach(reset);

test("snippetHtml escapes first and then marks each pair", () => {
  assert.equal(snippetHtml("a \x02<b>\x03 c"), "a <mark>&lt;b&gt;</mark> c");
  assert.equal(
    snippetHtml("\x02one\x03 and \x02two\x03"),
    "<mark>one</mark> and <mark>two</mark>",
  );
});

test("an unpaired marker never leaves an open mark tag", () => {
  const out = snippetHtml("a \x02b c \x02d e");
  assert.equal(out, "a b c d e");
  assert.ok(!out.includes("<mark"));
  assert.ok(!out.includes("\x02"));
  assert.ok(!out.includes("\x03"));

  const stray = snippetHtml("a \x02b\x03 c \x03 d");
  assert.ok(!stray.includes("\x02"));
  assert.ok(!stray.includes("\x03"));
  assert.equal((stray.match(/<mark>/g) ?? []).length, (stray.match(/<\/mark>/g) ?? []).length);
});

test("results list each hit with only the buttons it can use", () => {
  const out = resultsHtml(FILES);
  assert.ok(out.includes("<h2>recent files</h2>"));
  assert.ok(out.includes("<strong>paging.pdf</strong>"));
  assert.ok(out.includes("~/os/paging.pdf"));
  assert.ok(out.includes('<span class="tag">os</span>'));
  assert.ok(out.includes("<mark>paging</mark>"));
  assert.equal((out.match(/>Open<\/button>/g) ?? []).length, 1);
  assert.equal((out.match(/>Show in folder<\/button>/g) ?? []).length, 2);
  assert.equal((out.match(/>Study this<\/button>/g) ?? []).length, 2);
  assert.ok(out.includes('data-act="open" data-id="4"'));
  assert.ok(!out.includes('data-act="open" data-id="7"'));
  assert.ok(
    out.includes('data-act="study" data-id="4" data-path="/home/u/os/paging.pdf"'),
  );
  assert.ok(out.includes('data-act="reveal" data-id="7"'));
});

test("a file name is escaped everywhere", () => {
  const out = resultsHtml({
    hits: [
      {
        ...FILES.hits[0],
        name: "<i>.pdf",
        path: "/home/u/<i>.pdf",
        short: "~/<i>.pdf",
      },
    ],
    total: 1,
  });
  assert.ok(out.includes("&lt;i&gt;.pdf"));
  assert.ok(!out.includes("<i>.pdf"));
});

test("empty results say no matches, or how to index files", () => {
  assert.equal(resultsHtml({ hits: [], total: 5 }), '<p class="muted">no matches</p>');
  assert.equal(
    resultsHtml({ hits: [], total: 0 }),
    '<p class="muted">nothing indexed yet: run pm watch --install, or pm watch --once</p>',
  );
});

test("the heading counts matches only while searching", async () => {
  const { ctx } = fakeCtx();
  assert.ok(resultsHtml(FILES).includes("<h2>recent files</h2>"));
  await actions.search({ value: "paging" }, ctx);
  assert.ok(resultsHtml(FILES).includes("<h2>2 matches</h2>"));
  assert.ok(
    resultsHtml({ ...FILES, hits: FILES.hits.slice(0, 1) }).includes("<h2>1 match</h2>"),
  );
});

test("search fetches the encoded query, patches the results and never refreshes", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.search({ value: "a b" }, ctx);
  assert.deepEqual(calls[0], ["GET", "/api/files?q=a%20b", undefined]);
  assert.equal(calls[1][0], "PATCH");
  assert.equal(calls[1][1], "files-out");
  assert.ok(calls[1][2].includes("paging.pdf"));
  assert.ok(!calls.some((call) => call[0] === "REFRESH"));
});

test("load asks for the search and course the screen left behind", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.search({ value: "a b" }, ctx);
  calls.length = 0;
  const extra = await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/files?q=a%20b", undefined]]);
  assert.equal(extra.files, FILES);

  await actions.course({ value: "os" }, ctx);
  calls.length = 0;
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/files?q=a%20b&course=os", undefined]]);
});

test("only spaces count as no search", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.course({ value: "" }, ctx);
  await actions.search({ value: "   " }, ctx);
  assert.deepEqual(calls.at(-2), ["GET", "/api/files", undefined]);
  assert.ok(resultsHtml(FILES).includes("<h2>recent files</h2>"));
});

test("typing updates the filters before the debounced search runs", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.course({ value: "" }, ctx);
  input({ target: { name: "q", value: "tlb" } });
  input({ target: { name: "course", value: "os" } });
  calls.length = 0;
  await load(ctx);
  assert.deepEqual(calls, [["GET", "/api/files?q=tlb&course=os", undefined]]);
  input({ target: { name: "course", value: "" } });
});

test("a slower, older search never replaces a newer one", async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const patches = [];
  const ctx = {
    api: (_m, path) => (path.includes("old") ? slow : Promise.resolve({ ...FILES, hits: [] })),
    patch: (id, markup) => patches.push(markup),
  };
  const older = actions.search({ value: "old" }, ctx);
  await actions.search({ value: "new" }, ctx);
  release(FILES);
  await older;
  assert.equal(patches.length, 1);
  assert.ok(patches[0].includes("no matches"));
});

test("course fetches the filter on its own when the search is empty", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.course({ value: "os" }, ctx);
  assert.deepEqual(calls[0], ["GET", "/api/files?course=os", undefined]);
  assert.equal(calls[1][0], "PATCH");
});

test("html draws the controls and keeps the chosen course and query", async () => {
  const { ctx } = fakeCtx();
  await actions.search({ value: "a b" }, ctx);
  await actions.course({ value: "os" }, ctx);
  const out = html({}, { files: FILES });
  assert.ok(out.includes('type="search" name="q" data-act="search" aria-label="search files"'));
  assert.ok(out.includes('value="a b"'));
  assert.ok(out.includes('name="course" data-act="course"'));
  assert.ok(out.includes('<option value="">all courses</option>'));
  assert.ok(out.includes('<option value="os" selected>os</option>'));
  assert.ok(out.indexOf("all courses") < out.indexOf('value="db"'));
  assert.ok(out.includes('id="files-out"'));
});

test("html escapes the query in the search field and loads until data arrives", async () => {
  const { ctx } = fakeCtx();
  await actions.search({ value: '"><script>' }, ctx);
  const out = html({});
  assert.ok(out.includes('value="&quot;&gt;&lt;script&gt;"'));
  assert.ok(out.includes("loading…"));
  assert.ok(!out.includes("<script>"));
});

test("open and reveal post the file id", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.open({ id: "4" }, ctx);
  await actions.reveal({ id: "4" }, ctx);
  assert.deepEqual(calls, [
    ["POST", "/api/files/4/open", undefined],
    ["POST", "/api/files/4/reveal", undefined],
  ]);
});

test("study opens the add-to-study dialog with the full path", async () => {
  const { ctx, calls } = fakeCtx();
  await actions.study({ id: "4", path: "/home/u/os/paging.pdf" }, ctx);
  assert.deepEqual(calls, [["STUDY", "/home/u/os/paging.pdf"]]);
});
