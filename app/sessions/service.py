"""
sessions 业务层：会话元数据的登记、更新、列举、删除。
"""
import sqlite3
from datetime import datetime
from typing import List, Optional

from app.sessions import db as sessions_db
from app.history import service as history_service


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def save(conn: sqlite3.Connection, session_id: str, title: str = "新对话") -> None:
    """登记一个新会话（已存在则忽略）。"""
    sessions_db.insert_if_absent(conn, session_id, title, _now())


def touch(conn: sqlite3.Connection, session_id: str, title: Optional[str] = None) -> None:
    """更新 updated_at；若该会话标题仍是默认值且传入了 title，则一并更新标题。

    如果会话不存在，先兜底登记一条。
    """
    now = _now()
    sessions_db.insert_if_absent(conn, session_id, title or "新对话", now)
    if title:
        sessions_db.update_title_and_time(conn, session_id, title, now)
    else:
        sessions_db.update_time(conn, session_id, now)


def list_all(conn: sqlite3.Connection) -> List[dict]:
    return sessions_db.select_all(conn)


def delete(conn: sqlite3.Connection, session_id: str) -> None:
    """删除会话元数据 + 其全部消息。"""
    history_service.clear(session_id)  # 唯一跨包调用
    sessions_db.delete(conn, session_id)
