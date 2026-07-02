# cook-agent 重构解耦实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 275 行的 `server.py` 按功能拆成 `app/` 下的 4 个功能包（sessions / history / media / chat），前端 `index.html` 内联的 CSS/JS 抽成独立文件，行为完全保持不变。

**Architecture:** 后端每个功能包自带 `router.py` + `service.py` + `db.py`（media 只有纯函数 service）；包间只允许 `import 对方.service`；SQLite 连接由 FastAPI `Depends(get_db)` 注入到 service。前端只做搬家式拆分，无构建工具。

**Tech Stack:** FastAPI + LangChain (`langchain-community`, `langchain-openai`) + SQLite (`sqlite3` + `SQLChatMessageHistory`) + 原生 HTML/CSS/JS。

**Spec:** `docs/superpowers/specs/2026-07-02-refactor-decoupling-design.md`

**No-tests notice:** Spec 明确"不补单元测试；只做冒烟"，本计划遵循，每个任务以 curl/import 冒烟收尾。

---

## Task 1: 建立 `app/` 骨架并让空应用能启动

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/db.py`
- Create: `app/main.py`

- [ ] **Step 1: 创建 `app/__init__.py`（空文件）**

```bash
mkdir -p app
: > app/__init__.py
```

- [ ] **Step 2: 写 `app/config.py`——从旧 `config.py` 迁过来并加 `DB_PATH`**

```python
"""
LangChain + Doubao 配置：LLM 工厂 + 全局路径常量。
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# 数据库文件路径：可用环境变量 COOK_DB_PATH 覆盖，默认落在项目根。
DB_PATH: str = os.getenv("COOK_DB_PATH", "chat_history.db")
DB_URL: str = f"sqlite:///{DB_PATH}"


def get_llm(**kwargs) -> ChatOpenAI:
    """返回配置好的 Doubao-Seed-2.1-pro 聊天模型实例。"""
    return ChatOpenAI(
        model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
        api_key=os.getenv("ARK_API_KEY"),
        base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        temperature=kwargs.pop("temperature", 0.7),
        **kwargs,
    )
```

- [ ] **Step 3: 写 `app/db.py`——FastAPI 依赖注入连接**

```python
"""
SQLite 连接依赖：yield 一个短命 Connection，请求结束自动关闭。
"""
import sqlite3
from typing import Generator

from app.config import DB_PATH


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI 依赖：给路由提供一个 sqlite3 连接，退出时关闭。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
```

- [ ] **Step 4: 写最小可启动 `app/main.py`**

```python
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
```

- [ ] **Step 5: 冒烟验证——空应用能启动并返回首页**

Run:
```bash
.venv/bin/python -c "from app.main import app; print(app.title)"
```
Expected: `cook-agent web`

- [ ] **Step 6: 提交**

```bash
git add app/
git commit -m "refactor: bootstrap app/ package with config, db, main skeleton

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 迁移 sessions 功能包

**Files:**
- Create: `app/sessions/__init__.py`
- Create: `app/sessions/db.py`
- Create: `app/sessions/service.py`
- Create: `app/sessions/router.py`
- Modify: `app/main.py`（include router + 启动建表）

- [ ] **Step 1: 创建目录**

```bash
mkdir -p app/sessions
: > app/sessions/__init__.py
```

- [ ] **Step 2: 写 `app/sessions/db.py`——纯 SQL 低层函数**

```python
"""
sessions 表的低层 SQL：建表 + CRUD，不含业务判断。
"""
import sqlite3
from typing import List, Optional


def init(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
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
    conn.commit()


def insert_if_absent(conn: sqlite3.Connection, session_id: str, title: str, now: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (session_id, title, now, now),
    )
    conn.commit()


def update_title_and_time(conn: sqlite3.Connection, session_id: str, title: str, now: str) -> None:
    """更新 updated_at；若原标题仍为默认 '新对话' 才更新 title。"""
    conn.execute(
        "UPDATE sessions SET updated_at = ?, "
        "title = CASE WHEN title = '新对话' THEN ? ELSE title END "
        "WHERE session_id = ?",
        (now, title, session_id),
    )
    conn.commit()


def update_time(conn: sqlite3.Connection, session_id: str, now: str) -> None:
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()


def select_all(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT session_id, title, created_at, updated_at "
        "FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
```

- [ ] **Step 3: 写 `app/sessions/service.py`——业务规则层**

跨包只调 `history.service.clear`，方向合理（"删会话"是 sessions 领域完整操作）。

```python
"""
sessions 业务层：会话元数据的登记、更新、列举、删除。
"""
import sqlite3
from datetime import datetime
from typing import List, Optional

from app.sessions import db as sessions_db
from app.history import service as history_service


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def save(conn: sqlite3.Connection, session_id: str, title: str = "新对话") -> None:
    """登记一个新会话（已存在则忽略）。"""
    sessions_db.insert_if_absent(conn, session_id, title, _now())


def touch(conn: sqlite3.Connection, session_id: str, title: Optional[str] = None) -> None:
    """更新 updated_at；若该会话标题仍是默认值且传入了 title，则一并更新标题。

    如果会话不存在，先兜底登记一条。
    """
    now = _now()
    sessions_db.insert_if_absent(conn, session_id, title or "新对话", now)
    if title:
        sessions_db.update_title_and_time(conn, session_id, title, now)
    else:
        sessions_db.update_time(conn, session_id, now)


def list_all(conn: sqlite3.Connection) -> List[dict]:
    return sessions_db.select_all(conn)


def delete(conn: sqlite3.Connection, session_id: str) -> None:
    """删除会话元数据 + 其全部消息。"""
    history_service.clear(session_id)  # 唯一跨包调用
    sessions_db.delete(conn, session_id)
```

**注意：**`history_service.clear` 会在 Task 3 建好。为让本任务 import 能通过，先在 Task 3 前跑 import 会失败——这是预期的，Task 3 完成后就通了。

- [ ] **Step 4: 写 `app/sessions/router.py`——三个路由**

```python
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
```

- [ ] **Step 5: 更新 `app/main.py`——启动建表 + include router**

替换 `app/main.py` 的整个文件：

```python
"""
FastAPI 应用装配：挂载路由、启动时初始化数据库。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000
"""
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import DB_PATH
from app.sessions import db as sessions_db
from app.sessions.router import router as sessions_router

app = FastAPI(title="cook-agent web")


@app.on_event("startup")
def _init_db() -> None:
    """启动时建表（幂等）。"""
    with sqlite3.connect(DB_PATH) as conn:
        sessions_db.init(conn)


app.include_router(sessions_router)


@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")
```

- [ ] **Step 6: 冒烟验证——启动服务并读取会话列表**

先停掉之前的 uvicorn（如果还在跑）：

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

启动：

```bash
.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 2
curl -sS -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/api/sessions | head -c 500
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

Expected: HTTP 200，能看到旧 `chat_history.db` 里已存在的会话列表 JSON。

**注意**：此时 sessions.service 会 import history.service，如果 Task 3 还没做，服务启动就会 ImportError。**建议 Task 2 与 Task 3 连续做**，只在 Task 3 结束后跑冒烟。或者临时把 sessions.service 里的 `history_service.clear(session_id)` 那一行注释掉，等 Task 3 再打开。

- [ ] **Step 7: 提交**

```bash
git add app/sessions/ app/main.py
git commit -m "refactor: extract sessions package (db/service/router)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 迁移 history 功能包

**Files:**
- Create: `app/history/__init__.py`
- Create: `app/history/service.py`
- Create: `app/history/router.py`
- Modify: `app/main.py`（include history router）

- [ ] **Step 1: 创建目录**

```bash
mkdir -p app/history
: > app/history/__init__.py
```

- [ ] **Step 2: 写 `app/history/service.py`——封装 SQLChatMessageHistory**

```python
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
```

- [ ] **Step 3: 写 `app/history/router.py`——两个路由**

```python
"""
history 路由：读取会话消息 / 清空会话。
"""
from fastapi import APIRouter, Form

from app.history import service

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
def get_history_api(session_id: str):
    """读取某会话的消息记录（切换会话时回显）。"""
    return {"messages": service.serialize(session_id)}


@router.post("/clear")
def clear(session_id: str = Form("default")):
    """清空指定会话的消息（保留会话条目）。"""
    service.clear(session_id)
    return {"ok": True}
```

- [ ] **Step 4: 修改 `app/main.py`——include history router**

Modify `app/main.py`：在 `from app.sessions.router import router as sessions_router` 下方增加一行 import，并在 `app.include_router(sessions_router)` 下方新增一行 include。

替换整块（保持其余不变）：

```python
from app.sessions import db as sessions_db
from app.sessions.router import router as sessions_router
from app.history.router import router as history_router
```

以及：

```python
app.include_router(sessions_router)
app.include_router(history_router)
```

- [ ] **Step 5: 冒烟验证——history 与 sessions 全通**

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 2
# 读一个已存在的会话消息
SID=$(curl -sS http://127.0.0.1:8000/api/sessions | python -c "import sys,json;print(json.load(sys.stdin)['sessions'][0]['session_id'])")
curl -sS -w "\nHTTP %{http_code}\n" "http://127.0.0.1:8000/api/history?session_id=$SID" | head -c 500
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

Expected: HTTP 200，返回 `{"messages": [...]}`，能看到该会话的历史。

- [ ] **Step 6: 提交**

```bash
git add app/history/ app/main.py
git commit -m "refactor: extract history package (service/router)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 迁移 media 功能包（纯函数）

**Files:**
- Create: `app/media/__init__.py`
- Create: `app/media/service.py`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p app/media
: > app/media/__init__.py
```

- [ ] **Step 2: 写 `app/media/service.py`——两个纯函数**

`build_content` 收 `image_bytes` + `image_mime`（而不是 `UploadFile`），保持本层同步、无 IO。

```python
"""
media 服务：从文本抽取图片 URL、把文本 + 图片装成多模态 content。

