"""
演示工具集合。

- get_current_time(): 返回本机当前时间字符串。零依赖，便于验证工具链路。
- web_search(query): 走 Tavily 联网搜索。仅在 TAVILY_API_KEY 配置时启用。

新增工具的正确姿势：写一个 `@tool` 装饰的函数，放进下面的 `TOOLS` 列表即可，
runner 侧不需要改。docstring 会作为工具描述让模型看到，请写清楚。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

from langchain_core.tools import BaseTool, tool


@tool
def get_current_time() -> str:
    """获取当前时间。当用户问「现在几点」「今天日期」等与时间强相关的问题时调用。返回本地时区的当前时间。"""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _maybe_web_search() -> BaseTool | None:
    """有 TAVILY_API_KEY 就把 Tavily 搜索作为工具暴露，否则跳过。

    延迟 import，避免没装 langchain-tavily 时启动失败。
    """
    if not os.getenv("TAVILY_API_KEY"):
        return None
    try:
        from langchain_tavily import TavilySearch  # 新版包名
    except ImportError:
        try:
            from langchain_community.tools import TavilySearchResults as TavilySearch  # 旧回退
        except ImportError:
            return None
    return TavilySearch(
        max_results=5,
        name="web_search",
        description=(
            "联网搜索最新信息。适合处理超出模型知识截止日期的问题、"
            "需要实时数据（新闻、天气、股价、赛事结果）或需要引用外部页面的场景。"
            "输入是简明的中文/英文关键词。"
        ),
    )


def build_tools() -> List[BaseTool]:
    """收集当前可用的工具列表；调用时机是 agent 构建的一次性初始化。"""
    tools: List[BaseTool] = [get_current_time]
    ws = _maybe_web_search()
    if ws is not None:
        tools.append(ws)
    return tools
