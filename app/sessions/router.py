"""
sessions 路由：登记 / 列举 / 删除。
"""
import sqlite3

from fastapi import APIRouter, Depends, Form

from app.db import get_db
from app.sessions import service

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/session")
def create_session(session_id: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    """登记一个新会话（新建即保存）。"""
    service.save(conn, session_id)
    return {"ok": True}


@router.get("/sessions")
def get_sessions(conn: sqlite3.Connection = Depends(get_db)):
    """列出全部历史会话（按最近更新排序）。"""
    return {"sessions": service.list_all(conn)}


@router.post("/delete")
def delete_session(session_id: str = Form(...), conn: sqlite3.Connection = Depends(get_db)):
    """删除某个会话（连同其消息）。"""
    service.delete(conn, session_id)
    return {"ok": True}
