"""
Fix four Markdown patterns that render badly, without you editing your notes:

1. A list that starts right under a line of text ("Scope:" then "- item")
   is glued into that paragraph unless a blank line separates them.
   This adds the blank line.
2. A note's "_Added: 2026-09-27_" line becomes a small date label
   (styled by .added in stylesheets/extra.css).
3. Money amounts like "S ($26) ... T ($28)": the math renderer would pair
   the two $ signs and show the text between them as a formula. Such a $
   gets escaped (\\$). Real math like $2x + 3$ or $10^6$ is left alone.
   shortcut: it is a guess from the text between the two $ signs; if a line
   still shows money as a formula, write \\$ in that note yourself.
4. $$ display math written the way VS Code's preview accepts it: a $$...$$
   line glued to the text above or below gets blank lines around it (the
   site only draws a $$ block that stands alone), and $$...$$ in the middle
   of a sentence becomes $\\displaystyle ...$. A $$ line indented by 2 or 3
   spaces under a list item is moved to a multiple of 4 spaces, the only
   indents the site understands. In a table row, a | inside $...$ (like
   $|x|$) becomes \\vert, so it doesn't split the cell.

Code blocks, `code`, the inside of $$ math blocks and front matter are never touched.

Run from the project root:  python tidy_markdown.py
build.sh runs it before every deploy; run it yourself before `zensical serve`
if you want to preview the same result locally.
"""
import re
from pathlib import Path

DOCS = Path("docs")
LIST_ITEM = re.compile(r"([-*+]|\d+\.)\s")           # an unindented list item
ANY_LIST_ITEM = re.compile(r"\s*([-*+]|\d+\.)\s")
ADDED = re.compile(r"_Added: ([^_]+)_")
FENCE = re.compile(r"\s*(```|~~~)")
INLINE_MATH = re.compile(r"(?<!\\)\$(?!\s)((?:\\.|[^\\$])+?)(?<!\s)\$")  # pymdownx.arithmatex's own $...$ rule
CODE_SPAN = re.compile(r"(`+).+?\1")
QUOTE = re.compile(r"(?:\s*>)*\s*")  # a line's blockquote markers and indent
INLINE_DISPLAY = re.compile(r"\$\$(?!\s)(.+?)(?<!\s)\$\$")


def money(m: re.Match) -> bool:
    """A $...$ pair that is really money (or a plain $ sign) with text between, not math."""
    body, after = m.group(1), m.string[m.end():m.end() + 1]
    unit = re.compile(r"(₹|Rs\.?|INR|€|£|¥) ?[\d.,]* ?/$")  # "₹45/$" : $ as a unit
    if unit.search(m.string[max(0, m.start() - 15):m.start()]) or unit.search(m.string[max(0, m.end() - 16):m.end() - 1]) \
            or re.match(r"[),:;\]}]", body):
        return True  # also LR-parser "$" end markers like "{$}.": math never opens like that
    return bool(re.match(r"\(?\.?\d", body)) and not re.search(r"\\(?!\$)|\^|_\{", body) and \
        bool(re.search(r"[a-z]{3,}|\*\*", body) or after.isdigit())


def escape_money(para: str) -> str:
    text = CODE_SPAN.sub(lambda c: c.group(0).replace("$", "\0"), para)  # never touch `code`
    while True:  # repeat: an escaped \$ can sit inside a pair, so escaping one $ can create a new pair
        out, pos = [], 0
        while m := INLINE_MATH.search(text, pos):
            if money(m):
                out.append(text[pos:m.start()] + "\\$")
                pos = m.start() + 1  # the closing $ may open the next pair
            else:
                out.append(text[pos:m.end()])
                pos = m.end()
        new = "".join(out) + text[pos:]
        if new == text:
            return text.replace("\0", "$")
        text = new


def snap(line: str) -> str:  # "  $$x$$" -> "$$x$$", "     $$x$$" -> "    $$x$$"
    n = len(line) - len(line.lstrip(" "))
    return line[n % 4:] if line.lstrip(" ")[:1] != ">" else line


def masked(line: str) -> str:
    return CODE_SPAN.sub(lambda c: "\0" * len(c.group(0)), line)  # `code` blanked out, same length


