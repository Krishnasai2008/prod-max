import argparse
import hashlib
import json
import os
import plistlib
import random
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

from pm.bugs import episodes as bug_episodes
from pm.bugs import get_episode, record_run, set_tags, summary
from pm.calibrate import PRIOR, median_ratio, posteriors
from pm import agent, bank, drafts, generators, lh, mock, practice, spot, suggest, templates, variants, versus
from pm.grade import number as read_number
from pm.db import SEEN, DEFAULTS, backup, connect, default_path, get_setting, put_setting, set_setting, settings
from pm.energy import by_hour, suggest as suggest_peak
from pm.excerpt import default_pick, excerpt, outline, split_spec
from pm.files import find as find_files
from pm.files import roots as watch_roots
from pm.llm import command as llm_command
from pm.inbox import BUSY, UNPUSHED, apply as apply_inbox
from pm.links import add_link, drop_link, get_link, links, open_links, short
from pm.llm import ask as llm_ask
from pm.risk import cap_min, forecast
from pm.snap import diff, snapshot
from pm.stats import fetch_inbox, push, summary_now
from pm.evidence import misses, short_label
from pm.study import (add_item, add_items, add_topic, calibration, calibration_sources, facets,
                      find_topic, gap, get_item, get_topic, ready_courses, track_file, untrack_file,
                      held, mastery, new_cap, next_topic, queue, rank, record_review, topic_counts,
                      topics, has_item, studyable, remove_item, rename_topic, suspend, topic_items)
from pm.tasks import (LONG_SESSION_MIN, add_task, done, drop_task, edit_task, finished_ratios,
                      get_task, last_note, log_time, open_tasks, running_task_id, start, stop,
                      closed_tasks, reopen, running_session)
from pm.today import plan_day
from pm.units import fmt_duration as d
from pm.units import parse_due, parse_duration
from pm.watch import loop, tick
from pm.web import PORT, serve

def _now() -> datetime:
    return datetime.fromisoformat(os.environ["PM_NOW"]) if os.environ.get("PM_NOW") else datetime.now()


