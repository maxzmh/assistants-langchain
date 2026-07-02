"""
LangChain + Doubao-Seed-2.1-pro 配置模块

豆包（Doubao）模型部署在火山引擎 Ark 平台上，Ark 提供 OpenAI 兼容接口，
因此使用 langchain-openai 的 ChatOpenAI，并指向 Ark 的 base_url 即可。
"""
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# 加载 .env 中的环境变量
load_dotenv()

def get_llm(**kwargs) -> ChatOpenAI:
    """返回配置好的 Doubao-Seed-2.1-pro 聊天模型实例。

    额外参数（如 temperature、max_tokens 等）通过 kwargs 透传给 ChatOpenAI。
    """
    return ChatOpenAI(
        model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
        api_key=os.getenv("ARK_API_KEY"),
        base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        temperature=kwargs.pop("temperature", 0.7),
        **kwargs,
    )
