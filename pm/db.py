import math
import os
import shlex
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, course TEXT, kind TEXT NOT NULL DEFAULT 'task',
  est_min INTEGER NOT NULL CHECK(est_min > 0), due TEXT,
  energy TEXT NOT NULL DEFAULT 'deep' CHECK(energy IN ('deep','shallow')),
  first_step TEXT, created TEXT NOT NULL, done_at TEXT,
  dropped INTEGER NOT NULL DEFAULT 0 CHECK(dropped IN (0,1)));
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
  start TEXT NOT NULL, end TEXT, note TEXT, energy INTEGER CHECK(energy BETWEEN 1 AND 5),
  logged INTEGER NOT NULL DEFAULT 0 CHECK(logged IN (0,1)));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics(
  id INTEGER PRIMARY KEY, course TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
  exam_date TEXT, weight REAL NOT NULL DEFAULT 1 CHECK(weight > 0), UNIQUE(course, name));
CREATE TABLE IF NOT EXISTS topic_prereqs(
  topic_id INTEGER NOT NULL REFERENCES topics(id), prereq_id INTEGER NOT NULL REFERENCES topics(id),
  PRIMARY KEY(topic_id, prereq_id));
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id), path TEXT NOT NULL,
  locator TEXT, prompt TEXT, card TEXT NOT NULL, due TEXT NOT NULL, created TEXT NOT NULL,
  suspended INTEGER NOT NULL DEFAULT 0 CHECK(suspended IN (0,1)));
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id), ts TEXT NOT NULL,
  grade INTEGER NOT NULL CHECK(grade BETWEEN 1 AND 4),
  confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1), recalled INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS episodes(
  id INTEGER PRIMARY KEY, cmd TEXT NOT NULL, cwd TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','fixed','abandoned')),
  opened TEXT NOT NULL, closed TEXT, lost_s INTEGER, diff TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_episode ON episodes(cmd, cwd) WHERE status='open';
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, cmd TEXT NOT NULL, cwd TEXT NOT NULL, start TEXT NOT NULL,
  dur_s REAL NOT NULL, code INTEGER NOT NULL, task_id INTEGER REFERENCES tasks(id),
  snap TEXT, episode_id INTEGER REFERENCES episodes(id));
