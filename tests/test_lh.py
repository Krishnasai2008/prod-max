import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pm import bank, evidence, grade, lh, study
from pm.db import connect, put_setting
from pm.lh import TAG, local, parse_session

FIXTURES = Path(__file__).parent / "lh"
NOW = datetime.fromtimestamp(1794240000)  # 2026-11-09 16:00 UTC, after both fixture sessions


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class TestLocal(unittest.TestCase):
    def test_local(self):
        self.assertEqual(local(1762680000000), datetime.fromtimestamp(1762680000))
        self.assertEqual(local("2026-11-09T04:00:00Z"),
                         datetime(2026, 11, 9, 4, tzinfo=timezone.utc).astimezone().replace(tzinfo=None))
        self.assertEqual(local("2026-11-09T10:00:00"), datetime(2026, 11, 9, 10))
        for bad in (None, "soon", [], True):
            self.assertIsNone(local(bad))


class TestTeach(unittest.TestCase):
    def setUp(self):
        self.s = parse_session(fixture("teach"))
        self.by_question = {a.question: a for a in self.s.answers}

    def test_header(self):
        self.assertEqual((self.s.tag, self.s.kind, self.s.title), (1, "teach", "TLB and paging"))

    def test_only_gradable_answers(self):
        self.assertEqual(len(self.s.answers), 6)
        refs = [a.ref for a in self.s.answers]
        self.assertEqual(len(set(refs)), 6)
        self.assertTrue(all(r.startswith("chat_teach/") for r in refs))
        for gone in ("m11", "m13", "m15", "m17"):
            self.assertNotIn(f"chat_teach/{gone}", refs)

    def test_roles_and_confidence(self):
        probe = self.by_question["What does a page table map?"]
        self.assertEqual((probe.role, probe.correct, probe.confidence), ("probe", True, 0.7))
        predict = self.by_question["Will FIFO fault more with 4 frames on Belady's string?"]
        self.assertEqual((predict.role, predict.correct, predict.confidence), ("predict", False, 0.9))
        dk = self.by_question["What sets the dirty bit?"]
        self.assertTrue(dk.dont_know)
        self.assertFalse(dk.correct)
        self.assertIsNone(dk.confidence)

    def test_shuffled_options(self):
        check = self.by_question["Which policy is a stack algorithm?"]
        self.assertEqual(check.options, ["Random", "FIFO", "LRU"])
        self.assertEqual(check.options[check.correct_options[0] - 1], "LRU")

    def test_repeated_call_ids(self):
        first, second = self.by_question["What is a TLB?"], self.by_question["What does a TLB miss cost?"]
        self.assertNotEqual(first.ref, second.ref)
        self.assertEqual((first.correct, second.correct), (True, False))

    def test_minutes(self):
        self.assertEqual(sum(self.s.days.values()), 4)
        self.assertEqual(len(self.s.days), 1)

    def test_tag_is_found_in_text(self):
        self.assertEqual(TAG.search("[pm:topic=12] hi")[1], "12")


class TestPractice(unittest.TestCase):
    def test_outcomes(self):
        s = parse_session(fixture("practice"))
        self.assertIsNone(s.tag)
        self.assertEqual(s.kind, "practice")
        self.assertEqual([x.score for x in s.solved], [1.0, 0.5, None])
        self.assertEqual([x.statement for x in s.solved],
                         ["Problem 1: count the LRU faults.", "Problem 2: count the LRU faults.",
                          "Problem 4: count the LRU faults."])
        self.assertEqual(s.solved[0].solution, "Solution 1.")
        self.assertEqual(s.solved[0].ref, "chat_practice/p2/call_pr1")


