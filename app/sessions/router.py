"""
sessions 路由：登记 / 列举 / 删除。
"""
from fastapi import APIRouter, Form

from app.sessions import service

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/session")
async def create_session(session_id: str = Form(...)):
    """登记一个新会话（新建即保存）。"""
    await service.save(session_id)
    return {"ok": True}


@router.get("/sessions")
async def get_sessions():
    """列出全部历史会话（按最近更新排序）。"""
    return {"sessions": await service.list_all()}


@router.post("/delete")
async def delete_session(session_id: str = Form(...)):
    """删除某个会话（连同其消息）。"""
    await service.delete(session_id)
    return {"ok": True}
