import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pm import agent, bank, variants
from pm.db import connect, put_setting
from pm.study import add_topic

NOW = datetime(2026, 11, 9, 10, 0)
PARENT = "A disk has 200 cylinders. How far does the head move?"
ITEMS = [
    {"prompt": "A disk has 300 cylinders. How far does the head move?", "kind": "number", "value": 42, "tol": 0},
    {"prompt": "Which policy can starve a request?", "kind": "choice", "options": ["FCFS", "SSTF", "C-LOOK"],
     "correct": [2]},
    {"prompt": "Why does SCAN avoid starvation?", "kind": "open", "answer": "It sweeps both ways."},
]


class Asker:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("asked more than expected")
        return self.replies.pop(0)


def good(*extra, items=ITEMS):
    return Asker(json.dumps(items), "Working: …\n42", "so\n2", "It sweeps in both directions.", "same", *extra)


class VariantCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        add_topic(self.c, "disk", course="os")
        self.parent = bank.add_question(self.c, origin="manual", ref="m1", prompt=PARENT, now=NOW, trust="source",
                                        topic_id=1, kind="number", expected={"value": 36, "tol": 0}, marks=4)

    def variants(self):
        return bank.questions(self.c, origin="variant")


class TestMake(VariantCase):
    def test_three_checked(self):
        ask = good()
        self.assertEqual(variants.make(self.c, self.parent, NOW, ask), (3, 0))
        found = self.variants()
        self.assertEqual(len(found), 3)
        for q in found:
            self.assertEqual((q.origin, q.parent_id, q.topic_id, q.marks, q.trust), ("variant", 1, 1, 4, "checked"))
        self.assertEqual(len(ask.prompts), 5)
        self.assertIn(PARENT, ask.prompts[0])
        self.assertIn("<answer>\n36\n</answer>", ask.prompts[0])
        self.assertIn("1) FCFS\n2) SSTF\n3) C-LOOK", ask.prompts[2])
        self.assertEqual({q.kind for q in found}, {"number", "choice", "open"})

    def test_wrong_key_is_dropped(self):
        ask = Asker(json.dumps(ITEMS), "41", "2", "x", "same")
        self.assertEqual(variants.make(self.c, self.parent, NOW, ask), (2, 1))
        self.assertNotIn("number", {q.kind for q in self.variants()})

    def test_last_line_is_the_answer(self):
        ask = Asker(json.dumps(ITEMS[:1]), "Working…\n\nSo the answer is\n42\n")
        self.assertEqual(variants.make(self.c, self.parent, NOW, ask), (1, 0))

    def test_open_disagreement_is_unverified(self):
        for verdict in ("Different.", "maybe"):
            with self.subTest(verdict=verdict):
                self.c.execute("DELETE FROM questions WHERE origin='variant'")
                self.c.commit()
                ask = Asker(json.dumps(ITEMS[2:]), "something", verdict)
                self.assertEqual(variants.make(self.c, self.parent, NOW, ask), (1, 0))
                self.assertEqual(self.variants()[0].trust, "unverified")
        ask = Asker(json.dumps([{**ITEMS[2], "prompt": "Why is SCAN fair?"}]), "x", "**Same**")
        variants.make(self.c, self.parent, NOW, ask)
        self.assertEqual({q.prompt: q.trust for q in self.variants()}["Why is SCAN fair?"], "checked")

    def test_duplicates_dropped(self):
        items = [{**ITEMS[0], "prompt": "  a DISK has 200 cylinders.  How far does the head   move? "}, ITEMS[0], ITEMS[0]]
        ask = Asker(json.dumps(items), "42")
        self.assertEqual(variants.make(self.c, self.parent, NOW, ask), (1, 2))

    def test_bad_items_and_replies(self):
        items = [{"prompt": "x", "kind": "essay"}, {"prompt": "", "kind": "open", "answer": "a"},
                 {"prompt": "c", "kind": "choice", "options": ["a", "b"], "correct": [3]},
                 {"prompt": "n", "kind": "number", "value": "ten"},
                 {"prompt": "c7", "kind": "choice", "options": list("abcdefg"), "correct": [1]},
                 {"prompt": "o", "kind": "open", "answer": ""}, "a string", ITEMS[0]]
        self.assertEqual([i["prompt"] for i in variants.parse_items(json.dumps(items))], [ITEMS[0]["prompt"]])
        with self.assertRaisesRegex(ValueError, "expected JSON"):
            variants.make(self.c, self.parent, NOW, Asker("Sorry, I can't."))
        with self.assertRaisesRegex(ValueError, "expected JSON"):
            variants.parse_items('{"prompt": "not a list"}')
        self.assertEqual(self.variants(), [])

    def test_fenced_reply(self):
        reply = "Here are the questions:\n```json\n" + json.dumps(ITEMS[:1]) + "\n```"
        self.assertEqual(variants.make(self.c, self.parent, NOW, Asker(reply, "42")), (1, 0))

    def test_idempotent(self):
        variants.make(self.c, self.parent, NOW, good())
        self.assertEqual(variants.make(self.c, self.parent, NOW, Asker(json.dumps(ITEMS))), (0, 3))
        self.assertEqual(len(self.variants()), 3)

    def test_n_caps_the_items(self):
        five = [{**ITEMS[0], "prompt": f"variant {i}"} for i in range(5)]
        ask = Asker(json.dumps(five), "42", "42")
        self.assertEqual(variants.make(self.c, self.parent, NOW, ask, n=2), (2, 0))
        self.assertIn("Write 2 new questions", ask.prompts[0])

    def test_pdf_page_question(self):
        pdf = Path(__file__)  # any file; the excerpt is patched
        paper = bank.add_paper(self.c, "os", "2025 midsem", NOW)
        q = bank.add_question(self.c, origin="paper", ref=f"{paper}/Q1a", prompt="2025 midsem Q1a", now=NOW,
                              trust="source", topic_id=1, path=pdf.with_suffix(".pdf"), locator="p2", paper_id=paper)
        with mock.patch("pm.variants.excerpt", return_value="Q1a (4 marks) Seek time for 98, 183"), \
                mock.patch("pm.variants.kind_of", return_value="pdf"):
            ask = Asker("[]")
            self.assertEqual(variants.make(self.c, q, NOW, ask), (0, 0))
        self.assertIn('The question labelled "Q1a" on this page:', ask.prompts[0])
        self.assertIn("Seek time for 98, 183", ask.prompts[0])
        self.assertIn("(no answer on record)", ask.prompts[0])
        with mock.patch("pm.variants.excerpt", side_effect=OSError("gone")), \
                mock.patch("pm.variants.kind_of", return_value="pdf"), \
                self.assertRaisesRegex(ValueError, "^that question has no text for a model to read$"):
            variants.make(self.c, q, NOW, Asker())

    def test_only_originals(self):
        variants.make(self.c, self.parent, NOW, good())
        child = self.variants()[0].id
        with self.assertRaisesRegex(ValueError, "^make variants from an original question$"):
            variants.make(self.c, child, NOW, Asker())
        bank.retire(self.c, self.parent)
        with self.assertRaisesRegex(ValueError, "^make variants from an original question$"):
            variants.make(self.c, self.parent, NOW, Asker())

    def test_braces_in_the_question(self):
        q = bank.add_question(self.c, origin="manual", ref="m2", prompt="Find $\\frac{a}{b}$ for {n}", now=NOW,
                              trust="source", topic_id=1, answer="a/b")
        ask = Asker("[]")
        variants.make(self.c, q, NOW, ask)
        self.assertIn("Find $\\frac{a}{b}$ for {n}", ask.prompts[0])


class TestBudget(VariantCase):
    def test_out_of_budget_keeps_what_was_stored(self):
        put_setting(self.c, "agent_daily_calls", "2")
        call = agent.counted(self.c, NOW, good())
        with self.assertRaises(agent.OutOfBudget):
            variants.make(self.c, self.parent, NOW, call)
        self.assertEqual(len(self.variants()), 1)

    def test_job(self):
        put_setting(self.c, "agent_daily_calls", "10")
        agent.enqueue(self.c, "variants", "1", NOW)
        self.assertEqual(agent.run(self.c, NOW, good()), ["variants #1: 3 added, 0 dropped"])
        agent.enqueue(self.c, "variants", "abc", NOW)
        agent.enqueue(self.c, "variants", "99", NOW)
        lines = agent.run(self.c, NOW, good())
        self.assertTrue(lines[0].startswith("variants #2: failed:"))
        self.assertEqual(lines[1], "variants #3: failed: no question #99")


if __name__ == "__main__":
    unittest.main()
