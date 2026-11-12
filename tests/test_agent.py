import unittest
from datetime import datetime, timedelta

from pm import agent
from pm.db import connect, put_setting

NOW = datetime(2026, 11, 9, 10, 0)


class Asker:
    """A fake model: replies from a list (the last one repeats), recording the prompts."""

    def __init__(self, *replies, error=None):
        self.replies = list(replies) or ["ok"]
        self.prompts = []
        self.error = error

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


class AgentCase(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")
        self.addCleanup(self.c.close)
        put_setting(self.c, "agent_daily_calls", "3")
        self.saved = dict(agent.HANDLERS)
        self.addCleanup(lambda: (agent.HANDLERS.clear(), agent.HANDLERS.update(self.saved)))

    def status(self, job_id):
        return self.c.execute("SELECT status, calls FROM jobs WHERE id=?", (job_id,)).fetchone()


class TestQueue(AgentCase):
    def test_enqueue(self):
        first = agent.enqueue(self.c, "ping", "", NOW)
        self.assertEqual(agent.enqueue(self.c, "ping", "", NOW), first)
        self.assertEqual(self.c.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "^unknown job kind 'nope'$"):
            agent.enqueue(self.c, "nope", "", NOW)

    def test_ping(self):
        agent.enqueue(self.c, "ping", "", NOW)
        self.assertEqual(agent.run(self.c, NOW, Asker("ok")), ["ping #1: ping: ok"])
        self.assertEqual(tuple(self.status(1)), ("done", 1))
        self.assertEqual((agent.spent(self.c, NOW), agent.budget_left(self.c, NOW)), (1, 2))
        job = agent.jobs(self.c)[0]
        self.assertEqual((job.result, job.finished), ("ping: ok", NOW))

    def test_no_budget(self):
        put_setting(self.c, "agent_daily_calls", "0")
        agent.enqueue(self.c, "ping", "", NOW)
        ask = Asker()
        self.assertEqual(agent.run(self.c, NOW, ask), [])
        self.assertEqual(ask.prompts, [])

    def test_out_of_budget_pauses(self):
        agent.HANDLERS["five"] = lambda conn, arg, now, ask: [ask(str(i)) for i in range(5)] and "five done"
        agent.enqueue(self.c, "five", "", NOW)
        ask = Asker()
        lines = agent.run(self.c, NOW, ask)
        self.assertEqual(lines, ["five #1: paused, out of budget for today"])
        self.assertEqual(tuple(self.status(1)), ("queued", 3))
        self.assertEqual((len(ask.prompts), agent.budget_left(self.c, NOW)), (3, 0))
        tomorrow = NOW + timedelta(days=1)
        self.assertEqual(agent.spent(self.c, tomorrow), 0)
        self.assertEqual(agent.run(self.c, tomorrow, ask), ["five #1: paused, out of budget for today"])
        put_setting(self.c, "agent_daily_calls", "10")
        self.assertEqual(agent.run(self.c, tomorrow + timedelta(days=1), ask), ["five #1: five done"])
        self.assertEqual(tuple(self.status(1)), ("done", 11))

    def test_failures_and_the_next_job(self):
        def bad(conn, arg, now, ask):
            raise ValueError("bad reply")

        def missing(conn, arg, now, ask):
            raise LookupError("no question #9")
        agent.HANDLERS.update(bad=bad, missing=missing)
        agent.enqueue(self.c, "bad", "", NOW)
        agent.enqueue(self.c, "missing", "", NOW)
        agent.enqueue(self.c, "ping", "", NOW)
        self.assertEqual(agent.run(self.c, NOW, Asker()),
                         ["bad #1: failed: bad reply", "missing #2: failed: no question #9", "ping #3: ping: ok"])
        self.assertEqual(self.status(1)[0], "failed")

    def test_limit(self):
        agent.enqueue(self.c, "ping", "a", NOW)
        agent.enqueue(self.c, "ping", "b", NOW)
        self.assertEqual(len(agent.run(self.c, NOW, Asker(), limit=1)), 1)
        self.assertEqual(agent.queued(self.c), 1)

    def test_counted_charges_first(self):
        call = agent.counted(self.c, NOW, Asker(error=RuntimeError("boom")))
        with self.assertRaises(RuntimeError):
            call("hi")
        self.assertEqual(agent.spent(self.c, NOW), 1)


class TestParseJson(unittest.TestCase):
    def test_found(self):
        self.assertEqual(agent.parse_json('Here you go:\n```json\n[{"a": 1}]\n```'), [{"a": 1}])
        self.assertEqual(agent.parse_json("text [1, 2] more"), [1, 2])
        self.assertEqual(agent.parse_json('{"a": 1}', "{"), {"a": 1})
        self.assertEqual(agent.parse_json('```\n{"a": [1]}\n```', "{"), {"a": [1]})

    def test_refused(self):
        for text in ("no list here", "[1, 2", "] backwards [", "[1, 2,]"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "^the model's reply wasn't the expected JSON$"):
                agent.parse_json(text)


if __name__ == "__main__":
    unittest.main()


class TestPlan(AgentCase):
    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path
        from pm.study import add_topic
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        add_topic(self.c, "paging", course="os")

    def reviewed_item(self, name, text=None):
        from tests.test_spot import NOTE
        from pm.study import add_item, record_review
        path = self.dir / name
        path.write_text(text or NOTE)
        item = add_item(self.c, 1, path, "TLB", now=NOW)
        record_review(self.c, item, 3, 0.8, NOW)
        return item

    def kinds(self, ids):
        return [tuple(self.c.execute("SELECT kind, arg FROM jobs WHERE id=?", (i,)).fetchone()) for i in ids]

    def test_empty(self):
        self.assertEqual(agent.plan(self.c, NOW), [])

    def test_spots(self):
        item = self.reviewed_item("os.md")
        self.assertEqual(self.kinds(agent.plan(self.c, NOW)), [("spots", "")])
        self.assertEqual(agent.plan(self.c, NOW), [])
        self.c.execute("DELETE FROM jobs")
        for _ in range(5):
            self.c.execute("INSERT INTO spots(item_id, original, mutated, line, created) VALUES(?, 'a', 'b', 1, ?)",
                           (item, NOW.isoformat()))
        self.c.commit()
        self.assertEqual(agent.plan(self.c, NOW), [])

    def test_sort_sessions(self):
        self.c.execute("INSERT INTO lh_sessions(chat_id, title, kind, mtime, size) VALUES('chat_a', 't', 'teach', 0, 0)")
        self.c.commit()
        self.assertEqual(self.kinds(agent.plan(self.c, NOW)), [("sort-sessions", "")])
        self.c.execute("DELETE FROM jobs")
        self.c.execute("INSERT INTO suggestions(kind, subject, value, created) VALUES('topic', 'chat_a', '1', 'x')")
        self.c.commit()
        self.assertEqual(agent.plan(self.c, NOW), [])

    def missed(self, qid, minutes):
        when = (NOW + timedelta(minutes=minutes)).isoformat()
        mid = self.c.execute("INSERT INTO mocks(course, title, minutes, created, marked) VALUES('os', 't', 10, ?, ?)",
                             (when, when)).lastrowid
        self.c.execute("INSERT INTO mock_items(mock_id, pos, question_id, topic_id, marks, score) VALUES(?, 1, ?, 1, 1, 0)",
                       (mid, qid))
        self.c.commit()

    def test_variants(self):
        from pm import bank
        add = lambda ref, **kw: bank.add_question(self.c, origin="manual", ref=ref, prompt=f"q {ref}", now=NOW,  # noqa: E731
                                                  trust="source", topic_id=1, **kw)
        plain = [add(f"m{k}", answer="an answer") for k in range(4)]
        full = add("full", answer="a")
        for k in range(3):
            add(f"child{k}", answer="c", parent_id=full)
        gone = add("gone", answer="a")
        bank.retire(self.c, gone)
        variant = add("variant", answer="v", parent_id=plain[0])
        bare = add("bare")
        for minutes, qid in enumerate([*plain, full, gone, variant, bare]):
            self.missed(qid, minutes)
        jobs = self.kinds(agent.plan(self.c, NOW))
        self.assertEqual(jobs, [("variants", str(plain[3])), ("variants", str(plain[2])), ("variants", str(plain[1]))])
        self.assertEqual(agent.plan(self.c, NOW), [])
        self.assertEqual(self.c.execute("SELECT count(*) FROM jobs WHERE kind='prereqs'").fetchone()[0], 0)

    def test_variants_wait_a_week_after_a_run(self):
        from pm import bank
        qid = bank.add_question(self.c, origin="manual", ref="m", prompt="q", now=NOW, trust="source", topic_id=1,
                                answer="a")
        self.missed(qid, 0)
        [job] = agent.plan(self.c, NOW)
        self.c.execute("UPDATE jobs SET status='done', finished=? WHERE id=?", (NOW.isoformat(), job))
        self.c.commit()
        self.assertEqual(agent.plan(self.c, NOW + timedelta(days=1)), [])
        self.assertEqual(len(agent.plan(self.c, NOW + timedelta(days=8))), 1)

    def test_spots_handler(self):
        from tests.test_spot import change
        self.reviewed_item("a.md")
        self.reviewed_item("b.md")
        self.reviewed_item("short.md", "# OS\n\n## TLB\nshort\n")
        put_setting(self.c, "agent_daily_calls", "10")
        agent.enqueue(self.c, "spots", "", NOW)
        self.assertEqual(agent.run(self.c, NOW, change(2)), ["spots #1: 2 cards"])