约定：本模块纯函数、无 IO、无副作用。上传文件由 router 层预先读成 bytes。
"""
import base64
import re
from typing import List, Optional, Tuple, Union

# 从消息文本里抽取图片 URL：http(s) 结尾为常见图片扩展名，或明显的图床/静态托管路径。
# 只识别 URL 边界很清晰的场景，避免把普通文字里的链接误当图片。
_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>\"'，,、]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\s<>\"'，,、]*)?",
    re.IGNORECASE,
)


def extract_image_urls(text: str) -> Tuple[str, List[str]]:
    """从用户文本里抽出图片 URL 列表，返回 (剥离 URL 后的文本, 去重后的 URL 列表)。"""
    urls = _IMAGE_URL_RE.findall(text or "")
    if not urls:
        return text, []
    cleaned = _IMAGE_URL_RE.sub("", text).strip()
    seen: set = set()
    uniq: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return cleaned, uniq


def build_content(
    text: str,
    image_bytes: Optional[bytes],
    image_mime: Optional[str],
    urls: List[str],
    original_message: str = "",
) -> Union[str, List[dict]]:
    """组装 LangChain HumanMessage 的 content：

    - 无图片 → 返回原始字符串（等价于 message 本身）。
    - 有图片 → 返回 [{'type':'text',...}, {'type':'image_url',...}, ...]。
      如果 text 为空（用户只上传了图片），给一个默认提示。
    """
    parts: List[dict] = []
    if image_bytes is not None:
        mime = image_mime or "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    for url in urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})

    if not parts:
        # 无图片：直接把原始消息作为字符串给模型（保持与旧行为一致）
        return original_message or text

    text_prompt = text or (original_message.strip() if original_message else "") or "请描述并分析这张图片。"
    return [{"type": "text", "text": text_prompt}] + parts
```

- [ ] **Step 3: 冒烟验证——纯函数可 import 且行为正确**

```bash
.venv/bin/python -c "
from app.media.service import extract_image_urls, build_content
t, urls = extract_image_urls('看这张 https://x.com/a.jpg 好看吗')
assert urls == ['https://x.com/a.jpg'], urls
assert t == '看这张  好看吗', repr(t)
# 无图片场景
c = build_content('你好', None, None, [], original_message='你好')
assert c == '你好', c
# 有 URL 图片场景
c = build_content('看这个', None, None, ['https://x.com/a.jpg'])
assert isinstance(c, list) and c[0]['type'] == 'text' and c[1]['type'] == 'image_url'
# 上传图片场景
c = build_content('', b'\\x89PNG', 'image/png', [])
assert isinstance(c, list) and c[1]['image_url']['url'].startswith('data:image/png;base64,')
print('media.service OK')
"
```

Expected: 输出 `media.service OK`，无 AssertionError。

- [ ] **Step 4: 提交**

```bash
git add app/media/
git commit -m "refactor: extract media package (pure functions)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 迁移 chat 功能包 + 删除 server.py

**Files:**
- Create: `app/chat/__init__.py`
- Create: `app/chat/prompts.py`
- Create: `app/chat/service.py`
- Create: `app/chat/router.py`
- Modify: `app/main.py`（include chat router）
- Delete: `server.py`

- [ ] **Step 1: 创建目录**

```bash
mkdir -p app/chat
: > app/chat/__init__.py
```

- [ ] **Step 2: 写 `app/chat/prompts.py`**

```python
"""聊天系统提示词。"""

SYSTEM_PROMPT: str = (
    "你是一位资深美食家助手，乐于用亲切的口吻解答做菜相关的问题。"
    "若用户上传了图片，请结合图片内容作答。"
)
```

- [ ] **Step 3: 写 `app/chat/service.py`——SSE 流式生成器**

签名与设计文档一致：`stream_reply(session_id, content) -> Generator[str, None, None]`。

```python
"""
chat 服务：构造 prompt、调 llm.stream、生成 SSE 帧、结束后写历史。

