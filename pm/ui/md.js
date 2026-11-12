import { esc } from "./lib.js";

const PH = "\uE000";
const PH_RE = /\uE000(\d+)\uE000/g;
const MATHJAX_SRC = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js";

let mathjaxLoad = null;
let typesetChain = Promise.resolve();

// Strip the private-use range so a note can never forge one of our placeholders.
function stripPrivate(text) {
  let out = "";
  for (const char of String(text ?? "")) {
    if (char < "\uE000" || char > "\uF8FF") out += char;
  }
  return out;
}

function fenceClose(line, char, min) {
  const text = line.trim();
  if (text.length < min) return false;
  for (const c of text) if (c !== char) return false;
  return true;
}

function extractFences(text, push) {
  const lines = text.split("\n");
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const open = /^(\s*)(`{3,}|~{3,})(.*)$/.exec(lines[i]);
    if (!open) {
      out.push(lines[i]);
      continue;
    }
    const indent = open[1].length;
    const char = open[2][0];
    const min = open[2].length;
    let end = i + 1;
    while (end < lines.length && !fenceClose(lines[end], char, min)) end++;
    const body = lines
      .slice(i + 1, end)
      .map((line) => {
        let cut = 0;
        while (cut < indent && line[cut] === " ") cut++;
        return line.slice(cut);
      })
      .join("\n");
    out.push(open[1] + push("fence", body));
    i = end;
  }
  return out.join("\n");
}

function extractInlineCode(text, push) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "`") {
      out += text[i];
      i++;
      continue;
    }
    let run = 0;
    while (text[i + run] === "`") run++;
    const start = i + run;
    let end = -1;
    let j = start;
    while (j < text.length) {
      if (text[j] === "`") {
        let close = 0;
        while (text[j + close] === "`") close++;
        if (close === run) {
          end = j;
          break;
        }
        j += close;
      } else {
        j++;
      }
    }
    if (end < 0) {
      out += text.slice(i, start);
      i = start;
      continue;
    }
    let value = text.slice(start, end);
    if (value.length > 1 && value.startsWith(" ") && value.endsWith(" ")) {
      value = value.slice(1, -1);
    }
    out += push("code", value, text.slice(i, end + run));
    i = end + run;
  }
  return out;
}

function extractDisplayMath(text, push) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "$" || text[i + 1] !== "$") {
      out += text[i];
      i++;
      continue;
    }
    const end = text.indexOf("$$", i + 2);
    if (end < 0) {
      out += "$$";
      i += 2;
      continue;
    }
    out += push("math", text.slice(i, end + 2));
    i = end + 2;
  }
  return out;
}

function extractInlineMath(text, push) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "$") {
      out += text[i];
      i++;
      continue;
    }
    const first = text[i + 1];
    if (first === undefined || first === "$" || /\s/.test(first)) {
      out += "$";
      i++;
      continue;
    }
    const newline = text.indexOf("\n", i + 1);
    const stop = newline < 0 ? text.length : newline;
    let end = -1;
    for (let j = i + 1; j < stop; j++) {
      if (text[j] !== "$") continue;
      const prev = text[j - 1];
      if (/\s/.test(prev) || prev === "$") {
        end = -2;
        break;
      }
      end = j;
      break;
    }
    if (end < 0) {
      out += "$";
      i++;
      continue;
    }
    out += push("math", text.slice(i, end + 1));
    i = end + 1;
  }
  return out;
}

function extract(text) {
  const tokens = [];
  const push = (kind, value, raw) => {
    tokens.push({ kind, value, raw });
    return PH + (tokens.length - 1) + PH;
  };
  let source = stripPrivate(text);
  source = extractFences(source, push);
  source = extractInlineCode(source, push);
  source = extractDisplayMath(source, push);
  source = extractInlineMath(source, push);
  return { text: source, tokens };
}

