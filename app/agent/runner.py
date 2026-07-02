"""
Agent runner：跑 LangChain 1.x 的 create_agent，把 astream_events 的事件
翻译成前端 SSE 帧。

对外只暴露 `stream_events()` 这一个 async generator，
返回 SSE 字符串帧。事件形态见下方注释。

存储职责分离：
  * agent 的上下文记忆 / 中间态 / 断点续跑 → `AsyncPostgresSaver`（checkpointer）
    每次进入时先 `aget_state` 看看有没有未完成的 pending 步骤——有就先带 `None`
    输入把上次中断的部分收尾，再把本次用户消息作为新一轮送进去。
  * 前端展示的历史（只含 human/ai 最终文本） → `SQLChatMessageHistory`
    这是只写侧：跑完成功后落一条 HumanMessage + 一条 AIMessage；出错不落，
    避免脏数据污染下一次刷新时的展示。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, List, Union

from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langchain.agents.middleware import (
    FilesystemFileSearchMiddleware,
    SummarizationMiddleware,
)

from app import pg
from app.agent.tools import build_tools
from app.chat.prompts import SYSTEM_PROMPT
from app.config import get_llm
from app.history import service as history_service

# 项目根/docs：文档搜索工具的沙箱边界。middleware 只允许在此根内 glob/grep。
_DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"

# 单例 agent：Doubao 客户端 + tools 都不便宜，构建一次即可。
# 惰性构造，等 lifespan 里 saver 就绪之后第一次请求触发。
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = create_agent(
            model=get_llm(),
            tools=build_tools(),
            system_prompt=SYSTEM_PROMPT,
            middleware=[
                SummarizationMiddleware(
                    model=get_llm(),
                    trigger=("tokens", 4000),
                    keep=("messages", 20),
                ),
                # 让 agent 能在项目 docs/ 下用 glob_search / grep_search 找本地资料。
                # 未装系统 ripgrep 时会自动回退到纯 Python 实现，功能一致、速度更慢。
                FilesystemFileSearchMiddleware(
                    root_path=str(_DOCS_ROOT),
                    max_file_size_mb=5,
                ),
            ],
            checkpointer=pg.get_saver(),
        )
    return _agent


def _sse(payload: dict) -> str:
    """JSON 编码成一帧 SSE。default=str 兜底 ToolMessage/日期等非序列化对象。"""
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _extract_text(chunk_content: Any) -> str:
    """AIMessageChunk.content 可能是 str，也可能是结构化 list——统一成字符串。"""
    if isinstance(chunk_content, str):
        return chunk_content
    if isinstance(chunk_content, list):
        out = []
        for p in chunk_content:
            if isinstance(p, dict) and p.get("type") == "text":
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _extract_reasoning(chunk: Any) -> str:
    """
    Doubao Seed（Thinking 模式）与 DeepSeek-R1 家族都把思维链
    塞在 delta.reasoning_content 里，langchain-openai 会转发到
    AIMessageChunk.additional_kwargs["reasoning_content"]。
    """
    ak = getattr(chunk, "additional_kwargs", None) or {}
    if not isinstance(ak, dict):
        return ""
    return ak.get("reasoning_content") or ""


async def _pump_events(agent, agent_input, config):
    """跑一段 astream_events 并把事件翻译成 SSE 帧。抽出来复用：pending 收尾 + 新一轮共用。"""
    async for event in agent.astream_events(agent_input, config=config):
        kind = event.get("event")
        data = event.get("data") or {}

        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if chunk is None:
                continue
            r = _extract_reasoning(chunk)
            if r:
                yield _sse({"type": "reasoning", "delta": r})
            text = _extract_text(getattr(chunk, "content", None))
            if text:
                yield _sse({"type": "delta", "text": text})

        elif kind == "on_tool_start":
            yield _sse({
                "type": "tool_start",
                "id": event.get("run_id"),
                "name": event.get("name"),
                "input": data.get("input"),
            })

        elif kind == "on_tool_end":
            out = data.get("output")
            # ToolMessage → 只取 content；其余非基础类型 default=str 兜底
            if hasattr(out, "content"):
                out = out.content
            yield _sse({
                "type": "tool_end",
                "id": event.get("run_id"),
                "name": event.get("name"),
                "output": out,
            })


async def stream_events(
    session_id: str, content: Union[str, List[dict]]
) -> AsyncGenerator[str, None]:
    """
    流式执行 ReAct agent，产出 SSE 帧。

    事件类型（`data: {json}\\n\\n`，最后 `data: [DONE]`）：
      * {"type":"reasoning","delta":"..."}                   模型思考流
      * {"type":"tool_start","id":"...","name":"...","input":{...}}
      * {"type":"tool_end","id":"...","name":"...","output":"..."}
      * {"type":"delta","text":"..."}                        最终回复文本流
      * {"type":"ids","user_id":"...","ai_id":"..."}         成功跑完后一次性下发，前端用来定位气泡
      * {"type":"error","message":"..."}
    """
    agent = _get_agent()
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 50,
    }

    # 主动打 uuid：checkpointer / message_store / 前端 dataset 三处对齐用同一个 id。
    # LangGraph 的 messages reducer 看到 message 已带 id 就不再重新分配，因此本地这条对象
    # 与最终 checkpoint 里的那条是同一个 id。
    user_msg = HumanMessage(content=content, id=str(uuid.uuid4()))
    finished_ok = False

    try:
        # 断点续跑：state.next 非空说明上一轮跑到一半就中断了（比如 uvicorn 被杀 / 客户端断流）。
        # 先带 None 输入把中断的部分收尾（事件照样吐给前端），再进入新一轮。
        state = await agent.aget_state(config)
        if state is not None and state.next:
            async for frame in _pump_events(agent, None, config):
                yield frame

        async for frame in _pump_events(agent, {"messages": [user_msg]}, config):
            yield frame
        finished_ok = True
    except Exception as e:  # noqa: BLE001
        # checkpointer 已把出错前的状态存好了，下次请求会自动从 pending 处继续。
        yield _sse({"type": "error", "message": str(e)})

    if finished_ok:
        # 成功跑完后从 checkpointer 里把 reducer 装配好的最终 messages 取出来：
        #   * user_msg：直接用本地对象（uuid 与 checkpoint 里对齐）
        #   * ai_msg：取 messages 尾部最后一条 ai——包含 reducer 分配的 uuid + 完整 content
        # 落 message_store 用它们的官方对象，reasoning/工具日志不入库。
        state = await agent.aget_state(config)
        msgs = (state.values or {}).get("messages", []) if state else []
        ai_msg = next((m for m in reversed(msgs) if getattr(m, "type", None) == "ai"), None)

        # 先把 id 下发给前端（此时对话已完成，前端可用它挂到气泡 dataset 上）
        yield _sse({
            "type": "ids",
            "user_id": user_msg.id,
            "ai_id": getattr(ai_msg, "id", None),
        })

        history = history_service.get_history(session_id)
        to_persist: List[Any] = [user_msg]
        if ai_msg is not None:
            to_persist.append(ai_msg)
        await history.aadd_messages(to_persist)

    yield "data: [DONE]\n\n"
