"""Model drafts the user reviews before use: a past paper's question list, and formula templates.

Neither is used until the user acts: an outline is printed for editing and `pm paper import`, and a
template waits in `templates/drafts/` until `pm template approve`, which runs the full check again.
"""
import os
import re
from pathlib import Path

from pm import bank, generators, llm, templates
from pm.excerpt import FULL, excerpt, outline
from pm.study import topics

MAX_PAGES_TEXT = 60_000
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
_ID_LINE = re.compile(r'^(\s*id\s*=\s*)"[^"\n]*"', re.M)

OUTLINE = """Below is the text of an exam paper, page by page. List its questions, one per line, in this exact format:

label | marks | topic | where

- label: the question's label as printed, such as Q1a or 3(b)
- marks: the marks for that question, a number; write 1 if the paper doesn't say
- topic: the best match from the topic list below, copied exactly
- where: p and the page number the question starts on, such as p2

List sub-questions separately when they have their own marks. Output only the lines.

Topics:
{topics}

{pages}"""

EXAMPLE = '''id = "mm1-wait"
version = 1
title = "M/M/1 time in system"
text = "Jobs arrive at {lam} per hour and one server finishes {mu} per hour. What is the mean time a job spends in the system, in minutes?"
answer = "60 / (mu - lam)"
decimals = 2
steps = "W = 1 / (mu − lam) hours = 60 / ({mu} − {lam}) = {answer} minutes."
constraints = ["mu > lam", "(6000 / (mu - lam)) % 1 == 0"]

[params]
lam = { int = [2, 20] }
mu = { int = [3, 30] }

[original]
params = { lam = 8, mu = 12 }
answer = 15'''

TEMPLATE = """Turn this exam question into a reusable template in TOML, so new versions can be made by changing its numbers. The answer must be an arithmetic formula of the parameters.

Rules:
- "answer" may use + - * / // % ** and the functions min, max, abs, round, floor, ceil, sqrt, gcd, comb, factorial, log, exp. Nothing else.
- Give each parameter a sensible range with "int", "choice" or "decimal".
- Add "constraints" so every drawn problem makes sense and has a clean answer.
- "[original]" must hold the numbers of the question below and its known answer, {answer}. The formula has to reproduce it.
- Output only the TOML.

Example:
{example}

<question>
{question}
</question>"""


def _fill(template: str, **values: str) -> str:
    # plain replacement, never str.format: the values hold braces
    return re.sub(r"\{(\w+)\}", lambda m: values[m[1]] if m[1] in values else m[0], template)


def paper_outline(conn, paper_id: int, ask) -> str:
    paper = bank.get_paper(conn, paper_id)
    if paper.path is None:
        raise ValueError("that paper has no PDF to read")
    try:
        count = len(outline(paper.path))
    except (OSError, ValueError):
        count = 0
    blocks = []
    for n in range(1, count + 1):
        try:
            text = excerpt(paper.path, f"p{n}", FULL).strip()
        except (OSError, ValueError):
            text = ""
        if text:
            blocks.append(f"--- page {n} ---\n{text}")
    if not blocks:
        raise ValueError("couldn't read any text from that PDF (is it a scan?)")
    names = "\n".join(t.name for t in topics(conn) if t.course == paper.course)
    reply = ask(_fill(OUTLINE, topics=names, pages="\n\n".join(blocks)[:MAX_PAGES_TEXT]))
    out = ["# label | marks | topic | where | answer", "# drafted by a model: check every line against the paper"]
    for raw in llm.fenced(reply.strip()).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        errors = bank.check_paper_lines(conn, paper_id, [line])
        out.append(f"# ? {line}   ({errors[0].split(': ', 1)[1]})" if errors else line)
    return "\n".join(out) + "\n"


def template(conn, question_id: int, ask, tries: int = 2) -> str:
    q = bank.get_question(conn, question_id)
    if q.kind != "number" or not q.expected:
        raise ValueError("a template draft needs a question with a numeric answer")
    prompt = _fill(TEMPLATE, answer=f"{q.expected['value']:g}", example=EXAMPLE, question=q.prompt)
    asked, message = prompt, ""
    for _ in range(max(1, tries)):
        text = llm.fenced(ask(asked).strip()).strip() + "\n"
        try:
            templates.parse(text)
            return text
        except ValueError as e:
            message = str(e)
            asked = f"{prompt}\n\nYour last attempt was rejected: {message}. Fix it."
    raise ValueError(f"the model didn't produce a valid template: {message}")


def _folders(conn) -> tuple[Path, Path]:
    folder = templates.folder_of(conn)
    if folder is None:
        raise ValueError("the database is in memory, so there is no templates folder")
    return folder, folder / "drafts"


def save_template(conn, text: str) -> Path:
    t = templates.parse(text)
    folder, drafts = _folders(conn)
    loaded = set(generators.ids())
    name, n = t.id, 1
    while f"t:{name}" in loaded or (drafts / f"{name}.toml").exists() or (folder / f"{name}.toml").exists():
        n += 1
        name = f"{t.id}-{n}"
    if name != t.id:
        text = _ID_LINE.sub(lambda m: f'{m[1]}"{name}"', text, count=1)
        templates.parse(text)
    try:
        drafts.mkdir(parents=True, exist_ok=True)
        path = drafts / f"{name}.toml"
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise ValueError(str(e)) from None
    return path


def approve_template(conn, name: str) -> Path:
    folder, drafts = _folders(conn)
    draft = drafts / f"{name}.toml"
    if not _ID.fullmatch(name) or not draft.is_file():
        raise LookupError(f"no draft called {name!r}")
    templates.check_file(draft)
    target = folder / f"{name}.toml"
    if target.exists():
        raise ValueError(f"a template called {name} is already in use")
    try:
        os.replace(draft, target)
    except OSError as e:
        raise ValueError(str(e)) from None
    return target
