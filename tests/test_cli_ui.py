import os
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import CliCase


def _ping(body=b'{"pm": true}'):
    urlopen = mock.MagicMock()
    urlopen.return_value.__enter__.return_value.read.return_value = body
    return urlopen


class TestCliUi(CliCase):
    def test_ui_serves_and_opens_the_default_address(self):
        with mock.patch("pm.cli.serve", return_value=0) as serve, \
                mock.patch("pm.cli.webbrowser.open") as opened:
            code, out = self.pm("ui")
        self.assertEqual((code, out), (0, "pm ui on http://127.0.0.1:8321\n"))
        self.assertEqual(serve.call_args.args[1], 8321)
        opened.assert_called_once_with("http://127.0.0.1:8321")

    def test_no_open_and_a_custom_port(self):
        with mock.patch("pm.cli.serve", return_value=0) as serve, \
                mock.patch("pm.cli.webbrowser.open") as opened:
            code, out = self.pm("ui", "--no-open", "--port", "9000")
        self.assertEqual((code, out), (0, "pm ui on http://127.0.0.1:9000\n"))
        self.assertEqual(serve.call_args.args[1], 9000)
        opened.assert_not_called()

    def test_a_port_outside_the_range_is_rejected_by_argparse(self):
        for port in ("80", "70000", "abc"):
            with self.subTest(port=port), self.assertRaises(SystemExit) as caught:
                self.pm("ui", "--port", port)
            self.assertEqual(caught.exception.code, 2)

    def test_already_running_opens_the_page_and_exits_zero(self):
        probe = _ping()
        with mock.patch("pm.cli.serve", side_effect=OSError), \
                mock.patch("pm.cli.urlopen", probe), \
                mock.patch("pm.cli.webbrowser.open") as opened:
            code, out = self.pm("ui")
        self.assertEqual(code, 0)
        self.assertEqual(out, "pm ui on http://127.0.0.1:8321\n"
                              "pm ui is already running: http://127.0.0.1:8321\n")
        probe.assert_called_once_with("http://127.0.0.1:8321/api/ping", timeout=2)
        opened.assert_called_once_with("http://127.0.0.1:8321")

    def test_already_running_uses_the_custom_port_everywhere(self):
        probe = _ping()
        with mock.patch("pm.cli.serve", side_effect=OSError), \
                mock.patch("pm.cli.urlopen", probe), \
                mock.patch("pm.cli.webbrowser.open") as opened:
            code, out = self.pm("ui", "--port", "9000")
        self.assertEqual(code, 0)
        self.assertIn("pm ui is already running: http://127.0.0.1:9000\n", out)
        probe.assert_called_once_with("http://127.0.0.1:9000/api/ping", timeout=2)
        opened.assert_called_once_with("http://127.0.0.1:9000")

    def test_a_taken_port_that_is_not_pm_is_an_error(self):
        for probe in (_ping(b'{"other": true}'), mock.MagicMock(side_effect=OSError)):
            with self.subTest(probe=probe):
                with mock.patch("pm.cli.serve", side_effect=OSError), \
                        mock.patch("pm.cli.urlopen", probe), \
                        mock.patch("pm.cli.webbrowser.open"):
                    code, out = self.pm("ui")
                self.assertEqual(code, 1)
                self.assertTrue(out.endswith(
                    "error: port 8321 is in use; try pm ui --port 8322\n"))

    def test_install_writes_the_ui_unit(self):
        config = Path(self.d.name) / "config"
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}), \
                mock.patch("pm.cli.shutil.which", return_value="/usr/bin/pm"):
            code, out = self.pm("ui", "--install")
        self.assertEqual(code, 0)
        text = (config / "systemd/user/pm-ui.service").read_text()
        self.assertIn("Description=pm ui: the local planner page", text)
        self.assertIn("ExecStart=/usr/bin/pm ui --no-open", text)
        self.assertTrue(out.endswith(
            "start it: systemctl --user daemon-reload && systemctl --user enable --now pm-ui\n"))


if __name__ == "__main__":
    unittest.main()
