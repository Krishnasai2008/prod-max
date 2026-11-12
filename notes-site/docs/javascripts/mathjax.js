window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true
  },
  options: {
    ignoreHtmlClass: ".*|",
    processHtmlClass: "arithmatex"
  }
};

// Load MathJax (~1 MB) only on pages that contain math, and re-render math
// after instant navigation swaps the page.
function renderMath() {
  if (!document.querySelector(".arithmatex")) return;
  if (window.MathJax && MathJax.startup && MathJax.startup.output) {
    MathJax.startup.output.clearCache();
    MathJax.typesetClear();
    MathJax.texReset();
    MathJax.typesetPromise();
  } else if (!document.getElementById("mathjax-lib")) {
    const s = document.createElement("script");
    s.id = "mathjax-lib";
    s.async = true;
    s.src = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js";  // typesets the page itself once loaded
    document.head.appendChild(s);
  }
}
if (typeof document$ !== "undefined") document$.subscribe(renderMath);
else document.addEventListener("DOMContentLoaded", renderMath);
