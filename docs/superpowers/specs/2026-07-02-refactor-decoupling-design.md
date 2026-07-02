# cook-agent 重构设计：代码层面解耦

- 日期：2026-07-02
- 状态：待实现

## 背景

当前项目结构：

- `server.py`（275 行）把 FastAPI 路由、SQLite 会话元数据、LangChain 消息历史、图片 URL 抽取、多模态 content 组装、SSE 流式生成 + 落库六件事塞在一个文件里。
- `config.py`（26 行）只负责构造 LLM，本身已经干净。
- `static/index.html`（528 行）HTML/CSS/JS 全内联在单文件。

目标：把上述职责按功能拆开，让每个文件/模块只做一件事，且改一处不牵连别处。**不换框架，不引入构建工具，不写单元测试。**

## 决策摘要

- **范围**：后端拆包 + 前端 CSS/JS 从 HTML 抽出（三文件）。
- **粒度**：**按功能包切分**——每个功能自带 `router` + `service` + `db`。
- **包间依赖**：**直接 import 对方的 `service`**（不引入 Protocol / 事件总线）。
- **SQLite 连接**：**FastAPI 依赖注入 `get_db()`**，service 层收 `conn` 参数，不自己开连接。
- **前端拆分**：只做搬家式的三文件（`index.html` + `styles.css` + `app.js`），不引 ES modules、不引构建工具。

## 目标结构

```
cook-agent/
├── app/                          # 后端 Python 包
│   ├── __init__.py
│   ├── main.py                   # FastAPI 实例、装配、init_db、挂载 static、注册路由
│   ├── config.py                 # LLM 工厂 + DB_PATH（从环境变量读）
│   ├── db.py                     # get_db() 依赖：yield sqlite3 连接
│   ├── sessions/                 # 功能包：会话元数据
│   │   ├── __init__.py
│   │   ├── router.py             # /api/session, /api/sessions, /api/delete
│   │   ├── service.py            # save/touch/list/delete_session(conn, ...)
│   │   └── db.py                 # 建表 SQL + 直接执行的低层函数
│   ├── history/                  # 功能包：LangChain 消息历史
│   │   ├── __init__.py
│   │   ├── router.py             # /api/history, /api/clear
│   │   └── service.py            # get_history / serialize_messages / clear
│   ├── chat/                     # 功能包：对话 + 流式
│   │   ├── __init__.py
│   │   ├── router.py             # /api/chat
│   │   ├── service.py            # 组 prompt、调 llm.stream、落库
│   │   └── prompts.py            # SYSTEM_PROMPT
│   └── media/                    # 功能包：图片处理
│       ├── __init__.py
│       └── service.py            # extract_image_urls + build_multimodal_content
├── static/
│   ├── index.html                # 只留结构，<link> + <script src> 引入
│   ├── styles.css                # 抽出的 <style>
│   └── app.js                    # 抽出的 <script>
├── chat_history.db               # 原位不动
├── .env                          # 保持
└── README 或注释更新              # 新启动命令
```

**启动命令**：`.venv/bin/python -m uvicorn app.main:app --port 8000`（原来是 `server:app`）。

## 模块职责

依赖方向（左边依赖右边）：

```
routers ──► services ──► db (per package)
   │            │           │
   └────► db.py (get_db 依赖) ◄──── 共享 sqlite 连接

chat.service ──► history.service.get_history
             ──► config.get_llm
chat.router  ──► chat.service.stream_reply
             ──► media.service.extract_image_urls / build_content
             ──► sessions.service.touch

sessions.service.delete ──► history.service.clear   # 唯一跨包调用
```

| 模块 | 职责 | 对外接口（核心签名） |
|---|---|---|
| `app.config` | 加载 .env，构造 LLM；暴露 `DB_PATH` | `get_llm(**kw)`, `DB_PATH: str` |
| `app.db` | FastAPI 依赖：`yield` `sqlite3.Connection`（`row_factory=Row`），退出时关闭 | `get_db() -> Generator[Connection]` |
| `app.main` | 装配 FastAPI、启动时建表、挂 `/static`、`include_router` | — |
| `sessions.db` | 建表 `sessions`；纯 SQL 低层函数 | `init(conn)`, `insert_if_absent(conn, ...)`, `update_title_and_time(conn, ...)`, `select_all(conn)`, `delete(conn, id)` |
| `sessions.service` | 业务规则（"仅当标题仍是默认才更新"、时间戳格式） | `save(conn, sid)`, `touch(conn, sid, title=None)`, `list_all(conn)`, `delete(conn, sid)` |
| `sessions.router` | POST `/api/session`、GET `/api/sessions`、POST `/api/delete` | — |
| `history.service` | 封装 `SQLChatMessageHistory`；序列化给前端 | `get_history(sid)`, `serialize(sid) -> list[dict]`, `clear(sid)` |
| `history.router` | GET `/api/history`、POST `/api/clear` | — |
| `media.service` | 纯函数：抽 URL、组多模态 content。上传图片以 `(bytes, mime)` 形式传入（由 router 先 `await upload.read()`） | `extract_image_urls(text) -> (str, list[str])`, `build_content(text, image_bytes: bytes \| None, image_mime: str \| None, urls: list[str]) -> str \| list` |
| `chat.service` | 组 prompt、调 llm.stream、生成 SSE 帧、结束后写历史。**不做**图片读取、也不做标题 touch——那些在 router 完成。 | `stream_reply(sid, content) -> Generator[str]`（`content` 已是 str 或多模态 list） |
| `chat.router` | POST `/api/chat`：async 路由；`await upload.read()` 拿字节 → `media.build_content` → `sessions.service.touch` → 转交 `chat.service.stream_reply` 返回 `StreamingResponse` | — |
| `chat.prompts` | 系统提示词常量 | `SYSTEM_PROMPT: str` |