class TestRefused(unittest.TestCase):
    def test_versions_and_shapes(self):
        with self.assertRaisesRegex(ValueError, r"^newer LearnHarness format \(version 2\)$"):
            parse_session(fixture("v2"))
        for bad in ({}, [], {"id": "x", "messages": "no"}, {"id": 3, "messages": []}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "^not a LearnHarness session$"):
                parse_session(bad)

    def test_bare_session(self):
        s = parse_session({"id": "chat_x", "messages": []})
        self.assertEqual((s.kind, s.title, s.tag, s.answers, s.solved, s.days), ("teach", "chat_x", None, [], [], {}))

    def test_tag_only_in_first_user_message(self):
        blocks = {"id": "c", "messages": [{"role": "user", "content": [{"type": "text", "text": "[pm:topic=7] hi"}]}]}
        self.assertEqual(parse_session(blocks).tag, 7)
        later = {"id": "c", "messages": [{"role": "user", "content": "hi"},
                                          {"role": "user", "content": "[pm:topic=7]"}]}
        self.assertIsNone(parse_session(later).tag)

    def test_garbage_inside(self):
        data = {"id": "c", "messages": [
            "a string", 5, None,
            {"id": "g1", "role": "toolResult", "toolName": "quiz", "details": None},
            {"id": "g2", "role": "toolResult", "toolName": "quiz", "timestamp": 1762680000000,
             "details": {"kind": "quiz", "correct": True, "confidence": "high", "correctIndices": [9],
                         "options": [{"label": "a"}, 7, "b"]}},
            {"id": "g3", "role": "assistant", "content": "not a list"},
            {"id": "g4", "role": "assistant", "content": [{"type": "toolCall", "name": "conclude"}]},
            {"role": "toolResult", "toolName": "quiz", "details": {"kind": "quiz", "correct": True}},
        ]}
        s = parse_session(data)
        self.assertEqual(len(s.answers), 1)
        a = s.answers[0]
        self.assertEqual((a.options, a.correct_options, a.confidence, a.correct), (["a", "b"], [], None, True))

    def test_huge_timestamps(self):
        msgs = [{"role": "user", "content": "hi", "timestamp": t} for t in (1e300, 1e300, 10**400, float("inf"))]
        msgs += [{"role": "user", "content": "x", "timestamp": t} for t in (1762680000000, 1762680060000)]
        self.assertEqual(sum(parse_session({"id": "c", "messages": msgs}).days.values()), 1)


class LhCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        (self.root / "chats").mkdir(parents=True)
        for name in ("teach", "practice"):
            self.put(f"chat_{name}.json", (FIXTURES / f"{name}.json").read_text())
        self.c = connect(":memory:")
        study.add_topic(self.c, "paging", course="os")

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def put(self, name, text, age=3600, folder="chats"):
        path = self.root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.age(path, age)
        return path

    def age(self, path, seconds):
        t = NOW.timestamp() - seconds
        os.utime(path, (t, t))

    def sync(self):
        return lh.sync(self.c, NOW, self.root)

    def count(self, sql, *args):
        return self.c.execute(sql, args).fetchone()[0]


class TestDataDir(LhCase):
    def test_data_dir(self):
        put_setting(self.c, "lh_dir", str(self.root))
        self.assertEqual(lh.data_dir(self.c), self.root)
        shutil.rmtree(self.root / "chats")
        self.assertIsNone(lh.data_dir(self.c))

    def test_default_dir(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}):
            self.assertEqual(lh.default_dir(), Path(self.tmp.name) / "LearnHarness" / "data")
            self.assertIsNone(lh.data_dir(self.c))
            (Path(self.tmp.name) / "LearnHarness" / "data" / "chats").mkdir(parents=True)
            self.assertEqual(lh.data_dir(self.c), Path(self.tmp.name) / "LearnHarness" / "data")

    def test_no_folder(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}), \
                self.assertRaisesRegex(ValueError, r"^LearnHarness data not found \(pm set lh_dir <folder>\)$"):
            lh.sync(self.c, NOW)


