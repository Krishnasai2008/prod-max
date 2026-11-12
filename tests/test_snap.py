import shutil
import tempfile
import unittest
from pathlib import Path

from pm.snap import diff, snapshot
from tests.helpers import git, make_repo


@unittest.skipUnless(shutil.which("git"), "needs git")
class TestSnap(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)

    def test_outside_repo_is_none(self):
        self.assertIsNone(snapshot(Path(self.d.name)))

    def test_same_tree_same_id_and_diff_shows_change(self):
        repo = make_repo(Path(self.d.name))
        a = snapshot(repo)
        self.assertEqual(snapshot(repo), a)
        (repo / "a.c").write_text("for (i = 0; i < n; i++)\n")
        b = snapshot(repo)
        self.assertNotEqual(a, b)
        out = diff(repo, a, b)
        self.assertIn("-for (i = 0; i <= n; i++)", out)
        self.assertIn("+for (i = 0; i < n; i++)", out)

    def test_new_untracked_file_is_in_the_diff(self):
        repo = make_repo(Path(self.d.name))
        a = snapshot(repo)
        (repo / "fix.h").write_text("#define N 10\n")
        self.assertIn("+#define N 10", diff(repo, a, snapshot(repo)))

    def test_real_index_untouched(self):
        repo = make_repo(Path(self.d.name))
        (repo / "a.c").write_text("staged\n")
        git(repo, "add", "a.c")
        (repo / "a.c").write_text("unstaged\n")
        (repo / "new.txt").write_text("x\n")
        before = git(repo, "status", "--porcelain"), git(repo, "diff", "--cached")
        snapshot(repo)
        self.assertEqual((git(repo, "status", "--porcelain"), git(repo, "diff", "--cached")), before)

    def test_from_a_subdirectory(self):
        repo = make_repo(Path(self.d.name))
        (repo / "sub").mkdir()
        self.assertEqual(snapshot(repo / "sub"), snapshot(repo))
