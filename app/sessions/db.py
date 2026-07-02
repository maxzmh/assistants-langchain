"""
sessions 表的低层 SQL：建表 + CRUD，不含业务判断。

Postgres 版：语法与 SQLite 版基本对齐，只是
  * 占位符 ? → %s
  * INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
  * 通过连接池借 async 连接
时间戳继续用 TEXT + ISO 字符串，避免业务层同步改动。
"""
from typing import List

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def init(pool: AsyncConnectionPool) -> None:
    """建表（幂等）。"""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title      TEXT NOT NULL DEFAULT '新对话',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )


async def insert_if_absent(
    pool: AsyncConnectionPool, session_id: str, title: str, now: str
) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO sessions (session_id, title, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (session_id) DO NOTHING",
                (session_id, title, now, now),
            )


async def update_title_and_time(
    pool: AsyncConnectionPool, session_id: str, title: str, now: str
) -> None:
    """更新 updated_at；若原标题仍为默认 '新对话' 才更新 title。"""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sessions SET updated_at = %s, "
                "title = CASE WHEN title = '新对话' THEN %s ELSE title END "
                "WHERE session_id = %s",
                (now, title, session_id),
            )


async def update_time(pool: AsyncConnectionPool, session_id: str, now: str) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sessions SET updated_at = %s WHERE session_id = %s",
                (now, session_id),
            )


async def select_all(pool: AsyncConnectionPool) -> List[dict]:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT session_id, title, created_at, updated_at "
                "FROM sessions ORDER BY updated_at DESC"
            )
            return await cur.fetchall()


async def delete(pool: AsyncConnectionPool, session_id: str) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM sessions WHERE session_id = %s", (session_id,)
            )