class TestSync(LhCase):
    def test_import(self):
        out = self.sync()
        self.assertEqual((out.sessions, out.answers, out.outcomes, out.questions, out.skipped), (2, 6, 3, 9, []))
        self.assertTrue(out.changed)
        quiz = evidence.rows(self.c, source="lh-quiz")
        self.assertEqual(len(quiz), 6)
        self.assertTrue(all(r.grader == "code" and r.topic_id == 1 for r in quiz))
        by_label = {r.label: r for r in quiz}
        self.assertIsNone(by_label["Will FIFO fault more with 4 frames on Belady's string?"].facet)
        dk = by_label["What sets the dirty bit?"]
        self.assertEqual((dk.dont_know, dk.confidence), (True, None))
        practice = evidence.rows(self.c, source="lh-practice")
        self.assertEqual([(r.grader, r.topic_id, r.score, r.facet) for r in practice],
                         [("llm", None, 1.0, "application"), ("llm", None, 0.5, "application"),
                          ("llm", None, None, "application")])

    def test_questions(self):
        self.sync()
        qs = bank.questions(self.c, origin="lh")
        self.assertEqual(len(qs), 9)
        self.assertTrue(all(q.trust == "unverified" for q in qs))
        choice = {q.prompt: q for q in qs if q.kind == "choice"}
        self.assertEqual(len(choice), 6)
        self.assertTrue(all(q.topic_id == 1 for q in choice.values()))
        stack = choice["Which policy is a stack algorithm?"]
        self.assertTrue(grade.check("choice", stack.expected, "3"))
        self.assertFalse(grade.check("choice", stack.expected, "2"))
        open_ = sorted((q.prompt, q.answer, q.topic_id) for q in qs if q.kind == "open")
        self.assertEqual(open_[0], ("Problem 1: count the LRU faults.", "Solution 1.", None))
        self.assertEqual(len(open_), 3)

    def test_idempotent(self):
        self.sync()
        before = self.count("SELECT count(*) FROM evidence"), self.count("SELECT count(*) FROM questions")
        with mock.patch("pm.lh.parse_session") as parse:
            out = self.sync()
        parse.assert_not_called()
        self.assertEqual((out.sessions, out.answers, out.outcomes, out.questions, out.cards), (0, 0, 0, 0, 0))
        self.assertFalse(out.changed)
        self.assertEqual((self.count("SELECT count(*) FROM evidence"), self.count("SELECT count(*) FROM questions")),
                         before)

    def test_calibration_and_mastery(self):
        self.sync()
        self.assertEqual(study.calibration(self.c).n, 5)
        self.assertEqual(study.facets(self.c, 1, NOW).understanding.n, 5)
        predict = [r.ref for r in evidence.rows(self.c, source="lh-quiz") if r.facet is None]
        self.assertEqual(len(predict), 1)
        self.assertNotIn(predict[0], [r.ref for r in evidence.rows(self.c, facet="understanding")])

    def test_still_being_written(self):
        self.age(self.root / "chats" / "chat_teach.json", 3)
        self.assertEqual(self.sync().sessions, 1)
        self.assertEqual(self.count("SELECT count(*) FROM lh_sessions WHERE chat_id='chat_teach'"), 0)
        self.age(self.root / "chats" / "chat_teach.json", 3600)
        self.assertEqual(self.sync().sessions, 1)

    def test_half_written(self):
        path = self.put("chat_half.json", '{"id": "chat_half", "messa')
        self.assertEqual(self.sync().skipped, [])
        self.assertEqual(self.count("SELECT count(*) FROM lh_sessions WHERE chat_id='chat_half'"), 0)
        path.write_text('{"id": "chat_half", "messages": []}')
        self.age(path, 600)
        self.assertEqual(self.sync().sessions, 1)

    def test_newer_format(self):
        self.put("chat_v2.json", (FIXTURES / "v2.json").read_text().replace('"id": "chat_v2"', '"id": "chat_v2"'))
        msg = "newer LearnHarness format (version 2)"
        self.assertEqual(self.sync().skipped, [f"chat_v2.json: {msg}"])
        self.assertEqual(self.count("SELECT error FROM lh_sessions WHERE chat_id='chat_v2'"), msg)
        self.assertEqual(self.sync().skipped, [])

    def test_id_must_match_the_file(self):
        self.put("chat_other.json", '{"id": "chat_else", "messages": []}')
        self.assertEqual(self.sync().skipped, ["chat_other.json: the session id doesn't match its file name"])

    def test_too_large(self):
        with mock.patch("pm.lh.MAX_BYTES", 10):
            out = self.sync()
        self.assertEqual(out.skipped, ["chat_practice.json: too large", "chat_teach.json: too large"])
        self.assertEqual(self.count("SELECT count(*) FROM lh_sessions"), 0)
        self.assertEqual(self.count("SELECT count(*) FROM evidence"), 0)

    def test_mapping(self):
        self.sync()
        lh.map_session(self.c, "chat_practice", 1)
        self.assertEqual({r.topic_id for r in evidence.rows(self.c, source="lh-practice")}, {1})
        self.assertEqual({q.topic_id for q in bank.questions(self.c, origin="lh") if q.kind == "open"}, {1})
        self.assertEqual(self.count("SELECT tagged FROM lh_sessions WHERE chat_id='chat_practice'"), 0)
        self.age(self.root / "chats" / "chat_practice.json", 1800)
        self.assertEqual(self.sync().sessions, 1)
        self.assertEqual({r.topic_id for r in evidence.rows(self.c, source="lh-practice")}, {1})
        lh.map_session(self.c, "chat_practice", None)
        self.assertEqual({r.topic_id for r in evidence.rows(self.c, source="lh-practice")}, {None})
        self.assertEqual({r.topic_id for r in evidence.rows(self.c, source="lh-quiz")}, {1})
        with self.assertRaisesRegex(LookupError, "no LearnHarness session 'nope'"):
            lh.map_session(self.c, "nope", 1)
        with self.assertRaisesRegex(LookupError, "no topic #9"):
            lh.map_session(self.c, "chat_practice", 9)

    def test_mapping_a_tagged_session_sticks(self):
        study.add_topic(self.c, "tlb", course="os")
        self.sync()
        lh.map_session(self.c, "chat_teach", 2)
        self.age(self.root / "chats" / "chat_teach.json", 1800)
        self.assertEqual(self.sync().sessions, 1)
        self.assertEqual(self.count("SELECT topic_id FROM lh_sessions WHERE chat_id='chat_teach'"), 2)
        self.assertEqual({r.topic_id for r in evidence.rows(self.c, source="lh-quiz")}, {2})

    def test_similar_chat_ids_stay_apart(self):
        self.put("chat_practice2.json", (FIXTURES / "practice.json").read_text()
                 .replace('"id": "chat_practice"', '"id": "chat_practice2"'))
        self.sync()
        lh.map_session(self.c, "chat_practice", 1)
        topics = {r.ref.split("/")[0]: r.topic_id for r in evidence.rows(self.c, source="lh-practice")}
        self.assertEqual(topics, {"chat_practice": 1, "chat_practice2": None})

    def test_tag_to_missing_topic(self):
        self.put("chat_teach.json", (FIXTURES / "teach.json").read_text().replace("[pm:topic=1]", "[pm:topic=99]"))
        self.sync()
        self.assertEqual(self.count("SELECT count(*) FROM lh_sessions WHERE chat_id='chat_teach' AND topic_id IS NULL"
                                    " AND tagged=0"), 1)

    def test_sessions_and_minutes(self):
        self.sync()
        listed = lh.sessions(self.c)
        self.assertEqual([s.chat_id for s in listed], ["chat_practice", "chat_teach"])
        self.assertEqual(listed[1].topic_id, 1)
        self.assertTrue(listed[1].tagged)
        total = sum(s.minutes for s in listed)
        self.assertEqual(sum(lh.minutes_by_day(self.c).values()), total)
        self.assertEqual(listed[1].minutes, 4)

    def test_read_only(self):
        self.put("flashcards.json", (FIXTURES / "flashcards.json").read_text(), folder="core-plugin-data/flashcards")

        def snapshot():
            return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*")
                    if p.is_file()}
        before = snapshot()
        self.sync()
        self.assertEqual(snapshot(), before)


