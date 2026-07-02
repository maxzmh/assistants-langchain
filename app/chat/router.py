"""
chat 路由：POST /api/chat。

约定：async 层处理 UploadFile 读取；把纯字节交给同步的 media/chat 层。
"""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.chat import service as chat_service
from app.db import get_db
from app.media import service as media
from app.sessions import service as sessions_service

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(
    message: str = Form(""),
    session_id: str = Form("default"),
    image: Optional[UploadFile] = File(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    """接收一条用户消息（含可选图片）+ session_id，以 SSE 流式返回模型回复。

    图片来源支持三种（可混用）：
    1) `image` 表单字段：本地上传的图片文件（base64 内联给模型）
    2) `message` 文本里出现的 http(s) 图片 URL：自动抽出后直接以 URL 形式给模型
    3) 无图片：纯文本
    """
    # 读取上传图片为纯字节（async 边界）
    image_bytes: Optional[bytes] = None
    image_mime: Optional[str] = None
    if image is not None:
        image_bytes = await image.read()
        image_mime = image.content_type

    # 抽 URL 图片 + 组多模态 content（纯函数）
    text_only, url_list = media.extract_image_urls(message)
    content = media.build_content(text_only, image_bytes, image_mime, url_list, original_message=message)

    # 空校验：无文本 + 无任何图片
    if isinstance(content, str) and not content.strip():
        raise HTTPException(status_code=400, detail="empty message")

    # 登记 / 更新会话（首条消息作为标题）
    title = (text_only or message or "图片消息").strip()[:20] or "图片消息"
    sessions_service.touch(conn, session_id, title=title)

    return StreamingResponse(
        chat_service.stream_reply(session_id, content),
        media_type="text/event-stream",
    )
