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
