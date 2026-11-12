import { esc, pct } from "./lib.js";

const NODE_W = 160;
const NODE_H = 40;
const MARGIN = 20;
const LAYER_W = 190;
const ROW_H = 56;

function findCycles(topics, prereqsOf) {
  let index = 0;
  const order = new Map();
  const low = new Map();
  const stack = [];
  const onStack = new Set();
  const cyclic = new Set();

  for (const start of topics) {
    if (order.has(start.id)) continue;
    order.set(start.id, index);
    low.set(start.id, index);
    index++;
    stack.push(start.id);
    onStack.add(start.id);
    const calls = [{ id: start.id, prereqs: prereqsOf(start.id), at: 0 }];
    while (calls.length) {
      const call = calls[calls.length - 1];
      if (call.at < call.prereqs.length) {
        const next = call.prereqs[call.at++];
        if (!order.has(next)) {
          order.set(next, index);
          low.set(next, index);
          index++;
          stack.push(next);
          onStack.add(next);
          calls.push({ id: next, prereqs: prereqsOf(next), at: 0 });
        } else if (onStack.has(next)) {
          low.set(call.id, Math.min(low.get(call.id), order.get(next)));
        }
      } else {
        calls.pop();
        if (calls.length) {
          const parent = calls[calls.length - 1];
          low.set(parent.id, Math.min(low.get(parent.id), low.get(call.id)));
        }
        if (low.get(call.id) === order.get(call.id)) {
          const component = [];
          let id;
          do {
            id = stack.pop();
            onStack.delete(id);
            component.push(id);
          } while (id !== call.id);
          if (component.length > 1 || prereqsOf(call.id).includes(call.id)) {
            for (const member of component) cyclic.add(member);
          }
        }
      }
    }
  }
  return cyclic;
}

export function layout(topics) {
  const byId = new Map(topics.map((topic) => [topic.id, topic]));
  const prereqsOf = (id) => (byId.get(id)?.prereqs ?? []).filter((item) => byId.has(item));
  const sorted = [...topics].sort((a, b) => a.id - b.id);
  const cyclic = findCycles(sorted, prereqsOf);
  const layers = new Map();
  const state = new Map();

  for (const start of sorted) {
    if (state.get(start.id) === 2) continue;
    state.set(start.id, 1);
    const stack = [{ id: start.id, prereqs: prereqsOf(start.id), at: 0 }];
    while (stack.length) {
      const frame = stack[stack.length - 1];
      if (frame.at < frame.prereqs.length) {
        const id = frame.prereqs[frame.at++];
        if (!state.has(id)) {
          state.set(id, 1);
          stack.push({ id, prereqs: prereqsOf(id), at: 0 });
        }
      } else {
        let layer = 0;
        if (!cyclic.has(frame.id)) {
          for (const id of frame.prereqs) layer = Math.max(layer, (layers.get(id) ?? 0) + 1);
        }
        layers.set(frame.id, layer);
        state.set(frame.id, 2);
        stack.pop();
      }
    }
  }

  // shortcut: rows are in id order with no crossing reduction, fine under about 30 topics per course

  const nodes = [];
  const edges = [];
  const byLayer = new Map();
  for (const topic of sorted) {
    const layer = layers.get(topic.id) ?? 0;
    if (!byLayer.has(layer)) byLayer.set(layer, []);
    byLayer.get(layer).push(topic);
    for (const from of topic.prereqs ?? []) {
      if (byId.has(from)) edges.push({ from, to: topic.id });
    }
  }

  let width = MARGIN * 2;
  let height = MARGIN * 2;
  for (const [layer, items] of byLayer) {
    items.forEach((topic, row) => {
      const x = MARGIN + layer * LAYER_W;
      const y = MARGIN + row * ROW_H;
      nodes.push({ id: topic.id, layer, row, x, y });
      width = Math.max(width, x + NODE_W + MARGIN);
      height = Math.max(height, y + NODE_H + MARGIN);
    });
  }
  return { nodes, edges, width, height };
}

function label(name) {
  const chars = [...String(name ?? "")]; // code points, so a long name never splits a character
  return chars.length > 20 ? `${chars.slice(0, 19).join("")}…` : chars.join("");
}

export function graphSvg(topics, nextId, course) {
  const graph = layout(topics);
  const byId = new Map(topics.map((topic) => [topic.id, topic]));
  const at = new Map(graph.nodes.map((node) => [node.id, node]));
  const parts = [
    `<svg role="img" aria-label="prerequisites for ${esc(course)}" viewBox="0 0 ${graph.width} ${graph.height}" width="${graph.width}" height="${graph.height}">`,
    `<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="currentColor"></path></marker></defs>`,
  ];
  for (const edge of graph.edges) {
    const from = at.get(edge.from);
    const to = at.get(edge.to);
    parts.push(
      `<line x1="${from.x + NODE_W}" y1="${from.y + NODE_H / 2}" x2="${to.x}" y2="${to.y + NODE_H / 2}" marker-end="url(#arrow)"></line>`,
    );
  }
  for (const node of graph.nodes) {
    const topic = byId.get(node.id) ?? {};
    const level = Number(topic.mastery ?? 0) < 0.6 ? "red" : "green";
    const next = nextId != null && String(topic.id) === String(nextId) ? ' class="next"' : "";
    parts.push(
      `<g${next}>` +
        `<rect x="${node.x}" y="${node.y}" width="${NODE_W}" height="${NODE_H}" rx="8" data-level="${level}"></rect>` +
        `<text x="${node.x + 10}" y="${node.y + 17}" fill="currentColor">` +
        `<tspan>${esc(label(topic.name))}</tspan>` +
        `<tspan x="${node.x + 10}" dy="15">${esc(pct(topic.mastery))}</tspan>` +
        `</text>` +
        `</g>`,
    );
  }
  parts.push("</svg>");
  return parts.join("");
}