function expand(token, tokens, depth) {
  if (!token || depth > 8) return "";
  return token.value.replace(/\uE000(\d+)\uE000/g, (_, index) => {
    const inner = tokens[Number(index)];
    if (!inner) return "";
    if (inner.kind === "math") return expand(inner, tokens, depth + 1);
    return inner.raw ?? inner.value;
  });
}

function restore(token, tokens) {
  if (!token) return "";
  if (token.kind === "fence") return `<pre><code>${esc(expand(token, tokens, 0))}</code></pre>`;
  if (token.kind === "math") return `<span class="math">${esc(expand(token, tokens, 0))}</span>`;
  return `<code>${esc(expand(token, tokens, 0))}</code>`;
}

const HEADING_RE = /^(#{1,6})(?:\s+(.*?))?\s*$/;
const HR_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const ADM_RE = /^!!!\s*(\w+)(?:\s+&quot;(.*?)&quot;)?\s*$/;
const QUOTE_RE = /^&gt;\s?/;
const LIST_RE = /^(\s*)([-*+]|\d+\.)\s+(.*)$/;

function blank(line) {
  return line.trim() === "";
}

function fenceLine(line, tokens) {
  const match = /^\s*\uE000(\d+)\uE000\s*$/.exec(line);
  return match !== null && tokens[Number(match[1])]?.kind === "fence";
}

function splitRow(line) {
  let text = line.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  return text.split("|").map((cell) => cell.trim());
}

function separator(line) {
  if (!line.includes("|")) return false;
  const cells = splitRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function startsBlock(lines, i, tokens) {
  const line = lines[i];
  if (blank(line) || fenceLine(line, tokens)) return true;
  if (HEADING_RE.test(line) || HR_RE.test(line) || ADM_RE.test(line)) return true;
  if (QUOTE_RE.test(line) || LIST_RE.test(line)) return true;
  return line.includes("|") && i + 1 < lines.length && separator(lines[i + 1]);
}

function emphasis(chunk) {
  return chunk
    .replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+?)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+?)_/g, "<em>$1</em>");
}

function inline(text) {
  let out = text.replace(/!\[([^\]]*)\]\(((?:[^()]|\([^()]*\))*)\)/g, (_, alt) => `[image: ${alt}]`);
  out = out.replace(/\[([^\]]*)\]\(((?:[^()]|\([^()]*\))*)\)/g, (_, label, url) => {
    if (url.includes(PH) || !/^https?:\/\//i.test(url)) return label;
    return `<a href="${url}" rel="noopener noreferrer" target="_blank">${label}</a>`;
  });
  return out
    .split(/(<[^>]*>)/)
    .map((part, index) => (index % 2 ? part : emphasis(part)))
    .join("");
}

function renderList(items, start, indent) {
  const tag = items[start].ordered ? "ol" : "ul";
  let out = `<${tag}>`;
  let i = start;
  while (i < items.length && items[i].indent >= indent && items[i].indent < indent + 2) {
    if (items[i].ordered !== (tag === "ol")) break;
    out += `<li>${inline(items[i].text)}`;
    i++;
    while (i < items.length && items[i].indent >= indent + 2) {
      const [nested, next] = renderList(items, i, items[i].indent);
      out += nested;
      if (next === i) break;
      i = next;
    }
    out += "</li>";
  }
  return [out + `</${tag}>`, i];
}

