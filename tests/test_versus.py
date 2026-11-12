import json
import unittest
from datetime import date, datetime, timedelta

from pm import evidence
from pm.db import connect, get_setting
from pm.tasks import add_task, log_time
from pm.versus import CACHE, board, cached, card, parse

NOW = datetime(2026, 11, 13, 10, 0)
TODAY = NOW.date()


def c(generated="2026-11-13T09:00:00", **days):
    return {"version": 1, "generated": generated,
            "days": {k.replace("_", "-")[1:]: v for k, v in days.items()}}


def d(min=0, reviews=0, quiz=0, test=0, **kw):
    return {"min": min, "reviews": reviews, "quiz": quiz, "test": test, **kw}


class TestCard(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)

    def test_an_empty_database_gives_an_empty_card(self):
        self.assertEqual(card(self.c, NOW), {"version": 1, "generated": "2026-11-13T10:00:00", "days": {}})

    def test_minutes_and_answers_land_on_their_day(self):
        task = add_task(self.c, "read", 60, now=NOW)
        log_time(self.c, task, 45, NOW)
        evidence.add(self.c, source="practice", ref="a", ts=NOW, grader="code", correct=True)
        evidence.add(self.c, source="practice", ref="b", ts=NOW, grader="code", correct=False)
        evidence.add(self.c, source="test", ref="1/1", ts=NOW - timedelta(days=1), grader="code", correct=True)
        days = card(self.c, NOW)["days"]
        self.assertEqual(days["2026-11-13"], d(min=45, quiz=1))
        self.assertEqual(days["2026-11-12"], d(test=1))

    def test_the_card_holds_only_numbers(self):
        task = add_task(self.c, "secret title", 60, now=NOW, course="secret course")
        log_time(self.c, task, 30, NOW)
        self.assertNotIn("secret", json.dumps(card(self.c, NOW)))

    def test_a_day_older_than_the_window_is_left_out(self):
        evidence.add(self.c, source="practice", ref="a", ts=NOW - timedelta(days=400), grader="code", correct=True)
        self.assertEqual(card(self.c, NOW)["days"], {})

    def test_our_own_card_survives_parse(self):
        task = add_task(self.c, "read", 60, now=NOW)
        log_time(self.c, task, 45, NOW)
        mine = card(self.c, NOW)
        self.assertEqual(parse({"you": "a", "cards": {"a": mine}}),
                         ("a", {"a": {"generated": mine["generated"], "days": mine["days"]}}))

    def test_cached_is_none_before_a_sync_and_a_board_after(self):
        self.assertIsNone(cached(self.c, TODAY))
        from pm.db import set_setting
        set_setting(self.c, CACHE, json.dumps({"you": "a", "cards": {"a": c(), "b": c()}}))
        self.assertEqual(cached(self.c, TODAY)["players"], ["a", "b"])
        set_setting(self.c, CACHE, "[1]")
        self.assertIsNone(cached(self.c, TODAY))
        self.assertEqual(get_setting(self.c, CACHE, ""), "[1]")


