import test from "node:test";
import assert from "node:assert/strict";

import { mdHtml, hasMath, typeset } from "../../pm/ui/md.js";

test("headings shift down and inline rules render", () => {
  const out = mdHtml("# T\n\ntext **b** *i* `c`");
  assert.ok(out.includes("<h3>T</h3>"));
  assert.ok(out.includes("<strong>b</strong>"));
  assert.ok(out.includes("<em>i</em>"));
  assert.ok(out.includes("<code>c</code>"));
});

test("deeper headings cap at h6", () => {
  assert.ok(mdHtml("#### Deep").includes("<h6>Deep</h6>"));
  assert.ok(mdHtml("###### Deeper").includes("<h6>Deeper</h6>"));
});

test("paragraphs keep single line breaks as spaces", () => {
  assert.equal(mdHtml("Hello\nworld"), "<p>Hello world</p>");
});

test("raw html is escaped, never a tag", () => {
  const out = mdHtml("<script>alert(1)</script>");
  assert.ok(out.includes("&lt;script&gt;"));
  assert.ok(!out.includes("<script"));
});

test("links are made only for http and https", () => {
  const bad = mdHtml("[x](javascript:alert(1))");
  assert.ok(!bad.includes("<a"));
  assert.ok(!bad.includes("href"));

  const good = mdHtml("[x](https://a.b/c?d=1&e=2)");
  assert.ok(good.includes('href="https://a.b/c?d=1&amp;e=2"'));
  assert.ok(good.includes('rel="noopener noreferrer"'));
  assert.ok(good.includes('target="_blank"'));

  assert.ok(mdHtml("[x](HTTP://a.b)").includes("<a "));
});

test("a quote in the url cannot close the href attribute", () => {
  const out = mdHtml('[x](https://a.b/" onclick="alert(1))');
  assert.ok(!out.includes('onclick="'));
});

test("a placeholder in a link url renders the label only", () => {
  for (const out of [mdHtml("[x](https://a/`y`)"), mdHtml("[x](https://a/$y$)")]) {
    assert.ok(!out.includes("<a"));
    assert.ok(!out.includes("href"));
    assert.ok(!/href="[^"]*class="math"/.test(out));
  }
});

test("maths is pulled out before emphasis", () => {
  const out = mdHtml("$a_1 + b_2$ and _it_");
  assert.ok(out.includes('<span class="math">$a_1 + b_2$</span>'));
  assert.ok(out.includes("<em>it</em>"));
  const span = out.slice(out.indexOf('<span class="math">'), out.indexOf("</span>"));
  assert.ok(!span.includes("<em>"));
});

test("display maths keeps its source and currency is not maths", () => {
  assert.ok(mdHtml("$$\\sum_{i=1}^n x_i$$").includes('<span class="math">$$\\sum_{i=1}^n x_i$$</span>'));
  assert.ok(!mdHtml("costs $5 and $6").includes('class="math"'));
});

test("maths is escaped inside its span", () => {
  assert.ok(mdHtml("$x < y$").includes('<span class="math">$x &lt; y$</span>'));
});

test("fenced code is escaped and gets no block or inline rules", () => {
  const out = mdHtml("```\n# not a heading\n**x**\n```");
  assert.ok(out.includes("<pre><code>"));
  assert.ok(out.includes("# not a heading"));
  assert.ok(out.includes("**x**"));
  assert.ok(!out.includes("<h3>"));
  assert.ok(!out.includes("<strong>"));
  assert.ok(mdHtml("~~~\n`a`\n~~~").includes("<pre><code>`a`</code></pre>"));
});

test("lists nest by indent and ordered lists use ol", () => {
  assert.equal(
    mdHtml("- a\n- b\n  - c"),
    "<ul><li>a</li><li>b<ul><li>c</li></ul></li></ul>",
  );
  assert.ok(mdHtml("1. a\n2. b").includes("<ol>"));
});

test("pipe tables need a separator row", () => {
  const out = mdHtml("| a | b |\n|---|---|\n| 1 | 2 |");
  assert.ok(out.includes("<table>"));
  assert.ok(out.includes("<th>a</th>"));
  assert.ok(out.includes("<td>1</td>"));
  assert.ok(!mdHtml("| a | b |").includes("<table>"));
});

