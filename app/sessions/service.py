"""
sessions 业务层：会话元数据的登记、更新、列举、删除。

存储走 `app.pg` 里的 async 连接池；这里只处理业务判断与时间生成。
删除会话时会连带清掉 checkpointer 里的 thread 数据（由 history 层负责）。
"""
from datetime import datetime
from typing import List, Optional

from app.pg import get_pool
from app.sessions import db as sessions_db
from app.history import service as history_service


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


async def save(session_id: str, title: str = "新对话") -> None:
    """登记一个新会话（已存在则忽略）。"""
    await sessions_db.insert_if_absent(get_pool(), session_id, title, _now())


async def touch(session_id: str, title: Optional[str] = None) -> None:
    """更新 updated_at；若该会话标题仍是默认值且传入了 title，则一并更新标题。

    如果会话不存在，先兜底登记一条。
    """
    now = _now()
    pool = get_pool()
    await sessions_db.insert_if_absent(pool, session_id, title or "新对话", now)
    if title:
        await sessions_db.update_title_and_time(pool, session_id, title, now)
    else:
        await sessions_db.update_time(pool, session_id, now)


async def list_all() -> List[dict]:
    return await sessions_db.select_all(get_pool())


async def delete(session_id: str) -> None:
    """删除会话元数据 + 其全部消息 / checkpoint。"""
    await history_service.clear(session_id)   # 清 checkpointer 里的 thread
    await sessions_db.delete(get_pool(), session_id)
