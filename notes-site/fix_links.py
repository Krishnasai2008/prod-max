"""
Repair links between notes after you move folders or notes around.

A link like [DFA](../stage-1/topic-dfa.md) that no longer points to a file
is re-pointed to wherever a note with that file name now lives.
Only rewrites a link when exactly one match exists; everything else is
left alone and listed. Code blocks and inline code are never touched.

Run from the project root:  python fix_links.py          (fix files)
                            python fix_links.py --check  (only report)
Limitation: a note you RENAMED can't be found automatically - fix those by hand.
"""
import os, re, sys
from pathlib import Path
from urllib.parse import unquote
from collections import defaultdict

DOCS = Path("docs")
CHECK = "--check" in sys.argv
LINK = re.compile(r"(\[[^\]]*\]\()(<[^>]+>|[^)\s]+)((?:\s+\"[^\"]*\")?\))")
CODE = re.compile(r"(`+)(?:.*?)\1")
FENCE = re.compile(r"^\s*(```|~~~)")
INDEXES = {"index.md", "readme.md"}


def key(p: Path):
    # index pages are identified by their folder name, other notes by file name
    return (p.parent.name.lower(), p.name.lower()) if p.name.lower() in INDEXES else p.name.lower()


by_key = defaultdict(list)
for f in DOCS.rglob("*.md"):
    by_key[key(f)].append(f)

fixed, unfixable = 0, []


def repair(note: Path, m):
    global fixed
    raw = m.group(2)
    target = raw[1:-1] if raw.startswith("<") else raw
    path, _, anchor = target.partition("#")
    if not path.lower().endswith(".md") or re.match(r"^[a-z]+:|^/", path):
        return m.group(0)                         # web links, anchors, non-notes
    if (note.parent / unquote(path)).exists():
        return m.group(0)                         # link still works
    hits = by_key.get(key(Path(unquote(path))), [])
    if len(hits) != 1:
        unfixable.append(f"{note}: {target}")
        return m.group(0)
    new = os.path.relpath(hits[0], note.parent).replace(os.sep, "/") + ("#" + anchor if anchor else "")
    if " " in new:
        new = "<" + new + ">"
    fixed += 1
    return m.group(1) + new + m.group(3)


for note in sorted(DOCS.rglob("*.md")):
    text = note.read_bytes().decode("utf-8")
    out, in_fence = [], False
    for line in text.splitlines(keepends=True):
        if FENCE.match(line):
            in_fence = not in_fence
        if in_fence or FENCE.match(line) or "](" not in line:
            out.append(line); continue
        parts, last, new = [], 0, ""
        for c in CODE.finditer(line):
            new += LINK.sub(lambda m: repair(note, m), line[last:c.start()]) + c.group(0); last = c.end()
        out.append(new + LINK.sub(lambda m: repair(note, m), line[last:]))
    result = "".join(out)
    if result != text and not CHECK:
        note.write_bytes(result.encode("utf-8"))

print(f"{'Would fix' if CHECK else 'Fixed'} {fixed} links")
if unfixable:
    print(f"{len(unfixable)} broken links need a manual fix (renamed, deleted, or ambiguous):")
    print("\n".join("  " + u for u in unfixable))
