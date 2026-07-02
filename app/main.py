"""
FastAPI 应用装配：挂载路由、启动时初始化数据库。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000
"""
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.chat.router import router as chat_router
from app.config import DB_PATH
from app.history.router import router as history_router
from app.sessions import db as sessions_db
from app.sessions.router import router as sessions_router

app = FastAPI(title="cook-agent web")


@app.on_event("startup")
def _init_db() -> None:
    """启动时建表（幂等）。"""
    with sqlite3.connect(DB_PATH) as conn:
        sessions_db.init(conn)


app.include_router(sessions_router)
app.include_router(history_router)
app.include_router(chat_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")
