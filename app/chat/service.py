"""
chat 服务：委托给 agent runner，把 async SSE 流适配成 router 需要的
async generator。

历史（这段说明保留是为了让后续维护者理解演进）：
  最初这里是直接 llm.stream(messages)。接了 LangGraph agent 之后，
  流式来源改成 `app.agent.runner.stream_events`，本模块只负责
  「组装用户消息 → 交给 runner」，并暴露一个 async 迭代器给 FastAPI 的
  StreamingResponse。
"""
from typing import AsyncGenerator, List, Union

from app.agent import runner as agent_runner


async def stream_reply(
    session_id: str, content: Union[str, List[dict]]
) -> AsyncGenerator[str, None]:
    """生成 SSE 帧流。事件形态见 `agent.runner.stream_events` 注释。"""
    async for frame in agent_runner.stream_events(session_id, content):
        yield frame