class TestParse(unittest.TestCase):
    def test_a_reply_that_is_not_cards_is_refused(self):
        for bad in (None, [], "x", {}, {"cards": []}, {"cards": None}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "not a set of cards"):
                parse(bad)

    def test_a_bad_card_is_left_out_and_the_rest_kept(self):
        good = c(_2026_11_12=d(min=10))
        bad = [None, [], "x", {}, {"version": 2, "generated": "2026-11-13T09:00:00", "days": {}},
               {"version": 1, "generated": "soon", "days": {}}, {"version": 1, "generated": 5, "days": {}},
               {"version": 1, "generated": "2026-11-13T09:00:00+00:00", "days": {}},
               {"version": 1, "generated": "2026-11-13T09:00:00", "days": []}]
        for i, card_ in enumerate(bad):
            with self.subTest(i=i):
                you, cards = parse({"you": "bad", "cards": {"bad": card_, "ok": good}})
                self.assertEqual(list(cards), ["ok"])
                self.assertIsNone(you)

    def test_a_bad_day_is_left_out(self):
        bad = [d(min=-1), d(min=1441), d(min=1.5), d(min=True), d(min="9"), d(reviews=10**9), d(syllabus=101),
               d(syllabus=float("nan")), d(syllabus="50"), d(syllabus=True), "x", None]
        for i, day in enumerate(bad):
            with self.subTest(i=i):
                _, cards = parse({"cards": {"a": {"version": 1, "generated": "2026-11-13T09:00:00",
                                                  "days": {"2026-11-12": day, "2026-11-11": d(min=5)}}}})
                self.assertEqual(list(cards["a"]["days"]), ["2026-11-11"])

    def test_a_bad_date_or_name_is_left_out(self):
        _, cards = parse({"cards": {"a": c(), "": c(), "x" * 41: c(), "a\nb": c(),
                                    "b": {"version": 1, "generated": "2026-11-13T09:00:00",
                                          "days": {"yesterday": d(min=5), "20261112": d(min=5)}}}})
        self.assertEqual(cards, {"a": {"generated": "2026-11-13T09:00:00", "days": {}},
                                 "b": {"generated": "2026-11-13T09:00:00", "days": {}}})

    def test_unknown_keys_are_dropped(self):
        _, cards = parse({"cards": {"a": c(_2026_11_12={**d(min=5), "title": "<b>"})}})
        self.assertEqual(cards["a"]["days"]["2026-11-12"], d(min=5))


