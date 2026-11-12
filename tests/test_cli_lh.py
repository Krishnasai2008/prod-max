import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from tests.helpers import CliCase

FIXTURES = Path(__file__).parent / "lh"
OPENING_END = "Please check what I already know first, then teach what is missing."


class TestLhCli(CliCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.d.name) / "lh"
        (self.root / "chats").mkdir(parents=True)
        old = 1794225600 - 3600  # an hour before the fixtures start, so the files have settled
        for name in ("teach", "practice"):
            path = self.root / "chats" / f"chat_{name}.json"
            shutil.copy(FIXTURES / f"{name}.json", path)
            os.utime(path, (old, old))
        self.now = "2026-11-10T10:00:00"
        self.assertEqual(self.pm("set", "lh_dir", str(self.root))[0], 0)
        self.assertEqual(self.pm("topic", "add", "paging", "--course", "os")[0], 0)

    def test_sync_twice(self):
        self.assertEqual(self.pm("lh", "sync", now=self.now),
                         (0, "learnharness: 2 sessions, 6 answers, 3 outcomes, 9 questions, 0 cards\n"))
        self.assertEqual(self.pm("lh", "sync", now=self.now), (0, "learnharness: nothing new\n"))

    def test_ls_and_map(self):
        self.assertEqual(self.pm("lh", "ls"), (0, "no LearnHarness sessions (pm lh sync)\n"))
        self.pm("lh", "sync", now=self.now)
        code, out = self.pm("lh", "ls", now=self.now)
        self.assertEqual(code, 0)
        self.assertIn("chat_teach  teach  os/paging  4m  2026-11-09  TLB and paging", out)
        self.assertIn("chat_practice  practice  -  ", out)
        self.assertEqual(self.pm("lh", "map", "chat_practice", "paging"), (0, "mapped chat_practice to os/paging\n"))
        self.assertIn("chat_practice  practice  os/paging", self.pm("lh", "ls")[1])
        self.assertEqual(self.pm("lh", "map", "chat_practice", "--none"), (0, "unmapped chat_practice\n"))
        self.assertEqual(self.pm("lh", "map", "nope", "paging")[0], 1)
        self.assertEqual(self.pm("lh", "map", "chat_practice")[0], 1)

    def test_learn(self):
        code, out = self.pm("learn", "paging")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith('[pm:topic=1] I want to study "paging" (course: os).\n'))
        self.assertTrue(out.endswith(OPENING_END + "\n"))
        self.assertTrue(self.pm("learn", "paging", "--practice")[1].endswith(
            "Please give me exam-style practice problems on this topic.\n"))
        self.assertEqual(self.pm("learn", "nope")[0], 1)

    def test_copy(self):
        with mock.patch("pm.cli.shutil.which", return_value=None):
            code, out = self.pm("learn", "paging", "--copy")
        self.assertTrue(out.endswith(OPENING_END + "\nno clipboard tool found (wl-copy or xclip)\n"))
        with mock.patch("pm.cli.shutil.which", side_effect=lambda n: "/usr/bin/wl-copy" if n == "wl-copy" else None), \
                mock.patch("pm.cli.subprocess.run") as run:
            code, out = self.pm("learn", "paging", "--copy")
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith(OPENING_END + "\ncopied\n"))
        self.assertEqual(run.call_args.args[0], ["/usr/bin/wl-copy"])
        self.assertTrue(run.call_args.kwargs["input"].endswith(OPENING_END))

    def test_install(self):
        code, out = self.pm("lh", "install")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], f"installed the pm plugin in {self.root / 'plugins' / 'pm-bridge'}")
        self.assertEqual(lines[1:], ["enable it in LearnHarness: Settings → Community plugins → pm planner bridge,"
                                     " then restart LearnHarness", "it needs pm ui running: pm ui --install"])
        self.assertTrue(self.pm("lh", "install")[1].startswith("updated the pm plugin in"))

    def test_no_folder(self):
        self.pm("set", "lh_dir", "")
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": empty}):
            code, out = self.pm("lh", "sync")
        self.assertEqual(code, 1)
        self.assertIn("LearnHarness data not found", out)