class TestOpening(LhCase):
    def test_full(self):
        self.c.execute("UPDATE topics SET exam_date=? WHERE id=1", ((NOW.date() + timedelta(days=11)).isoformat(),))
        notes = Path(self.tmp.name) / "paging.md"
        notes.write_text("# Paging\n\n## TLB\n")
        study.track_file(self.c, 1, notes)
        study.add_item(self.c, 1, notes, "Paging#TLB", now=NOW)
        evidence.add(self.c, source="lh-quiz", ref="chat_x/m1/c1", ts=NOW, topic_id=1, correct=False,
                     confidence=0.9, grader="code", facet="understanding", label=f"{notes}#TLB")
        text = lh.opening(self.c, 1, NOW)
        lines = text.split("\n")
        self.assertEqual(lines[0], '[pm:topic=1] I want to study "paging" (course: os).')
        self.assertEqual(lines[1], f"My exam is on {NOW.date() + timedelta(days=11)}, in 11 days.")
        self.assertTrue(lines[2].startswith("From my planner: mastery "), lines[2])
        self.assertIn("no practice yet.", lines[2])
        self.assertIn("- paging.md#TLB (I said 90%)", lines)
        self.assertIn(f"- {notes}", lines)
        self.assertEqual(lines[-1], "Please check what I already know first, then teach what is missing.")
        self.assertEqual(TAG.search(text)[1], "1")

    def test_bare(self):
        self.assertEqual(lh.opening(self.c, 1, NOW).split("\n"), [
            '[pm:topic=1] I want to study "paging" (course: os).', "From my planner: nothing recorded yet.",
            "Please check what I already know first, then teach what is missing."])
        self.assertTrue(lh.opening(self.c, 1, NOW, practice=True).endswith(
            "Please give me exam-style practice problems on this topic."))
        with self.assertRaises(LookupError):
            lh.opening(self.c, 9, NOW)


