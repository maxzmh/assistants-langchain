"""
history 路由：读取会话消息 / 清空会话。
"""
from fastapi import APIRouter, Form

from app.history import service

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
def get_history_api(session_id: str):
    """读取某会话的消息记录（切换会话时回显）。"""
    return {"messages": service.serialize(session_id)}


@router.post("/clear")
def clear(session_id: str = Form("default")):
    """清空指定会话的消息（保留会话条目）。"""
    service.clear(session_id)
    return {"ok": True}
