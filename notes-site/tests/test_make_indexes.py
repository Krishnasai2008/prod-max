"""make_indexes.py runs at import time and rewrites docs/ indexes, so it is only ever run inside a temp dir."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "make_indexes.py"


class TestPages(unittest.TestCase):
    def test_stats_page_is_not_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp, "docs")
            (docs / "poe").mkdir(parents=True)
            (docs / "stats.md").write_text("# Stats\n")
            (docs / "poe" / "a.md").write_text("# A\n")
            (docs / "poe" / "stats.md").write_text("# Poe stats\n")
            subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp, check=True, capture_output=True)
            home = (docs / "index.md").read_text()
            self.assertNotIn("stats.md", home)
            self.assertIn("2 notes", home)
            self.assertIn("stats.md", (docs / "poe" / "index.md").read_text())


    def test_planner_slot_is_on_the_home_page_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp, "docs")
            (docs / "poe").mkdir(parents=True)
            (docs / "poe" / "a.md").write_text("# A\n")
            subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp, check=True, capture_output=True)
            home = (docs / "index.md").read_text()
            self.assertIn('<div class="study-today"></div>\n\n<div class="study-plan"></div>\n', home)
            self.assertNotIn("study-plan", (docs / "poe" / "index.md").read_text())


if __name__ == "__main__":
    unittest.main()