CREATE TABLE IF NOT EXISTS episode_tags(
  episode_id INTEGER NOT NULL REFERENCES episodes(id), tag TEXT NOT NULL,
  PRIMARY KEY(episode_id, tag));
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, mtime REAL NOT NULL,
  size INTEGER NOT NULL, course TEXT, indexed TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(name, body, tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS inbox_applied(id TEXT PRIMARY KEY, applied TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS task_links(
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
  target TEXT NOT NULL, UNIQUE(task_id, target));
CREATE TABLE IF NOT EXISTS spots(
  id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
  original TEXT NOT NULL, mutated TEXT NOT NULL, line INTEGER NOT NULL CHECK(line >= 1),
  created TEXT NOT NULL, answered TEXT, picked INTEGER,
  confidence REAL CHECK(confidence BETWEEN 0 AND 1));
CREATE TABLE IF NOT EXISTS evidence(
  id INTEGER PRIMARY KEY, topic_id INTEGER REFERENCES topics(id),
  source TEXT NOT NULL, ref TEXT NOT NULL, ts TEXT NOT NULL,
  correct INTEGER CHECK(correct IN (0,1)), score REAL CHECK(score BETWEEN 0 AND 1),
  confidence REAL CHECK(confidence BETWEEN 0 AND 1),
  dont_know INTEGER NOT NULL DEFAULT 0 CHECK(dont_know IN (0,1)),
  seconds INTEGER CHECK(seconds >= 0),
  grader TEXT NOT NULL CHECK(grader IN ('code','self','llm')),
  facet TEXT CHECK(facet IN ('memory','understanding','application')),
  label TEXT NOT NULL DEFAULT '', UNIQUE(source, ref));
CREATE TABLE IF NOT EXISTS topic_files(
  topic_id INTEGER NOT NULL REFERENCES topics(id), path TEXT NOT NULL,
  sections INTEGER, mtime REAL, PRIMARY KEY(topic_id, path));
CREATE TABLE IF NOT EXISTS papers(
  id INTEGER PRIMARY KEY, course TEXT NOT NULL, title TEXT NOT NULL, path TEXT,
  minutes INTEGER CHECK(minutes > 0), created TEXT NOT NULL, UNIQUE(course, title));
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY, topic_id INTEGER REFERENCES topics(id),
  origin TEXT NOT NULL CHECK(origin IN ('paper','note','manual','lh','variant')),
  ref TEXT NOT NULL, prompt TEXT NOT NULL, answer TEXT,
  kind TEXT NOT NULL DEFAULT 'open'
    CHECK(kind IN ('open','number','token','sequence','set','choice')),
  expected TEXT, marks REAL NOT NULL DEFAULT 1 CHECK(marks > 0),
  trust TEXT NOT NULL CHECK(trust IN ('verified','source','checked','unverified')),
  path TEXT, locator TEXT, paper_id INTEGER REFERENCES papers(id),
  parent_id INTEGER REFERENCES questions(id), created TEXT NOT NULL, retired TEXT,
  UNIQUE(origin, ref));
CREATE TABLE IF NOT EXISTS mocks(
  id INTEGER PRIMARY KEY, course TEXT NOT NULL, title TEXT NOT NULL,
  minutes INTEGER NOT NULL CHECK(minutes > 0), paper_id INTEGER REFERENCES papers(id),
  predicted REAL, created TEXT NOT NULL, started TEXT, finished TEXT, marked TEXT);
CREATE TABLE IF NOT EXISTS mock_items(
  mock_id INTEGER NOT NULL REFERENCES mocks(id), pos INTEGER NOT NULL,
  question_id INTEGER REFERENCES questions(id), gen TEXT, seed INTEGER, variant TEXT,
  topic_id INTEGER REFERENCES topics(id), marks REAL NOT NULL,
  answer TEXT, confidence REAL CHECK(confidence BETWEEN 0 AND 1),
  dont_know INTEGER NOT NULL DEFAULT 0 CHECK(dont_know IN (0,1)),
  seconds INTEGER, score REAL CHECK(score BETWEEN 0 AND 1),
  PRIMARY KEY(mock_id, pos), CHECK((question_id IS NULL) != (gen IS NULL)));
CREATE TABLE IF NOT EXISTS topic_gens(
  topic_id INTEGER NOT NULL REFERENCES topics(id), gen TEXT NOT NULL,
  PRIMARY KEY(topic_id, gen));
CREATE TABLE IF NOT EXISTS lh_sessions(
  chat_id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
  topic_id INTEGER REFERENCES topics(id),
  tagged INTEGER NOT NULL DEFAULT 0 CHECK(tagged IN (0,1)),
  created TEXT, updated TEXT, minutes INTEGER NOT NULL DEFAULT 0,
  mtime REAL NOT NULL, size INTEGER NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS lh_days(
  chat_id TEXT NOT NULL, day TEXT NOT NULL, minutes INTEGER NOT NULL,
  PRIMARY KEY(chat_id, day));
CREATE TABLE IF NOT EXISTS lh_cards(
  prop_id TEXT PRIMARY KEY, chat_id TEXT, topic_id INTEGER REFERENCES topics(id),
  name TEXT NOT NULL, state INTEGER NOT NULL, stability REAL, last_review TEXT, due TEXT);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, arg TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','done','failed')),
  created TEXT NOT NULL, finished TEXT, calls INTEGER NOT NULL DEFAULT 0, result TEXT);
CREATE TABLE IF NOT EXISTS suggestions(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('topic','prereq')),
  subject TEXT NOT NULL, value TEXT NOT NULL, created TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','accepted','rejected')),
  UNIQUE(kind, subject, value));