### 硬约束

1. **路由不直接调本包 `db.py`**——只调本包 `service`。
2. **跨包只能 import 对方的 `service`**，不许 import 别人的 `db.py` 或 `router.py`。
3. **service 函数收 `conn` 参数**，不自己开连接。DB 路径只在 `app/config.py` 里出现一次。
4. **`media.service` 是纯函数**，零依赖。

## 关键数据流

### A. 发消息（POST `/api/chat`）

```
Browser ──form-data──► chat.router.chat(message, session_id, image, conn=Depends(get_db))     # async
                          │
                          ▼
   image_bytes, image_mime = (await image.read(), image.content_type) if image else (None, None)
   text_only, url_list = media.service.extract_image_urls(message)
   content = media.service.build_content(text_only, image_bytes, image_mime, url_list)
                          │
                          ▼
   sessions.service.touch(conn, sid, title=text_only[:20] or "图片消息")
                          │
                          ▼
   generator = chat.service.stream_reply(sid, content)     # 内部构造 prompt、调 llm.stream、落库
                          │
                          ▼
   StreamingResponse(generator, media_type="text/event-stream")
                          │
Browser ◄─────── SSE frames: {"delta": "..."} ... [DONE]
```

**顺序保证**：先 `touch`（登记会话 + 更新标题），再进流；写历史在最后一帧 `[DONE]` 之前完成，跟现状语义一致。

**跨层规则**：router 是唯一的 async 层，负责把 `UploadFile` 化解为纯字节；`media` 和 `chat` service 都是同步的，方便被同步 `llm.stream` 驱动。

### B. 侧边栏读取

```
GET /api/sessions
  → sessions.router → sessions.service.list_all(conn) → sessions.db.select_all(conn)
  → {"sessions": [...]}

GET /api/history?session_id=xxx
  → history.router → history.service.serialize(sid)
  → {"messages": [{role, text, image}, ...]}
```

### C. 新建 / 删除 / 清空

```
POST /api/session    (Form: session_id)  → sessions.service.save(conn, sid)     → {"ok": true}
POST /api/delete     (Form: session_id)  → sessions.service.delete(conn, sid)
                                             ├─ history.service.clear(sid)   # 唯一跨包调用
                                             └─ sessions.db.delete(conn, sid)
POST /api/clear      (Form: session_id)  → history.service.clear(sid)           → {"ok": true}
```

### D. 启动（`app.main`）

```
FastAPI() → app.mount("/static", StaticFiles(directory="static"))
        → include_router(sessions/history/chat)
        → 启动事件：with sqlite3.connect(DB_PATH) as conn: sessions.db.init(conn)
```

## 错误处理

保持最小干预：

- 多数错误由 FastAPI 默认 500 处理；不新增全局异常处理器。
- 显式校验只加两处：
  - `/api/chat`：`message` 空且无任何图片 → `HTTPException(400, "empty message")`。
  - `/api/history`、`/api/delete`：`session_id` 未提供 → 由 FastAPI 的 `Form(...)` / `Query(...)` 自动 422。
- SSE 流内 `llm.stream` 抛异常时：包成一帧 `data: {"error": "..."}\n\n`，再发 `[DONE]`，避免前端一直转圈。
- DB 连接靠 `get_db()` 的 `try/finally` 关闭。

## 前端拆分

- `index.html`：DOM 骨架 + `<link rel="stylesheet" href="/static/styles.css">` + `<script src="/static/app.js" defer></script>`。
- `styles.css`：原 `<style>` 内容原样搬过来，不重命名类。
- `app.js`：原 `<script>` 内容原样搬过来。
- FastAPI 加 `app.mount("/static", StaticFiles(directory="static"))`；`GET /` 继续返回 `static/index.html`。

**这一步只搬家**：不改选择器、不改变量名、不改行为，diff 可核对。

## 验证清单（冒烟）

判定重构完成：

1. `.venv/bin/python -m uvicorn app.main:app --port 8000` 成功启动，无报错。
2. `curl / → HTTP 200`，HTML 里能看到"美食家助手"。
3. `curl /api/sessions → HTTP 200`，能读到旧 `chat_history.db` 里的历史会话。
4. 浏览器手工过一遍：新建会话 → 发文字消息 → 收到流式回复 → 刷新后历史仍在 → 删除会话。
5. `git diff` 中 `static/index.html + styles.css + app.js` 三份的净变化 ≈ 0（纯搬家）。

## 迁移步骤（每步独立 commit）

1. 建 `app/` 骨架 + 空模块 + `main.py` 可启动（暂无路由）。
2. 迁 `config.py` → `app/config.py`，加 `DB_PATH`。
3. 迁 sessions 包（db → service → router），`main.py` include，删原 `server.py` 里对应代码。
4. 迁 history 包，同上。
5. 迁 media 包（纯函数最简单），同上。
6. 迁 chat 包，同上；此时 `server.py` 应为空，删除。
7. 前端拆三文件；`main.py` 挂 `/static`。
8. 更新启动命令说明（README 或 `app/main.py` 顶部注释）。
9. 通跑验证清单 → 提交。

## YAGNI 复核（不做的事）

- 不引入 SQLAlchemy / Alembic。
- 不引入 Pydantic 请求模型（继续用 `Form`）。
- 不加日志框架、不加全局异常处理器。
- 前端不上 ES modules、不上 Vite/TS/构建工具。
- 不补单元测试；只做冒烟。
- 不动 `chat_history.db` 的表结构 / 存储位置。
