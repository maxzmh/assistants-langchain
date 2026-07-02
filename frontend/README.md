# Frontend (React + Semi Design)

前后端分离后的前端工程。技术栈：Vite + React 18 + TypeScript + `@douyinfe/semi-ui`。

## 开发

```bash
# 后端（另开一个终端，在项目根目录）
.venv/bin/python -m uvicorn app.main:app --port 8000

# 前端
cd frontend
pnpm install
pnpm dev
```

Vite 会在 5173 端口启动，`/api/*` 请求通过 dev-proxy 转发到 `http://127.0.0.1:8000`，SSE 流式响应正常工作。浏览器打开 `http://localhost:5173`。

## 构建

```bash
pnpm build       # 产物在 dist/
pnpm preview     # 本地起静态服务预览
```

生产部署时把 `dist/` 交给任意静态服务器（Nginx / Caddy / CDN），并通过反代把 `/api/*` 打到 FastAPI 即可。同源部署下也不再需要 CORS。

## 目录

```
src/
  App.tsx               顶层状态：会话/消息/发送
  main.tsx              入口 + Semi zh_CN locale
  components/
    Sidebar.tsx         左侧会话列表
    ChatArea.tsx        主聊天区
    MessageBubble.tsx   单条消息气泡（Markdown + 思考/工具区）
    ThinkingBlock.tsx   思考流可折叠卡片
    ToolsBlock.tsx      工具调用卡片
    Composer.tsx        底部输入 + 图片上传
  lib/
    api.ts              /api/* 薄封装 + SSE 解析
    markdown.ts         轻量 Markdown 渲染
    imageUrls.ts        从文本抽取图片 URL
    types.ts            前端消息模型
```

## 后端接口面（未改动）

- `POST /api/chat` — SSE 流式回复
- `GET  /api/sessions` / `POST /api/session` / `POST /api/delete`
- `GET  /api/history` / `POST /api/message/delete`

`app/main.py` 增加了 CORS，白名单默认为 `http://localhost:5173,http://127.0.0.1:5173`；如需扩展设置环境变量 `CORS_ALLOW_ORIGINS`（逗号分隔）。