CREATE TABLE IF NOT EXISTS versus_days(
  day TEXT PRIMARY KEY, syllabus REAL NOT NULL CHECK(syllabus BETWEEN 0 AND 100));
"""

# Every graded answer, wherever it is stored: reviews and spot cards stay in their own tables.
EVIDENCE_VIEW = """CREATE VIEW evidence_v AS
SELECT 'review' AS source, CAST(r.id AS TEXT) AS ref, i.topic_id AS topic_id, r.ts AS ts,
       r.recalled AS correct, NULL AS score, r.confidence AS confidence, 0 AS dont_know,
       NULL AS seconds, 'self' AS grader, 'memory' AS facet,
       coalesce(i.prompt, i.path || coalesce('#' || i.locator, '')) AS label
  FROM reviews r JOIN items i ON i.id = r.item_id
UNION ALL
SELECT 'spot', CAST(s.id AS TEXT), i.topic_id, s.answered, (s.picked = s.line), NULL,
       s.confidence, 0, NULL, 'code', 'understanding',
       coalesce(i.prompt, i.path || coalesce('#' || i.locator, ''))
  FROM spots s JOIN items i ON i.id = s.item_id WHERE s.answered IS NOT NULL
UNION ALL
SELECT source, ref, topic_id, ts, correct, score, confidence, dont_know, seconds, grader, facet, label
  FROM evidence"""


def default_path() -> Path:
    env = os.environ.get("PM_DB")
    return Path(env) if env else Path.home() / ".local/share/prod-max/pm.db"


def _add_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if column not in {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _view(conn: sqlite3.Connection, name: str, sql: str) -> None:
    """(Re)create a view only when its stored text differs, so an ordinary connect writes nothing."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()
    if row is None or row[0] != sql:
        conn.execute("BEGIN IMMEDIATE")  # one step, so another pm never finds the view missing
        conn.execute(f"DROP VIEW IF EXISTS {name}")
        conn.execute(sql)
        conn.commit()


VERSION = 15
SEEN = "watch_seen"  # internal: when the daemon last ticked (pm doctor reads it)


def backup(conn: sqlite3.Connection, dest: Path) -> Path:
    """A consistent copy of the database, safe while the daemon and the app are running."""
    if dest.exists():
        raise ValueError(f"{dest} already exists")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        copy = sqlite3.connect(dest)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    except (OSError, sqlite3.Error) as e:
        raise ValueError(f"backup failed: {e}") from None
    return dest


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    old = conn.execute("PRAGMA user_version").fetchone()[0]
    if 0 < old < VERSION and str(path) != ":memory:":  # an upgrade: keep the database as it was, once per version
        try:
            backup(conn, Path(f"{path}.v{old}.bak"))
        except ValueError:
            pass  # the copy is already there, or the disk refused: the upgrade itself only adds tables
    conn.executescript(SCHEMA)
    _add_column(conn, "tasks", "dropped", "INTEGER NOT NULL DEFAULT 0 CHECK(dropped IN (0,1))")
    _add_column(conn, "items", "suspended", "INTEGER NOT NULL DEFAULT 0 CHECK(suspended IN (0,1))")
    _add_column(conn, "sessions", "energy", "INTEGER CHECK(energy BETWEEN 1 AND 5)")
    _add_column(conn, "sessions", "logged", "INTEGER NOT NULL DEFAULT 0 CHECK(logged IN (0,1))")  # 1: pm log, no real clock time
    _view(conn, "evidence_v", EVIDENCE_VIEW)
    if old < 9:  # items from before phase 11 get their files tracked, sections still unknown
        conn.execute("INSERT OR IGNORE INTO topic_files(topic_id, path)"
                     " SELECT DISTINCT i.topic_id, i.path FROM items i JOIN topics t ON t.id = i.topic_id")
        conn.commit()
    if old < VERSION:
        conn.execute(f"PRAGMA user_version={VERSION}")
    return conn


