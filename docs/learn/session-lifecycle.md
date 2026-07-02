# 会话的新建与恢复链路

> 记录 cook-agent（LangChain + FastAPI + LangGraph ReAct agent）里「新建会话」和「恢复会话」的完整链路。

## 一、总体结构

- 存储：单文件 SQLite（`chat_history.db`）
  - `sessions` 表：`session_id / title / created_at / updated_at` —— 自己在 `app/sessions/db.py:8-20` 建表
  - `message_store` 表：由 `SQLChatMessageHistory` 自动建，用于存 human/ai 消息（`app/history/service.py:14`）
- 会话 ID 生成方：**前端**。见 `static/app.js:18-20`：
  ```js
  function newId() {
    return 'web-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  ```
- 后端从不主动生成 ID，只做「登记 / 更新 / 读取 / 删除」。

---

## 二、新建会话（Create）

### 1. 前端触发：`createSession()`（`static/app.js:24-41`）

- 先做去重优化：如果当前 `sessionId` 已存在但还是「空会话」(`dirty=false`)，直接清屏、显示欢迎语，不新建，避免连点产生一堆空会话。
- 否则：
  1. `sessionId = newId()`，本地状态置 `dirty=false`
  2. `POST /api/session` 带 `session_id` 表单
  3. 清空消息区、显示欢迎语、刷新左侧会话列表

### 2. 后端登记：`POST /api/session`

- 路由 `app/sessions/router.py:14-18` → 服务 `app/sessions/service.py:16-18` → SQL `app/sessions/db.py:23-29`
- 一句 `INSERT OR IGNORE INTO sessions ...`，只登记元数据，`title` 默认「新对话」，`created_at = updated_at = now`。
- 注意：**此时不会碰 `message_store`**——LangChain 的历史表要等到有第一条消息落库时才被写入。

### 3. 首条消息进来时的标题更新：`POST /api/chat`

`app/chat/router.py:20-56` 里，在把消息交给 agent 之前调用：

```python
title = (text_only or message or "图片消息").strip()[:20] or "图片消息"
sessions_service.touch(conn, session_id, title=title)
```

`touch()`（`app/sessions/service.py:21-31`）→ `update_title_and_time()`（`app/sessions/db.py:32-40`）里有一段关键逻辑：

```sql
title = CASE WHEN title = '新对话' THEN ? ELSE title END
```

也就是**只有首次消息时会用消息前 20 字覆盖默认标题**，之后的消息只更新 `updated_at`。此外 `touch()` 会先 `INSERT OR IGNORE` 兜底一次——即使用户跳过 `/api/session` 直接发消息（比如 `session_id=default`），会话记录也会被自动补上。

### 4. 消息本身怎么落库

`app/agent/runner.py:79-132`：

- 拿到 `session_id` 后 `history_service.get_history(session_id)` 返回一个 `SQLChatMessageHistory`
- 把「历史消息 + 本次用户消息」拼成 `input_msgs` 喂给 LangGraph 的 ReAct agent
- 流式跑完 **成功** 后，才做：
  ```python
  history.add_message(user_msg)
  history.add_message(AIMessage(content="".join(final_text_parts)))
  ```
  出错就不落库，避免脏数据。**思维链 (`reasoning`) 和工具调用日志故意不入库**，只把最终 human/ai 文本存下来，防止长思维链塞回下一轮上下文。

---

## 三、恢复会话（Restore）

「恢复」有两条路径。

### 路径 A：页面初始化时自动进入最近一个会话

`static/app.js:435-446`：

```js
(async function init() {
  const r = await fetch('/api/sessions');
  const sessions = (await r.json()).sessions || [];
  if (sessions.length) await switchSession(sessions[0].session_id);
  else await createSession();
})();
```

- `GET /api/sessions` → `sessions_db.select_all()`（`app/sessions/db.py:51-56`）按 `updated_at DESC` 排序，直接返回列表。
- 有历史就打开第一条（最近更新的），没有就新建。

### 路径 B：用户在侧边栏点某个会话：`switchSession(id)`（`static/app.js:74-92`）

1. 更新本地 `sessionId`，把 `dirty=true`（因为已经是「有历史」的会话）
2. `GET /api/history?session_id=...` 拉消息
3. 消息为空显示欢迎语，否则逐条 `addMessage(role, {text, imageUrl})` 重绘

