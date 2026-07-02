# cook-agent

基于 LangChain + 火山引擎豆包（Doubao-Seed-2.1-pro）的项目脚手架。

## 说明

豆包模型部署在火山引擎 **Ark** 平台，该平台提供 **OpenAI 兼容接口**，
因此本项目使用 `langchain-openai` 的 `ChatOpenAI`，并将 `base_url` 指向 Ark。

- 模型显示名：`Doubao-Seed-2.1-pro`
- Ark 实际模型 ID：`doubao-seed-2-1-pro-260628`
- Base URL：`https://ark.cn-beijing.volces.com/api/v3`

> 模型 ID 可通过 `GET /api/v3/models` 接口查询，平台一般使用「带日期的小写 ID」或「推理接入点 ID（ep-xxxx）」，
> 不能直接用显示名调用。

## 目录结构

```
.
├── .env             # API Key 与模型配置（已被 .gitignore 忽略）
├── config.py        # get_llm()：返回配置好的模型实例
├── main.py          # 单轮对话 + LCEL 链示例
├── chat.py          # 带短期记忆的多轮对话 + 流式输出
├── agent.py         # 能调用 Tavily 联网搜索的 ReAct Agent（带记忆 + 流式）
├── server.py        # FastAPI Web 后端（流式对话 + 图片上传）
├── static/
│   └── index.html   # 前端聊天页面（对话界面 + 图片上传预览）
├── requirements.txt
└── .venv/           # 虚拟环境
```

## 快速开始

```bash
# 1. 安装依赖（已完成，如需重装可用国内镜像加速）
.venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2. 运行示例
.venv/bin/python main.py

# 3. 多轮对话（带短期记忆 + 流式输出）
.venv/bin/python chat.py

# 4. 联网搜索 Agent（需先在 .env 填入 TAVILY_API_KEY）
.venv/bin/python agent.py

# 5. Web 聊天页面（对话 + 图片上传）
.venv/bin/uvicorn server:app --reload --port 8000
# 然后浏览器打开 http://127.0.0.1:8000
```

## 多轮对话说明（chat.py）

- **短期记忆**：用 `InMemoryChatMessageHistory` 按 `session_id` 在内存中保存对话历史，
  通过 `RunnableWithMessageHistory` 自动注入到每次请求。记忆存在进程内，**重启即清空**。
- **流式输出**：用 `chain.stream(...)` 逐 token 打印模型回复。
- 交互命令：`exit` / `quit` 退出，`clear` 清空当前会话记忆。

## 联网搜索 Agent 说明（agent.py）

- **工具**：`langchain_tavily.TavilySearch`，封装 Tavily 联网搜索。
- **Agent**：用 LangGraph 的 `create_react_agent` 构建 ReAct 智能体，
  豆包模型自行判断何时联网搜索、何时直接回答。
- **记忆**：`MemorySaver` 按 `thread_id` 在内存中保存历史（重启即清空）。
- **流式**：`stream_mode="messages"` 逐 token 输出，发起搜索时会提示「🔍 正在联网搜索…」。
- **前置条件**：在 `.env` 中填入 `TAVILY_API_KEY`（https://tavily.com 免费注册，格式 `tvly-xxxx`）。

## Web 聊天页面说明（server.py + static/index.html）

- **后端**：FastAPI，`POST /api/chat` 接收文本（+可选图片）+ `session_id`，以 **SSE 流式**返回回复。
- **多轮记忆**：后端手动管理历史——读取该 `session_id` 的历史 → 拼上下文 → 流式生成并累积 → 把本轮
  「用户消息 + AI 回复」写回 `SQLChatMessageHistory`。**持久化到 SQLite（`chat_history.db`），服务重启后历史仍在**。
- **历史会话列表**：左侧边栏展示全部会话（标题取首条用户消息），可点击切换、🗑 删除；点「＋ 新对话」新建。
- **图片**：豆包 Seed 2.1 是多模态模型，图片以 base64 data URL 作为 `image_url` 传入，模型可识别图片内容。
- **前端**：单页应用（`static/index.html`），含侧边栏会话列表、对话气泡、逐字流式渲染、图片上传与预览。
- 启动：`.venv/bin/uvicorn server:app --reload --port 8000`，浏览器打开 http://127.0.0.1:8000。

### Web 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/sessions` | 列出全部会话（按最近更新排序） |
| POST | `/api/session`  | 登记一个新会话（表单 `session_id`） |
| GET  | `/api/history`  | 读取某会话消息（`?session_id=`），用于切换回显 |
| POST | `/api/chat`     | 发消息，SSE 流式返回（表单 `message` / `session_id` / 可选 `image`） |
| POST | `/api/clear`    | 清空某会话消息（保留会话条目） |
| POST | `/api/delete`   | 删除某会话（连同消息） |

> 数据存于 `chat_history.db`（已被 `.gitignore` 忽略）：会话元数据在 `sessions` 表，消息在 `message_store` 表。
> 服务重启后对话历史仍在。

## 在代码中使用

```python
from config import get_llm

llm = get_llm(temperature=0.7)
print(llm.invoke("你好").content)
```
