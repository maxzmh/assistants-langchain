"""
LangChain + Doubao 配置：LLM 工厂 + 全局路径常量。
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# 数据库文件路径：可用环境变量 COOK_DB_PATH 覆盖，默认落在项目根。
DB_PATH: str = os.getenv("COOK_DB_PATH", "chat_history.db")
DB_URL: str = f"sqlite:///{DB_PATH}"


def _patch_reasoning_passthrough() -> None:
    """把 OpenAI 兼容协议里 delta.reasoning_content 转发到 AIMessageChunk。

    背景：豆包 Seed / DeepSeek-R1 等系列以 `reasoning_content` 字段流式返回思维链，
    但 `langchain-openai` 0.3.x 的 delta→MessageChunk 转换器只识别 content/function_call/
    tool_calls，直接丢掉这个字段。这里在导入时打一个小补丁：调用完原实现后，
    如果原始 delta 里带 reasoning_content，就补进结果的 additional_kwargs，
    让上层能用 chunk.additional_kwargs["reasoning_content"] 消费。

    幂等：靠函数属性做守卫，重复 import 也只打一次。
    """
    from langchain_openai.chat_models import base as _b
    if getattr(_b._convert_delta_to_message_chunk, "_reasoning_patched", False):
        return
    _orig = _b._convert_delta_to_message_chunk

    def _wrapped(_dict, default_class):
        chunk = _orig(_dict, default_class)
        rc = _dict.get("reasoning_content") if isinstance(_dict, dict) else None
        if rc:
            # 已有则拼接，让上游 chunk 相加时行为一致
            existing = chunk.additional_kwargs.get("reasoning_content", "")
            chunk.additional_kwargs["reasoning_content"] = existing + rc
        return chunk

    _wrapped._reasoning_patched = True  # type: ignore[attr-defined]
    _b._convert_delta_to_message_chunk = _wrapped


_patch_reasoning_passthrough()


def get_llm(**kwargs) -> ChatOpenAI:
    """返回配置好的 Doubao-Seed-2.1-pro 聊天模型实例。

    通过 `ARK_THINKING` 环境变量控制深度思考：
      - 未设置或 "on"/"enabled" -> 开启（默认；模型会吐 reasoning_content）
      - "off"/"disabled"/"0"/"false"/"no" -> 关闭

    注意：思考模式需要模型自身支持。当前 `doubao-seed-2-1-pro-260628` 只识别
    `enabled` / `disabled` 两个值（`auto` 会 400），且开启后会返回真实 reasoning。
    """
    thinking = os.getenv("ARK_THINKING", "on").lower()
    extra_body = kwargs.pop("extra_body", None) or {}
    if thinking not in {"off", "disabled", "0", "false", "no"}:
        extra_body.setdefault("thinking", {"type": "enabled"})

    return ChatOpenAI(
        model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
        api_key=os.getenv("ARK_API_KEY"),
        base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        temperature=kwargs.pop("temperature", 0.7),
        extra_body=extra_body,
        **kwargs,
    )