test("blockquotes and admonitions", () => {
  assert.ok(mdHtml("> q").includes("<blockquote>"));
  const adm = mdHtml('!!! note "Heads up"\n    body');
  assert.ok(adm.includes('<blockquote class="adm">'));
  assert.ok(adm.includes("<strong>Heads up</strong>"));
  assert.ok(adm.includes("body"));
});

test("images become alt text, never img", () => {
  const out = mdHtml("![alt](pic.png)");
  assert.ok(out.includes("[image: alt]"));
  assert.ok(!out.includes("<img"));
});

test("hasMath ignores code", () => {
  assert.equal(hasMath("a $x$ b"), true);
  assert.equal(hasMath("$$x$$"), true);
  assert.equal(hasMath("`$x$`"), false);
  assert.equal(hasMath("plain"), false);
});

test("a private-use character cannot forge a placeholder", () => {
  const out = mdHtml("\uE0000\uE000 and \uE0001\uE000");
  assert.ok(!/[\uE000-\uF8FF]/.test(out));
  assert.ok(out.includes("0 and 1"));
  assert.ok(!out.includes("<code>"));
});

test("an unclosed bold marker does not throw and is left alone", () => {
  let out;
  assert.doesNotThrow(() => {
    out = mdHtml("**a");
  });
  assert.ok(out.includes("**a"));
});

test("a large input renders in linear time", () => {
  const lines = [];
  for (let i = 0; i < 2000; i++) lines.push(`line ${i} with **bold** and $x_${i}$`);
  const start = Date.now();
  mdHtml(lines.join("\n"));
  const elapsed = Date.now() - start;
  assert.ok(elapsed < 200, `took ${elapsed}ms`);
});

test("typeset resolves quietly without a dom", async () => {
  await typeset(null);
});

test("inline code or maths alone on a line stays inside the paragraph", () => {
  assert.equal(mdHtml("before\n`x`\nafter"), "<p>before <code>x</code> after</p>");
  assert.equal(
    mdHtml("before\n$x$\nafter"),
    '<p>before <span class="math">$x$</span> after</p>',
  );
});

test("currency before maths does not swallow the maths", () => {
  const inline = mdHtml("costs $5 and $x + 1$");
  assert.ok(inline.includes('<span class="math">$x + 1$</span>'));
  assert.ok(!inline.includes('<span class="math">$5'));
  const display = mdHtml("costs $5 and $$x + 1$$");
  assert.ok(display.includes('<span class="math">$$x + 1$$</span>'));
  assert.ok(!display.includes('<span class="math">$5'));
});

test("an indented fence inside an admonition does not end the body", () => {
  const out = mdHtml('!!! note "T"\n    ```\n    code\n    ```\n    after');
  assert.ok(out.includes('<blockquote class="adm"><strong>T</strong><pre><code>code</code></pre>'));
  assert.ok(out.includes("after</p></blockquote>"));
});

test("one-space indents do not nest lists", () => {
  assert.equal(mdHtml("- a\n - b"), "<ul><li>a</li><li>b</li></ul>");
});

test("consecutive sublists stay inside their list item", () => {
  assert.equal(
    mdHtml("- a\n  - b\n  1. c\n  - d"),
    "<ul><li>a<ul><li>b</li></ul><ol><li>c</li></ol><ul><li>d</li></ul></li></ul>",
  );
});

test("a placeholder inside maths is expanded, not left raw", () => {
  const out = mdHtml("$`a`$");
  assert.ok(!/[\uE000-\uF8FF]/.test(out));
  assert.ok(out.includes('<span class="math">$`a`$</span>'));
});

function stubDom() {
  const scripts = [];
  const document = {
    head: { appendChild: (script) => scripts.push(script) },
    documentElement: { appendChild: (script) => scripts.push(script) },
    createElement: () => ({}),
  };
  const win = {};
  globalThis.window = win;
  globalThis.document = document;
  return { win, scripts };
}

function restoreDom() {
  delete globalThis.window;
  delete globalThis.document;
}

