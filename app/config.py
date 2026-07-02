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

    背景：豆包 Seed / DeepSeek-R1 等系列以 `reasoning_content` 字段流式返回思维链。
    `langchain-openai` 从 1.x 起明确只支持官方 OpenAI 协议、不再兼容第三方 provider 的
    `reasoning_content`（见 `langchain_openai/chat_models/base.py` 的模块 docstring），
    但底层私有函数 `_convert_delta_to_message_chunk` 仍存在。这里在导入时打一个小补丁：
    调用完原实现后，如果原始 delta 里带 reasoning_content，就补进结果的 additional_kwargs，
    让上层能用 chunk.additional_kwargs["reasoning_content"] 消费。

    幂等：靠函数属性做守卫，重复 import 也只打一次。
    容错：上游哪天真把这个私有函数删掉，就退化为不打补丁，不阻塞进程启动
        （思维链流会丢，但对话/工具链路仍可用；届时应转用 provider-specific 包）。
    """
    try:
        from langchain_openai.chat_models import base as _b
        _orig = _b._convert_delta_to_message_chunk
    except (ImportError, AttributeError):
        return
    if getattr(_orig, "_reasoning_patched", False):
        return

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