def tidy(text: str) -> str:
    lines = text.split("\n")
    out, prose = [], []
    fence = math = gap = False  # gap: the line before was a $$ block that needs a blank line after it
    front = bool(lines) and lines[0] == "---"
    for i, line in enumerate(lines):
        prev = out[-1] if out else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        quote = QUOTE.match(line).group(0)
        blank = quote.rstrip().lstrip(" ") if ">" in quote else ""  # a blank line that stays inside the > quote
        body, code = line[len(quote):].rstrip(), masked(line)
        if gap and line.strip() and not math:
            out.append(blank)
            prev = blank
        gap = False
        if front:
            front = not (i > 0 and line == "---")
        elif FENCE.match(line):
            fence = not fence
        elif fence:
            pass
        elif code.count("$$") % 2:  # a $$ block starts or ends here
            if not math and body.startswith("$$"):
                line = snap(line)
                if prev.strip(" >"):
                    out.append(blank)
            gap = math and body.endswith("$$")
            math = not math
        elif math:
            pass
        elif body.startswith("$$") and body.endswith("$$") and code.count("$$") == 2:  # one-line $$ block
            line = snap(line)
            if prev.strip(" >"):
                out.append(blank)
            gap = True
        else:
            if "$$" in code:  # $$...$$ mid-sentence
                line = INLINE_DISPLAY.sub(lambda m: m.group(0) if "\0" in code[m.start():m.end()]
                                          else f"$\\displaystyle {m.group(1)}$", line)
            if line.lstrip().startswith("|"):  # table row: a | inside math would split the cell
                for m in reversed(list(INLINE_MATH.finditer(masked(line)))):  # masked: same positions, `code` skipped
                    line = line[:m.start()] + re.sub(r"(?<!\\)\|", r"\\vert{}", m.group(0)) + line[m.end():]
            if LIST_ITEM.match(line) and prev.strip() and not ANY_LIST_ITEM.match(prev) \
                    and not prev.startswith(("|", "#", ">", "<", "    ", "\t")):
                out.append("")
            m = ADDED.fullmatch(line)
            if m and (not prev.strip() or prev.startswith("#")) and not nxt.strip():
                out += [f"Added {m.group(1)}", "{ .added }"]
                continue
            prose.append(len(out))
        out.append(line)
    # money: work per paragraph (consecutive prose lines), since a $...$ pair can span lines
    para = []
    for i in prose + [-1]:
        if para and (i != para[-1] + 1 or not out[i].strip()):
            first = out[para[0]].lstrip()
            if not first.startswith("<") or "markdown" in first:  # raw HTML: no math there, so leave $ alone
                out[para[0]:para[-1] + 1] = escape_money("\n".join(out[para[0]:para[-1] + 1])).split("\n")
            para = []
        if i >= 0 and out[i].strip():
            para.append(i)
    return "\n".join(out)


assert tidy("Scope:\n- a\n- b") == "Scope:\n\n- a\n- b"
assert tidy("```\ntext\n- not a list\n```") == "```\ntext\n- not a list\n```"
assert tidy("---\ntags:\n- x\n---\nhi") == "---\ntags:\n- x\n---\nhi"
assert tidy("## H\n_Added: 2026-09-27_\n\nx") == "## H\nAdded 2026-09-27\n{ .added }\n\nx"
assert tidy("text\n_Added: 2026-09-27_\n") == "text\n_Added: 2026-09-27_\n"
assert tidy("**13. (A) S ($26).** Labor is cheap. T ($28) loses.") == "**13. (A) S (\\$26).** Labor is cheap. T ($28) loses."  # a lone $ is shown as-is
assert tidy("Profit is $8,000\nand loss ($3,000) here") == "Profit is \\$8,000\nand loss ($3,000) here"
assert tidy("Profit:\n- TR = $1,000(total revenue)+$600 here") == "Profit:\n\n- TR = \\$1,000(total revenue)+$600 here"
assert tidy("from $.08 to $.31 (2008). It cut to **$.10**") == "from \\$.08 to \\$.31 (2008). It cut to **$.10**"
assert tidy("**₹30/$**; if the rate is ₹45/$, goods") == "**₹30/\\$**; if the rate is ₹45/$, goods"
assert tidy("so FIRST(ε$) = {$}. The end of input ($). Next") == "so FIRST(ε\\$) = {\\$}. The end of input ($). Next"
assert tidy("max at $1. So **saddle at {$1, $1}**") == "max at \\$1. So **saddle at {$1, $1}**"
assert tidy("₹45/$ ⇒ $/₹ = 1/45; ₹50/$ ⇒ 1/50") == "₹45/$ ⇒ \\$/₹ = 1/45; ₹50/$ ⇒ 1/50"
assert tidy("<details>\n<b>Use:</b> potential $5.4T, actual $4.96T → −$0.44T\n</details>") == \
    "<details>\n<b>Use:</b> potential $5.4T, actual $4.96T → −$0.44T\n</details>"
