"""
history 业务层：前端展示用的会话消息读写。

存储职责分离：
  * 展示历史（human / ai 最终文本）→ `SQLChatMessageHistory`（Postgres `message_store` 表）
  * agent 中间态 / 断点续跑     → LangGraph checkpointer（`checkpoints*` 表）

runner 只在成功跑完一轮之后把「用户消息 + 最终 AI 回复」写进 `SQLChatMessageHistory`；
思维链和工具调用故意不入历史，避免污染下一轮上下文 + 前端展示。
"""
from typing import List

from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import RemoveMessage

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


async def delete_one(session_id: str, message_id: str) -> bool:
    """删除某会话中的一条消息（human 或 ai）。

    两处存储都要同步动，顺序讲究：
      1) 先软删 checkpoint：`agent.aupdate_state({..messages: [RemoveMessage(id=..)]})`
         会追加一个新的 checkpoint，reducer 将目标消息从「最新 state」中摘掉，
         agent 下一轮就看不到这条消息了。历史 checkpoint 仍保留，不打断链。
      2) 再删 message_store：走 SQL 直接删该 session 下 message.data.id 匹配的行。
         `SQLChatMessageHistory` 官方接口只有 aclear，只能落到直接 SQL。

    顺序理由：checkpoint 是「真身」。checkpoint 删掉但 message_store 没删 →
    前端还看得到但 agent 已忘记，用户重试即可修复；反过来就会出现「界面已消失
    但 agent 悄悄记得」的隐藏状态，最难排查。

    返回值：True 表示 message_store 里确实删掉了行；False 表示 checkpoint 已软删
    但 message_store 里没匹配上（比如已经被清或从未落库）。
    """
    # 延迟 import 避免与 runner 之间形成 import 环
    from app.agent import runner
    agent = runner._get_agent()
    config = {"configurable": {"thread_id": session_id}}
    try:
        await agent.aupdate_state(config, {"messages": [RemoveMessage(id=message_id)]})
    except ValueError as e:
        # LangGraph 的 messages reducer 找不到目标 id 会抛 ValueError；
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
