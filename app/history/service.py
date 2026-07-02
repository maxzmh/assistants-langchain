"""
history 业务层：LangChain 消息历史的读、写、清空、序列化。
"""
from typing import List

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

from app.config import DB_URL


def get_history(session_id: str) -> BaseChatMessageHistory:
    """根据 session_id 返回基于 SQLite 的对话历史。"""
    return SQLChatMessageHistory(session_id=session_id, connection=DB_URL)


def serialize(session_id: str) -> List[dict]:
    """把某会话的消息转成前端易渲染的结构：[{role, text, image}]。"""
    out: List[dict] = []
    for m in get_history(session_id).messages:
        role = "user" if m.type == "human" else "bot"
        text, image = "", None
        if isinstance(m.content, str):
            text = m.content
        elif isinstance(m.content, list):
            # 多模态内容：拆出文本与图片
            for part in m.content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text += part.get("text", "")
                elif part.get("type") == "image_url":
                    image = part.get("image_url", {}).get("url")
        out.append({"role": role, "text": text, "image": image})
    return out


def clear(session_id: str) -> None:
    """清空某会话的所有消息。"""
    get_history(session_id).clear()
