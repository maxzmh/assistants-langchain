"""
FastAPI 应用装配：挂载路由、启动时初始化 Postgres 资源。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000

依赖环境变量：
    POSTGRES_URL   Postgres DSN，见 app/config.py。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import pg
from app.chat.router import router as chat_router
from app.history.router import router as history_router
from app.sessions.router import router as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时开连接池 + 建表；退出时关连接池。"""
    await pg.open_pool()
    try:
        yield
    finally:
        await pg.close_pool()


app = FastAPI(title="cook-agent web", lifespan=lifespan)

app.include_router(sessions_router)
app.include_router(history_router)
app.include_router(chat_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")