class TestPlugin(LhCase):
    def setUp(self):
        super().setUp()
        put_setting(self.c, "lh_dir", str(self.root))
        self.dist = self.root / "plugins" / "pm-bridge" / "dist"

    def files(self):
        return {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_status(self):
        self.assertEqual(lh.plugin_status(self.c), "missing")
        lh.install_plugin(self.c)
        self.assertEqual(lh.plugin_status(self.c), "ok")
        manifest = self.dist / "manifest.json"
        data = json.loads(manifest.read_text())
        manifest.write_text(json.dumps({**data, "version": "0.0.1"}))
        self.assertEqual(lh.plugin_status(self.c), "old")
        manifest.write_text("{not json")
        self.assertEqual(lh.plugin_status(self.c), "missing")
        put_setting(self.c, "lh_dir", "")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name}):
            self.assertEqual(lh.plugin_status(self.c), "no-app")
            with self.assertRaisesRegex(ValueError, "^LearnHarness data not found"):
                lh.install_plugin(self.c)

    def test_install_touches_only_its_two_files(self):
        sibling = self.root / "plugins" / "pm-bridge" / "data" / "x.json"
        sibling.parent.mkdir(parents=True)
        sibling.write_text('{"keep": 1}')
        before = self.files()
        self.assertEqual(lh.install_plugin(self.c), (self.root / "plugins" / "pm-bridge", False))
        after = self.files()
        for name in lh.PLUGIN_FILES:
            self.assertEqual(after.pop(self.dist / name), (lh.plugin_source() / name).read_bytes())
        self.assertEqual(after, before)
        self.assertEqual(lh.install_plugin(self.c)[1], True)
        self.assertEqual(set(self.files()) - set(before), {self.dist / n for n in lh.PLUGIN_FILES})

    def test_another_plugin(self):
        self.dist.mkdir(parents=True)
        (self.dist / "manifest.json").write_text('{"id": "other"}')
        with self.assertRaisesRegex(ValueError, "^another plugin is installed in that folder$"):
            lh.install_plugin(self.c)
        self.assertEqual((self.dist / "manifest.json").read_text(), '{"id": "other"}')
        self.assertFalse((self.dist / "backend.cjs").exists())

    def test_planted_temp_symlink(self):
        target = Path(self.tmp.name) / "target"
        target.write_text("keep")
        self.dist.mkdir(parents=True)
        (self.dist / ".manifest.json.pm-tmp").symlink_to(target)
        lh.install_plugin(self.c)
        self.assertEqual(target.read_text(), "keep")
        self.assertEqual(lh.plugin_status(self.c), "ok")

    def test_symlink_refused(self):
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (self.root / "plugins").mkdir()
        (self.root / "plugins" / "pm-bridge").symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, "symlink"):
            lh.install_plugin(self.c)
        self.assertEqual(list(elsewhere.iterdir()), [])


