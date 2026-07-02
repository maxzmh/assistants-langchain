"""
能调用 Tavily 联网搜索的 ReAct Agent（带短期记忆 + 流式输出）。

实现要点：
- 工具：langchain_tavily.TavilySearch，封装 Tavily 联网搜索，需要 TAVILY_API_KEY。
- Agent：用 LangGraph 的 create_react_agent 构建 ReAct 智能体，模型自行决定
  何时调用搜索工具、何时直接回答（豆包模型支持 function calling）。
- 短期记忆：MemorySaver 按 thread_id 在内存中保存对话历史（重启即清空）。
- 流式输出：astream_events / stream，逐 token 打印模型回复。

运行方式：
    .venv/bin/python agent.py
（运行前请在 .env 中填好 TAVILY_API_KEY）
"""
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from config import get_llm

load_dotenv()


def build_agent():
    """构建带 Tavily 工具、短期记忆的 ReAct Agent。"""
    if not os.getenv("TAVILY_API_KEY"):
        raise RuntimeError(
            "未检测到 TAVILY_API_KEY，请先在 .env 中填入 Tavily 的 API Key"
            "（https://tavily.com 免费注册获取）。"
        )

    # max_results 控制每次搜索返回的网页条数
    search = TavilySearch(max_results=5)
    tools = [search]

    llm = get_llm()

    # MemorySaver：进程内的短期记忆，按 thread_id 区分不同会话
    checkpointer = MemorySaver()

    return create_react_agent(
        llm,
        tools,
        prompt=(
            "你是一位资深美食家助手。当用户的问题涉及实时信息、最新资讯、"
            "具体店铺/价格/新闻等你不确定的内容时，调用搜索工具联网查证后再回答；"
            "属于通用烹饪常识的问题可以直接回答。回答用中文，简洁亲切。"
        ),
        checkpointer=checkpointer,
    )


def main() -> None:
    agent = build_agent()
    thread_id = "default"  # 换不同 id 即可隔离多个会话
    config = {"configurable": {"thread_id": thread_id}}

    print("Tavily 联网 Agent 已启动（输入 exit / quit 退出）\n")

    while True:
        try:
            user_input = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("再见！")
            break

        print("助手> ", end="", flush=True)
        # 以 messages 模式流式输出：只打印 LLM 生成的文本增量，
        # 工具调用过程则提示一行，让用户知道 Agent 正在联网搜索。
        for token, meta in agent.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config=config,
            stream_mode="messages",
        ):
            # 工具消息（搜索结果）不直接打印，仅在发起搜索时给个提示
            if meta.get("langgraph_node") == "tools":
                continue
            if getattr(token, "tool_calls", None):
                print("\n[🔍 正在联网搜索…]\n助手> ", end="", flush=True)
            if token.content:
                print(token.content, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    main()
