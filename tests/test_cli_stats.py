import json
import os
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request

from pm.db import connect, default_path, set_setting
from tests.helpers import CliCase


class TestCliStats(CliCase):
    def netrc(self, text):
        path = Path(self.d.name) / "netrc"
        path.write_text(text)
        os.chmod(path, 0o600)
        os.environ["PM_NETRC"] = str(path)

    def test_stats_prints_json(self):
        code, out = self.pm("stats")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["today"], {"cap_min": 240, "worked_min": 0, "plan": []})

    def test_push_without_url_refuses(self):
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: set notes_url first:"
                                          " pm set notes_url https://your-site.pages.dev\n"))
        urlopen.assert_not_called()

    def test_push_rejects_http(self):
        self.assertEqual(self.pm("set", "notes_url", "http://x.dev"),
                         (1, "error: notes_url must be empty or https://your-site\n"))
        conn = connect(default_path())
        set_setting(conn, "notes_url", "http://x.dev")
        conn.close()
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: notes_url must start with https://\n"))
        urlopen.assert_not_called()

    def test_push_needs_netrc_entry(self):
        self.pm("set", "notes_url", "https://x.dev")
        self.netrc("machine other.dev login u password p\n")
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: add 'machine x.dev login USER password PASS'"
                                          " to ~/.netrc (chmod 600)\n"))
        urlopen.assert_not_called()

    def test_push_needs_netrc_file(self):
        self.pm("set", "notes_url", "https://x.dev")
        os.environ["PM_NETRC"] = str(Path(self.d.name) / "missing")
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: add 'machine x.dev login USER password PASS'"
                                          " to ~/.netrc (chmod 600)\n"))
        urlopen.assert_not_called()

    def test_push_puts_summary(self):
        self.pm("set", "notes_url", "https://x.dev")
        self.netrc("machine x.dev login u password p\n")
        with mock.patch("pm.stats.urlopen") as urlopen:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (0, "pushed 1 KB to x.dev\n"))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.full_url, "https://x.dev/api/pm")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertEqual(headers["authorization"], "Basic dTpw")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["user-agent"], "pm/0.1")
        self.assertEqual(json.loads(request.data)["version"], 1)

    def test_push_reports_http_error(self):
        self.pm("set", "notes_url", "https://x.dev")
        self.netrc("machine x.dev login u password p\n")
        error = HTTPError("https://x.dev/api/pm", 401, "Unauthorized", None, None)
        with mock.patch("pm.stats.urlopen", side_effect=error):
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: push failed: HTTP 401 (check ~/.netrc)\n"))
        error.close()

    def test_push_reports_network_error(self):
        self.pm("set", "notes_url", "https://x.dev")
        self.netrc("machine x.dev login u password p\n")
        with mock.patch("pm.stats.urlopen", side_effect=URLError("no route")):
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (1, "error: push failed: no route\n"))

    def test_push_refuses_redirects(self):
        from pm.stats import _NoRedirect

        handler = _NoRedirect()
        request = Request("https://x.dev/api/pm")
        for target in ("http://x.dev/api/pm", "https://evil.dev/api/pm"):
            with self.subTest(target=target), self.assertRaises(URLError):
                handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_push_installs_no_redirect_handler(self):
        self.pm("set", "notes_url", "https://x.dev")
        self.netrc("machine x.dev login u password p\n")
        opener = mock.MagicMock()
        with mock.patch("pm.stats.build_opener", return_value=opener) as build_opener:
            code, out = self.pm("stats", "--push")
        self.assertEqual((code, out), (0, "pushed 1 KB to x.dev\n"))
        handlers = build_opener.call_args.args
        self.assertTrue(any(issubclass(h, HTTPRedirectHandler) and h is not HTTPRedirectHandler
                            for h in handlers))
