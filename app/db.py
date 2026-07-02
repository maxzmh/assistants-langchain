"""
SQLite 连接依赖：yield 一个短命 Connection，请求结束自动关闭。
"""
import sqlite3
from typing import Generator

from app.config import DB_PATH


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI 依赖：给路由提供一个 sqlite3 连接，退出时关闭。"""
    # check_same_thread=False：async 端点里 get_db 依赖在线程池线程创建连接，
    # 而端点主体在事件循环线程使用它，需放开 sqlite 的同线程限制。
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
