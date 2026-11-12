import os
import random
from datetime import datetime
from pathlib import Path

from pm import generators
from pm.db import connect
from pm.practice import next_problem
from tests.helpers import CliCase
from tests.test_practice import answer_for
from tests.test_templates import EXAMPLE

NOW = "2026-11-09T10:00:00"


class TestPracticeCli(CliCase):
    def setUp(self):
        super().setUp()
        self.pm("topic", "add", "paging", "--course", "os")

    def tearDown(self):
        generators.unregister("t:mm1-wait")
        super().tearDown()

    def first_problem(self):
        conn = connect(os.environ["PM_DB"])
        try:
            now = datetime.fromisoformat(NOW)
            return next_problem(conn, now, random.Random(now.isoformat())).problem
        finally:
            conn.close()

    def test_link_and_gens(self):
        self.assertEqual(self.pm("practice", "link", "paging", "--topic", "paging"), (0, "linked paging to os/paging\n"))
        code, out = self.pm("practice", "link", "nope", "--topic", "paging")
        self.assertEqual((code, out), (1, "error: no generator 'nope'\n"))
        lines = self.pm("practice", "gens")[1].splitlines()
        line = next(x for x in lines if x.startswith("paging  Page replacement"))
        self.assertTrue(line.endswith("→ os/paging"), line)
        self.assertIn("cpu  CPU scheduling  avg_wait, order, which", lines)
        self.assertEqual(self.pm("practice", "unlink", "paging", "--topic", "paging"),
                         (0, "unlinked paging from os/paging\n"))
        self.assertEqual(self.pm("practice", "unlink", "paging", "--topic", "paging")[0], 1)

    def test_no_links(self):
        code, out = self.pm("practice", stdin="q\n")
        self.assertEqual(code, 1)
        self.assertIn("no generators are linked", out)

    def test_session(self):
        self.pm("practice", "link", "paging", "--topic", "paging")
        code, out = self.pm("practice", stdin="q\n")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("os/paging  Page replacement\nFrames: "), out)
        self.assertTrue(out.endswith("practised 0\n"))
        problem = self.first_problem()
        code, out = self.pm("practice", stdin=f"{answer_for(problem)}\n80\nq\n")
        self.assertIn("(q quits): right\n", out)
        self.assertTrue(out.endswith("practised 1, 1 right\n"), out)

    def test_blank_answer(self):
        self.pm("practice", "link", "paging", "--topic", "paging")
        problem = self.first_problem()
        code, out = self.pm("practice", "paging", stdin="\nq\n")
        self.assertIn("the answer is ", out)
        self.assertIn(problem.steps, out)
        self.assertTrue(out.endswith("practised 1, 0 right\n"))

    def test_templates(self):
        code, out = self.pm("template", "dir")
        folder = Path(out.strip())
        self.assertEqual(folder, Path(self.d.name) / "templates")
        self.assertTrue(folder.is_dir())
        self.assertEqual(self.pm("template", "ls"), (0, f"no templates in {folder}\n"))
        (folder / "mm1.toml").write_text(EXAMPLE)
        self.assertEqual(self.pm("template", "ls"), (0, "t:mm1-wait  M/M/1 time in system  v1\n"))
        code, out = self.pm("template", "check", str(folder / "mm1.toml"))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("ok: mm1-wait "), out)
        broken = Path(self.d.name) / "broken.toml"
        broken.write_text(EXAMPLE.replace("answer = 15", "answer = 16"))
        code, out = self.pm("template", "check", str(broken))
        self.assertEqual(code, 1)
        self.assertIn("doesn't reproduce", out)


class TestTemplateDraftCli(CliCase):
    def tearDown(self):
        from pm import templates
        for gen_id in [g for g in generators.ids() if g.startswith("t:")]:
            generators.unregister(gen_id)
        templates._loaded.update(key=None, ids=[], errors=[])
        super().tearDown()

    def test_draft_and_approve(self):
        from unittest import mock
        from pm.drafts import EXAMPLE as DRAFT
        self.pm("topic", "add", "queues", "--course", "os")
        self.pm("q", "add", "Jobs arrive at 8 per hour; the server finishes 12. Minutes in the system?",
                "--topic", "queues", "--number", "15")
        with mock.patch("pm.cli.llm_ask", return_value=DRAFT):
            code, out = self.pm("template", "draft", "1")
        self.assertEqual(code, 0, out)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("drafted t:mm1-wait in "))
        self.assertTrue(lines[0].endswith("templates/drafts/mm1-wait.toml"))
        self.assertEqual(lines[1], "read it, then: pm template approve mm1-wait")
        self.assertEqual(self.pm("template", "approve", "mm1-wait"), (0, "approved t:mm1-wait\n"))
        self.assertIn("t:mm1-wait  M/M/1 time in system  v1", self.pm("template", "ls")[1])
        self.assertEqual(self.pm("template", "approve", "mm1-wait")[0], 1)
