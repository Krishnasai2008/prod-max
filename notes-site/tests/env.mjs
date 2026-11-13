// Runs the site's classic scripts (shared globals, no modules) in one Node vm context with a tiny fake browser.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const JS = new URL("../docs/javascripts/", import.meta.url);

// stored: localStorage to start with; globals: parts of the fake browser to replace (fetch, Date, setInterval, ...)
export function load(files, { path = "/", expose = [], stored = {}, globals = {} } = {}) {
  const store = new Map(Object.entries(stored));
  const localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k), key: i => [...store.keys()][i] ?? null, get length() { return store.size; },
  };
  const noop = () => {};
  const document = { querySelector: () => null, querySelectorAll: () => [], addEventListener: noop, visibilityState: "visible" };
  const ctx = vm.createContext({
    localStorage, document, location: { pathname: path, hash: "", href: "https://x.dev" + path },
    navigator: {}, addEventListener: noop, setInterval: noop, setTimeout: noop, fetch: async () => { throw new Error("offline"); },
    URL, Date, Math, JSON, console, ...globals,
  });
  // top-level const/function names live in the script scope, not on the context: hand them out explicitly
  const code = files.map(f => readFileSync(new URL(f, JS), "utf8")).join("\n;\n") + `\n;globalThis.__x = {${expose.join(",")}};`;
  vm.runInContext(code, ctx);
  return { ...ctx.__x, localStorage };
}
