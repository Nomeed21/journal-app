"""Local journal storage on the machine running FastAPI."""
import json
import os
import sqlite3
from datetime import date
from contextlib import contextmanager, closing
from functools import lru_cache
from pathlib import Path

from backend.config import LOCAL_TZ_OFFSET_HOURS

DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".local-data" / "journal.sqlite3"


@lru_cache(maxsize=8)
def _initialize(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '',
                mood INTEGER, energy INTEGER, focus INTEGER,
                entry_type TEXT NOT NULL DEFAULT 'free', tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS entries_chronological ON entries(created_at, id);
        """)
        from backend.sqlite_schema import initialize
        initialize(conn)
        conn.commit()


@contextmanager
def connection():
    path = Path(os.getenv("LIAINNE_JOURNAL_DB") or DEFAULT_PATH).expanduser().resolve()
    _initialize(path)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn


def decoded(row):
    if row is None:
        return None
    fields = ("id","title","content","mood","energy","focus","entry_type","created_at")
    return {**{field:row[field] for field in fields}, "tags":json.loads(row["tags"])}


def save(data, entry_id=None):
    fields = ("title", "content", "mood", "energy", "focus", "entry_type", "tags")
    values = [data.get(k, "") if k in ("title", "content") else data.get(k) for k in fields]
    values[-1] = json.dumps(data.get("tags", []), ensure_ascii=False)
    with connection() as conn:
        if entry_id is None:
            cursor = conn.execute(
                "INSERT INTO entries (title,content,mood,energy,focus,entry_type,tags,created_at) VALUES (?,?,?,?,?,?,?,?)",
                [*values, data["created_at"]],
            )
            entry_id = cursor.lastrowid
        else:
            conn.execute("UPDATE entries SET title=?,content=?,mood=?,energy=?,focus=?,entry_type=?,tags=? WHERE id=?",
                         [*values, entry_id])
        return decoded(conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone())


def get(entry_id):
    with connection() as conn:
        return decoded(conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone())


def delete(entry_id):
    with connection() as conn:
        return conn.execute("DELETE FROM entries WHERE id=?", (entry_id,)).rowcount == 1


def records(*, start=None, end=None, before=None, tag=None, keyword=None,
            newest=True, limit=None, offset=0):
    filters, values = [], []
    for comparison, value in (("created_at >= ?", start), ("created_at <= ?", end), ("created_at < ?", before),
                              ("EXISTS (SELECT 1 FROM json_each(entries.tags) WHERE value = ?)", tag)):
        if value is not None:
            filters.append(comparison)
            values.append(value)
    if keyword:
        filters.append("(instr(lower(title),lower(?)) OR instr(lower(content),lower(?)))")
        values.extend([keyword, keyword])
    query = "SELECT * FROM entries"
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY created_at DESC, id DESC" if newest else " ORDER BY created_at, id"
    if limit is not None:
        query += " LIMIT ? OFFSET ?"
        values.extend([limit, offset])
    with connection() as conn:
        return [decoded(row) for row in conn.execute(query, values)]


def participation():
    with connection() as conn:
        return dict(conn.execute("""
            SELECT count(*) AS recorded_entries,
                   count(DISTINCT date(created_at, ?)) AS recorded_days,
                   max(created_at) AS latest
            FROM entries
            WHERE NOT EXISTS (SELECT 1 FROM json_each(entries.tags) WHERE value = '__skipped__')
        """, (f"{LOCAL_TZ_OFFSET_HOURS:+} hours",)).fetchone())


def journal_streak(today):
    """Count recorded days. Two unrecorded days may bridge each streak."""
    local_today = date.fromisoformat(today)
    with connection() as conn:
        days = conn.execute("""
            SELECT DISTINCT date(created_at, ?) AS day FROM entries
            WHERE NOT EXISTS (SELECT 1 FROM json_each(entries.tags) WHERE value = '__skipped__')
            ORDER BY day
        """, (f"{LOCAL_TZ_OFFSET_HOURS:+} hours",)).fetchall()

    previous = None
    count, freezes = 0, 2
    for row in days:
        day = date.fromisoformat(row["day"])
        if day > local_today:
            break
        if previous is not None:
            missed = (day - previous).days - 1
            if missed > freezes:
                count, freezes = 0, 2
            else:
                freezes -= missed
        count += 1
        previous = day
    if previous is not None:
        missed = max(0, (local_today - previous).days - 1)
        if missed > freezes:
            count, freezes = 0, 2
        else:
            freezes -= missed
    return {"recorded_days": count, "freezes_left": freezes}