class TestCards(LhCase):
    def put_cards(self, text=None):
        return self.put("flashcards.json", text or (FIXTURES / "flashcards.json").read_text(),
                        folder="core-plugin-data/flashcards")

    def test_read_cards(self):
        cards = lh.read_cards(fixture("flashcards"))
        self.assertEqual(len(cards), 4)
        chats = {c[0]: c[1] for c in cards}
        self.assertEqual(chats, {"p_review": "chat_teach", "p_new": "chat_teach", "p_learn": "chat_teach",
                                 "p_hand": None})
        review = next(c for c in cards if c[0] == "p_review")
        self.assertEqual(review[3:6], (2, 10.0, NOW - timedelta(days=10)))
        self.assertIsNone(review[5].tzinfo)

    def test_unsupported(self):
        for bad in ({"version": 2, "propositions": {}, "decks": []}, {"version": 1},
                    {"version": 1, "propositions": [], "decks": []}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "^unsupported format$"):
                lh.read_cards(bad)
        data = fixture("flashcards")
        del data["propositions"]["p_hand"]["schedule"]
        self.assertEqual(len(lh.read_cards(data)), 3)

    def test_sync_cards(self):
        self.put_cards()
        out = self.sync()
        self.assertEqual(out.cards, 4)
        self.assertEqual(self.count("SELECT count(*) FROM lh_cards WHERE topic_id=1"), 3)
        self.assertEqual(self.sync().cards, 0)
        self.put_cards('{"version": 3}')
        self.put("chat_new.json", '{"id": "chat_new", "messages": []}')
        out = self.sync()
        self.assertEqual(out.skipped, ["flashcards: unsupported format (skipped)"])
        self.assertEqual(out.sessions, 1)
        self.assertEqual(self.count("SELECT count(*) FROM lh_cards"), 4)

    def test_unchanged_card_file_is_not_reread(self):
        self.put_cards()
        self.sync()
        with mock.patch("pm.lh.read_cards") as read:
            self.sync()
        read.assert_not_called()
        self.age(self.root / "core-plugin-data/flashcards/flashcards.json", 1800)
        self.assertEqual(self.sync().cards, 0)  # reread, nothing changed inside

    def test_cards_follow_a_session_that_gains_its_topic(self):
        self.put("chat_teach.json", (FIXTURES / "teach.json").read_text().replace("[pm:topic=1]", "[pm:topic=2]"))
        self.put_cards()
        self.sync()
        self.assertEqual(self.count("SELECT count(*) FROM lh_cards WHERE topic_id IS NOT NULL"), 0)
        study.add_topic(self.c, "tlb", course="os")
        self.age(self.root / "chats" / "chat_teach.json", 1800)
        self.sync()
        self.assertEqual(self.count("SELECT count(*) FROM lh_cards WHERE topic_id=2"), 3)

    def test_bad_stability(self):
        data = fixture("flashcards")
        data["propositions"]["p_review"]["schedule"]["stability"] = 10**400
        data["propositions"]["p_learn"]["schedule"]["stability"] = float("inf")
        self.assertEqual({c[0] for c in lh.read_cards(data)}, {"p_new", "p_hand"})

    def test_no_card_file(self):
        self.assertEqual(self.sync().cards, 0)

    def test_cards_ready(self):
        self.put_cards()
        self.sync()
        self.assertEqual(lh.cards_ready(self.c, NOW), 1)
        self.assertEqual(lh.cards_ready(self.c, NOW - timedelta(days=2)), 0)

    def test_memory(self):
        self.put_cards()
        self.sync()
        values = study.memory_values(self.c, 1, NOW)
        self.assertEqual(len(values), 2)  # the review card and the learning card; the new card adds none
        self.assertAlmostEqual(max(values), 0.9, places=2)
        self.assertEqual(study.facets(self.c, 1, NOW).memory.n, 2)


if __name__ == "__main__":
    unittest.main()
