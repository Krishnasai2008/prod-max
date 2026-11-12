import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pm.db import connect
from pm.spot import PROMPT, answer, candidates, check, eligible, get, make, pending
from pm.study import add_item, add_topic, record_review

NOW = datetime(2026, 11, 9, 10)
NOTE = """# OS

## TLB
The TLB caches page table entries.
A TLB hit avoids a page table walk.
The TLB is flushed on a context switch without ASIDs.
Larger pages mean more TLB reach.
A miss costs one memory access per level.
Hardware or the OS can refill it.
"""
SECTION = ("## TLB\n" + NOTE.split("## TLB\n")[1]).rstrip("\n").split("\n")  # the excerpt keeps its heading


def change(line: int):
    def ask(prompt: str) -> str:
        ask.prompts.append(prompt)
        lines = list(SECTION)
        lines[line - 1] = "The TLB caches disk blocks."
        return "\n".join(lines)
    ask.prompts = []
    return ask


class TestCheck(unittest.TestCase):
    def test_check(self):
        self.assertEqual(check("a\nb\nc\nd", "a\nB\nc\nd"), 2)
        self.assertEqual(check("a  \r\nb", "a\nB"), 2)
        for original, mutated, message in [
            ("a\nb", "a\nb", "no line changed"),
            ("a\nb\nc", "A\nB\nc", "more than one line changed"),
            ("a\nb", "a\nb\nc", "the line count changed"),
            ("a\nb", "a\n   ", "the changed line is blank"),
            ("## TLB\nb", "## Cache\nb", "the changed line is a heading"),
        ]:
            with self.subTest(mutated=mutated), self.assertRaisesRegex(ValueError, f"^{message}$"):
                check(original, mutated)

    def test_eligible(self):
        self.assertFalse(eligible("a\nb\nc"))
        self.assertTrue(eligible("a\nb\nc\nd"))
        self.assertFalse(eligible("\n".join(["x"] * 61)))
        self.assertFalse(eligible("\n".join(["y" * 1000] * 6) + "z"))


class TestSpot(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        self.path = Path(self.d.name) / "os.md"
        self.path.write_text(NOTE)
        add_topic(self.c, "paging", course="os")
        self.item = add_item(self.c, 1, self.path, "TLB", now=NOW)

    def count(self):
        return self.c.execute("SELECT COUNT(*) FROM spots").fetchone()[0]

    def test_make_stores_the_changed_line(self):
        ask = change(3)
        spot_id = make(self.c, self.item, NOW, ask)
        spot = get(self.c, spot_id)
        self.assertEqual(spot.line, 3)
        self.assertEqual(spot.original, "\n".join(SECTION))
        self.assertIn("exactly ONE line", ask.prompts[0])
        self.assertIn(SECTION[0], ask.prompts[0])
        self.assertEqual(len(ask.prompts), 1)

    def test_a_fenced_reply_is_unwrapped(self):
        inner = change(2)
        spot_id = make(self.c, self.item, NOW, lambda p: "```md\n" + inner(p) + "\n```")
        self.assertEqual(get(self.c, spot_id).line, 2)

    def test_two_changed_lines_twice_stores_nothing(self):
        calls = []

        def ask(prompt):
            calls.append(prompt)
            return "\n".join(["changed", "also changed", *SECTION[2:]])
        with self.assertRaisesRegex(ValueError, "^the model didn't change exactly one line: more than one"):
            make(self.c, self.item, NOW, ask)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.count(), 0)

    def test_a_bad_first_reply_is_retried(self):
        good, calls = change(4), []

        def ask(prompt):
            calls.append(prompt)
            return "Here is the excerpt:\n" + good(prompt) if len(calls) == 1 else good(prompt)
        make(self.c, self.item, NOW, ask)
        self.assertEqual((len(calls), self.count()), (2, 1))

    def test_an_ask_error_stops_at_once(self):
        calls = []

        def ask(prompt):
            calls.append(prompt)
            raise ValueError("set llm_cmd first, like: pm set llm_cmd 'my-llm --model small'")
        with self.assertRaisesRegex(ValueError, "^set llm_cmd first"):
            make(self.c, self.item, NOW, ask)
        self.assertEqual(len(calls), 1)

    def test_pdf_and_short_excerpts_are_refused(self):
        pdf = Path(self.d.name) / "slides.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        pdf_item = add_item(self.c, 1, pdf, "p2", now=NOW)
        with self.assertRaisesRegex(ValueError, "^spot-the-error needs a text or markdown item$"):
            make(self.c, pdf_item, NOW, change(1))
        short = Path(self.d.name) / "short.md"
        short.write_text("## A\none\ntwo\n")
        short_item = add_item(self.c, 1, short, "A", now=NOW)
        with self.assertRaisesRegex(ValueError, "too short or too long"):
            make(self.c, short_item, NOW, change(1))

    def test_a_card_grades_from_its_stored_copy(self):
        spot_id = make(self.c, self.item, NOW, change(3))
        self.path.write_text("# gone\n")
        self.assertEqual(get(self.c, spot_id).original, "\n".join(SECTION))
        self.assertTrue(answer(self.c, spot_id, 3, 0.8, NOW))

    def test_answer(self):
        spot_id = make(self.c, self.item, NOW, change(3))
        for picked in (0, 99, True):
            with self.subTest(picked=picked), self.assertRaisesRegex(ValueError, "^pick a line between 1 and 7$"):
                answer(self.c, spot_id, picked, 0.8, NOW)
        with self.assertRaisesRegex(ValueError, "^confidence must be 0-1$"):
            answer(self.c, spot_id, 3, 1.5, NOW)
        self.assertFalse(answer(self.c, spot_id, 2, 0.8, NOW))
        spot = get(self.c, spot_id)
        self.assertEqual((spot.picked, spot.confidence, spot.answered), (2, 0.8, NOW))
        with self.assertRaisesRegex(ValueError, "^that card is already answered$"):
            answer(self.c, spot_id, 3, 0.8, NOW)
        with self.assertRaises(LookupError):
            get(self.c, 99)

    def test_candidates(self):
        record_review(self.c, self.item, 1, 0.5, NOW)
        self.assertEqual(candidates(self.c, 5), [])
        record_review(self.c, self.item, 3, 0.5, NOW)
        self.assertEqual(candidates(self.c, 5), [self.item])
        spot_id = make(self.c, self.item, NOW, change(3))
        self.assertEqual(candidates(self.c, 5), [])
        self.assertEqual([s.id for s in pending(self.c)], [spot_id])
        answer(self.c, spot_id, 3, 0.8, NOW)
        other = add_item(self.c, 1, self.path, None, now=NOW)
        record_review(self.c, other, 4, 0.5, NOW)
        self.assertEqual(candidates(self.c, 5), [other, self.item])  # never spotted comes first
        self.assertEqual(candidates(self.c, 1), [other])

    def test_the_prompt_names_the_rules(self):
        self.assertIn("{text}", PROMPT)
