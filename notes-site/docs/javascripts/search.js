// Search box (header button, / or Ctrl+K). The index is built by Pagefind after the site build
// (build.sh, pagefind.yml); the browser only downloads the small pieces each search needs.

(() => {
  const base = new URL("pagefind/", document.querySelector(".md-header .md-logo")?.href ?? location.origin + "/");
  let dialog, ready, early = "";  // early: what you typed before the search box finished loading

  function open() {
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.className = "study-search";
      dialog.setAttribute("aria-label", "Search");
      dialog.innerHTML = '<div class="study-search-box"></div>';
      dialog.addEventListener("keydown", e => {
        if (!dialog.querySelector("input") && e.key.length === 1 && !e.ctrlKey && !e.metaKey) early += e.key;
      });
      dialog.addEventListener("click", e => {
        if (e.target === dialog || e.target.closest("a")) dialog.close();  // backdrop, or a result was opened
      });
      document.body.append(dialog);
      ready = new Promise((resolve, reject) => {  // load Pagefind's UI only when search is first opened
        const css = Object.assign(document.createElement("link"), { rel: "stylesheet", href: new URL("pagefind-ui.css", base) });
        const js = Object.assign(document.createElement("script"), { src: new URL("pagefind-ui.js", base), onerror: reject });
        js.onload = () => {
          new PagefindUI({ element: dialog.firstChild, bundlePath: base.pathname, showSubResults: true,
                           showImages: false, resetStyles: false, autofocus: true });
          resolve();
        };
        document.head.append(css, js);
      }).catch(() => { dialog.firstChild.textContent = "Search isn't available right now. Try reloading the page."; });
    }
    if (!dialog.open) dialog.showModal();
    ready.then(() => {
      const input = dialog.querySelector("input");
      if (!input) return;
      if (early) { input.value = early; early = ""; input.dispatchEvent(new Event("input", { bubbles: true })); }
      input.focus();
    });
  }

  const header = document.querySelector(".md-header__inner");
  if (header && !document.querySelector(".study-search-btn")) {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "study-search-btn";
    btn.innerHTML = '<span>Search</span><kbd>/</kbd>';
    btn.setAttribute("aria-label", "Search");
    btn.addEventListener("click", open);
    header.append(btn);
  }

  document.addEventListener("keydown", e => {
    const t = e.composedPath()[0];
    const typing = t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
    if ((e.key === "k" && (e.ctrlKey || e.metaKey)) || (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey)) {
      e.preventDefault();
      open();
    }
  });
})();
