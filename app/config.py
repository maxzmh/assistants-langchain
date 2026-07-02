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


def get_llm(**kwargs) -> ChatOpenAI:
    """返回配置好的 Doubao-Seed-2.1-pro 聊天模型实例。"""
    return ChatOpenAI(
        model=os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628"),
        api_key=os.getenv("ARK_API_KEY"),
        base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        temperature=kwargs.pop("temperature", 0.7),
        **kwargs,
    )
