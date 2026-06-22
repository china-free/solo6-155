import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

MAX_ENTRIES = 10000
MIN_ENTRIES_BEFORE_PURGE = 12000


def get_db_path():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    db_dir = base / "cb"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "history.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clipboard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_clipboard_created ON clipboard(created_at)"
        )


def add_entry(content: str) -> bool:
    if not content or not content.strip():
        return False
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM clipboard WHERE content = ? ORDER BY id DESC LIMIT 1",
            (content,),
        ).fetchone()
        now = time.time()
        if existing:
            conn.execute(
                "UPDATE clipboard SET created_at = ? WHERE id = ?",
                (now, existing["id"]),
            )
            return False
        conn.execute(
            "INSERT INTO clipboard (content, created_at) VALUES (?, ?)",
            (content, now),
        )
        count = conn.execute("SELECT COUNT(*) as c FROM clipboard").fetchone()["c"]
        if count > MIN_ENTRIES_BEFORE_PURGE:
            conn.execute(
                "DELETE FROM clipboard WHERE id IN ("
                "SELECT id FROM clipboard ORDER BY id ASC LIMIT ?)",
                (count - MAX_ENTRIES,),
            )
    return True


def search_entries(query: str = None, use_regex: bool = False, today_only: bool = True):
    sql = "SELECT id, content, created_at FROM clipboard"
    params = []
    conditions = []
    if today_only:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        conditions.append("created_at >= ?")
        params.append(today_start)
    if query:
        if use_regex:
            conditions.append("content REGEXP ?")
        else:
            conditions.append("content LIKE ?")
            query = f"%{query}%"
        params.append(query)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at DESC LIMIT 500"
    with get_conn() as conn:
        if use_regex:
            import re
            conn.create_function("REGEXP", 2, lambda expr, item: re.search(expr, item or "") is not None)
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_recent(limit: int = 50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, created_at FROM clipboard ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_entry(entry_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM clipboard WHERE id = ?", (entry_id,)
        ).fetchone()
    return row["content"] if row else None


def clear_all():
    with get_conn() as conn:
        conn.execute("DELETE FROM clipboard")