本模块是同步的（llm.stream 也是同步生成器）。
router 层负责把 UploadFile 转成 bytes 后再调 media/chat。
"""
import json
from typing import Generator, List, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.chat.prompts import SYSTEM_PROMPT
from app.config import get_llm
from app.history import service as history_service

# 单例：懒加载 LLM
_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = get_llm()
    return _llm


def stream_reply(session_id: str, content: Union[str, List[dict]]) -> Generator[str, None, None]:
    """生成 SSE 帧流：

    - 每个流式片段 -> `data: {"delta": "..."}\\n\\n`
    - 结束帧 -> `data: [DONE]\\n\\n`
    - 全部完成后把 human + ai 消息落库。
    - 出错时发一帧 `data: {"error": "..."}\\n\\n` 再 `[DONE]`。
    """
    history = history_service.get_history(session_id)
    user_msg = HumanMessage(content=content)
    prompt_messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(history.messages) + [user_msg]

    parts: List[str] = []
    try:
        for chunk in _get_llm().stream(prompt_messages):
            text = chunk.content
            if text:
                parts.append(text)
                # JSON 编码以避免文本中的换行破坏 SSE 帧格式
                yield f"data: {json.dumps({'delta': text}, ensure_ascii=False)}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    else:
        # 只有成功流完才落库（保持"AI 回复完整"的语义）
        history.add_message(user_msg)
        history.add_message(AIMessage(content="".join(parts)))
    yield "data: [DONE]\n\n"
```

- [ ] **Step 4: 写 `app/chat/router.py`——async 路由，负责化解 UploadFile**

```python
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
```

- [ ] **Step 5: 修改 `app/main.py`——include chat router**

在 `app/main.py` 的 imports 与 include 处新增：

```python
from app.chat.router import router as chat_router
```

以及：

```python
app.include_router(chat_router)
```

**替换后完整的 `app/main.py` 应为：**

```python
"""
FastAPI 应用装配：挂载路由、启动时初始化数据库。

