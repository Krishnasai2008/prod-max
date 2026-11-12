"""The pm watch daemon: scan, nudge and push, one testable tick at a time."""
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from pm import agent, lh, llm, versus
from pm.db import SEEN, connect, get_setting, set_setting
from pm.files import scan
from pm.inbox import UNPUSHED, apply as apply_inbox
from pm.nudge import due, send
from pm.risk import forecast
from pm.stats import fetch_inbox, pull_notes, push, save_notes, summary_now
from pm.study import refresh_files

EVERY = 10
HOURLY = timedelta(hours=1)
INBOX = timedelta(minutes=5)
LH_LOGGED = "lh_logged"  # internal: skipped LearnHarness files already logged
AGENT_JOBS = 5
AGENT_WARNED = "agent_warned"  # internal: the day "set llm_cmd first" was last logged


def _lh_sync(conn, now: datetime) -> list[str]:
    """Log a sync only when it found something, and a skipped file only the first time."""
    try:
        out = lh.sync(conn, now)
    except (ValueError, OSError) as e:
        return [f"learnharness: {e}"]
    logged = set(filter(None, get_setting(conn, LH_LOGGED, "").split("\n")))
    fresh = [s for s in out.skipped if s not in logged]
    if fresh:
        set_setting(conn, LH_LOGGED, "\n".join(sorted(logged | set(fresh))))
    lines = [lh.summary_line(out)] if out.changed else []
    return lines + [f"learnharness: {s}" for s in fresh]


def _agent(conn, now: datetime) -> list[str]:
    """Plan and run model jobs within today's budget; never fails the tick."""
    if agent.budget(conn) <= 0:
        return []
    try:
        if not llm.available(conn):
            today = now.date().isoformat()
            if get_setting(conn, AGENT_WARNED, "") == today:
                return []
            set_setting(conn, AGENT_WARNED, today)
            return ["agent: set llm_cmd first"]
        agent.plan(conn, now)
        # shortcut: model calls block the tick, so at most AGENT_JOBS jobs an hour; move to a thread if that's too slow
        ran = agent.run(conn, now, lambda prompt: llm.ask(conn, prompt), AGENT_JOBS)
        return [f"agent: {line}" for line in ran]
    except (ValueError, LookupError, OSError) as e:
        return [f"agent: {e}"]


def tick(conn, now: datetime, last_hourly: datetime | None,
         netrc_path: Path | None = None) -> tuple[list[str], datetime | None]:
    lines = []
    result = scan(conn, now)
    if result.added or result.updated or result.removed:
        line = f"indexed {result.added}, updated {result.updated}, removed {result.removed}"
        if result.pending:
            line += f", {result.pending} waiting"
        lines.append(line)
    url = get_setting(conn, "notes_url", "")
    checking = False
    if url:
        checked = get_setting(conn, "inbox_checked", "")
        try:
            last_check = datetime.fromisoformat(checked) if checked else None
        except ValueError:
            last_check = None
        checking = last_check is None or not timedelta(0) <= now - last_check < INBOX  # a clock set back counts as due
        if checking:
            set_setting(conn, "inbox_checked", now.isoformat(timespec="seconds"))
            try:
                found = apply_inbox(conn, fetch_inbox(url, netrc_path), now)
            except ValueError as error:
                message = str(error)
                lines.append(message if message.startswith("inbox failed:")
                             else f"inbox failed: {message}")
            else:
                lines.extend(found)
    if lh.data_dir(conn) is not None:
        lines.extend(_lh_sync(conn, now))
    hourly = last_hourly is None or not timedelta(0) <= now - last_hourly < HOURLY
    if hourly:
        refresh_files(conn)
        tasks, _, risks, _ = forecast(conn, now)
        messages = due(conn, now, tasks, risks)
        send(messages)
        if messages:
            lines.append(f"{len(messages)} nudge{'s' if len(messages) > 1 else ''}")
        if url:
            try:
                save_notes(conn, pull_notes(url, netrc_path))
            except ValueError as error:
                message = str(error)
                lines.append(message if message.startswith("pull failed:")
                             else f"pull failed: {message}")
        hub = get_setting(conn, "versus_url", "")
        if hub:  # before the push, so the site gets the fresh board
            try:
                players = versus.sync(conn, now, hub, netrc_path)
            except ValueError as error:
                message = str(error)
                lines.append(message if message.startswith("versus failed:")
                             else f"versus failed: {message}")
            else:
                lines.append(f"versus: {players} player{'' if players == 1 else 's'}")
        last_hourly = now
    # UNPUSHED: apply set it with the entry; a failed push leaves it, so the next inbox check (not the next tick) pushes again
    if url and (hourly or (checking and get_setting(conn, UNPUSHED, "") == "1")):
        try:
            sent = push(summary_now(conn, now), url, netrc_path)
        except ValueError as error:
            message = str(error)
            lines.append(message if message.startswith("push failed:")
                         else f"push failed: {message}")
        else:
            set_setting(conn, UNPUSHED, "")
            lines.append(f"pushed {max(1, round(sent / 1024))} KB")
    if hourly:
        lines.extend(_agent(conn, now))
    return lines, last_hourly


def loop(db_path, netrc_path: Path | None = None) -> int:
    last_hourly = None
    seen = ""
    try:
        while True:
            conn = connect(db_path)
            try:
                now = datetime.now()
                lines, last_hourly = tick(conn, now, last_hourly, netrc_path)
                if now.strftime("%H:%M") != seen:  # once a minute, so pm doctor can tell the daemon is alive
                    seen = now.strftime("%H:%M")
                    set_setting(conn, SEEN, now.isoformat(timespec="seconds"))
            except sqlite3.OperationalError as error:  # another pm held the database past busy_timeout: next tick
                lines = [f"database busy: {error}"]
            except Exception as error:  # one bad file or reply must not end the daemon; its hourly work waits an hour
                lines, last_hourly = [f"tick failed: {type(error).__name__}: {error}"], datetime.now()
            finally:
                conn.close()
            for line in lines:
                print(line, flush=True)
            time.sleep(EVERY)
    except KeyboardInterrupt:
        return 0
