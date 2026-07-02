"""聊天系统提示词。

从项目根 system_prompt.txt 读取；文件缺失或读失败时使用内置默认值。
改口吻 / 角色：编辑 system_prompt.txt 后重启服务生效。
"""
from pathlib import Path

_DEFAULT_PROMPT = (
    "你是一个乐于助人的智能助手。请用清晰、友好的中文回答用户的问题。"
    "如果用户上传了图片，请结合图片内容作答。"
)


def _load() -> str:
    try:
        text = Path("system_prompt.txt").read_text(encoding="utf-8").strip()
        return text or _DEFAULT_PROMPT
    except OSError:
        return _DEFAULT_PROMPT


SYSTEM_PROMPT: str = _load()
