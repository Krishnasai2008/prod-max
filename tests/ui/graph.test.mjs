import test from "node:test";
import assert from "node:assert/strict";

import { graphSvg, layout } from "../../pm/ui/graph.js";

const TOPICS = [
  { id: 1, name: "paging", mastery: 0.4, prereqs: [] },
  { id: 2, name: "tlb", mastery: 0.59, prereqs: [1] },
  { id: 3, name: "caching", mastery: 0.6, prereqs: [1] },
  { id: 4, name: "virtual memory", mastery: 0.8, prereqs: [2, 3] },
];

test("layout assigns layers and id-ordered rows", () => {
  const graph = layout(TOPICS);
  const layers = Object.fromEntries(graph.nodes.map((node) => [node.id, node.layer]));
  const rows = Object.fromEntries(graph.nodes.map((node) => [node.id, node.row]));
  assert.deepEqual(layers, { 1: 0, 2: 1, 3: 1, 4: 2 });
  assert.equal(rows[2], 0);
  assert.equal(rows[3], 1);
  assert.equal(graph.nodes.find((node) => node.id === 4).x, 400);
  assert.deepEqual(graph.edges, [
    { from: 1, to: 2 },
    { from: 1, to: 3 },
    { from: 2, to: 4 },
    { from: 3, to: 4 },
  ]);
});

test("layout fits the nodes plus a 20 px margin", () => {
  const graph = layout(TOPICS);
  assert.equal(graph.width, 580);
  assert.equal(graph.height, 136);
  const single = layout([{ id: 1, prereqs: [] }]);
  assert.equal(single.width, 200);
  assert.equal(single.height, 80);
});

test("layout ignores prerequisites outside the list", () => {
  const graph = layout([{ id: 5, prereqs: [99] }]);
  assert.equal(graph.nodes[0].layer, 0);
  assert.equal(graph.nodes[0].row, 0);
  assert.deepEqual(graph.edges, []);
});

test("layout of nothing has no nodes and numeric dimensions", () => {
  const graph = layout([]);
  assert.deepEqual(graph.nodes, []);
  assert.deepEqual(graph.edges, []);
  assert.equal(typeof graph.width, "number");
  assert.equal(typeof graph.height, "number");
});

test("layout ends prerequisite cycles at layer 0", () => {
  const graph = layout([
    { id: 1, prereqs: [2] },
    { id: 2, prereqs: [1] },
    { id: 3, prereqs: [4] },
    { id: 4, prereqs: [5] },
    { id: 5, prereqs: [3] },
    { id: 6, prereqs: [1] },
  ]);
  const layers = Object.fromEntries(graph.nodes.map((node) => [node.id, node.layer]));
  assert.deepEqual(layers, { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 1 });
  assert.equal(graph.edges.length, 6);
});

test("layout handles a long prerequisite chain without recursion", () => {
  const topics = Array.from({ length: 20000 }, (_, index) => ({
    id: index + 1,
    prereqs: index ? [index] : [],
  }));
  const graph = layout(topics);
  assert.equal(graph.nodes.find((node) => node.id === 20000).layer, 19999);
  assert.equal(graph.edges.length, 19999);
});

test("graphSvg escapes the course, names and percent labels", () => {
  const svg = graphSvg(
    [
      { id: 1, name: "<b>x</b>", mastery: 0.59, prereqs: [] },
      { id: 2, name: "abcdefghijklmnopqrstuvwxyz", mastery: 0.6, prereqs: [1] },
    ],
    2,
    "<os>",
  );
  assert.match(svg, /^<svg role="img" aria-label="prerequisites for &lt;os&gt;"/);
  assert.ok(svg.includes("&lt;b&gt;x&lt;/b&gt;"));
  assert.ok(!svg.includes("<b>x</b>"));
  assert.ok(svg.includes("59%"));
  assert.ok(svg.includes("60%"));
  assert.ok(svg.includes("abcdefghijklmnopqrs…"));
  assert.ok(!svg.includes("abcdefghijklmnopqrst"));
});

test("graphSvg marks the mastery level and the next topic", () => {
  const svg = graphSvg(
    [
      { id: 1, name: "red", mastery: 0.59, prereqs: [] },
      { id: 2, name: "green", mastery: 0.6, prereqs: [] },
    ],
    2,
    "os",
  );
  assert.equal((svg.match(/data-level="red"/g) ?? []).length, 1);
  assert.equal((svg.match(/data-level="green"/g) ?? []).length, 1);
  assert.match(svg, /<g class="next"><rect[^>]*data-level="green"/);
});

test("graphSvg draws one arrowed line per prerequisite edge", () => {
  const svg = graphSvg(TOPICS, 4, "os");
  const lines = svg.match(/<line [^>]*><\/line>/g) ?? [];
  assert.equal(lines.length, 4);
  assert.ok(
    lines.includes(
      '<line x1="180" y1="40" x2="210" y2="40" marker-end="url(#arrow)"></line>',
    ),
  );
  for (const line of lines) assert.match(line, /marker-end="url\(#arrow\)"/);
  assert.match(svg, /<marker id="arrow"[^>]*>/);
  assert.match(svg, /viewBox="0 0 580 136" width="580" height="136"/);
});

test("long non-ASCII names are cut by code point", () => {
  const svg = graphSvg([{ id: 1, name: "𝔸".repeat(25), mastery: 0.5, prereqs: [] }], null, "os");
  assert.ok(svg.includes("𝔸".repeat(19) + "…"));
  assert.ok(!svg.includes("\uFFFD"));
});
