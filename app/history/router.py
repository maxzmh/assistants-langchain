"""
history 路由：读取会话消息 / 清空会话。
"""
from fastapi import APIRouter, Form

from app.history import service

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
async def get_history_api(session_id: str):
    """读取某会话的消息记录（切换会话时回显）。"""
    return {"messages": await service.serialize(session_id)}


@router.post("/clear")
async def clear(session_id: str = Form("default")):
    """清空指定会话的消息（保留会话条目）。"""
    await service.clear(session_id)
    return {"ok": True}


@router.post("/message/delete")
async def delete_message_api(
    session_id: str = Form(...), message_id: str = Form(...)
):
    """删除指定会话中的某一条消息：checkpoint 软删 + message_store 硬删。"""
    deleted = await service.delete_one(session_id, message_id)
    return {"ok": True, "deleted": deleted}