function blocks(lines, tokens) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (blank(line)) {
      i++;
      continue;
    }
    if (fenceLine(line, tokens)) {
      out.push(line.trim());
      i++;
      continue;
    }
    const heading = HEADING_RE.exec(line);
    if (heading) {
      const level = Math.min(6, heading[1].length + 2);
      const text = (heading[2] ?? "").replace(/\s+#+\s*$/, "");
      out.push(`<h${level}>${inline(text)}</h${level}>`);
      i++;
      continue;
    }
    if (HR_RE.test(line)) {
      out.push("<hr>");
      i++;
      continue;
    }
    const adm = ADM_RE.exec(line);
    if (adm) {
      const title = adm[2] ?? adm[1];
      i++;
      const body = [];
      while (i < lines.length && (blank(lines[i]) || /^ {4}/.test(lines[i]))) {
        body.push(lines[i].replace(/^ {4}/, ""));
        i++;
      }
      while (body.length && blank(body[0])) body.shift();
      while (body.length && blank(body[body.length - 1])) body.pop();
      out.push(`<blockquote class="adm"><strong>${title}</strong>${blocks(body, tokens)}</blockquote>`);
      continue;
    }
    if (QUOTE_RE.test(line)) {
      const body = [];
      while (i < lines.length && QUOTE_RE.test(lines[i])) {
        body.push(lines[i].replace(QUOTE_RE, ""));
        i++;
      }
      out.push(`<blockquote>${blocks(body, tokens)}</blockquote>`);
      continue;
    }
    if (LIST_RE.test(line)) {
      const items = [];
      while (i < lines.length && LIST_RE.test(lines[i])) {
        const match = LIST_RE.exec(lines[i]);
        items.push({ indent: match[1].length, ordered: /\d/.test(match[2]), text: match[3] });
        i++;
      }
      let result = renderList(items, 0, items[0].indent);
      out.push(result[0]);
      while (result[1] < items.length) {
        result = renderList(items, result[1], items[result[1]].indent);
        out.push(result[0]);
      }
      continue;
    }
    if (line.includes("|") && i + 1 < lines.length && separator(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && !blank(lines[i]) && lines[i].includes("|")) {
        rows.push(splitRow(lines[i]));
        i++;
      }
      const th = head.map((cell) => `<th>${inline(cell)}</th>`).join("");
      const trs = rows
        .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join("")}</tr>`)
        .join("");
      out.push(`<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && !startsBlock(lines, i, tokens)) {
      paragraph.push(lines[i].trim());
      i++;
    }
    out.push(`<p>${inline(paragraph.join(" "))}</p>`);
  }
  return out.join("\n");
}

export function mdHtml(text) {
  const { text: source, tokens } = extract(text);
  return blocks(esc(source).split("\n"), tokens).replace(PH_RE, (_, index) =>
    restore(tokens[Number(index)], tokens),
  );
}

export function hasMath(text) {
  return extract(text).tokens.some((token) => token.kind === "math");
}

function typesetWhenReady(element) {
  const startup = window.MathJax && window.MathJax.startup;
  const ready = startup && startup.promise && typeof startup.promise.then === "function"
    ? Promise.resolve(startup.promise)
    : Promise.resolve();
  return ready.then(() => {
    if (window.MathJax && typeof window.MathJax.typesetPromise === "function") {
      window.MathJax.typesetClear?.([element]);
      return window.MathJax.typesetPromise([element]);
    }
  });
}

export function typeset(element) {
  if (typeof window === "undefined" || typeof document === "undefined") return Promise.resolve();
  if (!mathjaxLoad && !(window.MathJax && typeof window.MathJax.typesetPromise === "function")) {
    window.MathJax = {
      tex: {
        inlineMath: [["$", "$"], ["\\(", "\\)"]],
        displayMath: [["$$", "$$"], ["\\[", "\\]"]],
      },
      options: { processHtmlClass: "math", ignoreHtmlClass: "md" },
    };
    mathjaxLoad = new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = MATHJAX_SRC;
      script.integrity = "sha384-Wuix6BuhrWbjDBs24bXrjf4ZQ5aFeFWBuKkFekO2t8xFU0iNaLQfp2K6/1Nxveei";
      script.crossOrigin = "anonymous";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => resolve();
      (document.head || document.documentElement).appendChild(script);
    });
  }
  const load = mathjaxLoad ?? Promise.resolve();
  const done = typesetChain
    .then(() => load)
    .then(() => typesetWhenReady(element))
    .catch(() => {});
  typesetChain = done;
  return done;
}
