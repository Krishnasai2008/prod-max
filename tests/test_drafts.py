import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from pm import bank, drafts, generators, templates
from pm.db import connect
from pm.excerpt import Section
from pm.study import add_topic

NOW = datetime(2026, 11, 9, 10, 0)
EXAMPLE = drafts.EXAMPLE + "\n"


class Asker:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


class DraftCase(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.c = connect(str(self.dir / "pm.db"))
        self.addCleanup(self.c.close)
        for name in ("paging", "disk"):
            add_topic(self.c, name, course="os")
        add_topic(self.c, "joins", course="db")
        self.addCleanup(self.forget)

    def forget(self):
        for gen_id in [g for g in generators.ids() if g.startswith("t:")]:
            generators.unregister(gen_id)
        templates._loaded.update(key=None, ids=[], errors=[])


class TestOutline(DraftCase):
    def setUp(self):
        super().setUp()
        self.pdf = self.dir / "midsem.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\n")
        self.paper = bank.add_paper(self.c, "os", "2025 midsem", NOW, path=self.pdf)

    def patched(self, pages):
        sections = [Section(f"p{k}", f"page {k}", 1, 0, True, True) for k in range(1, len(pages) + 1)]

        def page(path, locator, lines):
            text = pages[int(locator[1:]) - 1]
            if text is None:
                raise ValueError("unreadable")
            return text
        return (mock.patch("pm.drafts.outline", return_value=sections), mock.patch("pm.drafts.excerpt", side_effect=page),
                mock.patch("pm.bank.outline", return_value=sections))

    def run_outline(self, pages, reply):
        a, b, c = self.patched(pages)
        ask = Asker(reply)
        with a, b, c:
            return drafts.paper_outline(self.c, self.paper, ask), ask

    def test_outline(self):
        reply = "Q1a | 5 | paging | p1\nQ1b | 3 | paging | p2\nQ2 | 4 | disk | p3\nQ3 | 2 | nonsense | p3\n"
        text, ask = self.run_outline(["one", "two", "three"], reply)
        lines = text.splitlines()
        self.assertEqual(lines[:2], ["# label | marks | topic | where | answer",
                                     "# drafted by a model: check every line against the paper"])
        self.assertEqual(lines[2:5], ["Q1a | 5 | paging | p1", "Q1b | 3 | paging | p2", "Q2 | 4 | disk | p3"])
        self.assertTrue(lines[5].startswith("# ? Q3 | 2 | nonsense | p3"))
        self.assertIn("no topic 'nonsense' in os", lines[5])
        self.assertIn("--- page 2 ---\ntwo", ask.prompts[0])
        self.assertIn("paging\ndisk", ask.prompts[0])
        self.assertNotIn("joins", ask.prompts[0])
        with mock.patch("pm.bank.outline", return_value=[Section(f"p{k}", "", 1, 0, True, True) for k in (1, 2, 3)]):
            self.assertEqual(bank.import_paper(self.c, self.paper, lines, NOW), (3, 0, []))

    def test_fenced_and_long(self):
        text, ask = self.run_outline(["x" * 100_000], "```\nQ1 | 2 | paging | p1\n```")
        self.assertIn("\nQ1 | 2 | paging | p1\n", text)
        self.assertLess(len(ask.prompts[0]), 61_000)

    def test_errors(self):
        bare = bank.add_paper(self.c, "os", "quiz", NOW)
        with self.assertRaisesRegex(ValueError, "^that paper has no PDF to read$"):
            drafts.paper_outline(self.c, bare, Asker())
        a, b, c = self.patched([None, ""])
        with a, b, c, self.assertRaisesRegex(ValueError, r"is it a scan\?"):
            drafts.paper_outline(self.c, self.paper, Asker())


class TestTemplate(DraftCase):
    def setUp(self):
        super().setUp()
        self.q = bank.add_question(self.c, origin="manual", ref="m1", now=NOW, trust="source", topic_id=1,
                                   prompt="Jobs arrive at 8 per hour and one server finishes 12 per hour. Mean time "
                                          "in the system, in minutes?", kind="number", expected={"value": 15, "tol": 0})

    def test_valid(self):
        ask = Asker(f"```toml\n{EXAMPLE}```")
        text = drafts.template(self.c, self.q, ask)
        self.assertEqual(templates.parse(text).id, "mm1-wait")
        self.assertIn("its known answer, 15.", ask.prompts[0])
        self.assertIn("Jobs arrive at 8 per hour", ask.prompts[0])

    def test_retry_then_give_up(self):
        wrong = EXAMPLE.replace("answer = 15", "answer = 16")
        ask = Asker(wrong, EXAMPLE)
        self.assertEqual(templates.parse(drafts.template(self.c, self.q, ask)).id, "mm1-wait")
        self.assertIn("Your last attempt was rejected: the template doesn't reproduce its original answer",
                      ask.prompts[1])
        self.assertTrue(ask.prompts[1].endswith(". Fix it."))
        ask = Asker(wrong, wrong)
        with self.assertRaisesRegex(ValueError, "^the model didn't produce a valid template: "):
            drafts.template(self.c, self.q, ask)
        self.assertEqual(len(ask.prompts), 2)

    def test_needs_a_number(self):
        q = bank.add_question(self.c, origin="manual", ref="m2", prompt="Why?", now=NOW, trust="source", answer="x")
        with self.assertRaisesRegex(ValueError, "numeric answer"):
            drafts.template(self.c, q, Asker())

    def test_save_and_approve(self):
        path = drafts.save_template(self.c, EXAMPLE)
        self.assertEqual(path, self.dir / "templates" / "drafts" / "mm1-wait.toml")
        second = drafts.save_template(self.c, EXAMPLE)
        self.assertEqual(second.name, "mm1-wait-2.toml")
        self.assertEqual(templates.parse(second.read_text()).id, "mm1-wait-2")
        self.assertEqual(templates.sync(self.c), [])
        self.assertNotIn("t:mm1-wait", generators.ids())
        self.assertEqual(drafts.approve_template(self.c, "mm1-wait"), self.dir / "templates" / "mm1-wait.toml")
        self.assertFalse(path.exists())
        templates.sync(self.c)
        self.assertIn("t:mm1-wait", generators.ids())
        with self.assertRaises(LookupError):
            drafts.approve_template(self.c, "nope")
        with self.assertRaises(LookupError):
            drafts.approve_template(self.c, "../mm1-wait")
        second.write_text(second.read_text().replace("answer = 15", "answer = 99"))
        with self.assertRaisesRegex(ValueError, "doesn't reproduce"):
            drafts.approve_template(self.c, "mm1-wait-2")
        self.assertTrue(second.exists())

    def test_a_loaded_id_is_renamed(self):
        (self.dir / "templates").mkdir()
        (self.dir / "templates" / "mm1-wait.toml").write_text(EXAMPLE)
        templates.sync(self.c)
        self.assertEqual(drafts.save_template(self.c, EXAMPLE).name, "mm1-wait-2.toml")


if __name__ == "__main__":
    unittest.main()
