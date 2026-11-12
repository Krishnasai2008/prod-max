import json
import os
import plistlib
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from pm.db import connect
from pm.stats import notes_minutes
from tests.helpers import CliCase

OLD = 1700000000


class TestCliWatch(CliCase):
    def setUp(self):
        super().setUp()
        self.home = Path(self.d.name) / "home"
        self.config = Path(self.d.name) / "config"
        (self.home / "Downloads").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                "XDG_CONFIG_HOME": str(self.config)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_find_prints_a_snippet_on_one_line(self):
        root = Path(self.d.name) / "files"
        root.mkdir()
        notes = root / "notes.txt"
        notes.write_text("# OS lab\nthe TLB caches\npages")
        os.utime(notes, (OLD, OLD))
        self.pm("set", "watch", str(root))
        self.pm("watch", "--once")
        code, out = self.pm("find", "tlb")
        self.assertEqual(out.splitlines()[1], "    # OS lab the [TLB] caches pages")

    def test_once_indexes_then_find_searches(self):
        root = Path(self.d.name) / "files"
        root.mkdir()
        notes = root / "notes.txt"
        notes.write_text("the TLB caches pages")
        os.utime(notes, (OLD, OLD))
        self.assertEqual(self.pm("set", "watch", str(root))[0], 0)
        code, out = self.pm("watch", "--once")
        self.assertEqual(code, 0)
        self.assertIn("indexed 1, updated 0, removed 0", out)
        code, out = self.pm("find", "tlb")
        self.assertEqual(code, 0)
        self.assertIn("notes.txt", out)
        self.assertIn("[TLB]", out)
        self.assertEqual(self.pm("find", "nothinghere"), (0, "no matches\n"))

    def test_install_writes_the_unit(self):
        with mock.patch("pm.cli.shutil.which", return_value="/x/pm"):
            code, out = self.pm("watch", "--install")
        self.assertEqual(code, 0)
        unit = self.config / "systemd/user/pm-watch.service"
        self.assertTrue(unit.exists())
        self.assertIn("ExecStart=/x/pm watch", unit.read_text())
        self.assertIn("wrote", out)
        self.assertIn("start it: systemctl --user daemon-reload &&"
                      " systemctl --user enable --now pm-watch", out)

    def test_install_on_a_mac_writes_a_launch_agent(self):
        with mock.patch("pm.cli.shutil.which", return_value="/x/pm"), \
                mock.patch("pm.cli.sys.platform", "darwin"), \
                mock.patch("pm.cli.Path.home", return_value=self.home):
            code, out = self.pm("watch", "--install")
        self.assertEqual(code, 0)
        path = self.home / "Library/LaunchAgents/dev.prod-max.pm-watch.plist"
        with path.open("rb") as f:
            agent = plistlib.load(f)
        self.assertEqual(agent["ProgramArguments"], ["/x/pm", "watch"])
        self.assertEqual(agent["Label"], "dev.prod-max.pm-watch")
        self.assertTrue(agent["RunAtLoad"] and agent["KeepAlive"])
        self.assertTrue(out.endswith(f"start it: launchctl load -w {path}\n"))
        self.assertFalse((self.config / "systemd").exists())

    def test_install_needs_pm_on_path(self):
        with mock.patch("pm.cli.shutil.which", return_value=None):
            self.assertEqual(self.pm("watch", "--install"),
                             (1, "error: install pm first: uv tool install --editable .\n"))

    def netrc(self):
        path = Path(self.d.name) / "netrc"
        path.write_text("machine x.dev login u password p\n")
        os.chmod(path, 0o600)
        return path

    def fake_site(self, inbox=b"null", backup=b"null"):
        def fake(request, timeout=20):
            response = mock.MagicMock()
            path = urlsplit(request.full_url).path
            response.__enter__.return_value.read.return_value = {
                "/api/pm-inbox": inbox, "/api/backup": backup}.get(path, b"")
            return response
        return fake

    def test_once_pulls_the_site_study_clock(self):
        netrc = self.netrc()
        body = json.dumps({"study.time": json.dumps(
            {"2026-11-09": {"os": 5_400_000}})}).encode()
        with mock.patch.dict(os.environ, {"PM_NETRC": str(netrc)}):
            self.assertEqual(self.pm("set", "notes_url", "https://x.dev")[0], 0)
            with mock.patch("pm.stats.urlopen", side_effect=self.fake_site(backup=body)):
                code, out = self.pm("watch", "--once")
        self.assertEqual(code, 0)
        self.assertNotIn("pull failed", out)
        conn = connect(os.environ["PM_DB"])
        try:
            self.assertEqual(notes_minutes(conn), {"2026-11-09": 90})
        finally:
            conn.close()

    def test_inbox_applies_and_pushes(self):
        netrc = self.netrc()
        body = json.dumps({"items": [{"id": "a1", "op": "add",
                                      "title": "OS lab 3", "est": "1h"}]}).encode()
        with mock.patch.dict(os.environ, {"PM_NETRC": str(netrc)}):
            self.assertEqual(self.pm("set", "notes_url", "https://x.dev")[0], 0)
            with mock.patch("pm.stats.urlopen", side_effect=self.fake_site(inbox=body)):
                code, out = self.pm("inbox")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(),
                         ["inbox: added #1 OS lab 3", "pushed 1 KB"])

    def test_inbox_with_nothing_new_does_not_push(self):
        netrc = self.netrc()
        requests = []

        def fake(request, timeout=20):
            requests.append(request.get_method())
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = b"null"
            return response

        with mock.patch.dict(os.environ, {"PM_NETRC": str(netrc)}):
            self.assertEqual(self.pm("set", "notes_url", "https://x.dev")[0], 0)
            with mock.patch("pm.stats.urlopen", side_effect=fake):
                code, out = self.pm("inbox")
        self.assertEqual((code, out), (0, "inbox empty\n"))
        self.assertEqual(requests, ["GET"])

    def test_inbox_pushes_again_after_a_failed_push(self):
        netrc = self.netrc()
        body = json.dumps({"items": [{"id": "a1", "op": "add",
                                      "title": "OS lab 3", "est": "1h"}]}).encode()
        site = self.fake_site(inbox=body)

        def down(request, timeout=20):
            if request.get_method() == "PUT":
                raise OSError("network is down")
            return site(request, timeout)

        with mock.patch.dict(os.environ, {"PM_NETRC": str(netrc)}):
            self.assertEqual(self.pm("set", "notes_url", "https://x.dev")[0], 0)
            with mock.patch("pm.stats.urlopen", side_effect=down):
                self.assertEqual(self.pm("inbox")[0], 1)
            with mock.patch("pm.stats.urlopen", side_effect=site):
                self.assertEqual(self.pm("inbox"), (0, "pushed 1 KB\n"))
                self.assertEqual(self.pm("inbox"), (0, "inbox empty\n"))

    def test_inbox_needs_notes_url(self):
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("inbox")
        self.assertEqual((code, out), (1, "error: set notes_url first:"
                                          " pm set notes_url https://your-site.pages.dev\n"))
        urlopen.assert_not_called()