test("typeset loads pinned MathJax once and reuses it", async () => {
  const { win, scripts } = stubDom();
  try {
    const { typeset: load } = await import("../../pm/ui/md.js?typeset-load");
    const first = load("a");
    const second = load("b");
    assert.equal(scripts.length, 1);
    assert.equal(scripts[0].src, "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js");
    assert.equal(
      scripts[0].integrity,
      "sha384-Wuix6BuhrWbjDBs24bXrjf4ZQ5aFeFWBuKkFekO2t8xFU0iNaLQfp2K6/1Nxveei",
    );
    assert.equal(scripts[0].crossOrigin, "anonymous");
    assert.equal(scripts[0].async, true);
    assert.deepEqual(win.MathJax.tex.inlineMath, [["$", "$"], ["\\(", "\\)"]]);
    assert.deepEqual(win.MathJax.tex.displayMath, [["$$", "$$"], ["\\[", "\\]"]]);
    const seen = [];
    win.MathJax.typesetPromise = (elements) => {
      seen.push(elements);
      return Promise.resolve();
    };
    scripts[0].onload();
    await Promise.all([first, second]);
    assert.deepEqual(seen, [["a"], ["b"]]);
    await load("c");
    assert.equal(scripts.length, 1);
    assert.deepEqual(seen[2], ["c"]);
  } finally {
    restoreDom();
  }
});

test("typeset serializes calls and clears each element first", async () => {
  const { win, scripts } = stubDom();
  try {
    const events = [];
    const pending = [];
    win.MathJax = {
      typesetClear: (elements) => events.push(["clear", elements]),
      typesetPromise: (elements) => {
        events.push(["typeset", elements]);
        return new Promise((resolve) => pending.push(resolve));
      },
    };
    const { typeset: load } = await import("../../pm/ui/md.js?typeset-serial");
    const first = load("a");
    const second = load("b");
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(scripts.length, 0);
    assert.deepEqual(events, [
      ["clear", ["a"]],
      ["typeset", ["a"]],
    ]);
    pending.shift()();
    await first;
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(events, [
      ["clear", ["a"]],
      ["typeset", ["a"]],
      ["clear", ["b"]],
      ["typeset", ["b"]],
    ]);
    pending.shift()();
    await second;
  } finally {
    restoreDom();
  }
});

test("typeset waits for MathJax startup before typesetting", async () => {
  const { win, scripts } = stubDom();
  try {
    const { typeset: load } = await import("../../pm/ui/md.js?typeset-startup");
    const done = load("x");
    let started = false;
    let release;
    win.MathJax = {
      startup: { promise: new Promise((resolve) => { release = resolve; }) },
      typesetPromise: (elements) => {
        started = true;
        assert.deepEqual(elements, ["x"]);
        return Promise.resolve();
      },
    };
    scripts[0].onload();
    await Promise.resolve();
    assert.equal(started, false);
    release();
    await done;
    assert.equal(started, true);
  } finally {
    restoreDom();
  }
});

test("typeset reuses an already loaded MathJax", async () => {
  const { win, scripts } = stubDom();
  try {
    const seen = [];
    win.MathJax = {
      typesetPromise: (elements) => {
        seen.push(elements);
        return Promise.resolve();
      },
    };
    const { typeset: loaded } = await import("../../pm/ui/md.js?typeset-ready");
    await loaded("x");
    assert.equal(scripts.length, 0);
    assert.deepEqual(seen, [["x"]]);
    assert.equal(win.MathJax.tex, undefined);
  } finally {
    restoreDom();
  }
});

test("typeset resolves quietly when the script fails to load", async () => {
  const { scripts } = stubDom();
  try {
    const { typeset: broken } = await import("../../pm/ui/md.js?typeset-load-fail");
    const done = broken("x");
    assert.equal(scripts.length, 1);
    scripts[0].onerror();
    await done;
  } finally {
    restoreDom();
  }
});

test("typeset resolves quietly when typesetting fails", async () => {
  const { win, scripts } = stubDom();
  try {
    const { typeset: broken } = await import("../../pm/ui/md.js?typeset-reject");
    const done = broken("x");
    win.MathJax.typesetPromise = () => Promise.reject(new Error("nope"));
    scripts[0].onload();
    await done;
  } finally {
    restoreDom();
  }
});
