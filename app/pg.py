"""
Postgres 资源单例：async 连接池 + AsyncPostgresSaver + SQLAlchemy async engine。

三样资源共用同一个 Postgres 实例，但走不同的驱动栈：

  * `AsyncConnectionPool`   → 直接 psycopg，给 sessions 元数据表用（CRUD SQL）
  * `AsyncPostgresSaver`    → LangGraph checkpointer，落 agent 中间态 / 断点续跑
  * `AsyncEngine` (SQLAlchemy) → 给 SQLChatMessageHistory 用，托管前端展示的 human/ai 历史

生命周期：
  * `open_pool()`：FastAPI lifespan 进入时调用。建 pool → 建 saver → `saver.setup()`
    幂等建表 → 建 SA engine → `sessions_db.init()` 幂等建表。
  * `close_pool()`：lifespan 退出时反向清理。

runtime 消费：
  * `get_pool()`   → sessions 层借连接
  * `get_saver()`  → agent runner 装进 `create_agent(checkpointer=...)`
  * `get_engine()` → history 层构造 SQLChatMessageHistory

集中管理能避免循环 import，也避免多个模块各自维护开关状态。
"""
from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import POSTGRES_URL, POSTGRES_URL_SA

_pool: Optional[AsyncConnectionPool] = None
_saver: Optional[AsyncPostgresSaver] = None
_engine: Optional[AsyncEngine] = None


# AsyncPostgresSaver 官方要求的连接参数：
#   * autocommit=True   → checkpointer 内部管理事务，交由驱动帮忙 commit 会造成死锁
#   * prepare_threshold=0 → 与 pgbouncer/连接复用兼容，避免 prepared statement 泄漏
_CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": 0}


async def open_pool() -> None:
    """建立连接池 + SA engine，完成 saver / sessions 表的一次性初始化。幂等。"""
    global _pool, _saver, _engine
    if _pool is not None:
        return

    pool = AsyncConnectionPool(
        conninfo=POSTGRES_URL,
        max_size=20,
        kwargs=_CONNECTION_KWARGS,
        open=False,  # 3.2+ 起显式 open() 才不会告警
    )
    await pool.open()
    _pool = pool

    _saver = AsyncPostgresSaver(pool)
    await _saver.setup()

    # SQLChatMessageHistory 用的 async engine。pool_pre_ping 防止连接被 pg 端主动断开后拿到僵尸连接。
    _engine = create_async_engine(POSTGRES_URL_SA, pool_pre_ping=True)

    # 延迟导入避免循环依赖：sessions.db 反过来 import app.pg 拿 pool。
    from app.sessions import db as sessions_db
    await sessions_db.init(pool)


async def close_pool() -> None:
    """关闭 SA engine + 连接池。saver 无需手动 close：它只是持有 pool 的引用。"""
    global _pool, _saver, _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _pool is not None:
        await _pool.close()
        _pool = None
    _saver = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("pg pool 未初始化，请确认 FastAPI lifespan 已启动")
    return _pool


def get_saver() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("AsyncPostgresSaver 未初始化，请确认 FastAPI lifespan 已启动")
    return _saver


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("SQLAlchemy engine 未初始化，请确认 FastAPI lifespan 已启动")
    return _engine
