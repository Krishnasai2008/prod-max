import json
import os
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from tests.helpers import CliCase

NOW = "2026-11-13T10:00:00"


def card(generated="2026-11-13T09:00:00", **days):
    return {"version": 1, "generated": generated,
            "days": {"2026-11-" + k[1:]: v for k, v in days.items()}}


def day(min=0, reviews=0, quiz=0, test=0, **kw):
    return {"min": min, "reviews": reviews, "quiz": quiz, "test": test, **kw}


REPLY = {"you": "kel", "cards": {
    "kel": card(_11=day(min=90), _12=day(min=60, syllabus=40.0),
                _13=day(min=185, reviews=42, quiz=18, test=9, syllabus=42.1)),
    "sam": card(_11=day(min=30), _12=day(min=60, syllabus=50.0),
                _13=day(min=140, reviews=60, quiz=18, syllabus=49.6))}}


class TestCliVersus(CliCase):
    def setUp(self):
        super().setUp()
        path = Path(self.d.name) / "netrc"
        path.write_text("machine hub.dev login kel password p\n")
        os.chmod(path, 0o600)
        env = mock.patch.dict(os.environ, {"PM_NETRC": str(path)})
        env.start()
        self.addCleanup(env.stop)

    def site(self, reply):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(reply).encode()
        return mock.patch("pm.stats.urlopen", return_value=response)

    def test_off_until_the_address_is_set(self):
        with mock.patch("pm.stats.urlopen") as urlopen:
            self.assertEqual(self.pm("versus"), (0, "versus is off: pm set versus_url https://the-scoreboard-site\n"))
            self.assertEqual(self.pm("versus", "--sync")[0], 0)
        urlopen.assert_not_called()

    def test_the_address_is_checked_like_notes_url(self):
        self.assertEqual(self.pm("set", "versus_url", "http://hub.dev"),
                         (1, "error: versus_url must be empty or https://your-site\n"))
        self.assertEqual(self.pm("set", "versus_url", "https://hub.dev")[0], 0)
        self.assertEqual(self.pm("set", "versus_url", "")[0], 0)

    def test_nothing_is_fetched_without_sync(self):
        self.pm("set", "versus_url", "https://hub.dev")
        with mock.patch("pm.stats.urlopen") as urlopen:
            self.assertEqual(self.pm("versus"), (0, "no scoreboard yet: pm versus --sync\n"))
        urlopen.assert_not_called()

    def test_sync_sends_the_card_and_prints_the_board(self):
        self.pm("set", "versus_url", "https://hub.dev")
        with self.site(REPLY) as urlopen:
            code, out = self.pm("versus", "--sync", now=NOW)
        self.assertEqual(code, 0)
        sent = [(c.args[0].get_method(), c.args[0].full_url) for c in urlopen.call_args_list]
        self.assertEqual(sent, [("PUT", "https://hub.dev/api/versus"), ("GET", "https://hub.dev/api/versus")])
        self.assertEqual(json.loads(urlopen.call_args_list[0].args[0].data),
                         {"version": 1, "generated": NOW, "days": {}})
        self.assertEqual(out, "\n".join([
            "versus · 2026-11-13 (live)",
            "                         you     sam",
            "minutes studied          185     140  you",
            "reviews done              42      60  sam",
            "quiz answers right        18      18",
            "test answers right         9       0  you",
            "syllabus gained         +2.1    -0.4  you",
            "today: you 3 · sam 1",
            "wins: you 1 · sam 0 · draws 1",  # the 11th is a win, the 12th a draw, so no streak line
            "days of 30m or less: you 0 · sam 1",  # sam studied 30m on the 11th
            "score: you 1 · sam 0",  # the score never goes below zero
        ]) + "\n")
        with mock.patch("pm.stats.urlopen") as urlopen:  # the board is kept: no network without --sync
            self.assertEqual(self.pm("versus", now=NOW), (0, out))
        urlopen.assert_not_called()

    def test_alone_on_the_board(self):
        self.pm("set", "versus_url", "https://hub.dev")
        with self.site({"you": "kel", "cards": {"kel": REPLY["cards"]["kel"]}}):
            code, out = self.pm("versus", "--sync", now=NOW)
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("today: you 5\nwaiting for another player\n"))

    def test_a_refused_login_or_a_strange_reply_is_an_error(self):
        self.pm("set", "versus_url", "https://hub.dev")
        with mock.patch("pm.stats.urlopen", side_effect=HTTPError("u", 401, "no", {}, None)):
            code, out = self.pm("versus", "--sync")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("error: versus failed: HTTP 401"))
        with self.site([1, 2]):
            self.assertEqual(self.pm("versus", "--sync"),
                             (1, "error: the scoreboard's reply is not a set of cards\n"))
        self.assertEqual(self.pm("versus"), (0, "no scoreboard yet: pm versus --sync\n"))

    def test_the_push_carries_the_board(self):
        self.assertIsNone(json.loads(self.pm("stats")[1])["versus"])
        self.pm("set", "versus_url", "https://hub.dev")
        with self.site(REPLY):
            self.pm("versus", "--sync", now=NOW)
        pushed = json.loads(self.pm("stats", now=NOW)[1])["versus"]
        self.assertEqual((pushed["you"], pushed["players"], pushed["today"]["points"]),
                         ("kel", ["kel", "sam"], {"kel": 3, "sam": 1}))


if __name__ == "__main__":
    unittest.main()
