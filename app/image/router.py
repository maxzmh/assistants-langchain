"""
image 路由：文生图 + 静态图片文件回读。

  * POST /api/image/gen        —— 生成并落库；返回 {ok, image_url, user_id, ai_id, prompt}
  * GET  /api/image/file/{name} —— 服务 `static/generated/<name>` 单张图片

生图消息不进 checkpointer（跟对话 agent 隔离），只写 `message_store`：
一次生成 = 一条 HumanMessage（`[画图] <prompt>`）+ 一条 AIMessage（多模态 content
里带 image_url 段），前端历史回显时 `_to_frontend` 会自动拆出 text + image。
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.config import GENERATED_DIR
from app.history import service as history_service
from app.image import service as image_service
from app.sessions import service as sessions_service

router = APIRouter(prefix="/api/image", tags=["image"])

# 文件名白名单：允许小写字母 / 数字 / 短横线 / 下划线 + 扩展名。
# 目的是拒绝 `..` / 绝对路径 / 特殊字符，避免任何形式的路径穿越。
_SAFE_NAME_RE = re.compile(r"^[a-z0-9_-]+\.(png|jpe?g|webp)$", re.IGNORECASE)


@router.post("/gen")
async def gen(
    session_id: str = Form(...),
    prompt: str = Form(...),
    size: str = Form("2048x2048"),
    style: str = Form("natural"),
):
    """生图并落库；同步返回结果，不走 SSE。生图秒级、没有 delta 需要流式。"""
    prompt = (prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    try:
        result = await image_service.generate(prompt, size=size, style=style)
    except Exception as e:  # noqa: BLE001 —— 上游 API 报错统一转 502
        raise HTTPException(status_code=502, detail=f"生图失败: {e}") from e

    # 会话元数据：与 chat 那侧同步 touch，让侧边栏出现 / 更新时间。
    # 标题用「[画图] xxx」前 20 字，跟 chat 那边的截断策略保持一致。
    title = ("[画图] " + prompt)[:20]
    await sessions_service.touch(session_id, title=title)

    # 落 message_store：一条 human + 一条 ai。id 主动分配，供前端做单条删除。
    user_id = str(uuid.uuid4())
    ai_id = str(uuid.uuid4())
    user_msg = HumanMessage(content=f"[画图] {prompt}", id=user_id)
    ai_msg = AIMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": result.url}},
        ],
        id=ai_id,
    )
    history = history_service.get_history(session_id)
    await history.aadd_messages([user_msg, ai_msg])

    return {
        "ok": True,
        "image_url": result.url,
        "user_id": user_id,
        "ai_id": ai_id,
        "prompt": result.prompt,
    }


@router.get("/file/{name}")
async def get_file(name: str):
    """回读 `static/generated/<name>`。做严格文件名校验，杜绝路径穿越。"""
    if not _SAFE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="非法文件名")
    path: Path = GENERATED_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