DEFAULTS = {"hours_per_day": "4", "peak": "09-12", "notes_url": "", "notes_dir": "",
            "watch": "~/Downloads", "watch_ignore": "", "course_codes": "", "nudge_hours": "08-22",
            "new_per_day": "10", "llm_cmd": "", "lh_dir": "", "agent_daily_calls": "0", "versus_url": ""}


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {key: get_setting(conn, key, default) for key, default in DEFAULTS.items()}


def _hours_range(value: str) -> None:
    try:
        lo, hi = (int(part) for part in value.split("-"))
    except ValueError:
        raise ValueError("expected a range like 09-17") from None
    if not (0 <= lo < hi <= 24):
        raise ValueError("expected a range like 09-17 with 0 <= start < end <= 24")


def _course_codes(value: str) -> None:
    for pair in value.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        name, sep, code = pair.partition("=")
        if not sep or not name.strip() or not code.strip():
            raise ValueError("course_codes must be name=CODE pairs separated by ;")


def put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if not isinstance(key, str) or not isinstance(value, str):
        raise ValueError("setting key and value must be text")
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key!r} (known: {', '.join(DEFAULTS)})")
    if key == "hours_per_day":
        try:
            hours = float(value)
        except ValueError:
            raise ValueError("hours_per_day must be between 0.1 and 16") from None
        if not math.isfinite(hours) or not 0.1 <= hours <= 16:
            raise ValueError("hours_per_day must be between 0.1 and 16")
    if key in ("peak", "nudge_hours"):
        _hours_range(value)
    if key == "course_codes":
        _course_codes(value)
    if key == "new_per_day":
        try:
            count = int(value)
        except ValueError:
            raise ValueError("new_per_day must be between 1 and 200") from None
        if not 1 <= count <= 200:
            raise ValueError("new_per_day must be between 1 and 200")
    if key == "agent_daily_calls":
        try:
            calls = int(value)
        except ValueError:
            calls = -1
        if not 0 <= calls <= 500:
            raise ValueError("agent_daily_calls must be between 0 and 500")
    if key in ("notes_url", "versus_url") and value:
        parts = urlsplit(value)
        try:
            parts.port
        except ValueError:
            raise ValueError(f"{key} must be empty or https://your-site") from None
        if (not value.startswith("https://") or not parts.hostname
                or any(ch.isspace() for ch in value)
                or parts.query or parts.fragment):
            raise ValueError(f"{key} must be empty or https://your-site")
    if key == "notes_dir" and value:
        try:
            folder = Path(value).expanduser().resolve()
            is_folder = folder.is_dir()
        except (OSError, RuntimeError):
            raise ValueError("notes_dir must be a folder, like ~/prod-max/notes-site/docs") from None
        if (value != value.strip() or not value.startswith(("/", "~/"))
                or not is_folder):
            raise ValueError("notes_dir must be a folder, like ~/prod-max/notes-site/docs")
    if key == "llm_cmd" and value:
        try:
            words = shlex.split(value)
        except ValueError:
            words = []
        if not words:
            raise ValueError("llm_cmd must be a command line, like: my-llm --model small")
    if key == "lh_dir" and value:
        try:
            ok = value == value.strip() and (Path(value).expanduser() / "chats").is_dir()
        except (OSError, RuntimeError):
            ok = False
        if not ok:
            raise ValueError("lh_dir must be LearnHarness's data folder, the one that holds chats/")
    if key in ("watch", "watch_ignore"):
        for part in value.split(":"):
            if part != part.strip() or (part and not (part.startswith("/")
                                                      or part.startswith("~/"))):
                raise ValueError(f"{key} folders must be full paths like ~/Downloads")
    set_setting(conn, key, value)


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
