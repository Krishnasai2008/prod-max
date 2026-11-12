"""Variants of real questions, written by a model and kept only when a second, independent solve agrees.

A typed variant (number or choice) whose key the second solve doesn't reproduce is thrown away; an open
variant is kept as `checked` when a model judges the two answers the same, else as `unverified`.
Nothing here ever sets trust above `checked`.
"""
import hashlib
import re
from datetime import datetime

from pm import agent, bank, grade
from pm.excerpt import FULL, excerpt, kind_of

MAX_PROMPT = 20_000
MAX_OPTIONS = 6

WRITE = """You write exam practice questions. Below is one real exam question and its answer. Write {n} new questions that test the same idea in a different way: change the numbers and the situation, ask for a different quantity, or turn the question around. Each new question must be answerable from its own text alone.

Return only a JSON list. Each item is an object with:
- "prompt": the question text (Markdown and $…$ maths are allowed)
- "kind": "number", "choice" or "open"
- for "number": "value" (the answer, a number) and "tol" (the allowed error, a number)
- for "choice": "options" (2 to 6 strings) and "correct" (the 1-based numbers of the correct options)
- for "open": "answer" (a model answer in a few sentences)

<question>
{question}
</question>
<answer>
{answer}
</answer>"""

SOLVE = """Answer this exam question. Work it out, then write the final answer alone on the last line.
For a numeric answer, the last line is just the number. For a multiple-choice question, the last line is just the number or numbers of the correct options.

{question}"""

COMPARE = """Two answers to the same exam question follow. Would a marker give them the same marks because they say the same thing? Reply with one word: same or different.

<question>
{question}
</question>
<answer-1>
{first}
</answer-1>
<answer-2>
{second}
</answer-2>"""


def _fill(template: str, **values: str) -> str:
    # plain replacement, never str.format: the values hold braces (maths, JSON)
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m[1], m[0]), template)


def source_text(conn, question) -> tuple[str, str]:
    if question.retired or question.parent_id is not None:
        raise ValueError("make variants from an original question")
    if question.path is not None and question.locator is not None and kind_of(question.path, question.locator) == "pdf":
        label = question.ref.split("/", 1)[1] if question.origin == "paper" and "/" in question.ref else question.prompt
        try:
            page = excerpt(question.path, question.locator, FULL).strip()
        except (OSError, ValueError):
            page = ""
        if not page:
            raise ValueError("that question has no text for a model to read")
        text = f'The question labelled "{label}" on this page:\n\n{page}'
    else:
        text = question.prompt
    if question.expected is not None and question.kind != "open":
        answer = grade.show(question.kind, question.expected)
    else:
        answer = question.answer or "(no answer on record)"
    return text, answer


def parse_items(reply: str) -> list[dict]:
    data = agent.parse_json(reply)
    if not isinstance(data, list):
        raise ValueError("the model's reply wasn't the expected JSON")
    items = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        prompt, kind = raw.get("prompt"), raw.get("kind")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
            continue
        try:
            if kind == "number":
                expected = grade.parse_expected("number", {"value": raw.get("value"), "tol": raw.get("tol", 0)})
            elif kind == "choice":
                options = raw.get("options")
                if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS:
                    continue
                expected = grade.parse_expected("choice", {"options": options, "correct": raw.get("correct")})
            elif kind == "open":
                answer = raw.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    continue
                items.append({"prompt": prompt.strip(), "kind": "open", "answer": answer.strip()})
                continue
            else:
                continue
        except ValueError:
            continue
        items.append({"prompt": prompt.strip(), "kind": kind, "expected": expected})
    return items


def _norm(text: str) -> str:
    return grade.clean(text).casefold()


def _asked(item: dict) -> str:
    if item["kind"] != "choice":
        return item["prompt"]
    return item["prompt"] + "\n\n" + "\n".join(f"{i}) {o}" for i, o in enumerate(item["expected"]["options"], 1))


def _last_line(reply: str) -> str:
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def make(conn, question_id: int, now: datetime, ask, n: int = 3) -> tuple[int, int]:
    parent = bank.get_question(conn, question_id)
    text, answer = source_text(conn, parent)
    items = parse_items(ask(_fill(WRITE, n=str(n), question=text, answer=answer)))[:n]
    seen = {_norm(parent.prompt), _norm(text)}
    seen |= {_norm(r[0]) for r in conn.execute("SELECT prompt FROM questions WHERE parent_id=?", (parent.id,))}
    added = dropped = 0
    for item in items:
        key = _norm(item["prompt"])
        ref = f"{parent.id}/{hashlib.sha1(item['prompt'].encode()).hexdigest()[:12]}"
        if key in seen or bank.has(conn, "variant", ref):
            dropped += 1
            continue
        seen.add(key)
        solved = ask(_fill(SOLVE, question=_asked(item)))
        if item["kind"] == "open":
            verdict = ask(_fill(COMPARE, question=item["prompt"], first=item["answer"], second=solved))
            words = verdict.strip().split()
            trust = "checked" if words and words[0].strip(".,;:!\"'*").casefold() == "same" else "unverified"
            fields = {"answer": item["answer"]}
        else:
            if not grade.check(item["kind"], item["expected"], _last_line(solved)):
                dropped += 1
                continue
            trust = "checked"
            fields = {"kind": item["kind"], "expected": item["expected"]}
        bank.add_question(conn, origin="variant", ref=ref, prompt=item["prompt"], now=now, trust=trust,
                          topic_id=parent.topic_id, marks=parent.marks, parent_id=parent.id, **fields)
        added += 1
    return added, dropped


def _job(conn, arg: str, now: datetime, ask) -> str:
    if not (arg.isascii() and arg.isdigit()):
        raise ValueError(f"variants needs a question id, not {arg!r}")
    added, dropped = make(conn, int(arg), now, ask)
    return f"{added} added, {dropped} dropped"


agent.HANDLERS["variants"] = _job
