import json
import unittest
from datetime import datetime

from pm import agent, lh, suggest
from pm.db import connect, put_setting
from pm.study import add_prereq, add_topic, get_topic, would_loop

NOW = datetime(2026, 11, 9, 10, 0)


class Asker:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def session(conn, chat_id, title, kind="teach"):
    conn.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES(?,?,?,0,0)", (chat_id, title, kind))
    conn.commit()


class SuggestCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        for name in ("paging", "disk"):
            add_topic(self.c, name, course="os")
        session(self.c, "chat_a", "TLB and paging")
        session(self.c, "chat_b", "Small talk")

    def status(self, sid):
        return self.c.execute("SELECT status FROM suggestions WHERE id=?", (sid,)).fetchone()[0]


class TestSessions(SuggestCase):
    def test_store_only_what_applies(self):
        ask = Asker(json.dumps({"chat_a": 1, "chat_b": None, "chat_zzz": 1, "chat_a2": 99}))
        self.assertEqual(suggest.session_topics(self.c, NOW, ask), 1)
        self.assertIn("chat_a: TLB and paging — teach", ask.prompts[0])
        self.assertIn("chat_b: Small talk — teach", ask.prompts[0])
        self.assertIn("1: os / paging\n2: os / disk", ask.prompts[0])
        [s] = suggest.open_suggestions(self.c)
        self.assertEqual(s.text, 'put session "TLB and paging" under os/paging')
        ask = Asker(json.dumps({"chat_b": 2}))
        suggest.session_topics(self.c, NOW, ask)
        self.assertEqual(ask.prompts, [])  # chat_a has its suggestion and chat_b got "no topic": neither is asked again

    def test_nothing_to_ask(self):
        self.c.execute("UPDATE lh_sessions SET topic_id=1")
        self.c.commit()
        ask = Asker()
        self.assertEqual(suggest.session_topics(self.c, NOW, ask), 0)
        self.assertEqual(ask.prompts, [])

    def test_bad_reply(self):
        with self.assertRaisesRegex(ValueError, "expected JSON"):
            suggest.session_topics(self.c, NOW, Asker("[1, 2]"))
        with self.assertRaisesRegex(ValueError, "expected JSON"):
            suggest.session_topics(self.c, NOW, Asker("no idea"))
        self.assertEqual(self.c.execute("SELECT count(*) FROM suggestions").fetchone()[0], 0)

    def test_accept_maps_the_session(self):
        suggest.session_topics(self.c, NOW, Asker('{"chat_a": 1}'))
        self.assertEqual(suggest.accept(self.c, 1), 'put session "TLB and paging" under os/paging')
        self.assertEqual({x.chat_id: x.topic_id for x in lh.sessions(self.c)}["chat_a"], 1)
        self.assertEqual(self.status(1), "accepted")

    def test_stale_suggestion_closes(self):
        suggest.session_topics(self.c, NOW, Asker('{"chat_a": 1}'))
        lh.map_session(self.c, "chat_a", 2)
        self.assertEqual(suggest.open_suggestions(self.c), [])
        self.assertEqual(self.status(1), "rejected")
        with self.assertRaisesRegex(LookupError, "^no open suggestion #1$"):
            suggest.accept(self.c, 1)

    def test_reject(self):
        suggest.session_topics(self.c, NOW, Asker('{"chat_a": 1}'))
        suggest.reject(self.c, 1)
        self.assertEqual(self.status(1), "rejected")
        with self.assertRaises(LookupError):
            suggest.accept(self.c, 1)
        with self.assertRaises(LookupError):
            suggest.reject(self.c, 9)


class TestPrereqs(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        for name in ("a", "b", "c"):
            add_topic(self.c, name, course="os")

    def test_pairs(self):
        reply = json.dumps([["b", "a"], ["c", "b"], ["a", "c"], ["a", "a"], ["b", "zzz"], ["b", "a"], "junk"])
        ask = Asker(reply)
        self.assertEqual(suggest.prereqs(self.c, "os", NOW, ask), 2)
        self.assertEqual("a\nb\nc", ask.prompts[0].split("Topics:\n")[1])
        self.assertEqual([s.text for s in suggest.open_suggestions(self.c)], ["os/b needs os/a", "os/c needs os/b"])
        self.assertEqual(get_topic(self.c, 2).prereqs, [])

    def test_existing_and_small_courses(self):
        add_prereq(self.c, 2, 1)
        self.assertEqual(suggest.prereqs(self.c, "os", NOW, Asker('[["b", "a"]]')), 0)
        add_topic(self.c, "solo", course="db")
        ask = Asker()
        self.assertEqual(suggest.prereqs(self.c, "db", NOW, ask), 0)
        self.assertEqual(ask.prompts, [])

    def test_accept_and_a_new_loop(self):
        suggest.prereqs(self.c, "os", NOW, Asker('[["b", "a"], ["c", "b"]]'))
        self.assertEqual(suggest.accept(self.c, 1), "os/b needs os/a")
        self.assertEqual(get_topic(self.c, 2).prereqs, [1])
        add_prereq(self.c, 1, 3)  # a needs c: now c needs b would close a loop
        with self.assertRaisesRegex(ValueError, "^that suggestion no longer applies"):
            suggest.accept(self.c, 2)
        self.assertEqual(self.c.execute("SELECT status FROM suggestions WHERE id=2").fetchone()[0], "rejected")


class TestWouldLoop(unittest.TestCase):
    def test_would_loop(self):
        c = connect(":memory:")
        self.addCleanup(c.close)
        for name in ("a", "b", "c", "d"):
            add_topic(c, name, course="os")
        add_prereq(c, 2, 1)  # b needs a
        add_prereq(c, 3, 2)  # c needs b
        self.assertFalse(would_loop(c, 4, 1))
        self.assertTrue(would_loop(c, 1, 2))
        self.assertTrue(would_loop(c, 1, 3))
        self.assertTrue(would_loop(c, 1, 1))
        self.assertTrue(would_loop(c, 1, 4, ((4, 3),)))
        self.assertEqual(c.execute("SELECT count(*) FROM topic_prereqs").fetchone()[0], 2)


class TestJobs(SuggestCase):
    def test_handlers(self):
        put_setting(self.c, "agent_daily_calls", "5")
        agent.enqueue(self.c, "sort-sessions", "", NOW)
        agent.enqueue(self.c, "prereqs", "os", NOW)
        agent.enqueue(self.c, "prereqs", "nope", NOW)
        lines = agent.run(self.c, NOW, Asker('{"chat_a": 1}', '[["paging", "disk"]]'))
        self.assertEqual(lines, ["sort-sessions #1: 1 suggestions", "prereqs #2: 1 suggestions",
                                 "prereqs #3: 0 suggestions"])


if __name__ == "__main__":
    unittest.main()
