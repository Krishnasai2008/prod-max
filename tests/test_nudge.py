import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from unittest import mock

from pm.db import connect, get_setting
from pm.nudge import due, send
from pm.risk import TaskRisk
from pm.tasks import Task, add_task, start

NOW = datetime(2026, 11, 9, 10, 0)
DUE = date(2026, 11, 12)


def os_lab(ident=3):
    return Task(ident, "OS lab 3", None, "lab", 120, DUE, "deep", None, None, 0, False)


class TestDue(unittest.TestCase):
    def setUp(self):
        self.c = connect(":memory:")

    def tearDown(self):
        self.c.close()

    def test_one_nudge_per_task_per_day(self):
        messages = due(self.c, NOW, [os_lab()], [TaskRisk(3, 0.42, NOW.date(), False)])
        self.assertEqual(messages, ["start #3 OS lab 3 today: 42% late risk, due 2026-11-12"])
        self.assertEqual(due(self.c, NOW, [os_lab()], [TaskRisk(3, 0.42, NOW.date(), False)]), [])
        tomorrow = NOW + timedelta(days=1)
        self.assertEqual(len(due(self.c, tomorrow, [os_lab()],
                                 [TaskRisk(3, 0.42, tomorrow.date(), False)])), 1)

    def test_worked_on_today_is_silent(self):
        task_id = add_task(self.c, "OS lab 3", 120, now=NOW, due=DUE, kind="lab")
        start(self.c, task_id, NOW)
        self.assertEqual(due(self.c, NOW, [os_lab(task_id)],
                             [TaskRisk(task_id, 0.42, NOW.date(), False)]), [])

    def test_overnight_session_is_silent(self):
        task_id = add_task(self.c, "OS lab 3", 120, now=NOW, due=DUE, kind="lab")
        start(self.c, task_id, NOW - timedelta(hours=12))
        self.assertEqual(due(self.c, NOW, [os_lab(task_id)],
                             [TaskRisk(task_id, 0.42, NOW.date(), False)]), [])

    def test_start_by_tomorrow_is_silent(self):
        self.assertEqual(due(self.c, NOW, [os_lab()],
                             [TaskRisk(3, 0.42, NOW.date() + timedelta(days=1), False)]), [])

    def test_outside_nudge_hours(self):
        late = NOW.replace(hour=23)
        self.assertEqual(due(self.c, late, [os_lab()],
                             [TaskRisk(3, 0.42, late.date(), False)]), [])

    def test_behind_wording(self):
        messages = due(self.c, NOW, [os_lab()], [TaskRisk(3, 0.42, NOW.date(), True)])
        self.assertEqual(messages, ["behind on #3 OS lab 3: 42% late risk, due 2026-11-12"])

    def test_records_the_day_as_json(self):
        due(self.c, NOW, [os_lab()], [TaskRisk(3, 0.42, NOW.date(), False)])
        self.assertEqual(json.loads(get_setting(self.c, "nudged", "{}")), {"3": "2026-11-09"})


class TestSend(unittest.TestCase):
    def test_missing_notify_send_only_logs(self):
        out = io.StringIO()
        with mock.patch("pm.nudge.shutil.which", return_value=None), \
                mock.patch("pm.nudge.subprocess.run") as run, redirect_stdout(out):
            send(["hello"])
        run.assert_not_called()
        self.assertEqual(out.getvalue(), "nudge: hello\n")

    def test_notify_send_arguments(self):
        with mock.patch("pm.nudge.shutil.which", return_value="/usr/bin/notify-send"), \
                mock.patch("pm.nudge.subprocess.run") as run, redirect_stdout(io.StringIO()):
            send(["hello"])
        run.assert_called_once_with(["/usr/bin/notify-send", "-a", "pm", "pm", "hello"])

    def test_subprocess_failure_is_ignored(self):
        out = io.StringIO()
        with mock.patch("pm.nudge.shutil.which", return_value="/usr/bin/notify-send"), \
                mock.patch("pm.nudge.subprocess.run", side_effect=OSError("no display")), \
                redirect_stdout(out):
            send(["hello"])
        self.assertEqual(out.getvalue(), "nudge: hello\n")
