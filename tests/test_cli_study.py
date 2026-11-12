import os
import unittest
from pathlib import Path

from tests.helpers import CliCase

NOTES = """# Paging
intro line

## TLB
a
b
c

## Example
one
two
three

```
# not a heading
```

## Example
four
five
six

## Short
x
"""


class TestStudyCli(CliCase):
    def notes(self, text="# BFS\nqueue based\n"):
        p = Path(self.d.name) / "algo.md"; p.write_text(text); return p

    def test_empty_reads(self):
        for args, msg in [(("topic", "ls"), "no topics"), (("study", "next"), "no topics with an upcoming exam"),
                          (("study", "calib"), "no reviews yet"), (("review",), "nothing due")]:
            self.assertEqual(self.pm(*args), (0, msg + "\n"))

    def test_flow(self):
        n = self.notes()
        self.assertEqual(self.pm("topic", "add", "Graphs", "--course", "algo"), (0, "topic #1 Graphs\n"))
        self.assertEqual(self.pm("topic", "add", "BFS", "--course", "algo", "--exam", "+5", "--needs", "Graphs")[0], 0)
        self.assertEqual(self.pm("study", "add", f"{n}#BFS", "--topic", "BFS"), (0, "item #1 added to BFS, due now\n"))
        self.assertIn("needs Graphs", self.pm("topic", "ls")[1])
        out = self.pm("study", "next")[1]
        self.assertIn("study next: algo/Graphs  mastery 0%  (prerequisite of BFS)", out)
        code, out = self.pm("review", stdin="70\n3\n")
        for s in ("[1/1] algo/BFS: recall: algo.md#BFS", "queue based", "next review 2026-11-09 10:10", "reviewed 1"):
            self.assertIn(s, out)
        self.assertEqual(self.pm("review"), (0, "nothing due\n"))
        self.assertIn("reviews 1  Brier 0.090", self.pm("study", "calib")[1])

    def test_add_all_picks_sections_and_reports_duplicates(self):
        p = Path(self.d.name) / "notes.md"
        p.write_text(NOTES)
        self.pm("topic", "add", "paging")
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging"),
                         (0, "added 3 items to paging\n"))
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging"),
                         (0, "nothing to add\n"))
        p.write_text(NOTES + "\n## Extra\nx\ny\nz\n")
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging"),
                         (0, "added 1 item to paging (3 already there)\n"))

    def test_add_all_singular_and_empty_picks(self):
        p = Path(self.d.name) / "one.md"
        p.write_text("# One\na\nb\nc\n")
        self.pm("topic", "add", "paging")
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging"),
                         (0, "added 1 item to paging\n"))
        short = Path(self.d.name) / "short.md"
        short.write_text("# Short\nx\n")
        self.assertEqual(self.pm("study", "add", str(short), "--all", "--topic", "paging"),
                         (0, "nothing to add\n"))

    def test_add_all_rejects_a_locator_and_a_prompt(self):
        p = self.notes()
        self.pm("topic", "add", "paging")
        self.assertEqual(self.pm("study", "add", f"{p}#BFS", "--all", "--topic", "paging"),
                         (1, "error: --all takes a file, not file#part\n"))
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging",
                                 "--prompt", "what"),
                         (1, "error: --prompt needs a single item\n"))
        self.assertEqual(self.pm("study", "add", str(p), "--all", "--topic", "paging",
                                 "--prompt", ""),
                         (1, "error: --prompt needs a single item\n"))

    def test_add_all_missing_file_is_an_error_not_a_traceback(self):
        gone = Path(self.d.name) / "gone.md"
        self.pm("topic", "add", "paging")
        self.assertEqual(self.pm("study", "add", str(gone), "--all", "--topic", "paging"),
                         (1, f"error: no such file: {gone}\n"))

    def test_add_bad_heading(self):
        n = self.notes(); self.pm("topic", "add", "BFS")
        self.assertEqual(self.pm("study", "add", f"{n}#DFS", "--topic", "BFS"), (1, "error: no heading 'DFS' in algo.md\n"))

    def test_bad_confidence_then_eof(self):
        n = self.notes(); self.pm("topic", "add", "BFS"); self.pm("study", "add", f"{n}#BFS", "--topic", "BFS")
        code, out = self.pm("review", stdin="abc\n150\n70%\n")
        self.assertEqual(out.count("confidence 0-100"), 3)
        self.assertIn("queue based", out)
        self.assertEqual((code, out.splitlines()[-1]), (0, "reviewed 0"))

    def test_missing_file_still_gradeable(self):
        n = self.notes(); self.pm("topic", "add", "BFS"); self.pm("study", "add", f"{n}#BFS", "--topic", "BFS")
        n.unlink()
        code, out = self.pm("review", stdin="50\n1\n")
        self.assertIn("can't show excerpt:", out); self.assertIn("reviewed 1", out)

    def test_directory_is_an_error_not_a_traceback(self):
        folder = Path(self.d.name) / "notes"; folder.mkdir()
        self.pm("topic", "add", "BFS")
        code, out = self.pm("study", "add", str(folder), "--topic", "BFS")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("error: "))
        self.assertNotIn("Traceback", out)

    def test_unexpandable_home_is_an_error_not_a_traceback(self):
        code, out = self.pm("study", "add", "~nosuchuser_x/a.md", "--topic", "T")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("error: "))
        self.assertNotIn("Traceback", out)

    def test_nan_weight_rejected(self):
        self.assertEqual(self.pm("topic", "add", "x", "--weight", "nan"),
                         (1, "error: weight must be a positive finite number\n"))

    def test_negative_limit_rejected(self):
        with self.assertRaises(SystemExit):
            self.pm("review", "--limit", "-1")

    def test_review_caps_new_items_and_says_how_many_wait(self):
        notes = self.notes(); self.pm("topic", "add", "BFS")
        for _ in range(12):
            self.assertEqual(self.pm("study", "add", f"{notes}#BFS", "--topic", "BFS", "--prompt", f"q{_}")[0], 0)
        code, out = self.pm("review", "--limit", "20", stdin="50\n3\n" * 10)
        self.assertEqual((code, out.splitlines()[-2:]),
                         (0, ["reviewed 10",
                              "2 new items wait for another day (pm set new_per_day)"]))

    def test_review_stopped_early_does_not_claim_items_wait(self):
        notes = self.notes(); self.pm("topic", "add", "BFS")
        for _ in range(12):
            self.assertEqual(self.pm("study", "add", f"{notes}#BFS", "--topic", "BFS", "--prompt", f"q{_}")[0], 0)
        code, out = self.pm("review", "--limit", "2", stdin="50\n3\n" * 2)
        self.assertEqual((code, out.splitlines()[-1]), (0, "reviewed 2"))
        self.assertNotIn("wait for another day", out)

    def test_review_says_one_item_waits(self):
        notes = self.notes(); self.pm("topic", "add", "BFS")
        for _ in range(11):
            self.assertEqual(self.pm("study", "add", f"{notes}#BFS", "--topic", "BFS", "--prompt", f"q{_}")[0], 0)
        code, out = self.pm("review", stdin="50\n3\n" * 10)
        self.assertEqual((code, out.splitlines()[-1]),
                         (0, "1 new item waits for another day (pm set new_per_day)"))

    def test_new_per_day_must_be_between_1_and_200(self):
        for value in ("0", "201", "x"):
            self.assertEqual(self.pm("set", "new_per_day", value),
                             (1, "error: new_per_day must be between 1 and 200\n"))


