"""
sessions 表的低层 SQL：建表 + CRUD，不含业务判断。
"""
import sqlite3
from typing import List


def init(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            title      TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def insert_if_absent(conn: sqlite3.Connection, session_id: str, title: str, now: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    conn.commit()


def update_title_and_time(conn: sqlite3.Connection, session_id: str, title: str, now: str) -> None:
    """更新 updated_at；若原标题仍为默认 '新对话' 才更新 title。"""
    conn.execute(
        "UPDATE sessions SET updated_at = ?, "
        "title = CASE WHEN title = '新对话' THEN ? ELSE title END "
        "WHERE session_id = ?",
        (now, title, session_id),
    )
    conn.commit()


def update_time(conn: sqlite3.Connection, session_id: str, now: str) -> None:
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()


def select_all(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT session_id, title, created_at, updated_at "
        "FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