class TestBoard(unittest.TestCase):
    def cards(self, **kw):
        return parse({"cards": kw})[1]

    def test_today_gives_each_point_to_the_sole_leader(self):
        cards = self.cards(
            kel=c(_2026_11_12=d(syllabus=40.0), _2026_11_13=d(min=185, reviews=42, quiz=18, test=9, syllabus=42.1)),
            sam=c(_2026_11_12=d(syllabus=50.0), _2026_11_13=d(min=140, reviews=60, quiz=18, syllabus=49.6)))
        b = board(cards, "kel", TODAY)
        today = b["today"]
        self.assertEqual([r["leader"] for r in today["rows"]], ["kel", "sam", None, "kel", "kel"])
        self.assertEqual(today["rows"][4]["values"], {"kel": 2.1, "sam": -0.4})
        self.assertEqual(today["points"], {"kel": 3, "sam": 1})
        self.assertEqual((today["leader"], today["draw"], b["you"]), ("kel", False, "kel"))
        self.assertEqual([r["key"] for r in today["rows"]], ["min", "reviews", "quiz", "test", "syllabus"])

    def test_nothing_done_is_no_point_and_no_draw(self):
        b = board(self.cards(a=c(), b=c()), None, TODAY)
        self.assertEqual(b["today"]["points"], {"a": 0, "b": 0})
        self.assertEqual((b["today"]["leader"], b["today"]["draw"]), (None, False))

    def test_a_first_syllabus_reading_is_no_gain(self):
        b = board(self.cards(a=c(_2026_11_13=d(syllabus=80.0)), b=c(_2026_11_13=d(min=1))), None, TODAY)
        self.assertEqual(b["today"]["rows"][4]["values"], {"a": 0.0, "b": 0.0})

    def test_final_days_make_the_tally_the_streak_and_the_draws(self):
        cards = self.cards(
            a=c(_2026_11_08=d(min=5), _2026_11_09=d(min=9), _2026_11_10=d(min=5), _2026_11_11=d(min=9),
                _2026_11_12=d(min=9), _2026_11_13=d(min=1)),
            b=c(_2026_11_09=d(min=5), _2026_11_10=d(min=5), _2026_11_11=d(min=1), _2026_11_13=d(min=99)))
        b = board(cards, "a", TODAY)
        self.assertEqual(b["tally"], {"a": 3, "b": 0})  # the 8th is before b started, today isn't final
        self.assertEqual(b["draws"], 1)
        self.assertEqual(b["streak"], {"name": "a", "days": 2})
        # 9th-12th: a studied 9, 5, 9, 9 minutes and b 5, 5, 1, 0, so every one of those days is a penalty for both
        self.assertEqual(b["penalties"], {"a": 4, "b": 4})
        self.assertEqual(b["score"], {"a": 0, "b": 0})  # never below zero
        self.assertEqual([(r["day"], r["winner"]) for r in b["recent"]],
                         [("2026-11-12", "a"), ("2026-11-11", "a"), ("2026-11-10", None), ("2026-11-09", "a")])

    def test_thirty_minutes_or_less_on_a_final_day_costs_a_point_of_score(self):
        cards = self.cards(a=c(_2026_11_10=d(min=31), _2026_11_11=d(min=30), _2026_11_12=d(min=120), _2026_11_13=d(min=0)),
                           b=c(_2026_11_10=d(min=90), _2026_11_11=d(min=45, reviews=99), _2026_11_13=d(min=200)))
        b = board(cards, "a", TODAY)
        self.assertEqual(b["tally"], {"a": 1, "b": 2})
        self.assertEqual(b["penalties"], {"a": 1, "b": 1})  # a on the 11th (30m), b on the 12th (nothing); today isn't final
        # 10th: b wins (1). 11th: b wins (2), a's penalty stops at 0. 12th: a wins (1), b's penalty takes one (1)
        self.assertEqual(b["score"], {"a": 1, "b": 1})
        self.assertEqual([r["penalty"] for r in b["recent"]], [["b"], ["a"], []])
        self.assertEqual(b["today"]["penalty"], ["a"])  # so far today: shown live, not counted yet

    def test_a_day_is_not_final_until_everyone_synced_after_it(self):
        cards = self.cards(a=c(_2026_11_11=d(min=9), _2026_11_12=d(min=9)),
                           b=c("2026-11-12T23:00:00", _2026_11_11=d(min=1), _2026_11_12=d(min=1)))
        b = board(cards, None, TODAY)
        self.assertEqual(b["tally"], {"a": 1, "b": 0})
        self.assertEqual(b["synced"], {"a": "2026-11-13T09:00:00", "b": "2026-11-12T23:00:00"})

    def test_the_latest_winner_changing_ends_the_streak(self):
        cards = self.cards(a=c(_2026_11_10=d(min=9), _2026_11_11=d(min=9), _2026_11_12=d(min=1)),
                           b=c(_2026_11_10=d(min=1), _2026_11_12=d(min=9)))
        self.assertEqual(board(cards, None, TODAY)["streak"], {"name": "b", "days": 1})

    def test_one_player_or_none_scores_nothing(self):
        alone = board(self.cards(a=c(_2026_11_12=d(min=9), _2026_11_13=d(min=9))), "a", TODAY)
        self.assertEqual((alone["players"], alone["tally"], alone["recent"], alone["streak"]), (["a"], {"a": 0}, [], None))
        self.assertEqual((alone["penalties"], alone["score"]), ({"a": 0}, {"a": 0}))  # nobody to play against: no penalty
        self.assertEqual(alone["today"]["points"], {"a": 1})
        empty = board({}, None, TODAY)
        self.assertEqual((empty["players"], empty["today"]["leader"], empty["tally"]), ([], None, {}))

    def test_three_players_share_one_board(self):
        cards = self.cards(a=c(_2026_11_12=d(min=9)), b=c(_2026_11_12=d(min=5)), z=c(_2026_11_12=d(min=5, quiz=3)))
        b = board(cards, None, TODAY)
        self.assertEqual(b["recent"][0]["points"], {"a": 1, "b": 0, "z": 1})
        self.assertEqual((b["draws"], b["tally"]), (1, {"a": 0, "b": 0, "z": 0}))

    def test_a_clock_in_the_future_cannot_close_today(self):
        cards = self.cards(a=c("2027-01-01T00:00:00", _2026_11_13=d(min=9)),
                           b=c("2027-01-01T00:00:00", _2026_11_13=d(min=1)))
        self.assertEqual(board(cards, None, TODAY)["tally"], {"a": 0, "b": 0})


if __name__ == "__main__":
    unittest.main()
