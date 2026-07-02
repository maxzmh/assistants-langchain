"""
SQLite 连接依赖：yield 一个短命 Connection，请求结束自动关闭。
"""
import sqlite3
from typing import Generator

from app.config import DB_PATH


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI 依赖：给路由提供一个 sqlite3 连接，退出时关闭。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
