"""
FastAPI 应用装配：挂载路由（后续任务逐步加入）、启动时初始化数据库。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000
"""
from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(title="cook-agent web")


@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")
