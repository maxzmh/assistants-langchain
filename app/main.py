"""
FastAPI 应用装配：挂载路由、启动时初始化 Postgres 资源。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000

依赖环境变量：
    POSTGRES_URL           Postgres DSN，见 app/config.py。
    CORS_ALLOW_ORIGINS     逗号分隔的前端来源白名单，默认放开常见 Vite dev 端口。
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI(title="cook-agent api", lifespan=lifespan)

# 前后端分离：允许 Vite dev server 直接跨域调 /api。生产接入网关时可用同源反代替代。
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_origins = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", _default_origins).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(history_router)
app.include_router(chat_router)


@app.get("/")
def index():
    """健康检查：前后端分离后，页面由前端工程提供，这里只回一个简单标识。"""
    return {"service": "cook-agent api", "status": "ok"}
