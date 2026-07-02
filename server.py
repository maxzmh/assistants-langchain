"""
Web 后端：FastAPI + 豆包多模态模型，支持流式对话、图片上传与多轮记忆。

接口：
- GET  /              返回前端页面
- POST /api/session   登记一个新会话（新建即保存）
- GET  /api/sessions  列出全部历史会话
- GET  /api/history   读取某会话的消息记录（用于切换会话时回显）
- POST /api/chat      接收文本（+可选图片）+ session_id，以 SSE 流式返回模型回复
- POST /api/clear     清空指定会话的消息
- POST /api/delete    删除某个会话（连同其消息）

记忆：按 session_id 持久化到 SQLite（chat_history.db），服务重启后历史仍在。
会话元数据（标题、时间）存于 sessions 表，消息存于 message_store 表。

运行方式：
    .venv/bin/uvicorn server:app --reload --port 8000
然后浏览器打开 http://127.0.0.1:8000
"""
import base64
import json
import re
import sqlite3
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import get_llm

app = FastAPI(title="cook-agent web")

SYSTEM_PROMPT = "你是一位资深美食家助手，乐于用亲切的口吻解答做菜相关的问题。若用户上传了图片，请结合图片内容作答。"

# 从消息文本里抽取图片 URL：http(s) 结尾为常见图片扩展名，或明显的图床/静态托管路径。
# 只识别 URL 边界很清晰的场景，避免把普通文字里的链接误当图片。
_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>\"'，,、]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\s<>\"'，,、]*)?",
    re.IGNORECASE,
)


def extract_image_urls(text: str) -> Tuple[str, List[str]]:
    """从用户文本里抽出图片 URL 列表，并返回 (剥离 URL 后的文本, URL 列表)。"""
    urls = _IMAGE_URL_RE.findall(text or "")
    if not urls:
        return text, []
    cleaned = _IMAGE_URL_RE.sub("", text).strip()
    # 去重并保留顺序
    seen: set = set()
    uniq: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return cleaned, uniq

# 对话历史与会话元数据都持久化到这个 SQLite 文件
DB_FILE = "chat_history.db"
DB_URL = f"sqlite:///{DB_FILE}"


# ——————————————————— 会话元数据（sessions 表） ———————————————————

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化 sessions 表（消息表由 SQLChatMessageHistory 自动建）。"""
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title      TEXT NOT NULL DEFAULT '新对话',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def save_session(session_id: str, title: str = "新对话") -> None:
    """登记一个新会话（已存在则忽略）。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, title, now, now),
        )


def touch_session(session_id: str, title: Optional[str] = None) -> None:
    """更新会话的 updated_at；若该会话标题仍是默认值且传入了 title，则一并更新标题。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _db() as conn:
        # 不存在则补登记一条（兜底）
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (session_id, title or "新对话", now, now),
        )
        if title:
            conn.execute(
                "UPDATE sessions SET updated_at = ?, "
                "title = CASE WHEN title = '新对话' THEN ? ELSE title END "
                "WHERE session_id = ?",
                (now, title, session_id),
            )
        else:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )


def list_sessions() -> List[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT session_id, title, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """删除会话元数据 + 其全部消息。"""
    get_history(session_id).clear()  # 删消息
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


# ——————————————————— 对话（带 SQLite 记忆） ———————————————————

def get_history(session_id: str) -> BaseChatMessageHistory:
    """根据 session_id 返回基于 SQLite 的对话历史。"""
    return SQLChatMessageHistory(session_id=session_id, connection=DB_URL)


def serialize_messages(session_id: str) -> List[dict]:
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


# 启动时初始化数据库
init_db()
llm = get_llm()


# ——————————————————— 路由 ———————————————————

@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")


@app.post("/api/session")
async def create_session(session_id: str = Form(...)):
    """登记一个新会话（新建即保存）。"""
    save_session(session_id)
    return {"ok": True}


@app.get("/api/sessions")
async def get_sessions():
    """列出全部历史会话（按最近更新排序）。"""
    return {"sessions": list_sessions()}


@app.get("/api/history")
async def get_history_api(session_id: str):
    """读取某会话的消息记录（切换会话时回显）。"""
    return {"messages": serialize_messages(session_id)}


@app.post("/api/chat")
async def chat(
    message: str = Form(""),
    session_id: str = Form("default"),
    image: Optional[UploadFile] = File(None),
):
    """接收一条用户消息（含可选图片）+ session_id，以 SSE 流式返回模型回复。

    图片来源支持三种（可混用）：
    1) `image` 表单字段：本地上传的图片文件（base64 内联给模型）
    2) `message` 文本里出现的 http(s) 图片 URL：自动抽出后直接以 URL 形式给模型
    3) 无图片：纯文本

    同一 session_id 的多次请求共享对话历史，从而实现多轮记忆。
    """
    # 从文本里抽出图片 URL，剩下的文本单独作为 text 部分
    text_only, url_images = extract_image_urls(message)

    parts: List[dict] = []
    # 上传的图片（base64 内联）
    if image is not None:
        raw = await image.read()
        b64 = base64.b64encode(raw).decode("utf-8")
        mime = image.content_type or "image/jpeg"
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    # 文本中提到的图片 URL（直接把 URL 传给模型，让平台自行拉取）
    for url in url_images:
        parts.append({"type": "image_url", "image_url": {"url": url}})

    if parts:
        # 有图片：走多模态 content。文本部分为空时给一个默认提示，避免只有图片没问题。
        text_prompt = text_only or message.strip() or "请描述并分析这张图片。"
        content = [{"type": "text", "text": text_prompt}] + parts
    else:
        content = message

    # 用首条用户消息作为会话标题（截断），并刷新更新时间
    title = (text_only or message or "图片消息").strip()[:20] or "图片消息"
    touch_session(session_id, title=title)

    user_msg = HumanMessage(content=content)

    # 手动管理历史：读历史 → 拼上下文 → 流式生成并累积 → 把本轮 human + ai 写回库。
    # （比起 RunnableWithMessageHistory 自动聚合流式块，这样能确保 AI 回复完整落库。）
    history = get_history(session_id)
    prompt_messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(history.messages) + [user_msg]

    def event_stream():
        parts: List[str] = []
        for chunk in llm.stream(prompt_messages):
            text = chunk.content
            if text:
                parts.append(text)
                # JSON 编码以避免文本中的换行破坏 SSE 帧格式
                yield f"data: {json.dumps({'delta': text}, ensure_ascii=False)}\n\n"
        # 流结束后把这一轮对话写回 SQLite
        history.add_message(user_msg)
        history.add_message(AIMessage(content="".join(parts)))
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/clear")
async def clear(session_id: str = Form("default")):
    """清空指定会话的消息（保留会话条目）。"""
    get_history(session_id).clear()
    return {"ok": True}


@app.post("/api/delete")
async def delete(session_id: str = Form(...)):
    """删除某个会话（连同其消息）。"""
    delete_session(session_id)
    return {"ok": True}