def _duration(s: str) -> int:
    try:
        return parse_duration(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _due(s: str):
    try:
        return parse_due(s, _now().date())
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _positive(s: str) -> int:
    try:
        value = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def _plural(n: int, word: str) -> str:
    return word if n == 1 else word + "s"


def _marks(n: float) -> str:
    return f"{n:g} mark" if n == 1 else f"{n:g} marks"


def _full(path: str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise ValueError(str(e)) from None


def _read_lines(path: str) -> list[str]:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(str(e)) from None


def _mock_line(conn, m) -> str:
    status = m.status
    if status == "marked":
        r = mock.result(conn, m.id)
        status = f"marked {round(r.pct * 100)}%"
        if m.predicted is not None:
            status += f" (predicted {round(m.predicted * 100)}%)"
    n = len(mock.items(conn, m.id))
    return f"#{m.id}  {m.title}  {n} {'question' if n == 1 else 'questions'}  {status}"


def _mock_show(conn, mock_id: int) -> None:
    m = mock.get(conn, mock_id)
    r = mock.result(conn, mock_id)
    print(f"test #{m.id}  {m.title}")
    line = f"score {r.got:g} of {r.total:g} ({round(r.pct * 100)}%)"
    if r.predicted is not None:
        line += f"  predicted {round(r.predicted * 100)}%"
    print(line)
    if r.over_min:
        print(f"time: {d(r.over_min)} over")
    for topic_id, got, total in r.by_topic:
        name = get_topic(conn, topic_id).name if topic_id is not None else "-"
        print(f"  {name}  {got:g} of {total:g}")
    if r.said is not None:
        print(f"said {round(r.said * 100)}% on average, scored {round(r.pct * 100)}%")
    if r.unread:
        print(f"couldn't read your answer to: {', '.join(map(str, r.unread))}")
    if r.missed:
        print(f"missed: {', '.join(map(str, r.missed))} (pm mock retry {m.id})")


def _made(conn, mock_id: int) -> None:
    m = mock.get(conn, mock_id)
    n = len(mock.items(conn, mock_id))
    print(f"test #{m.id}: {n} {'question' if n == 1 else 'questions'}, {d(m.minutes)} (pm mock take {m.id})")


def _take(conn, mock_id: int, now) -> int:
    m = mock.get(conn, mock_id)
    if m.status in ("ready", "running"):
        mock.start(conn, mock_id, now)
        rows = mock.items(conn, mock_id)
        for item in rows:
            if (item.answer is not None and item.confidence is not None) or item.dont_know:  # no bet yet: ask again
                continue
            view = mock.view(conn, mock_id, item.pos)
            print(f"[{item.pos}/{len(rows)}] {view['topic'] or '-'}  {_marks(item.marks)}")
            print(view["prompt"])
            if view["void"]:
                continue
            if view["page"]:
                q = bank.get_question(conn, item.question_id)
                print(f"see page {q.locator[1:]} of {q.path.name}")
            for k, text in enumerate(view.get("options", [])):
                print(f"  {chr(ord('a') + k)}) {text}")
            try:
                answer = input("answer (blank = don't know, q quits): ").strip()
            except EOFError:
                answer = "q"
            if answer.lower() == "q":
                print(f"paused test #{mock_id} (pm mock take {mock_id})")
                return 0
            if not answer:
                mock.save(conn, mock_id, item.pos, dont_know=True)
                continue
            mock.save(conn, mock_id, item.pos, answer=answer)
            confidence = _ask_confidence()
            if confidence is None:
                print(f"paused test #{mock_id} (pm mock take {mock_id})")
                return 0
            mock.save(conn, mock_id, item.pos, confidence=confidence)
        mock.finish(conn, mock_id, now)
    if mock.get(conn, mock_id).status == "to mark":
        for item in mock.items(conn, mock_id):
            if item.score is not None or item.question_id is None:
                continue
            view = mock.view(conn, mock_id, item.pos)
            print(f"[{item.pos}] your answer:")
            print(item.answer or "")
            print("model answer:")
            print(view["key"] or "no model answer; check the paper's key")
            while True:
                try:
                    text = input(f"marks 0-{item.marks:g}: ").strip()
                except EOFError:
                    print(f"paused marking test #{mock_id} (pm mock take {mock_id})")
                    return 0
                try:
                    got = float(text)
                except ValueError:
                    continue
                if 0 <= got <= item.marks:
                    break
            mock.mark(conn, mock_id, item.pos, got, now)
    _mock_show(conn, mock_id)
    return 0


def _tilde(path: Path) -> str:
    home = str(Path.home())
    return "~" + str(path)[len(home):] if str(path).startswith(home + "/") else str(path)


def _where(topic) -> str:
    return f"{topic.course or '-'}/{topic.name}"


def _practise(conn, now, topic_id: int | None) -> int:
    rng = random.Random(now.isoformat())
    done = right = 0
    while True:
        served = practice.next_problem(conn, now, rng, topic_id)
        problem = served.problem
        print(f"{_where(get_topic(conn, served.topic_id))}  {problem.title}")
        print(problem.text)
        try:
            answer = input("answer (blank = don't know, q quits): ").strip()
        except EOFError:
            print()
            answer = "q"
        if answer.lower() == "q":
            break
        confidence = None
        if answer:
            confidence = _ask_confidence()
            if confidence is None:
                break
        now = _now()
        verdict = practice.submit(conn, topic_id=served.topic_id, gen=problem.gen, seed=problem.seed,
                                  variant=problem.variant, answer=answer, confidence=confidence,
                                  dont_know=not answer, seconds=None, now=now)
        done += 1
        right += verdict.correct
        if not answer:
            print(f"the answer is {verdict.key}")
        elif verdict.correct:
            print("right")
        else:
            if not verdict.readable:
                print("couldn't read your answer" + (" as a number" if problem.kind == "number" else ""))
            print(f"wrong: the answer is {verdict.key}")
        print(verdict.steps)
        print()
    print(f"practised {done}, {right} right" if done else "practised 0")
    return 0


def _energy_arg(s: str) -> int:
    try:
        value = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("energy must be 1-5") from None
    if not 1 <= value <= 5:
        raise argparse.ArgumentTypeError("energy must be 1-5")
    return value


def _ask_line(count: int) -> int | None:
    while True:
        try:
            answer = input("which line is wrong? (q quits): ").strip()
        except EOFError:
            print()
            return None
        if answer.lower() == "q":
            return None
        try:
            value = int(answer)
        except ValueError:
            continue
        if 1 <= value <= count:
            return value


class _ModelError(ValueError):
    """The model command itself failed: stop making cards rather than blaming each item."""


def _port(s: str) -> int:
    try:
        value = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a port between 1024 and 65535") from None
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError("expected a port between 1024 and 65535")
    return value


def _ping(url: str) -> bool:
    try:
        with urlopen(f"{url}/api/ping", timeout=2) as response:
            return json.loads(response.read()) == {"pm": True}
    except (OSError, ValueError):
        return False


def _ask_confidence() -> float | None:
    while True:
        try:
            answer = input("confidence 0-100 (q quits): ").strip()
        except EOFError:
            print()
            return None
        if answer.lower() == "q":
            return None
        if answer.endswith("%"):
            answer = answer[:-1].strip()
        try:
            value = int(answer)
        except ValueError:
            continue
        if 0 <= value <= 100:
            return value / 100


def _ask_grade() -> int | None:
    while True:
        try:
            answer = input("grade 1 again, 2 hard, 3 good, 4 easy: ").strip()
        except EOFError:
            print()
            return None
        if answer.lower() == "q":
            return None
        try:
            value = int(answer)
        except ValueError:
            continue
        if 1 <= value <= 4:
            return value


def _fails(n: int) -> str:
    return f"{n} fail" if n == 1 else f"{n} fails"


def _netrc_path() -> Path | None:
    return Path(os.environ["PM_NETRC"]) if os.environ.get("PM_NETRC") else None


def _install_unit(name: str, description: str, command: str) -> None:
    pm = shutil.which("pm")
    if pm is None:
        raise ValueError("install pm first: uv tool install --editable .")
    if sys.platform == "darwin":
        path = Path.home() / f"Library/LaunchAgents/dev.prod-max.{name}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            # launchd starts with a bare PATH: keep this one, so Homebrew's pdftotext and llm_cmd are found
            plistlib.dump({"Label": f"dev.prod-max.{name}", "ProgramArguments": [pm, *command.split()],
                           "RunAtLoad": True, "KeepAlive": True,
                           "EnvironmentVariables": {"PATH": os.environ.get("PATH", "")}}, f)
        print(f"wrote {path}")
        print(f"start it: launchctl load -w {path}")
        return
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / f"systemd/user/{name}.service"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Unit]\n"
        f"Description={description}\n\n"
        "[Service]\n"
        f"ExecStart={pm} {command}\n"
        "Restart=on-failure\n"
        "RestartSec=30\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    print(f"wrote {path}")
    print(f"start it: systemctl --user daemon-reload && systemctl --user enable --now {name}")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pm", description="Planner that learns how long things really take.")
    sub = p.add_subparsers(dest="cmd")  # no command: today
    a = sub.add_parser("add", help="add a task")
    a.add_argument("title")
    a.add_argument("--est", type=_duration, required=True, help="estimate: 90m, 4h, 1h30m")
    a.add_argument("--due", type=_due, help="YYYY-MM-DD, +N days, or a weekday like fri")
    a.add_argument("--course")
    a.add_argument("--kind", default="task", help="lab, exam, pset, ... (bias is learned per kind)")
    a.add_argument("--shallow", action="store_true", help="low-focus work (default: deep)")
    a.add_argument("--first", help="a tiny first step, shown when you start")
    e = sub.add_parser("edit", help="change a task")
    e.add_argument("id", type=int)
    e.add_argument("--title")
    e.add_argument("--est", type=_duration, help="estimate: 90m, 4h, 1h30m")
    due = e.add_mutually_exclusive_group()
    due.add_argument("--due", type=_due, help="YYYY-MM-DD or +N days")
    due.add_argument("--no-due", action="store_true", help="remove the due date")
    e.add_argument("--course")
    e.add_argument("--kind")
    energy = e.add_mutually_exclusive_group()
    energy.add_argument("--deep", action="store_true", help="high-focus work (default)")
    energy.add_argument("--shallow", action="store_true", help="low-focus work")
    e.add_argument("--first", help="a tiny first step, shown when you start")
    lk = sub.add_parser("link", help="files and pages to open when you start a task")
    lk.add_argument("id", type=int)
    choose = lk.add_mutually_exclusive_group()
    choose.add_argument("target", nargs="?", help="a full path or an http(s) address")
    choose.add_argument("--rm", type=_positive, metavar="N", help="remove link number N")
    sub.add_parser("drop", help="drop a task").add_argument("id", type=int)
    stt = sub.add_parser("start", help="start the timer on a task")
    stt.add_argument("id", type=int)
    stt.add_argument("--no-open", action="store_true", help="don't open the task's links")
    s = sub.add_parser("stop", help="stop the timer")
    s.add_argument("note", nargs="?", help="where you left off")
    s.add_argument("--as", dest="as_min", type=_duration, help="record this length instead")
    s.add_argument("--energy", type=_energy_arg, help="how your energy was, 1-5")
    lg = sub.add_parser("log", help="log time after the fact")
    lg.add_argument("id", type=int)
    lg.add_argument("duration", type=_duration)
    sub.add_parser("done", help="finish a task").add_argument("id", type=int)
    sub.add_parser("ls", help="open tasks").add_argument("--done", action="store_true",
                                                         help="the last 20 finished or dropped tasks")
    sub.add_parser("reopen", help="undo done or drop").add_argument("id", type=int)
    sub.add_parser("backup", help="copy the database to a file (safe while pm is running)").add_argument(
        "file", nargs="?", help="default: a dated file in the backups folder next to the database")
    sub.add_parser("doctor", help="check the daemon, the optional programs and the settings")
    sub.add_parser("risk", help="chance each task is late, and when to start")
    sub.add_parser("bias", help="how far off your estimates are")
    sub.add_parser("energy", help="your energy by hour, and a peak-hours suggestion")
    sub.add_parser("today", help="what to work on today")
    st = sub.add_parser("set", help="show the settings, or change one: pm set KEY VALUE")
    st.add_argument("key", nargs="?", help=", ".join(DEFAULTS))
    st.add_argument("value", nargs="?")
    tp = sub.add_parser("topic", help="study topics")
    tsub = tp.add_subparsers(dest="topic_cmd", required=True)
    ta = tsub.add_parser("add", help="add a topic")
    ta.add_argument("name")
    ta.add_argument("--course", default="")
    ta.add_argument("--exam", type=_due, help="YYYY-MM-DD or +N days")
    ta.add_argument("--weight", type=float, default=1.0)
    ta.add_argument("--needs", action="append", default=[], metavar="NAME")
    tsub.add_parser("ls", help="topics with mastery")
    tr = tsub.add_parser("rename", help="give a topic a new name")
    tr.add_argument("name")
    tr.add_argument("new")
    tr.add_argument("--course")
    tf = tsub.add_parser("file", help="count a file toward a topic's coverage")
    tf.add_argument("name")
    tf.add_argument("path")
    tf.add_argument("--course")
    tf.add_argument("--rm", action="store_true", help="stop counting it")
    sd = sub.add_parser("study", help="study items and excerpts")
    ssub = sd.add_subparsers(dest="study_cmd", required=True)
    sa = ssub.add_parser("add", help="add an item to study")
    sa.add_argument("spec", help="path or path#locator")
    sa.add_argument("--topic", required=True)
    sa.add_argument("--course")
    sa.add_argument("--prompt")
    sa.add_argument("--all", action="store_true", help="add every section of a file")
    sl = ssub.add_parser("ls", help="a topic's items, with their numbers")
    sl.add_argument("name")
    sl.add_argument("--course")
    ssub.add_parser("rm", help="remove an item added by mistake (one with reviews is suspended instead)"
                    ).add_argument("id", type=int)
    ssub.add_parser("suspend", help="take an item out of reviews").add_argument("id", type=int)
    ssub.add_parser("resume", help="put a suspended item back").add_argument("id", type=int)
    ssub.add_parser("next", help="what to study next")
    ssub.add_parser("calib", help="confidence calibration")
    sw = ssub.add_parser("why", help="what a topic's mastery is made of")
    sw.add_argument("name")
    sw.add_argument("--course")
    ssub.add_parser("misses", help="confident mistakes")
    ssub.add_parser("ready", help="readiness per course with an exam ahead")
    rv = sub.add_parser("review", help="review due items")
    rv.add_argument("--limit", type=_positive, default=20)
    sp = sub.add_parser("spot", help="spot-the-error cards made from your notes")
    sp.add_argument("--make", type=_positive, metavar="N", help="make up to N new cards with llm_cmd")
    rn = sub.add_parser("run", help="run a command and log failures (pm run -- make test)")
    rn.add_argument("argv", nargs=argparse.REMAINDER)
    sub.add_parser("bugs", help="bug counts, tags and time lost")
    bg = sub.add_parser("bug", help="show a bug, or replace its tags")
    bg.add_argument("id", type=int)
    bg.add_argument("tags", nargs="*")
    ss = sub.add_parser("stats", help="everything pm knows, as JSON")
    ss.add_argument("--push", action="store_true", help="send it to the notes site")
    sub.add_parser("inbox", help="apply what was captured on the phone")
    vs = sub.add_parser("versus", help="the study scoreboard against your friends")
    vs.add_argument("--sync", action="store_true", help="send your numbers and fetch everyone's first")
    fd = sub.add_parser("find", help="search the file index")
    fd.add_argument("words", nargs="+", metavar="WORDS")
    fd.add_argument("--course")
    w = sub.add_parser("watch", help="index watched folders, nudge and push in the background")
    wg = w.add_mutually_exclusive_group()
    wg.add_argument("--once", action="store_true", help="run one tick now")
    wg.add_argument("--install", action="store_true", help="write the systemd user unit")
    u = sub.add_parser("ui", help="open the local planner page")
    u.add_argument("--port", type=_port, default=PORT, help="port to listen on (default 8321)")
    u.add_argument("--no-open", action="store_true", help="don't open the browser")
    u.add_argument("--install", action="store_true", help="write the systemd user unit")
    sub.add_parser("llm", help="ask the llm command").add_argument("words", nargs="+", metavar="WORDS")
    q = sub.add_parser("q", help="the question bank")
    qsub = q.add_subparsers(dest="q_cmd", required=True)
    qa = qsub.add_parser("add", help="add a question by hand")
    qa.add_argument("prompt")
    qa.add_argument("--topic", required=True)
    qa.add_argument("--course")
    qa.add_argument("--marks", type=float, default=1.0)
    key = qa.add_mutually_exclusive_group()
    key.add_argument("--answer", help="a model answer (an open question)")
    key.add_argument("--number", help="the right number")
    key.add_argument("--choice", help='the options, ";"-separated')
    qa.add_argument("--tol", help="how far off a number may be")
    qa.add_argument("--correct", help="the right options, like 2 or 1,3")
    qi = qsub.add_parser("import", help="questions from the answer sections of a note")
    qi.add_argument("file")
    qi.add_argument("--topic", required=True)
    qi.add_argument("--course")
    qsub.add_parser("ls", help="the questions").add_argument("--course")
    qr = qsub.add_parser("retire", help="take a question out of tests")
    qr.add_argument("id", type=int)
    qr.add_argument("reason", nargs="*")
    qsub.add_parser("restore", help="put a retired question back").add_argument("id", type=int)
    qsub.add_parser("review", help="questions whose key looks wrong, or that are too easy or too hard")
    qv = qsub.add_parser("vary", help="new questions like this one, written by the model and checked")
    qv.add_argument("id", type=int)
    qv.add_argument("-n", type=_positive, default=3)
    pp = sub.add_parser("paper", help="past papers")
    psub = pp.add_subparsers(dest="paper_cmd", required=True)
    pa = psub.add_parser("add", help="register a past paper")
    pa.add_argument("title")
    pa.add_argument("--course", required=True)
    pa.add_argument("--file", help="the paper's PDF")
    pa.add_argument("--minutes", type=_positive)
    pi = psub.add_parser("import", help="its questions, one line each")
    pi.add_argument("id", type=int)
    pi.add_argument("file")
    psub.add_parser("ls", help="the papers")
    psub.add_parser("draft", help="a model's list of the paper's questions, to edit and import").add_argument(
        "id", type=int)
    mk = sub.add_parser("mock", help="timed mock tests")
    msub = mk.add_subparsers(dest="mock_cmd", required=True)
    mn = msub.add_parser("new", help="build a test")
    mn.add_argument("--course")
    mn.add_argument("-n", type=int, default=10)
    mn.add_argument("--minutes", type=int)
    mn.add_argument("--paper", type=int)
    msub.add_parser("take", help="sit (or resume) a test").add_argument("id", type=int, nargs="?")
    msub.add_parser("ls", help="the tests")
    msub.add_parser("show", help="a marked test's result").add_argument("id", type=int)
    msub.add_parser("retry", help="a new test from the missed questions").add_argument("id", type=int)
    pr = sub.add_parser("practice", help="generated problems, checked by code")
    pr.add_argument("words", nargs="*", metavar="TOPIC | link GEN | unlink GEN | gens")
    pr.add_argument("--topic")
    pr.add_argument("--course")
    le = sub.add_parser("learn", help="the first message for a LearnHarness session on a topic")
    le.add_argument("topic")
    le.add_argument("--course")
    le.add_argument("--practice", action="store_true", help="ask for practice problems instead of teaching")
    le.add_argument("--copy", action="store_true", help="also copy it to the clipboard")
    lp = sub.add_parser("lh", help="LearnHarness sessions (read only)")
    lsub = lp.add_subparsers(dest="lh_cmd", required=True)
    lsub.add_parser("sync", help="read new sessions and cards")
    lsub.add_parser("ls", help="the sessions read so far")
    lsub.add_parser("install", help="put the pm plugin where LearnHarness finds it")
    lm = lsub.add_parser("map", help="give a session a topic")
    lm.add_argument("chat")
    lm.add_argument("topic", nargs="?")
    lm.add_argument("--course")
    lm.add_argument("--none", action="store_true", help="take its topic away")
    sg = sub.add_parser("suggest", help="the model's suggestions, applied only when you accept one")
    sg.add_argument("action", nargs="?", choices=("accept", "reject"))
    sg.add_argument("id", nargs="?", type=int)
    ag = sub.add_parser("agent", help="background model jobs, under a daily call budget")
    asub = ag.add_subparsers(dest="agent_cmd", required=True)
    aa = asub.add_parser("add", help="queue a job")
    aa.add_argument("kind")
    aa.add_argument("arg", nargs="?", default="")
    asub.add_parser("ls", help="recent jobs and today's budget")
    asub.add_parser("run", help="run queued jobs now").add_argument("--limit", type=_positive)
    tp = sub.add_parser("template", help="formula templates")
    tsub = tp.add_subparsers(dest="template_cmd", required=True)
    tsub.add_parser("check", help="check a template file").add_argument("file")
    tsub.add_parser("dir", help="the templates folder")
    tsub.add_parser("ls", help="the loaded templates")
    tsub.add_parser("draft", help="a model's template drafted from a numeric question").add_argument(
        "question", type=int)
    tsub.add_parser("approve", help="check a draft and put it to use").add_argument("name")
    return p


def _run(args, conn, now) -> int:
    match args.cmd:
        case "add":
            tid = add_task(conn, args.title, args.est, now=now, course=args.course, kind=args.kind,
                           due=args.due, energy="shallow" if args.shallow else "deep", first_step=args.first)
            print(f"added #{tid}")
            if args.due and args.due < now.date():
                print(f"note: {args.due} is already past")
        case "edit":
            clear = []
            if args.no_due:
                clear.append("due")
            if args.course == "":
                clear.append("course")
            if args.first == "":
                clear.append("first_step")
            energy = "shallow" if args.shallow else "deep" if args.deep else None
            t = edit_task(conn, args.id, now, title=args.title,
                          course=args.course if args.course != "" else None, kind=args.kind,
                          due=args.due, energy=energy,
                          first_step=args.first if args.first != "" else None, est_min=args.est,
                          clear=tuple(clear))
            print(f"edited #{t.id}")
        case "link":
            get_task(conn, args.id, now)
            if args.rm is not None:
                found = links(conn, args.id)
                if not 1 <= args.rm <= len(found):
                    raise ValueError(f"#{args.id} has no link {args.rm}")
                target = drop_link(conn, args.id, found[args.rm - 1].id)
                print(f"unlinked #{args.id}: {short(target)}")
            elif args.target is None:
                found = links(conn, args.id)
                if not found:
                    print(f"no links on #{args.id}")
                for n, link in enumerate(found, 1):
                    print(f"{n}  {short(link.target)}")
            else:
                target = args.target.strip()
                if not target:
                    raise ValueError("give a full path or an http(s) address")
                if not target.startswith(("http://", "https://")):
                    try:
                        path = Path(target).expanduser()
                        target = str(path if path.is_absolute() else Path.cwd() / path)
                    except (OSError, RuntimeError) as e:
                        raise ValueError(str(e)) from None
                link_id = add_link(conn, args.id, target, now)
                print(f"linked #{args.id}: {short(get_link(conn, args.id, link_id).target)}")
        case "drop":
            t = drop_task(conn, args.id, now)
            print(f"dropped #{t.id}")
        case "start":
            before = running_session(conn)
            t = start(conn, args.id, now)
            if before is not None and before[0] != t.id:
                print(f"stopped #{before[0]} after {d(max(0, int((now - before[1]).total_seconds() // 60)))}")
            print(f"started #{t.id} {t.title}")
            if t.first_step:
                print(f"first step: {t.first_step}")
            if note := last_note(conn, t.id):
                print(f"where you left off: {note}")
            if args.no_open:
                found = links(conn, t.id)
                if found:
                    print("links:")
                    for link in found:
                        print(f"  {short(link.target)}")
            else:
                opened, skipped = open_links(conn, t.id)
                if opened:
                    print(f"opened {opened} link" + ("s" if opened != 1 else ""))
                for message in skipped:
                    print(f"skipped: {message}")
        case "stop":
            res = stop(conn, now, note=args.note, minutes=args.as_min, energy=args.energy)
            if res is None:
                print("nothing running")
                return 1
            t, mins = res
            print(f"stopped #{t.id} after {d(mins)}")
            if mins > LONG_SESSION_MIN and args.as_min is None:
                print(f"warning: that ran {d(mins)}; fix it with pm stop --as next time, or pm log")
            if args.energy is not None:
                print(f"energy {args.energy}")
        case "log":
            log_time(conn, args.id, args.duration, now)
            print(f"logged {d(args.duration)} on #{args.id}")
        case "done":
            t = done(conn, args.id, now)
            print(f"done #{t.id}: {d(t.logged_min)} logged, estimated {d(t.est_min)}")
        case "ls" if args.done:
            closed = closed_tasks(conn)
            if not closed:
                print("nothing finished yet")
            for t in closed:
                print(f"#{t.id}  {t.title}  {'dropped' if t.dropped else 'done'} {t.done_at:%Y-%m-%d}"
                      f"  est {d(t.est_min)}  logged {d(t.logged_min)}")
        case "reopen":
            t = reopen(conn, args.id, now)
            print(f"reopened #{t.id} {t.title}")
        case "backup":
            dest = (_full(args.file) if args.file
                    else default_path().parent / "backups" / f"pm-{now:%Y%m%d-%H%M%S}.db")
            backup(conn, dest)
            print(f"saved {dest}")
        case "doctor":
            _doctor(conn, now)
        case "ls":
            tasks = open_tasks(conn, now)
            if not tasks:
                print("no open tasks")
            for t in tasks:
                print(f"#{t.id}  {t.title}  [{t.kind}/{t.course or '-'}]  due {t.due or '-'}"
                      f"  est {d(t.est_min)}  logged {d(t.logged_min)}" + ("  ▶" if t.running else ""))
        case "risk":
            tasks, _, risks, crunch = forecast(conn, now)
            if not risks:
                print("nothing with a due date")
                return 0
            by_id = {t.id: t for t in tasks}
            for r in risks:
                t = by_id[r.task_id]
                print(f"#{t.id}  {t.title}  due {t.due}  late {round(r.p_late * 100)}%  start by {r.start_by}"
                      + ("  BEHIND" if r.behind else ""))
            print(f"crunch risk {round(crunch * 100)}%  start the queue by {min(r.start_by for r in risks)}")
        case "bias":
            post = posteriors(finished_ratios(conn))
            if post["*"].n == 0:
                print(f"no finished tasks yet (assuming x{median_ratio(PRIOR):.2f})")
                return 0
            for kind, p in post.items():
                print(f"{'all' if kind == '*' else kind}  n={p.n}  median x{median_ratio(p):.2f}")
        case "energy":
            hours = by_hour(conn)
            if not hours:
                print("no rated sessions yet (pm stop --energy 1-5)")
                return 0
            for hour, (mean, minutes) in hours.items():
                print(f"{hour:02d}-{(hour + 1) % 24:02d}  {mean:.1f}  ({d(round(minutes))})")
            peak = get_setting(conn, "peak", DEFAULTS["peak"])
            best = suggest_peak(conn)
            if best is None:
                print("not enough ratings yet for a suggestion")
            elif best == peak:
                print(f"your peak setting matches ({peak})")
            else:
                print(f"suggested peak {best} (now {peak}): pm set peak {best}")
        case "today":
            tasks, post, risks, _ = forecast(conn, now)
            plan = plan_day(tasks, {r.task_id: r for r in risks}, post, cap_min(conn))
            if not plan:
                print("nothing to do")
            peak = get_setting(conn, "peak", DEFAULTS["peak"])
            for energy, header in (("deep", f"Deep work (peak {peak}):"), ("shallow", "Shallow:")):
                items = [(t, m) for t, m in plan if t.energy == energy]
                if items:
                    print(header)
                for t, m in items:
                    print(f"  #{t.id} {t.title}  ~{d(m)}" + (f"  first step: {t.first_step}" if t.first_step else ""))
        case "set" if args.value is None:
            current = settings(conn)
            if args.key is not None and args.key not in current:
                raise ValueError(f"unknown setting '{args.key}' (known: {', '.join(current)})")
            for key, value in current.items():
                if args.key in (None, key):
                    print(f"{key} = {value}")
        case "set":
            put_setting(conn, args.key, args.value)
            print(f"{args.key} = {args.value}")
            if args.key == "watch":
                for root in watch_roots(conn):
                    if not root.is_dir():
                        print(f"note: {root} isn't a folder (yet), so nothing is indexed from it")
        case "topic":
            match args.topic_cmd:
                case "add":
                    tid = add_topic(conn, args.name, course=args.course, exam_date=args.exam,
                                    weight=args.weight, needs=args.needs)
                    print(f"topic #{tid} {args.name}")
                case "rename":
                    topic = rename_topic(conn, find_topic(conn, args.name, args.course).id, args.new)
                    print(f"topic #{topic.id} is now {topic.name}")
                case "ls":
                    all_topics = topics(conn)
                    if not all_topics:
                        print("no topics")
                    counts = topic_counts(conn, now)
                    for topic in all_topics:
                        count = counts[topic.id][0]
                        line = (f"#{topic.id}  {topic.course or '-'}/{topic.name}"
                                f"  exam {topic.exam_date or '-'}  weight {topic.weight:g}"
                                f"  mastery {round(mastery(conn, topic.id, now) * 100)}%  items {count}")
                        if topic.prereqs:
                            names = ", ".join(get_topic(conn, pid).name for pid in topic.prereqs)
                            line += f"  needs {names}"
                        print(line)
                case "file":
                    topic = find_topic(conn, args.name, args.course)
                    try:
                        path = Path(args.path).expanduser().resolve()
                    except (OSError, RuntimeError) as e:
                        raise ValueError(str(e)) from None
                    shown = short(str(path))
                    if args.rm:
                        untrack_file(conn, topic.id, path)
                        print(f"stopped tracking {shown} for {topic.name}")
                    else:
                        if not path.is_file():
                            raise ValueError(f"no such file: {shown}")
                        n = track_file(conn, topic.id, path)
                        print(f"tracking {shown} for {topic.name} "
                              + ("(sections unknown)" if n is None else f"({n} {_plural(n, 'section')})"))
        case "study":
            match args.study_cmd:
                case "add":
                    path, locator = split_spec(args.spec)
                    if args.all:
                        if locator is not None:
                            raise ValueError("--all takes a file, not file#part")
                        if args.prompt is not None:
                            raise ValueError("--prompt needs a single item")
                        try:
                            sections = default_pick(outline(path))
                        except (OSError, ValueError) as e:
                            raise ValueError(str(e)) from None
                        topic = find_topic(conn, args.topic, args.course)
                        added, skipped = add_items(
                            conn, topic.id, path, [s.locator for s in sections], now=now)
                        if not added:
                            print("nothing to add")
                        else:
                            tail = f" ({skipped} already there)" if skipped else ""
                            noun = "item" if added == 1 else "items"
                            print(f"added {added} {noun} to {topic.name}{tail}")
                    else:
                        try:
                            excerpt(path, locator)
                        except (OSError, ValueError) as e:
                            raise ValueError(str(e)) from None
                        topic = find_topic(conn, args.topic, args.course)
                        if has_item(conn, topic.id, path, locator, args.prompt):
                            raise ValueError(f"that item is already in {topic.name}")
                        item_id = add_item(conn, topic.id, path, locator, now=now, prompt=args.prompt)
                        print(f"item #{item_id} added to {topic.name}, due now")
                case "ls":
                    topic = find_topic(conn, args.name, args.course)
                    found = topic_items(conn, topic.id)
                    if not found:
                        print(f"no items in {topic.name}")
                    for item in found:
                        where = item.path.name + (f"#{item.locator}" if item.locator else "")
                        print(f"#{item.id}  {item.prompt or where}" + ("  (suspended)" if item.suspended else ""))
                case "rm":
                    if remove_item(conn, args.id):
                        print(f"removed item #{args.id}")
                    else:
                        print(f"item #{args.id} has answers on record, so it is suspended instead"
                              f" (pm study resume {args.id})")
                case "suspend" | "resume":
                    suspend(conn, args.id, args.study_cmd == "suspend")
                    print(f"item #{args.id} {'suspended' if args.study_cmd == 'suspend' else 'is back in reviews'}")
                case "next":
                    result = next_topic(conn, now)
                    if result is None:
                        print("no topics with an upcoming exam")
                        return 0
                    study_topic, unblocks = result
                    line = (f"study next: {study_topic.course or '-'}/{study_topic.name}"
                            f"  mastery {round(mastery(conn, study_topic.id, now) * 100)}%")
                    if unblocks is not None:
                        line += f"  (prerequisite of {unblocks.name})"
                    print(line)
                    if not studyable(conn, study_topic.id):
                        print(f"  nothing in it yet: pm study add FILE --topic {shlex.quote(study_topic.name)}")
                    print("ranking:")
                    for pick in rank(conn, now)[:5]:
                        print(f"  {pick.topic.course or '-'}/{pick.topic.name}  exam {pick.topic.exam_date}"
                              f"  mastery {round(pick.mastery * 100)}%  score {pick.score:.2f}")
                case "calib":
                    cal = calibration(conn)
                    if cal.n == 0:
                        print("no reviews yet")
                        return 0
                    sources = calibration_sources(conn)
                    what = "answers" if len(sources) > 1 else "reviews"
                    print(f"{what} {cal.n}  Brier {cal.brier:.3f}  (0 is perfect, 0.25 is always guessing 50%)")
                    for lo, hi, count, mean, recall in cal.bins:
                        print(f"  said {lo}-{hi}%: recalled {round(recall * 100)}% of {count}")
                    difference = gap(cal)
                    if difference > 0.1:
                        print(f"you overrate yourself by {round(difference * 100)} points")
                    elif difference < -0.1:
                        print(f"you underrate yourself by {round(-difference * 100)} points")
                    else:
                        print("well calibrated")
                    if len(sources) > 1:
                        print("by source:")
                        for name, c in sources:
                            print(f"  {name}  {c.n}  Brier {c.brier:.3f}")
                case "why":
                    topic = find_topic(conn, args.name, args.course)
                    f = facets(conn, topic.id, now)
                    print(f"{topic.course or '-'}/{topic.name}  mastery {round(f.mastery * 100)}%")
                    if f.total:
                        print(f"  coverage {round(f.coverage * 100)}% ({f.covered} of {f.total} sections)")
                    else:
                        print("  coverage - (no files tracked)")
                    for name, part, unit, missing in (
                            ("memory", f.memory, "item", "no items yet"),
                            ("understanding", f.understanding, "answer", "no checks yet"),
                            ("application", f.application, "answer", "no practice yet")):
                        if part is None:
                            print(f"  {name} - ({missing})")
                        else:
                            print(f"  {name} {round(part.value * 100)}% ({part.n} {_plural(part.n, unit)})")
                case "misses":
                    found = misses(conn)
                    if not found:
                        print("no confident mistakes")
                        return 0
                    for row in found:
                        topic = get_topic(conn, row.topic_id) if row.topic_id is not None else None
                        where = f"{topic.course or '-'}/{topic.name}" if topic else "-"
                        print(f"{row.ts:%Y-%m-%d}  {where}  said {round(row.confidence * 100)}%"
                              f"  {row.source}  {short_label(row.label)}")
                case "ready":
                    courses = ready_courses(conn, now)
                    if not courses:
                        print("no topics with an upcoming exam")
                        return 0
                    for course, value, exam, n in courses:
                        print(f"{course or '-'}  {round(value * 100)}%  next exam {exam}  ({n} {_plural(n, 'topic')})")
        case "q":
            match args.q_cmd:
                case "add":
                    topic = find_topic(conn, args.topic, args.course)
                    if args.tol is not None and args.number is None:
                        raise ValueError("--tol goes with --number")
                    if args.correct is not None and args.choice is None:
                        raise ValueError("--correct goes with --choice")
                    kind, expected = "open", None
                    if args.number is not None:
                        kind = "number"
                        try:
                            expected = {"value": float(read_number(args.number)),
                                        "tol": float(read_number(args.tol)) if args.tol else 0}
                        except OverflowError:
                            raise ValueError("that number is too large") from None
                    elif args.choice is not None:
                        try:
                            correct = [int(x) for x in (args.correct or "").replace(" ", "").split(",") if x]
                        except ValueError:
                            raise ValueError("--correct takes option numbers, like 2 or 1,3") from None
                        kind = "choice"
                        expected = {"options": [o.strip() for o in args.choice.split(";")], "correct": correct}
                    ref = hashlib.sha1(args.prompt.encode()).hexdigest()[:12]
                    qid = bank.add_question(conn, origin="manual", ref=ref, prompt=args.prompt, now=now,
                                            trust="source", topic_id=topic.id, answer=args.answer, kind=kind,
                                            expected=expected, marks=args.marks)
                    print(f"question #{qid} added to {topic.name}")
                case "import":
                    topic = find_topic(conn, args.topic, args.course)
                    path = _full(args.file)
                    added, skipped = bank.import_note(conn, path, topic.id, now)
                    if not added and not skipped:
                        print("no sections with an answer in that file")
                    else:
                        tail = f" ({skipped} already there)" if skipped else ""
                        print(f"added {added} {'question' if added == 1 else 'questions'} to {topic.name}{tail}")
                case "ls":
                    found = bank.questions(conn, course=args.course)
                    if not found:
                        print("no questions")
                    for q in found:
                        topic = get_topic(conn, q.topic_id) if q.topic_id is not None else None
                        where = f"{topic.course or '-'}/{topic.name}" if topic else "-"
                        first = q.prompt.strip().splitlines()[0][:60]
                        print(f"#{q.id}  {where}  {q.trust}  {q.kind}  {_marks(q.marks)}  {first}")
                case "retire":
                    bank.retire(conn, args.id, " ".join(args.reason))
                    print(f"retired #{args.id}")
                case "restore":
                    bank.restore(conn, args.id)
                    print(f"restored #{args.id}")
                case "review":
                    found = bank.to_check(conn)
                    if not found:
                        print("no questions need a look")
                        return 0
                    for q, s in found:
                        tries = "1 try" if s.attempts == 1 else f"{s.attempts} tries"
                        print(f"#{q.id}  {', '.join(s.flags)}  {q.trust}  {tries}, mean {round(s.mean * 100)}%"
                              f"  {q.prompt.splitlines()[0][:80]}")
                    print("retire one with: pm q retire ID reason")
                case "vary":
                    added, dropped = variants.make(conn, args.id, now, lambda prompt: llm_ask(conn, prompt),
                                                   min(args.n, 10))
                    print(f"{added} {_plural(added, 'variant')} of #{args.id} added, {dropped} dropped")
        case "paper":
            match args.paper_cmd:
                case "add":
                    path = _full(args.file) if args.file else None
                    pid = bank.add_paper(conn, args.course, args.title, now, path=path, minutes=args.minutes)
                    print(f"paper #{pid} {args.title.strip()}")
                case "draft":
                    sys.stdout.write(drafts.paper_outline(conn, args.id, lambda prompt: llm_ask(conn, prompt)))
                    print("review this list before importing it: marks and topics are the model's guesses",
                          file=sys.stderr)
                case "import":
                    added, skipped, errors = bank.import_paper(conn, args.id, _read_lines(args.file), now)
                    tail = f" ({skipped} already there)" if skipped else ""
                    print(f"added {added} {'question' if added == 1 else 'questions'}{tail}")
                    for line in errors:
                        print(line)
                    return 1 if errors else 0
                case "ls":
                    found = bank.papers(conn)
                    if not found:
                        print("no papers")
                    for paper in found:
                        n = len(bank.questions(conn, paper_id=paper.id))
                        print(f"#{paper.id}  {paper.course}  {paper.title}  {n} {'question' if n == 1 else 'questions'}"
                              f"  {d(paper.minutes) if paper.minutes else '-'}")
        case "mock":
            match args.mock_cmd:
                case "new":
                    if args.paper is None and not args.course:
                        raise ValueError("give --course or --paper")
                    mid = mock.build(conn, args.course, now, random.Random(now.isoformat()), n=args.n,
                                     minutes=args.minutes, paper_id=args.paper)
                    _made(conn, mid)
                case "take":
                    mid = args.id if args.id is not None else mock.in_progress(conn)
                    if mid is None:
                        raise ValueError("no test in progress (pm mock ls)")
                    return _take(conn, mid, now)
                case "ls":
                    found = mock.mocks(conn)
                    if not found:
                        print("no tests")
                    for m in found:
                        print(_mock_line(conn, m))
                case "show":
                    _mock_show(conn, args.id)
                case "retry":
                    _made(conn, mock.retry(conn, args.id, now, random.Random(now.isoformat())))
        case "practice":
            words = args.words
            if words and words[0] in ("link", "unlink"):
                if len(words) != 2 or not args.topic:
                    raise ValueError(f"usage: pm practice {words[0]} GEN --topic TOPIC [--course C]")
                topic = find_topic(conn, args.topic, args.course)
                if words[0] == "link":
                    practice.link(conn, topic.id, words[1])
                    print(f"linked {words[1]} to {_where(topic)}")
                else:
                    practice.unlink(conn, topic.id, words[1])
                    print(f"unlinked {words[1]} from {_where(topic)}")
            elif words == ["gens"]:
                errors = templates.sync(conn)
                pairs = practice.linked(conn)
                for gen_id in generators.ids():
                    g = generators.info(gen_id)
                    to = [_where(get_topic(conn, t)) for t, g2 in pairs if g2 == gen_id]
                    print(f"{gen_id}  {g.TITLE}  {', '.join(g.VARIANTS)}" + (f"  → {', '.join(to)}" if to else ""))
                for line in errors:
                    print(line)
            elif len(words) > 1 or args.topic:
                raise ValueError("usage: pm practice [TOPIC] [--course C]")
            else:
                topic_id = find_topic(conn, words[0], args.course).id if words else None
                return _practise(conn, now, topic_id)
        case "suggest":
            if (args.action is None) != (args.id is None):
                raise ValueError("usage: pm suggest [accept|reject ID]")
            if args.action == "accept":
                print(f"done: {suggest.accept(conn, args.id)}")
            elif args.action == "reject":
                suggest.reject(conn, args.id)
                print(f"rejected #{args.id}")
            else:
                found = suggest.open_suggestions(conn)
                if not found:
                    print("no suggestions")
                for s in found:
                    print(f"#{s.id}  {s.text}")
        case "agent":
            match args.agent_cmd:
                case "add":
                    print(f"queued {args.kind} #{agent.enqueue(conn, args.kind, args.arg, now)}")
                case "ls":
                    found = agent.jobs(conn)
                    if not found:
                        print("no jobs")
                    for j in found:
                        line = f"#{j.id}  {j.kind}{'  ' + j.arg if j.arg else ''}  {j.status}  {j.calls} {_plural(j.calls, 'call')}"
                        print(line + (f"  {j.result}" if j.result and j.status != "queued" else ""))
                    print(f"budget: {agent.spent(conn, now)} of {agent.budget(conn)} calls used today")
                case "run":
                    if not agent.queued(conn):
                        print("nothing queued")
                    elif agent.budget_left(conn, now) <= 0:
                        print("no budget left today (pm set agent_daily_calls N)")
                    else:
                        for line in agent.run(conn, now, lambda prompt: llm_ask(conn, prompt), args.limit):
                            print(line)
        case "learn":
            text = lh.opening(conn, find_topic(conn, args.topic, args.course).id, now, args.practice)
            print(text)
            if args.copy:
                if tool := shutil.which("wl-copy"):
                    argv = [tool]
                elif tool := shutil.which("xclip"):
                    argv = [tool, "-selection", "clipboard"]
                else:
                    print("no clipboard tool found (wl-copy or xclip)")
                    return 0
                try:
                    subprocess.run(argv, input=text, text=True, check=True, timeout=10)
                except (OSError, subprocess.SubprocessError) as e:
                    raise ValueError(f"couldn't copy: {e}") from None
                print("copied")
        case "lh":
            match args.lh_cmd:
                case "sync":
                    out = lh.sync(conn, now)
                    if out.changed or not out.skipped:
                        print(lh.summary_line(out))
                    for line in out.skipped:
                        print(line)
                case "ls":
                    found = lh.sessions(conn)
                    if not found:
                        print("no LearnHarness sessions (pm lh sync)")
                        return 0
                    for s in found:
                        where = _where(get_topic(conn, s.topic_id)) if s.topic_id is not None else "-"
                        when = f"{s.updated:%Y-%m-%d}" if s.updated else "-"
                        print(f"{s.chat_id}  {s.kind}  {where}  {s.minutes}m  {when}  {s.error or s.title}")
                case "install":
                    folder, replaced = lh.install_plugin(conn)
                    print(f"{'updated' if replaced else 'installed'} the pm plugin in {_tilde(folder)}")
                    print("enable it in LearnHarness: Settings → Community plugins → pm planner bridge,"
                          " then restart LearnHarness")
                    print("it needs pm ui running: pm ui --install")
                case "map":
                    if args.none == bool(args.topic):
                        raise ValueError("usage: pm lh map CHAT TOPIC [--course C] | pm lh map CHAT --none")
                    if args.none:
                        lh.map_session(conn, args.chat, None)
                        print(f"unmapped {args.chat}")
                    else:
                        topic = find_topic(conn, args.topic, args.course)
                        lh.map_session(conn, args.chat, topic.id)
                        print(f"mapped {args.chat} to {_where(topic)}")
        case "template":
            match args.template_cmd:
                case "check":
                    print(templates.check_file(_full(args.file)))
                case "dir":
                    folder = templates.folder_of(conn)
                    if folder is None:
                        raise ValueError("the database is in memory, so there is no templates folder")
                    try:
                        folder.mkdir(parents=True, exist_ok=True)
                    except OSError as e:
                        raise ValueError(str(e)) from None
                    print(folder)
                case "draft":
                    templates.sync(conn)
                    text = drafts.template(conn, args.question, lambda prompt: llm_ask(conn, prompt))
                    path = drafts.save_template(conn, text)
                    print(f"drafted t:{path.stem} in {_tilde(path)}")
                    print(f"read it, then: pm template approve {path.stem}")
                case "approve":
                    path = drafts.approve_template(conn, args.name)
                    print(f"approved t:{templates.parse(path.read_text(encoding='utf-8')).id}")
                case "ls":
                    errors = templates.sync(conn)
                    loaded = [g for g in generators.ids() if g.startswith("t:")]
                    if not loaded and not errors:
                        print(f"no templates in {templates.folder_of(conn)}")
                    for gen_id in loaded:
                        g = generators.info(gen_id)
                        print(f"{gen_id}  {g.TITLE}  v{g.VERSION}")
                    for line in errors:
                        print(line)
        case "review":
            cap = new_cap(conn)
            due = queue(conn, now, cap)[:args.limit]
            if not due:
                print("nothing due")
                return 0
            reviewed = 0
            for k, item in enumerate(due, 1):
                topic = get_topic(conn, item.topic_id)
                if item.prompt:
                    description = item.prompt
                else:
                    description = f"recall: {item.path.name}"
                    if item.locator:
                        description += f"#{item.locator}"
                print(f"[{k}/{len(due)}] {topic.course or '-'}/{topic.name}: {description}")
                confidence = _ask_confidence()
                if confidence is None:
                    break
                try:
                    print(excerpt(item.path, item.locator))
                except (OSError, ValueError) as e:
                    print(f"can't show excerpt: {e}")
                grade = _ask_grade()
                if grade is None:
                    break
                next_due = record_review(conn, item.id, grade, confidence, _now())
                print(f"next review {next_due:%Y-%m-%d %H:%M}")
                reviewed += 1
            print(f"reviewed {reviewed}")
            if not queue(conn, now, cap):
                waiting = held(conn, now, cap)
                if waiting:
                    print(f"{waiting} new {'item waits' if waiting == 1 else 'items wait'}"
                          " for another day (pm set new_per_day)")
        case "spot":
            if args.make is not None:
                ids = spot.candidates(conn, args.make)
                if not ids:
                    print("nothing to make cards from (review some text items first)")
                    return 0

                def model(prompt: str) -> str:
                    try:
                        return llm_ask(conn, prompt)
                    except ValueError as e:
                        raise _ModelError(str(e)) from None

                made, skipped = 0, []
                for item_id in ids:
                    try:
                        spot.make(conn, item_id, now, model)
                        made += 1
                    except _ModelError as e:
                        if not made and not skipped:
                            raise ValueError(str(e)) from None
                        skipped.append(f"stopped: {e}")
                        break
                    except (LookupError, ValueError) as e:
                        skipped.append(f"skipped #{item_id}: {e}")
                print(f"made {made} {'card' if made == 1 else 'cards'}")
                for line in skipped:
                    print(line)
                return 0
            cards = spot.pending(conn)
            if not cards:
                print("no spot cards (pm spot --make 3)")
                return 0
            answered = 0
            for k, card in enumerate(cards, 1):
                item = get_item(conn, card.item_id)
                topic = get_topic(conn, item.topic_id)
                label = item.prompt or (f"{item.path.name}#{item.locator}" if item.locator
                                        else item.path.name)
                print(f"[{k}/{len(cards)}] {topic.course or '-'}/{topic.name}: {label}")
                lines = card.mutated.split("\n")
                width = len(str(len(lines)))
                for n, text in enumerate(lines, 1):
                    print(f"  {n:>{width}}  {text}")
                confidence = _ask_confidence()
                if confidence is None:
                    break
                picked = _ask_line(len(lines))
                if picked is None:
                    break
                right = spot.answer(conn, card.id, picked, confidence, now)
                print(f"right: line {card.line}" if right else f"wrong: it was line {card.line}")
                print(f"was:   {card.original.split(chr(10))[card.line - 1]}")
                print(f"shown: {lines[card.line - 1]}")
                answered += 1
            print(f"answered {answered}")
        case "run":
            argv = list(args.argv)
            if argv and argv[0] == "--":
                argv.pop(0)
            if not argv:
                raise ValueError("give a command, like pm run -- make test")
            cwd = Path.cwd()
            snap = snapshot(cwd)
            t0 = time.monotonic()
            try:
                code = subprocess.run(argv).returncode
            except (FileNotFoundError, PermissionError):
                raise ValueError(f"command not found: {argv[0]}") from None
            except KeyboardInterrupt:
                return 130
            try:
                episode = record_run(conn, shlex.join(argv), str(cwd), now, time.monotonic() - t0,
                                     code, snap, running_task_id(conn),
                                     differ=lambda a, b: diff(cwd, a, b))
            except (sqlite3.Error, ValueError, MemoryError) as e:  # the command's own exit code must survive
                print(f"pm: run not logged: {e}", file=sys.stderr)
                return code
            if episode is not None:
                lost = d(round((episode.lost_s or 0) / 60))
                if episode.tags:
                    tail = f"[{', '.join(episode.tags)}]"
                else:
                    tail = f"(tag it: pm bug {episode.id} <tag>)"
                print(f"pm: fixed bug #{episode.id} after {_fails(episode.fails)},"
                      f" {lost} lost {tail}", file=sys.stderr)
            return code if code >= 0 else 128 - code
        case "bugs":
            s = summary(conn, now.date())
            if s.fixed == s.open == s.abandoned == 0:
                print("no bugs yet")
                return 0
            print(f"episodes {s.fixed + s.open + s.abandoned}: {s.fixed} fixed, {s.open} open,"
                  f" {s.abandoned} abandoned  lost {d(round(s.lost_s / 60))}")
            tag_parts = [f"{tag} {n}" for tag, n in s.tags]
            if s.untagged:
                tag_parts.append(f"untagged {s.untagged}")
            if tag_parts:
                print(f"tags: {', '.join(tag_parts)}")
            if s.bursts:
                print(f"burst: {', '.join(f'{tag} {n}' for tag, n in s.bursts)} in 7 days")
            print("recent:")
            for ep in bug_episodes(conn):
                line = f"  #{ep.id}  {ep.status:<5}  {ep.cmd}  {_fails(ep.fails)}"
                if ep.lost_s is not None:
                    line += f"  lost {d(round(ep.lost_s / 60))}"
                if ep.tags:
                    line += f"  [{', '.join(ep.tags)}]"
                print(line + f"  {short(ep.cwd)}")
        case "bug":
            ep = get_episode(conn, args.id)
            if args.tags:
                tags = set_tags(conn, ep.id, [] if args.tags == ["none"] else args.tags)
                print(f"#{ep.id} tags: {', '.join(tags) if tags else 'none'}")
            else:
                print(f"#{ep.id} {ep.status}  {ep.cmd}  {short(ep.cwd)}")
                line = f"opened {ep.opened:%Y-%m-%d %H:%M}"
                if ep.closed:
                    line += f"  closed {ep.closed:%Y-%m-%d %H:%M}"
                line += f"  {_fails(ep.fails)}"
                if ep.lost_s is not None:
                    line += f"  lost {d(round(ep.lost_s / 60))}"
                print(line)
                print(f"tags: {', '.join(ep.tags) if ep.tags else 'none'}")
                print()
                print(ep.diff if ep.diff else "no diff (not a git repo, or not fixed)")
        case "stats":
            data = summary_now(conn, now)
            if not args.push:
                print(json.dumps(data, indent=2, ensure_ascii=False))
                return 0
            url = get_setting(conn, "notes_url", DEFAULTS["notes_url"])
            netrc_path = _netrc_path()
            sent = push(data, url, netrc_path)
            host = urlsplit(url).hostname or url
            print(f"pushed {max(1, round(sent / 1024))} KB to {host}")
        case "versus":
            url = get_setting(conn, "versus_url", DEFAULTS["versus_url"])
            if not url:
                print("versus is off: pm set versus_url https://the-scoreboard-site")
                return 0
            if args.sync:
                versus.sync(conn, now, url, _netrc_path())
            b = versus.cached(conn, now.date())
            if b is None:
                print("no scoreboard yet: pm versus --sync")
                return 0
            for line in versus.text(b):
                print(line)
        case "inbox":
            url = get_setting(conn, "notes_url", DEFAULTS["notes_url"])
            netrc_path = _netrc_path()
            lines = apply_inbox(conn, fetch_inbox(url, netrc_path), now)
            for line in lines:
                print(line)
            if BUSY in lines:  # what was applied is marked unpushed; the next run pushes it
                return 0
            if get_setting(conn, UNPUSHED, "") != "1":
                print("inbox empty")
                return 0
            sent = push(summary_now(conn, now), url, netrc_path)
            set_setting(conn, UNPUSHED, "")
            print(f"pushed {max(1, round(sent / 1024))} KB")
        case "find":
            hits = find_files(conn, " ".join(args.words), args.course)
            if not hits:
                print("no matches")
            for hit in hits:
                print(f"{short(hit.path)}  [{hit.course or '-'}]")
                print(f"    {' '.join(hit.snippet.split())}")  # PDFs keep their line breaks; one line reads better
        case "watch":
            if args.install:
                _install_unit("pm-watch", "pm watch: index Downloads, nudge, push stats", "watch")
            elif args.once:
                lines, _ = tick(conn, now, None, _netrc_path())
                for line in lines:
                    print(line)
                if not lines:
                    print("nothing new")
            else:
                return loop(default_path(), _netrc_path())
        case "ui":
            if args.install:
                _install_unit("pm-ui", "pm ui: the local planner page", "ui --no-open")
                return 0
            url = f"http://127.0.0.1:{args.port}"
            print(f"pm ui on {url}", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            try:
                return serve(default_path(), args.port, _now)
            except OSError:
                if _ping(url):
                    print(f"pm ui is already running: {url}")
                    return 0
                raise ValueError(f"port {args.port} is in use; try pm ui --port {args.port + 1}")
        case "llm":
            print(llm_ask(conn, " ".join(args.words)))
    return 0


PROGRAMS = (("pdftotext", "text from PDFs, for search and excerpts"), ("pdfinfo", "page counts of PDFs"),
            ("pdftoppm", "PDF pages as pictures in the app, and OCR"), ("tesseract", "OCR for scanned PDFs"),
            ("git", "what changed between a failing and a passing pm run"),
            *((("osascript", "desktop nudges"), ("open", "opening files and links")) if sys.platform == "darwin"
              else (("notify-send", "desktop nudges"), ("xdg-open", "opening files and links"))),
            ("node", "only for LearnHarness's pm-bridge plugin and pm's own tests"))


def _doctor(conn, now: datetime) -> None:
    path = default_path()
    size = f"{path.stat().st_size / 1e6:.1f} MB" if path.is_file() else "new"
    print(f"database    {path}  ({size})")
    seen = get_setting(conn, SEEN, "")
    try:
        ago = now - datetime.fromisoformat(seen) if seen else None
    except ValueError:
        ago = None
    if ago is None:
        print("daemon      never ran: pm watch (or pm watch --install to start it at login)")
    elif timedelta(0) <= ago < timedelta(minutes=3):
        print("daemon      running")
    else:
        print(f"daemon      not running, last seen {seen.replace('T', ' ')}: pm watch")
    for root in watch_roots(conn):
        print(f"watching    {root}" + ("" if root.is_dir() else "  (not a folder)"))
    try:
        argv = llm_command(conn)
    except ValueError as e:
        print(f"model       llm_cmd can't be read: {e}")
    else:
        if argv is None:
            print("model       not set (optional): pm set llm_cmd 'COMMAND'")
        else:
            print(f"model       {argv[0]}" + ("" if shutil.which(argv[0]) else "  (not found on PATH)"))
    budget = get_setting(conn, "agent_daily_calls", "0")
    print(f"model jobs  {'off' if budget == '0' else budget + ' calls a day'}")
    print(f"notes site  {get_setting(conn, 'notes_url', '') or 'not set (optional): pm set notes_url URL'}")
    print(f"learnharness  {lh.data_dir(conn) or 'not found (optional): pm set lh_dir FOLDER'}")
    for name, use in PROGRAMS:
        print(f"{'ok     ' if shutil.which(name) else 'missing'}     {name}: {use}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd is None:
        args.cmd = "today"
    conn = connect(default_path())
    try:
        return _run(args, conn, _now())
    except (LookupError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except sqlite3.OperationalError as e:
        if "locked" not in str(e) and "busy" not in str(e):
            raise
        print("error: the database is busy (another pm is writing), try again", file=sys.stderr)
        return 1
    finally:
        conn.close()
