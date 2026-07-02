"""
history 业务层：前端展示用的会话消息读写。

存储职责分离：
  * 展示历史（human / ai 最终文本）→ `SQLChatMessageHistory`（Postgres `message_store` 表）
  * agent 中间态 / 断点续跑     → LangGraph checkpointer（`checkpoints*` 表）

runner 只在成功跑完一轮之后把「用户消息 + 最终 AI 回复」写进 `SQLChatMessageHistory`；
思维链和工具调用故意不入历史，避免污染下一轮上下文 + 前端展示。
"""
from typing import Annotated, List, TypedDict

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import RemoveMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app import pg


def get_history(session_id: str) -> BaseChatMessageHistory:
    """构造一个走 SA async engine 的 SQLChatMessageHistory。

    `async_mode=True` 才会走 `aadd_message / aget_messages / aclear` 那套异步接口；
    engine 由 `app.pg` 统一维护，避免每次调用都新建/连接。
    """
    return SQLChatMessageHistory(
        session_id=session_id,
        connection=pg.get_engine(),
        async_mode=True,
    )


def _to_frontend(msg) -> dict | None:
    """把一条 LangChain 消息转成前端结构 `{id, role, text, image}`；忽略非 human/ai。

    `id` 是消息的 uuid（HumanMessage 由 runner 主动分配、AIMessage 由 LangGraph reducer 分配），
    前端拿它来标识某条消息，做单条删除等操作。
    """
    mtype = getattr(msg, "type", None)
    if mtype == "human":
        role = "user"
    elif mtype == "ai":
        role = "bot"
    else:
        return None

    text, image = "", None
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text += part.get("text", "")
            elif part.get("type") == "image_url":
                image = part.get("image_url", {}).get("url")
    return {
        "id": getattr(msg, "id", None),
        "role": role,
        "text": text,
        "image": image,
    }


async def serialize(session_id: str) -> List[dict]:
    """把某会话的消息转成前端易渲染的结构：[{role, text, image}]。"""
    messages = await get_history(session_id).aget_messages()
    return [item for m in messages if (item := _to_frontend(m)) is not None]


async def clear(session_id: str) -> None:
    """清空某会话：既清展示用的 message_store，也清 checkpointer 里的中间态。"""
    await get_history(session_id).aclear()
    await pg.get_saver().adelete_thread(session_id)


# —— 删单条消息用的极简图 ——
#
# 为什么不直接在主 agent 上跑 `aupdate_state(RemoveMessage)`：
# langgraph 1.2.7 里 `create_agent` + `SummarizationMiddleware` 组合下，
# `aupdate_state` 会重放条件路由，去 `self.ends` 里查 middleware 节点 key
# （比如 `SummarizationMiddleware.before_model`），但该字典没被填全，
# 直接抛 `KeyError`。上游未修复，不能等。
#
# 绕开的做法：另建一个只有 messages 通道 + 一个 noop 节点的极简图，
# **共享同一个 checkpointer 和 thread_id**。所有 checkpoint 操作（包括
# RemoveMessage）都通过它转发到底层 saver，主 agent 的 middleware 完全无关。
_DeleteState = TypedDict("_DeleteState", {"messages": Annotated[list, add_messages]})
_delete_graph = None


def _get_delete_graph():
    global _delete_graph
    if _delete_graph is None:
        def _noop(_state):
            return {}
        g = StateGraph(_DeleteState)
        g.add_node("noop", _noop)
        g.add_edge(START, "noop")
        g.add_edge("noop", END)
        _delete_graph = g.compile(checkpointer=pg.get_saver())
    return _delete_graph


async def delete_one(session_id: str, message_id: str) -> bool:
    """删除某会话中的一条消息（human 或 ai）。

    两处存储都要同步动，顺序讲究：
      1) 先软删 checkpoint：通过极简图 `aupdate_state({..messages: [RemoveMessage(id=..)]})`
         追加一个新 checkpoint，reducer 将目标消息从最新 state 中摘掉，
         主 agent 下一轮不再看到这条消息。历史 checkpoint 仍保留，不打断链。
      2) 再删 message_store：走 SQL 直接删该 session 下 message.data.id 匹配的行。
         `SQLChatMessageHistory` 官方接口只有 aclear，只能落到直接 SQL。

    顺序理由：checkpoint 是「真身」。checkpoint 删掉但 message_store 没删 →
    前端还看得到但 agent 已忘记，用户重试即可修复；反过来就会出现「界面已消失
    但 agent 悄悄记得」的隐藏状态，最难排查。

    返回值：True 表示 message_store 里确实删掉了行；False 表示 checkpoint 已软删
    但 message_store 里没匹配上（比如已经被清或从未落库）。
    """
    graph = _get_delete_graph()
    config = {"configurable": {"thread_id": session_id}}
    try:
        await graph.aupdate_state(config, {"messages": [RemoveMessage(id=message_id)]})
    except ValueError as e:
        # add_messages reducer 找不到目标 id 会抛 ValueError（"doesn't exist"），
        # 这在「消息只在 message_store 里、checkpoint 已被清 / 未记录」时会发生。
        # 展示层的删除仍应继续进行，checkpoint 侧当作无操作。
        if "doesn't exist" not in str(e):
            raise

    pool = pg.get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM message_store WHERE session_id = %s "
                "AND message::jsonb->'data'->>'id' = %s",
                (session_id, message_id),
            )
            return cur.rowcount > 0