### 后端历史回读：`GET /api/history`

`app/history/router.py:12-14` → `app/history/service.py:17-35`：

```python
def get_history(session_id):
    return SQLChatMessageHistory(session_id=session_id, connection=DB_URL)

def serialize(session_id):
    for m in get_history(session_id).messages: ...
```

- 全权交给 LangChain 的 `SQLChatMessageHistory` 去查它自己维护的 `message_store` 表
- `serialize()` 把 `HumanMessage / AIMessage` 归一成前端需要的 `[{role, text, image}]`；多模态消息（`content` 是 list）会把 `text` / `image_url` 拆开
- **不返回思维链 / 工具调用**（因为它们本来就没入库），恢复出来的对话干干净净只有人和模型两方的最终文本

### 恢复会话后继续对话时的上下文拼接

再次 `POST /api/chat` 时，`app/agent/runner.py:81` 会：

```python
input_msgs = list(history.messages) + [user_msg]
```

把 SQLite 里所有旧消息读出来 + 本次新消息一起送给 agent —— 这就是「恢复」在模型侧真正生效的地方：**上下文即历史消息的完整回放**（没有滑窗、没有摘要）。

---

## 四、删除会话（跟恢复对称）

`POST /api/delete` → `app/sessions/service.py:38-41`：

```python
history_service.clear(session_id)    # 先清 message_store
sessions_db.delete(conn, session_id) # 再清 sessions 元数据
```

两张表一起收拾干净。前端 `deleteSession()`（`static/app.js:95-105`）如果删的是当前会话，会顺势 `createSession()` 新起一个，保证界面始终有一个可用会话。

---

## 五、几点值得注意的设计取舍

1. **ID 前端生成、后端只登记**：省一次「先请求 ID 再请求创建」的往返，代价是要信任前端 ID 的唯一性（`Math.random()+Date.now()` 足够）。
2. **`INSERT OR IGNORE` + `touch()` 兜底**：即使跳过 `/api/session` 直接聊天，会话也会自动出现在列表里；`session_id=default` 也能一直可用。
3. **标题一次性生成**：首条消息前 20 字作为标题，写完就不再改（除非它仍是「新对话」），避免后续对话不断改标题。
4. **消息只在 agent 成功跑完后落库**：出错的对话不污染历史，也不会让下一轮上下文里带着一条孤零零的用户消息。
5. **两套持久化职责清楚分开**：`sessions` 表自己写 SQL（业务字段可控），`message_store` 交给 LangChain（免维护、直接兼容 `BaseChatMessageHistory` 接口）。
6. **`get_db` 用 `check_same_thread=False`**：因为 FastAPI 的同步依赖跑在线程池，而 async endpoint 用它的地方在事件循环线程，需要放开 SQLite 的同线程限制（`app/db.py:14`）。

---

## 六、一句话总结

**新建 = 前端生成 ID → `INSERT OR IGNORE` 一条 sessions 元数据；恢复 = 用 ID 从 LangChain 的 `SQLChatMessageHistory` 里把消息读出来重绘，并在下一次调用 agent 时作为完整上下文回放。**

---

## 附：调用链一览

```
新建：
  [前端 newChat 按钮]
    → createSession()  (static/app.js:24)
    → POST /api/session
    → sessions.router.create_session      (app/sessions/router.py:14)
    → sessions.service.save               (app/sessions/service.py:16)
    → sessions.db.insert_if_absent        (app/sessions/db.py:23)

首条消息 + 标题：
  POST /api/chat
    → chat.router.chat                    (app/chat/router.py:20)
    → sessions.service.touch              (app/sessions/service.py:21)
    → chat.service.stream_reply           (app/chat/service.py:16)
    → agent.runner.stream_events          (app/agent/runner.py:66)
    → history.add_message (成功后)         (app/agent/runner.py:131-132)

恢复：
  [页面初始化 或 点击侧边栏]
    → GET /api/sessions → sessions.db.select_all           (app/sessions/db.py:51)
    → switchSession(id)                                    (static/app.js:74)
    → GET /api/history → history.service.serialize        (app/history/service.py:17)
    → SQLChatMessageHistory(session_id).messages           (LangChain)
    → 下一次 POST /api/chat 时 list(history.messages)+[user_msg] 作为上下文
```