assert tidy("costs $5/$10 each") == "costs \\$5/$10 each"
assert tidy("(new ₹/$ − old ₹/$) / old ₹/$ |") == "(new ₹/$ − old ₹/\\$) / old ₹/$ |"
assert tidy("a = $: FIRST($) = {$}.") == "a = \\$: FIRST(\\$) = {$}."
assert tidy("Investing $(14,000) + Financing (**$500,000**)") == "Investing \\$(14,000) + Financing (**$500,000**)"
assert tidy("a $1,000 bond at $1,050 has a premium of **$50**.") == "a \\$1,000 bond at \\$1,050 has a premium of **$50**."
# $$ display math, as VS Code draws it
assert tidy("### 9. Coefficients\n$$a_{ij} = \\frac{X_{ij}}{X_j}$$\n— the proportion") == \
    "### 9. Coefficients\n\n$$a_{ij} = \\frac{X_{ij}}{X_j}$$\n\n— the proportion"
assert tidy("form:\n$$X = F$$\n$$Y = G$$\nnext") == "form:\n\n$$X = F$$\n\n$$Y = G$$\n\nnext"
assert tidy("1. step\n   $$x^2$$\n   more") == "1. step\n\n$$x^2$$\n\n   more"
assert tidy("- a:\n\n  $$x$$\n\n  b") == "- a:\n\n$$x$$\n\n  b"
assert tidy("  3. Then\n\n     $$x$$\n") == "  3. Then\n\n    $$x$$\n"
assert tidy("> quote\n> $$x$$\n> more") == "> quote\n>\n> $$x$$\n>\n> more"
assert tidy("text\n$$\na + b\n= c\n$$\nafter") == "text\n\n$$\na + b\n= c\n$$\n\nafter"
assert tidy("text\n    $$a\n    + b$$\n    after") == "text\n\n    $$a\n    + b$$\n\n    after"
assert tidy("**Core:** $$P(A) = 1$$ It relates") == "**Core:** $\\displaystyle P(A) = 1$ It relates"
assert tidy("\n$$x$$\n\nok") == "\n$$x$$\n\nok"
assert tidy("| $\\ln|x|$ | $\\frac{|B-C|}2$ |") == "| $\\ln\\vert{}x\\vert{}$ | $\\frac{\\vert{}B-C\\vert{}}2$ |"
assert tidy("| `a|b` | $x$ |") == "| `a|b` | $x$ |"
assert tidy("| `a|b` | $|x|$ |") == "| `a|b` | $\\vert{}x\\vert{}$ |"
assert tidy("| $R^2$ | $1 - SS_{res}/SS_{tot}$ | — |") == "| $R^2$ | $1 - SS_{res}/SS_{tot}$ | — |"
for code in ["`$$` this PID, `$!` last", "Bison: `$1..$k` are values and `$$` is the head's:\nnext $5 and $6"]:
    assert tidy(code) == code, code
assert tidy("`$$ = $1` default\nThen $$x$$ here\n- a") == "`$$ = $1` default\nThen $\\displaystyle x$ here\n\n- a"  # `$$` in code no longer flips math mode
for math in ["state $H_0$/$H_1$ and $t$/$F$", "outcomes $/\\,k$.", "range $0 … TMax$ are", "balance: $.75\\times N = .25\\times M$", "$2x + 3 = 5$", "$10^6$", "$3$ and $4$", "$2\\text{ lakh}$", "`$5 and $6` code", "$x$ costs $5"]:
    assert tidy(math) == math, math

if __name__ == "__main__":
    changed = 0
    for md in DOCS.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # leave files that aren't valid UTF-8 exactly as they are
        new = tidy(text)
        if new != text:
            md.write_text(new, encoding="utf-8")
            changed += 1
    print(f"Tidied {changed} notes")