class TestStudyEvidenceCli(CliCase):
    def setUp(self):
        super().setUp()
        self.five = Path(self.d.name) / "five.md"
        self.five.write_text("".join(f"# S{k}\na\nb\nc\n\n" for k in range(1, 6)))
        self.pm("topic", "add", "paging", "--course", "os")

    def test_topic_file(self):
        code, out = self.pm("topic", "file", "paging", str(self.five))
        self.assertEqual((code, out), (0, f"tracking {self.five} for paging (5 sections)\n"))
        self.assertEqual(self.pm("topic", "file", "paging", str(self.five), "--rm"),
                         (0, f"stopped tracking {self.five} for paging\n"))
        self.assertEqual(self.pm("topic", "file", "paging", str(self.five), "--rm")[0], 1)
        code, out = self.pm("topic", "file", "paging", str(Path(self.d.name) / "no.md"))
        self.assertEqual(code, 1)
        self.assertIn("error: no such file:", out)

    def test_why(self):
        for s in ("S1", "S2"):
            self.pm("study", "add", f"{self.five}#{s}", "--topic", "paging")
        code, out = self.pm("study", "why", "paging")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 5)
        self.assertRegex(lines[0], r"^os/paging  mastery \d+%$")
        self.assertEqual(lines[1], "  coverage 40% (2 of 5 sections)")
        self.assertRegex(lines[2], r"^  memory \d+% \(2 items\)$")
        self.assertEqual(lines[3:], ["  understanding - (no checks yet)", "  application - (no practice yet)"])

    def test_why_without_files(self):
        self.pm("topic", "add", "empty")
        self.assertEqual(self.pm("study", "why", "empty"),
                         (0, "-/empty  mastery 0%\n  coverage - (no files tracked)\n  memory - (no items yet)\n"
                             "  understanding - (no checks yet)\n  application - (no practice yet)\n"))

    def test_misses(self):
        self.assertEqual(self.pm("study", "misses"), (0, "no confident mistakes\n"))
        self.pm("study", "add", f"{self.five}#S1", "--topic", "paging")
        self.pm("review", stdin="90\n1\n")
        out = self.pm("study", "misses")[1]
        self.assertEqual(out, "2026-11-09  os/paging  said 90%  review  five.md#S1\n")

    def test_ready(self):
        self.assertEqual(self.pm("study", "ready"), (0, "no topics with an upcoming exam\n"))
        self.pm("topic", "add", "tlb", "--course", "os", "--exam", "+5")
        self.assertEqual(self.pm("study", "ready"), (0, "os  0%  next exam 2026-11-14  (1 topic)\n"))


class TestSuggestCli(CliCase):
    def test_suggest(self):
        from pm.db import connect
        self.assertEqual(self.pm("suggest"), (0, "no suggestions\n"))
        self.pm("topic", "add", "paging", "--course", "os")
        conn = connect(os.environ["PM_DB"])
        conn.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('chat_a', 'TLB', 'teach', 0, 0)")
        conn.execute("INSERT INTO suggestions(kind, subject, value, created) VALUES('topic', 'chat_a', '1', '2026-11-09')")
        conn.commit()
        conn.close()
        self.assertEqual(self.pm("suggest"), (0, '#1  put session "TLB" under os/paging\n'))
        self.assertEqual(self.pm("suggest", "accept", "1"), (0, 'done: put session "TLB" under os/paging\n'))
        self.assertEqual(self.pm("suggest", "reject", "9")[0], 1)
        self.assertEqual(self.pm("suggest", "accept")[0], 1)