启动方式：
    .venv/bin/python -m uvicorn app.main:app --port 8000
"""
import sqlite3

from fastapi import FastAPI
from fastapi.responses import FileResponse

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


@app.get("/")
def index():
    """返回前端单页。"""
    return FileResponse("static/index.html")
```

- [ ] **Step 6: 删除旧 `server.py`**

```bash
git rm server.py
```

- [ ] **Step 7: 冒烟验证——完整流程通**

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 3
# 首页
curl -sS -o /dev/null -w "index: %{http_code}\n" http://127.0.0.1:8000/
# 会话列表
curl -sS -o /dev/null -w "sessions: %{http_code}\n" http://127.0.0.1:8000/api/sessions
# 发一条消息，收前几帧 SSE
SID="smoke-$(date +%s)"
curl -sS -X POST -F "session_id=$SID" -F "message=一句话介绍番茄炒蛋" \
     -N http://127.0.0.1:8000/api/chat | head -c 400
echo
# 清理：删掉本次 smoke 会话
curl -sS -X POST -F "session_id=$SID" http://127.0.0.1:8000/api/delete
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

Expected：
- `index: 200`
- `sessions: 200`
- SSE 输出里能看到多帧 `data: {"delta": "..."}` 和最终 `data: [DONE]`。

- [ ] **Step 8: 提交**

```bash
git add app/chat/ app/main.py
git commit -m "refactor: extract chat package, remove server.py

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 前端拆成三文件 + 挂载 /static

**Files:**
- Create: `static/styles.css`
- Create: `static/app.js`
- Modify: `static/index.html`（删掉 `<style>`/`<script>` 主体，改为外链）
- Modify: `app/main.py`（`app.mount("/static", ...)`）

- [ ] **Step 1: 抽出 CSS 到 `static/styles.css`**

创建 `static/styles.css`，内容为原 `static/index.html` 第 8–162 行 `<style>` 里的 CSS（**逐字复制，不改任何选择器/变量**）：

```css
:root {
  --bg: #f5f6f8;
  --panel: #ffffff;
  --primary: #ff6b35;
  --primary-soft: #fff0e9;
  --text: #1f2329;
  --muted: #8a9099;
  --border: #ebedf0;
  --sidebar: #fafbfc;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--bg); color: var(--text); height: 100vh;
  display: flex; justify-content: center;
}
.app {
  width: 100%; max-width: 1040px; height: 100vh;
  display: flex; background: var(--panel);
}

/* —— 侧边栏：历史会话列表 —— */
.sidebar {
  width: 260px; flex-shrink: 0; background: var(--sidebar);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
}
.sidebar .top { padding: 14px; }
.new-btn {
  width: 100%; padding: 10px; border-radius: 10px; border: 1px solid var(--primary);
  background: var(--primary); color: #fff; cursor: pointer; font-size: 14px;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.new-btn:hover { opacity: .92; }
.session-list { flex: 1; overflow-y: auto; padding: 0 8px 12px; }
.session-list .label {
  font-size: 12px; color: var(--muted); padding: 6px 8px;
}
.session-item {
  display: flex; align-items: center; gap: 6px; padding: 9px 10px;
  border-radius: 8px; cursor: pointer; margin-bottom: 2px; font-size: 14px;
}
.session-item:hover { background: #eef0f2; }
.session-item.active { background: var(--primary-soft); color: var(--primary); }
.session-item .title {
  flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.session-item .del {
  border: none; background: transparent; cursor: pointer; color: var(--muted);
  font-size: 14px; opacity: 0; flex-shrink: 0; padding: 2px 4px; border-radius: 4px;
}
.session-item:hover .del { opacity: 1; }
.session-item .del:hover { background: rgba(0,0,0,.08); color: #e23; }
.empty-tip { font-size: 13px; color: var(--muted); padding: 12px 10px; }

/* —— 主区域：对话 —— */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
header {
  padding: 16px 20px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}
header .logo {
  width: 36px; height: 36px; border-radius: 10px;
  background: var(--primary); color: #fff; font-size: 20px;
  display: grid; place-items: center;
}
header h1 { font-size: 17px; font-weight: 600; }
header p { font-size: 12px; color: var(--muted); }

#messages {
  flex: 1; overflow-y: auto; padding: 20px;
  display: flex; flex-direction: column; gap: 16px;
}
.msg { display: flex; gap: 10px; max-width: 88%; }
.msg.user { align-self: flex-end; flex-direction: row-reverse; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; font-size: 16px;
}
.msg.user .avatar { background: var(--primary); color: #fff; }
.msg.bot .avatar { background: var(--primary-soft); }
.bubble {
  padding: 10px 14px; border-radius: 14px; line-height: 1.6;
  font-size: 15px; white-space: pre-wrap; word-break: break-word;
}
.msg.user .bubble { background: var(--primary); color: #fff; border-top-right-radius: 4px; }
.msg.bot .bubble { background: var(--bg); border-top-left-radius: 4px; }
.bubble img { max-width: 220px; border-radius: 10px; margin-bottom: 8px; display: block; }
.bubble .cursor { display: inline-block; width: 7px; height: 16px;
  background: var(--muted); animation: blink 1s steps(2) infinite; vertical-align: text-bottom; }
@keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }

/* —— Markdown 渲染样式（仅作用于助手消息）—— */
.bubble.md { white-space: normal; }
.bubble.md > :first-child { margin-top: 0; }
.bubble.md > :last-child { margin-bottom: 0; }
.bubble.md h1, .bubble.md h2, .bubble.md h3, .bubble.md h4 {
  margin: 14px 0 8px; line-height: 1.35; font-weight: 600;
}
.bubble.md h1 { font-size: 19px; }
.bubble.md h2 { font-size: 17px; }
.bubble.md h3 { font-size: 16px; color: var(--primary); }
.bubble.md h4 { font-size: 15px; }
.bubble.md p { margin: 8px 0; }
.bubble.md ul, .bubble.md ol { margin: 8px 0; padding-left: 22px; }
.bubble.md li { margin: 4px 0; }
.bubble.md li::marker { color: var(--primary); }
.bubble.md strong { font-weight: 600; }
.bubble.md em { font-style: italic; }
.bubble.md a { color: var(--primary); text-decoration: underline; }
.bubble.md hr { border: none; border-top: 1px solid var(--border); margin: 12px 0; }
.bubble.md blockquote {
  margin: 8px 0; padding: 4px 12px; border-left: 3px solid var(--primary);
  background: #fff; color: var(--muted); border-radius: 0 6px 6px 0;
}
.bubble.md code {
  background: #eef0f2; padding: 1px 5px; border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px;
}
.bubble.md pre {
  background: #1f2329; color: #e6e6e6; padding: 12px 14px; border-radius: 10px;
  overflow-x: auto; margin: 10px 0;
}
.bubble.md pre code { background: transparent; color: inherit; padding: 0; font-size: 13px; }
.bubble.md table { border-collapse: collapse; margin: 10px 0; width: 100%; font-size: 14px; }
.bubble.md th, .bubble.md td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
.bubble.md th { background: var(--primary-soft); }

.composer {
  border-top: 1px solid var(--border); padding: 12px 16px; flex-shrink: 0;
}
#preview {
  display: none; position: relative; width: 72px; height: 72px;
  margin-bottom: 10px; border-radius: 10px; overflow: hidden; border: 1px solid var(--border);
}
#preview img { width: 100%; height: 100%; object-fit: cover; }
#preview .remove {
  position: absolute; top: 2px; right: 2px; width: 20px; height: 20px;
  border-radius: 50%; background: rgba(0,0,0,.6); color: #fff; border: none;
  cursor: pointer; font-size: 13px; line-height: 20px; padding: 0;
}
.input-row { display: flex; align-items: flex-end; gap: 8px; }
.icon-btn {
  width: 40px; height: 40px; border-radius: 10px; border: 1px solid var(--border);
  background: #fff; cursor: pointer; font-size: 18px; flex-shrink: 0;
  display: grid; place-items: center; transition: .15s;
}
.icon-btn:hover { background: var(--bg); }
#text {
  flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; font-size: 15px; font-family: inherit; line-height: 1.5;
  max-height: 120px; outline: none;
}
#text:focus { border-color: var(--primary); }
#send { background: var(--primary); color: #fff; border: none; }
#send:disabled { opacity: .5; cursor: not-allowed; }
```

- [ ] **Step 2: 抽出 JS 到 `static/app.js`**

创建 `static/app.js`，内容为原 `static/index.html` 第 206–525 行 `<script>` 里的 JS（**逐字复制，不改任何变量名/逻辑**）：

```javascript
const messagesEl = document.getElementById('messages');
const textEl = document.getElementById('text');
const sendBtn = document.getElementById('send');
const fileInput = document.getElementById('file');
const uploadBtn = document.getElementById('uploadBtn');
const preview = document.getElementById('preview');
const previewImg = document.getElementById('previewImg');
const removeImg = document.getElementById('removeImg');
const newChatBtn = document.getElementById('newChat');
const sessionItems = document.getElementById('sessionItems');

let selectedFile = null;
let sessionId = null;       // 当前会话 id
let dirty = false;          // 当前会话是否已产生过消息

const WELCOME = '你好！我是你的美食家助手。问我任何做菜问题，也可以上传照片，或直接把图片链接贴在消息里让我帮你分析～';

function newId() {
  return 'web-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// —— 新建会话：立即在后端登记保存，并刷新列表 ——
// 若当前已是一个空会话（还没发过消息），则直接复用，避免连点产生一堆空会话。
async function createSession() {
  if (sessionId && !dirty) {
    messagesEl.innerHTML = '';
    addMessage('bot', { text: WELCOME });
    await loadSessions();
    return;
  }
  sessionId = newId();
  dirty = false;
  const form = new FormData();
  form.append('session_id', sessionId);
  try { await fetch('/api/session', { method: 'POST', body: form }); } catch (_) {}
  messagesEl.innerHTML = '';
  addMessage('bot', { text: WELCOME });
  await loadSessions();
}
newChatBtn.onclick = createSession;

// —— 加载并渲染历史会话列表 ——
async function loadSessions() {
  let sessions = [];
  try {
    const r = await fetch('/api/sessions');
    sessions = (await r.json()).sessions || [];
  } catch (_) {}
  sessionItems.innerHTML = '';
  if (!sessions.length) {
    sessionItems.innerHTML = '<div class="empty-tip">还没有历史会话</div>';
    return;
  }
  for (const s of sessions) {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.session_id === sessionId ? ' active' : '');
    const title = document.createElement('span');
    title.className = 'title';
    title.textContent = s.title || '新对话';
    const del = document.createElement('button');
    del.className = 'del';
    del.textContent = '🗑';
    del.title = '删除会话';
    del.onclick = (e) => { e.stopPropagation(); deleteSession(s.session_id); };
    item.appendChild(title);
    item.appendChild(del);
    item.onclick = () => switchSession(s.session_id);
    sessionItems.appendChild(item);
  }
}

// —— 切换会话：拉取该会话历史并回显 ——
async function switchSession(id) {
  if (id === sessionId) return;
  sessionId = id;
  dirty = true; // 已有历史的会话
  messagesEl.innerHTML = '';
  let msgs = [];
  try {
    const r = await fetch('/api/history?session_id=' + encodeURIComponent(id));
    msgs = (await r.json()).messages || [];
  } catch (_) {}
  if (!msgs.length) {
    addMessage('bot', { text: WELCOME });
  } else {
    for (const m of msgs) {
      addMessage(m.role, { text: m.text, imageUrl: m.image });
    }
  }
  loadSessions();
}

// —— 删除会话 ——
async function deleteSession(id) {
  if (!confirm('确定删除这个会话吗？')) return;
  const form = new FormData();
  form.append('session_id', id);
  try { await fetch('/api/delete', { method: 'POST', body: form }); } catch (_) {}
  if (id === sessionId) {
    await createSession();
  } else {
    await loadSessions();
  }
}

// —— 图片选择与预览 ——
uploadBtn.onclick = () => fileInput.click();
fileInput.onchange = () => {
  const f = fileInput.files[0];
  if (!f) return;
  selectedFile = f;
  previewImg.src = URL.createObjectURL(f);
  preview.style.display = 'block';
};
removeImg.onclick = () => {
  selectedFile = null;
  fileInput.value = '';
  preview.style.display = 'none';
};

// —— 文本框自适应高度 ——
textEl.addEventListener('input', () => {
  textEl.style.height = 'auto';
  textEl.style.height = Math.min(textEl.scrollHeight, 120) + 'px';
});

// —— Enter 发送 / Shift+Enter 换行 ——
textEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
sendBtn.onclick = send;

// —— 轻量 Markdown 渲染器（内置，无外部依赖；先转义 HTML 再解析，避免 XSS）——
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function renderInline(s) {
  let out = s.replace(/`([^`]+)`/g, (_, c) => '<code>' + c + '</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  return out;
}
function renderMarkdown(src) {
  const text = escapeHtml(src);
  const lines = text.split('\n');
  let html = '', i = 0;
  let listType = null;
  const closeList = () => { if (listType) { html += '</' + listType + '>'; listType = null; } };
  while (i < lines.length) {
    let line = lines[i];
    if (/^```/.test(line)) {
      closeList();
      i++;
      let code = '';
      while (i < lines.length && !/^```/.test(lines[i])) { code += lines[i] + '\n'; i++; }
      i++;
      html += '<pre><code>' + code.replace(/\n$/, '') + '</code></pre>';
      continue;
    }
    if (/^\s*---\s*$/.test(line)) { closeList(); html += '<hr>'; i++; continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { closeList(); const lv = h[1].length; html += '<h' + lv + '>' + renderInline(h[2]) + '</h' + lv + '>'; i++; continue; }
    if (/^&gt;\s?/.test(line)) {
      closeList();
      let quote = '';
      while (i < lines.length && /^&gt;\s?/.test(lines[i])) { quote += lines[i].replace(/^&gt;\s?/, '') + '\n'; i++; }
      html += '<blockquote>' + renderInline(quote.trim()).replace(/\n/g, '<br>') + '</blockquote>';
      continue;
    }
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ol) { if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + renderInline(ol[1]) + '</li>'; i++; continue; }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) { if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + renderInline(ul[1]) + '</li>'; i++; continue; }
    if (/^\s*$/.test(line)) { closeList(); i++; continue; }
    closeList();
    let para = line;
    i++;
    while (i < lines.length && !/^\s*$/.test(lines[i]) &&
           !/^(#{1,4}\s|&gt;\s?|```|\s*---\s*$|\s*\d+\.\s|\s*[-*+]\s)/.test(lines[i])) {
      para += '\n' + lines[i]; i++;
    }
    html += '<p>' + renderInline(para).replace(/\n/g, '<br>') + '</p>';
  }
  closeList();
  return html;
}

function addMessage(role, { text = '', imageUrl = null } = {}) {
  const msg = document.createElement('div');
  msg.className = 'msg ' + role;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? '🙂' : '🍳';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (imageUrl) {
    const img = document.createElement('img');
    img.src = imageUrl;
    bubble.appendChild(img);
  }
  const content = document.createElement('div');
  content.style.display = 'inline';
  if (role === 'bot') {
    bubble.classList.add('md');
    content.style.display = 'block';
    if (text) content.innerHTML = renderMarkdown(text);
  } else {
    content.textContent = text;
  }
  bubble.appendChild(content);
  msg.appendChild(avatar);
  msg.appendChild(bubble);
  messagesEl.appendChild(msg);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { bubble, content };
}

// —— 从文本里抽取图片 URL（与后端 _IMAGE_URL_RE 保持一致的规则）——
const IMAGE_URL_RE = /https?:\/\/[^\s<>"'，,、]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\s<>"'，,、]*)?/gi;
function extractImageUrls(text) {
  const urls = (text || '').match(IMAGE_URL_RE) || [];
  if (!urls.length) return { text, urls: [] };
  const cleaned = text.replace(IMAGE_URL_RE, '').trim();
  return { text: cleaned, urls: [...new Set(urls)] };
}

async function send() {
  const raw = textEl.value.trim();
  if (!raw && !selectedFile) return;

  const { text: cleanText, urls: pastedUrls } = extractImageUrls(raw);
  const bubbleImg = selectedFile
    ? URL.createObjectURL(selectedFile)
    : (pastedUrls[0] || null);
  const bubbleText = selectedFile ? raw : cleanText;

  addMessage('user', { text: bubbleText, imageUrl: bubbleImg });

  const form = new FormData();
  form.append('message', raw);
  form.append('session_id', sessionId);
  if (selectedFile) form.append('image', selectedFile);

  textEl.value = '';
  textEl.style.height = 'auto';
  selectedFile = null;
  fileInput.value = '';
  preview.style.display = 'none';
  sendBtn.disabled = true;

  const wasFirst = !dirty;
  dirty = true;

  const { bubble, content } = addMessage('bot', { text: '' });
  bubble.classList.add('streaming');
  let acc = '';

  try {
    const resp = await fetch('/api/chat', { method: 'POST', body: form });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') continue;
        try {
          const { delta } = JSON.parse(payload);
          acc += delta;
          content.innerHTML = renderMarkdown(acc) + '<span class="cursor"></span>';
          messagesEl.scrollTop = messagesEl.scrollHeight;
        } catch (_) {}
      }
    }
    content.innerHTML = renderMarkdown(acc);
  } catch (err) {
    content.innerHTML = renderMarkdown(acc + '\n\n[出错了：' + err.message + ']');
  } finally {
    bubble.classList.remove('streaming');
    sendBtn.disabled = false;
    textEl.focus();
    if (wasFirst) loadSessions();
  }
}

// —— 初始化：有历史会话则打开最近一个，否则新建一个 ——
(async function init() {
  let sessions = [];
  try {
    const r = await fetch('/api/sessions');
    sessions = (await r.json()).sessions || [];
  } catch (_) {}
  if (sessions.length) {
    await switchSession(sessions[0].session_id);
  } else {
    await createSession();
  }
})();
```

- [ ] **Step 3: 精简 `static/index.html`**

用外链替换内联 `<style>` 和 `<script>`。把 `static/index.html` 整个替换为：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>美食家助手</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <div class="app">
    <!-- 侧边栏：历史会话 -->
    <aside class="sidebar">
      <div class="top">
        <button class="new-btn" id="newChat">＋ 新对话</button>
      </div>
      <div class="session-list">
        <div class="label">历史会话</div>
        <div id="sessionItems"></div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <header>
        <div class="logo">🍳</div>
        <div style="flex:1">
          <h1>美食家助手</h1>
          <p>Doubao-Seed-2.1-pro · 支持图片识别 · 多轮记忆（SQLite 持久化）</p>
        </div>
      </header>

      <div id="messages"></div>

      <div class="composer">
        <div id="preview">
          <img id="previewImg" alt="预览" />
          <button class="remove" id="removeImg" title="移除图片">×</button>
        </div>
        <div class="input-row">
          <input type="file" id="file" accept="image/*" hidden />
          <button class="icon-btn" id="uploadBtn" title="上传图片">🖼️</button>
          <textarea id="text" rows="1" placeholder="输入消息，可粘贴图片链接。Enter 发送，Shift+Enter 换行"></textarea>
          <button class="icon-btn" id="send" title="发送">➤</button>
        </div>
      </div>
    </div>
  </div>

  <script src="/static/app.js" defer></script>
</body>
</html>
```

- [ ] **Step 4: 修改 `app/main.py` 挂载 `/static`**

在 imports 顶部加：

```python
from fastapi.staticfiles import StaticFiles
```

在 `include_router(...)` 之后新增：

```python
app.mount("/static", StaticFiles(directory="static"), name="static")
```

**替换后完整的 `app/main.py`：**

```python
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
```

- [ ] **Step 5: 冒烟验证——前端外链能正常返回**

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
.venv/bin/python -m uvicorn app.main:app --port 8000 &
sleep 3
curl -sS -o /dev/null -w "index: %{http_code}\n" http://127.0.0.1:8000/
curl -sS -o /dev/null -w "css:   %{http_code}\n" http://127.0.0.1:8000/static/styles.css
curl -sS -o /dev/null -w "js:    %{http_code}\n" http://127.0.0.1:8000/static/app.js
# 验证 HTML 引用了外链
curl -sS http://127.0.0.1:8000/ | grep -E "styles.css|app.js"
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

Expected：三行都是 `200`，`grep` 能看到 `<link rel="stylesheet" href="/static/styles.css" />` 和 `<script src="/static/app.js" defer></script>`。

- [ ] **Step 6: 提交**

```bash
git add static/ app/main.py
git commit -m "refactor: split index.html into styles.css + app.js, mount /static

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 更新启动说明并跑一遍完整冒烟

**Files:**
- Modify: `app/main.py` 顶部注释已含启动方式（Task 5 已完成），无需再改。
- Optional: 若仓库无 README，可创建一份最小 README（本任务不强制）。

- [ ] **Step 1: 检查 `app/main.py` 注释里启动命令正确**

Read `app/main.py`，确认 docstring 里写着：

```
    .venv/bin/python -m uvicorn app.main:app --port 8000
```

若不一致，就地更正。

- [ ] **Step 2: 完整冒烟——真机跑一遍全流程**

```bash
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
.venv/bin/python -m uvicorn app.main:app --port 8000 > /tmp/cook-agent.log 2>&1 &
sleep 3
echo "--- 1. 首页 ---"
curl -sS -o /tmp/root.html -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
grep -c "美食家助手" /tmp/root.html    # 期望：1
echo "--- 2. 会话列表能读到旧数据 ---"
curl -sS http://127.0.0.1:8000/api/sessions | head -c 300
echo
echo "--- 3. 静态资源 ---"
curl -sS -o /dev/null -w "styles: %{http_code}\n" http://127.0.0.1:8000/static/styles.css
curl -sS -o /dev/null -w "app.js: %{http_code}\n" http://127.0.0.1:8000/static/app.js
echo "--- 4. SSE 对话 ---"
SID="smoke-$(date +%s)"
curl -sS -X POST -F "session_id=$SID" -F "message=用一句话介绍番茄炒蛋" \
     -N http://127.0.0.1:8000/api/chat | head -c 400
echo
echo "--- 5. 历史消息回读 ---"
curl -sS "http://127.0.0.1:8000/api/history?session_id=$SID" | head -c 400
echo
echo "--- 6. 删除 smoke 会话 ---"
curl -sS -X POST -F "session_id=$SID" http://127.0.0.1:8000/api/delete
echo
echo "--- 7. 服务日志末尾（应无异常）---"
tail -20 /tmp/cook-agent.log
lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill
```

Expected：
- 首页 HTTP 200，`grep -c` 返回 `1`。
- 会话列表非空（旧数据仍在）。
- styles.css 与 app.js 均 200。
- SSE 输出多帧 `data: {"delta": ...}`，最后一帧 `data: [DONE]`。
- 历史回读能看到刚发的 `番茄炒蛋` 相关内容。
- 删除返回 `{"ok":true}`。
- 服务日志无 `Traceback` / `ERROR`。

若上一节任一断言失败：不要修 spec、直接就地修代码；改完再跑一遍这一节。

- [ ] **Step 3: 校验前端搬家 diff 是纯搬家**

```bash
# 从原始 index.html（HEAD 前 N 版本，或 git show 上一个 commit 的老版本）里
# 抽出 CSS/JS 与现在的 styles.css/app.js 逐行 diff。
git log --oneline static/index.html | tail -1  # 找到最初的 commit
git show <old-commit>:static/index.html | awk '/<style>/,/<\/style>/' | sed '1d;$d' > /tmp/old.css
diff /tmp/old.css static/styles.css        # 期望：无输出或仅缩进层级差异
git show <old-commit>:static/index.html | awk '/<script>/,/<\/script>/' | sed '1d;$d' > /tmp/old.js
diff /tmp/old.js static/app.js             # 期望：无输出或仅缩进层级差异
```

Expected：diff 除缩进差外应为空。若有实质差异，恢复到原文。

- [ ] **Step 4: 提交（如有末次微调）**

```bash
git status
# 若有未提交改动
git add -A
git commit -m "chore: finalize refactor smoke checks

Co-Authored-By: Claude <noreply@anthropic.com>" || true
```

---

## 完成判定

- `app/` 下四个包（sessions / history / media / chat）齐全，每个包结构符合设计。
- 根目录 `server.py` 已删除。
- `static/` 下 `index.html` + `styles.css` + `app.js` 三文件；HTML 里没有 `<style>` 或 `<script>` 主体。
- Task 7 的完整冒烟脚本全部通过。
- 所有 commit 集中在 refactor 主题，无 spec 未覆盖的改动。
