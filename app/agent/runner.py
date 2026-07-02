"""
Agent runner：跑 LangGraph 的 ReAct agent，把 astream_events(v2) 的事件
翻译成前端 SSE 帧。

对外只暴露 `stream_events()` 这一个 async generator，
返回 SSE 字符串帧。事件形态见下方注释。
"""
from __future__ import annotations

import json
from typing import Any, AsyncGenerator, List, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agent.tools import build_tools
from app.chat.prompts import SYSTEM_PROMPT
from app.config import get_llm
from app.history import service as history_service

# 单例 agent：Doubao 客户端 + tools 都不便宜，构建一次即可
_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = create_react_agent(
            model=get_llm(),
            tools=build_tools(),
            prompt=SystemMessage(content=SYSTEM_PROMPT),
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
      * {"type":"error","message":"..."}
    """
    history = history_service.get_history(session_id)
    user_msg = HumanMessage(content=content)
    input_msgs = list(history.messages) + [user_msg]

    final_text_parts: List[str] = []
    finished_ok = False
    try:
        async for event in _get_agent().astream_events({"messages": input_msgs}):
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
                    final_text_parts.append(text)
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
        finished_ok = True
    except Exception as e:  # noqa: BLE001
        yield _sse({"type": "error", "message": str(e)})

    if finished_ok:
        # 只落最终 AI 文本 + 用户消息；reasoning 和工具日志不入历史，
        # 避免长思考塞回下一轮上下文，也让老历史接口保持只关心 human/ai。
        history.add_message(user_msg)
        history.add_message(AIMessage(content="".join(final_text_parts)))

    yield "data: [DONE]\n\n"
